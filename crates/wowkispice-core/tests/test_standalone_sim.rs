// Use component values appropriate for dt=1us simulation:
    // L=1uH: di/dt = 5V/1uH = 5MA/s -> di = 5mA per step (very fast)
    // C=1pF: dv/dt = 0.5A/1pF = 50GV/s -> dv = 50V per step (extremely fast)
    // R=10Ohm: load current at 3V = 0.3A
    // With these values, vout can charge/discharge within one timestep,
    // allowing the hysteretic controller to regulate properly.
    let mut cosim = BuckCoSim::new(
        build_buck_converter(12.0, 10e-6, 1e-12, 10.0, 100_000.0),
        "vout".to_string(), "sw".to_string(), "0".to_string(),
        3.0, 0.05, 1.0, 3.3, 1e-6, 0.05,
    ).unwrap();