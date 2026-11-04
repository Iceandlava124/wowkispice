/*
 * test_netlist.rs - port of tests/test_ngspice_sanitiser.py.
 *
 * Line-for-line transcription of the Python assertions; tests the Python
 * file cannot have in Rust are labelled as explained in place:
 *
 *   - test_engine_load_rejects_it_and_marker_never_appears needs the real
 *     NgSpiceEngine (ctypes + ngspice.dll); that assertion STAYS in the
 *     Python suite.  The Rust port keeps the two observables that are still
 *     checkable without the DLL: load_circuit's domestic phase (sanitise_deck)
 *     must reject the deck, and the S3B marker file must never appear (the
 *     deck is refused before anything reaches ngspice — which is the
 *     regression the marker assertion exists to catch).
 *
 * The foreign-cwd test runs the same generated Python script the Python
 * test runs — Python is the second side of the contract, so it runs Python.
 */

use std::fs;
use std::path::Path;
use std::process::Command;

use wowkispice_core::netlist::{
    allowed_include_dirs, expanduser_tilde, find_tstop, project_root, py_realpath, sanitise_deck,
    sanitise_line, validate_cmd, SanitisedDeck,
};

// The Python suite calls NgSpiceEngine._sanitise_line; errors surface as
// RuntimeError with a message — here the message IS the exception string.
fn expect_err(line: &str) -> String {
    let exc = sanitise_line(line).expect_err(&format!("expected rejection: {:?}", line));
    exc.msg().to_string()
}

fn expect_err_cmd(command: &str) -> String {
    match validate_cmd(command) {
        Err(exc) => exc.msg().to_string(),
        Ok(_) => panic!("expected rejection: {:?}", command),
    }
}

// ------------------------------------------------------------- hygiene
// Port of TestIncludedFileContent's setUp/tearDown: temp libs are written
// into circuits/components with the same prefix, always removed again, and
// nothing with the prefix may survive in the repo dir (belt assertion).

const TMP_PREFIX: &str = "__tmp_s3b_scan_";
const MARKER_NAME: &str = "wosp_s3b_marker.txt";

struct S3B {
    created: Vec<String>,
    /// Python's unittest runs serially; cargo runs in parallel.  The belt
    /// assertion ("nothing with the prefix survives") must observe a
    /// SETTLED repo dir, so every S3B test holds this lock from fixture
    /// creation until cleanup completes — serialization, not a weakening.
    _lock: std::sync::MutexGuard<'static, ()>,
}

static S3B_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

impl S3B {
    fn new() -> Self {
        S3B {
            created: Vec::new(),
            _lock: S3B_LOCK.lock().unwrap_or_else(|e| e.into_inner()),
        }
    }

    fn lib(&self, name: &str) -> String {
        format!(
            "{}{}circuits{}components{}{}{}.lib",
            project_root(),
            std::path::MAIN_SEPARATOR_STR,
            std::path::MAIN_SEPARATOR_STR,
            std::path::MAIN_SEPARATOR_STR,
            TMP_PREFIX,
            name
        )
    }

    fn write(&mut self, name: &str, content: &str) -> String {
        let path = self.lib(name);
        fs::write(&path, content).expect("write temp lib");
        self.created.push(path.clone());
        path
    }

    /// tearDown minus the marker file (which, if the sanitiser ever regressed,
    /// would have been created by ngspice itself and is checked by the tests,
    /// not deleted).
    fn check_and_clear(&mut self, marker: &str) {
        for path in &self.created {
            if Path::new(path).exists() {
                fs::remove_file(path).expect("remove temp lib");
            }
        }
        self.created.clear();
        // belt: nothing from this class may survive in the repo dir
        let dir = self
            .lib("x")
            .rsplit_once(std::path::MAIN_SEPARATOR_STR)
            .map(|(d, _)| d.to_string())
            .unwrap();
        let leftovers: Vec<String> = fs::read_dir(&dir)
            .unwrap()
            .filter_map(|e| e.ok())
            .map(|e| e.path().to_string_lossy().into_owned())
            .filter(|p| {
                Path::new(p)
                    .file_name()
                    .and_then(|f| f.to_str())
                    .map(|f| f.starts_with(TMP_PREFIX))
                    .unwrap_or(false)
            })
            .collect();
        assert!(leftovers.is_empty(), "temp libs not cleaned up: {leftovers:?}");
        // (marker cleanup like the Python setUp: state begins absent)
        if Path::new(marker).exists() {
            fs::remove_file(marker).expect("remove marker");
        }
    }
}

