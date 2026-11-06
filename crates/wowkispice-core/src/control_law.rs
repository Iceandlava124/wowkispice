/*
 * control_law.rs - Rust port of bridge/control_law.py.
 *
 * Executable MCU firmware behaviour for mixed-signal co-simulation: the law
 * reads the *simulated* feedback node and returns the pin voltage for that
 * instant, so the analog solver sees a pin that reacts to the circuit.  What
 * is still not claimed: the compiled .hex/.elf binary is not executed - the
 * decision logic and its constants are real, read out of the actual C source
 * by law_from_firmware_source().
 *
 * PARITY CONTRACT
 *
 *   tests/test_control_law_unit.py          spec normalisation, decision table
 *   tests/test_adc_conversion.py            ADC clamp/round at the boundaries
 *   tests/test_cosim_control.py             firmware import, divider semantics
 *                                           (control-law/firmware-import/
 *                                           divider classes only; the
 *                                           netlist/end-to-end classes need
 *                                           the ngspice solver and are NOT
 *                                           part of this port)
 *
 * crates/wowkispice-core/tests/test_control_law.rs is a line-for-line port of
 * those assertions (same test function names, so the two suites stay
 * greppable against each other), and
 * crates/parity/{src/bin/parity_control_law.rs, python/parity_control_law.py}
 * cross-check this implementation against bridge/control_law.py over a
 * battery neither suite was transcribed from - a re-written test can be
 * wrong in the same way as the code it tests; a cross-implementation diff
 * cannot be.
 *
 * native/src/control_law.c is the audited C port of the same file and was
 * used as the reference for subtle behaviour; Python remains the contract
 * where the two differ (divergences are listed at the bottom of this
 * comment).
 *
 * WHAT THIS DOES NOT MODEL, AND WHY IT IS NOT A BUG
 *
 * firmware/esp32_buck_controller/src/main.c does four things this law does
 * not (verbatim from the Python module, which explains each in full):
 *
 *   1. ADC_OVERSAMPLE_N = 16.  Deliberately NOT modelled: those 16 reads are
 *      microseconds apart in real time while solver timesteps here are
 *      sub-microsecond, so "average the last 16 samples" has no defensible
 *      analogue in this loop.  What it means in practice: the modelled loop
 *      switches more often than the firmware would.
 *   2. adc_cali line-fitting calibration.  This law assumes a flat
 *      counts = volts/vref*full_scale mapping with vref = 3.3 V.  On real
 *      silicon the calibration curve is neither flat nor exactly 3.3 V.
 *   3. The attenuation setting itself is not read from the source.
 *   4. ESP_ERROR_CHECK guards on init failure have no counterpart.
 *
 * tests/test_control_law_unit.py::TestFidelityGap and the TestFidelityGap of
 * tests/test_cosim_control.py pin this gap deliberately: they assert main.c
 * still declares ADC_OVERSAMPLE_N and still calls adc_cali.  If someone
 * removes them, the test fails and forces this comment to be revisited.  A
 * fidelity gap nobody can notice is how a model rots.
 *
 * WHICH NET IS `sense_net`? THIS IS THE WHOLE BALLGAME.
 *
 * The firmware's #define ADC_LOW_THRESHOLD 1995 / ADC_HIGH_THRESHOLD 2030 are
 * raw counts measured AT THE ADC PIN, and its own comment says so.  The
 * divider is already reflected in them.  Passing the undivided output node as
 * `sense_net` and leaving divider=1.0 regulates to 1.62 V instead of 3.24 V -
 * exactly the divider ratio, silently.  implied_output_voltages() exists so a
 * caller can check before trusting a run.
 *
 * SPEC (JSON, per MCU) maps onto LawInput field-by-field:
 *
 *   {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
 *    "target_v": 3.3, "hysteresis_v": 0.04, "divider": 0.5,
 *    "vhigh": 3.3, "vref": 3.3, "adc_bits": 12}
 *
 * `divider` is the attenuation from the sense net to the ADC pin, so
 * v_pin = sense_net * divider.  `adc_bits`/`vref` quantise the read exactly as
 * a real ADC would, so the modelled thresholds are counts, not float volts.
 *
 * SUBTLE SEMANTICS REPRODUCED HERE (each is a place a naive port silently
 * diverges from CPython; all pinned against CPython during the C port):
 *
 *   - Python's round() is round-half-to-EVEN; use pycompat::round_half_even,
 *     never f64::round.  to_counts does max(0, min(full,
 *     int(round(volts/vref*full)))) in that operation order.
 *   - Error messages are Python f-strings: interpolated floats go through
 *     pycompat::py_repr (Python str()/repr()), integers through Rust's
 *     Display (same as Python's int formatting).  describe() uses
 *     pycompat::py_g for f"{x:g}".
 *   - `not 0 < vhigh <= 24` rejects NaN, so vhigh/vref/divider/adc_bits
 *     checks reject it too (a NaN fails `x > 0.0 && x <= 24.0` naturally).
 *     `if target_v <= 0` lets NaN THROUGH in Python - and therefore here.
 *   - normalize_law: explicit low/high counts win ONLY if BOTH are present
 *     (Python: `if low is None or high is None` recomputes both).
 *   - decide() for hysteretic: counts < low -> HIGH, counts > high -> LOW,
 *     else hold the previous level; thresholds inclusive (holding on the
 *     boundary is what stops chatter).
 *   - decide() for pwm: reads history_time[-1] BEFORE update() appends
 *     (update appends after decide), i.e. the previous timestep's time;
 *     Python's % on floats yields [0, period), fmod can go negative - fixed
 *     up here exactly as Python's float.__mod does.
 *   - stats(): duty = count(v > vhigh/2)/samples; counts_* are None when
 *     samples == 0 (Option in Rust).
 *   - regulation_error(): empty input -> all fields None; n == 1 slices the
 *     single sample away and then divides by zero in Python
 *     (ZeroDivisionError) - this port rejects it with a LawError carrying
 *     that fact, the same trade the C port makes (status instead of
 *     exception).
 *   - Firmware import: the #define scan is a hand transcription of Python's
 *     re `^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)\s+([^\r\n/]+)` (MULTILINE);
 *     the core builds dependency-free, so there is no regex crate.  The text
 *     is read with Python's universal-newline translation (\r\n and lone \r
 *     both become \n) and UTF-8-lossy decoding (Python: encoding="utf-8",
 *     errors="replace") before the scan sees it.
 *   - law_from_firmware_source: round(target, 4)/round(hyst, 4) via
 *     pycompat::round4; divider-zero guard `midpoint / divider if divider
 *     else midpoint` (truthiness: only 0.0/-0.0 are false, NaN divides).
 *   - describe_law() never raises: returns `<invalid control law: {exc}>`.
 *
 * KNOWN DIVERGENCES FROM THE PYTHON ORIGINAL (deliberate, type-driven):
 *
 *   - LawInput models key-ABSENT as None (Python's `spec.get(key, default)`).
 *     A key PRESENT with the value None (`{"kind": None}`, `{"vhigh": None}`)
 *     is inexpressible in Rust's types: Python would compute str(None) for
 *     kind ("unsupported law kind 'none'") or raise TypeError for float(None)
 *     on the numeric fields.  The C port's presence flags make the same
 *     choice (its header claims absent and None behave identically; for
 *     present-None Python actually raises TypeError - noted here, never
 *     exercised by any test or parity case).
 *   - implied_pin_voltages() on a pwm spec: Python raises KeyError, whose
 *     str() is `'low_counts'` (probed against CPython) - reproduced verbatim
 *     as the LawError message, so describe_law-style rendering matches.  The
 *     C port invented a different message here ("spec has no
 *     low_counts/high_counts (kind ...") - Python is the contract.
 *   - _parse_int takes ASCII digits only; Python's \d also matches other
 *     Unicode decimal digits (int() would parse them).  Firmware sources are
 *     ASCII; the C port documents the same limitation.  Overflow past i64
 *     yields None (skip) where Python's int() is unbounded.
 *   - Non-ASCII whitespace: Python's \s and str.strip() include e.g. U+00A0;
 *     the ASCII-only scan and pycompat::py_trim do not.  pycompat documents
 *     this stance for trim; the #define scan matches the C port's.
 */

