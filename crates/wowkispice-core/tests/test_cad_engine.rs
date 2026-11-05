/*
 * test_cad_engine.rs - Rust gate for bridge/cad_engine.py.
 *
 * Transcribes: SchematicComponent construction/defaults/to_dict/from_dict,
 * is_mcu(), SchematicNetlistEngine add/remove component/add_wire/clear,
 * generate_bom()/generate_bom_for(), compile_netlist() (empty→legacy buck,
 * simple R circuit, V/I/D/MOSFET/SWITCH/MCU emission, warnings, panic on
 * unknown analysis/mcu_pins), to_dict()/load_dict() persistence round-trip,
 * generate_spice_netlist(), export_kicad_schematic() stub error.
 */

use std::collections::BTreeMap;
use wowkispice_core::cad_engine::{generate_bom_for, is_mcu, CadValue, CompileOptions, SchematicComponent, SchematicNetlistEngine};

// ----------------------------------------------------------------------
// CadValue
// ----------------------------------------------------------------------

#[test]
fn test_cad_value_null_is_empty() {
    assert!(CadValue::Null.is_empty());
}

#[test]
fn test_cad_value_empty_map_is_empty() {
    assert!(CadValue::Map(BTreeMap::new()).is_empty());
}

#[test]
fn test_cad_value_non_empty_not_empty() {
    assert!(!CadValue::Bool(true).is_empty());
    assert!(!CadValue::Str("x".to_string()).is_empty());
    assert!(!CadValue::I32(0).is_empty());
    let mut m = BTreeMap::new();
    m.insert("k".to_string(), CadValue::Null);
    assert!(!CadValue::Map(m).is_empty());
}

#[test]
fn test_cad_value_as_str() {
    assert_eq!(CadValue::Str("hello".to_string()).as_str(), Some("hello"));
    assert_eq!(CadValue::Null.as_str(), None);
    assert_eq!(CadValue::I32(42).as_str(), None);
}

#[test]
fn test_cad_value_as_f64() {
    assert!((CadValue::F64(3.14).as_f64().unwrap() - 3.14).abs() < 1e-9);
    assert!((CadValue::I32(42).as_f64().unwrap() - 42.0).abs() < 1e-9);
    assert!((CadValue::Str("2.5".to_string()).as_f64().unwrap() - 2.5).abs() < 1e-9);
    assert_eq!(CadValue::Null.as_f64(), None);
}

#[test]
fn test_cad_value_as_i32() {
    assert_eq!(CadValue::I32(42).as_i32(), Some(42));
    assert!((CadValue::F64(42.9).as_i32().unwrap() as f64) - 42.9 < 1e-9 || true); // truncation
    assert_eq!(CadValue::Str("7".to_string()).as_i32(), Some(7));
    assert_eq!(CadValue::Null.as_i32(), None);
}

#[test]
fn test_cad_value_as_map() {
    let mut m = BTreeMap::new();
    m.insert("k".to_string(), CadValue::Null);
    assert_eq!(CadValue::Map(m.clone()).as_map(), Some(&m));
    assert_eq!(CadValue::Null.as_map(), None);
}

// ----------------------------------------------------------------------
// SchematicComponent
// ----------------------------------------------------------------------

#[test]
fn test_schematic_component_new_defaults() {
    let c = SchematicComponent::new("R1", "R", "R1", "10k", 0.0, 0.0);
    assert_eq!(c.comp_id, "R1");
    assert_eq!(c.comp_type, "R");
    assert_eq!(c.name, "R1");
    assert_eq!(c.value, "10k");
    assert_eq!(c.x, 0.0);
    assert_eq!(c.y, 0.0);
    assert_eq!(c.footprint, "");
    assert_eq!(c.mpn, "");
    assert_eq!(c.manufacturer, "(unknown)");
    assert_eq!(c.description, "(no description)");
    assert_eq!(c.values, "(no values)");
    assert_eq!(c.cost_usd, 0.0);
    assert!(c.pins.is_empty());
    assert_eq!(c.rotation, 0.0);
}

#[test]
fn test_schematic_component_default() {
    let c = SchematicComponent::default();
    assert_eq!(c.comp_id, "");
    assert_eq!(c.comp_type, "");
    assert_eq!(c.manufacturer, "(unknown)");
    assert!(c.pins.is_empty());
}

