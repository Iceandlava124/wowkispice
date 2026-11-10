/*
 * test_control_law.rs - port of the Python control_law test contract.
 *
 * WHAT IS PORTED
 *
 *   tests/test_control_law_unit.py   all 18 tests
 *   tests/test_adc_conversion.py     all 12 tests
 *   tests/test_cosim_control.py      the control-law classes only
 *
 * Test functions keep the Python test's name, so the two suites stay
 * greppable against each other:
 *
 *     Select-String -Path tests\*.py -Pattern 'def (test_\w+)'
 *     Select-String -Path crates\wowkispice-core\tests\test_control_law.rs -Pattern 'fn (test_\w+)'
 *
 * Two Python tests share a name across files (test_inside_band_holds_previous_state
 * appears in both test_control_law_unit.py and test_cosim_control.py on
 * different fixtures), so the cosim one carries a _cosim suffix here.  The
 * comment at the function says so - a deliberate, reviewable choice, not a
 * silent gap.
 *
 * WHAT IS NOT PORTED, AND WHY
 *
 *   test_cosim_control.py          TestNetlistEmission, TestCosimEndToEnd and
 *                                  the save/reload and warning-path classes all
 *                                  call the ngspice solver through
 *                                  bridge/cosim_runner.py.  They are not
 *                                  control-law tests wearing a different name:
 *                                  they assert on netlist text, on a transient
 *                                  run regulating to 3.3 V, and on UI-level
 *                                  warning plumbing.  Porting them means
 *                                  porting the solver first.
 *
 *   bridge/control_law.py surface  The four tests in the C-ONLY ADDITIONS
 *                                  block at the bottom of this file are NOT
 *                                  ports.  They are marked loudly because the
 *                                  Python suite leaves regulation_error()
 *                                  entirely untested and stats() only
 *                                  indirectly so (mirrors the four C-ONLY
 *                                  ADDITIONS of native/tests/test_control_law.c,
 *                                  which this file is transcribed from).
 *
 * A test that does not exist here must not be read as "the Python test was
 * dropped" - check this list first, then the Python file.
 *
 * WHAT THIS CANNOT PROVE
 *
 * No test here measures real silicon; the firmware is read, not executed.
 * crates/parity additionally diffs this implementation against
 * bridge/control_law.py on a battery neither suite was transcribed from,
 * which is what catches a port and its ported test being wrong in the same
 * way.
 */

use wowkispice_core::control_law::*;

// Resolved from the crate manifest, so the tests do not depend on the
// runner's working directory.
const FIRMWARE_MAIN_C: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../firmware/esp32_buck_controller/src/main.c"
);

// ----------------------------------------------------------------------
// Fixtures and assertion helpers (transcribed from the Python fixtures and
// native/tests/wosp_test.h's CHECK_* macros)
// ----------------------------------------------------------------------

/// {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout"}
fn base_hysteretic() -> LawInput {
    LawInput {
        kind: Some("hysteretic".to_string()),
        pin: Some("GPIO18".to_string()),
        sense_net: Some("vout".to_string()),
        ..Default::default()
    }
}

/// The firmware's ADC_LOW_THRESHOLD/ADC_HIGH_THRESHOLD (1995/2030) are raw
/// counts at the ADC pin (firmware/esp32_buck_controller/src/main.c lines
/// 40-41).  Explicit counts are used so the decision boundary is bit-for-bit
/// the firmware's.
fn fixture_with_counts() -> LawInput {
    LawInput {
        target_v: Some(3.3),
        hysteresis_v: Some(0.165),
        divider: Some(0.5),
        vref: Some(3.3),
        adc_bits: Some(12),
        low_counts: Some(1995),
        high_counts: Some(2030),
        ..base_hysteretic()
    }
}

/// The law described by the real firmware in this repo
/// (Python: law_from_firmware_source_exact(FIRMWARE_MAIN_C, ..)).
fn firmware_law(sense_net: &str, divider: f64) -> LawInput {
    law_from_firmware_source_exact(
        FIRMWARE_MAIN_C,
        sense_net,
        divider,
        DEFAULT_VHIGH,
        DEFAULT_VREF,
        DEFAULT_ADC_BITS,
    )
    .expect("firmware main.c must yield a spec")
}

/// The firmware source, decoded as the Python fidelity tests read it.
fn firmware_source() -> String {
    let raw = std::fs::read(FIRMWARE_MAIN_C).expect("read firmware main.c");
    String::from_utf8_lossy(&raw).into_owned()
}

fn assert_contains(haystack: &str, needle: &str) {
    assert!(
        haystack.contains(needle),
        "{:?} does not contain {:?}",
        haystack,
        needle
    );
}

