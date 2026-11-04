/*
 * measurements.rs - port of bridge/measurements.py.
 *
 * Pure computation over arrays the solver produced. No Qt, no solver
 * dependency: unit-testable headlessly. Time is in seconds and values in
 * volts throughout, matching ngspice.
 *
 * Fidelity contract: transcribe line-for-line from Python. Float edge cases
 * (None -> Option::None, EPS comparisons, NaN handling) mirror CPython.
 */

use std::f64::consts::PI;

/// Threshold below which a denominator is treated as zero (Python: EPS = 1e-15).
const EPS: f64 = 1e-15;

/// Interpolated value of a trace at time `t`.
///
/// Out-of-range queries return None unless clamp is set, in which case the
/// nearest endpoint is returned - which is what a cursor dragged past the end
/// of a waveform should show.
pub fn sample_at(
    times: &[f64],
    values: &[f64],
    t: f64,
    clamp: bool,
) -> Option<f64> {
    if times.is_empty() || values.is_empty() || times.len() != values.len() {
        return None;
    }
    if t <= times[0] {
        return if clamp { Some(values[0]) } else { None };
    }
    if t >= times[times.len() - 1] {
        return if clamp { Some(values[values.len() - 1]) } else { None };
    }
    // Binary search for the bracketing pair.
    let mut lo = 0usize;
    let mut hi = times.len() - 1;
    while hi - lo > 1 {
        let mid = (lo + hi) / 2;
        if times[mid] <= t {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    let span = times[hi] - times[lo];
    if span <= 0.0 {
        return Some(values[lo]);
    }
    let frac = (t - times[lo]) / span;
    Some(values[lo] + frac * (values[hi] - values[lo]))
}

/// Cursor ruler measurement: everything an LTspice ruler shows between two
/// points. Pass t2 to get a ruler measurement (dt, dv, slope, 1/dt); leave it
/// None for a single cursor's coordinates only.
#[derive(Debug, Clone)]
pub struct CursorReadout {
    pub t1: Option<f64>,
    pub v1: Option<f64>,
    pub t2: Option<f64>,
    pub v2: Option<f64>,
    pub dt: Option<f64>,
    pub dv: Option<f64>,
    pub slope: Option<f64>,
    pub inv_dt: Option<f64>,
    pub inv_dv: Option<f64>,
}

impl CursorReadout {
    fn empty() -> Self {
        CursorReadout {
            t1: None, v1: None, t2: None, v2: None,
            dt: None, dv: None, slope: None, inv_dt: None, inv_dv: None,
        }
    }
}

pub fn cursor_readout(
    times: &[f64],
    values: &[f64],
    t1: Option<f64>,
    v1: Option<f64>,
    t2: Option<f64>,
    v2: Option<f64>,
) -> CursorReadout {
    if times.is_empty() || values.is_empty() || times.len() != values.len() {
        return CursorReadout::empty();
    }

    let t1 = t1.unwrap_or(times[0]);
    let v1 = v1.or_else(|| sample_at(times, values, t1, true));

    let mut out = CursorReadout {
        t1: Some(t1), v1, t2: None, v2: None,
        dt: None, dv: None, slope: None, inv_dt: None, inv_dv: None,
    };

    let t2 = match t2 {
        Some(t2) => t2,
        None => return out,
    };

    let v2 = v2.or_else(|| sample_at(times, values, t2, true));
    out.t2 = Some(t2);
    out.v2 = v2;

    let dt = t2 - t1;
    let dv = v2.unwrap_or(0.0) - v1.unwrap_or(0.0);
    out.dt = Some(dt);
    out.dv = Some(dv);
    if dt.abs() > EPS {
        out.inv_dt = Some(1.0 / dt); // frequency, if dt is a period
        if dv.abs() > EPS {
            out.slope = Some(dv / dt); // V/s
        }
    }
    if dv.abs() > EPS {
        out.inv_dv = Some(1.0 / dv);
    }
    out
}

/// Format like Python's `:g`: up to 6 significant digits, strips trailing
/// zeros and the decimal point when not needed (1.0 -> "1", 0.5 -> "0.5").
fn format_g(v: f64) -> String {
    let s = format!("{:.6}", v);
    let s = if s.contains('.') {
        s.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        s
    };
    if s.is_empty() || s == "-0" {
        "0".to_string()
    } else {
        s.to_string()
    }
}

/// One-line console form of a cursor readout.
pub fn format_readout(readout: &CursorReadout) -> String {
    fn eng(v: Option<f64>, unit: &str) -> String {
        match v {
            None => "-".to_string(),
            Some(0.0) => format!("0 {unit}"),
            Some(v) => {
                let a = v.abs();
                let (scaled, prefix) = if a < 1e-3 {
                    (v * 1e3, "m")
                } else if a >= 1e3 {
                    (v * 1e-3, "k")
                } else {
                    (v, "")
                };
                format!("{}{prefix}{unit}", format_g(scaled))
            }
        }
    }

    match readout.t1 {
        None => "no trace".to_string(),
        Some(t1) => {
            let left = format!(
                "t1={} v1={}",
                eng(Some(t1), "s"),
                eng(readout.v1, "V")
            );
            match readout.t2 {
                None => left,
                Some(t2) => {
                    let right = format!(
                        "t2={} v2={}",
                        eng(Some(t2), "s"),
                        eng(readout.v2, "V")
                    );
                    let mut extra = Vec::new();
                    if let Some(inv_dt) = readout.inv_dt {
                        extra.push(format!("1/dt={}", eng(Some(inv_dt), "Hz")));
                    }
                    if let Some(slope) = readout.slope {
                        extra.push(format!("slope={}", eng(Some(slope), "V/s")));
                    }
                    format!("{}  {}  {}", left, right, extra.join("  "))
                }
            }
        }
    }
}

/// Summary statistics of one trace.
#[derive(Debug, Clone)]
pub struct TraceStats {
    pub points: usize,
    pub mean: Option<f64>,
    pub rms: Option<f64>,
    pub min: Option<f64>,
    pub max: Option<f64>,
    pub p2p: Option<f64>,
    pub duty: Option<f64>,
    pub first_crossing_s: Option<f64>,
}

impl TraceStats {
    fn empty() -> Self {
        TraceStats {
            points: 0, mean: None, rms: None, min: None, max: None,
            p2p: None, duty: None, first_crossing_s: None,
        }
    }
}

pub fn trace_stats(
    times: &[f64],
    values: &[f64],
    threshold: Option<f64>,
) -> TraceStats {
    if values.is_empty() {
        return TraceStats::empty();
    }
    let vals: Vec<f64> = values.iter().map(|&v| v as f64).collect();
    let mean = vals.iter().sum::<f64>() / vals.len() as f64;
    let rms = (vals.iter().map(|&v| v * v).sum::<f64>() / vals.len() as f64).sqrt();
    let min = vals.iter().copied().fold(f64::INFINITY, f64::min);
    let max = vals.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let p2p = max - min;

    let mut out = TraceStats {
        points: vals.len(),
        mean: Some(mean),
        rms: Some(rms),
        min: Some(min),
        max: Some(max),
        p2p: Some(p2p),
        duty: None,
        first_crossing_s: None,
    };

    if let Some(thr) = threshold {
        if times.len() == vals.len() && vals.len() > 1 {
            let high = vals.iter().filter(|&&v| v >= thr).count();
            out.duty = Some(high as f64 / vals.len() as f64);
            if let Some(edge) = _crossing_time(times, &vals, thr, true) {
                out.first_crossing_s = Some(edge);
            }
        }
    }
    out
}

/// Time after `t_start` at which the trace enters and stays inside +/- tolerance
/// of `target`. Returns None if it never settles.
pub fn settling_time(
    times: &[f64],
    values: &[f64],
    target: f64,
    tolerance: f64,
    t_start: Option<f64>,
) -> Option<f64> {
    if times.len() != values.len() || times.len() < 2 {
        return None;
    }
    let band = target.abs() * tolerance;
    let mut lo = 0usize;
    if let Some(ts) = t_start {
        while lo < times.len() && times[lo] < ts {
            lo += 1;
        }
    }
    let t0 = if t_start.is_none() { times[0] } else { t_start.unwrap() };
    for i in lo..times.len() {
        if (values[i] - target).abs() <= band {
            // Confirm it stays put for the rest of the window.
            if values[i..].iter().all(|&v| (v - target).abs() <= band) {
                return Some(times[i] - t0);
            }
        }
    }
    None
}

#[derive(Debug, Clone)]
pub struct EdgeTiming {
    pub rise_s: Option<f64>,
    pub fall_s: Option<f64>,
    pub v_low: f64,
    pub v_high: f64,
}

pub fn rise_fall_time(
    times: &[f64],
    values: &[f64],
    low: f64,
    high: f64,
    fraction: f64,
) -> EdgeTiming {
    let span = high - low;
    if span <= 0.0 {
        return EdgeTiming {
            rise_s: None, fall_s: None, v_low: low, v_high: high,
        };
    }
    let lo_thr = low + span * fraction * 0.2;
    let hi_thr = low + span * fraction * 0.8;

    let mut rise = None;
    let mut fall = None;
    for i in 1..times.len() {
        let a = values[i - 1];
        let b = values[i];
        if rise.is_none() && a <= lo_thr && lo_thr <= b {
            rise = Some(_interp_cross(times[i - 1], a, times[i], b, lo_thr));
        }
        if rise.is_none() && a >= hi_thr && hi_thr >= b {
            rise = Some(_interp_cross(times[i - 1], a, times[i], b, hi_thr));
        }
        if fall.is_none() && a >= hi_thr && hi_thr >= b {
            fall = Some(_interp_cross(times[i - 1], a, times[i], b, hi_thr));
        }
    }
    if fall.is_none() && rise.is_some() {
        fall = rise;
    }
    EdgeTiming { rise_s: rise, fall_s: fall, v_low: low, v_high: high }
}

#[derive(Debug, Clone)]
pub struct StepMetrics {
    pub points: usize,
    pub v_start: Option<f64>,
    pub v_final: Option<f64>,
    pub step_v: Option<f64>,
    pub direction: Option<String>,
    pub delay_s: Option<f64>,
    pub rise_s: Option<f64>,
    pub overshoot_pct: f64,
    pub undershoot_pct: f64,
    pub settling_s: Option<f64>,
    pub slew_v_ms: Option<f64>,
}

pub fn step_metrics(times: &[f64], values: &[f64], tolerance: f64) -> StepMetrics {
    let mut out = StepMetrics {
        points: values.len(),
        v_start: None, v_final: None, step_v: None, direction: None,
        delay_s: None, rise_s: None, overshoot_pct: 0.0, undershoot_pct: 0.0,
        settling_s: None, slew_v_ms: None,
    };

    if times.len() != values.len() || values.len() < 3 {
        return out;
    }
    let n = values.len();
    let tail_start = n.saturating_sub(2usize.max(n / 10));
    let tail_start = tail_start.min(n - 1);
    let tail = &values[tail_start..];
    let v_start = values[0];
    let v_final: f64 = tail.iter().sum::<f64>() / tail.len() as f64;
    let span = v_final - v_start;
    out.v_start = Some(v_start);
    out.v_final = Some(v_final);
    out.step_v = Some(span);

    if span.abs() <= 1e-12 {
        return out; // flat trace: no step to measure
    }
    let rising = span > 0.0;
    out.direction = Some(if rising { "rising".to_string() } else { "falling".to_string() });

    let l10 = v_start + 0.10 * span;
    let l50 = v_start + 0.50 * span;
    let l90 = v_start + 0.90 * span;
    let t10 = _crossing_time(times, values, l10, rising);
    let t50 = _crossing_time(times, values, l50, rising);
    let t90 = _crossing_time(times, values, l90, rising);
    if let Some(t50) = t50 {
        out.delay_s = Some(t50 - times[0]);
    }
    if let (Some(t10), Some(t90)) = (t10, t90) {
        if t90 >= t10 {
            let rise = t90 - t10;
            out.rise_s = Some(rise);
            if rise > 0.0 {
                out.slew_v_ms = Some(0.8 * span.abs() / (rise * 1000.0));
            }
        }
    }

    // Overshoot only after the 50% crossing.
    let mut i_lo = 0usize;
    if let Some(t50) = t50 {
        for i in 1..times.len() {
            if times[i] >= t50 {
                i_lo = i;
                break;
            }
        }
    }
    let post = &values[i_lo..];
    if !post.is_empty() {
        if rising {
            out.overshoot_pct = (post.iter().copied().fold(f64::NEG_INFINITY, f64::max) - v_final) / span.abs() * 100.0;
            out.overshoot_pct = out.overshoot_pct.max(0.0);
        } else {
            out.overshoot_pct = (v_final - post.iter().copied().fold(f64::INFINITY, f64::min)) / span.abs() * 100.0;
            out.overshoot_pct = out.overshoot_pct.max(0.0);
        }
        let t_final = _crossing_time(times, values, v_final, rising);
        if let Some(t_final) = t_final {
            let mut i_fin = 0usize;
            for i in 1..times.len() {
                if times[i] >= t_final {
                    i_fin = i;
                    break;
                }
            }
            let tail_post = &values[i_fin..];
            if !tail_post.is_empty() {
                if rising {
                    out.undershoot_pct = (v_final - tail_post.iter().copied().fold(f64::INFINITY, f64::min)) / span.abs() * 100.0;
                } else {
                    out.undershoot_pct = (tail_post.iter().copied().fold(f64::NEG_INFINITY, f64::max) - v_final) / span.abs() * 100.0;
                }
                out.undershoot_pct = out.undershoot_pct.max(0.0);
            }
        }
    }

    out.settling_s = settling_time(times, values, v_final, tolerance, None);
    out
}

fn _interp_cross(t0: f64, v0: f64, t1: f64, v1: f64, level: f64) -> f64 {
    if v1 == v0 {
        return t0;
    }
    t0 + (level - v0) * (t1 - t0) / (v1 - v0)
}

fn _crossing_time(
    times: &[f64],
    values: &[f64],
    threshold: f64,
    rising: bool,
) -> Option<f64> {
    for i in 1..times.len() {
        let a = values[i - 1];
        let b = values[i];
        if rising && a < threshold && threshold <= b {
            return Some(_interp_cross(times[i - 1], a, times[i], b, threshold));
        }
        if !rising && a >= threshold && threshold > b {
            return Some(_interp_cross(times[i - 1], a, times[i], b, threshold));
        }
    }
    None
}

// ----------------------------------------------------------------------
// FFT
// ----------------------------------------------------------------------

/// A complex number (Python's `complex` has no std equivalent in Rust).
#[derive(Debug, Clone, Copy)]
struct C64 { re: f64, im: f64 }

impl C64 {
    fn new(re: f64, im: f64) -> Self { C64 { re, im } }
    fn norm_sqr(self) -> f64 { self.re * self.re + self.im * self.im }
    fn hypot(self) -> f64 { self.norm_sqr().sqrt() }
}

impl std::ops::Add for C64 {
    type Output = C64;
    fn add(self, rhs: C64) -> C64 { C64 { re: self.re + rhs.re, im: self.im + rhs.im } }
}

impl std::ops::Sub for C64 {
    type Output = C64;
    fn sub(self, rhs: C64) -> C64 { C64 { re: self.re - rhs.re, im: self.im - rhs.im } }
}

impl std::ops::Mul for C64 {
    type Output = C64;
    fn mul(self, rhs: C64) -> C64 {
        C64 {
            re: self.re * rhs.re - self.im * rhs.im,
            im: self.re * rhs.im + self.im * rhs.re,
        }
    }
}

#[derive(Debug, Clone)]
pub struct FftSpectrum {
    pub freqs: Vec<f64>,
    pub magnitude: Vec<f64>,
    pub dominant_hz: Option<f64>,
    pub n: usize,
    pub sample_rate_hz: f64,
    pub noise_floor: f64,
    pub bin_width_hz: f64,
}

pub fn fft_spectrum(
    times: &[f64],
    values: &[f64],
    window: &str,
) -> FftSpectrum {
    let empty = || FftSpectrum {
        freqs: Vec::new(), magnitude: Vec::new(), dominant_hz: None, n: 0,
        sample_rate_hz: 0.0, noise_floor: 0.0, bin_width_hz: 0.0,
    };

    if times.len() != values.len() || values.len() < 4 {
        return empty();
    }
    let t0 = times[0];
    let t1 = times[times.len() - 1];
    let duration = t1 - t0;
    if duration <= 0.0 {
        return empty();
    }

    let n = values.len();
    let step = if n > 1 { duration / (n - 1) as f64 } else { duration };
    // Radix-2 FFT needs a power-of-two length. Take the largest power of two
    // that fits entirely inside the solved window.
    let whole_cycles = (duration / step) as usize;
    let mut usable = 1usize;
    while usable * 2 <= whole_cycles.min(n) {
        usable *= 2;
    }
    if usable < 8 {
        return empty();
    }
    let samples: Vec<f64> = values[..usable].iter().map(|&v| v as f64).collect();
    let mean: f64 = samples.iter().sum::<f64>() / samples.len() as f64;
    let samples: Vec<f64> = samples.iter().map(|&v| v - mean).collect();

    let w: Vec<f64> = match window {
        "hann" => {
            let denom = (samples.len() - 1) as f64;
            (0..samples.len()).map(|i| {
                0.5 * (1.0 - (2.0 * PI * i as f64 / denom).cos())
            }).collect()
        }
        "blackman" => {
            let a0 = 0.35875;
            let a1 = 0.48829;
            let a2 = 0.14128;
            let a3 = 0.01168;
            let denom = (samples.len() - 1) as f64;
            (0..samples.len()).map(|i| {
                let x = 2.0 * PI * i as f64 / denom;
                a0 - a1 * x.cos() + a2 * (2.0 * x).cos() - a3 * (3.0 * x).cos()
            }).collect()
        }
        "rect" => vec![1.0; samples.len()],
        _ => panic!(
            "unsupported window '{window}' (use 'blackman', 'hann' or 'rect')"
        ),
    };

    let samples: Vec<f64> = samples.iter().zip(w.iter()).map(|(&s, &wi)| s * wi).collect();

    // Zero-pad to the next power of two.
    let mut n_fft = 1usize;
    while n_fft < 4 * samples.len() {
        n_fft *= 2;
    }
    let mut samples_padded: Vec<f64> = samples.clone();
    samples_padded.resize(n_fft, 0.0);
    let spec = _dft(&samples_padded);
    let half = n_fft / 2;
    let w_sum: f64 = w.iter().sum();
    let scale = 2.0 / if w_sum > 0.0 { w_sum } else { 1.0 };
    let mut mags: Vec<f64> = Vec::with_capacity(half);
    let mut freqs: Vec<f64> = Vec::with_capacity(half);
    for k in 0..half {
        let m = spec[k].hypot() * scale;
        mags.push(m);
        freqs.push(k as f64 / (n_fft as f64 * step));
    }

    // Drop DC, then find the peak.
    let mut dominant = None;
    let mut noise_floor = 0.0;
    if !mags.is_empty() {
        let body = &mags[1..];
        if !body.is_empty() {
            let peak = (1..mags.len())
                .max_by(|&a, &b| mags[a].partial_cmp(&mags[b]).unwrap())
                .unwrap_or(1);
            let bin_hz = if freqs.len() > 1 {
                freqs[1] - freqs[0]
            } else {
                0.0
            };
            dominant = _interp_peak(&freqs, &mags, peak, bin_hz);
            let others: Vec<f64> = mags.iter()
                .enumerate()
                .filter(|(i, _)| *i != peak + 1)
                .map(|(_, &m)| m)
                .collect();
            noise_floor = _median(&others);
            let top = mags[peak];
            if top > 0.0 {
                mags = mags.iter().map(|&m| m / top).collect();
            }
        }
    }
    let bin_width_hz = if freqs.len() > 1 { freqs[1] - freqs[0] } else { 0.0 };
    let sample_rate_hz = 1.0 / step;

    FftSpectrum {
        freqs, magnitude: mags, dominant_hz: dominant, n: n_fft,
        sample_rate_hz, noise_floor, bin_width_hz,
    }
}

fn _interp_peak(freqs: &[f64], mags: &[f64], peak_index: usize, bin_hz: f64) -> Option<f64> {
    let n = mags.len();
    if !(1 <= peak_index && peak_index < n - 1) || bin_hz <= 0.0 {
        return Some(freqs[peak_index]);
    }
    let a = mags[peak_index - 1];
    let b = mags[peak_index];
    let c = mags[peak_index + 1];
    let denom = a - 2.0 * b + c;
    if denom.abs() < EPS {
        return Some(freqs[peak_index]);
    }
    let mut delta = 0.5 * (a - c) / denom;
    if delta.abs() > 1.0 {
        delta = 0.0;
    }
    Some(freqs[peak_index] + delta * bin_hz)
}

fn _median(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut s = values.to_vec();
    s.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mid = s.len() / 2;
    if s.len() % 2 == 1 {
        s[mid]
    } else {
        0.5 * (s[mid - 1] + s[mid])
    }
}

fn _dft(samples: &[f64]) -> Vec<C64> {
    // Radix-2 FFT; input length must be a power of two (caller pads).
    let n = samples.len();
    if n & (n - 1) != 0 {
        panic!("FFT length must be a power of two");
    }
    let mut data: Vec<C64> = samples.iter().map(|&s| C64::new(s, 0.0)).collect();
    // Bit-reversal permutation.
    let mut j = 0usize;
    for i in 1..n {
        let mut bit = n >> 1;
        while j & bit != 0 {
            j ^= bit;
            bit >>= 1;
        }
        j |= bit;
        if i < j {
            data.swap(i, j);
        }
    }
    let mut length = 2usize;
    while length <= n {
        let ang = -2.0 * PI / length as f64;
        let wlen = C64::new(ang.cos(), ang.sin());
        let step = length >> 1;
        for i in (0..n).step_by(length) {
            let mut w = C64::new(1.0, 0.0);
            for k in i..(i + step) {
                let u = data[k];
                let v = data[k + step] * w;
                data[k] = u + v;
                data[k + step] = u - v;
                w = w * wlen;
            }
        }
        length <<= 1;
    }
    data
}

/// Total harmonic distortion as a fraction (0.01 = 1%).
pub fn thd(
    freqs: &[f64],
    magnitude: &[f64],
    fundamental_hz: Option<f64>,
    max_harmonic: i32,
) -> Option<f64> {
    if freqs.len() < 3 || magnitude.len() < 2 {
        return None;
    }
    let bin_hz = freqs[1] - freqs[0];
    if bin_hz <= 0.0 {
        return None;
    }
    let fundamental_hz = match fundamental_hz {
        Some(f) if f > 0.0 => f,
        _ => {
            let peak = (1..magnitude.len())
                .max_by(|&a, &b| magnitude[a].partial_cmp(&magnitude[b]).unwrap())
                .unwrap_or(1);
            freqs[peak]
        }
    };
    let nyquist = freqs[freqs.len() - 1];
    if fundamental_hz <= 0.0 {
        return None;
    }

    // A Blackman-windowed tone occupies about +/-4 bins around its centre.
    let half_width = 4.0 * bin_hz;

    fn lobe_amplitude(freqs: &[f64], magnitude: &[f64], center_hz: f64, half_width: f64) -> f64 {
        let mut total = 0.0;
        for (&f, &m) in freqs.iter().zip(magnitude.iter()) {
            if (f - center_hz).abs() <= half_width {
                total += m * m;
            }
        }
        total.sqrt()
    }

    let fundamental = lobe_amplitude(freqs, magnitude, fundamental_hz, half_width);
    if fundamental <= 0.0 {
        return None;
    }

    let mut harmonics = 0.0;
    let mut counted = 0i32;
    for n in 2..=max_harmonic {
        let f_n = n as f64 * fundamental_hz;
        if f_n > nyquist {
            break;
        }
        let amp = lobe_amplitude(freqs, magnitude, f_n, half_width);
        if amp > 0.0 {
            harmonics += amp * amp;
            counted += 1;
        }
    }
    if counted == 0 {
        return None;
    }
    Some((harmonics.sqrt()) / fundamental)
}

// ----------------------------------------------------------------------
// Bode
// ----------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct BodeResult {
    pub freqs: Vec<f64>,
    pub gain_db: Vec<f64>,
    pub phase_deg: Vec<f64>,
    pub peak_db: Option<f64>,
    pub peak_hz: Option<f64>,
}

pub fn bode_from_ac(
    freqs: &[f64],
    re: &[f64],
    im: &[f64],
    magnitude_ref: f64,
) -> BodeResult {
    if freqs.is_empty() || freqs.len() != re.len() || freqs.len() != im.len() {
        return BodeResult {
            freqs: Vec::new(), gain_db: Vec::new(), phase_deg: Vec::new(),
            peak_db: None, peak_hz: None,
        };
    }
    let mut gain_db = Vec::with_capacity(freqs.len());
    let mut phase = Vec::with_capacity(freqs.len());
    for (&a, &b) in re.iter().zip(im.iter()) {
        let mag = (a * a + b * b).sqrt();
        gain_db.push(
            if mag > EPS { 20.0 * (mag / magnitude_ref).log10() } else { -300.0 }
        );
        phase.push(b.atan2(a).to_degrees());
    }
    // Unwrap phase so the curve reads continuously instead of sawtoothing.
    let mut unwrapped = Vec::with_capacity(phase.len());
    let mut prev: Option<f64> = None;
    for &p in &phase {
        let mut p = p;
        if let Some(prev_p) = prev {
            while p - prev_p > 180.0 { p -= 360.0; }
            while p - prev_p < -180.0 { p += 360.0; }
        }
        unwrapped.push(p);
        prev = Some(p);
    }

    let peak_db = gain_db.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let peak_hz = if peak_db != f64::NEG_INFINITY {
        let idx = gain_db.iter().position(|&g| g == peak_db).unwrap_or(0);
        Some(freqs[idx])
    } else {
        None
    };
    let peak_db = if peak_db == f64::NEG_INFINITY { None } else { Some(peak_db) };

    BodeResult {
        freqs: freqs.to_vec(), gain_db, phase_deg: unwrapped, peak_db, peak_hz,
    }
}

#[derive(Debug, Clone)]
pub struct PhaseMarginResult {
    pub crossover_hz: Option<f64>,
    pub gain_at_crossover_db: Option<f64>,
    pub phase_margin_deg: Option<f64>,
    pub gain_margin_db: Option<f64>,
}

pub fn phase_margin(
    freqs: &[f64],
    gain_db: &[f64],
    phase_deg: &[f64],
) -> PhaseMarginResult {
    let empty = || PhaseMarginResult {
        crossover_hz: None, gain_at_crossover_db: None,
        phase_margin_deg: None, gain_margin_db: None,
    };

    if gain_db.is_empty() || gain_db.len() != phase_deg.len() {
        return empty();
    }

    let mut crossings: Vec<(f64, f64)> = Vec::new();
    for i in 1..gain_db.len() {
        if gain_db[i - 1] >= 0.0 && gain_db[i] < 0.0 {
            let frac = gain_db[i - 1] / (gain_db[i - 1] - gain_db[i]);
            crossings.push((
                (i - 1) as f64 + frac,
                freqs[i - 1] + frac * (freqs[i] - freqs[i - 1]),
            ));
        }
    }
    if crossings.is_empty() {
        return empty();
    }

    let (idx, f_cross) = crossings[0];
    let phase_at = phase_deg[idx as usize];
    let margin = 180.0 + phase_at;

    // Gain margin: where phase is -180 degrees.
    let mut gain_margin = None;
    for i in 1..phase_deg.len() {
        if phase_deg[i - 1] > -180.0 && phase_deg[i] <= -180.0 {
            let frac = (phase_deg[i - 1] + 180.0) / (phase_deg[i - 1] - phase_deg[i]);
            let g = gain_db[i - 1] + frac * (gain_db[i] - gain_db[i - 1]);
            gain_margin = Some(-g);
            break;
        }
    }

    PhaseMarginResult {
        crossover_hz: Some(f_cross),
        gain_at_crossover_db: Some(gain_db[idx as usize]),
        phase_margin_deg: Some(margin),
        gain_margin_db: gain_margin,
    }
}

// ----------------------------------------------------------------------
// Power
// ----------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct PowerMetrics {
    pub p_in_w: f64,
    pub p_out_w: f64,
    pub loss_w: f64,
    pub efficiency: Option<f64>,
}

pub fn power_metrics(
    v_in: f64, i_in: f64, v_out: f64, i_out: f64,
) -> PowerMetrics {
    let p_in = v_in * i_in;
    let p_out = v_out * i_out;
    let mut out = PowerMetrics {
        p_in_w: p_in, p_out_w: p_out, loss_w: p_in - p_out, efficiency: None,
    };
    if p_in > EPS {
        let eff = p_out / p_in;
        if 0.0 <= eff && eff <= 1.0 {
            out.efficiency = Some(eff);
        }
    }
    out
}

/// Ohm's law over a trace - the honest way to get a current trace in SPICE.
pub fn series_current(
    _times: &[f64],
    voltages: &[f64],
    resistance: f64,
) -> Vec<f64> {
    if resistance <= 0.0 {
        return vec![0.0; voltages.len()];
    }
    voltages.iter().map(|&v| v as f64 / resistance).collect()
}
