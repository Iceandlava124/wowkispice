/*
 * gpio_model.rs - port of bridge/gpio_model.py.
 *
 * Digital GPIO behaviour for mixed-signal co-simulation: an MCU pin becomes
 * a real independent voltage source in the SPICE netlist, so the analog
 * solver sees real switching voltages instead of a comment line.  What that
 * voltage does is declared by a *pin profile*, not extracted by executing
 * the binary - the port keeps that stance verbatim from the Python module.
 *
 * The port covers: profile normalisation and validation, the SPICE source
 * card, logic-level reduction of a sampled waveform, per-pin analysis
 * (transitions, duty, min/max), measured frequency, the one-line human
 * description, the pin-direction heuristic, and pin_map - the panel behind
 * "pin mapping shown visually".
 *
 * PARITY CONTRACT
 *
 *   tests/test_firmware_gpio.py    TestGpioProfile (spice_card,
 *                                  describe_pin, rejection of nonsense) and
 *                                  TestLogicAnalysis (analyze_pin,
 *                                  measured_frequency).  The Intel HEX/ELF
 *                                  parsing, JSON profile parsing and the
 *                                  TestGpioCosimEndToEnd class in that file
 *                                  belong to firmware/ or need the live
 *                                  ngspice solver and are NOT ported here.
 *   tests/test_editor_workflow.py  the three pin_map tests in
 *                                  TestPinMappingAndSerial (the
 *                                  serial-console tests are unrelated).
 *   No other test file imports gpio_model; bridge/cad_engine.py and
 *   ui/schematic_editor.py are callers, not contracts.
 *
 * crates/parity/src/bin/parity_gpio_model.rs and
 * crates/parity/python/gpio_model/parity_gpio_model.py cross-check both
 * implementations over a shared battery that is NOT transcribed from those
 * tests: index-keyed profile specs, SPICE cards, describe strings, sampled
 * waveforms and pin_map fixtures (the arduino fixture is driven through the
 * REAL cad_engine on the Python side, so this file's is_mcu transcription
 * cannot drift from bridge/cad_engine.py unnoticed).
 *
 * WHAT IS NOT PORTED, AND WHY IT IS NOT A BUG
 *
 *   1. Anything needing a live ngspice solver is OUT OF SCOPE:
 *      TestGpioCosimEndToEnd runs NgSpiceEngine for real, and cad_engine's
 *      compile_netlist (which calls spice_card/describe_pin while building
 *      the netlist) lives in bridge/cad_engine.py, which is not part of
 *      this port.  pin_map itself is pure logic over a model interface, so
 *      it IS ported - against the PinMapModel trait below.  Note that
 *      cad_engine's _resolve_nets() currently names every pin, so `wired`
 *      is true for every row of a real model today; the battery exercises
 *      the None-net path through a stub because that is where pin_map's
 *      code can still see it.
 *   2. firmware.parse_pin_profile (JSON text -> profile dicts) is
 *      firmware.rs's contract, not this module's.  This port takes a typed
 *      ProfileSpec - the field-by-field mapping of that JSON, the way the
 *      control_law port maps its spec onto wosp_law_input.
 *   3. Python's duck typing on spec values is narrowed to types (mode is a
 *      string, the numbers are f64), so these Python behaviours are
 *      unreachable through this API and are outside the contract:
 *      a non-string mode (Python: str(5).lower() ->
 *      "unsupported GPIO mode '5'"), a numeric-string vhigh/freq/duty
 *      (Python: float("3.3") succeeds), a string or None level (Python:
 *      int("1") / TypeError), and a level of NaN/inf (Python's int() raises
 *      there; the port would read NaN as HIGH).  vhigh/freq/duty of NaN ARE
 *      in contract and behave exactly as Python (vhigh raises with
 *      "got nan", freq NaN passes the `<= 0` check and yields a PULSE with
 *      nan fields, duty NaN raises) - the battery pins all three down.
 *   4. `level` is f64 because Python's `int(level)` accepts both JSON ints
 *      and floats, truncating toward zero (0.7 -> LOW, 1.9 -> HIGH).
 *   5. str.lower()/str.upper()/str.isdigit() are ASCII-folded here
 *      (py_lower_ascii, str::to_ascii_uppercase, is_ascii_digit): pin names
 *      are ASCII identifiers, the same contract pycompat's py_trim states.
 *   6. A profile dict holding ONLY unknown keys counts as "present" in
 *      Python's truthiness; ProfileSpec cannot express unknown keys, so a
 *      spec counts as present here when it carries at least one recognised
 *      field.  Identical for every well-formed profile.
 *   7. pin_map's control_laws values are typed ControlLawView, so Python's
 *      `isinstance(law, dict)` guard (a non-dict law value behaves as no
 *      law) is unreachable.  A law dict without a "pin" key behaves as no
 *      law on both sides, and a law without "sense_net" renders 'None' in
 *      the behaviour string on both sides.
 *   8. NaN waveform samples are excluded from the battery: the port
 *      transcribes Python min/max literally (a NaN stays where CPython
 *      leaves it), but the parity driver compares numbers by parsing them
 *      and NaN never equals itself.
 *
 * PYCOMPAT GAPS FILLED LOCALLY (private to this file, as agreed with the
 * module's owner report): pycompat.rs has no fixed-point formatter, so
 * py_fmt_fixed0() implements Python's `f"{x:.0f}"` (round-half-even on the
 * exact binary value, sign-of-zero preserved); and it has only
 * py_lower_ascii, so the upper fold uses str::to_ascii_uppercase directly.
 */