/// assertAlmostEqual(x, y, delta=t)
fn assert_near(actual: f64, expected: f64, tol: f64) {
    assert!(
        (actual - expected).abs() <= tol,
        "{} ~= {} failed: |{}| > {}",
        actual,
        expected,
        actual - expected,
        tol
    );
}

/// assertAlmostEqual(x, y, places=p): |a-b| < 0.5 * 10^-places
fn assert_places(actual: f64, expected: f64, places: i32) {
    assert_near(actual, expected, 0.5 / 10f64.powi(places));
}

/// with pytest.raises(ControlLawError) / self.assertRaises(...) - labelled
/// like a unittest subTest so a failure names the case that broke.
fn expect_normalize_fail(input: &LawInput, label: &str) {
    assert!(
        normalize_law(input).is_err(),
        "expected ControlLawError for {}",
        label
    );
}

/// tempfile.mkdtemp()-style scratch file; unique per test via the pid.
fn write_tmp(name: &str, content: &str) -> std::path::PathBuf {
    let path = std::env::temp_dir()
        .join(format!("wowkispice_ctl_{}_{}", std::process::id(), name));
    std::fs::write(&path, content).expect("write scratch firmware file");
    path
}

// ==========================================================================
// tests/test_control_law_unit.py::TestSpecNormalization
// ==========================================================================

#[test]
fn test_normalize_fills_defaults() {
    let spec = normalize_law(&LawInput {
        kind: Some("hysteretic".to_string()),
        pin: Some("GPIO18".to_string()),
        sense_net: Some("vout".to_string()),
        target_v: Some(3.3),
        hysteresis_v: Some(0.165),
        divider: Some(0.5),
        vref: Some(3.3),
        adc_bits: Some(12),
        ..Default::default()
    })
    .unwrap();
    assert_eq!(spec.kind.as_str(), "hysteretic");
    assert!(spec.low_counts.is_some() && spec.high_counts.is_some());
}

#[test]
fn test_rejects_unknown_kind() {
    // normalize_law accepts only LAW_KINDS = ("hysteretic", "pwm").
    // Everything else must raise ControlLawError, and the message must name
    // the offending kind (pytest.raises match=re.escape(bad)).
    for bad in ["sine", "bang-bang"] {
        let input = LawInput {
            kind: Some(bad.to_string()),
            pin: Some("GPIO18".to_string()),
            sense_net: Some("vout".to_string()),
            ..Default::default()
        };
        let err = normalize_law(&input).unwrap_err();
        assert_contains(err.message(), bad);
    }
    // Empty kind must also be rejected.
    let input = LawInput {
        kind: Some(String::new()),
        pin: Some("GPIO18".to_string()),
        sense_net: Some("vout".to_string()),
        ..Default::default()
    };
    assert!(normalize_law(&input).is_err());
}

#[test]
fn test_accepts_pwm_kind() {
    // PwmLaw is a registered kind and must normalise cleanly.
    let spec = normalize_law(&LawInput {
        kind: Some("pwm".to_string()),
        pin: Some("GPIO18".to_string()),
        sense_net: Some("vout".to_string()),
        target_v: Some(3.3),
        vref: Some(3.3),
        adc_bits: Some(12),
        ..Default::default()
    })
    .unwrap();
    assert_eq!(spec.kind, LawKind::Pwm);
}

#[test]
fn test_rejects_zero_divider() {
    let input = LawInput {
        divider: Some(0.0),
        target_v: Some(3.3),
        hysteresis_v: Some(0.165),
        ..base_hysteretic()
    };
    // expected ControlLawError for divider=0
    assert!(normalize_law(&input).is_err());
}

#[test]
fn test_rejects_negative_adc_bits() {
    let input = LawInput {
        adc_bits: Some(4), // below the 8..24 floor
        target_v: Some(3.3),
        hysteresis_v: Some(0.165),
        vref: Some(3.3),
        ..base_hysteretic()
    };
    // expected ControlLawError for adc_bits=4
    assert!(normalize_law(&input).is_err());
}

// ==========================================================================
// tests/test_control_law_unit.py::TestHystereticDecision
// ==========================================================================

#[test]
fn test_every_transition_around_1995_and_2030() {
    // 1995 and 2030 are the firmware's own thresholds (main.c lines 40-41);
    // every transition around them, including exact-at-threshold values, is
    // asserted here. The firmware's branch order is < low -> HIGH,
    // > high -> LOW, else hold - so exactly 1995 and exactly 2030 hold.
    let mut law = make_law(&fixture_with_counts()).unwrap();
    assert!(law.decide(1992));
    assert!(law.decide(1994));
    law.level = true;
    assert!(law.decide(1995));
    law.level = false;
    assert!(!law.decide(1995));
    law.level = true;
    assert!(law.decide(2030));
    law.level = false;
    assert!(!law.decide(2030));
    // 2031 is above the high threshold, so the firmware drives LOW (main.c
    // uses strict `>`). It never forces HIGH; instead it forces the gate OFF
    // from any prior ON state, and holds OFF when already OFF.
    law.level = true;
    assert!(!law.decide(2031));
    law.level = false;
    assert!(!law.decide(2031));
    assert!(!law.decide(2033));
}