use crate::pycompat;
use std::fmt;

/// Defaults of the Python module, verbatim.
pub const DEFAULT_VHIGH: f64 = 3.3;
pub const DEFAULT_VREF: f64 = 3.3;
pub const DEFAULT_ADC_BITS: i32 = 12;

/// `LAW_KINDS = ("hysteretic", "pwm")`.
pub const LAW_KINDS: [&str; 2] = ["hysteretic", "pwm"];

// ----------------------------------------------------------------------
// Errors
// ----------------------------------------------------------------------

/// Raised when a control law spec or firmware source cannot be used.
///
/// Python: `class ControlLawError(ValueError)`.  The `message` is the exact
/// text Python's `str(exc)` would produce for the same failure - the parity
/// harness compares error messages as text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LawError {
    message: String,
}

impl LawError {
    pub fn new(message: impl Into<String>) -> Self {
        LawError { message: message.into() }
    }

    /// The exact Python message string.
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl fmt::Display for LawError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for LawError {}

// ----------------------------------------------------------------------
// Spec input and normalisation
// ----------------------------------------------------------------------

/// The two law kinds, `LAW_KINDS`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LawKind {
    Hysteretic,
    Pwm,
}

impl LawKind {
    pub fn as_str(self) -> &'static str {
        match self {
            LawKind::Hysteretic => "hysteretic",
            LawKind::Pwm => "pwm",
        }
    }
}

impl fmt::Display for LawKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// A raw, caller-supplied spec.  Every field is optional, mirroring the
/// Python side's untyped dict where a key is either absent or a value (see
/// the header comment for the present-None case).  Defaults live in
/// normalize_law().
///
/// `source_counts` is the nested {"low": .., "high": ..} that
/// law_from_firmware_source() records.  normalize_law() deliberately DROPS
/// it (as Python does); it only survives on the input so that
/// law_from_firmware_source_exact() can copy it into low_counts/high_counts.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct LawInput {
    pub kind: Option<String>,
    pub pin: Option<String>,
    pub sense_net: Option<String>,
    pub target_v: Option<f64>,
    pub hysteresis_v: Option<f64>,
    pub vhigh: Option<f64>,
    pub vref: Option<f64>,
    pub adc_bits: Option<i32>,
    pub divider: Option<f64>,
    pub low_counts: Option<i64>,
    pub high_counts: Option<i64>,
    pub carrier_hz: Option<f64>,
    pub duty_gain: Option<f64>,
    pub source: Option<String>,
    pub source_counts: Option<(i64, i64)>,
}

