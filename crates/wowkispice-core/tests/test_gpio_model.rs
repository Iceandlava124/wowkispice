/*
 * test_gpio_model.rs - Rust gate for bridge/gpio_model.py pure functions.
 *
 * Transcribes TestGpioProfile and TestLogicAnalysis from
 * tests/test_firmware_gpio.py. The end-to-end cosim class
 * (TestGpioCosimEndToEnd) stays Python-gated (wave 3, BLOCKED-ON-FFI).
 */

use wowkispice_core::gpio_model::*;

fn approx(a: f64, b: f64, eps: f64) -> bool {
    (a - b).abs() <= eps
}

// ----------------------------------------------------------------------
// TestGpioProfile
// ----------------------------------------------------------------------

#[test]
fn test_static_pin_emits_dc_card() {
    assert_eq!(
        spice_card("static", Some(3.3), Some(1), None, None, None, 1e-7).unwrap(),
        "DC 3.3"
    );
    assert_eq!(
        spice_card("static", Some(3.3), Some(0), None, None, None, 1e-7).unwrap(),
        "DC 0"
    );
}

#[test]
fn test_square_pin_emits_pulse_with_right_period_and_duty() {
    let card = spice_card("square", Some(3.3), None, Some(1000.0), Some(0.25), None, 1e-7).unwrap();
    assert!(card.starts_with("PULSE(0 3.3"));
    let inner = &card["PULSE(".len()..card.len() - 1];
    let parts: Vec<&str> = inner.split_whitespace().collect();
    let on_time: f64 = parts[5].parse().unwrap();
    let period: f64 = parts[6].parse().unwrap();
    assert!(approx(period, 0.001, 1e-6));
    assert!(approx(on_time / period, 0.25, 1e-3));
}

#[test]
fn test_default_is_idle_low() {
    assert_eq!(spice_card("static", None, None, None, None, None, 1e-7).unwrap(), "DC 0");
}

#[test]
fn test_rejects_nonsense() {
    let cases = [
        ("sine", None, None, None, None, None),
        ("square", None, None, Some(0.0), None, None),
        ("square", None, None, Some(1.0), Some(0.0), None),
        ("static", Some(99.0), None, None, None, None),
    ];
    for (mode, vhigh, level, freq, duty, phase) in cases {
        assert!(
            spice_card(mode, vhigh, level, freq, duty, phase, 1e-7).is_err(),
            "expected error for mode={:?} vhigh={:?} freq={:?} duty={:?}",
            mode, vhigh, freq, duty
        );
    }
}

#[test]
fn test_describe_pin_is_human_readable() {
    let text = describe_pin(
        "GPIO18", "square", Some(3.3), None, Some(1000.0), Some(0.5), None,
    ).unwrap();
    assert!(text.contains("1000 Hz"));
    assert!(text.contains("50%"));
}

// ----------------------------------------------------------------------
// TestLogicAnalysis
// ----------------------------------------------------------------------

#[test]
fn test_detects_levels_duty_and_frequency() {
    // 5 us steps, toggling every 100 samples -> 1 kHz square wave
    let mut times = Vec::with_capacity(2000);
    let mut values = Vec::with_capacity(2000);
    for i in 0..2000 {
        times.push(i as f64 * 5e-6);
        values.push(if (i / 100) % 2 == 0 { 3.3 } else { 0.0 });
    }
    let info = analyze_pin(&times, &values, 1.65);
    assert!(info.transitions > 10);
    assert!(approx(info.duty, 0.5, 0.06));
    assert!(approx(info.v_max.unwrap(), 3.3, 1e-3));
    let freq = measured_frequency(&times, &values, 1.65).unwrap();
    assert!(approx(freq, 1000.0, 40.0));
}

#[test]
fn test_static_signal_has_no_transitions() {
    let times: Vec<f64> = (0..10).map(|i| i as f64 * 1e-3).collect();
    let values = vec![3.3; 10];
    let info = analyze_pin(&times, &values, 1.65);
    assert_eq!(info.transitions, 0);
    assert!(measured_frequency(&times, &values, 1.65).is_none());
}

// ----------------------------------------------------------------------
// pin_direction
// ----------------------------------------------------------------------

#[test]
fn test_pin_direction_power() {
    assert_eq!(pin_direction("GND"), "power");
    assert_eq!(pin_direction("VCC"), "power");
    assert_eq!(pin_direction("5V"), "power");
    assert_eq!(pin_direction("NRST"), "power");
}

#[test]
fn test_pin_direction_analog() {
    assert_eq!(pin_direction("A0"), "analog");
    assert_eq!(pin_direction("A5"), "analog");
    assert_eq!(pin_direction("ADC1"), "analog");
}

#[test]
fn test_pin_direction_bidirectional() {
    assert_eq!(pin_direction("GPIO18"), "bidirectional");
    assert_eq!(pin_direction("D13"), "bidirectional");
    assert_eq!(pin_direction("TX"), "bidirectional");
    assert_eq!(pin_direction("SCL"), "bidirectional");
}