#[test]
fn test_below_low_drives_high() {
    let mut law = make_law(&fixture_with_counts()).unwrap();
    assert!(law.decide(1994));
}

#[test]
fn test_above_high_drives_low() {
    let mut law = make_law(&fixture_with_counts()).unwrap();
    assert!(!law.decide(2030));
    assert!(!law.decide(2031));
    assert!(!law.decide(2032));
}

#[test]
fn test_exact_at_high_holds_when_low() {
    let mut law = make_law(&fixture_with_counts()).unwrap();
    law.level = true;
    assert!(law.decide(2030));
}

#[test]
fn test_inside_band_holds_previous_state() {
    let mut law = make_law(&fixture_with_counts()).unwrap();
    let inside = (law.low_counts + law.high_counts) / 2;
    // Python's first line here is `assert law.decide(inside) is not None` -
    // vacuous for a bool (it returns law.level, never None), so there is
    // nothing to transcribe; the value-producing asserts follow.
    law.level = true;
    assert!(law.decide(inside));
    law.level = false;
    assert!(!law.decide(inside));
}

// ==========================================================================
// tests/test_control_law_unit.py::TestDividerSemantics
// ==========================================================================

#[test]
fn test_pin_referenced_net_needs_no_divider() {
    let spec = firmware_law("fb", 1.0);
    assert_eq!(spec.divider, Some(1.0));
    assert_eq!(spec.low_counts, Some(1995));
    assert_eq!(spec.high_counts, Some(2030));
}

#[test]
fn test_undivided_node_regulates_to_half() {
    let spec = firmware_law("vout", 0.5);
    let (lo, hi) = implied_output_voltages(&spec, 0.5).unwrap();
    assert_near(lo, 3.2154, 0.01);
    assert_near(hi, 3.2718, 0.01);
}

#[test]
fn test_reapplying_divider_twice_halves_the_target() {
    let mut spec = firmware_law("vout", 0.5);
    spec.divider = Some(1.0); // spec["divider"] = 1.0
    let s = normalize_law(&spec).unwrap();
    assert_eq!(s.low_counts, Some(1995));
    assert_eq!(s.high_counts, Some(2030));
}

// ==========================================================================
// tests/test_control_law_unit.py::TestFidelityGap
// ==========================================================================

#[test]
fn test_firmware_still_oversamples() {
    assert_contains(&firmware_source(), "ADC_OVERSAMPLE_N");
}

#[test]
fn test_firmware_still_calibrates() {
    assert_contains(&firmware_source(), "adc_cali");
}

#[test]
fn test_firmware_still_says_counts_are_raw() {
    assert_contains(&firmware_source(), "RAW counts");
}

// ==========================================================================
// tests/test_control_law_unit.py::TestAdcFrontEndAndThresholds
// ==========================================================================

#[test]
fn test_to_counts_applies_the_sense_divider() {
    let spec = normalize_law(&LawInput {
        target_v: Some(3.3),
        hysteresis_v: Some(0.165),
        divider: Some(0.5),
        vref: Some(3.3),
        adc_bits: Some(12),
        ..base_hysteretic()
    })
    .unwrap();
    let law = ControlLaw::from_spec(spec).unwrap();
    // 2.4 V at the sense node is 1.2 V at the ADC once the 0.5 divider has
    // done its work; dropping the divider reports counts for double the
    // voltage the firmware actually samples.
    assert_eq!(law.to_counts(2.4), to_counts_raw(1.2, 3.3, 12));
    assert_ne!(law.to_counts(2.4), to_counts_raw(2.4, 3.3, 12));
}

#[test]
fn test_equal_threshold_counts_are_rejected() {
    // low == high leaves no band to hold a state in, so a law built from it
    // would decide purely on which side of one number the sample sits.
    let input = LawInput {
        target_v: Some(3.3),
        hysteresis_v: Some(0.165),
        divider: Some(0.5),
        vref: Some(3.3),
        adc_bits: Some(12),
        low_counts: Some(2000),
        high_counts: Some(2000),
        ..base_hysteretic()
    };
    expect_normalize_fail(&input, "low_counts == high_counts");
}