use crate::pycompat::{py_g, py_lower_ascii, py_repr, round_half_even};
use std::collections::{BTreeMap, HashMap};
use std::fmt;

/// Logic midpoint of a 3.3 V pin (Python: DEFAULT_THRESHOLD).
pub const DEFAULT_THRESHOLD: f64 = 1.65;
/// Declared high level of a profile without an explicit vhigh.
pub const DEFAULT_VHIGH: f64 = 3.3;
/// Python's default edge_time for spice_card.
pub const DEFAULT_EDGE_TIME: f64 = 1e-7;

// ---------------------------------------------------------------- errors

/// Carries Python's ValueError messages verbatim (tests and the parity
/// battery compare them as text).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GpioError(String);

impl GpioError {
    fn new(msg: String) -> Self {
        GpioError(msg)
    }

    pub fn message(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for GpioError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for GpioError {}

// ------------------------------------------------------- profile spec/out

/// The *input* side: one pin profile as declared (JSON maps field-by-field
/// onto this struct), with every field optional exactly as the Python dict's
/// `.get(key, default)` reads it.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ProfileSpec {
    pub mode: Option<String>,
    pub level: Option<f64>,
    pub vhigh: Option<f64>,
    pub freq_hz: Option<f64>,
    pub duty: Option<f64>,
    pub phase_s: Option<f64>,
}

impl ProfileSpec {
    /// Python truthiness of the profile dict as pin_map tests it: a spec
    /// counts as present when it carries at least one recognised field
    /// (see header note 6 for the unknown-keys narrowing).
    pub fn is_empty(&self) -> bool {
        self.mode.is_none()
            && self.level.is_none()
            && self.vhigh.is_none()
            && self.freq_hz.is_none()
            && self.duty.is_none()
            && self.phase_s.is_none()
    }
}

/// The *output* side of normalize_profile: exactly the keys Python's
/// normalised dict carries - a static profile has no freq/duty/phase and a
/// square profile has no level, which this enum makes unrepresentable.
#[derive(Debug, Clone, PartialEq)]
pub enum Profile {
    Static {
        vhigh: f64,
        level: i64, // 0 or 1
    },
    Square {
        vhigh: f64,
        freq_hz: f64,
        duty: f64,
        phase_s: f64,
    },
}

/// Fill in defaults and reject nonsense, so callers never guard twice.
///
/// Validation order is Python's: mode, then vhigh, then (per mode) level or
/// freq/duty - a spec with two faults reports the first one Python would.
pub fn normalize_profile(spec: Option<&ProfileSpec>) -> Result<Profile, GpioError> {
    let empty = ProfileSpec::default();
    let spec = spec.unwrap_or(&empty);

    let mode_raw = spec.mode.clone().unwrap_or_else(|| "static".to_string());
    let mode = py_lower_ascii(&mode_raw); // Python: str(...).lower()
    if mode != "static" && mode != "square" {
        return Err(GpioError::new(format!(
            "unsupported GPIO mode '{}' (use 'static' or 'square')",
            mode
        )));
    }

    // Python: float(spec.get("vhigh", DEFAULT_VHIGH)); `not 0 < vhigh <= 24`
    let vhigh = spec.vhigh.unwrap_or(DEFAULT_VHIGH);
    if !(vhigh > 0.0 && vhigh <= 24.0) {
        return Err(GpioError::new(format!(
            "vhigh must be 0..24 V, got {}",
            py_repr(vhigh)
        )));
    }

    if mode == "static" {
        // Python: 1 if int(spec.get("level", 0)) else 0 - int() on a float
        // truncates toward zero (see header note 4 for the NaN/inf edge).
        let level = if spec.level.unwrap_or(0.0).trunc() != 0.0 { 1 } else { 0 };
        return Ok(Profile::Static { vhigh, level });
    }

    let freq = spec.freq_hz.unwrap_or(1.0);
    let duty = spec.duty.unwrap_or(0.5);
    if freq <= 0.0 {
        return Err(GpioError::new(format!(
            "freq_hz must be > 0, got {}",
            py_repr(freq)
        )));
    }
    if !(duty > 0.0 && duty <= 1.0) {
        return Err(GpioError::new(format!(
            "duty must be in (0, 1], got {}",
            py_repr(duty)
        )));
    }
    Ok(Profile::Square {
        vhigh,
        freq_hz: freq,
        duty,
        phase_s: spec.phase_s.unwrap_or(0.0),
    })
}

/// SPICE source card for a GPIO pin.
///
/// static -> "DC 3.3"
/// square -> "PULSE(0 3.3 0 100n 100n 500u 1m)"  (tr, tf, on-time, period)
///
/// Python's default edge_time is DEFAULT_EDGE_TIME, passed explicitly here
/// (no default arguments in Rust; the C port does the same).
pub fn spice_card(spec: Option<&ProfileSpec>, edge_time: f64) -> Result<String, GpioError> {
    let s = normalize_profile(spec)?;
    match s {
        Profile::Static { vhigh, level } => {
            Ok(if level != 0 {
                format!("DC {}", py_g(vhigh))
            } else {
                "DC 0".to_string()
            })
        }
        Profile::Square { vhigh, freq_hz, duty, phase_s } => {
            let period = 1.0 / freq_hz;
            let on_time = period * duty;
            // Python: tr = min(edge_time, period / 20.0).  Spelled out as
            // `y < x ? y : x` so a NaN operand keeps Python's choice -
            // Rust's f64::min would silently drop the NaN instead.
            let p20 = period / 20.0;
            let tr = if p20 < edge_time { p20 } else { edge_time };
            Ok(format!(
                "PULSE(0 {} {} {} {} {} {})",
                py_g(vhigh),
                py_g(phase_s),
                py_g(tr),
                py_g(tr),
                py_g(on_time),
                py_g(period)
            ))
        }
    }
}

/// Every declared pin drives its net.
pub fn is_output_pin(_profile: Option<&ProfileSpec>) -> bool {
    true
}

// ---------------------------------------------------------- logic analysis

/// Reduce a sampled pin waveform to (time, level) transitions.
///
/// Returns only transitions plus the initial state, which is what a GPIO
/// inspector should show rather than 10k samples.
pub fn logic_levels(times: &[f64], values: &[f64], threshold: f64) -> Vec<(f64, bool)> {
    if times.len() != values.len() || times.is_empty() {
        return Vec::new();
    }
    let mut level = values[0] >= threshold;
    let mut transitions = vec![(times[0], level)];
    for (t, v) in times.iter().zip(values.iter()).skip(1) {
        let new_level = *v >= threshold;
        if new_level != level {
            transitions.push((*t, new_level));
            level = new_level;
        }
    }
    transitions
}

/// Per-pin summary: logic levels, transition count, duty cycle, min/max
/// level (Python's analyze_pin return dict, field for field).
#[derive(Debug, Clone, PartialEq)]
pub struct PinSummary {
    pub points: usize,
    pub transitions: usize,
    pub duty: f64,
    pub v_min: Option<f64>,
    pub v_max: Option<f64>,
    pub levels: Vec<(f64, bool)>,
}

/// Duty is the fraction of the observed window spent above the threshold.
pub fn analyze_pin(times: &[f64], values: &[f64], threshold: f64) -> PinSummary {
    if times.len() != values.len() || times.len() < 2 {
        // Note Python reports points as len(values) even when the lengths
        // disagree, and omits v_min/v_max even for a single sample.
        return PinSummary {
            points: values.len(),
            transitions: 0,
            duty: 0.0,
            v_min: None,
            v_max: None,
            levels: Vec::new(),
        };
    }

    let levels = logic_levels(times, values, threshold);
    let mut high_time = 0.0;
    for i in 0..levels.len().saturating_sub(1) {
        if levels[i].1 {
            high_time += levels[i + 1].0 - levels[i].0;
        }
    }
    let window = times[times.len() - 1] - times[0];
    let duty = if window > 0.0 { high_time / window } else { 0.0 };

    // Python's min()/max() keep the FIRST element and replace only on a
    // strict </>, so a NaN in the data stays put exactly where CPython
    // leaves it (f64::min/max would drop it).  Transcribed literally.
    let mut v_min = values[0];
    let mut v_max = values[0];
    for &v in &values[1..] {
        if v < v_min {
            v_min = v;
        }
        if v > v_max {
            v_max = v;
        }
    }

    PinSummary {
        points: values.len(),
        transitions: levels.len().saturating_sub(1),
        duty,
        v_min: Some(v_min),
        v_max: Some(v_max),
        levels,
    }
}

/// Frequency in Hz from rising edges, or None if fewer than two.
pub fn measured_frequency(times: &[f64], values: &[f64], threshold: f64) -> Option<f64> {
    let levels = logic_levels(times, values, threshold);
    // A rise is a high transition whose predecessor is low - including the
    // initial state when it starts high (i == 0), as Python's enumerate
    // condition says.
    let mut rises: Vec<f64> = Vec::new();
    for (i, (t, lvl)) in levels.iter().enumerate() {
        if *lvl && (i == 0 || !levels[i - 1].1) {
            rises.push(*t);
        }
    }
    if rises.len() < 2 {
        return None;
    }
    let mut sum = 0.0;
    for pair in rises.windows(2) {
        sum += pair[1] - pair[0];
    }
    let period = sum / (rises.len() - 1) as f64;
    if period > 0.0 {
        Some(1.0 / period)
    } else {
        None
    }
}

// ------------------------------------------------------------- describe

/// One-line human description of a pin's declared behaviour.
pub fn describe_pin(pin: &str, spec: Option<&ProfileSpec>) -> Result<String, GpioError> {
    let s = normalize_profile(spec)?;
    Ok(match s {
        Profile::Static { vhigh, level } => format!(
            "{}: {} @ {} V",
            pin,
            if level != 0 { "HIGH" } else { "LOW" },
            py_g(vhigh)
        ),
        Profile::Square { vhigh, freq_hz, duty, phase_s: _ } => format!(
            "{}: square {} Hz, {}% duty @ {} V",
            pin,
            py_g(freq_hz),
            py_fmt_fixed0(duty * 100.0),
            py_g(vhigh)
        ),
    })
}

/// Python's `f"{x:.0f}"`: round-half-to-even on the exact binary value,
/// with Python's sign-of-zero preservation (format(-0.4, '.0f') is "-0").
/// pycompat.rs has no fixed-point formatter - see the header's PYCOMPAT
/// GAPS note.  Only describe_pin's `duty * 100` reaches this, which is
/// finite and non-negative for a normalised profile, but the sign is
/// handled anyway so the helper never lies.
fn py_fmt_fixed0(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".to_string() } else { "-inf".to_string() };
    }
    let r = round_half_even(x);
    if r == 0 && x.is_sign_negative() {
        "-0".to_string()
    } else {
        r.to_string()
    }
}