fn marker_path() -> String {
    format!(
        "{}{}{}",
        std::env::temp_dir().to_string_lossy(),
        std::path::MAIN_SEPARATOR_STR,
        MARKER_NAME
    )
}

// ---------------------------------------------------------------------
// class TestNgspiceSanitiser
// ---------------------------------------------------------------------
// "Sanitiser tests for untrusted netlist input."

#[test]
fn test_control_banned() {
    // ".control should be rejected"
    let msg = expect_err(".control");
    assert!(msg.contains(".control"));
}

#[test]
fn test_endc_banned() {
    // ".endc should be rejected"
    let msg = expect_err(".endc");
    assert!(msg.contains(".endc"));
}

#[test]
fn test_tran_allowed() {
    assert_eq!(sanitise_line(".tran 1n 10n").unwrap(), ".tran 1n 10n");
}

#[test]
fn test_ac_allowed() {
    assert_eq!(
        sanitise_line(".ac dec 5 1k 1MHz").unwrap(),
        ".ac dec 5 1k 1MHz"
    );
}

#[test]
fn test_dc_allowed() {
    assert_eq!(sanitise_line(".dc 0 1 0.1").unwrap(), ".dc 0 1 0.1");
}

#[test]
fn test_op_allowed() {
    assert_eq!(sanitise_line(".op").unwrap(), ".op");
}

#[test]
fn test_model_allowed() {
    assert_eq!(
        sanitise_line(".model mymosfet MOSFET").unwrap(),
        ".model mymosfet MOSFET"
    );
}

#[test]
fn test_measure_allowed() {
    assert_eq!(
        sanitise_line(".measure dc V(node)").unwrap(),
        ".measure dc V(node)"
    );
}

#[test]
fn test_run_allowed() {
    assert_eq!(sanitise_line("run").unwrap(), "run");
}

#[test]
fn test_alter_allowed() {
    assert_eq!(sanitise_line("alter V1 = 5.0").unwrap(), "alter V1 = 5.0");
}

#[test]
fn test_bg_run_allowed() {
    assert_eq!(sanitise_line("bg_run").unwrap(), "bg_run");
}

#[test]
fn test_destroy_allowed() {
    assert_eq!(sanitise_line("destroy").unwrap(), "destroy");
}

#[test]
fn test_unknown_directive_passes() {
    // Unknown directives that are not .control/.endc pass through
    // (they're not in the allowlist but not explicitly banned either; the
    // netlist fails at ngSpice_Circ load time, not at sanitise time).
    assert_eq!(sanitise_line(".foo").unwrap(), ".foo");
}

#[test]
fn test_control_with_whitespace_banned() {
    // ".control with leading space should still be banned"
    let msg = expect_err("  .control");
    assert!(msg.contains(".control"));
}

#[test]
fn test_alter_with_equation() {
    assert_eq!(sanitise_line("alter V1 = sin(t)").unwrap(), "alter V1 = sin(t)");
}

#[test]
fn test_sanitise_line_preserves_comments() {
    assert_eq!(
        sanitise_line("* This is a comment").unwrap(),
        "* This is a comment"
    );
}

#[test]
fn test_sanitise_line_preserves_blanks() {
    assert_eq!(sanitise_line("").unwrap(), "");
}

#[test]
fn test_cmd_reference_in_netlist_is_rejected() {
    // "cmd() embedded in netlist content must hit the banned-command branch
    // (R3 coverage gap)."
    let msg = expect_err("R1 1 0 cmd(shell echo pwned)");
    assert!(msg.contains("banned command"));
}

