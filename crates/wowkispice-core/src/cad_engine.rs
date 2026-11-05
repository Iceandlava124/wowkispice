/*
 * cad_engine.rs - port of bridge/cad_engine.py.
 *
 * Interactive CAD Schematic, Netlist Generator & EDA Exporter:
 *   1. Component & pin graph database with dynamic terminal routing
 *   2. Visual to SPICE netlist compiler
 *   3. KiCad / LTspice exporters (the KiCad exporter is not ported yet
 *      and is stubbed below - bridge.kicad_export has no Rust equivalent)
 *   4. Bill of Materials generator
 *
 * Pure computation over strings and numbers: no solver, no Qt, no
 * filesystem, no external crates (std only), mirroring a Python original
 * that depends only on `re` and `typing`.  Class/function names, default
 * values, warning text and `f"{x:g}"` float formatting match
 * bridge/cad_engine.py one-to-one (the latter via pycompat::py_g); the
 * core's hand-rolled parsers replace the `re` module.
 */

use crate::control_law;
use crate::gpio_model;
use crate::pycompat::py_g;
use std::collections::BTreeMap;
use std::collections::BTreeSet;

/// A dependency-free stand-in for Python's `Any`, so `to_dict`/`load_dict`
/// round-trip mixed-type documents without serde.
#[derive(Debug, Clone, PartialEq)]
pub enum CadValue {
    Null,
    Bool(bool),
    I32(i32),
    F64(f64),
    Str(String),
    List(Vec<CadValue>),
    Map(BTreeMap<String, CadValue>),
}

impl CadValue {
    pub fn as_str(&self) -> Option<&str> {
        match self {
            CadValue::Str(s) => Some(s),
            _ => None,
        }
    }

    pub fn as_f64(&self) -> Option<f64> {
        match self {
            CadValue::I32(v) => Some(*v as f64),
            CadValue::F64(v) => Some(*v),
            CadValue::Str(s) => s.parse().ok(),
            _ => None,
        }
    }

    pub fn as_i32(&self) -> Option<i32> {
        match self {
            CadValue::I32(v) => Some(*v),
            CadValue::F64(v) => Some(*v as i32),
            CadValue::Str(s) => s.parse().ok(),
            _ => None,
        }
    }

    pub fn as_i64(&self) -> Option<i64> {
        match self {
            CadValue::I32(v) => Some(*v as i64),
            CadValue::F64(v) => Some(*v as i64),
            CadValue::Str(s) => s.parse().ok(),
            _ => None,
        }
    }

    pub fn as_map(&self) -> Option<&BTreeMap<String, CadValue>> {
        match self {
            CadValue::Map(m) => Some(m),
            _ => None,
        }
    }

    /// Python's `not spec` for the profile values this module stores: None
    /// / null or an empty mapping is "empty", everything else is not.
    pub fn is_empty(&self) -> bool {
        match self {
            CadValue::Null => true,
            CadValue::Map(m) => m.is_empty(),
            _ => false,
        }
    }
}

/// One placed schematic symbol: identity, kind, value, position and the
/// pin -> net map mutated in place by `add_wire`.  Mirrors
/// `bridge/cad_engine.py::SchematicComponent` field-for-field.
#[derive(Debug, Clone)]
pub struct SchematicComponent {
    pub comp_id: String,
    pub comp_type: String,
    pub name: String,
    pub value: String,
    pub x: f64,
    pub y: f64,
    pub footprint: String,
    pub mpn: String,
    pub manufacturer: String,
    pub description: String,
    pub values: String,
    pub cost_usd: f64,
    /// Dict mapping pin_name -> net_name.
    pub pins: BTreeMap<String, String>,
    /// Editor rotation in degrees (0/90/180/270); geometry only, not used
    /// by the netlister.
    pub rotation: f64,
}

impl Default for SchematicComponent {
    fn default() -> Self {
        Self {
            comp_id: String::new(),
            comp_type: String::new(),
            name: String::new(),
            value: String::new(),
            x: 0.0,
            y: 0.0,
            footprint: String::new(),
            mpn: String::new(),
            manufacturer: "(unknown)".to_string(),
            description: "(no description)".to_string(),
            values: "(no values)".to_string(),
            cost_usd: 0.0,
            pins: BTreeMap::new(),
            rotation: 0.0,
        }
    }
}

impl SchematicComponent {
    pub fn new(
        comp_id: &str,
        comp_type: &str,
        name: &str,
        value: &str,
        x: f64,
        y: f64,
    ) -> Self {
        Self {
            comp_id: comp_id.to_string(),
            comp_type: comp_type.to_string(),
            name: name.to_string(),
            value: value.to_string(),
            x,
            y,
            ..Default::default()
        }
    }

    pub fn to_dict(&self) -> BTreeMap<String, CadValue> {
        let mut out = BTreeMap::new();
        out.insert("comp_id".to_string(), CadValue::Str(self.comp_id.clone()));
        out.insert(
            "comp_type".to_string(),
            CadValue::Str(self.comp_type.clone()),
        );
        out.insert("name".to_string(), CadValue::Str(self.name.clone()));
        out.insert("value".to_string(), CadValue::Str(self.value.clone()));
        out.insert("x".to_string(), CadValue::F64(self.x));
        out.insert("y".to_string(), CadValue::F64(self.y));
        out.insert(
            "footprint".to_string(),
            CadValue::Str(self.footprint.clone()),
        );
        out.insert("mpn".to_string(), CadValue::Str(self.mpn.clone()));
        out.insert(
            "manufacturer".to_string(),
            CadValue::Str(self.manufacturer.clone()),
        );
        out.insert("cost_usd".to_string(), CadValue::F64(self.cost_usd));
        out.insert(
            "pins".to_string(),
            CadValue::Map(
                self.pins
                    .iter()
                    .map(|(k, v)| (k.clone(), CadValue::Str(v.clone())))
                    .collect(),
            ),
        );
        out.insert("rotation".to_string(), CadValue::F64(self.rotation));
        out
    }