// ------------------------------------------------------- pin direction

// Pins that are supply or ground rather than signal.  Python keeps "gnd"
// in the set even though pin_direction uppercases first, so it can never
// match; the entry is kept so the port exposes the same list.
pub const POWER_PINS: [&str; 11] = [
    "GND", "0", "gnd", "VCC", "5V", "3V3", "VIN", "VCC3V3", "AREF", "NRST", "EN",
];

// Python defines this tuple but never reads it (pin_direction classifies by
// the startswith("A") + isdigit rule instead); kept under the same name so
// a future caller finds it here too.
pub const ANALOG_PINS: [&str; 8] = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7"];

/// Best-effort pin direction from its name.
///
/// Heuristic, and labelled as such: only the device datasheet knows for
/// sure.  Anything ambiguous is reported as "bidirectional" rather than
/// guessed confidently, because a wrong 'output' on an input pin makes a
/// pin-mapping view actively misleading.
pub fn pin_direction(pin: &str) -> &'static str {
    // Python: p = str(pin or "").upper().  The port takes &str, so the
    // `or ""` only mattered for None/non-str pins (typed out, header 3).
    let p = pin.to_ascii_uppercase();
    if POWER_PINS.contains(&p.as_str()) {
        return "power";
    }
    // Python: p.startswith("A") and p[1:].isdigit() - Arduino analog pins.
    // p[1:] drops the first CODE POINT (str slicing), so the port skips one
    // char rather than one byte; isdigit() is ASCII here (header note 5).
    let rest: String = p.chars().skip(1).collect();
    if p.starts_with('A') && !rest.is_empty() && rest.chars().all(|c| c.is_ascii_digit()) {
        return "analog";
    }
    if p.starts_with("ADC") {
        return "analog";
    }
    // Python has this startswith branch AND an unconditional fallback that
    // both return "bidirectional"; the redundancy is preserved verbatim
    // rather than collapsed, so a diff against the Python source still
    // shows every family the original classified deliberately.
    if [
        "D", "GPIO", "PA", "PB", "PC", "PD", "PE", "PF", "PG", "PH", "LED", "SCL", "SDA", "TX",
        "RX", "SCK", "MOSI", "MISO",
    ]
    .iter()
    .any(|pre| p.starts_with(pre))
    {
        return "bidirectional";
    }
    "bidirectional"
}

