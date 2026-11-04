/*
 * test_gpio_model.rs - port of the gpio_model parts of
 * tests/test_firmware_gpio.py (TestGpioProfile, TestLogicAnalysis) and
 * tests/test_editor_workflow.py (the three pin_map tests).
 *
 * Line-for-line transcription of the Python assertions; tests the Python
 * files do not have are labelled `// RUST-ONLY ADDITION`.
 *
 * NOT ported from tests/test_firmware_gpio.py: TestIntelHex, TestElf,
 * TestGpioCosimEndToEnd and test_pin_profile_json_parsing - they belong to
 * firmware.rs (HEX/ELF/JSON parsing) or need the live ngspice solver; see
 * the header of src/gpio_model.rs.
 */

use std::collections::{BTreeMap, HashMap};

use wowkispice_core::gpio_model::{
    self, analyze_pin, describe_pin, is_output_pin, logic_levels, measured_frequency,
    pin_direction, pin_map, normalize_profile, spice_card, ComponentView, ControlLawView,
    PinMapModel, ProfileSpec, DEFAULT_EDGE_TIME, DEFAULT_THRESHOLD,
};

// --------------------------------------------------------------- fixtures

fn spec(mode: &str) -> ProfileSpec {
    ProfileSpec { mode: Some(mode.to_string()), ..Default::default() }
}

fn square(freq_hz: f64, duty: f64) -> ProfileSpec {
    ProfileSpec {
        mode: Some("square".to_string()),
        freq_hz: Some(freq_hz),
        duty: Some(duty),
        ..Default::default()
    }
}

// The pin_map stub: the Python tests use cad_engine's SchematicNetlistEngine
// (not part of this port), whose observable surface for pin_map is exactly
// components.get(comp_id) and _resolve_nets()[0] - the PinMapModel trait.
struct StubComp {
    comp_type: &'static str,
    pins: BTreeMap<String, String>,
}

struct StubModel {
    components: HashMap<String, StubComp>,
    net_of: HashMap<(String, String), String>,
}

impl StubModel {
    fn new() -> Self {
        StubModel { components: HashMap::new(), net_of: HashMap::new() }
    }

    fn with_comp(mut self, comp_id: &str, comp_type: &'static str, pins: &[&str]) -> Self {
        let mut map = BTreeMap::new();
        for p in pins {
            map.insert(p.to_string(), String::new());
        }
        self.components.insert(
            comp_id.to_string(),
            StubComp { comp_type, pins: map },
        );
        self
    }

    fn with_net(mut self, comp_id: &str, pin: &str, net: &str) -> Self {
        self.net_of
            .insert((comp_id.to_string(), pin.to_string()), net.to_string());
        self
    }
}

impl PinMapModel for StubModel {
    fn component(&self, comp_id: &str) -> Option<ComponentView<'_>> {
        self.components.get(comp_id).map(|c| ComponentView {
            comp_type: c.comp_type,
            pins: &c.pins,
        })
    }

    fn resolve_nets(&self) -> HashMap<(String, String), String> {
        self.net_of.clone()
    }
}

fn empty_maps() -> (HashMap<String, HashMap<String, ProfileSpec>>, HashMap<String, ControlLawView>) {
    (HashMap::new(), HashMap::new())
}

// ============================================ TestGpioProfile (transcribed)

#[test]
fn test_static_pin_emits_dc_card() {
    let hi = ProfileSpec {
        mode: Some("static".to_string()),
        level: Some(1.0),
        ..Default::default()
    };
    let lo = ProfileSpec {
        mode: Some("static".to_string()),
        level: Some(0.0),
        ..Default::default()
    };
    assert_eq!(
        spice_card(Some(&hi), DEFAULT_EDGE_TIME).unwrap(),
        "DC 3.3"
    );
    assert_eq!(
        spice_card(Some(&lo), DEFAULT_EDGE_TIME).unwrap(),
        "DC 0"
    );
}