/// A normalised spec: every field the chosen kind needs is filled, the rest
/// is None (Python's normalized dict simply lacks those keys).
#[derive(Debug, Clone, PartialEq)]
pub struct LawSpec {
    pub kind: LawKind,
    pub pin: String,
    pub sense_net: String,
    pub target_v: f64,
    pub vhigh: f64,
    pub vref: f64,
    pub adc_bits: i32,
    pub divider: f64,
    /// hysteretic only (None for pwm, where Python's dict has no such key).
    pub hysteresis_v: Option<f64>,
    pub low_counts: Option<i64>,
    pub high_counts: Option<i64>,
    /// pwm only.
    pub carrier_hz: Option<f64>,
    pub duty_gain: Option<f64>,
    /// echoed when the spec named a firmware source (verbatim, not stripped).
    pub source: Option<String>,
}

/// Fill defaults and reject nonsense so callers never guard twice.
///
/// Returns a new spec; never mutates the input.  Python's `normalize_law(None)`
/// maps to `normalize_law(&LawInput::default())`.
///
/// Check order is the Python function's order, because the first failing
/// check is the message a test (or the parity battery) sees.
pub fn normalize_law(input: &LawInput) -> Result<LawSpec, LawError> {
    // str(spec.get("kind", "hysteretic")).lower()
    let kind_str =
        pycompat::py_lower_ascii(input.kind.as_deref().unwrap_or("hysteretic"));
    if kind_str != "hysteretic" && kind_str != "pwm" {
        return Err(LawError::new(format!(
            "unsupported law kind '{}' (use {})",
            kind_str,
            LAW_KINDS.join(" or ")
        )));
    }
    let kind = if kind_str == "pwm" {
        LawKind::Pwm
    } else {
        LawKind::Hysteretic
    };

    // str(spec.get("pin", "")).strip()
    let pin = pycompat::py_trim(input.pin.as_deref().unwrap_or("")).to_string();
    if pin.is_empty() {
        return Err(LawError::new(
            "law needs a 'pin' naming the MCU output pin",
        ));
    }

    // str(spec.get("sense_net", "")).strip()
    let sense_net =
        pycompat::py_trim(input.sense_net.as_deref().unwrap_or("")).to_string();
    if sense_net.is_empty() {
        return Err(LawError::new(format!(
            "law for {} needs a 'sense_net' - the analog net the firmware \
             reads back (e.g. 'vout')",
            pin
        )));
    }

    // `not 0 < vhigh <= 24` - NaN fails this, as in Python.
    let vhigh = input.vhigh.unwrap_or(DEFAULT_VHIGH);
    if !(vhigh > 0.0 && vhigh <= 24.0) {
        return Err(LawError::new(format!(
            "vhigh must be 0..24 V, got {}",
            pycompat::py_repr(vhigh)
        )));
    }
    let vref = input.vref.unwrap_or(DEFAULT_VREF);
    if !(vref > 0.0 && vref <= 24.0) {
        return Err(LawError::new(format!(
            "vref must be 0..24 V, got {}",
            pycompat::py_repr(vref)
        )));
    }

    let adc_bits = input.adc_bits.unwrap_or(DEFAULT_ADC_BITS);
    if !(8..=24).contains(&adc_bits) {
        return Err(LawError::new(format!(
            "adc_bits must be 8..24, got {}",
            adc_bits
        )));
    }

    let divider = input.divider.unwrap_or(1.0);
    if !(divider > 0.0 && divider <= 1.0) {
        return Err(LawError::new(format!(
            "divider must be in (0, 1], got {}",
            pycompat::py_repr(divider)
        )));
    }

    // `if target_v <= 0` - unlike the checks above, NaN slips past in Python.
    let target_v = input.target_v.unwrap_or(3.3);
    if target_v <= 0.0 {
        return Err(LawError::new(format!(
            "target_v must be > 0, got {}",
            pycompat::py_repr(target_v)
        )));
    }

    let mut spec = LawSpec {
        kind,
        pin,
        sense_net,
        target_v,
        vhigh,
        vref,
        adc_bits,
        divider,
        hysteresis_v: None,
        low_counts: None,
        high_counts: None,
        carrier_hz: None,
        duty_gain: None,
        source: input.source.clone(),
    };

    if kind == LawKind::Hysteretic {
        let hyst = input.hysteresis_v.unwrap_or(0.04);
        if hyst <= 0.0 {
            return Err(LawError::new(format!(
                "hysteresis_v must be > 0, got {}",
                pycompat::py_repr(hyst)
            )));
        }
        if hyst >= target_v {
            return Err(LawError::new(format!(
                "hysteresis_v ({}) must be smaller than target_v ({})",
                pycompat::py_repr(hyst),
                pycompat::py_repr(target_v)
            )));
        }

        // Explicit counts win - that is how a spec imported from firmware
        // source keeps the file's exact decision boundary.  If EITHER is
        // missing both are recomputed, exactly as Python's
        // `if low is None or high is None`.
        let (low, high) = match (input.low_counts, input.high_counts) {
            (Some(low), Some(high)) => (low, high),
            _ => (
                to_counts_raw((target_v - hyst) * divider, vref, adc_bits),
                to_counts_raw((target_v + hyst) * divider, vref, adc_bits),
            ),
        };
        if low >= high {
            return Err(LawError::new(format!(
                "threshold counts must increase, got low={} high={}",
                low, high
            )));
        }
        spec.hysteresis_v = Some(hyst);
        spec.low_counts = Some(low);
        spec.high_counts = Some(high);
    } else {
        let freq = input.carrier_hz.unwrap_or(20000.0);
        if freq <= 0.0 {
            return Err(LawError::new(format!(
                "carrier_hz must be > 0, got {}",
                pycompat::py_repr(freq)
            )));
        }
        let gain = input.duty_gain.unwrap_or(0.25);
        if gain <= 0.0 {
            return Err(LawError::new(format!(
                "duty_gain must be > 0, got {}",
                pycompat::py_repr(gain)
            )));
        }
        spec.carrier_hz = Some(freq);
        spec.duty_gain = Some(gain);
    }

    // source is echoed verbatim; source_counts is dropped, as in Python.
    Ok(spec)
}

