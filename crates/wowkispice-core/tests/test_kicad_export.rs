//! Port of tests/test_kicad_export.py — KiCad exporter verification.
//!
//! Three layers:
//! 1. Structure: balanced s-expressions, one symbol per component, real wires.
//! 2. Pin mapping: our canonical pin names map to the pin numbers KiCad's own
//!    libraries use (Device:D is K=1/A=2, Device:Q_NMOS is numbered D/G/S).
//! 3. Round-trip: skipped (kicad-cli not available on this machine).

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::fs;
use std::path::Path;
use std::time::SystemTime;

use wowkispice_core::cad_engine::{SchematicComponent, SchematicNetlistEngine};
use wowkispice_core::kicad_export::{
    all_symbols, export_kicad_netlist, export_kicad_schematic, get_symbol,
    kicad_refs, pin_number_for,
};

fn build_rc() -> SchematicNetlistEngine {
    // 12 V -> 1k -> 'out' with 100nF to ground.
    let mut g = SchematicNetlistEngine::new();
    for c in [
        SchematicComponent::new("V1", "V", "V1", "12", 0.0, 0.0),
        SchematicComponent::new("R1", "R", "R1", "1k", 80.0, 0.0),
        SchematicComponent::new("C1", "C", "C1", "100n", 160.0, 0.0),
        SchematicComponent::new("GND1", "GND", "GND", "", 160.0, 80.0),
    ] {
        g.add_component(c);
    }
    g.add_wire("V1:+", "R1:1", Some("in"));
    g.add_wire("V1:-", "GND1:1", Some("gnd"));
    g.add_wire("R1:2", "C1:1", Some("out"));
    g.add_wire("C1:2", "GND1:1", Some("gnd"));
    g
}

/// Check that parentheses are balanced, respecting double-quoted strings.
fn balanced(text: &str) -> bool {
    let mut depth = 0i32;
    let mut in_str = false;
    let mut esc = false;
    for ch in text.chars() {
        if in_str {
            if esc {
                esc = false;
            } else if ch == '\\' {
                esc = true;
            } else if ch == '"' {
                in_str = false;
            }
            continue;
        }
        if ch == '"' {
            in_str = true;
        } else if ch == '(' {
            depth += 1;
        } else if ch == ')' {
            depth -= 1;
            if depth < 0 {
                return false;
            }
        }
    }
    depth == 0
}

fn write_tmp(name: &str, text: &str) -> String {
    // Unique suffix so parallel tests don't overwrite each other's files.
    let mut hasher = DefaultHasher::new();
    name.hash(&mut hasher);
    SystemTime::now().hash(&mut hasher);
    std::process::id().hash(&mut hasher);
    let suffix = hasher.finish();

    let tmp = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("target")
        .join("kicad_export_test_tmp");
    let _ = fs::create_dir_all(&tmp);
    let path = tmp.join(format!("{suffix}_{name}"));
    fs::write(&path, text).unwrap();
    path.to_string_lossy().to_string()
}

mod test_schematic_structure {
    use super::*;

    fn model_and_text() -> (SchematicNetlistEngine, String) {
        let model = build_rc();
        let path = write_tmp("out.kicad_sch", "");
        export_kicad_schematic(&model, &path, None, "WOSP Schematic").unwrap();
        let text = fs::read_to_string(&path).unwrap();
        (model, text)
    }

    #[test]
    fn test_file_is_balanced_s_expression() {
        let (_model, text) = model_and_text();
        let bal = balanced(&text);
        let _ = fs::write("C:/temp/sch_debug.txt", format!("balanced={} len={}\n{}", bal, text.len(), text));
        assert!(bal, "unbalanced parentheses");
    }

    #[test]
    fn test_one_symbol_per_component() {
        let (model, text) = model_and_text();
        let count = text.matches("(symbol (lib_id").count();
        assert_eq!(count, model.components.len());
    }

    #[test]
    fn test_wires_come_from_the_graph() {
        let (_model, text) = model_and_text();
        let model = build_rc();
        assert_eq!(text.matches("(wire ").count(), model.wires.len());
    }

