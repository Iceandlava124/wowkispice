/*
 * parity_control_law.rs - emits a fixed battery of control_law results.
 *
 * The companion python/parity_control_law.py computes the SAME battery from
 * bridge/control_law.py and diffs the two.  This is the gate that says the
 * Rust port is behaviourally the Python module, rather than merely passing a
 * re-written copy of its tests - a re-written test can be wrong in the same
 * way as the code it tests, a cross-implementation diff cannot.
 *
 * The battery mirrors native/tools/parity_control_law.c key for key (and its
 * Python twin mirrors native/tools/parity_control_law.py), so all three
 * implementations - C, Python, Rust - are diffed over one identical key
 * space.  The battery is deliberately NOT derived from the unit tests: it is
 * an independent set of inputs chosen here.
 *
 * Output format: one `key<TAB>value` per line.
 *   doubles  -> Rust's shortest round-trip Display (the Python side parses
 *               and compares exactly as a double, so the formatting itself
 *               need not match)
 *   longs    -> decimal
 *   bools    -> true / false
 *   strings  -> verbatim, including spaces
 *   errors   -> empty string on success, the message on failure
 *
 * Keys are index-based (`adc12[3]`, `spec[7].low`) rather than value-derived,
 * so a value that formats differently on one side can never shift the key
 * space; a case added or removed on one side alone is caught as a key
 * mismatch.
 */

use wowkispice_core::control_law::{
    self, LawInput, DEFAULT_ADC_BITS, DEFAULT_VHIGH, DEFAULT_VREF,
};

/// Same path the Python driver uses (repo-relative), just spelled with `/`.
const FW: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../firmware/esp32_buck_controller/src/main.c"
);

fn emit_d(key: &str, v: f64) {
    println!("{}\t{}", key, v);
}

fn emit_l(key: &str, v: i64) {
    println!("{}\t{}", key, v);
}

fn emit_b(key: &str, v: bool) {
    println!("{}\t{}", key, if v { "true" } else { "false" });
}

fn emit_s(key: &str, v: &str) {
    println!("{}\t{}", key, v);
}

// ----------------------------------------------------------------------
// 1. ADC conversion grid
// ----------------------------------------------------------------------
// Same list, same order, in native/tools/parity_control_law.c and .py.
// Expressions are written identically so both sides evaluate the same
// IEEE-754 doubles.
const ADC12_VOLTS: [f64; 18] = [
    -0.01, -0.001, 0.0, 3.3 / 8190.0, 3.3 / 8190.0 + 1e-9, 0.1, 0.5, 1.0,
    1.2, 1.6077, 1.625, 1.6359, 2.4, 3.3 - 1e-9, 3.3, 3.30000001, 3.31,
    10.0,
];
const ADC16_VOLTS: [f64; 8] = [
    -1.0, 0.0, 0.0001, 2.5, 4.999999, 5.0, 5.5, 100.0,
];

fn battery_adc() {
    for (i, v) in ADC12_VOLTS.iter().enumerate() {
        emit_l(
            &format!("adc12[{}]", i),
            control_law::to_counts_raw(*v, 3.3, 12),
        );
    }
    for (i, v) in ADC16_VOLTS.iter().enumerate() {
        emit_l(
            &format!("adc16[{}]", i),
            control_law::to_counts_raw(*v, 5.0, 16),
        );
    }
    // adc_bits extremes accepted by normalisation: 8 and 24.
    emit_l("adc8[0]", control_law::to_counts_raw(1.0, 3.3, 8));
    emit_l("adc8[1]", control_law::to_counts_raw(3.3, 3.3, 8));
    emit_l("adc24[0]", control_law::to_counts_raw(1.0, 3.3, 24));
    emit_l("adc24[1]", control_law::to_counts_raw(3.3, 3.3, 24));
}

// ----------------------------------------------------------------------
// 2. Spec normalisation
// ----------------------------------------------------------------------
fn spec_base() -> LawInput {
    LawInput {
        kind: Some("hysteretic".to_string()),
        pin: Some("GPIO18".to_string()),
        sense_net: Some("vout".to_string()),
        ..Default::default()
    }
}

