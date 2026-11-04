/*
 * load_stepper.rs - port of bridge/load_stepper.py.
 *
 * Configurable load-step injection for mid-simulation testing: during a
 * solve, every timestep asks the stepper whether one of its declared steps
 * has come due; the first due step is applied by sending ngspice an `alter`
 * command that changes the load resistor's value, and it is never applied
 * twice.
 *
 * PARITY CONTRACT
 *
 *   tests/test_load_step_injection.py   the pure-logic parts:
 *     - test_load_stepper_creation (create_load_step_profile)
 *     - the create_load_step_profile() prefix of
 *       test_load_step_injection_in_cosim (the rest of that test builds a
 *       schematic and runs cosim_runner.run_cosim, which needs the live
 *       ngspice solver and is OUT OF SCOPE here)
 *     - tests/test_binary_runner.py::TestProgressAndLoadStepping needs a
 *       full solve through _run_with_fake_monitor and is likewise out of
 *       scope; it only drives the check_and_apply() *interface* through a
 *       double, which the RUST-ONLY ADDITION tests below cover directly.
 *
 * crates/parity/src/bin/parity_load_stepper.rs and
 * crates/parity/python/load_stepper/parity_load_stepper.rs cross-check both
 * implementations over a shared battery (unsorted step tables, one-step-per-
 * call sequencing, unit-suffix command forms, engine failures and retries).
 *
 * WHAT IS NOT PORTED, AND WHY IT IS NOT A BUG
 *
 *   1. Anything that spawns the solver or the cosim CLI is out of scope
 *      (see above).  The engine here is the LoadEngine trait: Python takes
 *      any object with .cmd(cmd), and any exception it raises is caught,
 *      printed as `Load step failed: {e}` and reported as False.  The trait
 *      returns Result<(), String> for exactly that path; the message is
 *      printed verbatim, to stdout, like Python's print().
 *   2. Python's steps are dicts, so `step['time_s']` can raise KeyError
 *      *outside* the try (it propagates) and `unit` can be a non-string
 *      (TypeError at `unit[0]`).  The port types steps as LoadStep - the
 *      shape create_load_step_profile() always produces - so those failure
 *      modes are unreachable by construction.  The one formatting failure
 *      that IS reachable with well-typed data - an empty non-"ohm" unit
 *      string, where Python raises IndexError at `unit[0]` inside the try -
 *      is reproduced verbatim, message and all (probe: CPython 3.12 str =
 *      "string index out of range"), including the fact that the step is
 *      NOT marked applied, so it retries and prints again next call.
 *   3. Python formats `value` with str(): an int-typed hand-written step
 *      renders "5" while a float renders "5.0".  The port types value as
 *      f64, matching create_load_step_profile (always float * float); a
 *      hand-written int step would render "5.0" here vs "5" there.  Not in
 *      the contract; the battery uses profile-built and float steps.
 *   4. `import time` at the top of the Python module is unused and is not
 *      ported.  `sorted()` is a stable sort in Python; Rust's sort_by is
 *      stable too, so equal time_s values keep insertion order on both
 *      sides (the battery includes a tie).
 */

use crate::pycompat::py_repr;
use std::collections::BTreeSet;

/// One declared load step, i.e. one entry of the Python `steps` list:
/// `{'time_s': float, 'value': float, 'unit': 'ohm'}`.
#[derive(Debug, Clone, PartialEq)]
pub struct LoadStep {
    pub time_s: f64,
    pub value: f64,
    pub unit: String,
}

impl LoadStep {
    pub fn new(time_s: f64, value: f64, unit: &str) -> Self {
        LoadStep { time_s, value, unit: unit.to_string() }
    }

    /// The profile form: unit is always 'ohm'.
    pub fn ohm(time_s: f64, value: f64) -> Self {
        LoadStep::new(time_s, value, "ohm")
    }
}