#[test]
fn test_square_pin_emits_pulse_with_right_period_and_duty() {
    let card = spice_card(Some(&square(1000.0, 0.25)), DEFAULT_EDGE_TIME).unwrap();
    assert!(
        card.starts_with("PULSE(0 3.3"),
        "unexpected card: {}",
        card
    );
    let body = &card["PULSE(".len()..card.len() - 1];
    let parts: Vec<&str> = body.split_whitespace().collect();
    let on_time: f64 = parts[5].parse().unwrap();
    let period: f64 = parts[6].parse().unwrap();
    // Python: assertAlmostEqual(period, 0.001, places=6) ->
    // round(period - 0.001, 6) == 0, i.e. |delta| <= 5e-7 (the exact tie
    // Python also accepts cannot occur: 1.0/1000 is the same double as
    // the literal 0.001, so the delta is 0 here).
    assert!((period - 0.001).abs() <= 5e-7, "period={}", period);
    // places=3 -> |delta| <= 5e-4, same reasoning.
    assert!(
        (on_time / period - 0.25).abs() <= 5e-4,
        "on_time/period={}",
        on_time / period
    );
}

#[test]
fn test_default_is_idle_low() {
    assert_eq!(spice_card(None, DEFAULT_EDGE_TIME).unwrap(), "DC 0");
}

#[test]
fn test_rejects_nonsense() {
    let bads: Vec<ProfileSpec> = vec![
        spec("sine"),
        ProfileSpec { mode: Some("square".to_string()), freq_hz: Some(0.0), ..Default::default() },
        ProfileSpec { mode: Some("square".to_string()), duty: Some(0.0), ..Default::default() },
        ProfileSpec { vhigh: Some(99.0), ..Default::default() },
    ];
    for bad in &bads {
        assert!(
            spice_card(Some(bad), DEFAULT_EDGE_TIME).is_err(),
            "expected ValueError for {:?}",
            bad
        );
    }
}

// NOT PORTED: test_pin_profile_json_parsing - parse_pin_profile lives in
// firmware.py and is firmware.rs's contract, not gpio_model's.

#[test]
fn test_describe_pin_is_human_readable() {
    let text = describe_pin("GPIO18", Some(&square(1000.0, 0.5))).unwrap();
    assert!(text.contains("1000 Hz"), "got: {}", text);
    assert!(text.contains("50%"), "got: {}", text);
}

// ======================================== TestLogicAnalysis (transcribed)

#[test]
fn test_detects_levels_duty_and_frequency() {
    // 5 us steps, toggling every 100 samples -> 1 kHz square wave
    let mut times = Vec::new();
    let mut values = Vec::new();
    for i in 0..2000 {
        // 10 ms window
        times.push(i as f64 * 5e-6);
        values.push(if (i / 100) % 2 == 0 { 0.0 } else { 3.3 });
    }
    let info = analyze_pin(&times, &values, DEFAULT_THRESHOLD);
    assert!(info.transitions > 10, "transitions={}", info.transitions);
    // delta=0.06 -> |delta| <= 0.06
    assert!(
        (info.duty - 0.5).abs() <= 0.06,
        "duty={}",
        info.duty
    );
    // places=3 -> |delta| <= 5e-4
    assert!(
        (info.v_max.unwrap() - 3.3).abs() <= 5e-4,
        "v_max={:?}",
        info.v_max
    );
    let freq = measured_frequency(&times, &values, DEFAULT_THRESHOLD).unwrap();
    // delta=40 -> |delta| <= 40
    assert!((freq - 1000.0).abs() <= 40.0, "freq={}", freq);
}

#[test]
fn test_static_signal_has_no_transitions() {
    let times: Vec<f64> = (0..10).map(|i| i as f64 * 1e-3).collect();
    let values = vec![3.3; 10];
    let info = analyze_pin(&times, &values, DEFAULT_THRESHOLD);
    assert_eq!(info.transitions, 0);
    assert!(measured_frequency(&times, &values, DEFAULT_THRESHOLD).is_none());
}

// ================================== pin_map tests (test_editor_workflow.py)