/// Index order mirrored exactly in parity_control_law.c and .py.
fn spec_at(i: i32) -> LawInput {
    let mut sp = spec_base();
    match i {
        0 => {
            // fixture with the firmware's explicit counts
            sp.target_v = Some(3.3);
            sp.hysteresis_v = Some(0.165);
            sp.divider = Some(0.5);
            sp.vref = Some(3.3);
            sp.adc_bits = Some(12);
            sp.low_counts = Some(1995);
            sp.high_counts = Some(2030);
        }
        1 => {
            // counts derived from target and hysteresis
            sp.target_v = Some(3.3);
            sp.hysteresis_v = Some(0.165);
            sp.divider = Some(0.5);
            sp.vref = Some(3.3);
            sp.adc_bits = Some(12);
        }
        2 => {
            // pwm
            sp.kind = Some("pwm".to_string());
            sp.target_v = Some(3.3);
            sp.carrier_hz = Some(1000.0);
            sp.duty_gain = Some(0.5);
        }
        3 => {
            // defaults only - every default must materialise
        }
        4 => {
            // explicit counts overriding a round-trip through volts
            sp.target_v = Some(1.0);
            sp.hysteresis_v = Some(0.01);
            sp.low_counts = Some(1995);
            sp.high_counts = Some(2030);
        }
        5 => {
            // only low_counts given -> both recomputed
            sp.target_v = Some(3.3);
            sp.hysteresis_v = Some(0.165);
            sp.divider = Some(0.5);
            sp.vref = Some(3.3);
            sp.adc_bits = Some(12);
            sp.low_counts = Some(1995);
        }
        6 => {
            // kind is case-insensitive in Python
            sp.kind = Some("HYSTERETIC".to_string());
        }
        7 => {
            // pin is stripped
            sp.pin = Some("   GPIO42\t".to_string());
        }
        // --- invalid from here on ---
        8 => sp.kind = Some("banana".to_string()),
        9 => sp.divider = Some(0.0),
        10 => {
            sp.low_counts = Some(2000);
            sp.high_counts = Some(2000);
        }
        11 => sp.vhigh = Some(99.0),
        12 => sp.pin = None,
        13 => sp.sense_net = None,
        14 => sp.adc_bits = Some(40),
        15 => {
            sp.target_v = Some(3.3);
            sp.hysteresis_v = Some(0.0);
        }
        16 => {
            sp.target_v = Some(1.0);
            sp.hysteresis_v = Some(2.0);
        }
        17 => {
            sp.kind = Some("pwm".to_string());
            sp.carrier_hz = Some(0.0);
        }
        18 => sp.vref = Some(0.0),
        19 => sp.target_v = Some(-5.0),
        _ => {}
    }
    sp
}

const SPEC_COUNT: i32 = 20;

fn battery_specs() {
    for i in 0..SPEC_COUNT {
        let sp = spec_at(i);
        let norm = match control_law::normalize_law(&sp) {
            Ok(n) => n,
            Err(e) => {
                emit_s(&format!("spec[{}]", i), e.message());
                continue;
            }
        };
        emit_s(&format!("spec[{}]", i), "");
        emit_s(&format!("spec[{}].kind", i), norm.kind.as_str());
        emit_s(&format!("spec[{}].pin", i), &norm.pin);
        emit_s(&format!("spec[{}].sense_net", i), &norm.sense_net);
        emit_d(&format!("spec[{}].target", i), norm.target_v);
        emit_d(&format!("spec[{}].vhigh", i), norm.vhigh);
        emit_d(&format!("spec[{}].vref", i), norm.vref);
        emit_d(&format!("spec[{}].divider", i), norm.divider);
        emit_l(&format!("spec[{}].adc_bits", i), i64::from(norm.adc_bits));
        // Keyed on kind: Python's normalized dict holds low/high counts only
        // for a hysteretic law and carrier/gain only for a pwm one, so
        // emitting both would invent keys neither side really has.
        if norm.kind == control_law::LawKind::Hysteretic {
            emit_l(&format!("spec[{}].low", i), norm.low_counts.unwrap_or(0));
            emit_l(&format!("spec[{}].high", i), norm.high_counts.unwrap_or(0));
            emit_d(&format!("spec[{}].hyst", i), norm.hysteresis_v.unwrap_or(0.0));
        } else {
            emit_d(&format!("spec[{}].carrier", i), norm.carrier_hz.unwrap_or(0.0));
            emit_d(&format!("spec[{}].gain", i), norm.duty_gain.unwrap_or(0.0));
        }
        emit_s(
            &format!("spec[{}].source", i),
            norm.source.as_deref().unwrap_or("(none)"),
        );
    }
}

// ----------------------------------------------------------------------
// 3. Decision table
// ----------------------------------------------------------------------
const DECIDE_COUNTS: [i64; 12] = [
    0, 100, 1990, 1994, 1995, 1996, 2012, 2029, 2030, 2031, 2035, 4095,
];