// ==========================================================================
// tests/test_adc_conversion.py::TestToCountsClampAndRounding
// ==========================================================================

#[test]
fn test_negative_maps_to_zero() {
    // -0.001 V must be clamped to 0 counts, not wrapped.
    assert_eq!(to_counts_raw(-0.001, 3.3, 12), 0);
}

#[test]
fn test_exact_half_lsb_rounds_down() {
    // A voltage exactly half an LSB above 0 must round to 0 counts.  LSB =
    // vref/full = 3.3/4095, so half LSB = 3.3/8190.  This lands on an exact
    // .5 in counts, so it is the case that distinguishes Python's
    // round-half-to-even (round(0.5) == 0) from round-half-away-from-zero.
    assert_eq!(to_counts_raw(3.3 / 8190.0, 3.3, 12), 0);
    // One ulp above the half-LSB boundary must round up to 1.
    assert_eq!(to_counts_raw(3.3 / 8190.0 + 1e-9, 3.3, 12), 1);
}

#[test]
fn test_exact_full_scale_clips_to_max() {
    // 3.3 V is exactly full scale and must map to 4095, never 4096.
    assert_eq!(to_counts_raw(3.3, 3.3, 12), 4095);
}

#[test]
fn test_just_below_full_scale() {
    // One ulp below full scale is a real count, not clipped.
    assert_eq!(to_counts_raw(3.3 - 1e-9, 3.3, 12), 4095);
}

#[test]
fn test_above_vref_clips() {
    assert_eq!(to_counts_raw(3.31, 3.3, 12), 4095);
}

#[test]
fn test_clamp_behaviour_without_float() {
    // The clamp must hold even for a voltage that is clearly above Vref but
    // tiny enough that exact half-lsb rounding would otherwise matter.
    assert_eq!(to_counts_raw(3.30000001, 3.3, 12), 4095);
}

// ==========================================================================
// tests/test_adc_conversion.py::TestLawCountsAtThresholds
// ==========================================================================

#[test]
fn test_decide_below_low_drives_high() {
    let mut law = make_law(&fixture_with_counts()).unwrap();
    // firmware branch: raw_adc < ADC_LOW_THRESHOLD -> drive HIGH
    assert!(law.decide(1994));
    assert!(law.decide(1993));
}

#[test]
fn test_decide_at_low_drives_high_hold() {
    let mut law = make_law(&fixture_with_counts()).unwrap();
    // Exactly at ADC_LOW_THRESHOLD holds the previous state, because the
    // firmware's hold region is the inclusive band [1995, 2030].
    law.level = true;
    assert!(law.decide(1995));
    law.level = false;
    assert!(!law.decide(1995));
    // Just below still drives HIGH.
    assert!(law.decide(1994));
}

#[test]
fn test_decide_inside_band_holds() {
    let mut law = make_law(&fixture_with_counts()).unwrap();
    let inside = (law.low_counts + law.high_counts) / 2;
    law.level = true;
    assert!(law.decide(inside));
    law.level = false;
    assert!(!law.decide(inside));
    law.level = true;
    assert!(law.decide(inside + 1));
    law.level = false;
    assert!(!law.decide(inside + 1));
}

#[test]
fn test_decide_at_high_drives_low_hold() {
    let mut law = make_law(&fixture_with_counts()).unwrap();
    // Exactly at ADC_HIGH_THRESHOLD holds the previous state.
    law.level = true;
    assert!(law.decide(2030));
    law.level = false;
    assert!(!law.decide(2030));
    // Just above still drives LOW.
    assert!(!law.decide(2031));
}

#[test]
fn test_decide_above_high_drives_low() {
    let mut law = make_law(&fixture_with_counts()).unwrap();
    assert!(!law.decide(2031));
    assert!(!law.decide(2032));
}

#[test]
fn test_update_counts_switches_only_on_change() {
    // With the firmware's real thresholds (1995/2030), two readings inside
    // the hysteresis band must not change the level or switch_count.
    //
    // The Python comment says 3.25 V through the 2:1 divider is "2023
    // counts".  That arithmetic is off: 1.625/3.3*4095 = 2016.48 -> 2016,
    // which is still inside (1995, 2030), and the Python test asserts only
    // that the second reading matches the first and that no switch occurred
    // - it never pins the count value, so neither does this port (the C
    // port documents the same finding).
    let mut law = make_law(&fixture_with_counts()).unwrap();
    law.update(3.25, 0.0);
    let first = *law.history_counts.last().unwrap();
    law.update(3.25, 1e-6);
    assert_eq!(*law.history_counts.last().unwrap(), first);
    assert_eq!(law.switch_count, 0);
}

// ==========================================================================
// tests/test_cosim_control.py::TestControlLawSpec
// ==========================================================================