#[test]
fn test_pin_map_lists_every_declared_pin() {
    // U1.D5 -> R1 -> GND, extracted from arduino_circuit() in
    // tests/test_editor_workflow.py (probed against the real cad_engine:
    // pins {'D5', 'GND'}, net_of D5 -> "led", GND -> "0").
    let g = StubModel::new()
        .with_comp("U1", "ARDUINO_UNO", &["D5", "GND"])
        .with_net("U1", "D5", "led")
        .with_net("U1", "GND", "0");
    let mut profiles: HashMap<String, HashMap<String, ProfileSpec>> = HashMap::new();
    profiles.insert(
        "U1".to_string(),
        [("D5".to_string(), square(1000.0, 0.5))].into(),
    );
    let (_p, laws) = empty_maps();

    let pins = pin_map(&g, "U1", &profiles, &laws).unwrap();
    let names: Vec<&str> = pins.iter().map(|r| r.pin.as_str()).collect();
    assert!(names.contains(&"D5"), "names={:?}", names);
    assert!(names.contains(&"GND"), "names={:?}", names);

    let d5 = pins.iter().find(|r| r.pin == "D5").unwrap();
    assert_eq!(d5.role, "output");
    assert!(d5.wired);
    assert!(d5.behaviour.contains("1000 Hz"), "behaviour={}", d5.behaviour);

    let gnd = pins.iter().find(|r| r.pin == "GND").unwrap();
    assert_eq!(gnd.direction, "power");
}

#[test]
fn test_pin_map_flags_an_unwired_pin_as_absent() {
    // A freshly placed board symbol with no wires has no pins at all, so
    // pin_map lists nothing - an empty pin table, not a hidden one.
    let (profiles, laws) = empty_maps();
    let g = StubModel::new().with_comp("U1", "ARDUINO_UNO", &[]);
    assert!(pin_map(&g, "U1", &profiles, &laws).unwrap().is_empty());
    assert!(pin_map(&g, "U1", &profiles, &laws).unwrap().is_empty());

    // Unknown component id -> empty, as Python's components.get() returning
    // None does.
    let g2 = StubModel::new();
    assert!(pin_map(&g2, "NOPE", &profiles, &laws).unwrap().is_empty());
}

#[test]
fn test_pin_map_reports_a_non_mcu_as_empty() {
    let (profiles, laws) = empty_maps();
    let g = StubModel::new().with_comp("R1", "R", &["1"]);
    assert!(pin_map(&g, "R1", &profiles, &laws).unwrap().is_empty());
}

// ==================================== RUST-ONLY ADDITION: error wording

// The Python tests only assert that a ValueError is raised; the port pins
// the verbatim f-string messages, because callers and the parity battery
// compare them as text.  Every float formats through Python's str(float).
#[test]
fn test_normalize_error_messages_are_verbatim_python() {
    let err = normalize_profile(Some(&spec("sine"))).unwrap_err();
    assert_eq!(
        err.to_string(),
        "unsupported GPIO mode 'sine' (use 'static' or 'square')"
    );
    // Python lowercases the mode BEFORE formatting the message.
    let err = normalize_profile(Some(&spec("SINE"))).unwrap_err();
    assert_eq!(
        err.to_string(),
        "unsupported GPIO mode 'sine' (use 'static' or 'square')"
    );

    let err = normalize_profile(Some(&ProfileSpec { vhigh: Some(99.0), ..Default::default() }))
        .unwrap_err();
    assert_eq!(err.to_string(), "vhigh must be 0..24 V, got 99.0");

    let err = normalize_profile(Some(&ProfileSpec { vhigh: Some(0.0), ..Default::default() }))
        .unwrap_err();
    assert_eq!(err.to_string(), "vhigh must be 0..24 V, got 0.0");

    let err = normalize_profile(Some(&ProfileSpec {
        mode: Some("square".to_string()),
        freq_hz: Some(0.0),
        ..Default::default()
    }))
    .unwrap_err();
    assert_eq!(err.to_string(), "freq_hz must be > 0, got 0.0");

    let err = normalize_profile(Some(&ProfileSpec {
        mode: Some("square".to_string()),
        duty: Some(0.0),
        ..Default::default()
    }))
    .unwrap_err();
    assert_eq!(err.to_string(), "duty must be in (0, 1], got 0.0");

    // NaN formats as "nan" on both sides (probed from CPython).
    let err = normalize_profile(Some(&ProfileSpec {
        vhigh: Some(f64::NAN),
        ..Default::default()
    }))
    .unwrap_err();
    assert_eq!(err.to_string(), "vhigh must be 0..24 V, got nan");
    let err = normalize_profile(Some(&ProfileSpec {
        mode: Some("square".to_string()),
        duty: Some(f64::NAN),
        ..Default::default()
    }))
    .unwrap_err();
    assert_eq!(err.to_string(), "duty must be in (0, 1], got nan");
    // ...but a NaN freq_hz passes Python's `freq <= 0` check (NaN compares
    // False) and yields a PULSE card with nan fields - pinned so nobody
    // "fixes" it into an error.
    let card = spice_card(
        Some(&ProfileSpec {
            mode: Some("square".to_string()),
            freq_hz: Some(f64::NAN),
            ..Default::default()
        }),
        DEFAULT_EDGE_TIME,
    )
    .unwrap();
    assert_eq!(card, "PULSE(0 3.3 0 1e-07 1e-07 nan nan)");

    // Validation order: mode is checked before vhigh.
    let err = normalize_profile(Some(&ProfileSpec {
        mode: Some("sine".to_string()),
        vhigh: Some(99.0),
        ..Default::default()
    }))
    .unwrap_err();
    assert!(err.message().starts_with("unsupported GPIO mode"));
}

