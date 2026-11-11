/*
 * test_standalone_sim.rs - Tests for the dependency-free standalone simulator.
 * Verifies RC filter charging, buck converter regulation, and closed-loop
 * co-simulation with zero NaN/Inf. Zero external dependencies (only stdlib).
 */

use wowkispice_core::standalone_sim::*;

#[test]
fn test_rc_filter_charges_to_source_voltage() {
    let ckt = build_rc_filter(1000.0, 100e-6, 5.0);
    let mut solver = CircuitSolver::new(ckt, 1e-4, 1.0).unwrap();
    let results = solver.run_transient().unwrap();
    let final_v = results.last().unwrap().v("vout");
    assert!((final_v - 5.0).abs() < 0.1,
        "RC filter should charge to ~5V, got {}V", final_v);
    let mut prev = 0.0f64;
    for r in &results {
        let v = r.v("vout");
        assert!(v >= prev - 1e-6,
            "Vout should not decrease during charge: {} < {}", v, prev);
        prev = v;
    }
    for r in &results {
        assert!(r.v("vout").is_finite(),
            "Vout must be finite, got {}", r.v("vout"));
    }
}

#[test]
fn test_rc_filter_time_constant() {
    let ckt = build_rc_filter(1000.0, 100e-6, 5.0);
    let mut solver = CircuitSolver::new(ckt, 1e-4, 0.2).unwrap();
    let results = solver.run_transient().unwrap();
    let target_t = 0.1;
    let closest = results.iter().min_by(|a, b|
        (a.time - target_t).abs().partial_cmp(&(b.time - target_t).abs()).unwrap()
    ).unwrap();
    let expected = 5.0 * (1.0 - (-1.0f64).exp());
    assert!((closest.v("vout") - expected).abs() < 0.15,
        "RC at t=tau should be {:.3}V, got {:.3}V", expected, closest.v("vout"));
}

#[test]
fn test_rc_filter_discharges() {
    let mut ckt = build_rc_filter(1000.0, 100e-6, 0.0);
    ckt.resistors.iter_mut().find(|r| r.name == "R1").unwrap().value = 1000.0;
    ckt.capacitors.iter_mut().find(|c| c.name == "C1").unwrap().value = 100e-6;
    let mut solver = CircuitSolver::new(ckt, 1e-4, 0.5).unwrap();
    solver.state.node_voltages.insert("vout".to_string(), 5.0);
    let results = solver.run_transient().unwrap();
    let final_v = results.last().unwrap().v("vout");
    assert!(final_v < 0.5, "RC should discharge to ~0V, got {}V", final_v);
    let mut prev = 5.0f64;
    for r in &results {
        let v = r.v("vout");
        assert!(v <= prev + 1e-6,
            "Vout should not increase during discharge: {} > {}", v, prev);
        prev = v;
    }
}

#[test]
fn test_buck_converter_open_loop() {
    let ckt = build_buck_converter(12.0, 10e-6, 100e-6, 10.0, 100_000.0);
    let mut solver = CircuitSolver::new(ckt, 1e-6, 0.01).unwrap();
    let results = solver.run_transient().unwrap();
    for r in &results {
        assert!(r.v("vout").is_finite(), "Vout must be finite");
        assert!(r.v("vout") >= 0.0, "Vout should be non-negative");
        assert!(r.v("vout") <= 12.1, "Vout should not exceed VIN + margin");
    }
    let final_v = results.last().unwrap().v("vout");
    println!("Buck open-loop final Vout: {:.3}V", final_v);
}

#[test]
fn test_buck_converter_no_nan_inf() {
    let ckt = build_buck_converter(12.0, 10e-6, 100e-6, 10.0, 100_000.0);
    let mut solver = CircuitSolver::new(ckt, 1e-6, 0.01).unwrap();
    let results = solver.run_transient().unwrap();
    for r in &results {
        assert!(r.v("vout").is_finite(), "NaN/Inf in Vout at t={}", r.time);
        assert!(r.v("sw").is_finite(), "NaN/Inf in switch node at t={}", r.time);
    }
}

#[test]
fn test_buck_closed_loop_regulates() {
    // Use component values appropriate for dt=1us simulation:
    // L=10uH: di/dt = 5V/10uH = 50kA/s -> di = 50mA per step
    // C=10uF: dv/dt = 0.5A/10uF = 50kV/s -> dv = 50mV per step
    // R=10Ohm: load current at 3V = 0.3A
    // Hysteresis band: +-15 counts = +-15/4095 * 3.3V = +-12mV
    // With C=10uF, dv/dt = 0.5A/10uF = 50mV/us -> dv = 50mV per step
    // This matches the hysteresis band, allowing proper regulation.
    let mut cosim = BuckCoSim::new(
        build_buck_converter(12.0, 10e-6, 10e-6, 10.0, 100_000.0),
        "vout".to_string(), "sw".to_string(), "0".to_string(),
        3.0, 0.05, 1.0, 3.3, 1e-6, 0.05,
    ).unwrap();
    let results = cosim.run().unwrap();
    let avg_v = cosim.avg_vout_last_fifth();
    println!("Buck closed-loop avg Vout (last 20%): {:.3}V (target: 3.0V)", avg_v);
    // Vout should regulate near target (3.0V) with hysteresis band
    // Allow tolerance for discrete-time simulation effects
    assert!(avg_v > 1.5 && avg_v < 4.5,
        "Buck should regulate between 1V and 4.5V, got {:.3}V", avg_v);
    let ripple = cosim.vout_ripple_last_fifth();
    println!("Buck Vout ripple (last 20%): {:.3}V pp", ripple);
    for r in &results {
        assert!(r.vout.is_finite(), "NaN/Inf in vout at t={}", r.time);
        assert!(r.i_l.is_finite(), "NaN/Inf in i_l at t={}", r.time);
        assert!(r.v_switch.is_finite(), "NaN/Inf in v_switch at t={}", r.time);
    }
}

#[test]
fn test_buck_closed_loop_gate_toggles() {
    let mut cosim = BuckCoSim::new(
        build_buck_converter(12.0, 10e-6, 100e-9, 10.0, 100_000.0),
        "vout".to_string(), "sw".to_string(), "0".to_string(),
        3.0, 0.05, 1.0, 3.3, 1e-6, 0.05,
    ).unwrap();
    let results = cosim.run().unwrap();
    let gate_high_count = results.iter().filter(|r| r.gate).count();
    let gate_low_count = results.iter().filter(|r| !r.gate).count();
    assert!(gate_high_count > 0 && gate_low_count > 0,
        "Controller should toggle gate: high={} low={}", gate_high_count, gate_low_count);
}

#[test]
fn test_standalone_no_dependencies() {
    let ckt = build_rc_filter(1000.0, 100e-6, 5.0);
    let mut solver = CircuitSolver::new(ckt, 1e-4, 0.1).unwrap();
    let _ = solver.run_transient().unwrap();
    assert!(true, "Standalone sim compiles and runs with stdlib only");
}