    pub fn from_dict(data: &BTreeMap<String, CadValue>) -> Self {
        let get_s =
            |data: &BTreeMap<String, CadValue>, key: &str, default: &str| -> String {
                data.get(key)
                    .and_then(CadValue::as_str)
                    .unwrap_or(default)
                    .to_string()
            };
        let get_f =
            |data: &BTreeMap<String, CadValue>, key: &str, default: f64| -> f64 {
                data.get(key)
                    .and_then(CadValue::as_f64)
                    .unwrap_or(default)
            };
        let pins = data
            .get("pins")
            .and_then(CadValue::as_map)
            .map(|m| {
                m.iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect()
            })
            .unwrap_or_default();
        Self {
            comp_id: get_s(data, "comp_id", ""),
            comp_type: get_s(data, "comp_type", "R"),
            name: get_s(data, "name", "R1"),
            value: get_s(data, "value", "10k"),
            x: get_f(data, "x", 0.0),
            y: get_f(data, "y", 0.0),
            footprint: get_s(data, "footprint", ""),
            mpn: get_s(data, "mpn", ""),
            // Python's from_dict() does not read manufacturer, so it always
            // defaults to "(unknown)" after a round-trip. Match that for parity.
            manufacturer: "(unknown)".to_string(),
            description: get_s(data, "description", "(no description)"),
            values: get_s(data, "values", "(no values)"),
            cost_usd: get_f(data, "cost_usd", 0.0),
            pins,
            rotation: get_f(data, "rotation", 0.0),
        }
    }
}