// ==================================== RUST-ONLY ADDITION: spice_card edges

#[test]
fn test_spice_card_edge_time_forms() {
    let sq = square(1000.0, 0.5);
    // edge_time 0 -> zero rise/fall (Python min(0, period/20) = 0).
    assert_eq!(
        spice_card(Some(&sq), 0.0).unwrap(),
        "PULSE(0 3.3 0 0 0 0.0005 0.001)"
    );
    // A large edge clamps to half a period / 20.
    assert_eq!(
        spice_card(Some(&sq), 1.0).unwrap(),
        "PULSE(0 3.3 0 5e-05 5e-05 0.0005 0.001)"
    );
    // A NaN edge keeps Python's choice of min (first operand), where Rust's
    // f64::min would drop the NaN - the transcription is `y < x ? y : x`.
    let card = spice_card(Some(&sq), f64::NAN).unwrap();
    assert_eq!(card, "PULSE(0 3.3 0 nan nan 0.0005 0.001)");

    // %g boundaries: exponential below 1e-4 and at/above 1e6.
    let lo = ProfileSpec {
        mode: Some("static".to_string()),
        level: Some(1.0),
        vhigh: Some(1e-5),
        ..Default::default()
    };
    assert_eq!(spice_card(Some(&lo), DEFAULT_EDGE_TIME).unwrap(), "DC 1e-05");
    let lo2 = ProfileSpec {
        mode: Some("static".to_string()),
        level: Some(1.0),
        vhigh: Some(0.0001),
        ..Default::default()
    };
    assert_eq!(
        spice_card(Some(&lo2), DEFAULT_EDGE_TIME).unwrap(),
        "DC 0.0001"
    );

    // Very fast carrier: period 1e-9, so period/20 = 5e-11 clamps the edge
    // well below the 1e-7 default, and %g writes the period as 1e-09.
    let fast = ProfileSpec {
        mode: Some("square".to_string()),
        freq_hz: Some(1e9),
        duty: Some(0.5),
        ..Default::default()
    };
    assert_eq!(
        spice_card(Some(&fast), DEFAULT_EDGE_TIME).unwrap(),
        "PULSE(0 3.3 0 5e-11 5e-11 5e-10 1e-09)"
    );
}

// ==================================== RUST-ONLY ADDITION: describe_pin edges

#[test]
fn test_describe_pin_fixed0_is_round_half_even() {
    // duty * 100 lands on an exact tie: 0.025 * 100 == 2.5, and Python's
    // `.0f` rounds half to EVEN -> "2%" (probed from CPython).
    let text = describe_pin("GPIO4", Some(&square(250.0, 0.025))).unwrap();
    assert_eq!(text, "GPIO4: square 250 Hz, 2% duty @ 3.3 V");

    // Static forms.
    let hi = ProfileSpec {
        mode: Some("static".to_string()),
        level: Some(1.0),
        vhigh: Some(5.0),
        ..Default::default()
    };
    assert_eq!(describe_pin("D2", Some(&hi)).unwrap(), "D2: HIGH @ 5 V");
    let lo = ProfileSpec { mode: Some("static".to_string()), ..Default::default() };
    assert_eq!(describe_pin("D2", Some(&lo)).unwrap(), "D2: LOW @ 3.3 V");

    // A spec that fails normalisation propagates the same ValueError.
    assert!(describe_pin("D2", Some(&spec("sine"))).is_err());
}