/// Volts -> ADC counts, clipped to the converter's full scale.
///
/// Python `_to_counts`: `max(0, min(full, int(round(volts / vref * full))))`
/// in that operation order, with round-half-to-even (pycompat).
pub fn to_counts_raw(volts: f64, vref: f64, bits: i32) -> i64 {
    let full = (1i64 << bits) - 1;
    let r = pycompat::round_half_even(volts / vref * full as f64);
    r.max(0).min(full)
}

// ----------------------------------------------------------------------
// The executable law
// ----------------------------------------------------------------------

/// One-line run summary; identical shape for every law kind so callers can
/// print it.  Python: the dict returned by `law.stats()`.
#[derive(Debug, Clone, PartialEq)]
pub struct LawStats {
    pub kind: LawKind,
    pub pin: String,
    pub sense_net: String,
    pub samples: usize,
    pub switches: i64,
    pub duty: f64,
    /// None when there are no samples (Python reports None, not 0).
    pub counts_min: Option<i64>,
    pub counts_max: Option<i64>,
    pub counts_last: Option<i64>,
    /// "HIGH" or "LOW" (Python's `final_level`).
    pub final_level: &'static str,
}

/// The executable law - the Python class hierarchy (ControlLaw +
/// HystereticLaw/PwmLaw) as one struct, the way the C port does it.  The two
/// kinds share the ADC front end, the telemetry and the state a caller needs
/// to report a run honestly, and differ only in decide().  The kind-specific
/// fields simply sit unused for the other kind (Python would not even have
/// them on the instance).
#[derive(Clone)]
pub struct ControlLaw {
    pub spec: LawSpec,
    pub pin: String,
    pub sense_net: String,
    pub vhigh: f64,
    pub divider: f64,
    pub vref: f64,
    pub adc_bits: i32,
    pub level: bool,
    pub switch_count: i64,
    /// hysteretic only
    pub low_counts: i64,
    pub high_counts: i64,
    /// pwm only
    pub carrier_hz: f64,
    pub duty_gain: f64,
    pub target_counts: i64,
    pub duty: f64,
    pub history_time: Vec<f64>,
    pub history_pin: Vec<f64>,
    pub history_counts: Vec<i64>,
}

/// Build the right law for a (raw or already-normalized) spec.
///
/// Python's make_law() normalizes and then each subclass normalizes again
/// inside __init__; normalize_law is idempotent on its own output, so one
/// normalisation here is equivalent (proven by the parity battery, which
/// feeds specs both raw and pre-normalized).
pub fn make_law(input: &LawInput) -> Result<ControlLaw, LawError> {
    ControlLaw::from_spec(normalize_law(input)?)
}

impl ControlLaw {
    /// Build from an already-normalized spec (Python's
    /// `HystereticLaw(normalized)` / `PwmLaw(normalized)`).
    pub fn from_spec(spec: LawSpec) -> Result<ControlLaw, LawError> {
        let pin = spec.pin.clone();
        let sense_net = spec.sense_net.clone();
        let vhigh = spec.vhigh;
        let divider = spec.divider;
        let vref = spec.vref;
        let adc_bits = spec.adc_bits;

        let (low_counts, high_counts) = match (spec.low_counts, spec.high_counts)
        {
            (Some(low), Some(high)) => (low, high),
            _ => (0, 0),
        };
        let (carrier_hz, duty_gain) = match (spec.carrier_hz, spec.duty_gain) {
            (Some(freq), Some(gain)) => (freq, gain),
            _ => (0.0, 0.0),
        };

        let mut law = ControlLaw {
            spec,
            pin,
            sense_net,
            vhigh,
            divider,
            vref,
            adc_bits,
            level: false,
            switch_count: 0,
            low_counts,
            high_counts,
            carrier_hz,
            duty_gain,
            target_counts: 0,
            duty: 0.0,
            history_time: Vec::new(),
            history_pin: Vec::new(),
            history_counts: Vec::new(),
        };
        if law.spec.kind == LawKind::Pwm {
            law.target_counts = to_counts_raw(
                law.spec.target_v * law.divider,
                law.vref,
                law.adc_bits,
            );
        }
        Ok(law)
    }

