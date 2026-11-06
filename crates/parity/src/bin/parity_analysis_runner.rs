/*
 * parity_analysis_runner.rs - emits a fixed battery of analysis_runner results.
 *
 * The companion python/parity_analysis_runner.py computes the SAME battery from
 * bridge/analysis_runner.py and diffs the two.
 *
 * Tests pure computation (no ngspice DLL required):
 *   - spice_value: SPICE component value parser
 *   - _divide: complex division real part
 *   - fft_spectrum: windowed FFT
 *   - thd: total harmonic distortion
 *   - bode_from_ac: gain/phase from AC data
 *   - phase_margin: stability margins
 *
 * Output format: one key<tab>value per line.
 */

use wowkispice_core::analysis_runner::{spice_value, _divide};
use wowkispice_core::measurements::{bode_from_ac, fft_spectrum, phase_margin, thd};

fn emit_d(key: &str, v: f64) {
    println!("{}\t{}", key, v);
}

fn emit_l(key: &str, v: i64) {
    println!("{}\t{}", key, v);
}

fn emit_s(key: &str, v: &str) {
    println!("{}\t{}", key, v);
}

#[allow(dead_code)]
fn emit_b(key: &str, v: bool) {
    println!("{}\t{}", key, if v { "true" } else { "false" });
}

fn battery_spice_value() {
    let cases: &[(&str, &str)] = &[
        ("10", "10"),
        ("3.14", "3.14"),
        ("0", "0"),
        ("-5.5", "-5.5"),
        ("1k", "1k"),
        ("1K", "1K"),
        ("4.7u", "4.7u"),
        ("100n", "100n"),
        ("2.2p", "2.2p"),
        ("1f", "1f"),
        ("1meg", "1meg"),
        ("100m", "100m"),
        ("10mil", "10mil"),
        ("  1k  ", "  1k  "),
    ];
    for (text, key_suffix) in cases {
        match spice_value(text) {
            Ok(v) => emit_d(&format!("spice_value[{}]", key_suffix), v),
            Err(_) => emit_s(&format!("spice_value[{}]", key_suffix), "ValueError"),
        }
    }

    for text in ["", "   ", "PULSE(0 1 0 1n 1n 1u 10u)", "1k2"] {
        match spice_value(text) {
            Ok(_) => emit_s(&format!("spice_value_invalid[{}]", text), "no-error"),
            Err(_) => emit_s(&format!("spice_value_invalid[{}]", text), "ValueError"),
        }
    }
}

fn battery_divide() {
    let cases: &[(&[f64], &[f64], &[f64], &[f64])] = &[
        (&[1.0], &[2.0], &[3.0], &[4.0]),
        (&[3.0], &[4.0], &[3.0], &[4.0]),
        (&[1.0], &[2.0], &[0.0], &[0.0]),
        (&[5.0], &[0.0], &[1.0], &[0.0]),
        (&[0.0], &[0.0], &[2.0], &[3.0]),
    ];
    for (i, (nre, nim, dre, dim)) in cases.iter().enumerate() {
        let result = _divide(nre, nim, dre, dim);
        emit_d(&format!("divide[{i}].real0"), result[0]);
    }
}

fn battery_fft() {
    let sample_rate = 44100.0f64;
    let f0 = 1000.0f64;
    let n = 1024usize;
    let times: Vec<f64> = (0..n).map(|i| i as f64 / sample_rate).collect();
    let values: Vec<f64> = times.iter().map(|&t| (2.0 * std::f64::consts::PI * f0 * t).sin()).collect();

    for window in ["hann", "blackman", "rect"] {
        let spec = fft_spectrum(&times, &values, window);
        emit_d(&format!("fft[{window}].dominant_hz"), spec.dominant_hz.unwrap_or(-1.0));
        emit_l(&format!("fft[{window}].n"), spec.n as i64);
        emit_d(&format!("fft[{window}].sample_rate_hz"), spec.sample_rate_hz);
        emit_d(&format!("fft[{window}].noise_floor"), spec.noise_floor);
        emit_d(&format!("fft[{window}].bin_width_hz"), spec.bin_width_hz);
        emit_l(&format!("fft[{window}].num_freqs"), spec.freqs.len() as i64);
    }

    let short_spec = fft_spectrum(&[0.0, 1.0], &[1.0, 2.0], "hann");
    emit_l("fft[short].n", short_spec.n as i64);
    emit_l("fft[short].num_freqs", short_spec.freqs.len() as i64);

    emit_s("fft[invalid_window]", "panics_in_rust");
}

fn battery_thd() {
    let freqs: Vec<f64> = (1..51).map(|i| 100.0 * i as f64).collect();
    let mut magnitude = vec![0.0f64; 50];
    magnitude[9] = 1.0;
    magnitude[19] = 0.1;
    magnitude[29] = 0.05;

    let thd_val = thd(&freqs, &magnitude, Some(1000.0), 10);
    emit_d("thd.with_fundamental", thd_val.unwrap_or(-1.0));

    let thd_auto = thd(&freqs, &magnitude, None, 10);
    emit_d("thd.auto_fundamental", thd_auto.unwrap_or(-1.0));

    let mut magnitude2 = vec![0.0f64; 50];
    magnitude2[9] = 1.0;
    let thd_pure = thd(&freqs, &magnitude2, Some(1000.0), 10);
    emit_d("thd.pure_tone", thd_pure.unwrap_or(-1.0));

    let thd_empty = thd(&[], &[], None, 10);
    emit_s("thd.empty", if thd_empty.is_none() { "none" } else { "some" });
}

fn battery_bode() {
    let freqs = vec![10.0, 100.0, 1000.0, 10000.0, 100000.0];
    let re = vec![1.0, 0.5, 0.1, 0.01, 0.001];
    let im = vec![0.0; 5];

    let bode = bode_from_ac(&freqs, &re, &im, 1.0);
    emit_d("bode.peak_db", bode.peak_db.unwrap_or(-999.0));
    emit_d("bode.peak_hz", bode.peak_hz.unwrap_or(-1.0));
    emit_l("bode.num_points", bode.freqs.len() as i64);

    let empty_bode = bode_from_ac(&[], &[], &[], 1.0);
    emit_l("bode.empty.num_points", empty_bode.freqs.len() as i64);
    emit_s("bode.empty.peak_db", if empty_bode.peak_db.is_none() { "none" } else { "some" });
}

fn battery_phase_margin() {
    let freqs = vec![10.0, 100.0, 1000.0, 10000.0];
    let gain_db = vec![10.0, 5.0, 0.0, -20.0];
    let phase_deg = vec![-90.0, -100.0, -120.0, -150.0];

    let pm = phase_margin(&freqs, &gain_db, &phase_deg);
    emit_d("pm.crossover_hz", pm.crossover_hz.unwrap_or(-1.0));
    emit_d("pm.gain_at_crossover_db", pm.gain_at_crossover_db.unwrap_or(-999.0));
    emit_d("pm.phase_margin_deg", pm.phase_margin_deg.unwrap_or(-999.0));
    emit_d("pm.gain_margin_db", pm.gain_margin_db.unwrap_or(-999.0));

    let pm_none = phase_margin(&[10.0, 100.0], &[10.0, 5.0], &[-90.0, -100.0]);
    emit_s("pm.no_crossover", if pm_none.crossover_hz.is_none() { "none" } else { "some" });
}

fn main() {
    battery_spice_value();
    battery_divide();
    battery_fft();
    battery_thd();
    battery_bode();
    battery_phase_margin();
}