#[test]
fn test_double_plus_continuation_cannot_smuggle_control() {
    // "'++ .control' survives the first directive check (still
    // '+'-prefixed after one strip) and must be caught by the re-check
    // after normalisation (R3 coverage gap)."
    let msg = expect_err("++ .control");
    assert!(msg.contains(".control"));
}

// ---------------------------------------------------------------------
// class TestMeasAlias
// ---------------------------------------------------------------------
// ".meas is ngspice's short form of .measure and must not be rejected;
// the editor's own measurement workflow uses it verbatim."

#[test]
fn test_meas_alias_is_allowed() {
    let line = ".meas tran vout_max MAX v(out)";
    assert_eq!(sanitise_line(line).unwrap(), line);
}

#[test]
fn test_meas_alias_is_allowed_case_insensitive() {
    let line = ".MEAS tran vout_min MIN v(out)";
    assert_eq!(sanitise_line(line).unwrap(), line);
}

// ---------------------------------------------------------------------
// class TestIncludeAllowlist
// ---------------------------------------------------------------------

fn s3b_lib() -> String {
    format!(
        "{}{}circuits{}components{}models.lib",
        project_root(),
        std::path::MAIN_SEPARATOR_STR,
        std::path::MAIN_SEPARATOR_STR,
        std::path::MAIN_SEPARATOR_STR
    )
}

fn s3b_allowed() -> String {
    format!(
        "{}{}circuits{}components",
        project_root(),
        std::path::MAIN_SEPARATOR_STR,
        std::path::MAIN_SEPARATOR_STR
    )
}

#[test]
fn test_allowlist_is_exactly_the_known_library_directory() {
    // Default policy check: exactly one directory, nothing else.
    // (realpath on both sides first, as the Python test does.)
    let real: Vec<String> = allowed_include_dirs()
        .iter()
        .map(|d| py_realpath(d))
        .collect();
    let expected = py_realpath(&s3b_allowed());
    assert_eq!(real, vec![expected]);
}

#[test]
fn test_the_listed_library_file_really_exists() {
    // The allowlisted path must be a real file, not a invented one.
    assert!(
        Path::new(&s3b_lib()).is_file(),
        "missing library: {}",
        s3b_lib()
    );
}

#[test]
fn test_include_of_the_listed_library_is_allowed() {
    let line = format!(".include \"{}\"", s3b_lib());
    assert_eq!(sanitise_line(&line).unwrap(), line);
}

#[test]
fn test_include_relative_to_repo_root_is_allowed() {
    // J3c/3b: a repo-relative include is accepted AND rewritten to the
    // validated absolute path (ngspice reads exactly the checked file,
    // whatever the process working directory is).
    let line = ".include circuits/components/models.lib";
    let result = sanitise_line(line).unwrap();
    let expected_abs = py_realpath(&s3b_lib());
    assert_eq!(result, format!(".include {}", expected_abs));
    assert!(result.ends_with(&expected_abs));
}

#[test]
fn test_include_outside_allowed_dirs_is_rejected() {
    let outside = format!(
        "{}\\not_allowed.lib",
        expanduser_tilde().trim_end_matches(['\\', '/'])
    );
    let line = format!(".include \"{}\"", outside);
    let msg = expect_err(&line);
    assert!(msg.contains("outside allowed directories"));
    assert!(msg.contains(&outside));
}

#[test]
fn test_include_traversal_out_of_allowed_dir_is_rejected() {
    // "'..' must collapse before the check, not after it."
    let line = ".include \"circuits/components/../../../secrets.lib\"";
    let msg = expect_err(line);
    assert!(msg.contains("outside allowed directories"));
}

#[test]
fn test_include_without_argument_is_rejected() {
    let msg = expect_err(".include");
    assert!(msg.contains("no file argument"));
}

#[test]
fn test_lib_inside_allowed_dir_is_allowed() {
    let line = format!(".lib \"{}\"", s3b_lib());
    assert_eq!(sanitise_line(&line).unwrap(), line);
}

