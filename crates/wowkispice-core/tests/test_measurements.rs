/*
 * test_measurements.rs - Rust gate for bridge/measurements.py pure functions.
 *
 * Transcribes the pure-array test classes from tests/test_measurements.py:
 *   TestCursors, TestTraceStats, TestFft, TestBodeMaths,
 *   TestPowerMetrics, TestStepMetrics
 *
 * The solver-driven classes (TestAgainstRealSolver, TestNoiseAndYield,
 * TestDistortion) stay Python-gated (wave 3, BLOCKED-ON-FFI) and are covered
 * by the parity_measurements harness instead.
 */

use wowkispice_core::measurements::*;

fn approx(a: f64, b: f64, eps: f64) -> bool {
    (a - b).abs() <= eps
}

fn sine(freq: f64, amp: f64, duration: f64, step: f64) -> (Vec<f64>, Vec<f64>) {
    let n = (duration / step) as usize + 1;
    let mut times = Vec::with_capacity(n);
    let mut values = Vec::with_capacity(n);
    for i in 0..n {
        let t = i as f64 * step;
        times.push(t);
        values.push(amp * (2.0 * std::f64::consts::PI * freq * t).sin());
    }
    (times, values)
}

fn square(freq: f64, amp: f64, duty: f64, duration: f64, step: f64) -> (Vec<f64>, Vec<f64>) {
    let n = (duration / step) as usize + 1;
    let mut times = Vec::with_capacity(n);
    let mut values = Vec::with_capacity(n);
    for i in 0..n {
        let t = i as f64 * step;
        times.push(t);
        if ((t * freq) % 1.0) < duty {
            values.push(amp);
        } else {
            values.push(0.0);
        }
    }
    (times, values)
}

// ----------------------------------------------------------------------
// TestCursors
// ----------------------------------------------------------------------

#[test]
fn test_sample_at_interpolates_between_points() {
    let times = vec![0.0, 1.0, 2.0, 3.0];
    let values = vec![0.0, 10.0, 20.0, 30.0];
    assert!(approx(sample_at(&times, &values, 0.5, true).unwrap(), 5.0, 1e-9));
    assert!(approx(sample_at(&times, &values, 1.25, true).unwrap(), 12.5, 1e-9));
}

#[test]
fn test_sample_at_clamps_outside_the_window() {
    let times = vec![0.0, 1.0];
    let values = vec![3.0, 9.0];
    assert_eq!(sample_at(&times, &values, -5.0, true).unwrap(), 3.0);
    assert_eq!(sample_at(&times, &values, 99.0, true).unwrap(), 9.0);
    assert!(sample_at(&times, &values, -5.0, false).is_none());
    assert!(sample_at(&times, &values, 99.0, false).is_none());
}

#[test]
fn test_readout_reports_dt_dv_and_reciprocals() {
    let times = vec![0.0, 1e-3, 2e-3];
    let values = vec![0.0, 1.0, 4.0];
    let r = cursor_readout(&times, &values, Some(0.0), Some(0.0), Some(1e-3), Some(1.0));
    assert!(approx(r.dt.unwrap(), 1e-3, 1e-12));
    assert!(approx(r.dv.unwrap(), 1.0, 1e-12));
    assert!(approx(r.inv_dt.unwrap(), 1000.0, 1e-9));
    assert!(approx(r.inv_dv.unwrap(), 1.0, 1e-12));
    assert!(approx(r.slope.unwrap(), 1000.0, 1e-9));
}

#[test]
fn test_single_cursor_has_no_differences() {
    let times = vec![0.0, 1.0];
    let values = vec![0.0, 1.0];
    let r = cursor_readout(&times, &values, Some(0.5), None, None, None);
    assert!(approx(r.t1.unwrap(), 0.5, 1e-12));
    assert!(r.inv_dt.is_none());
    assert!(r.dt.is_none());
}