// --------------------------------------------------------------- pin_map

/// One component as pin_map sees it: its type string and its pin table.
/// pin_map reads only the pin NAMES (Python: `sorted(comp.pins)`); the BTreeMap
/// yields them in the same sorted order Python's sorted() produces.
pub struct ComponentView<'a> {
    pub comp_type: &'a str,
    pub pins: &'a BTreeMap<String, String>,
}

/// The model side of pin_map: what model.components.get() and
/// model._resolve_nets()[0] give the Python function.  The ground list from
/// _resolve_nets is dropped because pin_map ignores it.
pub trait PinMapModel {
    fn component(&self, comp_id: &str) -> Option<ComponentView<'_>>;
    /// (comp_id, pin) -> net name, exactly as Python's net_of dict.
    fn resolve_nets(&self) -> HashMap<(String, String), String>;
}

/// A control law as pin_map reads it: `law.get("pin")` decides the branch,
/// `law.get("sense_net")` is quoted in the behaviour string (missing ->
/// Python renders the None as 'None').  Typed, so Python's
/// `isinstance(law, dict)` guard is unreachable - header note 7.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ControlLawView {
    pub pin: Option<String>,
    pub sense_net: Option<String>,
}

/// One row of the pin-mapping panel (Python's row dict, field for field).
#[derive(Debug, Clone, PartialEq)]
pub struct PinMapRow {
    pub pin: String,
    pub net: Option<String>,
    pub direction: &'static str,
    pub role: String,
    pub behaviour: String,
    pub wired: bool,
}