#[test]
fn test_lib_outside_allowed_dirs_is_rejected() {
    let outside = format!(
        "{}\\not_allowed.lib",
        expanduser_tilde().trim_end_matches(['\\', '/'])
    );
    let line = format!(".lib \"{}\"", outside);
    let msg = expect_err(&line);
    assert!(msg.contains("outside allowed directories"));
}

// ---------------------------------------------------------------------
// class TestIncludedFileContent
// ---------------------------------------------------------------------
// 3b: the sanitiser must inspect the LINES of an included file.

#[test]
fn test_control_block_inside_included_file_is_rejected() {
    let marker = marker_path();
    let mut s3b = S3B::new();
    let lib = s3b.write(
        "control",
        &format!(
            "* tmp lib\n.control\nshell echo PWNED> {}\n.endc\n.model S3B D(IS=1e-12 N=1.0)\n",
            marker
        ),
    );
    let line = format!(".include \"{}\"", lib);
    let msg = expect_err(&line);
    assert!(msg.contains(".control"));
    let basename = Path::new(&lib)
        .file_name()
        .and_then(|f| f.to_str())
        .unwrap()
        .to_string();
    assert!(
        msg.contains(&basename),
        "the error must name the offending file"
    );
    s3b.check_and_clear(&marker);
}

#[test]
fn test_engine_load_rejects_it_and_marker_never_appears() {
    // Full app path, DOMESTIC PHASE ONLY (see the porting note in the file
    // header): sanitise_deck (load_circuit minus the ngSpice_Circ call)
    // must refuse the deck before anything reaches ngspice.  The marker
    // assertion is the observable from the empirical exploit — it proves
    // no code path had the chance to execute the payload.
    let marker = marker_path();
    if Path::new(&marker).exists() {
        fs::remove_file(&marker).expect("remove stale marker");
    }
    let mut s3b = S3B::new();
    let lib = s3b.write(
        "engine",
        &format!(
            "* tmp lib\n.control\nshell echo PWNED> {}\n.endc\n.model S3B D(IS=1e-12 N=1.0)\n",
            marker
        ),
    );
    let deck = vec![
        "* 3b".to_string(),
        format!(".include \"{}\"", lib),
        "V1 in 0 DC 1".to_string(),
        "R1 in out 1k".to_string(),
        ".op".to_string(),
        ".end".to_string(),
    ];
    let lines: Vec<&str> = deck.iter().map(String::as_str).collect();
    let exc = sanitise_deck(&lines)
        .expect_err("engineload must reject a .control payload in an include");
    assert!(exc.msg().contains(".control"));
    assert!(
        !Path::new(&marker).exists(),
        "the .control payload inside the include must never execute"
    );
    s3b.check_and_clear(&marker);
}

#[test]
fn test_nested_include_inside_allowlist_is_allowed() {
    let marker = marker_path();
    let mut s3b = S3B::new();
    let b = s3b.write("nest_b", ".model NESTB D(IS=1e-12 N=1.0)\n");
    let a = s3b.write(
        "nest_a",
        &format!(".include \"{}\"\n.model NESTA D(IS=1e-12 N=1.0)\n", b),
    );
    let line = format!(".include \"{}\"", a);
    assert_eq!(sanitise_line(&line).unwrap(), line);
    s3b.check_and_clear(&marker);
}

#[test]
fn test_self_including_file_hits_the_depth_limit() {
    // A cycle must fail fast with the depth message, not recurse.
    let marker = marker_path();
    let mut s3b = S3B::new();
    let x_path = s3b.lib("cycle");
    s3b.write("cycle", &format!(".include \"{}\"\n", x_path));
    let line = format!(".include \"{}\"", x_path);
    let msg = expect_err(&line);
    assert!(msg.contains("nesting exceeds"));
    s3b.check_and_clear(&marker);
}

