/*
 * gpio_model.rs - port of bridge/gpio_model.py.
 *
 * Digital GPIO behaviour for mixed-signal co-simulation. An MCU pin becomes a
 * real independent voltage source in the SPICE netlist; what that voltage does
 * is declared by a pin profile (JSON), not extracted by executing the binary.
 *
 * Pure computation over numbers and strings: no solver, no Qt, no filesystem.
 * Unit-testable headlessly. Core stays dependency-free (no serde_json).
 *
 * Profile spec (per pin):
 *   {"mode": "static", "level": 1,                 "vhigh": 3.3}
 *   {"mode": "square", "freq_hz": 1000, "duty": 0.5, "vhigh": 3.3}
 *   {"mode": "square", "freq_hz": 10,  "duty": 0.02, "vhigh": 5.0, "phase_s": 0.001}
 */

use std::collections::BTreeMap;

pub const DEFAULT_VHIGH: f64 = 3.3;
pub const DEFAULT_THRESHOLD: f64 = 1.65; // logic midpoint of a 3.3 V pin

/// Normalised pin profile. Filled defaults + rejected nonsense, so callers
/// never guard twice.
#[derive(Debug, Clone, Default)]
pub struct ProfileSpec {
    pub mode: String,
    pub vhigh: f64,
    pub level: Option<i32>,
    pub freq_hz: Option<f64>,
    pub duty: Option<f64>,
    pub phase_s: Option<f64>,
}

/// Build a `ProfileSpec` from raw fields, mirroring `normalize_profile`.
/// Returns an error on invalid input (Python raises ValueError).
pub fn build_profile(
    mode: &str,
    vhigh: Option<f64>,
    level: Option<i32>,
    freq_hz: Option<f64>,
    duty: Option<f64>,
    phase_s: Option<f64>,
) -> Result<ProfileSpec, String> {
    let mode_l = mode.to_lowercase();
    let mode = match mode_l.as_str() {
        "static" | "square" => mode_l,
        _ => return Err(format!(
            "unsupported GPIO mode '{}' (use 'static' or 'square')",
            mode
        )),
    };

    let vhigh = vhigh.unwrap_or(DEFAULT_VHIGH);
    if !(0.0 < vhigh && vhigh <= 24.0) {
        return Err(format!("vhigh must be 0..24 V, got {}", vhigh));
    }

    let mut out = ProfileSpec {
        mode: mode.clone(),
        vhigh,
        level: None,
        freq_hz: None,
        duty: None,
        phase_s,
    };
    if mode == "static" {
        out.level = Some(level.unwrap_or(0).rem_euclid(2));
    } else {
        let freq = freq_hz.unwrap_or(1.0);
        let duty = duty.unwrap_or(0.5);
        if freq <= 0.0 {
            return Err(format!("freq_hz must be > 0, got {}", freq));
        }
        if !(0.0 < duty && duty <= 1.0) {
            return Err(format!("duty must be in (0, 1], got {}", duty));
        }
        out.freq_hz = Some(freq);
        out.duty = Some(duty);
    }
    Ok(out)
}

/// SPICE source card for a GPIO pin.
///
/// static -> "DC 3.3" / "DC 0"
/// square -> "PULSE(0 3.3 0 100n 100n 500u 1m)"  (tr, tf, on-time, period)
pub fn spice_card(
    mode: &str,
    vhigh: Option<f64>,
    level: Option<i32>,
    freq_hz: Option<f64>,
    duty: Option<f64>,
    phase_s: Option<f64>,
    edge_time: f64,
) -> Result<String, String> {
    let s = build_profile(mode, vhigh, level, freq_hz, duty, phase_s)?;
    let vhigh = s.vhigh;
    if s.mode == "static" {
        if s.level == Some(1) {
            return Ok(format!("DC {}", g(vhigh)));
        }
        return Ok("DC 0".to_string());
    }

    let period = 1.0 / s.freq_hz.unwrap();
    let on_time = period * s.duty.unwrap();
    // Keep edges fast relative to the period but sane on CPU ngspice
    let tr = edge_time.min(period / 20.0);
    Ok(format!(
        "PULSE(0 {} {} {} {} {} {})",
        g(vhigh),
        g(s.phase_s.unwrap_or(0.0)),
        g(tr),
        g(tr),
        g(on_time),
        g(period)
    ))
}