fn battery_decide() {
    let mut law = match control_law::make_law(&spec_at(0)) {
        Ok(l) => l,
        Err(e) => {
            emit_s("decide.setup", e.message());
            return;
        }
    };
    emit_s("decide.setup", "");

    // Two passes: decide() must hold the PREVIOUS level inside the band, so
    // the same counts must give different answers depending on law.level.
    for pass in 0..2 {
        law.level = pass == 1;
        for (i, c) in DECIDE_COUNTS.iter().enumerate() {
            emit_b(&format!("decide[{}][{}]", pass, i), law.decide(*c));
        }
    }

    // And the ADC front end on this law: sense volts -> counts, with the
    // sense divider applied.
    emit_l("law.to_counts[0]", law.to_counts(0.0));
    emit_l("law.to_counts[1]", law.to_counts(2.4));
    emit_l("law.to_counts[2]", law.to_counts(3.3));
    emit_l("law.to_counts[3]", law.to_counts(6.6));
}

// ----------------------------------------------------------------------
// 4. update() sequence and the telemetry it produces
// ----------------------------------------------------------------------
const UPD_VOLTS: [f64; 10] =
    [0.0, 5.0, 5.0, 3.25, 3.25, 0.0, 1.6, 3.3, 0.0, 4.0];
const UPD_TIME: [f64; 10] = [
    0.0, 1e-6, 2e-6, 3e-6, 4e-6, 5e-6, 6e-6, 7e-6, 8e-6, 9e-6,
];

fn battery_update() {
    let mut law = match control_law::make_law(&spec_at(0)) {
        Ok(l) => l,
        Err(e) => {
            emit_s("update.setup", e.message());
            return;
        }
    };
    emit_s("update.setup", "");

    for (i, (v, t)) in UPD_VOLTS.iter().zip(UPD_TIME.iter()).enumerate() {
        let pin = law.update(*v, *t);
        emit_d(&format!("update[{}].pin", i), pin);
        emit_l(&format!("update[{}].switches", i), law.switch_count);
        emit_l(
            &format!("update[{}].counts", i),
            *law.history_counts.last().unwrap_or(&0),
        );
    }

    let st = law.stats();
    emit_l("stats.samples", st.samples as i64);
    emit_l("stats.switches", st.switches);
    emit_d("stats.duty", st.duty);
    // The C struct keeps a zeroed counts_min/max/last when there are no
    // samples; Python's dict says None.  Only the flag carries meaning
    // there, and this battery always has samples.
    let has_counts = st.counts_min.is_some();
    emit_l("stats.has_counts", i64::from(has_counts));
    emit_l("stats.min", st.counts_min.unwrap_or(0));
    emit_l("stats.max", st.counts_max.unwrap_or(0));
    emit_l("stats.last", st.counts_last.unwrap_or(0));
    emit_s("stats.final", st.final_level);
    emit_s("stats.pin", &st.pin);
    emit_s("stats.sense_net", &st.sense_net);
    emit_s("stats.kind", st.kind.as_str());
}

// ----------------------------------------------------------------------
// 5. PWM behaviour
// ----------------------------------------------------------------------
fn battery_pwm() {
    let sp = LawInput {
        kind: Some("pwm".to_string()),
        pin: Some("PWM0".to_string()),
        sense_net: Some("vout".to_string()),
        target_v: Some(3.3),
        carrier_hz: Some(1000.0),
        duty_gain: Some(0.5),
        ..Default::default()
    };
    let mut law = match control_law::make_law(&sp) {
        Ok(l) => l,
        Err(e) => {
            emit_s("pwm.setup", e.message());
            return;
        }
    };
    emit_s("pwm.setup", "");
    emit_d("pwm.target_counts", law.target_counts as f64);

    let mut low_error = 0.0;
    let mut high_error = 0.0;
    for i in 0..2000 {
        law.update(3.0, i as f64 * 1e-7);
        low_error = law.duty;
        law.update(0.5, i as f64 * 1e-7);
        high_error = law.duty;
    }
    emit_d("pwm.low_error", low_error);
    emit_d("pwm.high_error", high_error);
    emit_l("pwm.switches", law.switch_count);
    emit_l("pwm.samples", law.history_pin.len() as i64);

    let st = law.stats();
    emit_d("pwm.stats.duty", st.duty);
    emit_l("pwm.stats.switches", st.switches);

    // Saturating case: gain 100 must clamp to 1.0, never exceed it.
    let sat_sp = LawInput {
        kind: Some("pwm".to_string()),
        pin: Some("PWM0".to_string()),
        sense_net: Some("vout".to_string()),
        target_v: Some(3.3),
        duty_gain: Some(100.0),
        ..Default::default()
    };
    if let Ok(mut sat) = control_law::make_law(&sat_sp) {
        sat.update(0.0, 0.0);
        emit_d("pwm.saturated", sat.duty);
    }
}