/// Component types that behave as an MCU for netlisting purposes. Board
/// specific symbols (Arduino Uno, STM32F103, ...) differ only in their pin
/// names; the compiler treats them all the same way.
pub const MCU_TYPES: &[&str] = &[
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

/// True when this component type is an MCU for netlisting purposes.
pub fn is_mcu(comp_type: &str) -> bool {
    let ct = comp_type.to_uppercase();
    MCU_TYPES.iter().any(|&t| t == ct.as_str())
}

/// Build a BOM from an actual schematic graph (one row per placed
/// component).  Distinct from `SchematicNetlistEngine::generate_bom`,
/// which returns the legacy hard-coded reference buck converter BOM.
pub fn generate_bom_for(
    model: &SchematicNetlistEngine,
) -> Vec<BTreeMap<String, CadValue>> {
    let mut rows: Vec<BTreeMap<String, CadValue>> = Vec::new();
    let mut comps: Vec<&SchematicComponent> = model.components.values().collect();
    comps.sort_by(|a, b| a.name.cmp(&b.name));
    for comp in comps {
        let ctype = comp.comp_type.to_uppercase();
        if ctype == "GND" {
            continue;
        }
        let mut row = BTreeMap::new();
        row.insert("Designator".to_string(), CadValue::Str(comp.name.clone()));
        row.insert("Type".to_string(), CadValue::Str(comp.comp_type.clone()));
        row.insert(
            "Value".to_string(),
            CadValue::Str(if comp.value.is_empty() {
                "(default)".to_string()
            } else {
                comp.value.clone()
            }),
        );
        row.insert(
            "Footprint".to_string(),
            CadValue::Str(if comp.footprint.is_empty() {
                "-".to_string()
            } else {
                comp.footprint.clone()
            }),
        );
        row.insert(
            "MPN".to_string(),
            CadValue::Str(if comp.mpn.is_empty() {
                "-".to_string()
            } else {
                comp.mpn.clone()
            }),
        );
        row.insert("Qty".to_string(), CadValue::I32(1));
        row.insert(
            "Unit Cost (USD)".to_string(),
            CadValue::F64(comp.cost_usd),
        );
        row.insert(
            "Extended Cost".to_string(),
            CadValue::F64(comp.cost_usd),
        );
        rows.push(row);
    }
    rows
}

/// One endpoint in the union-find: (component id, pin name).
type Node = (String, String);

/// Compile options, mirroring `compile_netlist`'s keyword arguments with
/// their Python defaults.
#[derive(Debug, Clone)]
pub struct CompileOptions {
    pub vin: f64,
    pub tstep_us: f64,
    pub duration_ms: f64,
    pub analysis: String,
    pub mcu_pins: String,
    pub ac_start_hz: f64,
    pub ac_stop_hz: f64,
    pub ac_points_per_decade: i32,
    pub noise_output_net: Option<String>,
}

impl Default for CompileOptions {
    fn default() -> Self {
        Self {
            vin: 12.0,
            tstep_us: 0.5,
            duration_ms: 5.0,
            analysis: "tran".to_string(),
            mcu_pins: "drive".to_string(),
            ac_start_hz: 1.0,
            ac_stop_hz: 1e6,
            ac_points_per_decade: 20,
            noise_output_net: None,
        }
    }
}

/// `SchematicNetlistEngine` - visual to SPICE netlist compiler.
///
/// `compile_netlist` resolves nets with a union-find over wires (chained
/// wires A-B, B-C collapse into one electrical node) and ground is node
/// "0".  An empty schematic falls back to the legacy reference buck
/// converter.
pub struct SchematicNetlistEngine {
    pub components: BTreeMap<String, SchematicComponent>,
    pub wires: Vec<BTreeMap<String, String>>,
    /// Per-MCU declared pin behaviour: {comp_id: {pin_name: profile}}
    pub gpio_profiles: BTreeMap<String, BTreeMap<String, CadValue>>,
    /// Per-MCU closed-loop control law: {comp_id: {spec...}}
    pub control_laws: BTreeMap<String, BTreeMap<String, CadValue>>,
    /// Firmware metadata per MCU: {comp_id: {...FirmwareImage.to_dict()...}}
    pub firmware: BTreeMap<String, BTreeMap<String, CadValue>>,
}

impl Default for SchematicNetlistEngine {
    fn default() -> Self {
        Self {
            components: BTreeMap::new(),
            wires: Vec::new(),
            gpio_profiles: BTreeMap::new(),
            control_laws: BTreeMap::new(),
            firmware: BTreeMap::new(),
        }
    }
}

impl SchematicNetlistEngine {
    pub fn new() -> Self {
        Default::default()
    }

    pub fn clear(&mut self) {
        self.components.clear();
        self.wires.clear();
        self.gpio_profiles.clear();
        self.control_laws.clear();
        self.firmware.clear();
    }

    pub fn add_component(&mut self, comp: SchematicComponent) {
        let id = comp.comp_id.clone();
        self.components.insert(id, comp);
    }

    pub fn remove_component(&mut self, comp_id: &str) {
        self.components.remove(comp_id);
        // Remove attached wires.
        let prefix = format!("{}:", comp_id);
        self.wires.retain(|w| !wire_end(w, "from").starts_with(&prefix)
            && !wire_end(w, "to").starts_with(&prefix));
    }

    pub fn add_wire(&mut self, pin_from: &str, pin_to: &str, net_name: Option<&str>) {
        // Add a wire between two component pins (e.g. 'R1:1' -> 'C1:1').
        let net: String = net_name
            .map(|s| s.to_string())
            .unwrap_or_else(|| format!("NET_{}", self.wires.len() + 1));
        self.wires.push({
            let mut w = BTreeMap::new();
            w.insert("from".to_string(), pin_from.to_string());
            w.insert("to".to_string(), pin_to.to_string());
            w.insert("net".to_string(), net.clone());
            w
        });

        // Assign pins to net.
        if let Some((cid, pin)) = pin_from.split_once(':') {
            if let Some(comp) = self.components.get_mut(cid) {
                comp.pins.insert(pin.to_string(), net.clone());
            }
        }
        if let Some((cid, pin)) = pin_to.split_once(':') {
            if let Some(comp) = self.components.get_mut(cid) {
                comp.pins.insert(pin.to_string(), net);
            }
        }
    }

    // ------------------------------------------------------------------
    // Graph -> SPICE netlist compilation
    // ------------------------------------------------------------------

    pub fn compile_netlist(
        &self,
        opts: CompileOptions,
    ) -> (Vec<String>, Vec<String>, Vec<String>) {
        // Compile the schematic component graph into an executable SPICE
        // netlist.  Returns (netlist_lines, probeable_net_names,
        // warnings).
        let analysis = opts.analysis.to_lowercase();
        match analysis.as_str() {
            "tran" | "ac" | "noise" | "disto" => {}
            _ => panic!(
                "unknown analysis '{}' (use 'tran', 'ac', 'noise' or 'disto')",
                analysis
            ),
        }
        let mcu_pins = opts.mcu_pins.to_lowercase();
        match mcu_pins.as_str() {
            "drive" | "ignore" => {}
            _ => panic!(
                "unknown mcu_pins mode '{}' (use 'drive' or 'ignore')",
                mcu_pins
            ),
        }
        if self.components.is_empty() {
            let legacy = self._legacy_reference_netlist(
                opts.vin,
                opts.tstep_us,
                opts.duration_ms,
            );
            return (
                legacy,
                vec!["in".to_string(), "sw_node".to_string(), "vout".to_string()],
                Vec::new(),
            );
        }

        let (net_of, ground_nets) = self._resolve_nets();
        let mut warnings: Vec<String> = Vec::new();
        let mut lines: Vec<String> = Vec::new();
        lines.push("* WOWKISPICE CAD Netlist - compiled from schematic graph".to_string());
        lines.push(format!(
            "* {} component(s), {} wire(s)",
            self.components.len(),
            self.wires.len()
        ));

        let mut models_needed: Vec<String> = Vec::new();
        let mut has_source = false;
        let mut _emitted = 0usize;
        let mut ac_marked = false;
        let mut noise_src: Option<String> = None;

        let mut comps: Vec<&SchematicComponent> = self.components.values().collect();
        comps.sort_by(|a, b| a.name.cmp(&b.name));

        for comp in comps {
            let ctype = comp.comp_type.to_uppercase();
            if ctype == "GND" || ctype == "GROUND" {
                continue; // ground is expressed by node name "0"
            }
            if is_mcu(&ctype) {
                let (mcu_lines, mcu_sources) =
                    self._emit_mcu(comp, &net_of, &mut warnings, &mcu_pins);
                lines.extend(mcu_lines);
                has_source = has_source || mcu_sources > 0;
                continue;
            }

            let letter = match element_letter(&ctype) {
                Some(letter) => letter,
                None => {
                    lines.push(format!(
                        "* unsupported component {} ({}) - skipped",
                        comp.name, comp.comp_type
                    ));
                    warnings.push(format!(
                        "Component {} ({}) is not SPICE-simulatable; skipped.",
                        comp.name, comp.comp_type
                    ));
                    continue;
                }
            };
            let letter_ch = letter.chars().next().unwrap();

            let canon = canonical_pins(&ctype).unwrap_or(&["1", "2"]);
            let pin_nets = self._ordered_pin_nets(comp, canon, &net_of);

            let designator = if comp
                .name
                .chars()
                .next()
                .map_or(false, |c| c.to_ascii_uppercase() == letter_ch)
            {
                comp.name.clone()
            } else if comp
                .comp_id
                .chars()
                .next()
                .map_or(false, |c| c.to_ascii_uppercase() == letter_ch)
            {
                comp.comp_id.clone()
            } else {
                format!("{}{}", letter, comp.comp_id) // e.g. Q1 -> MQ1 (SPICE needs the type letter)
            };
            let value = if comp.value.trim().is_empty() {
                default_value(&ctype).unwrap_or("0").to_string()
            } else {
                comp.value.trim().to_string()
            };

            if ctype == "V" || ctype == "I" {
                has_source = true;
                if noise_src.is_none() {
                    noise_src = Some(designator.clone()); // .noise input reference
                }
                let card = if is_dc_number(&value) {
                    format!("DC {}", value)
                } else {
                    value.clone() // PULSE(...), PWL(...), SIN(...) pass through verbatim
                };
                let card = if (analysis == "ac" || analysis == "noise" || analysis == "disto")
                    && !ac_marked
                {
                    // .ac drives the first independent source with its AC
                    // magnitude; without this the sweep has nothing to
                    // excite.  .disto additionally needs distof1 so the
                    // source carries a fundamental for the Volterra
                    // expansion to work on.
                    let mut card = format!("{} AC 1", card);
                    if analysis == "disto" {
                        card = format!("{} distof1 1 0", card);
                    }
                    ac_marked = true;
                    card
                } else {
                    card
                };
                lines.push(format!(
                    "{} {} {}",
                    designator,
                    pin_nets.join(" "),
                    card
                ));
            } else if ctype == "D" {
                models_needed.push("D_MODEL".to_string());
                lines.push(format!(
                    "{} {} D_MODEL",
                    designator,
                    pin_nets.join(" ")
                ));
            } else if ctype == "MOSFET" {
                models_needed.push("NMOS_MODEL".to_string());
                if pin_nets.len() == 4 {
                    lines.push(format!(
                        "{} {} NMOS_MODEL",
                        designator,
                        pin_nets.join(" ")
                    ));
                } else {
                    let d = &pin_nets[0];
                    let g = &pin_nets[1];
                    let s = &pin_nets[2];
                    lines.push(format!(
                        "{} {} {} {} {} NMOS_MODEL", // bulk tied to source
                        designator, d, g, s, s
                    ));
                }
            } else if ctype == "SWITCH" {
                models_needed.push("SW_MODEL".to_string());
                let ctrl = SchematicNetlistEngine::_net(
                    &net_of,
                    comp.comp_id.as_str(),
                    "CTRL",
                    &format!("{}_ctrl", comp.name),
                );
                let n1 = &pin_nets[0];
                let n2 = &pin_nets[1];
                lines.push(format!(
                    "{} {} {} {} 0 SW_MODEL",
                    designator, n1, n2, ctrl
                ));
            } else {
                lines.push(format!(
                    "{} {} {}",
                    designator,
                    pin_nets.join(" "),
                    value
                ));
            }
            _emitted += 1;
        }

        if models_needed.iter().any(|m| m == "D_MODEL") {
            lines.push(".model D_MODEL D(IS=1e-14 N=1 RS=0.1 BV=100 IBV=1e-3)".to_string());
        }
        if models_needed.iter().any(|m| m == "NMOS_MODEL") {
            lines.push(".model NMOS_MODEL NMOS(VTO=2.0 KP=20)".to_string());
        }
        if models_needed.iter().any(|m| m == "SW_MODEL") {
            lines.push(
                ".model SW_MODEL SW(Ron=0.02 Roff=1e6 Vt=1.65 Vh=0.05)".to_string(),
            );
        }

        // -- electrical sanity checks -> actionable warnings for the editor console
        if ground_nets.is_empty() {
            warnings.push(
                "No ground node: place a GND symbol (or name a net '0'/'GND') before running."
                    .to_string(),
            );
        }
        if !has_source {
            warnings.push(
                "No independent source (V/I): simulation output will be all zeros.".to_string(),
            );
        } else if analysis == "ac" || analysis == "noise" || analysis == "disto" {
            if !ac_marked {
                warnings.push(
                    "AC/noise/distortion analysis needs an independent V/I source; none was stamped with an AC magnitude, so the sweep has no excitation."
                        .to_string(),
                );
            }
        }
        for (_cid, comp) in self.components.iter() {
            let ctype = comp.comp_type.to_uppercase();
            let canonical = match canonical_pins(&ctype) {
                Some(canonical) => canonical,
                None => continue,
            };
            if ctype == "GND" || is_mcu(&ctype) {
                continue;
            }
            let mut filled: BTreeSet<String> = comp.pins.keys().cloned().collect();
            for pin in comp.pins.keys() {
                filled.insert(Self::_canon_pin(pin));
            }
            for pin in canonical {
                if !filled.contains(*pin) {
                    warnings.push(format!("Pin {}.{} is unconnected.", comp.name, pin));
                }
            }
        }

        if analysis == "ac" {
            lines.push(format!(
                ".ac dec {} {} {}",
                opts.ac_points_per_decade,
                py_g(opts.ac_start_hz),
                py_g(opts.ac_stop_hz)
            ));
        } else if analysis == "noise" {
            let noise_output_net = match &opts.noise_output_net {
                Some(net) => net,
                None => panic!("noise analysis needs an output net (noise_output_net=...)"),
            };
            let noise_src = match &noise_src {
                Some(src) => src,
                None => panic!(
                    "noise analysis needs an independent source as its input reference"
                ),
            };
            lines.push(format!(
                ".noise V({}) {} dec {} {} {}",
                noise_output_net,
                noise_src,
                opts.ac_points_per_decade,
                py_g(opts.ac_start_hz),
                py_g(opts.ac_stop_hz)
            ));
        } else if analysis == "disto" {
            // Both cards: .ac supplies the fundamental reference (HD = 2f1/3f1
            // over f1) and .disto sweeps the Volterra harmonic analysis over
            // the same grid.
            let _noise_src = match &noise_src {
                Some(src) => src,
                None => panic!(
                    "distortion analysis needs an independent source as its input reference"
                ),
            };
            let sweep = format!(
                "{} {} {}",
                opts.ac_points_per_decade,
                py_g(opts.ac_start_hz),
                py_g(opts.ac_stop_hz)
            );
            lines.push(format!(".ac dec {}", sweep));
            lines.push(format!(".disto dec {}", sweep));
        } else {
            lines.push(format!(
                ".tran {:.2}u {:.1}m uic",
                opts.tstep_us, opts.duration_ms
            ));
        }
        lines.push(".end".to_string());

        let mut probe_nets: Vec<String> = net_of
            .values()
            .filter(|n| !n.is_empty() && *n != "0" && !n.starts_with("__"))
            .cloned()
            .collect();
        probe_nets.sort();
        probe_nets.dedup();
        (lines, probe_nets, warnings)
    }

    fn _emit_mcu(
        &self,
        comp: &SchematicComponent,
        net_of: &BTreeMap<Node, String>,
        warnings: &mut Vec<String>,
        mcu_pins: &str,
    ) -> (Vec<String>, i32) {
        // Emit an MCU as a comment plus one real voltage source per wired output pin.
        // Pins drive their net with the declared GPIO profile (bridge/gpio_model).
        // A pin carrying a closed-loop control law instead emits an `external`
        // source, which bridge/cosim_runner.py drives from inside the solver.
        // Unprofiled output pins idle LOW and say so, rather than floating the net.
        // Pins named GND/0 stay as ground and emit nothing.
        let label: &str = if comp.value.trim().is_empty() {
            &comp.name
        } else {
            comp.value.trim()
        };
        let empty = BTreeMap::new();
        let profile = self
            .gpio_profiles
            .get(&comp.comp_id)
            .unwrap_or(&empty);
        let firmware = self.firmware.get(&comp.comp_id);
        let law = self.control_laws.get(&comp.comp_id);

        let mut out: Vec<String> = Vec::new();
        out.push(format!(
            "* MCU {} ({}) - co-simulation digital source",
            comp.comp_id, label
        ));
        if let Some(fw) = firmware {
            let name = fw.get("name").and_then(CadValue::as_str).unwrap_or("?");
            let size = fw.get("size_bytes").and_then(CadValue::as_i32).unwrap_or(0);
            let sha = fw.get("sha256").and_then(CadValue::as_str).unwrap_or("");
            let sha: String = sha.chars().take(12).collect();
            out.push(format!(
                "*   firmware: {}, {} bytes, sha256 {}",
                name, size, sha
            ));
        }
        if law.is_none() {
            out.push(
                "*   NOTE: pin behaviour comes from a declared profile, not from executing the binary"
                    .to_string(),
            );
        }
        if let Some(law_map) = law {
            let law_pin = law_map.get("pin").and_then(CadValue::as_str);
            let input = law_input_from_map(law_map);
            let desc = control_law::describe_law(&input);
            out.push(format!(
                "*   CONTROL LAW on {}: {}",
                law_pin.as_deref().unwrap_or("None"),
                desc
            ));
        }

        let mut sources = 0i32;
        let law_pin = law
            .and_then(|m| m.get("pin").and_then(CadValue::as_str))
            .map(|s| s.to_string());

        if mcu_pins == "ignore" {
            out.push(format!(
                "*   MCU pins are NOT driven (transient-only mode): {} pin(s) left undriven, run is pure analog",
                comp.pins.len()
            ));
            for pin in comp.pins.keys() {
                let node = net_of
                    .get(&(comp.comp_id.clone(), pin.clone()))
                    .unwrap_or(&format!("{}_{}", comp.comp_id, Self::_safe(pin)))
                    .clone();
                out.push(format!(
                    "*     {} -> {}",
                    pin,
                    if node == "0" {
                        "ground (node 0)".to_string()
                    } else {
                        "net ".to_string() + &node
                    }
                ));
            }
            return (out, 0);
        }
        for pin in comp.pins.keys() {
            let node = net_of
                .get(&(comp.comp_id.clone(), pin.clone()))
                .unwrap_or(&format!("{}_{}", comp.comp_id, Self::_safe(pin)))
                .clone();
            if node == "0" || pin == "GND" || pin == "0" || pin == "gnd" {
                out.push(format!("*   {} -> ground (node 0)", pin));
                continue;
            }
            let designator = format!("V{}_{}", Self::_safe(&comp.comp_id), Self::_safe(pin));
            if law_pin.as_deref() == Some(pin.as_str()) {
                // Driven by the solver, not by a fixed waveform.
                out.push(format!("{} {} 0 external", designator, node));
                sources += 1;
                continue;
            }
            let spec = profile.get(pin);
            let card = match build_gpio_card(spec) {
                Ok(card) => card,
                Err(exc) => {
                    warnings.push(format!(
                        "{}.{} profile invalid ({}); pin left undriven.",
                        comp.comp_id, pin, exc
                    ));
                    continue;
                }
            };
            out.push(format!("{} {} 0 {}", designator, node, card));
            sources += 1;
            if spec.is_none() || spec.map_or(false, CadValue::is_empty) {
                // None *or* an empty profile both mean undeclared
                warnings.push(format!(
                    "{}.{} has no GPIO profile; assumed idle LOW (set one for real behaviour).",
                    comp.comp_id, pin
                ));
            }
            let (mode, vhigh, level, freq_hz, duty, phase_s) = spec_fields(spec);
            // Validated by build_gpio_card above, so describe cannot fail.
            let desc = gpio_model::describe_pin(
                pin,
                &mode,
                vhigh,
                level,
                freq_hz,
                duty,
                phase_s,
            )
            .unwrap();
            out.push(format!("*   {}", desc));
        }
        if comp.pins.is_empty() {
            out.push("*   no pins wired".to_string());
        }
        if let Some(lp) = &law_pin {
            if !comp.pins.contains_key(lp.as_str()) {
                warnings.push(format!(
                    "{} control law targets pin '{}', which is not wired; the law cannot run.",
                    comp.comp_id, lp
                ));
            }
        }
        (out, sources)
    }

    fn _legacy_reference_netlist(
        &self,
        vin: f64,
        tstep_us: f64,
        duration_ms: f64,
    ) -> Vec<String> {
        // Empty-schematic fallback: the reference 12V->3.3V buck (keeps
        // legacy export behavior).
        vec![
            "* WOWKISPICE Reference Buck Converter (empty schematic fallback)".to_string(),
            format!("Vin in 0 DC {:.2}", vin),
            "Vgate gate 0 dc 0 external".to_string(),
            "S1 in sw_node gate 0 SW_MODEL".to_string(),
            "D1 0 sw_node DIODE_MODEL".to_string(),
            "L1 sw_node vout 47u IC=0".to_string(),
            "C1 vout 0 100u IC=0".to_string(),
            "Rload vout 0 5.0".to_string(),
            ".model SW_MODEL SW(Ron=0.02 Roff=1e6 Vt=1.65 Vh=0.05)".to_string(),
            ".model DIODE_MODEL D(IS=1e-9 RS=0.01 N=1.0 BV=50 IBV=1e-4)".to_string(),
            format!(".tran {:.2}u {:.1}m uic", tstep_us, duration_ms),
            ".end".to_string(),
        ]
    }

    /// Canonical pin order per passive/source type (aliases normalized to
    /// these).
    fn _canon_pin(pin: &str) -> String {
        let p = pin.trim();
        if p == "0" || p == "GND" || p == "gnd" {
            return p.to_string();
        }
        pin_alias(p).unwrap_or(p).to_string()
    }

    fn _net(net_of: &BTreeMap<Node, String>, cid: &str, pin: &str, fallback: &str) -> String {
        net_of
            .get(&(cid.to_string(), pin.to_string()))
            .cloned()
            .unwrap_or_else(|| fallback.to_string())
    }

    fn _ordered_pin_nets(
        &self,
        comp: &SchematicComponent,
        canonical: &[&str],
        net_of: &BTreeMap<Node, String>,
    ) -> Vec<String> {
        // Resolve this component's pin nets in canonical order.
        // Actual pin names are matched alias-aware ('GATE'->'G', 'A'->'1', ...);
        // canonical slots left unfilled take leftover wired pins in order, which
        // keeps nonstandard pin naming schemes (A/B passives, diode anode) working.
        let actuals: Vec<String> = comp.pins.keys().cloned().collect();
        if actuals.is_empty() {
            return canonical
                .iter()
                .map(|c| format!("{}_{}", comp.comp_id, Self::_safe(c)))
                .collect();
        }

        let mut pairs: Vec<Option<String>> = vec![None; canonical.len()];
        let mut used: BTreeSet<String> = BTreeSet::new();
        for (i, canon) in canonical.iter().enumerate() {
            let m = actuals
                .iter()
                .find(|a| !used.contains(*a) && Self::_canon_pin(a) == *canon)
                .cloned();
            if let Some(ref mm) = m {
                used.insert(mm.clone());
            }
            pairs[i] = m;
        }
        let mut leftovers: Vec<String> = actuals
            .into_iter()
            .filter(|a| !used.contains(a))
            .collect();
        for i in 0..pairs.len() {
            if pairs[i].is_none() {
                if let Some(l) = leftovers.first().cloned() {
                    pairs[i] = Some(l.clone());
                    leftovers.remove(0);
                    used.insert(l);
                }
            }
        }

        let mut ordered: Vec<String> = Vec::new();
        for (i, actual) in pairs.into_iter().enumerate() {
            let canon = canonical[i];
            match actual {
                Some(actual) => ordered.push(
                    net_of
                        .get(&(comp.comp_id.clone(), actual.clone()))
                        .unwrap_or(&format!("{}_{}", comp.comp_id, Self::_safe(&actual)))
                        .clone(),
                ),
                None => ordered.push(format!("{}_{}", comp.comp_id, Self::_safe(canon))),
            }
        }
        ordered
    }

    fn _safe(name: &str) -> String {
        name.chars()
            .map(|c| if c.is_ascii_alphanumeric() || c == '_' { c } else { '_' })
            .collect()
    }

    pub fn _resolve_nets(
        &self,
    ) -> (BTreeMap<Node, String>, Vec<String>) {
        // Union-find over (comp_id, pin) endpoints. Wires merge endpoints;
        // identical explicit net names also merge. Returns
        // (net_of[(comp_id,pin)] -> net name, list of nets that are ground).
        let mut parent: BTreeMap<Node, Node> = BTreeMap::new();

        fn uf_find(parent: &mut BTreeMap<Node, Node>, mut x: Node) -> Node {
            parent.entry(x.clone()).or_insert_with(|| x.clone());
            loop {
                let px = parent[&x].clone();
                if px == x {
                    return x;
                }
                let ppx = parent[&px].clone();
                parent.insert(x.clone(), ppx);
                x = px;
            }
        }

        fn uf_union(parent: &mut BTreeMap<Node, Node>, a: &Node, b: &Node) {
            let ra = uf_find(parent, a.clone());
            let rb = uf_find(parent, b.clone());
            if ra != rb {
                parent.insert(rb, ra);
            }
        }

        let parse = |ref_: &str| -> Option<Node> {
            let (cid, pin) = ref_.split_once(':')?;
            if self.components.contains_key(cid) {
                Some((cid.to_string(), pin.to_string()))
            } else {
                None
            }
        };

        // Seed nodes: wire endpoints + pins already recorded on components
        for w in &self.wires {
            let a = parse(wire_end(w, "from"));
            let b = parse(wire_end(w, "to"));
            if let (Some(a), Some(b)) = (a, b) {
                uf_union(&mut parent, &a, &b);
            }
        }
        for comp in self.components.values() {
            for pin in comp.pins.keys() {
                uf_find(&mut parent, (comp.comp_id.clone(), pin.clone()));
            }
        }

        // Merge pins that share an explicit net name (label-based connectivity)
        let mut by_name: BTreeMap<String, Node> = BTreeMap::new();
        for comp in self.components.values() {
            for (pin, netname) in &comp.pins {
                if netname.is_empty() {
                    continue;
                }
                let node = (comp.comp_id.clone(), pin.clone());
                if let Some(existing) = by_name.get(netname) {
                    uf_union(&mut parent, existing, &node);
                } else {
                    by_name.insert(netname.clone(), node);
                }
            }
        }

        // Assign names per group: gather label candidates from wire net names
        // (comp.pins keeps only the last wire's label per pin, so wires are the
        // authoritative source of labels) and from pins' declared nets.
        let mut wire_labels: BTreeMap<Node, Vec<String>> = BTreeMap::new();
        for w in &self.wires {
            let label = match wire_end(w, "net").trim() {
                "" => continue,
                label => label.to_string(),
            };
            for ref_ in [wire_end(w, "from"), wire_end(w, "to")] {
                if let Some(node) = parse(ref_) {
                    wire_labels.entry(node).or_default().push(label.clone());
                }
            }
        }

        let mut groups: BTreeMap<Node, Vec<Node>> = BTreeMap::new();
        for node in parent.keys().cloned().collect::<Vec<Node>>() {
            let root = uf_find(&mut parent, node.clone());
            groups.entry(root).or_default().push(node);
        }

        let mut net_of: BTreeMap<Node, String> = BTreeMap::new();
        let mut ground_nets: Vec<String> = Vec::new();
        let mut auto_idx = 0usize;
        for (_root, members) in &groups {
            let mut is_ground = false;
            let mut candidates: Vec<String> = Vec::new();
            for (cid, pin) in members {
                let comp = &self.components[cid];
                if comp.comp_type.to_uppercase() == "GND"
                    || comp.comp_type.to_uppercase() == "GROUND"
                {
                    is_ground = true;
                }
                if pin == "0" || pin == "GND" || pin == "gnd" {
                    is_ground = true;
                }
                let declared = comp.pins.get(pin).map(|s| s.as_str()).unwrap_or("");
                if declared == "0" || declared == "GND" || declared == "gnd" {
                    is_ground = true;
                }
                if let Some(labels) = wire_labels.get(&(cid.clone(), pin.clone())) {
                    candidates.extend(labels.iter().cloned());
                }
                if !declared.is_empty() {
                    candidates.push(declared.to_string());
                }
            }
            let name = if is_ground {
                ground_nets.push("0".to_string());
                "0".to_string()
            } else if !candidates.is_empty() {
                // Prefer human labels (in/out) over auto-generated NET_<n>
                let human: Vec<&String> =
                    candidates.iter().filter(|c| !is_auto_net(c)).collect();
                match human.iter().min() {
                    Some(h) => h.to_string(),
                    None => candidates.iter().min().unwrap().to_string(),
                }
            } else {
                auto_idx += 1;
                format!("n{}", auto_idx)
            };
            for node in members {
                net_of.insert(node.clone(), name.clone());
            }
        }
        ground_nets.sort();
        ground_nets.dedup();
        (net_of, ground_nets)
    }

    // ------------------------------------------------------------------
    // Document persistence (for the editor's save/open/undo)
    // ------------------------------------------------------------------

    pub fn to_dict(&self) -> BTreeMap<String, CadValue> {
        // Copy the pin dicts: undo snapshots must not alias live component
        // state, because add_wire() mutates component.pins in place.
        let mut out = BTreeMap::new();
        out.insert(
            "format".to_string(),
            CadValue::Str("wowki-schematic-v1".to_string()),
        );
        out.insert(
            "components".to_string(),
            CadValue::List(
                self.components
                    .values()
                    .map(|c| {
                        let mut m = c.to_dict();
                        m.insert(
                            "pins".to_string(),
                            CadValue::Map(
                                c.pins
                                    .iter()
                                    .map(|(k, v)| (k.clone(), CadValue::Str(v.clone())))
                                    .collect(),
                            ),
                        );
                        CadValue::Map(m)
                    })
                    .collect(),
            ),
        );
        out.insert(
            "wires".to_string(),
            CadValue::List(
                self.wires
                    .iter()
                    .map(|w| {
                        CadValue::Map(
                            w.iter()
                                .map(|(k, v)| (k.clone(), CadValue::Str(v.clone())))
                                .collect(),
                        )
                    })
                    .collect(),
            ),
        );
        out.insert(
            "gpio_profiles".to_string(),
            CadValue::Map(
                self.gpio_profiles
                    .iter()
                    .map(|(k, v)| (k.clone(), CadValue::Map(v.clone())))
                    .collect(),
            ),
        );
        out.insert(
            "control_laws".to_string(),
            CadValue::Map(
                self.control_laws
                    .iter()
                    .map(|(k, v)| (k.clone(), CadValue::Map(v.clone())))
                    .collect(),
            ),
        );
        out.insert(
            "firmware".to_string(),
            CadValue::Map(
                self.firmware
                    .iter()
                    .map(|(k, v)| (k.clone(), CadValue::Map(v.clone())))
                    .collect(),
            ),
        );
        out
    }

    pub fn load_dict(&mut self, data: &BTreeMap<String, CadValue>) {
        self.clear();
        if let Some(CadValue::List(items)) = data.get("components") {
            for item in items {
                if let CadValue::Map(m) = item {
                    let comp = SchematicComponent::from_dict(m);
                    self.components.insert(comp.comp_id.clone(), comp);
                }
            }
        }
        self.wires = wire_list(data.get("wires"));
        self.gpio_profiles = map_of_maps(data.get("gpio_profiles"));
        self.control_laws = map_of_maps(data.get("control_laws"));
        self.firmware = map_of_maps(data.get("firmware"));
    }

    pub fn generate_spice_netlist(
        &self,
        vin: f64,
        tstep_us: f64,
        duration_ms: f64,
    ) -> Vec<String> {
        // Compile the visual circuit graph into an executable SPICE netlist.
        let (lines, _nets, _warnings) = self.compile_netlist(CompileOptions {
            vin,
            tstep_us,
            duration_ms,
            ..Default::default()
        });
        lines
    }

    pub fn generate_bom(&self) -> Vec<BTreeMap<String, CadValue>> {
        // Return a drawing-derived BOM from placed components.
        //
        // Raises ValueError if the schematic has no components placed.
        if self.components.is_empty() {
            panic!(
                "empty schematic: no components placed. Do not guess a BOM from a reference design — place parts first (use the demo query or draw a schematic)."
            );
        }
        let mut rows: Vec<BTreeMap<String, CadValue>> = Vec::new();
        let mut comps: Vec<&SchematicComponent> = self.components.values().collect();
        comps.sort_by(|a, b| a.name.cmp(&b.name));
        for comp in comps {
            let ctype = comp.comp_type.to_uppercase();
            if ctype == "GND" {
                continue;
            }
            let mut row = BTreeMap::new();
            row.insert("Designator".to_string(), CadValue::Str(comp.name.clone()));
            row.insert(
                "Description".to_string(),
                CadValue::Str(if comp.description.is_empty() {
                    "(no description)".to_string()
                } else {
                    comp.description.clone()
                }),
            );
            row.insert(
                "Manufacturer".to_string(),
                CadValue::Str(if comp.manufacturer.is_empty() {
                    "(unknown)".to_string()
                } else {
                    comp.manufacturer.clone()
                }),
            );
            row.insert(
                "MPN".to_string(),
                CadValue::Str(if comp.mpn.is_empty() {
                    "(unknown)".to_string()
                } else {
                    comp.mpn.clone()
                }),
            );
            row.insert(
                "Footprint".to_string(),
                CadValue::Str(if comp.footprint.is_empty() {
                    "-".to_string()
                } else {
                    comp.footprint.clone()
                }),
            );
            row.insert("Quantity".to_string(), CadValue::I32(1));
            row.insert(
                "Unit Cost (USD)".to_string(),
                CadValue::F64(comp.cost_usd),
            );
            row.insert(
                "Extended Cost".to_string(),
                CadValue::F64(comp.cost_usd),
            );
            row.insert(
                "Source".to_string(),
                CadValue::Str("drawn schematic".to_string()),
            );
            rows.push(row);
        }
        rows
    }

    pub fn export_kicad_schematic(
        &self,
        _output_path: &str,
        _origins: Option<Vec<String>>,
        _title: &str,
    ) -> Result<(), String> {
        // Export this schematic to a KiCad 9/10 schematic file.
        //
        // Thin wrapper around bridge.kicad_export, which is verified against a real
        // kicad-cli install.  Not ported to the Rust core yet.
        Err(
            "kicad_schematic export is not ported to the Rust core yet (bridge.kicad_export has no Rust equivalent)"
                .to_string(),
        )
    }
}

// ----------------------------------------------------------------------
// Canonical pin tables (mirrors of the Python class attributes)
// ----------------------------------------------------------------------

const _CANONICAL_PINS: &[(&str, &[&str])] = &[
    ("R", &["1", "2"]),
    ("C", &["1", "2"]),
    ("L", &["1", "2"]),
    ("V", &["+", "-"]),
    ("I", &["+", "-"]),
    ("D", &["A", "K"]),
    ("MOSFET", &["D", "G", "S"]),
    ("SWITCH", &["1", "2"]),
    ("GND", &["1"]),
];

const _PIN_ALIASES: &[(&str, &str)] = &[
    ("GATE", "G"),
    ("DRAIN", "D"),
    ("DRN", "D"),
    ("SOURCE", "S"),
    ("SRC", "S"),
    ("ANODE", "A"),
    ("CATHODE", "K"),
    ("KATHODE", "K"),
    ("PLUS", "+"),
    ("MINUS", "-"),
    ("P", "+"),
    ("N", "-"),
    ("IN", "1"),
    ("OUT", "2"),
    ("A", "1"),
    ("B", "2"),
];

const _ELEMENT_LETTERS: &[(&str, &str)] = &[
    ("R", "R"),
    ("C", "C"),
    ("L", "L"),
    ("V", "V"),
    ("I", "I"),
    ("D", "D"),
    ("MOSFET", "M"),
    ("SWITCH", "S"),
];

const _DEFAULT_VALUES: &[(&str, &str)] = &[
    ("R", "1k"),
    ("C", "1n"),
    ("L", "1u"),
    ("V", "0"),
    ("I", "0"),
    ("D", "D_MODEL"),
    ("MOSFET", "NMOS_MODEL"),
    ("SWITCH", "SW_MODEL"),
];

fn element_letter(ctype: &str) -> Option<&'static str> {
    _ELEMENT_LETTERS
        .iter()
        .find(|(k, _)| *k == ctype)
        .map(|(_, v)| *v)
}