#[test]
fn test_empty_trace_is_reported_not_crashed() {
    let r = cursor_readout(&[], &[], Some(0.0), Some(0.0), None, None);
    assert!(r.t1.is_none());
    let text = format_readout(&r);
    assert!(text.contains("no trace"));
}

#[test]
fn test_format_is_human_readable() {
    let times = vec![0.0, 1e-3];
    let values = vec![0.0, 1.0];
    let r = cursor_readout(&times, &values, Some(0.0), Some(0.0), Some(1e-3), Some(1.0));
    let text = format_readout(&r);
    assert!(text.contains("t1="));
    assert!(text.contains("1/dt="));
    assert!(text.contains("1kHz"));
}

// ----------------------------------------------------------------------
// TestTraceStats
// ----------------------------------------------------------------------

#[test]
fn test_mean_rms_and_peak_to_peak() {
    let (times, values) = sine(1000.0, 2.0, 0.02, 1e-5);
    let s = trace_stats(&times, &values, None);
    assert!(approx(s.mean.unwrap(), 0.0, 0.01));
    assert!(approx(s.rms.unwrap(), 2.0 / 2.0f64.sqrt(), 0.02));
    assert!(approx(s.p2p.unwrap(), 4.0, 0.05));
}

#[test]
fn test_duty_is_measured_against_a_threshold() {
    let (times, values) = square(1000.0, 1.0, 0.25, 0.02, 1e-5);
    let s = trace_stats(&times, &values, Some(0.5));
    assert!(approx(s.duty.unwrap(), 0.25, 0.01));
}

#[test]
fn test_empty_trace_does_not_divide_by_zero() {
    let s = trace_stats(&[], &[], None);
    assert_eq!(s.points, 0);
    assert!(s.mean.is_none());
}

#[test]
fn test_settling_time_finds_the_entry_point() {
    // Charges toward 5 V with tau = 1 ms; 2% band entered at ~3.9 tau.
    let step = 1e-6;
    let tau = 1e-3;
    let n = (0.02 / step) as usize;
    let mut times = Vec::with_capacity(n);
    let mut values = Vec::with_capacity(n);
    for i in 0..n {
        let t = i as f64 * step;
        times.push(t);
        values.push(5.0 * (1.0 - (-t / tau).exp()));
    }
    let settled = settling_time(&times, &values, 5.0, 0.02, None).unwrap();
    assert!(approx(settled, -tau * 0.02f64.ln(), 0.2e-3));
}

#[test]
fn test_settling_time_is_none_when_it_never_settles() {
    let times: Vec<f64> = (0..100).map(|i| i as f64 * 1e-6).collect();
    let values: Vec<f64> = times.iter().map(|&t| t * 1000.0).collect(); // a ramp: never settles
    assert!(settling_time(&times, &values, 1.0, 0.02, None).is_none());
}

#[test]
fn test_rise_fall_time_scales_with_the_actual_amplitude() {
    let n = 2000;
    let mut times = Vec::with_capacity(n);
    let mut values = Vec::with_capacity(n);
    for i in 0..n {
        let t = i as f64 * 1e-6;
        times.push(t);
        if t < 1e-3 {
            values.push(0.0);
        } else {
            values.push(5.0);
        }
    }
    let r = rise_fall_time(&times, &values, 0.0, 5.0, 0.5);
    // 50% threshold is crossed exactly at the 1 ms edge.
    assert!(approx(r.rise_s.unwrap(), 1e-3, 2e-6));
}

// ----------------------------------------------------------------------
// TestFft
// ----------------------------------------------------------------------

#[test]
fn test_dominant_frequency_of_a_pure_tone() {
    let (times, values) = sine(1000.0, 1.0, 0.05, 1e-5);
    let out = fft_spectrum(&times, &values, "blackman");
    assert!(approx(out.dominant_hz.unwrap(), 1000.0, 5.0));
}

#[test]
fn test_pure_tone_has_negligible_thd() {
    // The classic false-positive: leakage counted as distortion.
    let (times, values) = sine(1000.0, 1.0, 0.05, 1e-5);
    let out = fft_spectrum(&times, &values, "blackman");
    let thd_val = thd(&out.freqs, &out.magnitude, Some(1000.0), 20).unwrap();
    assert!(thd_val < 0.005, "pure sine reported {:.3}% THD", thd_val * 100.0);
}