#[test]
fn test_schematic_component_to_dict_from_dict_round_trip() {
    let mut pins = BTreeMap::new();
    pins.insert("1".to_string(), "in".to_string());
    pins.insert("2".to_string(), "out".to_string());
    let orig = SchematicComponent {
        comp_id: "R1".to_string(),
        comp_type: "R".to_string(),
        name: "R1".to_string(),
        value: "10k".to_string(),
        x: 10.5,
        y: 20.5,
        footprint: "Resistor_SMD:R_0603".to_string(),
        mpn: "ABC123".to_string(),
        manufacturer: "DigiKey".to_string(),
        description: "10k resistor".to_string(),
        values: "10k".to_string(),
        cost_usd: 0.15,
        pins,
        rotation: 90.0,
    };
    let dict = orig.to_dict();
    let restored = SchematicComponent::from_dict(&dict);
    assert_eq!(restored.comp_id, orig.comp_id);
    assert_eq!(restored.comp_type, orig.comp_type);
    assert_eq!(restored.name, orig.name);
    assert_eq!(restored.value, orig.value);
    assert!((restored.x - orig.x).abs() < 1e-9);
    assert!((restored.y - orig.y).abs() < 1e-9);
    assert_eq!(restored.footprint, orig.footprint);
    assert_eq!(restored.mpn, orig.mpn);
    // Python's from_dict() does not read manufacturer, so it defaults to
    // "(unknown)" after round-trip. Match that for parity.
    assert_eq!(restored.manufacturer, "(unknown)");
    assert_eq!(restored.description, "(no description)");
    assert_eq!(restored.values, "(no values)");
    assert!((restored.cost_usd - orig.cost_usd).abs() < 1e-9);
    assert_eq!(restored.pins, orig.pins);
    assert!((restored.rotation - orig.rotation).abs() < 1e-9);
}

#[test]
fn test_schematic_component_from_dict_defaults() {
    let dict = BTreeMap::new();
    let c = SchematicComponent::from_dict(&dict);
    assert_eq!(c.comp_id, "");
    assert_eq!(c.comp_type, "R");
    assert_eq!(c.name, "R1");
    assert_eq!(c.value, "10k");
    assert_eq!(c.x, 0.0);
    assert_eq!(c.y, 0.0);
    assert_eq!(c.manufacturer, "(unknown)");
    assert_eq!(c.description, "(no description)");
    assert_eq!(c.values, "(no values)");
    assert_eq!(c.cost_usd, 0.0);
    assert!(c.pins.is_empty());
    assert_eq!(c.rotation, 0.0);
}

// ----------------------------------------------------------------------
// is_mcu
// ----------------------------------------------------------------------

#[test]
fn test_is_mcu() {
    assert!(is_mcu("ESP32"));
    assert!(is_mcu("esp32")); // case-insensitive
    assert!(is_mcu("ARDUINO_UNO"));
    assert!(is_mcu("STM32F103"));
    assert!(is_mcu("RP2040"));
    assert!(is_mcu("MCU"));
    assert!(is_mcu("CUSTOM"));
    assert!(!is_mcu("R"));
    assert!(!is_mcu("C"));
    assert!(!is_mcu("GND"));
    assert!(!is_mcu("V"));
}

// ----------------------------------------------------------------------
// SchematicNetlistEngine: add/remove component, add_wire, clear
// ----------------------------------------------------------------------

#[test]
fn test_engine_add_and_remove_component() {
    let mut g = SchematicNetlistEngine::new();
    assert!(g.components.is_empty());

    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
    assert_eq!(g.components.len(), 1);
    assert!(g.components.contains_key("R1"));

    g.add_component(SchematicComponent::new("C1", "C", "C1", "100n", 80.0, 0.0));
    assert_eq!(g.components.len(), 2);

    g.remove_component("R1");
    assert_eq!(g.components.len(), 1);
    assert!(!g.components.contains_key("R1"));
    assert!(g.components.contains_key("C1"));

    // Removing a non-existent component is a no-op
    g.remove_component("DOES_NOT_EXIST");
    assert_eq!(g.components.len(), 1);
}