fn canonical_pins(ctype: &str) -> Option<&'static [&'static str]> {
    _CANONICAL_PINS
        .iter()
        .find(|(k, _)| *k == ctype)
        .map(|(_, v)| *v)
}

fn default_value(ctype: &str) -> Option<&'static str> {
    _DEFAULT_VALUES
        .iter()
        .find(|(k, _)| *k == ctype)
        .map(|(_, v)| *v)
}

/// `re.fullmatch(r"[+-]?\d+(\.\d+)?([eE][+-]?\d+)?", value)` - a DC voltage
/// or number, hand-rolled because the core crate has no regex crate.
fn is_dc_number(s: &str) -> bool {
    let mut it = s.chars().peekable();
    if matches!(it.peek(), Some('+') | Some('-')) {
        it.next();
    }
    let mut digits = 0;
    while it.peek().map_or(false, |c| c.is_ascii_digit()) {
        digits += 1;
        it.next();
    }
    if digits == 0 {
        return false;
    }
    if it.peek() == Some(&'.') {
        it.next();
        let mut frac = 0;
        while it.peek().map_or(false, |c| c.is_ascii_digit()) {
            frac += 1;
            it.next();
        }
        if frac == 0 {
            return false;
        }
    }
    if matches!(it.peek(), Some('e') | Some('E')) {
        it.next();
        if matches!(it.peek(), Some('+') | Some('-')) {
            it.next();
        }
        let mut exp_digits = 0;
        while it.peek().map_or(false, |c| c.is_ascii_digit()) {
            exp_digits += 1;
            it.next();
        }
        if exp_digits == 0 {
            return false;
        }
    }
    it.next().is_none()
}