#[test]
fn test_square_wave_thd_matches_theory() {
    // An ideal 50% square wave has THD = sqrt(1/9 + 1/25 + 1/49 + ...) ~ 0.49.
    // A finite number of sampled edges keeps it a little below that.
    let (times, values) = square(1000.0, 1.0, 0.5, 0.05, 1e-5);
    let out = fft_spectrum(&times, &values, "blackman");
    let thd_val = thd(&out.freqs, &out.magnitude, Some(1000.0), 20).unwrap();
    assert!(approx(thd_val, 0.4937, 0.12));
}

#[test]
fn test_quarter_duty_is_worse_than_half() {
    let (times_a, val_a) = square(1000.0, 1.0, 0.5, 0.05, 1e-5);
    let (times_b, val_b) = square(1000.0, 1.0, 0.25, 0.05, 1e-5);
    let a = fft_spectrum(&times_a, &val_a, "blackman");
    let b = fft_spectrum(&times_b, &val_b, "blackman");
    let thd_a = thd(&a.freqs, &a.magnitude, Some(1000.0), 20).unwrap();
    let thd_b = thd(&b.freqs, &b.magnitude, Some(1000.0), 20).unwrap();
    assert!(thd_b > thd_a);
}

#[test]
fn test_too_short_a_trace_reports_empty_rather_than_failing() {
    let out = fft_spectrum(&[0.0, 1e-6], &[0.0, 1.0], "blackman");
    assert!(out.freqs.is_empty());
    assert!(out.dominant_hz.is_none());
}

#[test]
fn test_unknown_window_is_rejected() {
    let (times, values) = sine(1000.0, 1.0, 0.01, 1e-5);
    let result = std::panic::catch_unwind(|| {
        fft_spectrum(&times, &values, "gaussian")
    });
    assert!(result.is_err());
}

// ----------------------------------------------------------------------
// TestBodeMaths
// ----------------------------------------------------------------------

#[test]
fn test_rc_response_matches_analytic_gain_and_phase() {
    // First-order low-pass: |H| = 1/sqrt(1+(wRC)^2), phase = -atan(wRC).
    let freqs = vec![10.0, 100.0, 1000.0, 10000.0, 100000.0];
    let rc = 1e-4; // R*C for 1k and 100n, in seconds
    let corner = 1.0 / (2.0 * std::f64::consts::PI * rc);
    assert!(approx(corner, 1591.55, 0.01));
    let re: Vec<f64> = freqs.iter().map(|&f| 1.0 / (1.0 + (2.0 * std::f64::consts::PI * f * rc).powi(2)).sqrt()).collect();
    let im = vec![0.0; freqs.len()];
    let out = bode_from_ac(&freqs, &re, &im, 1.0);
    assert!(approx(out.gain_db[0], 0.0, 0.01));
    let expected = 20.0 * (1.0 / (1.0 + (2.0 * std::f64::consts::PI * 10000.0 * rc).powi(2)).sqrt()).log10();
    assert!(approx(out.gain_db[3], expected, 0.01));
}

#[test]
fn test_phase_is_unwrapped_across_the_negative_axis() {
    let freqs = vec![1.0, 2.0, 3.0];
    let re = vec![1.0, -1.0, 1.0];
    let im = vec![1.0, 1e-9, -1.0]; // crosses behind the origin
    let out = bode_from_ac(&freqs, &re, &im, 1.0);
    let spread = out.phase_deg.iter().cloned().fold(f64::NEG_INFINITY, f64::max)
        - out.phase_deg.iter().cloned().fold(f64::INFINITY, f64::min);
    assert!(spread < 360.0, "phase jumped {} deg: {:?}", spread, out.phase_deg);
}

