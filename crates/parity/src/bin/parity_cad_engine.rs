/*
 * parity_cad_engine.rs - Rust half of the cad_engine-parity battery.
 *
 * Computes a fixed battery of schematic-graph facts from
 * crates/wowkispice-core/src/cad_engine.rs and prints KEY<TAB>VALUE lines
 * for crates/parity/python/parity_cad_engine.py to diff against
 * bridge/cad_engine.py.
 *
 * Battery design: one fixed set of inputs, computed independently on both
 * sides. Keys are index-based plus named keys. Strings are compared as text;
 * counts as integers. Booleans print True/False (matching Python str(bool)).
 * Floats mimic Python str(): whole numbers keep a trailing .0 (e.g. 0.0,
 * 90.0), non-whole numbers print naturally (e.g. 10.5).
 */

use std::collections::BTreeMap;
use std::io::{BufWriter, Write};

use wowkispice_core::cad_engine::{
    generate_bom_for, is_mcu, CompileOptions, SchematicComponent,
    SchematicNetlistEngine,
};

/// Python str(bool) -> "True" / "False".
fn py_bool(b: bool) -> String {
    if b { "True".to_string() } else { "False".to_string() }
}

/// Python str(float): whole numbers keep ".0" (0.0, 90.0), non-whole print
/// naturally (10.5). Mirrors CPython's float __str__.
fn py_float(v: f64) -> String {
    if v.is_finite() && v == v.trunc() {
        format!("{:.1}", v)
    } else {
        format!("{}", v)
    }
}

fn main() {
    let stdout = std::io::stdout();
    let lock = stdout.lock();
    let mut writer = BufWriter::new(lock);

    let mut out: Vec<(String, String)> = Vec::new();

    // ---- im[i]: is_mcu
    for (i, ct) in [
        "ESP32", "esp32", "ARDUINO_UNO", "STM32F103", "RP2040", "MCU",
        "CUSTOM", "R", "C", "GND", "V", "D",
    ]
    .iter()
    .enumerate()
    {
        out.push((format!("im[{i}]"), py_bool(is_mcu(ct))));
    }

    // ---- sc[i]: SchematicComponent defaults / round-trip
    {
        let c = SchematicComponent::new("R1", "R", "R1", "10k", 0.0, 0.0);
        out.push((
            "sc[0]".to_string(),
            format!(
                "comp_id={}|comp_type={}|name={}|value={}|x={}|y={}|footprint={}|mpn={}|manufacturer={}|description={}|values={}|cost_usd={}|rotation={}|pins_len={}",
                c.comp_id, c.comp_type, c.name, c.value, py_float(c.x), py_float(c.y),
                c.footprint, c.mpn, c.manufacturer, c.description, c.values,
                py_float(c.cost_usd), py_float(c.rotation), c.pins.len()
            ),
        ));
    }

    {
        let mut pins = BTreeMap::new();
        pins.insert("1".to_string(), "in".to_string());
        pins.insert("2".to_string(), "out".to_string());
        let c = SchematicComponent {
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
        let dict = c.to_dict();
        let restored = SchematicComponent::from_dict(&dict);
        out.push((
            "sc[1]".to_string(),
            format!(
                "comp_id={}|name={}|value={}|x={}|y={}|footprint={}|mpn={}|manufacturer={}|cost_usd={}|rotation={}|pins_len={}",
                restored.comp_id, restored.name, restored.value,
                py_float(restored.x), py_float(restored.y),
                restored.footprint, restored.mpn, restored.manufacturer,
                py_float(restored.cost_usd), py_float(restored.rotation),
                restored.pins.len()
            ),
        ));
    }

    // ---- eng[i]: SchematicNetlistEngine
    {
        let mut g = SchematicNetlistEngine::new();
        g.add_component(SchematicComponent::new("V1", "V", "V1", "12", 0.0, 0.0));
        g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 80.0, 0.0));
        g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));
        g.add_wire("V1:+", "R1:1", Some("in"));
        g.add_wire("V1:-", "GND1:1", Some("gnd"));
        g.add_wire("R1:2", "GND1:1", Some("gnd"));

        let (lines, nets, warnings) = g.compile_netlist(CompileOptions::default());
        let all = lines.join("\n");
        out.push((
            "eng[0]".to_string(),
            format!(
                "lines={}|nets={}|warnings={}|has_tran={}|has_end={}",
                lines.len(),
                nets.len(),
                warnings.len(),
                py_bool(all.contains(".tran")),
                py_bool(all.contains(".end"))
            ),
        ));
        // net names joined
        out.push((
            "eng[1]".to_string(),
            nets.join("||"),
        ));
        // warnings joined
        out.push((
            "eng[2]".to_string(),
            warnings.join("||"),
        ));
    }

    // ---- eng[3]: empty schematic → legacy buck
    {
        let g = SchematicNetlistEngine::new();
        let (lines, nets, warnings) = g.compile_netlist(CompileOptions::default());
        let all = lines.join("\n");
        out.push((
            "eng[3]".to_string(),
            format!(
                "lines={}|nets={}|warnings={}|has_vin={}|has_end={}",
                lines.len(),
                nets.len(),
                warnings.len(),
                py_bool(all.contains("Vin")),
                py_bool(all.contains(".end"))
            ),
        ));
    }

    // ---- eng[4]: unknown analysis panics
    {
        let mut g = SchematicNetlistEngine::new();
        g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
        let panicked = std::panic::catch_unwind(|| {
            g.compile_netlist(CompileOptions {
                analysis: "fourier".to_string(),
                ..CompileOptions::default()
            })
        })
        .is_err();
        out.push((
            "eng[4]".to_string(),
            py_bool(panicked),
        ));
    }

    // ---- eng[5]: unknown mcu_pins panics
    {
        let mut g = SchematicNetlistEngine::new();
        g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
        let panicked = std::panic::catch_unwind(|| {
            g.compile_netlist(CompileOptions {
                mcu_pins: "floating".to_string(),
                ..CompileOptions::default()
            })
        })
        .is_err();
        out.push((
            "eng[5]".to_string(),
            py_bool(panicked),
        ));
    }

    // ---- bom[i]: generate_bom_for
    {
        let mut g = SchematicNetlistEngine::new();
        g.add_component(SchematicComponent::new("R1", "R", "R1", "1k", 0.0, 0.0));
        g.add_component(SchematicComponent::new("C1", "C", "C1", "100n", 80.0, 0.0));
        g.add_component(SchematicComponent::new("GND1", "GND", "GND", "", 80.0, 80.0));
        let rows = generate_bom_for(&g);
        out.push((
            "bom[0]".to_string(),
            format!("rows={}", rows.len()),
        ));
        if let Some(row) = rows.first() {
            out.push((
                "bom[1]".to_string(),
                format!(
                    "designator={}|type={}|value={}|qty={}|cost={}",
                    row.get("Designator").map(|v| v.as_str().unwrap_or("")).unwrap_or(""),
                    row.get("Type").map(|v| v.as_str().unwrap_or("")).unwrap_or(""),
                    row.get("Value").map(|v| v.as_str().unwrap_or("")).unwrap_or(""),
                    row.get("Qty").map(|v| v.as_i64().unwrap_or(0)).unwrap_or(0),
                    py_float(row.get("Unit Cost (USD)").map(|v| v.as_f64().unwrap_or(0.0)).unwrap_or(0.0)),
                ),
            ));
        }
    }

    for (key, value) in out {
        writeln!(writer, "{}\t{}", key, value).expect("stdout write");
    }
    writer.flush().expect("stdout flush");
}