#[test]
fn test_hysteretic_counts_come_from_target_and_hysteresis() {
    let law = make_law(&LawInput {
        target_v: Some(3.3),
        hysteresis_v: Some(0.165),
        divider: Some(0.5),
        vref: Some(3.3),
        adc_bits: Some(12),
        ..base_hysteretic()
    })
    .unwrap();
    // (3.3 -+ 0.165) V through a 0.5 divider, 12-bit over a 3.3 V reference
    assert_eq!(law.spec.low_counts, Some(1945));
    assert_eq!(law.spec.high_counts, Some(2150));
    assert!(law.low_counts < law.high_counts);
}

#[test]
fn test_explicit_counts_are_preserved_verbatim() {
    let law = make_law(&LawInput {
        target_v: Some(1.0),
        hysteresis_v: Some(0.01),
        low_counts: Some(1995),
        high_counts: Some(2030),
        ..base_hysteretic()
    })
    .unwrap();
    assert_eq!((law.low_counts, law.high_counts), (1995, 2030));
}

#[test]
fn test_rejects_nonsense() {
    // Python builds these with dict(base, ...) mutations of
    // {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout"} and
    // expects ControlLawError for each (unittest subTest labels).
    let cases: Vec<(&str, LawInput)> = vec![
        (
            "kind=sine",
            LawInput {
                kind: Some("sine".to_string()),
                ..base_hysteretic()
            },
        ),
        (
            "hysteresis_v=0 (no dead band)",
            LawInput {
                hysteresis_v: Some(0.0),
                ..base_hysteretic()
            },
        ),
        (
            "hysteresis_v > target_v",
            LawInput {
                target_v: Some(1.0),
                hysteresis_v: Some(2.0),
                ..base_hysteretic()
            },
        ),
        (
            "vhigh=99",
            LawInput {
                vhigh: Some(99.0),
                ..base_hysteretic()
            },
        ),
        (
            "divider=0",
            LawInput {
                divider: Some(0.0),
                ..base_hysteretic()
            },
        ),
        (
            "low_counts > high_counts",
            LawInput {
                low_counts: Some(3000),
                high_counts: Some(100),
                ..base_hysteretic()
            },
        ),
        (
            "adc_bits=40",
            LawInput {
                adc_bits: Some(40),
                ..base_hysteretic()
            },
        ),
        (
            "no pin",
            LawInput {
                pin: None,
                ..base_hysteretic()
            },
        ),
        (
            "no sense_net",
            LawInput {
                sense_net: None,
                ..base_hysteretic()
            },
        ),
        (
            "pwm carrier_hz=0",
            LawInput {
                kind: Some("pwm".to_string()),
                pin: Some("P1".to_string()),
                carrier_hz: Some(0.0),
                ..base_hysteretic()
            },
        ),
    ];
    for (label, input) in &cases {
        expect_normalize_fail(input, label);
    }
}

#[test]
fn test_describe_never_raises_on_junk() {
    let input = LawInput {
        kind: Some("banana".to_string()),
        ..Default::default()
    };
    assert_contains(&describe_law(&input), "invalid");
}

// ==========================================================================
// tests/test_cosim_control.py::TestHystereticDecision
// ==========================================================================

/// counts_for(volts) = _to_counts(volts * 0.5, 3.3, 12)
fn counts_for(volts: f64) -> i64 {
    to_counts_raw(volts * 0.5, 3.3, 12)
}

fn cosim_derived_law() -> ControlLaw {
    make_law(&LawInput {
        target_v: Some(3.3),
        hysteresis_v: Some(0.165),
        divider: Some(0.5),
        ..base_hysteretic()
    })
    .unwrap()
}

#[test]
fn test_below_band_drives_high() {
    let mut law = cosim_derived_law();
    let below = counts_for(3.3 - 0.5);
    assert!(below < law.low_counts);
    assert!(law.decide(below));
}

#[test]
fn test_above_band_drives_low() {
    let mut law = cosim_derived_law();
    let above = counts_for(3.3 + 0.5);
    assert!(above > law.high_counts);
    assert!(!law.decide(above));
}

// Same name as the test_control_law_unit.py test of the same name, but a
// different fixture: this one runs on counts derived from target+hysteresis
// (1945/2150) rather than the firmware's explicit 1995/2030, so it exercises
// the derived-threshold path.  One fn per name in Rust, hence the _cosim
// suffix - it names the source file, not a variation.
#[test]
fn test_inside_band_holds_previous_state_cosim() {
    let mut law = cosim_derived_law();
    let inside = (law.low_counts + law.high_counts) / 2;
    law.level = true;
    assert!(law.decide(inside));
    law.level = false;
    assert!(!law.decide(inside));
}