    /// Converter full scale, `(1 << adc_bits) - 1` (Python property).
    pub fn full_scale(&self) -> i64 {
        (1i64 << self.adc_bits) - 1
    }

    /// Sense node -> ADC counts, including the divider and clipping.
    pub fn to_counts(&self, sense_v: f64) -> i64 {
        to_counts_raw(sense_v * self.divider, self.vref, self.adc_bits)
    }

    /// One decision: feedback counts -> logic level.
    ///
    /// For the hysteretic kind this reads `self.level` to hold the previous
    /// state inside the band.  For the pwm kind it reads the last history
    /// timestamp - the PREVIOUS timestep, because update() appends after
    /// decide() runs - and updates `self.duty`.
    pub fn decide(&mut self, counts: i64) -> bool {
        if self.spec.kind == LawKind::Hysteretic {
            // The firmware's own branch order: counts < low -> drive HIGH,
            // counts > high -> drive LOW, otherwise hold.  Thresholds are
            // inclusive: a sample sitting exactly on low_counts or
            // high_counts holds, which is what stops the regulator
            // chattering on the boundary.
            if counts < self.low_counts {
                return true;
            }
            if counts > self.high_counts {
                return false;
            }
            return self.level;
        }

        // pwm: error = (target - counts) / max(1, target);
        // duty = clamp(error * gain, 0, 1) - Python's
        // `max(0.0, min(1.0, error * gain))`, min first.  Rust's f64::min/
        // max return the non-NaN operand, so NaN here lands on 1.0 exactly
        // as Python's min/max do (probed: max(0.0, min(1.0, nan)) == 1.0).
        let denom = if self.target_counts > 1 {
            self.target_counts as f64
        } else {
            1.0
        };
        let error = (self.target_counts as f64 - counts as f64) / denom;
        self.duty = (error * self.duty_gain).min(1.0).max(0.0);

        let period = 1.0 / self.carrier_hz;
        // update() appends AFTER decide(), so this is the previous time.
        let t = self.history_time.last().copied().unwrap_or(0.0);
        // Python's % on floats always yields [0, period): fmod keeps the
        // sign of the dividend, so negative times are shifted up.  Python
        // also folds fmod's -0.0 to +0.0 (probed: (-0.0) % 3.0 == 0.0);
        // `+ 0.0` does the same here (the two compare identically anyway).
        let mut phase = t % period;
        if phase < 0.0 {
            phase += period;
        }
        let phase = phase + 0.0;
        phase < self.duty * period
    }

    /// One solver timestep.  Returns the pin voltage for this instant and
    /// records telemetry for the run report (Python's update(), whose
    /// `time_s` defaults to 0.0 - pass 0.0 explicitly here).
    pub fn update(&mut self, sense_v: f64, time_s: f64) -> f64 {
        let counts = self.to_counts(sense_v);
        let previous = self.level;
        self.level = self.decide(counts);
        if self.level != previous {
            self.switch_count += 1;
        }
        self.history_time.push(time_s);
        self.history_counts.push(counts);
        let pin = if self.level { self.vhigh } else { 0.0 };
        self.history_pin.push(pin);
        pin
    }

    /// One-line human description (Python's describe() on each subclass).
    pub fn describe(&self) -> String {
        if self.spec.kind == LawKind::Hysteretic {
            format!(
                "hysteretic on {}: HIGH below {} counts, LOW above {} counts, \
                 hold in between (target {} V via {}x divider)",
                self.sense_net,
                self.low_counts,
                self.high_counts,
                pycompat::py_g(self.spec.target_v),
                pycompat::py_g(self.divider),
            )
        } else {
            format!(
                "PWM on {}: {} Hz carrier, duty = min(1, gain {} x error \
                 toward {} V)",
                self.sense_net,
                pycompat::py_g(self.carrier_hz),
                pycompat::py_g(self.duty_gain),
                pycompat::py_g(self.spec.target_v),
            )
        }
    }

    /// Run summary; identical shape for every law kind so callers can print
    /// it (Python's stats()).
    pub fn stats(&self) -> LawStats {
        let samples = self.history_pin.len();
        let midpoint = self.vhigh / 2.0;
        let high = self
            .history_pin
            .iter()
            .filter(|&&v| v > midpoint)
            .count();
        LawStats {
            kind: self.spec.kind,
            pin: self.pin.clone(),
            sense_net: self.sense_net.clone(),
            samples,
            switches: self.switch_count,
            duty: if samples > 0 {
                high as f64 / samples as f64
            } else {
                0.0
            },
            counts_min: self.history_counts.iter().copied().min(),
            counts_max: self.history_counts.iter().copied().max(),
            counts_last: self.history_counts.last().copied(),
            final_level: if self.level { "HIGH" } else { "LOW" },
        }
    }
}

/// One-line human description; never raises, for console display.
///
/// Python catches (ControlLawError, KeyError, TypeError, ValueError) around
/// make_law(spec).describe(); in Rust only LawError can surface here.
pub fn describe_law(input: &LawInput) -> String {
    match make_law(input) {
        Ok(law) => law.describe(),
        Err(exc) => format!("<invalid control law: {}>", exc),
    }
}