// ==================================== RUST-ONLY ADDITION: pin_direction

#[test]
fn test_pin_direction_heuristic() {
    // power (checked before the analog/prefix rules)
    for pin in ["GND", "gnd", "0", "VCC", "5V", "3V3", "VIN", "VCC3V3",
                "AREF", "NRST", "EN"] {
        assert_eq!(pin_direction(pin), "power", "pin={}", pin);
    }
    // analog: "A" + digits only (A10 counts, even though _ANALOG_PINS
    // lists only A0..A7 - that tuple is dead in Python too), and ADC*
    for pin in ["A0", "A7", "A10", "adc2", "ADC0"] {
        assert_eq!(pin_direction(pin), "analog", "pin={}", pin);
    }
    // "A" alone and "AX1" are not A+digits -> fall through
    assert_eq!(pin_direction("A"), "bidirectional");
    assert_eq!(pin_direction("AX1"), "bidirectional");
    // The listed prefix families - and everything else - are
    // "bidirectional" (Python's branch and its fallback agree).
    for pin in ["D5", "GPIO18", "PA5", "PB0", "PC13", "PD2", "PE0", "PF3",
                "PG1", "PH0", "LED1", "SCL", "SDA", "TX", "RX", "SCK",
                "MOSI", "MISO", "banana", "", "gpio18", "sda"] {
        assert_eq!(pin_direction(pin), "bidirectional", "pin={}", pin);
    }
}

// ==================================== RUST-ONLY ADDITION: waveform edges

#[test]
fn test_logic_levels_edges() {
    // Empty or mismatched input -> no transitions at all.
    assert!(logic_levels(&[], &[], DEFAULT_THRESHOLD).is_empty());
    assert!(logic_levels(&[1.0], &[1.0, 2.0], DEFAULT_THRESHOLD).is_empty());

    // Threshold equality: >= is inclusive, so 1.65 is HIGH.
    let t = logic_levels(&[0.0, 1.0], &[1.65, 1.6499], DEFAULT_THRESHOLD);
    assert_eq!(t, vec![(0.0, true), (1.0, false)]);

    // A single sample still reports the initial state.
    let t = logic_levels(&[5.0], &[3.3], DEFAULT_THRESHOLD);
    assert_eq!(t, vec![(5.0, true)]);

    // Descending timestamps are not reordered: transitions follow the
    // sample order, and the initial state comes from the FIRST sample.
    let t = logic_levels(&[2.0, 1.0, 0.0], &[3.3, 0.0, 3.3], DEFAULT_THRESHOLD);
    assert_eq!(t, vec![(2.0, true), (1.0, false), (0.0, true)]);

    // The threshold parameter is honoured (Python's third argument).
    let t = logic_levels(&[0.0, 1.0], &[0.9, 1.1], 1.0);
    assert_eq!(t, vec![(0.0, false), (1.0, true)]);
}

#[test]
fn test_analyze_pin_edges() {
    // Mismatched lengths: early return, but points counts len(values).
    let info = analyze_pin(&[1.0], &[1.0, 2.0], DEFAULT_THRESHOLD);
    assert_eq!(info.points, 2);
    assert_eq!(info.transitions, 0);
    assert_eq!(info.duty, 0.0);
    assert!(info.v_min.is_none());
    assert!(info.v_max.is_none());
    assert!(info.levels.is_empty());

    // A single sample is below the len >= 2 bar too - even though values
    // is non-empty, Python's early return omits v_min/v_max.
    let info = analyze_pin(&[0.0], &[3.3], DEFAULT_THRESHOLD);
    assert_eq!(info.points, 1);
    assert!(info.v_min.is_none());

    // Descending window: high_time is negative and window <= 0, so duty
    // is 0.0 rather than a negative fraction.
    let info = analyze_pin(&[2.0, 1.0, 0.0], &[3.3, 0.0, 3.3], DEFAULT_THRESHOLD);
    assert_eq!(info.transitions, 2);
    assert_eq!(info.duty, 0.0);
    assert_eq!(info.v_min, Some(0.0));
    assert_eq!(info.v_max, Some(3.3));

    // Zero-width window (all samples at t=0) -> duty 0.0, no division by 0.
    let info = analyze_pin(&[0.0, 0.0], &[3.3, 0.0], DEFAULT_THRESHOLD);
    assert_eq!(info.duty, 0.0);

    // Initial HIGH: the first segment counts toward duty.
    // t: 0(high) 1(high) 2(low) 3(low), window 3 -> high_time 2 -> 2/3.
    let info = analyze_pin(&[0.0, 1.0, 2.0, 3.0], &[3.3, 3.3, 0.0, 0.0], DEFAULT_THRESHOLD);
    assert!((info.duty - 2.0 / 3.0).abs() < 1e-15, "duty={}", info.duty);
    assert_eq!(info.transitions, 1);
}