/// Per-pin view of an MCU: what it is, what drives it, what it reads.
///
/// This is the panel behind "pin mapping shown visually".  It reports only
/// what the document actually declares - an unwired pin is listed as such
/// rather than omitted, so a missing wire is visible instead of invisible.
///
/// Branch order is Python's: control-law pin first (it outranks even a
/// power pin), then power, then a declared profile, then "declared but
/// undriven".  `gpio_profiles`/`control_laws` are plain maps: Python's
/// `x or {}` treats None and {} identically, and an absent comp_id is the
/// same as no entry.
pub fn pin_map<M: PinMapModel>(
    model: &M,
    comp_id: &str,
    gpio_profiles: &HashMap<String, HashMap<String, ProfileSpec>>,
    control_laws: &HashMap<String, ControlLawView>,
) -> Result<Vec<PinMapRow>, GpioError> {
    let comp = match model.component(comp_id) {
        Some(c) => c,
        None => return Ok(Vec::new()),
    };
    // Transcribed from bridge/cad_engine.py: is_mcu() uppercases into
    // MCU_TYPES.  cad_engine itself is not part of this port; the parity
    // battery calls the REAL Python is_mcu, so drift of this list shows up
    // as a parity failure rather than a silent divergence.
    if !is_mcu(comp.comp_type) {
        return Ok(Vec::new());
    }

    let profile = gpio_profiles.get(comp_id);
    let law = control_laws.get(comp_id);
    let law_pin = law.and_then(|l| l.pin.as_deref());
    let net_of = model.resolve_nets();

    let mut rows = Vec::new();
    for pin in comp.pins.keys() {
        let key = (comp_id.to_string(), pin.clone());
        let net = net_of.get(&key).cloned();
        let wired = net.is_some();
        let direction = pin_direction(pin);
        let spec = profile.and_then(|p| p.get(pin));

        let (role, behaviour) = if Some(pin.as_str()) == law_pin {
            (
                "closed-loop control output".to_string(),
                format!(
                    "control law reading '{}'",
                    law.and_then(|l| l.sense_net.as_deref()).unwrap_or("None")
                ),
            )
        } else if direction == "power" {
            (
                "power".to_string(),
                if net.as_deref() == Some("0") {
                    "ground / supply rail".to_string()
                } else {
                    // Python f"rail on net {net}" renders None as 'None'.
                    format!("rail on net {}", net.as_deref().unwrap_or("None"))
                },
            )
        } else if spec.map(|s| !s.is_empty()).unwrap_or(false) {
            ("output".to_string(), describe_pin(pin, spec)?)
        } else {
            (
                "declared but undriven".to_string(),
                "no GPIO profile - idles LOW in simulation".to_string(),
            )
        };

        rows.push(PinMapRow {
            pin: pin.clone(),
            net,
            direction,
            role,
            behaviour,
            wired,
        });
    }
    Ok(rows)
}

/// Component types that behave as an MCU for netlisting purposes -
/// verbatim from bridge/cad_engine.py MCU_TYPES (see pin_map).
const MCU_TYPES: [&str; 11] = [
    "MCU",
    "ESP32",
    "ESP32S3",
    "ARDUINO_UNO",
    "ARDUINO_NANO",
    "ARDUINO_MEGA",
    "STM32F103",
    "STM32F407",
    "STM32L4",
    "RP2040",
    "CUSTOM",
];

/// Python: `str(comp_type or "").upper() in MCU_TYPES`.  The `or ""` only
/// mattered for None/non-str types (typed out); the fold is ASCII.
fn is_mcu(comp_type: &str) -> bool {
    MCU_TYPES.contains(&comp_type.to_ascii_uppercase().as_str())
}
