/*
 * parity_measurements.rs - Rust half of the measurements-parity battery.
 *
 * Computes a fixed battery of waveform-analysis facts from
 * crates/wowkispice-core/src/measurements.rs and prints KEY<TAB>VALUE lines
 * for crates/parity/python/parity_measurements.py to diff against
 * bridge/measurements.py.
 *
 * Battery design: one fixed set of synthetic inputs, computed independently
 * on both sides. Keys are index-based (s[i], c[i], t[i], s_m[i], f[i], b[i],
 * p[i]) plus named keys where helpful. Float values are compared as doubles;
 * strings are compared as text.
 */

use std::io::{BufWriter, Write};

/// Format an f64 like Python's `f"{v:.10e}"`: 10 decimal places, minimum
/// 2-digit exponent with explicit sign (e.g. `1.0000000000e+03`, `-1.71e-04`).
fn format_e10(v: f64) -> String {
    let s = format!("{:.10e}", v);
    if let Some(e_pos) = s.find('e') {
        let (base, exp) = s.split_at(e_pos);
        let exp_str = &exp[1..]; // skip 'e'
        let (sign, num) = if exp_str.starts_with('+') || exp_str.starts_with('-') {
            (&exp_str[..1], &exp_str[1..])
        } else {
            ("+", exp_str)
        };
        // Python uses minimum 2 exponent digits
        let num_padded = if num.len() >= 2 {
            num.to_string()
        } else {
            format!("0{}", num)
        };
        return format!("{}e{}{}", base, sign, num_padded);
    }
    s
}

use wowkispice_core::measurements::*;

fn enc_opt_f64(v: Option<f64>) -> String {
    match v {
        None => "None".to_string(),
        Some(x) => format_e10(x),
    }
}

fn enc_vec_f64(v: &[f64]) -> String {
    v.iter().map(|&x| format_e10(x)).collect::<Vec<_>>().join("|")
}

fn enc_cursor(r: &CursorReadout) -> String {
    format!(
        "t1={}|v1={}|t2={}|v2={}|dt={}|dv={}|slope={}|inv_dt={}|inv_dv={}",
        enc_opt_f64(r.t1), enc_opt_f64(r.v1), enc_opt_f64(r.t2), enc_opt_f64(r.v2),
        enc_opt_f64(r.dt), enc_opt_f64(r.dv), enc_opt_f64(r.slope),
        enc_opt_f64(r.inv_dt), enc_opt_f64(r.inv_dv)
    )
}

fn enc_stats(s: &TraceStats) -> String {
    format!(
        "points={}|mean={}|rms={}|min={}|max={}|p2p={}|duty={}|first_crossing_s={}",
        s.points, enc_opt_f64(s.mean), enc_opt_f64(s.rms), enc_opt_f64(s.min),
        enc_opt_f64(s.max), enc_opt_f64(s.p2p), enc_opt_f64(s.duty),
        enc_opt_f64(s.first_crossing_s)
    )
}

fn enc_step(m: &StepMetrics) -> String {
    format!(
        "points={}|v_start={}|v_final={}|step_v={}|direction={}|delay_s={}|rise_s={}|overshoot_pct={}|undershoot_pct={}|settling_s={}|slew_v_ms={}",
        m.points, enc_opt_f64(m.v_start), enc_opt_f64(m.v_final), enc_opt_f64(m.step_v),
        m.direction.as_deref().unwrap_or("None"), enc_opt_f64(m.delay_s), enc_opt_f64(m.rise_s),
        format_e10(m.overshoot_pct), format_e10(m.undershoot_pct),
        enc_opt_f64(m.settling_s), enc_opt_f64(m.slew_v_ms)
    )
}

fn enc_fft(f: &FftSpectrum) -> String {
    format!(
        "dominant_hz={}|n={}|sample_rate_hz={}|noise_floor={}|bin_width_hz={}|mag0={}|freq0={}",
        enc_opt_f64(f.dominant_hz), f.n, format_e10(f.sample_rate_hz), format_e10(f.noise_floor),
        format_e10(f.bin_width_hz),
        format_e10(f.magnitude.first().copied().unwrap_or(0.0)),
        format_e10(f.freqs.first().copied().unwrap_or(0.0))
    )
}

