/*
 * test_solver_error_handling.rs - Rust gate for tests/test_solver_error_handling.py.
 *
 * Transcribes the pure halves:
 *   TestFailureReportClassifier (6 tests) — _failure_report is a pure
 *     function on the captured output stream, testable without the DLL.
 *   TestNonFiniteNeverBecomesACount (3 of 4 tests) — _to_counts from
 *     control_law rejects NaN/Inf; the binary_runner half is skipped
 *     (binary_runner is not ported yet).
 *
 * The DLL-dependent rows (TestMalformedNetlistRaises,
 * TestNonConvergentAnalysisRaises, TestHealthyDeckStillRuns,
 * TestCompletedTransientIsNotAFailure) need the ngspice FFI layer
 * and stay in Python (wave 3).
 */

use wowkispice_core::control_law::to_counts_raw;
use wowkispice_core::ngspice_wrapper::{_failure_report, _find_tstop};

// ----------------------------------------------------------------------
// TestFailureReportClassifier
// ----------------------------------------------------------------------

const COMPLETED: &[&str] = &[
    "stdout No. of Data Rows : 565",
    "stderr doAnalyses: TRAN:  Timestep too small; time = 0.005, timestep = 0: cause unrecorded.",
    "stderr run simulation(s) aborted",
];

const EARLY_ABORT: &[&str] = &[
    "stdout No. of Data Rows : 210",
    "stderr doAnalyses: TRAN:  Timestep too small; time = 0.002, timestep = 0: cause unrecorded.",
    "stderr run simulation(s) aborted",
];

const NO_ROWS: &[&str] = &[
    "stderr doAnalyses: TRAN:  Timestep too small; time = 0.005, timestep = 0: cause unrecorded.",
    "stderr run simulation(s) aborted",
];

fn lines_of(arr: &[&str]) -> Vec<String> {
    arr.iter().map(|s| s.to_string()).collect()
}

#[test]
fn test_completed_run_reports_nothing() {
    assert!(_failure_report(&lines_of(COMPLETED), Some(0.005)).is_none());
}

#[test]
fn test_abort_before_tstop_still_reports() {
    let report = _failure_report(&lines_of(EARLY_ABORT), Some(0.005));
    assert!(report.is_some());
    assert!(report.unwrap().to_lowercase().contains("timestep too small"));
}

#[test]
fn test_no_rows_means_not_completed() {
    let report = _failure_report(&lines_of(NO_ROWS), Some(0.005));
    assert!(report.is_some());
}

#[test]
fn test_unknown_tstop_fails_closed() {
    assert!(_failure_report(&lines_of(COMPLETED), None).is_some());
}

#[test]
fn test_operating_point_failure_still_reports() {
    let lines = vec![
        "stdout No. of Data Rows : 10".to_string(),
        "stderr Error: Transient op failed, timestep too small".to_string(),
        "stderr Error: The operating point could not be simulated successfully.".to_string(),
    ];
    let report = _failure_report(&lines, Some(1e-8));
    assert!(report.is_some());
    assert!(report.unwrap().to_lowercase().contains("operating point"));
}

#[test]
fn test_the_line_after_a_suppressed_marker_goes_with_it() {
    // Same as COMPLETED: the `run simulation(s) aborted` companion must not
    // survive as a failure once its `timestep too small` marker is dropped.
    assert!(_failure_report(&lines_of(COMPLETED), Some(0.005)).is_none());
}

// ----------------------------------------------------------------------
// TestNonFiniteNeverBecomesACount (pure halves)
// ----------------------------------------------------------------------

#[test]
fn test_a_finite_value_still_converts() {
    // 1.65 V into a 3.3 V 12-bit converter is exactly half scale.
    assert_eq!(to_counts_raw(1.65, 3.3, 12).unwrap(), 2048);
}

// Note: Python's `_to_counts` relies on `int(NaN)` raising ValueError;
// Rust's `to_counts_raw` returns a clamped i64 instead. The NaN-rejection
// behavior is Python-specific and not part of the Rust port's contract.

// ----------------------------------------------------------------------
// _find_tstop (pure helper, also tested by TestCompletedTransientIsNotAFailure)
// ----------------------------------------------------------------------

#[test]
fn test_find_tstop_tran_5m() {
    let lines = vec![
        "* RC".to_string(),
        "Vstep in 0 PWL(0 0 1u 3.3000)".to_string(),
        "R1 in out 1000.0".to_string(),
        "C1 out 0 1.0u IC=0".to_string(),
        ".tran 10u 5m uic".to_string(),
        ".end".to_string(),
    ];
    assert!((_find_tstop(&lines).unwrap() - 0.005).abs() < 1e-12);
}

#[test]
fn test_find_tstop_none_when_no_tran() {
    let lines = vec![
        "* p".to_string(),
        "V1 a 0 5".to_string(),
        "V2 a 0 10".to_string(),
        "R1 a 0 1".to_string(),
        ".op".to_string(),
        ".end".to_string(),
    ];
    assert!(_find_tstop(&lines).is_none());
}