// ----------------------------------------------------------------------
// Firmware import
// ----------------------------------------------------------------------

/// Constants pulled out of a C firmware source: Python's
/// `{"low": int, "high": int, "pin": "GPIO18"}`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FirmwareConstants {
    pub low: i64,
    pub high: i64,
    /// "GPIO18" - the pin slot is already spelled this way by Python.
    pub pin: String,
}

fn is_ascii_ws(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c)
}

fn is_ident_start(b: u8) -> bool {
    b.is_ascii_alphabetic() || b == b'_'
}

fn is_ident_cont(b: u8) -> bool {
    b.is_ascii_alphanumeric() || b == b'_'
}

/// The Python regex `^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)\s+([^\r\n/]+)`
/// with re.MULTILINE, as an iterator over non-overlapping matches.
///
/// `^` anchors at a line start and `\s*` may cross blank lines, so "#define"
/// is only a match when every character back to a line start is whitespace.
/// The value stops at CR, LF or '/' (to cut a // comment) and must be at
/// least one character.  Matches are non-overlapping: scanning resumes past
/// the value (finditer's semantics), so a "#define" that lives *inside* a
/// value is never rescanned.
///
/// Hand-rolled because the core crate builds without dependencies (see the
/// header comment).  The C port's wosp_next_define() is the same
/// transcription and was validated against CPython's re.
struct DefineMatches<'a> {
    text: &'a [u8],
    pos: usize,
}

impl<'a> DefineMatches<'a> {
    fn new(text: &'a str) -> Self {
        DefineMatches { text: text.as_bytes(), pos: 0 }
    }
}

impl<'a> Iterator for DefineMatches<'a> {
    type Item = (&'a str, &'a str);

    fn next(&mut self) -> Option<(&'a str, &'a str)> {
        let t = self.text;
        let len = t.len();
        let mut i = self.pos;
        while i + 7 <= len {
            if &t[i..i + 7] != b"#define" {
                i += 1;
                continue;
            }
            // `^` with MULTILINE: walk back through whitespace; a line
            // start (or the start of the text) must be reached.
            let mut line_start = i == 0;
            let mut k = i;
            while k > 0 && is_ascii_ws(t[k - 1]) {
                if t[k - 1] == b'\n' {
                    line_start = true;
                    break;
                }
                k -= 1;
            }
            if k == 0 {
                line_start = true;
            }
            if !line_start {
                i += 1;
                continue;
            }

            let mut j = i + 7;
            let ws_start = j;
            while j < len && is_ascii_ws(t[j]) {
                j += 1;
            }
            if j == ws_start {
                i += 1;
                continue; // \s+ needs at least one
            }
            if j >= len || !is_ident_start(t[j]) {
                i += 1;
                continue;
            }
            let name_start = j;
            while j < len && is_ident_cont(t[j]) {
                j += 1;
            }
            let name_end = j;

            let ws_start = j;
            while j < len && is_ascii_ws(t[j]) {
                j += 1;
            }
            if j == ws_start {
                i += 1;
                continue; // \s+ needs at least one
            }

            let value_start = j;
            while j < len && t[j] != b'\r' && t[j] != b'\n' && t[j] != b'/' {
                j += 1;
            }
            if j == value_start {
                i += 1;
                continue; // [^\r\n/]+ needs at least one
            }

            self.pos = j;
            // Slices of valid UTF-8 cut at ASCII boundaries - both decode.
            let name = std::str::from_utf8(&t[name_start..name_end]).ok()?;
            let value = std::str::from_utf8(&t[value_start..j]).ok()?;
            return Some((name, value));
        }
        self.pos = len;
        None
    }
}

/// Python's `_parse_int`: `re.search(r"(\d+)\s*$", text)` - the digit run
/// immediately before any trailing whitespace (which is also the leftmost
/// such run, because anything between it and the end would have to be
/// whitespace).  Accepts plain decimals and the GPIO_NUM_n spellings.
///
/// ASCII digits only, and None on overflow past i64 (see the header
/// comment); firmware constants are small.
fn parse_int(text: &str) -> Option<i64> {
    let b = text.as_bytes();
    let mut end = b.len();
    while end > 0 && is_ascii_ws(b[end - 1]) {
        end -= 1;
    }
    if end == 0 || !b[end - 1].is_ascii_digit() {
        return None;
    }
    let mut start = end;
    while start > 0 && b[start - 1].is_ascii_digit() {
        start -= 1;
    }
    std::str::from_utf8(&b[start..end]).ok()?.parse::<i64>().ok()
}

/// Read a file as CPython's text mode would: bytes in, universal-newline
/// translation (\r\n -> \n, then a lone \r -> \n), then a UTF-8 lossy decode
/// (Python: encoding="utf-8", errors="replace" - replacement can only ever
/// rewrite non-ASCII bytes, and the #define scan matches ASCII exclusively,
/// so lossy and raw are indistinguishable here).
fn read_text(path: &str) -> Result<String, LawError> {
    if !std::path::Path::new(path).exists() {
        return Err(LawError::new(format!(
            "firmware source not found: {}",
            path
        )));
    }
    let raw = std::fs::read(path).map_err(|exc| {
        LawError::new(format!(
            "cannot read firmware source {}: {}",
            path, exc
        ))
    })?;
    let mut out: Vec<u8> = Vec::with_capacity(raw.len());
    let mut i = 0;
    while i < raw.len() {
        if raw[i] == b'\r' {
            if i + 1 < raw.len() && raw[i + 1] == b'\n' {
                i += 1;
            }
            out.push(b'\n');
        } else {
            out.push(raw[i]);
        }
        i += 1;
    }
    Ok(String::from_utf8_lossy(&out).into_owned())
}