/// Python: any object with `.cmd(cmd)`; a raised exception becomes an Err
/// carrying `str(e)`, which check_and_apply prints verbatim.
pub trait LoadEngine {
    fn cmd(&mut self, cmd: &str) -> Result<(), String>;
}

/// Dynamically step load resistor values during simulation.
pub struct LoadStepper<E: LoadEngine> {
    engine: E,
    load_component: String,
    steps: Vec<LoadStep>,
    /// Python: a plain set of applied indices; BTreeSet keeps the same
    /// membership semantics with sorted iteration for free.
    applied: BTreeSet<usize>,
}

impl<E: LoadEngine> LoadStepper<E> {
    /// `steps` is sorted by time_s here, exactly as Python's
    /// `sorted(steps, key=lambda x: x['time_s'])` (stable on both sides).
    pub fn new(engine: E, load_component: &str, steps: Vec<LoadStep>) -> Self {
        let mut steps = steps;
        steps.sort_by(|a, b| {
            a.time_s
                .partial_cmp(&b.time_s)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        LoadStepper {
            engine,
            load_component: load_component.to_string(),
            steps,
            applied: BTreeSet::new(),
        }
    }

    /// The sorted step table (Python: `stepper.steps`).
    pub fn steps(&self) -> &[LoadStep] {
        &self.steps
    }

    /// Applied step indices (Python: `stepper.applied`).
    pub fn applied(&self) -> &BTreeSet<usize> {
        &self.applied
    }

    pub fn load_component(&self) -> &str {
        &self.load_component
    }

    pub fn engine(&self) -> &E {
        &self.engine
    }

    /// Check if any load steps should be applied at current time.
    ///
    /// Only the FIRST due step is applied per call (Python returns from
    /// inside the loop), and a failure leaves it unapplied so the next call
    /// retries it - printing the failure again.
    pub fn check_and_apply(&mut self, current_time_s: f64) -> bool {
        for i in 0..self.steps.len() {
            if self.applied.contains(&i) {
                continue;
            }
            if current_time_s >= self.steps[i].time_s {
                // Python wraps BOTH the alter-command formatting and the
                // engine call in one try/except, so both failures print
                // `Load step failed: {e}` and return False without marking
                // the step applied.
                let step = &self.steps[i];
                let cmd = match build_alter_cmd(&self.load_component, step) {
                    Ok(cmd) => cmd,
                    Err(e) => {
                        println!("Load step failed: {}", e);
                        return false;
                    }
                };
                if let Err(e) = self.engine.cmd(&cmd) {
                    println!("Load step failed: {}", e);
                    return false;
                }
                self.applied.insert(i);
                return true;
            }
        }
        false
    }
}

/// The `alter` command Python builds at bridge/load_stepper.py:33:
/// `f"alter {self.load_component} {value}{unit[0] if unit != 'ohm' else ''}"`.
///
/// `value` goes through Python's str(float), i.e. repr - py_repr.
fn build_alter_cmd(component: &str, step: &LoadStep) -> Result<String, String> {
    // Python: unit = step.get('unit', 'ohm'); the profile always sets it.
    let unit = step.unit.as_str();
    let suffix = if unit != "ohm" {
        // Python `unit[0]`: IndexError on an empty string, caught by the
        // caller's try/except and printed as its str(e).  Probed from
        // CPython 3.12: str(IndexError('string index out of range')).
        match unit.chars().next() {
            Some(c) => c.to_string(),
            None => return Err("string index out of range".to_string()),
        }
    } else {
        String::new()
    };
    Ok(format!("alter {} {}{}", component, py_repr(step.value), suffix))
}

/// Create a load step profile: `zip()` truncates to the shorter list,
/// exactly as Python does.
pub fn create_load_step_profile(
    base_load_ohm: f64,
    step_times_s: &[f64],
    step_multipliers: &[f64],
) -> Vec<LoadStep> {
    step_times_s
        .iter()
        .zip(step_multipliers.iter())
        .map(|(&t, &mult)| LoadStep::ohm(t, base_load_ohm * mult))
        .collect()
}