/// `re.fullmatch(r"NET_\d+", c)` - an auto-generated net label.
fn is_auto_net(name: &str) -> bool {
    let rest = name.strip_prefix("NET_").unwrap_or("");
    !rest.is_empty() && rest.bytes().all(|b| b.is_ascii_digit())
}

fn wire_end<'a>(w: &'a BTreeMap<String, String>, key: &'a str) -> &'a str {
    w.get(key).map(|s| s.as_str()).unwrap_or("")
}

fn wire_list(v: Option<&CadValue>) -> Vec<BTreeMap<String, String>> {
    match v {
        Some(CadValue::List(items)) => {
            let mut out = Vec::new();
            for item in items {
                if let CadValue::Map(m) = item {
                    let mut w = BTreeMap::new();
                    w.insert(
                        "from".to_string(),
                        m.get("from").and_then(CadValue::as_str).unwrap_or("").to_string(),
                    );
                    w.insert(
                        "to".to_string(),
                        m.get("to").and_then(CadValue::as_str).unwrap_or("").to_string(),
                    );
                    w.insert(
                        "net".to_string(),
                        m.get("net").and_then(CadValue::as_str).unwrap_or("").to_string(),
                    );
                    out.push(w);
                }
            }
            out
        }
        _ => Vec::new(),
    }
}