/// Pull the ADC thresholds and gate pin out of a C firmware source.
///
/// Returns low/high/pin for whatever was found.  Fails if the file is
/// missing or holds none of the names - we would rather say so than silently
/// simulate a made-up controller.  Last definition of a name wins (Python's
/// finditer loop overwrites `found`).
pub fn read_firmware_constants(
    path: &str,
) -> Result<FirmwareConstants, LawError> {
    let text = read_text(path)?;

    let mut low: Option<i64> = None;
    let mut high: Option<i64> = None;
    let mut pin: Option<i64> = None;
    for (name, value) in DefineMatches::new(&text) {
        let slot = match name {
            "ADC_LOW_THRESHOLD" => 0,
            "ADC_HIGH_THRESHOLD" => 1,
            "GATE_PIN" => 2,
            _ => continue,
        };
        // A define whose value has no trailing digits is skipped, not
        // treated as zero - Python does `continue` on _parse_int() None.
        let v = match parse_int(value) {
            Some(v) => v,
            None => continue,
        };
        match slot {
            0 => low = Some(v),
            1 => high = Some(v),
            _ => pin = Some(v),
        }
    }

    // missing = [k for k in ("low", "high", "pin") if k not in found]
    let missing: Vec<&str> = [
        ("low", low.is_some()),
        ("high", high.is_some()),
        ("pin", pin.is_some()),
    ]
    .iter()
    .filter(|(_, present)| !*present)
    .map(|(name, _)| *name)
    .collect();
    if !missing.is_empty() {
        return Err(LawError::new(format!(
            "{} has no {} constant; expected #define ADC_LOW_THRESHOLD \
             / ADC_HIGH_THRESHOLD / GATE_PIN",
            pycompat::py_basename(path),
            missing.join("/")
        )));
    }
    let low = low.unwrap_or(0);
    let high = high.unwrap_or(0);
    let pin = pin.unwrap_or(0);

    if low >= high {
        return Err(LawError::new(format!(
            "nonsense thresholds in {}: ADC_LOW_THRESHOLD ({}) >= \
             ADC_HIGH_THRESHOLD ({})",
            pycompat::py_basename(path),
            low,
            high
        )));
    }

    Ok(FirmwareConstants {
        low,
        high,
        pin: format!("GPIO{}", pin),
    })
}

/// Build a control-law spec from a real firmware C source.
///
/// The thresholds in that firmware are already *scaled* counts (its comments
/// state the divider is folded in), so the returned spec uses divider as
/// given (1.0 by default from Python callers): the counts are compared
/// directly, exactly as the firmware does.
///
/// Pass `divider` only when `sense_net` is NOT the net the ADC pin samples -
/// i.e. when it is the undivided output and the pin sees it attenuated.  The
/// derived target and hysteresis are then reported in that net's units, and
/// dividing `sense_net="fb"` by 1.0 must reproduce the firmware's own counts.
pub fn law_from_firmware_source(
    path: &str,
    sense_net: &str,
    divider: f64,
    vhigh: f64,
    vref: f64,
    adc_bits: i32,
) -> Result<LawInput, LawError> {
    let consts = read_firmware_constants(path)?;
    let full = ((1i64 << adc_bits) - 1) as f64;

    // Recover the output-target scale factor from the source's own numbers
    // so the reported target is the real one, not a round-number guess.
    // Same operation order as Python: (low + high) / 2.0 / full * vref.
    let midpoint = ((consts.low + consts.high) as f64) / 2.0 / full * vref;
    let half_band =
        ((consts.high - consts.low).abs() as f64) / 2.0 / full * vref;
    // A non-unit divider means the caller pointed us at an undivided net, so
    // BOTH the target and the band move to that net's scale.  (`if divider`
    // is false only for 0.0/-0.0 - NaN would divide, as in Python.)
    let target_v = if divider != 0.0 {
        midpoint / divider
    } else {
        midpoint
    };
    let hysteresis_v = if divider != 0.0 {
        half_band / divider
    } else {
        half_band
    };

    Ok(LawInput {
        kind: Some("hysteretic".to_string()),
        pin: Some(consts.pin),
        sense_net: Some(sense_net.to_string()),
        target_v: Some(pycompat::round4(target_v)),
        hysteresis_v: Some(pycompat::round4(hysteresis_v)),
        vhigh: Some(vhigh),
        vref: Some(vref),
        adc_bits: Some(adc_bits),
        divider: Some(divider),
        source: Some(pycompat::py_basename(path).to_string()),
        // Preserve the source numbers verbatim; normalize_law recomputes
        // low/high counts from target/hysteresis, and the recovered target
        // is a rational fraction that must not drift.
        source_counts: Some((consts.low, consts.high)),
        ..Default::default()
    })
}