#[test]
fn test_measured_frequency_edges() {
    // Starts HIGH: the initial state counts as a rise (Python's i == 0
    // condition), so rises = [0.0, 1.0] -> period 1.0 -> 1.0 Hz.
    let f = measured_frequency(
        &[0.0, 0.5, 1.0, 1.5],
        &[3.3, 0.0, 3.3, 0.0],
        DEFAULT_THRESHOLD,
    );
    assert_eq!(f, Some(1.0));

    // Starts HIGH and never rises again: one rise only -> None.
    let f = measured_frequency(
        &[0.0, 1.0, 2.0, 3.0],
        &[3.3, 3.3, 0.0, 0.0],
        DEFAULT_THRESHOLD,
    );
    assert!(f.is_none());

    // Two rises at the same timestamp: period 0 -> None (Python's
    // `period > 0 else None`), never an inf.
    let f = measured_frequency(
        &[0.5, 0.5, 0.5, 0.5],
        &[0.0, 3.3, 0.0, 3.3],
        DEFAULT_THRESHOLD,
    );
    assert!(f.is_none());

    // Descending timestamps: the two rises are recorded out of temporal
    // order, so the summed period is negative -> None (Python's
    // `period > 0 else None`).
    let f = measured_frequency(
        &[2.0, 1.0, 0.0, -1.0],
        &[0.0, 3.3, 0.0, 3.3],
        DEFAULT_THRESHOLD,
    );
    assert!(f.is_none());

    // Empty / mismatched -> no transitions -> None.
    assert!(measured_frequency(&[], &[], DEFAULT_THRESHOLD).is_none());
    assert!(measured_frequency(&[1.0], &[1.0, 2.0], DEFAULT_THRESHOLD).is_none());
}

// ==================================== RUST-ONLY ADDITION: pin_map branches