#[test]
fn test_passive_filter_reports_no_phase_margin_rather_than_a_fake_one() {
    let out = phase_margin(&[1.0, 100.0], &[-0.1, -20.0], &[-5.0, -80.0]);
    assert!(out.phase_margin_deg.is_none());
    assert!(out.crossover_hz.is_none());
}

// ----------------------------------------------------------------------
// TestPowerMetrics
// ----------------------------------------------------------------------

#[test]
fn test_efficiency_of_a_halving_regulator() {
    let m = power_metrics(12.0, 0.275, 3.3, 1.0);
    assert!(approx(m.efficiency.unwrap(), 3.3 / 3.3, 0.02));
    assert!(m.loss_w > 0.0);
}

#[test]
fn test_impossible_efficiency_is_refused() {
    let m = power_metrics(3.3, 1.0, 12.0, 1.0); // a gain, not a reg
    assert!(m.efficiency.is_none());
    assert!(m.loss_w != 0.0);
}

#[test]
fn test_series_current_from_ohms_law() {
    let currents = series_current(&[0.0, 1.0], &[5.0, 10.0], 1000.0);
    assert!(approx(currents[0], 0.005, 1e-12));
    assert!(approx(currents[1], 0.01, 1e-12));
}

// ----------------------------------------------------------------------
// TestStepMetrics
// ----------------------------------------------------------------------

#[test]
fn test_analytic_rc_step() {
    let tau = 1e-3;
    let n = 2001;
    let mut times = Vec::with_capacity(n);
    let mut values = Vec::with_capacity(n);
    for i in 0..n {
        let t = i as f64 * 5e-6; // 0 .. 10 ms = 10 tau
        times.push(t);
        values.push(1.0 - (-t / tau).exp());
    }
    let m = step_metrics(&times, &values, 0.02);
    assert_eq!(m.direction.as_deref(), Some("rising"));
    assert!(approx(m.v_final.unwrap(), 1.0, 0.01));
    // 50% crossing of an exponential RC step is tau*ln2 ...
    assert!(approx(m.delay_s.unwrap(), tau * 2.0f64.ln(), 0.01 * tau));
    // ... and its 10-90% rise time is tau*ln9.
    assert!(approx(m.rise_s.unwrap(), tau * 9.0f64.ln(), 0.05 * tau));
    assert!(m.overshoot_pct < 1.0, "monotonic rise must not report overshoot");
    assert!(m.undershoot_pct < 1.0, "a monotonic rise must not report its own approach as undershoot");
    // enters the +/-2% band at tau*ln(50) and stays there.
    assert!(approx(m.settling_s.unwrap(), tau * 50.0f64.ln(), 0.1 * tau));
    // slew is the same 80% swing over the sampled 10-90% rise.
    assert!(approx(m.slew_v_ms.unwrap(), 0.8 / (m.rise_s.unwrap() * 1000.0), 1e-4));
}

#[test]
fn test_ringy_step_reports_overshoot() {
    let tau = 1e-3;
    let n = 3001;
    let mut times = Vec::with_capacity(n);
    let mut values = Vec::with_capacity(n);
    for i in 0..n {
        let t = i as f64 * 5e-6; // 0 .. 15 ms
        let v = if t < 3.0 * tau {
            1.0 - (-t / tau).exp()
        } else if 4.0 * tau <= t && t < 4.2 * tau {
            1.25 // 25% bump on plateau
        } else {
            1.0
        };
        times.push(t);
        values.push(v);
    }
    let m = step_metrics(&times, &values, 0.02);
    assert!(approx(m.overshoot_pct, 25.0, 1.0));
    assert!(m.undershoot_pct < 1.0);
    assert!(m.settling_s.is_some());
}

#[test]
fn test_flat_trace_reports_no_step() {
    let times: Vec<f64> = (0..50).map(|i| i as f64 * 1e-5).collect();
    let m = step_metrics(&times, &vec![2.5; 50], 0.02);
    assert!(m.direction.is_none());
    assert!(m.delay_s.is_none());
    assert!(m.settling_s.is_none());
}
