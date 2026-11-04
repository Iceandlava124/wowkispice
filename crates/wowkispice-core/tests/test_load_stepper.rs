/*
 * test_load_stepper.rs - port of tests/test_load_step_injection.py.
 *
 * Only the pure-logic parts of the Python file are ported: the cosim test
 * builds a schematic and runs the live solver, which is out of scope (see
 * the header of src/load_stepper.rs).  Tests the Python file does not have
 * are labelled `// RUST-ONLY ADDITION`.
 */

use wowkispice_core::load_stepper::{create_load_step_profile, LoadEngine, LoadStepper, LoadStep};

#[test]
fn test_load_stepper_creation() {
    let steps = create_load_step_profile(10.0, &[0.001, 0.002], &[1.5, 0.5]);
    assert_eq!(steps.len(), 2);
    assert_eq!(steps[0].value, 15.0);
    assert_eq!(steps[1].value, 5.0);
}

// The pure prefix of tests/test_load_step_injection.py::
// test_load_step_injection_in_cosim: the profile it builds before handing
// everything to cosim_runner.run_cosim (which needs the live solver and is
// OUT OF SCOPE here).  The Python test never asserts on these values; the
// assertions below are the obvious facts about them - labelled accordingly.
#[test]
fn test_cosim_test_profile_prefix() {
    let steps = create_load_step_profile(10.0, &[0.001], &[0.5]);
    // RUST-ONLY ADDITION (assertion strength the Python test lacks)
    assert_eq!(steps.len(), 1);
    assert_eq!(steps[0].time_s, 0.001);
    assert_eq!(steps[0].value, 5.0);
    assert_eq!(steps[0].unit, "ohm");
}

// ---------------------------------------------------------------- helpers

/// Records every command the stepper sends; can fail on demand, like the
/// Python test doubles for the ngspice engine.
struct FakeEngine {
    cmds: Vec<String>,
    fail_times: Vec<usize>, // 0-based indices of cmds that must raise
}

impl FakeEngine {
    fn new() -> Self {
        FakeEngine { cmds: Vec::new(), fail_times: Vec::new() }
    }

    fn failing(mut self, first_n: usize) -> Self {
        self.fail_times = (0..first_n).collect();
        self
    }
}

impl LoadEngine for FakeEngine {
    fn cmd(&mut self, cmd: &str) -> Result<(), String> {
        let idx = self.cmds.len();
        self.cmds.push(cmd.to_string());
        if self.fail_times.contains(&idx) {
            return Err("alter denied".to_string());
        }
        Ok(())
    }
}

// RUST-ONLY ADDITION: check_and_apply has no direct Python test (the
// Python tests only build profiles or run a full solve), so the sequencing
// contract is pinned here from the source: one step per call, applied
// exactly once, nothing applied before its time.
#[test]
fn test_steps_apply_one_per_call_in_time_order() {
    let engine = FakeEngine::new();
    let mut st = LoadStepper::new(
        engine,
        "Rload",
        vec![
            LoadStep::ohm(0.002, 5.0),
            LoadStep::ohm(0.001, 15.0),
        ],
    );
    // Construction sorts by time_s, like Python's sorted().
    assert_eq!(st.steps()[0].time_s, 0.001);
    assert_eq!(st.steps()[1].time_s, 0.002);

    assert!(!st.check_and_apply(0.0)); // nothing due yet
    assert!(st.engine().cmds.is_empty());

    assert!(st.check_and_apply(0.001)); // first due step
    assert_eq!(st.engine().cmds, vec!["alter Rload 15.0".to_string()]);

    // Second call at the same time: step 0 is applied, step 1 not due.
    assert!(!st.check_and_apply(0.001));
    assert_eq!(st.engine().cmds.len(), 1);

    assert!(st.check_and_apply(0.002));
    assert_eq!(
        st.engine().cmds,
        vec!["alter Rload 15.0".to_string(), "alter Rload 5.0".to_string()]
    );
    assert!(!st.check_and_apply(0.005)); // all applied
    assert_eq!(st.engine().cmds.len(), 2);
    let applied: Vec<usize> = st.applied().iter().copied().collect();
    assert_eq!(applied, vec![0, 1]);
}