#[test]
fn test_pin_map_branch_order_and_none_handling() {
    let mut profiles: HashMap<String, HashMap<String, ProfileSpec>> = HashMap::new();
    profiles.insert(
        "U1".to_string(),
        [
            // law pin, whose spec is nonsense: the law branch wins and the
            // spec is never normalised (Python checks law_pin FIRST).
            ("GPIO18".to_string(), spec("sine")),
            // power pin with a nonsense spec: the power branch wins.
            ("VCC".to_string(), ProfileSpec { vhigh: Some(99.0), ..Default::default() }),
            // declared profile -> output.
            ("A0".to_string(), ProfileSpec {
                mode: Some("static".to_string()),
                level: Some(1.0),
                ..Default::default()
            }),
            // an EMPTY spec dict is falsy in Python -> "declared but
            // undriven", not an idle LOW description.
            ("D2".to_string(), ProfileSpec::default()),
        ]
        .into(),
    );
    let mut laws: HashMap<String, ControlLawView> = HashMap::new();
    laws.insert(
        "U1".to_string(),
        ControlLawView { pin: Some("GPIO18".to_string()), sense_net: Some("vout".to_string()) },
    );

    let g = StubModel::new()
        .with_comp("U1", "MCU", &["GPIO18", "VCC", "A0", "D2", "EN"])
        .with_net("U1", "GPIO18", "gate")
        .with_net("U1", "VCC", "3v3")
        .with_net("U1", "D2", "sig");
    // A0 and EN are absent from net_of: net None, wired false.

    let rows = pin_map(&g, "U1", &profiles, &laws).unwrap();
    let by_pin = |p: &str| rows.iter().find(|r| r.pin == p).unwrap().clone();

    let law = by_pin("GPIO18");
    assert_eq!(law.role, "closed-loop control output");
    assert_eq!(law.behaviour, "control law reading 'vout'");
    assert!(law.wired);

    let vcc = by_pin("VCC");
    assert_eq!(vcc.role, "power");
    assert_eq!(vcc.behaviour, "rail on net 3v3");

    let a0 = by_pin("A0");
    assert_eq!(a0.role, "output");
    assert_eq!(a0.direction, "analog");
    assert_eq!(a0.behaviour, "A0: HIGH @ 3.3 V");
    assert!(!a0.wired, "a pin missing from net_of is not wired");

    let d2 = by_pin("D2");
    assert_eq!(d2.role, "declared but undriven");
    assert_eq!(d2.behaviour, "no GPIO profile - idles LOW in simulation");

    // A power pin on net "0" is the ground rail...
    let g2 = StubModel::new()
        .with_comp("U1", "MCU", &["GND", "EN"])
        .with_net("U1", "GND", "0");
    let rows2 = pin_map(&g2, "U1", &profiles, &laws).unwrap();
    let gnd = rows2.iter().find(|r| r.pin == "GND").unwrap();
    assert_eq!(gnd.behaviour, "ground / supply rail");
    // ...and one with no net at all renders Python's f-string None.
    let en = rows2.iter().find(|r| r.pin == "EN").unwrap();
    assert_eq!(en.behaviour, "rail on net None");
    assert!(!en.wired);

    // A law whose dict has no "sense_net" quotes Python's str(None).
    // (The sine spec on GPIO18 must go first: it was only safe while
    // GPIO18 was the law pin, because the law branch skips describe_pin.
    // With the law elsewhere, Python - and this port - correctly raise on
    // it, which is asserted at the bottom of this test.)
    let mut profiles_clean = profiles.clone();
    profiles_clean.get_mut("U1").unwrap().remove("GPIO18");
    let mut laws2: HashMap<String, ControlLawView> = HashMap::new();
    laws2.insert(
        "U1".to_string(),
        ControlLawView { pin: Some("D2".to_string()), sense_net: None },
    );
    let rows3 = pin_map(&g, "U1", &profiles_clean, &laws2).unwrap();
    let d2 = rows3.iter().find(|r| r.pin == "D2").unwrap();
    assert_eq!(d2.role, "closed-loop control output");
    assert_eq!(d2.behaviour, "control law reading 'None'");

    // A law pin that is ALSO a power pin: the law branch outranks power.
    let mut laws3: HashMap<String, ControlLawView> = HashMap::new();
    laws3.insert(
        "U1".to_string(),
        ControlLawView { pin: Some("VCC".to_string()), sense_net: Some("vout".to_string()) },
    );
    let rows4 = pin_map(&g, "U1", &profiles_clean, &laws3).unwrap();
    let vcc = rows4.iter().find(|r| r.pin == "VCC").unwrap();
    assert_eq!(vcc.role, "closed-loop control output");

    // A bad profile on a NON-power, NON-law pin propagates the ValueError
    // out of pin_map, exactly as Python's describe_pin call does.
    let mut profiles2: HashMap<String, HashMap<String, ProfileSpec>> = HashMap::new();
    profiles2.insert("U1".to_string(), [("D2".to_string(), ProfileSpec { vhigh: Some(99.0), ..Default::default() })].into());
    let err = pin_map(&g, "U1", &profiles2, &laws).unwrap_err();
    assert_eq!(err.to_string(), "vhigh must be 0..24 V, got 99.0");

    // Lowercase component types are MCUs (is_mcu uppercases).
    let g3 = StubModel::new().with_comp("U1", "arduino_nano", &["D3"]);
    assert_eq!(pin_map(&g3, "U1", &profiles, &laws).unwrap().len(), 1);
}

#[test]
fn test_is_output_pin_always_true() {
    // Python returns True unconditionally: every declared pin drives its
    // net, whatever the profile says (even None).
    assert!(is_output_pin(None));
    assert!(is_output_pin(Some(&spec("static"))));
    assert!(is_output_pin(Some(&square(1000.0, 0.5))));
    // Keep the module import "used" for DEFAULT_THRESHOLD readers above.
    assert_eq!(gpio_model::DEFAULT_VHIGH, 3.3);
}