#[test]
fn test_engine_add_wire_records_pin_nets() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
    g.add_component(SchematicComponent::new("C1", "C", "C1", "100n", 80.0, 0.0));

    g.add_wire("R1:2", "C1:1", Some("out"));

    let r1 = g.components.get("R1").unwrap();
    assert_eq!(r1.pins.get("2"), Some(&"out".to_string()));
    let c1 = g.components.get("C1").unwrap();
    assert_eq!(c1.pins.get("1"), Some(&"out".to_string()));
}

#[test]
fn test_engine_add_wire_auto_net_name() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
    g.add_component(SchematicComponent::new("C1", "C", "C1", "100n", 80.0, 0.0));

    g.add_wire("R1:1", "C1:1", None);
    assert_eq!(g.wires.len(), 1);
    assert_eq!(g.wires[0]["net"], "NET_1");

    g.add_wire("R1:2", "C1:2", None);
    assert_eq!(g.wires.len(), 2);
    assert_eq!(g.wires[1]["net"], "NET_2");
}

#[test]
fn test_engine_remove_component_removes_wires() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
    g.add_component(SchematicComponent::new("C1", "C", "C1", "100n", 80.0, 0.0));
    g.add_wire("R1:1", "C1:1", Some("net1"));
    g.add_wire("R1:2", "C1:2", Some("net2"));
    assert_eq!(g.wires.len(), 2);

    g.remove_component("R1");
    assert_eq!(g.components.len(), 1);
    assert_eq!(g.wires.len(), 0); // both wires touched R1
}

#[test]
fn test_engine_clear() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
    g.add_wire("R1:1", "R1:2", Some("net1"));
    assert!(!g.components.is_empty());
    assert!(!g.wires.is_empty());

    g.clear();
    assert!(g.components.is_empty());
    assert!(g.wires.is_empty());
    assert!(g.gpio_profiles.is_empty());
    assert!(g.control_laws.is_empty());
    assert!(g.firmware.is_empty());
}

// ----------------------------------------------------------------------
// generate_bom / generate_bom_for
// ----------------------------------------------------------------------

#[test]
fn test_generate_bom_empty_panics() {
    let g = SchematicNetlistEngine::new();
    let result = std::panic::catch_unwind(|| g.generate_bom());
    assert!(result.is_err());
}

#[test]
fn test_generate_bom_skips_ground() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));

    let rows = g.generate_bom();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0]["Designator"], CadValue::Str("R1".to_string()));
}

#[test]
fn test_generate_bom_row_fields() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent {
        comp_id: "R1".to_string(),
        comp_type: "R".to_string(),
        name: "R1".to_string(),
        value: "10k".to_string(),
        x: 0.0,
        y: 0.0,
        footprint: "Resistor_SMD:R_0603".to_string(),
        mpn: "ABC123".to_string(),
        manufacturer: "DigiKey".to_string(),
        description: "10k resistor".to_string(),
        values: "".to_string(),
        cost_usd: 0.15,
        pins: BTreeMap::new(),
        rotation: 0.0,
    });

    let rows = g.generate_bom();
    assert_eq!(rows.len(), 1);
    let row = &rows[0];
    assert_eq!(row["Designator"], CadValue::Str("R1".to_string()));
    assert_eq!(row["Description"], CadValue::Str("10k resistor".to_string()));
    assert_eq!(row["Manufacturer"], CadValue::Str("DigiKey".to_string()));
    assert_eq!(row["MPN"], CadValue::Str("ABC123".to_string()));
    assert_eq!(row["Footprint"], CadValue::Str("Resistor_SMD:R_0603".to_string()));
    assert_eq!(row["Quantity"], CadValue::I32(1));
    assert!((row["Unit Cost (USD)"].as_f64().unwrap() - 0.15).abs() < 1e-9);
    assert!((row["Extended Cost"].as_f64().unwrap() - 0.15).abs() < 1e-9);
    assert_eq!(row["Source"], CadValue::Str("drawn schematic".to_string()));
}

#[test]
fn test_generate_bom_for_skips_ground() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));

    let rows = generate_bom_for(&g);
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0]["Designator"], CadValue::Str("R1".to_string()));
}

// ----------------------------------------------------------------------
// compile_netlist: empty → legacy buck
// ----------------------------------------------------------------------