#[test]
fn test_missing_file_inside_allowed_dir_is_rejected() {
    let marker = marker_path();
    let mut s3b = S3B::new();
    let missing = s3b.lib("never_written");
    assert!(!Path::new(&missing).exists());
    let line = format!(".include \"{}\"", missing);
    let msg = expect_err(&line);
    assert!(msg.contains("not found"));
    s3b.check_and_clear(&marker);
}

// ---------------------------------------------------------------------
// class TestIncludeCwdIndependence
// ---------------------------------------------------------------------
// 3c: the same include decisions from a different working directory.
// ALLOWED_INCLUDE_DIRS is anchored at PROJECT_ROOT, never at cwd; and the
// validated line is rewritten to an absolute path.  The Python test runs a
// generated script under sys.executable; the port runs the identical script
// under the venv's interpreter.

#[test]
fn test_decisions_are_identical_from_a_foreign_cwd() {
    let root = project_root();
    let root_repr = wowkispice_core::pycompat::py_repr_str(&root);
    let script = format!(
        r#"import os, sys
sys.path.insert(0, {root_repr})
from bridge.ngspice_wrapper import NgSpiceEngine as E
lib = os.path.join(E.PROJECT_ROOT, "circuits", "components", "models.lib")
assert os.path.isfile(lib), "fixture missing"
r = E._sanitise_line(".include " + lib)
assert r == ".include " + os.path.realpath(lib), r
r2 = E._sanitise_line(".include circuits/components/models.lib")
assert r2.endswith(os.path.realpath(lib)), r2
assert os.getcwd() != E.PROJECT_ROOT, "cwd not foreign"
ok = False
try:
    E._sanitise_line('.include "C:\\\\outside_allowed.lib"')
except RuntimeError as e:
    ok = "outside allowed directories" in str(e)
assert ok, "outside include not rejected from foreign cwd"
print("CWD_PROOF", os.getcwd())
print("ROOT_PROOF", E.PROJECT_ROOT)
print("ALL_CHECKS_PASSED")
"#
    );

    let foreign = std::env::temp_dir().join(format!(
        "wosp_foreign_cwd_{}",
        std::process::id()
    ));
    fs::create_dir_all(&foreign).unwrap();

    let python = format!("{}\\.venv\\Scripts\\python.exe", root);
    let output = Command::new(python)
        .arg("-c")
        .arg(&script)
        .current_dir(&foreign)
        .output()
        .expect("spawn python for foreign-cwd check");
    let out = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.status.success(), "{out}");
    assert!(out.contains("ALL_CHECKS_PASSED"), "{out}");
    assert!(out.contains("CWD_PROOF") && out.contains("ROOT_PROOF"), "{out}");
    let foreign_str = foreign.to_string_lossy().into_owned();
    assert!(out.contains(&foreign_str), "cwd proof missing\n{out}");

    fs::remove_dir_all(&foreign).ok();
}

// ---------------------------------------------------------------------
// Ported pure half of tests/test_security_vectors.py TestCommandVectors
// ("Vectors that travel through NgSpiceEngine.cmd()").  Each rejection
// must happen inside validate_cmd before the library call; the `calls == []
// "it never reached ngspice"` half of each claim is engine-FFI evidence and
// STAYS in the Python suite.  No markers here either — markers never touch
// the repository (see _MarkerCase), and in the pure half the payload never
// has anywhere to go.
// ---------------------------------------------------------------------

#[test]
fn test_vector2_shell_command_is_rejected() {
    // "shell echo PWNED> <marker>" — msg names the verb and the allowlist;
    // rejected by validate_cmd("shell ...") on its verb alone.
    let msg = expect_err_cmd("shell echo PWNED> C:\\Users\\gudae\\...\\marker_v2.txt");
    assert!(msg.contains("shell"));
    assert!(msg.contains("allowlist"));
}

#[test]
fn test_vector3_source_command_is_rejected_blind() {
    let msg = expect_err_cmd("source \"C:\\Users\\gudae\\...\\payload_v3.cir\"");
    assert!(msg.contains("source"));
}

#[test]
fn test_vector5_write_cannot_create_a_file() {
    let msg = expect_err_cmd("write \"C:\\Users\\gudae\\...\\payload_v5_out\" v(out)");
    assert!(msg.contains("write"));
}