fn map_of_maps(v: Option<&CadValue>) -> BTreeMap<String, BTreeMap<String, CadValue>> {
    match v {
        Some(CadValue::Map(m)) => {
            let mut out = BTreeMap::new();
            for (k, inner) in m {
                if let CadValue::Map(inner) = inner {
                    out.insert(k.clone(), inner.clone());
                }
            }
            out
        }
        _ => BTreeMap::new(),
    }
}

// ----------------------------------------------------------------------
// GPIO profile <-> bridge/gpio_model.py adaptation
// ----------------------------------------------------------------------

/// Convert a stored pin profile (CadValue dict) into the individual fields
/// `gpio_model::spice_card` takes, mirroring Python's
/// `gpio_model.spice_card(spec, edge_time=1e-7)`.
fn build_gpio_card(spec: Option<&CadValue>) -> Result<String, String> {
    let m = spec.and_then(CadValue::as_map).ok_or_else(|| {
        "profile is not an object".to_string()
    })?;
    let mode = m
        .get("mode")
        .and_then(CadValue::as_str)
        .ok_or_else(|| "missing 'mode'".to_string())?;
    let vhigh = m.get("vhigh").and_then(CadValue::as_f64);
    let level = m.get("level").and_then(CadValue::as_i32);
    let freq_hz = m.get("freq_hz").and_then(CadValue::as_f64);
    let duty = m.get("duty").and_then(CadValue::as_f64);
    let phase_s = m.get("phase_s").and_then(CadValue::as_f64);
    // Python default edge_time = 1e-7 (100 ns).
    gpio_model::spice_card(mode, vhigh, level, freq_hz, duty, phase_s, 1e-7)
}