// ----------------------------------------------------------------------
// 6. Firmware import and divider semantics
// ----------------------------------------------------------------------
fn battery_firmware() {
    let consts = match control_law::read_firmware_constants(FW) {
        Ok(c) => c,
        Err(e) => {
            emit_s("fw.setup", e.message());
            return;
        }
    };
    emit_s("fw.setup", "");
    emit_s("fw.pin", &consts.pin);
    emit_l("fw.low", consts.low);
    emit_l("fw.high", consts.high);

    for (d, div) in [1.0f64, 0.5].iter().enumerate() {
        let spec = match control_law::law_from_firmware_source(
            FW,
            "vout",
            *div,
            DEFAULT_VHIGH,
            DEFAULT_VREF,
            DEFAULT_ADC_BITS,
        ) {
            Ok(s) => s,
            Err(e) => {
                emit_s(&format!("fw.div[{}]", d), e.message());
                continue;
            }
        };
        emit_s(&format!("fw.div[{}]", d), "");
        emit_d(&format!("fw.div[{}].target", d), spec.target_v.unwrap_or(0.0));
        emit_d(&format!("fw.div[{}].hyst", d), spec.hysteresis_v.unwrap_or(0.0));
        emit_s(
            &format!("fw.div[{}].source", d),
            spec.source.as_deref().unwrap_or(""),
        );
        let (src_low, src_high) = spec.source_counts.unwrap_or((0, 0));
        emit_l(&format!("fw.div[{}].src_low", d), src_low);
        emit_l(&format!("fw.div[{}].src_high", d), src_high);

        if let Ok(norm) = control_law::normalize_law(&spec) {
            emit_l(&format!("fw.div[{}].low", d), norm.low_counts.unwrap_or(0));
            emit_l(&format!("fw.div[{}].high", d), norm.high_counts.unwrap_or(0));
            emit_d(
                &format!("fw.div[{}].target_norm", d),
                norm.target_v,
            );
        }
    }

    // _exact() must reproduce the file's integers verbatim.
    let spec = match control_law::law_from_firmware_source_exact(
        FW,
        "fb",
        1.0,
        DEFAULT_VHIGH,
        DEFAULT_VREF,
        DEFAULT_ADC_BITS,
    ) {
        Ok(s) => s,
        Err(e) => {
            emit_s("fw.exact", e.message());
            emit_s("fw.empty_source", &empty_source_message());
            return;
        }
    };
    emit_s("fw.exact", "");
    emit_l("fw.exact.low", spec.low_counts.unwrap_or(0));
    emit_l("fw.exact.high", spec.high_counts.unwrap_or(0));
    emit_d("fw.exact.divider", spec.divider.unwrap_or(0.0));
    emit_s("fw.exact.pin", spec.pin.as_deref().unwrap_or(""));
    emit_s("fw.exact.source", spec.source.as_deref().unwrap_or(""));

    if let Ok(norm) = control_law::normalize_law(&spec) {
        emit_l("fw.exact.norm_low", norm.low_counts.unwrap_or(0));
        emit_l("fw.exact.norm_high", norm.high_counts.unwrap_or(0));
    }

    if let Ok((lo, hi)) = control_law::implied_pin_voltages(&spec) {
        emit_d("fw.pin_v.lo", lo);
        emit_d("fw.pin_v.hi", hi);
        emit_d("fw.pin_v.mid", (lo + hi) / 2.0);
    }
    if let Ok((lo, hi)) = control_law::implied_output_voltages(&spec, 0.5) {
        emit_d("fw.out_v.lo", lo);
        emit_d("fw.out_v.hi", hi);
    }
    // A bad pin divider must be rejected, after the pin voltages are
    // computed - the same order Python validates in.
    match control_law::implied_output_voltages(&spec, 0.0) {
        Ok(_) => {
            emit_l("fw.bad_div.status", 0);
            emit_s("fw.bad_div.msg", "");
        }
        Err(e) => {
            emit_l("fw.bad_div.status", 1);
            emit_s("fw.bad_div.msg", e.message());
        }
    }

    // Re-derive from the undivided node: the switching points must not move,
    // but the reported target halves.
    if let Ok(spec2) = control_law::law_from_firmware_source(
        FW,
        "vout",
        0.5,
        DEFAULT_VHIGH,
        DEFAULT_VREF,
        DEFAULT_ADC_BITS,
    ) {
        if let Ok(norm2) = control_law::normalize_law(&spec2) {
            emit_l("fw.vout_half.low", norm2.low_counts.unwrap_or(0));
            emit_l("fw.vout_half.high", norm2.high_counts.unwrap_or(0));
            emit_d("fw.vout_half.target", norm2.target_v);
        }
    }

    emit_s("fw.empty_source", &empty_source_message());
}