#[test]
fn test_update_counts_switches_only_on_a_level_change() {
    let mut law = cosim_derived_law();
    let low = counts_for(0.0);
    let high = counts_for(5.0);

    assert_eq!(law.update(0.0, 0.0), 3.3); // LOW counts -> HIGH
    assert_eq!(law.switch_count, 1);
    assert_eq!(law.update(5.0, 1e-6), 0.0); // HIGH counts -> LOW
    assert_eq!(law.switch_count, 2);
    law.update(5.0, 2e-6); // hold LOW
    assert_eq!(law.switch_count, 2);
    // 0 V sense reads as 0 counts; 5 V through the 0.5 divider saturates
    // nothing.
    assert_eq!(low, 0);
    assert_eq!(high, 3102);
}

// ==========================================================================
// tests/test_cosim_control.py::TestFirmwareImport
// ==========================================================================

#[test]
fn test_reads_thresholds_and_gate_pin_from_real_source() {
    let consts = read_firmware_constants(FIRMWARE_MAIN_C).unwrap();
    assert_eq!(consts.pin, "GPIO18");
    assert_eq!(consts.low, 1995);
    assert_eq!(consts.high, 2030);
}

#[test]
fn test_imported_spec_keeps_the_file_counts() {
    let spec = firmware_law("fb", 1.0);
    assert_eq!(spec.pin.as_deref(), Some("GPIO18"));
    assert_eq!(spec.source.as_deref(), Some("main.c"));
    let norm = normalize_law(&spec).unwrap();
    assert_eq!(norm.low_counts, Some(1995));
    assert_eq!(norm.high_counts, Some(2030));
}

#[test]
fn test_missing_file_and_missing_constants_are_reported() {
    let err =
        read_firmware_constants("does/not/exist.c").unwrap_err();
    // Python only checks the exception type here; the C reference also pins
    // that the message says what went wrong.
    assert_contains(err.message(), "not found");

    let path = write_tmp("empty.c", "int main(void) { return 0; }\n");
    let err = read_firmware_constants(path.to_str().unwrap()).unwrap_err();
    assert_contains(err.message(), "ADC_LOW_THRESHOLD");
    let _ = std::fs::remove_file(&path);
}

#[test]
fn test_inverted_thresholds_are_rejected() {
    let path = write_tmp(
        "bad.c",
        "#define ADC_LOW_THRESHOLD 3000\n\
         #define ADC_HIGH_THRESHOLD 100\n\
         #define GATE_PIN GPIO_NUM_4\n",
    );
    let err = read_firmware_constants(path.to_str().unwrap()).unwrap_err();
    // Python asserts only the exception; the C reference pins the wording.
    assert_contains(err.message(), "nonsense thresholds");
    let _ = std::fs::remove_file(&path);
}

// ==========================================================================
// tests/test_cosim_control.py::TestDividerSemantics
// ==========================================================================

#[test]
fn test_thresholds_are_counts_at_the_pin() {
    let s = firmware_law("fb", 1.0);
    assert_eq!(s.low_counts, Some(1995));
    assert_eq!(s.high_counts, Some(2030));
    assert_eq!(
        s.divider,
        Some(1.0),
        "a pin-referenced sense net needs no divider"
    );
}

#[test]
fn test_pin_voltages_invert_the_firmware_mapping() {
    let s = firmware_law("fb", 1.0);
    let (lo, hi) = implied_pin_voltages(&s).unwrap();
    // 1995/4095*3.3 and 2030/4095*3.3
    assert_places(lo, 1.6077, 3);
    assert_places(hi, 1.6359, 3);
}

#[test]
fn test_midpoint_matches_the_firmware_comment() {
    // main.c claims ~2012 counts is 3.24 V out.  Check it.
    let s = firmware_law("fb", 1.0);
    let (lo, hi) = implied_pin_voltages(&s).unwrap();
    let mid_out = ((lo + hi) / 2.0) / 0.5; // 2:1 divider to vout
    assert_places(mid_out, 3.2436, 3);
    assert_places(mid_out, 3.24, 1);
}

#[test]
fn test_picking_the_undivided_node_halves_the_target() {
    // The trap: sense_net='vout' regulates to half the intended voltage.
    let s = firmware_law("fb", 1.0);
    let (lo, hi) = implied_output_voltages(&s, 0.5).unwrap();
    assert_places(lo, 3.2154, 3);
    assert_places(hi, 3.2718, 3);
    // Same numbers with the divider applied twice would be half again.
    assert_places(hi / 2.0, 1.6359, 3);
}

#[test]
fn test_bad_pin_divider_is_rejected() {
    let s = firmware_law("fb", 1.0);
    let err = implied_output_voltages(&s, 0.0).unwrap_err();
    assert_contains(err.message(), "pin_divider");
}