fn g(v: f64) -> String {
    // Python's %g: shortest round-trip, strip trailing zeros and the decimal
    // point if not needed. Switches to exponential when exponent < -4 or >= 6.
    let abs_v = v.abs();
    let exp = if abs_v == 0.0 { 0 } else { abs_v.log10().floor() as i32 };
    let use_exp = exp < -4 || exp >= 6;
    if use_exp {
        // Exponential notation: like {:.5e} but strip trailing zeros
        let s = format!("{:.5e}", v);
        let parts: Vec<&str> = s.split('e').collect();
        let mantissa = parts[0].trim_end_matches('0').trim_end_matches('.');
        let exp_part = parts[1];
        // Normalize exponent to at least 2 digits with sign
        let (sign, num) = if exp_part.starts_with('+') || exp_part.starts_with('-') {
            (&exp_part[..1], &exp_part[1..])
        } else {
            ("+", exp_part)
        };
        let num_padded = if num.len() >= 2 { num.to_string() } else { format!("0{}", num) };
        format!("{}e{}{}", mantissa, sign, num_padded)
    } else {
        let s = format!("{:.10}", v);
        let s = if s.contains('.') {
            s.trim_end_matches('0').trim_end_matches('.').to_string()
        } else {
            s
        };
        if s.is_empty() || s == "-0" {
            "0".to_string()
        } else {
            s
        }
    }
}

/// Every declared pin drives its net.
pub fn is_output_pin() -> bool {
    true
}

/// Reduce a sampled pin waveform to (time, level) transitions.
///
/// Returns only transitions plus the initial state.
pub fn logic_levels(times: &[f64], values: &[f64], threshold: f64) -> Vec<(f64, bool)> {
    if times.len() != values.len() || times.is_empty() {
        return Vec::new();
    }
    let mut level = values[0] >= threshold;
    let mut transitions = vec![(times[0], level)];
    for (&t, &v) in times.iter().skip(1).zip(values.iter().skip(1)) {
        let new_level = v >= threshold;
        if new_level != level {
            transitions.push((t, new_level));
            level = new_level;
        }
    }
    transitions
}

/// Per-pin summary: logic levels, transition count, duty cycle, min/max level.
///
/// Duty is the fraction of the observed window spent above the threshold.
#[derive(Debug, Clone)]
pub struct PinAnalysis {
    pub points: usize,
    pub transitions: usize,
    pub duty: f64,
    pub v_min: Option<f64>,
    pub v_max: Option<f64>,
    pub levels: Vec<(f64, bool)>,
}

pub fn analyze_pin(times: &[f64], values: &[f64], threshold: f64) -> PinAnalysis {
    if times.len() != values.len() || times.len() < 2 {
        return PinAnalysis {
            points: values.len(),
            transitions: 0,
            duty: 0.0,
            v_min: None,
            v_max: None,
            levels: Vec::new(),
        };
    }

    let transitions = logic_levels(times, values, threshold);
    let mut high_time = 0.0;
    for i in 0..transitions.len().saturating_sub(1) {
        if transitions[i].1 {
            high_time += transitions[i + 1].0 - transitions[i].0;
        }
    }
    let window = times[times.len() - 1] - times[0];
    let duty = if window > 0.0 { high_time / window } else { 0.0 };

    PinAnalysis {
        points: values.len(),
        transitions: transitions.len().saturating_sub(1),
        duty,
        v_min: Some(values.iter().cloned().fold(f64::INFINITY, f64::min)),
        v_max: Some(values.iter().cloned().fold(f64::NEG_INFINITY, f64::max)),
        levels: transitions,
    }
}

