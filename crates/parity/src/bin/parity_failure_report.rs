/*
 * parity_failure_report.rs - Rust half of the failure-report-parity battery.
 *
 * Computes _failure_report results from
 * crates/wowkispice-core/src/ngspice_wrapper.rs and prints KEY<TAB>VALUE lines
 * for crates/parity/python/parity_failure_report.py to diff against
 * bridge/ngspice_wrapper._failure_report.
 *
 * Battery: the same line sets from test_solver_error_handling.py's
 * TestFailureReportClassifier, computed twice (Python vs Rust).
 */

use std::io::{BufWriter, Write};

use wowkispice_core::ngspice_wrapper::_failure_report;

fn main() {
    let stdout = std::io::stdout();
    let lock = stdout.lock();
    let mut writer = BufWriter::new(lock);

    let mut out: Vec<(String, String)> = Vec::new();

    let completed = vec![
        "stdout No. of Data Rows : 565".to_string(),
        "stderr doAnalyses: TRAN:  Timestep too small; time = 0.005, timestep = 0: cause unrecorded.".to_string(),
        "stderr run simulation(s) aborted".to_string(),
    ];
    let early_abort = vec![
        "stdout No. of Data Rows : 210".to_string(),
        "stderr doAnalyses: TRAN:  Timestep too small; time = 0.002, timestep = 0: cause unrecorded.".to_string(),
        "stderr run simulation(s) aborted".to_string(),
    ];
    let no_rows = vec![
        "stderr doAnalyses: TRAN:  Timestep too small; time = 0.005, timestep = 0: cause unrecorded.".to_string(),
        "stderr run simulation(s) aborted".to_string(),
    ];
    let op_failure = vec![
        "stdout No. of Data Rows : 10".to_string(),
        "stderr Error: Transient op failed, timestep too small".to_string(),
        "stderr Error: The operating point could not be simulated successfully.".to_string(),
    ];

    // completed run with tstop=0.005 -> None (timestep too small at tstop is not a failure)
    out.push((
        "completed_tstop_0005".to_string(),
        match _failure_report(&completed, Some(0.005)) {
            Some(r) => format!("some({})", r),
            None => "none".to_string(),
        },
    ));
    // completed run with tstop=None -> some (no tstop to compare against)
    out.push((
        "completed_tstop_none".to_string(),
        match _failure_report(&completed, None) {
            Some(r) => format!("some({})", r),
            None => "none".to_string(),
        },
    ));
    // early abort before tstop -> some
    out.push((
        "early_abort_tstop_0005".to_string(),
        match _failure_report(&early_abort, Some(0.005)) {
            Some(r) => format!("some({})", r),
            None => "none".to_string(),
        },
    ));
    // no rows -> some
    out.push((
        "no_rows_tstop_0005".to_string(),
        match _failure_report(&no_rows, Some(0.005)) {
            Some(r) => format!("some({})", r),
            None => "none".to_string(),
        },
    ));
    // operating point failure -> some
    out.push((
        "op_failure_tstop_1e-8".to_string(),
        match _failure_report(&op_failure, Some(1e-8)) {
            Some(r) => format!("some({})", r),
            None => "none".to_string(),
        },
    ));
    // companion line check: completed with tstop=0.005 -> none (same as first)
    out.push((
        "completed_companion_tstop_0005".to_string(),
        match _failure_report(&completed, Some(0.005)) {
            Some(r) => format!("some({})", r),
            None => "none".to_string(),
        },
    ));

    for (key, value) in out {
        writeln!(writer, "{}\t{}", key, value).expect("stdout write");
    }
    writer.flush().expect("stdout flush");
}