fn spec_fields(
    spec: Option<&CadValue>,
) -> (String, Option<f64>, Option<i32>, Option<f64>, Option<f64>, Option<f64>) {
    let empty = BTreeMap::new();
    let m = spec.and_then(CadValue::as_map).unwrap_or(&empty);
    (
        m.get("mode")
            .and_then(CadValue::as_str)
            .unwrap_or("static")
            .to_string(),
        m.get("vhigh").and_then(CadValue::as_f64),
        m.get("level").and_then(CadValue::as_i32),
        m.get("freq_hz").and_then(CadValue::as_f64),
        m.get("duty").and_then(CadValue::as_f64),
        m.get("phase_s").and_then(CadValue::as_f64),
    )
}

/// Convert a stored control-law dict into a `control_law::LawInput` so it
/// can be rendered with `control_law::describe_law` (which never fails).
fn law_input_from_map(m: &BTreeMap<String, CadValue>) -> control_law::LawInput {
    let mut li = control_law::LawInput::default();
    if let Some(v) = m.get("kind").and_then(CadValue::as_str) {
        li.kind = Some(v.to_string());
    }
    if let Some(v) = m.get("pin").and_then(CadValue::as_str) {
        li.pin = Some(v.to_string());
    }
    if let Some(v) = m.get("sense_net").and_then(CadValue::as_str) {
        li.sense_net = Some(v.to_string());
    }
    li.target_v = m.get("target_v").and_then(CadValue::as_f64);
    li.hysteresis_v = m.get("hysteresis_v").and_then(CadValue::as_f64);
    li.vhigh = m.get("vhigh").and_then(CadValue::as_f64);
    li.vref = m.get("vref").and_then(CadValue::as_f64);
    li.adc_bits = m.get("adc_bits").and_then(CadValue::as_i32);
    li.divider = m.get("divider").and_then(CadValue::as_f64);
    li.low_counts = m.get("low_counts").and_then(CadValue::as_i64);
    li.high_counts = m.get("high_counts").and_then(CadValue::as_i64);
    li.carrier_hz = m.get("carrier_hz").and_then(CadValue::as_f64);
    li.duty_gain = m.get("duty_gain").and_then(CadValue::as_f64);
    li.source = m.get("source").and_then(CadValue::as_str).map(|s| s.to_string());
    li
}

fn pin_alias(pin: &str) -> Option<&'static str> {
    let upper = pin.to_uppercase();
    _PIN_ALIASES
        .iter()
        .find(|(k, _)| *k == upper.as_str())
        .map(|(_, v)| *v)
}