#[test]
fn test_vector6_wrdata_cannot_create_a_file() {
    let msg = expect_err_cmd("wrdata \"C:\\Users\\gudae\\...\\payload_v6_out\" v(out)");
    assert!(msg.contains("wrdata"));
}

#[test]
fn test_vector7_hardcopy_cannot_create_a_file() {
    let msg = expect_err_cmd("hardcopy \"C:\\Users\\gudae\\...\\payload_v7_out\" v(out)");
    assert!(msg.contains("hardcopy"));
}

#[test]
fn test_command_separators_are_rejected() {
    // A newline or ';' inside one cmd() string can carry a second command
    // past any first-token check.
    for payload in [
        "run\nshell echo PWNED",
        "run; shell echo PWNED",
        "run | shell echo PWNED",
        "run `shell echo PWNED`",
    ] {
        let _msg = expect_err_cmd(payload); // must be rejected
    }
}

#[test]
fn test_legitimate_commands_still_pass_the_guard() {
    // The guard must not break the commands the code actually sends.
    for ok in [
        "run",
        "bg_run",
        "reset",
        "destroy",
        "stop",
        "setplot",
        "setplot tran1",
        "alter v1 = 5.0",
        "alter rload 10k",
        "tran 1u 10m uic",
    ] {
        assert_eq!(validate_cmd(ok).unwrap(), ok.trim());
    }
}

// ---------------------------------------------------------------------
// RUST-ONLY ADDITION: the load_circuit domestic-phase header/end rewrite,
// exercised through sanitise_deck (the Python tests reach it only through
// the DLL-bound engine; the pure phase has no direct Python test to
// transcribe, but its behaviour is pinned here and by the parity harness).
// ---------------------------------------------------------------------

#[test]
fn test_deck_gets_title_and_end_inserted() {
    let lines = vec!["V1 in 0 DC 1", "R1 in out 1k", ".op"];
    let deck: SanitisedDeck = sanitise_deck(&lines).unwrap();
    assert_eq!(deck.lines[0], "* WOWKISPICE circuit");
    assert_eq!(deck.lines.last().unwrap(), ".end");
    assert_eq!(
        deck.lines,
        vec![
            "* WOWKISPICE circuit".to_string(),
            "V1 in 0 DC 1".to_string(),
            "R1 in out 1k".to_string(),
            ".op".to_string(),
            ".end".to_string(),
        ]
    );
}

#[test]
fn test_deck_tstop_from_tran_card() {
    // .tran <tstep> <tstop> ... -> tstop in seconds (SPICE suffix scale)
    let deck: SanitisedDeck = sanitise_deck(&[
        "* deck",
        ".tran 1u 5m uic",
        ".end",
    ])
    .unwrap();
    assert_eq!(deck.tstop, Some(0.005));
}

#[test]
fn test_deck_tstop_none_without_tran() {
    let deck: SanitisedDeck =
        sanitise_deck(&["* deck", ".ac dec 5 1k 1MEG", ".end"]).unwrap();
    assert_eq!(deck.tstop, None);
}

#[test]
fn test_find_tstop_direct() {
    let d = |lines: &[&str]| -> Vec<String> { lines.iter().map(|s| s.to_string()).collect() };
    let got = find_tstop(&d(&["* t", ".tran 0 2m 1k uic", ".end"]));
    assert_eq!(got, Some(0.002));
    let got = find_tstop(&d(&["* t", ".ac dec 10 1 1e5", ".end"]));
    assert_eq!(got, None);
}

#[test]
fn test_deck_rejects_banned_line_with_doubled_prefix() {
    // load_circuit's re-wrap behaviour — verbatim double prefix.
    let lines = ["* d", ".control", "run"];
    let exc = sanitise_deck(&lines)
        .expect_err("deck with .control must be rejected");
    let msg = exc.msg();
    assert!(
        msg.contains("banned directive @line: .control"),
        "msg = {msg:?}"
    );
}