fn enc_bode(b: &BodeResult) -> String {
    format!(
        "peak_db={}|peak_hz={}|gain0={}|phase0={}",
        enc_opt_f64(b.peak_db), enc_opt_f64(b.peak_hz),
        format_e10(b.gain_db.first().copied().unwrap_or(0.0)),
        format_e10(b.phase_deg.first().copied().unwrap_or(0.0))
    )
}

fn enc_power(p: &PowerMetrics) -> String {
    format!(
        "p_in_w={}|p_out_w={}|loss_w={}|efficiency={}",
        format_e10(p.p_in_w), format_e10(p.p_out_w), format_e10(p.loss_w),
        enc_opt_f64(p.efficiency)
    )
}

fn main() {
    let mut args = std::env::args();
    let _prog = args.next();
    let manifest = args.next().unwrap_or_else(|| {
        eprintln!("usage: parity_measurements <manifest-file>");
        std::process::exit(2);
    });

    let _ = std::fs::read_to_string(&manifest); // manifest exists check only

    // Fixed synthetic traces (identical to the Python driver's inputs).
    let t_sine: Vec<f64> = (0..5001).map(|i| i as f64 * 1e-5).collect();
    let v_sine: Vec<f64> = t_sine.iter().map(|&t| (2.0 * std::f64::consts::PI * 1000.0 * t).sin()).collect();

    let t_sq: Vec<f64> = (0..5001).map(|i| i as f64 * 1e-5).collect();
    let v_sq: Vec<f64> = t_sq.iter().map(|&t| {
        if ((t * 1000.0) % 1.0) < 0.5 { 1.0 } else { 0.0 }
    }).collect();

    let t_rc: Vec<f64> = (0..2001).map(|i| i as f64 * 5e-6).collect();
    let tau = 1e-3;
    let v_rc: Vec<f64> = t_rc.iter().map(|&t| 1.0 - (-t / tau).exp()).collect();

    let t_step: Vec<f64> = (0..3001).map(|i| i as f64 * 5e-6).collect();
    let v_step: Vec<f64> = t_step.iter().map(|&t| {
        if t < 3.0 * tau {
            1.0 - (-t / tau).exp()
        } else if 4.0 * tau <= t && t < 4.2 * tau {
            1.25
        } else {
            1.0
        }
    }).collect();

    let stdout = std::io::stdout();
    let lock = stdout.lock();
    let mut writer = BufWriter::new(lock);

    let mut out: Vec<(String, String)> = Vec::new();

    // ---- s[i]: sample_at
    out.push(("s[0]".to_string(), enc_opt_f64(sample_at(&t_sine, &v_sine, 0.5, true))));
    out.push(("s[1]".to_string(), enc_opt_f64(sample_at(&t_sine, &v_sine, 1.25, true))));
    out.push(("s[2]".to_string(), enc_opt_f64(sample_at(&t_sine, &v_sine, -5.0, true))));
    out.push(("s[3]".to_string(), enc_opt_f64(sample_at(&t_sine, &v_sine, 99.0, false))));

    // ---- c[i]: cursor_readout
    out.push(("c[0]".to_string(), enc_cursor(&cursor_readout(
        &t_sine, &v_sine, Some(0.0), Some(0.0), Some(1e-3), Some(1.0)))));
    out.push(("c[1]".to_string(), enc_cursor(&cursor_readout(
        &t_sine, &v_sine, Some(0.5), None, None, None))));
    out.push(("c[2]".to_string(), enc_cursor(&cursor_readout(&[], &[], Some(0.0), Some(0.0), None, None))));

    // ---- r[i]: format_readout
    out.push(("r[0]".to_string(), format_readout(&cursor_readout(
        &t_sine, &v_sine, Some(0.0), Some(0.0), Some(1e-3), Some(1.0)))));

    // ---- t[i]: trace_stats
    out.push(("t[0]".to_string(), enc_stats(&trace_stats(&t_sine, &v_sine, None))));
    out.push(("t[1]".to_string(), enc_stats(&trace_stats(&t_sq, &v_sq, Some(0.5)))));
    out.push(("t[2]".to_string(), enc_stats(&trace_stats(&[], &[], None))));

    // ---- st[i]: settling_time
    out.push(("st[0]".to_string(), enc_opt_f64(settling_time(&t_rc, &v_rc, 5.0, 0.02, None))));
    out.push(("st[1]".to_string(), enc_opt_f64(settling_time(&t_step, &v_step, 1.0, 0.02, None))));

    // ---- rf[i]: rise_fall_time
    let n = 2000;
    let mut t_rf = Vec::with_capacity(n);
    let mut v_rf = Vec::with_capacity(n);
    for i in 0..n {
        let t = i as f64 * 1e-6;
        t_rf.push(t);
        if t < 1e-3 { v_rf.push(0.0); } else { v_rf.push(5.0); }
    }
    let rf = rise_fall_time(&t_rf, &v_rf, 0.0, 5.0, 0.5);
    out.push(("rf[0]".to_string(), format!("rise={}|fall={}", enc_opt_f64(rf.rise_s), enc_opt_f64(rf.fall_s))));

    // ---- sm[i]: step_metrics
    out.push(("sm[0]".to_string(), enc_step(&step_metrics(&t_rc, &v_rc, 0.02))));
    out.push(("sm[1]".to_string(), enc_step(&step_metrics(&t_step, &v_step, 0.02))));
    out.push(("sm[2]".to_string(), enc_step(&step_metrics(&t_rc, &vec![2.5; 50], 0.02))));

    // ---- f[i]: fft_spectrum
    out.push(("f[0]".to_string(), enc_fft(&fft_spectrum(&t_sine, &v_sine, "blackman"))));
    out.push(("f[1]".to_string(), enc_fft(&fft_spectrum(&t_sq, &v_sq, "blackman"))));
    out.push(("f[2]".to_string(), enc_fft(&fft_spectrum(&[0.0, 1e-6], &[0.0, 1.0], "blackman"))));

    // ---- thd[i]: thd
    let f0 = fft_spectrum(&t_sine, &v_sine, "blackman");
    out.push(("thd[0]".to_string(), enc_opt_f64(thd(&f0.freqs, &f0.magnitude, Some(1000.0), 20))));
    let f1 = fft_spectrum(&t_sq, &v_sq, "blackman");
    out.push(("thd[1]".to_string(), enc_opt_f64(thd(&f1.freqs, &f1.magnitude, Some(1000.0), 20))));

    // ---- b[i]: bode_from_ac
    let freqs = vec![10.0, 100.0, 1000.0, 10000.0, 100000.0];
    let rc = 1e-4;
    let re: Vec<f64> = freqs.iter().map(|&f| 1.0 / (1.0 + (2.0 * std::f64::consts::PI * f * rc).powi(2)).sqrt()).collect();
    let im = vec![0.0; freqs.len()];
    let b = bode_from_ac(&freqs, &re, &im, 1.0);
    out.push(("b[0]".to_string(), enc_bode(&b)));

    // ---- pm[i]: phase_margin
    let pm = phase_margin(&[1.0, 100.0], &[-0.1, -20.0], &[-5.0, -80.0]);
    out.push(("pm[0]".to_string(), format!("crossover={}|gain={}|pm={}|gm={}",
        enc_opt_f64(pm.crossover_hz), enc_opt_f64(pm.gain_at_crossover_db),
        enc_opt_f64(pm.phase_margin_deg), enc_opt_f64(pm.gain_margin_db))));

    // ---- p[i]: power_metrics
    out.push(("p[0]".to_string(), enc_power(&power_metrics(12.0, 0.275, 3.3, 1.0))));
    out.push(("p[1]".to_string(), enc_power(&power_metrics(3.3, 1.0, 12.0, 1.0))));

    // ---- sc[i]: series_current
    out.push(("sc[0]".to_string(), enc_vec_f64(&series_current(&[0.0, 1.0], &[5.0, 10.0], 1000.0))));

    for (key, value) in out {
        writeln!(writer, "{}\t{}", key, value).expect("stdout write");
    }
    writer.flush().expect("stdout flush");
}