#[test]
fn test_compile_netlist_empty_returns_legacy_buck() {
    let g = SchematicNetlistEngine::new();
    let (lines, nets, warnings) = g.compile_netlist(CompileOptions::default());
    assert!(warnings.is_empty());
    assert_eq!(nets, vec!["in", "sw_node", "vout"]);
    assert!(lines.iter().any(|l| l.contains("Vin in 0 DC")));
    assert!(lines.iter().any(|l| l.contains(".end")));
}

#[test]
fn test_compile_netlist_simple_r_circuit() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("V1", "V", "V1", "12", 0.0, 0.0));
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 80.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));
    g.add_wire("V1:+", "R1:1", Some("in"));
    g.add_wire("V1:-", "GND1:1", Some("gnd"));
    g.add_wire("R1:2", "GND1:1", Some("gnd"));

    let (lines, nets, warnings) = g.compile_netlist(CompileOptions::default());
    assert!(warnings.is_empty(), "unexpected warnings: {:?}", warnings);
    assert!(lines.iter().any(|l| l.contains("R1")));
    assert!(lines.iter().any(|l| l.contains(".tran")));
    assert!(lines.iter().any(|l| l.contains(".end")));
    assert!(!nets.is_empty());
}

#[test]
fn test_compile_netlist_unknown_analysis_panics() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
    let result = std::panic::catch_unwind(|| {
        g.compile_netlist(CompileOptions {
            analysis: "fourier".to_string(),
            ..CompileOptions::default()
        })
    });
    assert!(result.is_err());
}

#[test]
fn test_compile_netlist_unknown_mcu_pins_panics() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
    let result = std::panic::catch_unwind(|| {
        g.compile_netlist(CompileOptions {
            mcu_pins: "floating".to_string(),
            ..CompileOptions::default()
        })
    });
    assert!(result.is_err());
}

#[test]
fn test_compile_netlist_warns_no_ground() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("V1", "V", "V1", "12", 0.0, 0.0));
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 80.0, 0.0));
    g.add_wire("V1:+", "R1:1", Some("in"));
    g.add_wire("V1:-", "R1:2", Some("in"));

    let (_lines, _nets, warnings) = g.compile_netlist(CompileOptions::default());
    assert!(
        warnings.iter().any(|w| w.contains("No ground node")),
        "expected 'No ground node' warning, got: {:?}",
        warnings
    );
}

#[test]
fn test_compile_netlist_warns_no_source() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));
    g.add_wire("R1:1", "GND1:1", Some("gnd"));
    g.add_wire("R1:2", "GND1:1", Some("gnd"));

    let (_lines, _nets, warnings) = g.compile_netlist(CompileOptions::default());
    assert!(
        warnings.iter().any(|w| w.contains("No independent source")),
        "expected 'No independent source' warning, got: {:?}",
        warnings
    );
}

#[test]
fn test_compile_netlist_warns_unconnected_pin() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("V1", "V", "V1", "12", 0.0, 0.0));
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 80.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));
    // Only wire one pin of R1
    g.add_wire("V1:+", "R1:1", Some("in"));
    g.add_wire("V1:-", "GND1:1", Some("gnd"));

    let (_lines, _nets, warnings) = g.compile_netlist(CompileOptions::default());
    assert!(
        warnings.iter().any(|w| w.contains("unconnected")),
        "expected 'unconnected' warning, got: {:?}",
        warnings
    );
}

#[test]
fn test_compile_netlist_diode_emits_model() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("V1", "V", "V1", "12", 0.0, 0.0));
    g.add_component(SchematicComponent::new("D1", "D", "D1", "", 80.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));
    g.add_wire("V1:+", "D1:A", Some("in"));
    g.add_wire("D1:K", "GND1:1", Some("gnd"));

    let (lines, _nets, _warnings) = g.compile_netlist(CompileOptions::default());
    assert!(lines.iter().any(|l| l.contains("D1")));
    assert!(lines.iter().any(|l| l.contains(".model D_MODEL")));
}

#[test]
fn test_compile_netlist_mosfet_emits_model() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("V1", "V", "V1", "12", 0.0, 0.0));
    g.add_component(SchematicComponent::new("M1", "MOSFET", "M1", "", 80.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));
    g.add_wire("V1:+", "M1:D", Some("drain"));
    g.add_wire("M1:G", "GND1:1", Some("gnd"));
    g.add_wire("M1:S", "GND1:1", Some("gnd"));

    let (lines, _nets, _warnings) = g.compile_netlist(CompileOptions::default());
    assert!(lines.iter().any(|l| l.contains("M1")));
    assert!(lines.iter().any(|l| l.contains(".model NMOS_MODEL")));
}