#[test]
fn test_undivided_sense_net_with_a_divider_reproduces_the_counts() {
    // Naming the undivided net must not change the switching points.  This
    // was wrong and nothing caught it: law_from_firmware_source() divided
    // its recovered target by `divider` but left hysteresis_v in pin volts,
    // so normalize_law() multiplied both by divider again and the band came
    // out halved - 2004/2020 instead of 1995/2030, a 35% narrower deadband.
    let vout = law_from_firmware_source(
        FIRMWARE_MAIN_C,
        "vout",
        0.5,
        DEFAULT_VHIGH,
        DEFAULT_VREF,
        DEFAULT_ADC_BITS,
    )
    .unwrap();
    let s = normalize_law(&vout).unwrap();
    assert_eq!(s.low_counts, Some(1995));
    assert_eq!(s.high_counts, Some(2030));
}

#[test]
fn test_the_two_sense_nets_agree_exactly() {
    // fb at divider 1.0 and vout at divider 0.5 are one law, not two.
    let a = normalize_law(
        &law_from_firmware_source(
            FIRMWARE_MAIN_C,
            "fb",
            1.0,
            DEFAULT_VHIGH,
            DEFAULT_VREF,
            DEFAULT_ADC_BITS,
        )
        .unwrap(),
    )
    .unwrap();
    let b = normalize_law(
        &law_from_firmware_source(
            FIRMWARE_MAIN_C,
            "vout",
            0.5,
            DEFAULT_VHIGH,
            DEFAULT_VREF,
            DEFAULT_ADC_BITS,
        )
        .unwrap(),
    )
    .unwrap();
    assert_eq!(
        (a.low_counts, a.high_counts),
        (b.low_counts, b.high_counts)
    );
    assert_places(a.target_v, b.target_v * 0.5, 4);
}

// ==========================================================================
// tests/test_cosim_control.py::TestFidelityGap
// ==========================================================================

fn ascii_ws(c: u8) -> bool {
    matches!(c, b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c)
}

/// `#define\s+ADC_OVERSAMPLE_N\s+(\d+)` - the unanchored Python re.search of
/// test_oversample_count_is_not_silently_ignored: the value must still be a
/// #define, because the point of the test is that the constant remains a
/// constant the firmware actually compiles.
fn oversample_define_value(src: &str) -> Option<i64> {
    let b = src.as_bytes();
    let n = b.len();
    let mut i = 0usize;
    while i + 7 <= n {
        if &b[i..i + 7] != b"#define" {
            i += 1;
            continue;
        }
        let mut j = i + 7;
        let ws_start = j;
        while j < n && ascii_ws(b[j]) {
            j += 1;
        }
        if j == ws_start || j + 16 > n {
            i += 1;
            continue;
        }
        if &b[j..j + 16] != b"ADC_OVERSAMPLE_N" {
            i += 1;
            continue;
        }
        j += 16;
        let ws_start = j;
        while j < n && ascii_ws(b[j]) {
            j += 1;
        }
        if j == ws_start {
            i += 1;
            continue;
        }
        let ds = j;
        while j < n && b[j].is_ascii_digit() {
            j += 1;
        }
        if j == ds {
            i += 1;
            continue;
        }
        return std::str::from_utf8(&b[ds..j]).ok()?.parse::<i64>().ok();
    }
    None
}

#[test]
fn test_oversample_count_is_not_silently_ignored() {
    // Oversampling changes the loop, so its value must stay visible.
    // Python: m = re.search(...); assertIsNotNone (msg: "ADC_OVERSAMPLE_N
    // is not a #define any more"); assertGreaterEqual(int(m.group(1)), 1).
    let n = oversample_define_value(&firmware_source());
    let n = n.unwrap_or_else(|| panic!("ADC_OVERSAMPLE_N is not a #define any more"));
    assert!(n >= 1);
}

// Three more TestFidelityGap tests exist in test_cosim_control.py
// (firmware_still_oversamples / _calibrates_the_adc / _states_counts_are_raw);
// they assert the same three substrings against the same main.c as the unit
// file's fidelity trio above, so they are one coverage each, not two - same
// reasoning as the C port's.

// ==========================================================================
// tests/test_cosim_control.py::TestPwmLaw
// ==========================================================================

