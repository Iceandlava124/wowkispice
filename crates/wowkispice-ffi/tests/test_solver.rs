/*
 * test_solver.rs - Rust gate for tests/test_solver_error_handling.py.
 *
 * End-to-end smoke test using wowkispice-ffi::NgSpiceFfi (the real DLL),
 * mirroring how the Python tests use bridge.ngspice_wrapper.NgSpiceEngine.
 *
 * Note: ngspice maintains global C state. Only one full simulation should
 * run per process to avoid heap corruption from ngspice's internal memory
 * management.
 */

use wowkispice_ffi::NgSpiceFfi;

const COMPLETED_TRAN: &[&str] = &[
    "* RC",
    "Vstep in 0 PWL(0 0 1u 3.3000)",
    "R1 in out 1000.0",
    "C1 out 0 1.0u IC=0",
    ".tran 10u 5m uic",
    ".end",
];

#[test]
fn test_rc_transient_does_not_raise() {
    let mut engine = NgSpiceFfi::new().expect("ngspice DLL should load");
    engine.init(None, None, None, None).expect("ngSpice_Init should succeed");

    engine
        .load_circuit(COMPLETED_TRAN)
        .expect("completed tran deck should load");
    engine.cmd("run").expect("completed transient run should succeed");

    let time = engine
        .get_vector_array("time")
        .expect("get_vector_array('time') should succeed");
    let v = engine
        .get_vector_array("v(out)")
        .expect("get_vector_array('v(out)') should succeed");

    assert!(
        time.len() > 100,
        "completed run should have >100 time points, got {}",
        time.len()
    );
    assert!(
        (time.last().copied().unwrap_or(0.0) - 0.005).abs() < 1e-9,
        "transient should reach 5ms stop time, got {:?}",
        time.last()
    );
    assert!(
        v.iter().all(|&v| v.is_finite()),
        "completed data must be finite"
    );
}