fn empty_source_message() -> String {
    match control_law::read_firmware_constants("does/not/exist.c") {
        Ok(_) => String::new(),
        Err(e) => e.message().to_string(),
    }
}

// ----------------------------------------------------------------------
// 7. Regulation error
// ----------------------------------------------------------------------
const REG_A: [i64; 5] = [0, 12, 8, 12, 8];
const REG_B: [i64; 10] = [100, 101, 99, 100, 100, 102, 98, 100, 100, 100];
const REG_C: [i64; 20] = [5; 20];
const REG_ONE: [i64; 1] = [1995];

fn battery_regulation() {
    // n == 5: cannot fail; only the has/field keys are comparable.
    match control_law::regulation_error(&REG_A, 10, 3.3, 12) {
        Ok(re) => {
            let has = re.mean_error_counts.is_some();
            emit_l("regA.has", i64::from(has));
            if has {
                emit_d("regA.mean", re.mean_error_counts.unwrap_or(0.0));
                emit_d("regA.max", re.max_error_counts.unwrap_or(0.0));
                emit_d("regA.final", re.final_error_counts.unwrap_or(0.0));
                emit_d("regA.mean_v", re.mean_error_v.unwrap_or(0.0));
            }
        }
        Err(_) => emit_l("regA.has", 0),
    }

    match control_law::regulation_error(&REG_B, 100, 3.3, 12) {
        Ok(re) => {
            let has = re.mean_error_counts.is_some();
            emit_l("regB.has", i64::from(has));
            if has {
                emit_d("regB.mean", re.mean_error_counts.unwrap_or(0.0));
                emit_d("regB.max", re.max_error_counts.unwrap_or(0.0));
                emit_d("regB.final", re.final_error_counts.unwrap_or(0.0));
            }
        }
        Err(_) => emit_l("regB.has", 0),
    }

    match control_law::regulation_error(&REG_C, 5, 5.0, 16) {
        Ok(re) => {
            let has = re.mean_error_counts.is_some();
            emit_l("regC.has", i64::from(has));
            if has {
                emit_d("regC.mean", re.mean_error_counts.unwrap_or(0.0));
                emit_d("regC.max", re.max_error_counts.unwrap_or(0.0));
            }
        }
        Err(_) => emit_l("regC.has", 0),
    }

    // Empty: Python returns all-None (has=0) and emits no field keys.
    match control_law::regulation_error(&[], 10, 3.3, 12) {
        Ok(re) => emit_l("regEmpty.has", i64::from(re.mean_error_counts.is_some())),
        Err(_) => emit_l("regEmpty.has", 0),
    }

    // One sample: Python divides by zero (ZeroDivisionError), this port
    // refuses by error.  Only the STATUS is compared - see the note in
    // native/tools/parity_control_law.c: the two messages are deliberately
    // different and neither is a transcription of the other, so each side
    // pins its own wording in its own unit test.
    match control_law::regulation_error(&REG_ONE, 10, 3.3, 12) {
        Ok(_) => emit_l("regOne.status", 0),
        Err(_) => emit_l("regOne.status", 1),
    }
}

// ----------------------------------------------------------------------
// 8. describe_law
// ----------------------------------------------------------------------
fn battery_describe() {
    emit_s("desc.fixture", &control_law::describe_law(&spec_at(0)));
    emit_s("desc.pwm", &control_law::describe_law(&spec_at(2)));
    let invalid = LawInput {
        kind: Some("banana".to_string()),
        ..Default::default()
    };
    emit_s("desc.invalid", &control_law::describe_law(&invalid));
}

fn main() {
    battery_adc();
    battery_specs();
    battery_decide();
    battery_update();
    battery_pwm();
    battery_firmware();
    battery_regulation();
    battery_describe();
}