/// Frequency in Hz from rising edges, or None if fewer than two.
pub fn measured_frequency(times: &[f64], values: &[f64], threshold: f64) -> Option<f64> {
    let transitions = logic_levels(times, values, threshold);
    let mut rises: Vec<f64> = Vec::new();
    for (i, (t, level)) in transitions.iter().enumerate() {
        if *level && (i == 0 || !transitions[i - 1].1) {
            rises.push(*t);
        }
    }
    if rises.len() < 2 {
        return None;
    }
    let period: f64 = rises
        .windows(2)
        .map(|w| w[1] - w[0])
        .sum::<f64>()
        / (rises.len() - 1) as f64;
    if period > 0.0 {
        Some(1.0 / period)
    } else {
        None
    }
}

/// One-line human description of a pin's declared behaviour.
pub fn describe_pin(
    pin: &str,
    mode: &str,
    vhigh: Option<f64>,
    level: Option<i32>,
    freq_hz: Option<f64>,
    duty: Option<f64>,
    phase_s: Option<f64>,
) -> Result<String, String> {
    let s = build_profile(mode, vhigh, level, freq_hz, duty, phase_s)?;
    if s.mode == "static" {
        return Ok(format!(
            "{}: {} @ {} V",
            pin,
            if s.level == Some(1) { "HIGH" } else { "LOW" },
            g(s.vhigh)
        ));
    }
    Ok(format!(
        "{}: square {} Hz, {}% duty @ {} V",
        pin,
        g(s.freq_hz.unwrap()),
        (s.duty.unwrap() * 100.0) as u32,
        g(s.vhigh)
    ))
}

// Pins that are supply or ground rather than signal.
const _POWER_PINS: [&str; 11] = [
    "GND", "0", "gnd", "VCC", "5V", "3V3", "VIN", "VCC3V3", "AREF", "NRST", "EN",
];
const _ANALOG_PINS: [&str; 8] = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7"];

/// Best-effort pin direction from its name.
///
/// Heuristic, and labelled as such: only the device datasheet knows for sure.
/// Anything ambiguous is reported as "bidirectional" rather than guessed
/// confidently, because a wrong 'output' on an input pin makes a pin-mapping
/// view actively misleading.
pub fn pin_direction(pin: &str) -> String {
    let p = pin.to_uppercase();
    if _POWER_PINS.contains(&p.as_str()) {
        return "power".to_string();
    }
    if p.starts_with('A') && p.get(1..).map_or(false, |s| s.chars().all(char::is_numeric)) {
        return "analog".to_string();
    }
    if p.starts_with("ADC") {
        return "analog".to_string();
    }
    if p.starts_with("D")
        || p.starts_with("GPIO")
        || p.starts_with("PA")
        || p.starts_with("PB")
        || p.starts_with("PC")
        || p.starts_with("PD")
        || p.starts_with("PE")
        || p.starts_with("PF")
        || p.starts_with("PG")
        || p.starts_with("PH")
        || p.starts_with("LED")
        || p.starts_with("SCL")
        || p.starts_with("SDA")
        || p.starts_with("TX")
        || p.starts_with("RX")
        || p.starts_with("SCK")
        || p.starts_with("MOSI")
        || p.starts_with("MISO")
    {
        return "bidirectional".to_string();
    }
    "bidirectional".to_string()
}

/// Per-pin view of an MCU: what it is, what drives it, what it reads.
///
/// BLOCKED: depends on `cad_engine::is_mcu` and `model._resolve_nets()`,
/// neither of which is ported yet (wave 2+). Returns an empty vec as a
/// placeholder so the module compiles standalone.
pub fn pin_map(
    _model: &(),
    _comp_id: &str,
    _gpio_profiles: &BTreeMap<String, BTreeMap<String, f64>>,
    _control_laws: &BTreeMap<String, BTreeMap<String, f64>>,
) -> Vec<PinMapRow> {
    // Placeholder until cad_engine + model are ported.
    Vec::new()
}

/// Placeholder row type for the pin-mapping panel (wave 2+).
#[derive(Debug, Clone)]
pub struct PinMapRow {
    pub pin: String,
    pub net: Option<String>,
    pub direction: String,
    pub role: String,
    pub behaviour: String,
    pub wired: bool,
}