#[test]
fn test_duty_grows_as_feedback_falls() {
    let mut law = make_law(&LawInput {
        kind: Some("pwm".to_string()),
        pin: Some("PWM0".to_string()),
        sense_net: Some("vout".to_string()),
        target_v: Some(3.3),
        carrier_hz: Some(1000.0),
        duty_gain: Some(0.5),
        ..Default::default()
    })
    .unwrap();
    // Python: low_error = high_error = 0.0
    let mut low_error = 0.0;
    let mut high_error = 0.0;
    let mut i = 0;
    loop {
        if i == 2000 {
            break;
        }
        law.update(3.0, i as f64 * 1e-7); // close to target
        low_error = law.duty;
        law.update(0.5, i as f64 * 1e-7); // far below target
        high_error = law.duty;
        i += 1;
    }
    assert!(high_error > low_error);
    assert!(high_error <= 1.0);
    assert!(low_error >= 0.0);
}

#[test]
fn test_duty_saturates_rather_than_exceeding_one() {
    let mut law = make_law(&LawInput {
        kind: Some("pwm".to_string()),
        pin: Some("PWM0".to_string()),
        sense_net: Some("vout".to_string()),
        target_v: Some(3.3),
        duty_gain: Some(100.0),
        ..Default::default()
    })
    .unwrap();
    law.update(0.0, 0.0);
    assert!(law.duty <= 1.0);
}

// ==========================================================================
// C-ONLY ADDITIONS - not ports of any Python test.  (Same four as
// native/tests/test_control_law.c, kept under the same label.)
//
// Marked loudly because the file header promises a port, and a reader who
// assumes every test here mirrors one over there would be wrong.
//
// They cover API that the Python suite does not test:
//   - regulation_error() has NO test in tests/ at all.
//   - stats() is asserted exactly once, indirectly, inside an end-to-end
//     test of the report line (test_cosim_control.py line 278); its shape
//     on an empty run and its counts fields are otherwise unexercised.
//   - describe() is covered in Python via describe_law(), but not for an
//     already-constructed law.
//
// If the Python suite grows equivalents, fold these into the ported set
// and delete this note.
// ==========================================================================

#[test]
fn test_stats_reports_a_run() {
    let mut law = make_law(&fixture_with_counts()).unwrap();
    let st = law.stats();
    assert_eq!(st.samples, 0);
    assert_eq!(st.switches, 0);
    assert_eq!(st.duty, 0.0);
    assert_eq!(st.counts_min, None); // Python reports None, not 0
    assert_eq!(st.counts_max, None);
    assert_eq!(st.counts_last, None);
    assert_eq!(st.final_level, "LOW");

    for i in 0..10 {
        law.update(if i % 2 != 0 { 5.0 } else { 0.0 }, i as f64 * 1e-6);
    }
    let st = law.stats();
    assert_eq!(st.samples, 10);
    assert!(st.switches >= 2);
    assert!(st.duty > 0.0 && st.duty < 1.0);
    assert_eq!(st.counts_min, Some(0));
    assert_eq!(st.counts_max, Some(3102));
    assert_eq!(st.counts_last, Some(3102));
    assert_eq!(st.kind, LawKind::Hysteretic);
    assert_eq!(st.pin, "GPIO18");
    assert_eq!(st.sense_net, "vout");
}

#[test]
fn test_describe_names_the_law() {
    // A spec with a pin and a sense net - describe() needs both, which is
    // precisely why describe_law() exists for the case where it has neither.
    let law = make_law(&base_hysteretic()).unwrap();
    let out = law.describe();
    assert_contains(&out, "hysteretic");
    assert_contains(&out, "vout");
}

#[test]
fn test_regulation_error_skips_startup() {
    // Ignores the first fifth of the samples: an inductor charging from zero
    // is start-up, not regulation error.  n=5 skips exactly one sample.
    let samples: [i64; 5] = [0, 12, 8, 12, 8];
    let re = regulation_error(&samples, 10, 3.3, 12).unwrap();
    assert_near(re.mean_error_counts.unwrap(), 0.0, 1e-12); // mean of +2,-2,+2,-2
    assert_near(re.max_error_counts.unwrap(), 2.0, 1e-12);
    assert_near(re.final_error_counts.unwrap(), -2.0, 1e-12); // tail[-1] = 8
    assert_near(re.mean_error_v.unwrap(), 0.0, 1e-12);
}

#[test]
fn test_regulation_error_empty_and_single_sample() {
    let re = regulation_error(&[], 10, 3.3, 12).unwrap();
    // Python returns all-None.
    assert_eq!(re.mean_error_counts, None);
    assert_eq!(re.max_error_counts, None);
    assert_eq!(re.mean_error_v, None);
    assert_eq!(re.final_error_counts, None);

    // Python raises ZeroDivisionError for a single sample; C refuses by
    // status, and this port by error.  All three are failures - none
    // invents a number.
    let one: [i64; 1] = [1995];
    assert!(regulation_error(&one, 10, 3.3, 12).is_err());
}