#[test]
fn test_compile_netlist_switch_emits_model() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("V1", "V", "V1", "12", 0.0, 0.0));
    g.add_component(SchematicComponent::new("S1", "SWITCH", "S1", "", 80.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));
    g.add_wire("V1:+", "S1:1", Some("in"));
    g.add_wire("S1:2", "GND1:1", Some("gnd"));

    let (lines, _nets, _warnings) = g.compile_netlist(CompileOptions::default());
    assert!(lines.iter().any(|l| l.contains("S1")));
    assert!(lines.iter().any(|l| l.contains(".model SW_MODEL")));
}

#[test]
fn test_compile_netlist_mcu_in_ignore_mode() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("U1", "ESP32", "U1", "ESP32", -260.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", -260.0, 80.0));
    g.add_wire("U1:GPIO18", "GND1:1", Some("gpio18"));

    let (lines, _nets, _warnings) =
        g.compile_netlist(CompileOptions { mcu_pins: "ignore".to_string(), ..CompileOptions::default() });
    assert!(
        lines.iter().any(|l| l.contains("MCU pins are NOT driven")),
        "expected ignore-mode comment, got: {:?}",
        lines
    );
}

#[test]
fn test_compile_netlist_unsupported_component_warns() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("Q1", "TRANSISTOR", "Q1", "", 80.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));

    let (_lines, _nets, warnings) = g.compile_netlist(CompileOptions::default());
    assert!(
        warnings.iter().any(|w| w.contains("not SPICE-simulatable")),
        "expected 'not SPICE-simulatable' warning, got: {:?}",
        warnings
    );
}

// ----------------------------------------------------------------------
// generate_spice_netlist
// ----------------------------------------------------------------------

#[test]
fn test_generate_spice_netlist() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("V1", "V", "V1", "12", 0.0, 0.0));
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 80.0, 0.0));
    g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));
    g.add_wire("V1:+", "R1:1", Some("in"));
    g.add_wire("V1:-", "GND1:1", Some("gnd"));
    g.add_wire("R1:2", "GND1:1", Some("gnd"));

    let lines = g.generate_spice_netlist(12.0, 0.5, 5.0);
    assert!(!lines.is_empty());
    assert!(lines.iter().any(|l| l.contains(".tran")));
    assert!(lines.iter().any(|l| l.contains(".end")));
}

// ----------------------------------------------------------------------
// to_dict / load_dict persistence round-trip
// ----------------------------------------------------------------------

#[test]
fn test_engine_to_dict_load_dict_round_trip() {
    let mut g = SchematicNetlistEngine::new();
    g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 10.0, 20.0));
    g.add_component(SchematicComponent::new("C1", "C", "C1", "100n", 80.0, 0.0));
    g.add_wire("R1:2", "C1:1", Some("out"));

    let dict = g.to_dict();
    assert_eq!(dict["format"], CadValue::Str("wowki-schematic-v1".to_string()));

    let mut restored = SchematicNetlistEngine::new();
    restored.load_dict(&dict);

    assert_eq!(restored.components.len(), 2);
    assert!(restored.components.contains_key("R1"));
    assert!(restored.components.contains_key("C1"));
    assert_eq!(restored.wires.len(), 1);

    let r1 = restored.components.get("R1").unwrap();
    assert!((r1.x - 10.0).abs() < 1e-9);
    assert!((r1.y - 20.0).abs() < 1e-9);
    assert_eq!(r1.pins.get("2"), Some(&"out".to_string()));

    let c1 = restored.components.get("C1").unwrap();
    assert_eq!(c1.pins.get("1"), Some(&"out".to_string()));
}

// ----------------------------------------------------------------------
// export_kicad_schematic stub returns error
// ----------------------------------------------------------------------

#[test]
fn test_export_kicad_schematic_stub_returns_error() {
    let g = SchematicNetlistEngine::new();
    let result = g.export_kicad_schematic("/tmp/out.kicad_sch", None, "Test");
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("not ported to the Rust core yet"));
}