// RUST-ONLY ADDITION: the `alter` command form - unit suffix rules from
// bridge/load_stepper.py:33, value through Python's str(float).
#[test]
fn test_alter_command_form() {
    // unit 'ohm' -> no suffix; value str() is repr(float) -> "5.0".
    let engine = FakeEngine::new();
    let mut st = LoadStepper::new(
        engine,
        "RL",
        vec![LoadStep::new(0.0, 5.0, "ohm")],
    );
    assert!(st.check_and_apply(0.0));
    assert_eq!(st.engine().cmds, vec!["alter RL 5.0".to_string()]);

    // Non-'ohm' unit -> its FIRST character is appended ("5.0k"), exactly
    // as Python's `unit[0] if unit != 'ohm' else ''`.
    let engine = FakeEngine::new();
    let mut st = LoadStepper::new(
        engine,
        "Rr",
        vec![LoadStep::new(0.0, 4700.0, "k")],
    );
    assert!(st.check_and_apply(0.0));
    assert_eq!(st.engine().cmds, vec!["alter Rr 4700.0k".to_string()]);

    // The unit test is case-sensitive in Python: "Ohm" is not "ohm".
    let engine = FakeEngine::new();
    let mut st = LoadStepper::new(
        engine,
        "Rx",
        vec![LoadStep::new(0.0, 5.0, "Ohm")],
    );
    assert!(st.check_and_apply(0.0));
    assert_eq!(st.engine().cmds, vec!["alter Rx 5.0O".to_string()]);
}

// RUST-ONLY ADDITION: an engine exception is printed verbatim as Python's
// `print(f"Load step failed: {e}")`, reported as False, and the step is NOT
// marked applied - the next call retries it (printing again) and succeeds
// once the engine recovers.
#[test]
fn test_engine_failure_prints_and_retries() {
    let engine = FakeEngine::new().failing(1);
    let mut st = LoadStepper::new(engine, "RL", vec![LoadStep::ohm(0.0, 4700.0)]);
    // First call fails: `Load step failed: alter denied` is printed to
    // stdout (asserted verbatim by the parity battery, which captures it).
    assert!(!st.check_and_apply(0.0));
    assert!(st.applied().is_empty());
    assert_eq!(st.engine().cmds.len(), 1);

    // Retry succeeds and marks the step applied.
    assert!(st.check_and_apply(0.1));
    assert_eq!(st.applied().iter().copied().collect::<Vec<_>>(), vec![0]);
    assert_eq!(st.engine().cmds.len(), 2);
}

// RUST-ONLY ADDITION: the empty non-'ohm' unit reproduces Python's
// IndexError at `unit[0]` - message probed from CPython 3.12 - with no
// command sent and no step applied (it would retry and print again).
#[test]
fn test_empty_unit_fails_like_pythons_indexerror() {
    let engine = FakeEngine::new();
    let mut st = LoadStepper::new(engine, "R1", vec![LoadStep::new(0.0, 5.0, "")]);
    // `Load step failed: string index out of range` is printed to stdout.
    assert!(!st.check_and_apply(0.0));
    assert!(st.engine().cmds.is_empty(), "no alter must reach the engine");
    assert!(st.applied().is_empty());
    // ...and it is retried (and prints again) on the next call.
    assert!(!st.check_and_apply(0.1));
    assert!(st.engine().cmds.is_empty());
}

// RUST-ONLY ADDITION: equal time_s keeps insertion order (Python's sorted()
// is stable; Rust's sort_by is stable too).
#[test]
fn test_equal_times_keep_insertion_order() {
    let engine = FakeEngine::new();
    let mut st = LoadStepper::new(
        engine,
        "Rload",
        vec![
            LoadStep::ohm(0.001, 1.0),
            LoadStep::ohm(0.001, 2.0),
            LoadStep::ohm(0.001, 3.0),
        ],
    );
    assert!(st.check_and_apply(0.001));
    assert!(st.check_and_apply(0.001));
    assert!(st.check_and_apply(0.001));
    assert!(!st.check_and_apply(0.001));
    assert_eq!(
        st.engine().cmds,
        vec![
            "alter Rload 1.0".to_string(),
            "alter Rload 2.0".to_string(),
            "alter Rload 3.0".to_string(),
        ]
    );
}

// RUST-ONLY ADDITION: zip() truncation of create_load_step_profile, from
// Python's own zip semantics (the Python test only uses equal lengths).
#[test]
fn test_profile_zip_truncates_to_the_shorter_list() {
    let steps = create_load_step_profile(10.0, &[1.0, 2.0, 3.0], &[2.0]);
    assert_eq!(steps.len(), 1);
    assert_eq!(steps[0].time_s, 1.0);
    assert_eq!(steps[0].value, 20.0);
    assert_eq!(steps[0].unit, "ohm");

    assert!(create_load_step_profile(10.0, &[], &[1.0, 2.0]).is_empty());
    assert!(create_load_step_profile(10.0, &[1.0], &[]).is_empty());
}