/// As law_from_firmware_source(), but pins the counts to the file's own
/// integers instead of a round-trip through volts, so what the solver sees
/// is bit-for-bit the firmware's decision boundary.
pub fn law_from_firmware_source_exact(
    path: &str,
    sense_net: &str,
    divider: f64,
    vhigh: f64,
    vref: f64,
    adc_bits: i32,
) -> Result<LawInput, LawError> {
    let mut spec =
        law_from_firmware_source(path, sense_net, divider, vhigh, vref, adc_bits)?;
    let (low, high) = spec.source_counts.unwrap_or((0, 0));
    spec.low_counts = Some(low);
    spec.high_counts = Some(high);
    Ok(spec)
}

// ----------------------------------------------------------------------
// Divider sanity check
// ----------------------------------------------------------------------

/// Voltages the ADC pin must see to cross the low and high thresholds.
///
/// Inverts the same pin-referenced mapping the firmware uses, so this is the
/// direct statement of what the constants in the C file mean physically.
///
/// On a spec without counts (a normalized pwm spec) Python raises
/// KeyError('low_counts') whose str() is `'low_counts'` - reproduced
/// verbatim here (the C port invented a different message; Python is the
/// contract, see the header comment).
pub fn implied_pin_voltages(
    input: &LawInput,
) -> Result<(f64, f64), LawError> {
    let spec = normalize_law(input)?;
    let (low, high) = match (spec.low_counts, spec.high_counts) {
        (Some(low), Some(high)) => (low, high),
        _ => return Err(LawError::new("'low_counts'")),
    };
    let full = ((1i64 << spec.adc_bits) - 1) as f64;
    Ok((low as f64 / full * spec.vref, high as f64 / full * spec.vref))
}

/// What the schematic's output node will be regulated to.
///
/// `pin_divider` is the schematic's pin-to-output attenuation (0.5 for the
/// 100k/100k divider in circuits/buck_converter.cir).  Call this before
/// trusting a run: if `sense_net` is the undivided output node rather than
/// the divider output, the returned numbers are half what you expect, and
/// that is the signature of a mis-wired sense net rather than a bad circuit.
pub fn implied_output_voltages(
    input: &LawInput,
    pin_divider: f64,
) -> Result<(f64, f64), LawError> {
    // Python computes the pin voltages first and validates pin_divider
    // after, so an invalid spec and a bad divider report the spec error.
    let (lo, hi) = implied_pin_voltages(input)?;
    if pin_divider <= 0.0 {
        return Err(LawError::new(format!(
            "pin_divider must be > 0, got {}",
            pycompat::py_repr(pin_divider)
        )));
    }
    Ok((lo / pin_divider, hi / pin_divider))
}

// ----------------------------------------------------------------------
// Per-run performance metric
// ----------------------------------------------------------------------

/// Steady-state regulation error of a run, in counts and in volts.
///
/// None fields for an empty run (Python returns all-None).  mean is a float,
/// max/final are counts - Python keeps the latter two as ints in its dict;
/// they convert exactly at these magnitudes, as the C port's doubles do.
#[derive(Debug, Clone, PartialEq)]
pub struct RegulationError {
    pub mean_error_counts: Option<f64>,
    pub max_error_counts: Option<f64>,
    pub mean_error_v: Option<f64>,
    pub final_error_counts: Option<f64>,
}

/// Steady-state regulation error of a run.
///
/// Operates on samples already in counts space (the law's own ADC view), so
/// no volts<->counts round trip can smear the measurement.  Ignores the
/// first fifth of the samples: an inductor charging from zero is start-up,
/// not regulation error.
///
/// Empty input yields Ok with all fields None (Python returns all-None).
/// A single sample is an Err: Python slices its only sample away and then
/// divides by zero (ZeroDivisionError) - both implementations reject it,
/// this one by error instead of by exception (the same trade as C's status).
pub fn regulation_error(
    count_samples: &[i64],
    target_counts: i64,
    vref: f64,
    adc_bits: i32,
) -> Result<RegulationError, LawError> {
    if count_samples.is_empty() {
        return Ok(RegulationError {
            mean_error_counts: None,
            max_error_counts: None,
            mean_error_v: None,
            final_error_counts: None,
        });
    }
    if count_samples.len() == 1 {
        // Python slices its only sample away and divides by zero.
        return Err(LawError::new(
            "regulation_error needs at least 2 samples \
             (Python raises ZeroDivisionError here)",
        ));
    }

    let start = std::cmp::max(1, count_samples.len() / 5);
    let tail = &count_samples[start..];
    let mut sum: i64 = 0;
    let mut maxabs: i64 = 0;
    for &c in tail {
        let e = c - target_counts;
        sum += e;
        maxabs = maxabs.max(e.abs());
    }
    let mean = sum as f64 / tail.len() as f64;
    let full = std::cmp::max(1, (1i64 << adc_bits) - 1);
    let lsb_v = vref / full as f64;
    Ok(RegulationError {
        mean_error_counts: Some(mean),
        max_error_counts: Some(maxabs as f64),
        mean_error_v: Some(mean * lsb_v),
        final_error_counts: Some((tail[tail.len() - 1] - target_counts) as f64),
    })
}