    #[test]
    fn test_junction_where_three_pins_meet() {
        // 'gnd' ties V1-, C1 and the ground symbol: three points, so a junction
        let (_model, text) = model_and_text();
        assert!(text.contains("(junction (at"), "expected a junction where 3 pins meet");
    }

    #[test]
    fn test_power_symbol_uses_pwr_reference() {
        let (model, text) = model_and_text();
        let refs = kicad_refs(&model);
        assert!(refs["GND1"].starts_with("#PWR"));
        assert_eq!(refs["R1"], "R1");
        assert!(
            text.contains(&format!(r#"(property "Reference" "{}"#, refs["GND1"])),
            "ground reference not found in export"
        );
    }

    #[test]
    fn test_named_nets_survive_as_labels() {
        let (_model, text) = model_and_text();
        assert!(text.contains(r#"(label "in""#));
        assert!(text.contains(r#"(label "out""#));
    }

    #[test]
    fn test_export_is_deterministic() {
        let model = build_rc();
        let path1 = write_tmp("out.kicad_sch", "");
        export_kicad_schematic(&model, &path1, None, "WOSP Schematic").unwrap();
        let text1 = fs::read_to_string(&path1).unwrap();

        let path2 = write_tmp("again.kicad_sch", "");
        export_kicad_schematic(&model, &path2, None, "WOSP Schematic").unwrap();
        let text2 = fs::read_to_string(&path2).unwrap();

        assert_eq!(
            text1.replace("out.kicad_sch", ""),
            text2.replace("again.kicad_sch", "")
        );
    }

    #[test]
    #[should_panic(expected = "Nothing to export")]
    fn test_empty_schematic_refuses_instead_of_faking() {
        let empty = SchematicNetlistEngine::new();
        export_kicad_schematic(&empty, &write_tmp("empty.kicad_sch", ""), None, "WOSP Schematic").unwrap();
    }
}

mod test_pin_mapping {
    use super::*;

    #[test]
    fn test_diode_matches_kicad_convention() {
        // Device:D: pin 1 is the cathode, pin 2 the anode
        assert_eq!(pin_number_for("D", "K"), Some("1".to_string()));
        assert_eq!(pin_number_for("D", "A"), Some("2".to_string()));
    }

    #[test]
    fn test_sources_map_to_kicad_parts() {
        assert_eq!(
            get_symbol("V").map(|s| s.part),
            Some("VDC".to_string())
        );
        assert_eq!(
            get_symbol("I").map(|s| s.part),
            Some("IDC".to_string())
        );
        assert_eq!(pin_number_for("V", "+"), Some("1".to_string()));
        assert_eq!(pin_number_for("V", "-"), Some("2".to_string()));
    }

    #[test]
    fn test_mosfet_pins_match_library_numbering() {
        // KiCad Device:Q_NMOS numbers pins D/G/S, not 1/2/3
        assert_eq!(
            get_symbol("MOSFET").map(|s| s.part),
            Some("Q_NMOS".to_string())
        );
        assert_eq!(pin_number_for("MOSFET", "G"), Some("G".to_string()));
    }

    #[test]
    fn test_every_symbol_has_pin_offsets() {
        for (ctype, spec) in all_symbols() {
            for pin in &spec.pins {
                assert!(
                    pin_number_for(&ctype, &pin.ours).is_some(),
                    "{ctype} pin {} unmapped",
                    pin.ours
                );
            }
        }
    }
}

mod test_netlist_export {
    use super::*;

    #[test]
    fn test_netlist_contains_components_and_nets() {
        let tmp = write_tmp("out.net", "");
        export_kicad_netlist(&build_rc(), &tmp).unwrap();
        let text = fs::read_to_string(&tmp).unwrap();
        assert!(balanced(&text));
        assert!(text.contains(r#"(comp (ref "R1")"#));
        assert!(text.contains(r#"(net (code "1")"#));
        assert!(text.contains(r#"(libpart (lib "Device") (part "R")"#));
    }
}
