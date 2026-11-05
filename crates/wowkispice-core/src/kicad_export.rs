/*
 * kicad_export.rs - port of bridge/kicad_export.py.
 *
 * KiCad exporters driven by the actual schematic graph (wowkispice-core::cad_engine).
 *
 * Two formats:
 *   1. export_kicad_netlist()  -> KiCad netlist (.net, "export version E")
 *   2. export_kicad_schematic() -> KiCad 9 schematic (.kicad_sch)
 *
 * Pure computation over strings and numbers plus std-only file I/O.  No
 * external crates.  UUID5 (SHA-1 based) is hand-rolled so re-exports are
 * stable diffs.  Float formatting, pin tables, body primitives and the
 * s-expression output match bridge/kicad_export.py one-to-one.
 *
 * The KiCadSymbol / KicadPin tables mirror the Python KICAD_SYMBOLS dict
 * field-for-field.  Component types, pin names, default values, warning
 * text and coordinate math match the Python original.
 */

use crate::cad_engine::SchematicNetlistEngine;
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

// ---------------------------------------------------------------------------
// SHA-1 (hand-rolled, std only) - needed for UUID5
// ---------------------------------------------------------------------------

#[derive(Clone, Copy)]
struct Sha1 {
    h0: u32,
    h1: u32,
    h2: u32,
    h3: u32,
    h4: u32,
    buffer: [u8; 64],
    buffer_len: usize,
    total_bytes: u64,
}

const SHA1_K: [u32; 4] = [0x5a827999, 0x6ed9eba1, 0x8f1bbcdc, 0xca62c1d6];

fn sha1_rol(value: u32, bits: u32) -> u32 {
    (value << bits) | (value >> (32 - bits))
}

impl Sha1 {
    fn new() -> Self {
        Sha1 {
            h0: 0x67452301,
            h1: 0xefcdab89,
            h2: 0x98badcfe,
            h3: 0x10325476,
            h4: 0xc3d2e1f0,
            buffer: [0; 64],
            buffer_len: 0,
            total_bytes: 0,
        }
    }

    fn update(&mut self, data: &[u8]) {
        self.total_bytes += data.len() as u64;
        let mut i = 0;
        while i < data.len() {
            let to_fill = 64 - self.buffer_len;
            let n = data.len() - i;
            let take = if n < to_fill { n } else { to_fill };
            self.buffer[self.buffer_len..self.buffer_len + take]
                .copy_from_slice(&data[i..i + take]);
            self.buffer_len += take;
            i += take;
            if self.buffer_len == 64 {
                self._compress_block();
                self.buffer_len = 0;
            }
        }
    }

    fn _compress_block(&mut self) {
        let b = &self.buffer;
        let mut w: [u32; 80] = [0; 80];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([b[i * 4], b[i * 4 + 1], b[i * 4 + 2], b[i * 4 + 3]]);
        }
        for i in 16..80 {
            w[i] = sha1_rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
        }

        let mut a = self.h0;
        let mut b = self.h1;
        let mut c = self.h2;
        let mut d = self.h3;
        let mut e = self.h4;

        for i in 0..80 {
            let (f, k) = if i <= 19 {
                ((b & c) | ((!b) & d), SHA1_K[0])
            } else if i <= 39 {
                (b ^ c ^ d, SHA1_K[1])
            } else if i <= 59 {
                ((b & c) | (b & d) | (c & d), SHA1_K[2])
            } else {
                (b ^ c ^ d, SHA1_K[3])
            };
            let temp = sha1_rol(a, 5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(w[i]);
            e = d;
            d = c;
            c = sha1_rol(b, 30);
            b = a;
            a = temp;
        }

        self.h0 = self.h0.wrapping_add(a);
        self.h1 = self.h1.wrapping_add(b);
        self.h2 = self.h2.wrapping_add(c);
        self.h3 = self.h3.wrapping_add(d);
        self.h4 = self.h4.wrapping_add(e);
    }

    fn finalize(mut self) -> [u8; 20] {
        let bit_len = self.total_bytes.wrapping_mul(8);
        self.update(&[0x80]);
        while self.buffer_len != 56 {
            self.update(&[0]);
        }
        self.update(&bit_len.to_be_bytes());

        let mut out = [0u8; 20];
        out[0..4].copy_from_slice(&self.h0.to_be_bytes());
        out[4..8].copy_from_slice(&self.h1.to_be_bytes());
        out[8..12].copy_from_slice(&self.h2.to_be_bytes());
        out[12..16].copy_from_slice(&self.h3.to_be_bytes());
        out[16..20].copy_from_slice(&self.h4.to_be_bytes());
        out
    }

    fn digest(data: &[u8]) -> [u8; 20] {
        let mut s = Sha1::new();
        s.update(data);
        s.finalize()
    }
}

/// UUID5: name-based UUID using SHA-1 (RFC 4122 section 4.3).
fn uuid5(namespace: &[u8; 16], name: &str) -> String {
    let mut data = Vec::with_capacity(namespace.len() + name.len());
    data.extend_from_slice(namespace);
    data.extend_from_slice(name.as_bytes());
    let hash = Sha1::digest(&data);

    let mut uuid = [0u8; 16];
    uuid[..16].copy_from_slice(&hash[..16]);

    uuid[6] = (uuid[6] & 0x0f) | 0x50;
    uuid[8] = (uuid[8] & 0x3f) | 0x80;

    format!(
        "{:02x}{:02x}{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
        uuid[0], uuid[1], uuid[2], uuid[3],
        uuid[4], uuid[5],
        uuid[6], uuid[7],
        uuid[8], uuid[9],
        uuid[10], uuid[11], uuid[12], uuid[13], uuid[14], uuid[15]
    )
}

// ---------------------------------------------------------------------------
// Symbol table
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct KicadPin {
    pub ours: String,
    pub number: String,
    pub x: f64,
    pub y: f64,
    pub angle: f64,
    pub length: f64,
    pub etype: String,
    pub name: String,
}

#[derive(Clone, Debug)]
pub enum KicadBodyPrim {
    Rect { x: f64, y: f64, w: f64, h: f64 },
    Circle { cx: f64, cy: f64, r: f64 },
    Line { x1: f64, y1: f64, x2: f64, y2: f64 },
    Poly { pts: Vec<(f64, f64)> },
}

#[derive(Clone, Debug)]
pub struct KicadSymbol {
    pub lib: String,
    pub part: String,
    pub desc: String,
    pub footprint: String,
    pub body: Vec<KicadBodyPrim>,
    pub pins: Vec<KicadPin>,
}

/// 1 canvas pixel (grid unit) expressed in KiCad schematic millimetres
const PX_TO_MM: f64 = 0.254;
/// Distance between MCU header pins in mm
const MCU_PIN_PITCH_MM: f64 = 2.54;

/// UUID namespace for WOSP exports (uuid5).
/// 6f9619ff-8b86-d011-b42d-00c04fc964ff as 16 raw bytes.
static UUID_NAMESPACE: [u8; 16] = [
    0x6f, 0x96, 0x19, 0xff, 0x8b, 0x86, 0xd0, 0x11,
    0xb4, 0x2d, 0x00, 0xc0, 0x4f, 0xc9, 0x64, 0xff,
];

/// Project name carried in KiCad schematic instances.
const PROJECT_NAME: &str = "wokispice";

/// Deterministic UUID so re-exporting the same schematic is a stable diff.
fn uid(parts: &[&str]) -> String {
    uuid5(&UUID_NAMESPACE, &parts.join("|"))
}

/// Format a float like Python's `f"{value:.4f}".rstrip("0").rstrip(".") or "0"`.
fn f(value: f64) -> String {
    let s = format!("{:.4}", value);
    let trimmed = s.trim_end_matches('0').trim_end_matches('.');
    if trimmed.is_empty() || trimmed == "-0" {
        "0".to_string()
    } else {
        trimmed.to_string()
    }
}

/// Escape backslashes and double-quotes for KiCad s-expressions.
fn esc(text: &str) -> String {
    text.replace('\\', "\\\\").replace('"', "\\\"")
}

/// Build the base symbol table (non-MCU entries).
fn base_symbols() -> BTreeMap<&'static str, KicadSymbol> {
    use KicadBodyPrim::*;
    let mut m: BTreeMap<&'static str, KicadSymbol> = BTreeMap::new();

    // R
    m.insert(
        "R",
        KicadSymbol {
            lib: "Device".to_string(),
            part: "R".to_string(),
            desc: "Resistor".to_string(),
            footprint: "Resistor_SMD:R_0603_1608Metric".to_string(),
            body: vec![Rect { x: -5.08, y: -1.27, w: 10.16, h: 2.54 }],
            pins: vec![
                KicadPin { ours: "1".to_string(), number: "1".to_string(), x: -7.62, y: 0.0, angle: 0.0, length: 2.54, etype: "passive".to_string(), name: "~".to_string() },
                KicadPin { ours: "2".to_string(), number: "2".to_string(), x: 7.62, y: 0.0, angle: 180.0, length: 2.54, etype: "passive".to_string(), name: "~".to_string() },
            ],
        },
    );

    // C
    m.insert(
        "C",
        KicadSymbol {
            lib: "Device".to_string(),
            part: "C".to_string(),
            desc: "Capacitor".to_string(),
            footprint: "Capacitor_SMD:C_0603_1608Metric".to_string(),
            body: vec![
                Line { x1: -1.524, y1: -2.794, x2: -1.524, y2: 2.794 },
                Line { x1: 1.524, y1: -2.794, x2: 1.524, y2: 2.794 },
            ],
            pins: vec![
                KicadPin { ours: "1".to_string(), number: "1".to_string(), x: -7.62, y: 0.0, angle: 0.0, length: 5.842, etype: "passive".to_string(), name: "~".to_string() },
                KicadPin { ours: "2".to_string(), number: "2".to_string(), x: 7.62, y: 0.0, angle: 180.0, length: 5.842, etype: "passive".to_string(), name: "~".to_string() },
            ],
        },
    );

    // L
    m.insert(
        "L",
        KicadSymbol {
            lib: "Device".to_string(),
            part: "L".to_string(),
            desc: "Inductor".to_string(),
            footprint: "Inductor_SMD:L_0805_2012Metric".to_string(),
            body: vec![Rect { x: -5.08, y: -1.27, w: 10.16, h: 2.54 }],
            pins: vec![
                KicadPin { ours: "1".to_string(), number: "1".to_string(), x: -7.62, y: 0.0, angle: 0.0, length: 2.54, etype: "passive".to_string(), name: "~".to_string() },
                KicadPin { ours: "2".to_string(), number: "2".to_string(), x: 7.62, y: 0.0, angle: 180.0, length: 2.54, etype: "passive".to_string(), name: "~".to_string() },
            ],
        },
    );

    // V (VDC)
    m.insert(
        "V",
        KicadSymbol {
            lib: "Simulation_SPICE".to_string(),
            part: "VDC".to_string(),
            desc: "Voltage source".to_string(),
            footprint: "".to_string(),
            body: vec![
                Circle { cx: 0.0, cy: 0.0, r: 3.81 },
                Line { x1: -1.905, y1: -1.27, x2: -1.905, y2: 1.27 },
                Line { x1: -1.905, y1: 0.0, x2: -0.635, y2: 0.0 },
                Line { x1: 0.635, y1: 0.0, x2: 1.905, y2: 0.0 },
                Line { x1: 1.905, y1: -1.27, x2: 1.905, y2: 1.27 },
            ],
            pins: vec![
                KicadPin { ours: "+".to_string(), number: "1".to_string(), x: -7.62, y: 0.0, angle: 0.0, length: 3.81, etype: "passive".to_string(), name: "+".to_string() },
                KicadPin { ours: "-".to_string(), number: "2".to_string(), x: 7.62, y: 0.0, angle: 180.0, length: 3.81, etype: "passive".to_string(), name: "-".to_string() },
            ],
        },
    );

    // I (IDC)
    m.insert(
        "I",
        KicadSymbol {
            lib: "Simulation_SPICE".to_string(),
            part: "IDC".to_string(),
            desc: "Current source".to_string(),
            footprint: "".to_string(),
            body: vec![
                Circle { cx: 0.0, cy: 0.0, r: 3.81 },
                Line { x1: -2.54, y1: 0.0, x2: 1.27, y2: 0.0 },
                Line { x1: 0.0, y1: -1.27, x2: 1.27, y2: 0.0 },
                Line { x1: 0.0, y1: 1.27, x2: 1.27, y2: 0.0 },
            ],
            pins: vec![
                KicadPin { ours: "+".to_string(), number: "1".to_string(), x: -7.62, y: 0.0, angle: 0.0, length: 3.81, etype: "passive".to_string(), name: "+".to_string() },
                KicadPin { ours: "-".to_string(), number: "2".to_string(), x: 7.62, y: 0.0, angle: 180.0, length: 3.81, etype: "passive".to_string(), name: "-".to_string() },
            ],
        },
    );

    // D
    m.insert(
        "D",
        KicadSymbol {
            lib: "Device".to_string(),
            part: "D".to_string(),
            desc: "Diode".to_string(),
            footprint: "Diode_SMD:D_SOD-123".to_string(),
            body: vec![
                Poly { pts: vec![(0.0, 2.54), (0.0, -2.54), (3.81, 0.0), (0.0, 2.54)] },
                Line { x1: 3.81, y1: -2.54, x2: 3.81, y2: 2.54 },
            ],
            pins: vec![
                KicadPin { ours: "A".to_string(), number: "2".to_string(), x: -7.62, y: 0.0, angle: 0.0, length: 3.81, etype: "passive".to_string(), name: "A".to_string() },
                KicadPin { ours: "K".to_string(), number: "1".to_string(), x: 7.62, y: 0.0, angle: 180.0, length: 3.81, etype: "passive".to_string(), name: "K".to_string() },
            ],
        },
    );

    // MOSFET (Q_NMOS)
    m.insert(
        "MOSFET",
        KicadSymbol {
            lib: "Device".to_string(),
            part: "Q_NMOS".to_string(),
            desc: "N-MOSFET".to_string(),
            footprint: "Package_TO_SOT_THT:TO-220-3".to_string(),
            body: vec![
                Rect { x: -2.54, y: -5.08, w: 5.08, h: 10.16 },
                Line { x1: -2.54, y1: 0.0, x2: -7.62, y2: 0.0 },
                Line { x1: -2.54, y1: -5.08, x2: -7.62, y2: -5.08 },
                Line { x1: -2.54, y1: 5.08, x2: -7.62, y2: 5.08 },
            ],
            pins: vec![
                KicadPin { ours: "D".to_string(), number: "D".to_string(), x: 0.0, y: -7.62, angle: 90.0, length: 2.54, etype: "passive".to_string(), name: "D".to_string() },
                KicadPin { ours: "G".to_string(), number: "G".to_string(), x: -7.62, y: 0.0, angle: 180.0, length: 2.54, etype: "input".to_string(), name: "G".to_string() },
                KicadPin { ours: "S".to_string(), number: "S".to_string(), x: 0.0, y: 7.62, angle: 270.0, length: 2.54, etype: "passive".to_string(), name: "S".to_string() },
            ],
        },
    );

    // GND
    m.insert(
        "GND",
        KicadSymbol {
            lib: "power".to_string(),
            part: "GND".to_string(),
            desc: "Power symbol, ground".to_string(),
            footprint: "".to_string(),
            body: vec![
                Line { x1: 0.0, y1: 0.0, x2: 0.0, y2: 2.54 },
                Line { x1: -2.54, y1: 2.54, x2: 2.54, y2: 2.54 },
                Line { x1: -1.524, y1: 3.81, x2: 1.524, y2: 3.81 },
                Line { x1: -0.762, y1: 5.08, x2: 0.762, y2: 5.08 },
            ],
            pins: vec![KicadPin {
                ours: "1".to_string(),
                number: "1".to_string(),
                x: 0.0,
                y: 0.0,
                angle: 90.0,
                length: 0.0,
                etype: "power_in".to_string(),
                name: "GND".to_string(),
            }],
        },
    );

    // MCU (generic, 5 pins)
    m.insert(
        "MCU",
        KicadSymbol {
            lib: "WOSP".to_string(),
            part: "MCU_GENERIC".to_string(),
            desc: "WOSP co-simulation MCU".to_string(),
            footprint: "".to_string(),
            body: vec![Rect { x: -10.16, y: -7.62, w: 20.32, h: 15.24 }],
            pins: vec![
                KicadPin { ours: "GPIO18".to_string(), number: "1".to_string(), x: -15.24, y: -5.08, angle: 0.0, length: 5.08, etype: "bidirectional".to_string(), name: "GPIO18".to_string() },
                KicadPin { ours: "GPIO17".to_string(), number: "2".to_string(), x: -15.24, y: 0.0, angle: 0.0, length: 5.08, etype: "bidirectional".to_string(), name: "GPIO17".to_string() },
                KicadPin { ours: "ADC0".to_string(), number: "3".to_string(), x: -15.24, y: 5.08, angle: 0.0, length: 5.08, etype: "input".to_string(), name: "ADC0".to_string() },
                KicadPin { ours: "GPIO5".to_string(), number: "4".to_string(), x: 15.24, y: -5.08, angle: 180.0, length: 5.08, etype: "bidirectional".to_string(), name: "GPIO5".to_string() },
                KicadPin { ours: "GND".to_string(), number: "5".to_string(), x: 15.24, y: 5.08, angle: 180.0, length: 5.08, etype: "power_in".to_string(), name: "GND".to_string() },
            ],
        },
    );

    m
}

/// Build a KiCad symbol for a microcontroller board.
fn mcu_symbol(
    part: &str,
    desc: &str,
    left: &[&str],
    right: &[&str],
    footprint: &str,
) -> KicadSymbol {
    let rows = left.len().max(right.len());
    let height = (rows as f64 * MCU_PIN_PITCH_MM).max(10.16);
    let top = height / 2.0;
    let mut pins: Vec<KicadPin> = Vec::new();
    let mut number = 1u32;
    for name in left {
        let y = top - (row_y(name, left, rows) as f64) * MCU_PIN_PITCH_MM;
        pins.push(KicadPin {
            ours: name.to_string(),
            number: number.to_string(),
            x: -10.16,
            y,
            angle: 0.0,
            length: 2.54,
            etype: if is_power(name) { "power_in" } else { "bidirectional" }.to_string(),
            name: name.to_string(),
        });
        number += 1;
    }
    for name in right {
        let y = top - (row_y(name, right, rows) as f64) * MCU_PIN_PITCH_MM;
        pins.push(KicadPin {
            ours: name.to_string(),
            number: number.to_string(),
            x: 10.16,
            y,
            angle: 180.0,
            length: 2.54,
            etype: if is_power(name) { "power_in" } else { "bidirectional" }.to_string(),
            name: name.to_string(),
        });
        number += 1;
    }
    KicadSymbol {
        lib: "WOSP".to_string(),
        part: part.to_string(),
        desc: desc.to_string(),
        footprint: footprint.to_string(),
        body: vec![KicadBodyPrim::Rect {
            x: -10.16,
            y: -height / 2.0,
            w: 20.32,
            h: height,
        }],
        pins,
    }
}

fn row_y(_name: &str, column: &[&str], _rows: usize) -> usize {
    column.iter().position(|n| *n == _name).unwrap_or(0)
}

fn is_power(name: &str) -> bool {
    matches!(
        name.to_uppercase().as_str(),
        "GND" | "5V" | "3V3" | "VIN" | "VCC" | "AREF" | "NRST"
    )
}

/// Per-board MCU symbols, mirroring the editor palette.
fn mcu_symbols() -> BTreeMap<&'static str, KicadSymbol> {
    let mut out: BTreeMap<&'static str, KicadSymbol> = BTreeMap::new();

    fn arduino_pins() -> (Vec<String>, Vec<String>) {
        let left: Vec<String> = (0..10).map(|i| format!("D{i}")).chain((0..6).map(|i| format!("A{i}"))).collect();
        let right: Vec<String> = (10..14)
            .map(|i| format!("D{i}"))
            .chain(["5V", "3V3", "GND", "GND", "VIN", "AREF"].iter().map(|s| s.to_string()))
            .collect();
        (left, right)
    }

    let (uno_left, uno_right) = arduino_pins();
    out.insert(
        "ARDUINO_UNO",
        mcu_symbol(
            "MCU_ARDUINO_UNO",
            "Arduino Uno (ATmega328P)",
            &uno_left.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            &uno_right.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            "Package_DIP:DIP-28_W7.62mm",
        ),
    );
    out.insert(
        "ARDUINO_NANO",
        mcu_symbol(
            "MCU_ARDUINO_NANO",
            "Arduino Nano (ATmega328P)",
            &uno_left.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            &uno_right.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            "Package_QFP:LQFP-48_7x7mm_P0.5mm",
        ),
    );

    let mega_left: Vec<String> = (0..22).map(|i| format!("D{i}")).collect();
    let mega_right: Vec<String> = (22..54)
        .map(|i| format!("D{i}"))
        .chain((0..16).map(|i| format!("A{i}")))
        .chain(["5V", "3V3", "GND", "GND", "VIN", "AREF"].iter().map(|s| s.to_string()))
        .collect();
    out.insert(
        "ARDUINO_MEGA",
        mcu_symbol(
            "MCU_ARDUINO_MEGA",
            "Arduino Mega 2560",
            &mega_left.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            &mega_right.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            "Package_QFP:LQFP-64_10x10mm_P0.5mm",
        ),
    );

    let f103_left: Vec<String> = (0..16).map(|i| format!("PB{i}")).chain((0..8).map(|i| format!("PA{i}"))).collect();
    let f103_right: Vec<String> = (8..16)
        .map(|i| format!("PA{i}"))
        .chain(["3V3", "5V", "GND", "GND", "NRST", "SWDIO", "SWCLK"].iter().map(|s| s.to_string()))
        .collect();
    out.insert(
        "STM32F103",
        mcu_symbol(
            "MCU_STM32F103",
            "STM32F103C8T6",
            &f103_left.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            &f103_right.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            "Package_QFP:LQFP-48_7x7mm_P0.5mm",
        ),
    );

    let esp_left: Vec<String> = (0..16).map(|i| format!("GPIO{i}")).collect();
    let esp_right: Vec<String> = (16..32)
        .map(|i| format!("GPIO{i}"))
        .chain(["3V3", "5V", "GND", "GND", "EN", "VP", "VN"].iter().map(|s| s.to_string()))
        .collect();
    out.insert(
        "ESP32",
        mcu_symbol(
            "MCU_ESP32",
            "ESP32 DevKit (ESP32-WROOM-32)",
            &esp_left.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            &esp_right.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            "Module:ESP32-WROOM-32",
        ),
    );
    out.insert(
        "ESP32S3",
        mcu_symbol(
            "MCU_ESP32S3",
            "ESP32-S3 DevKit",
            &esp_left.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            &esp_right.iter().map(|s| s.as_str()).collect::<Vec<_>>(),
            "Module:ESP32-S3-WROOM-1",
        ),
    );

    out
}

/// Combined symbol table including per-board MCU symbols.
pub fn all_symbols() -> BTreeMap<String, KicadSymbol> {
    let mut out: BTreeMap<String, KicadSymbol> = BTreeMap::new();
    for (k, v) in base_symbols() {
        out.insert(k.to_string(), v);
    }
    for (k, v) in mcu_symbols() {
        out.insert(k.to_string(), v);
    }
    out
}

/// Look up a symbol from the combined table.
pub fn get_symbol(comp_type: &str) -> Option<KicadSymbol> {
    all_symbols().get(comp_type).cloned()
}

/// Look up a symbol's KiCad library:part id.
pub fn lib_id_for(comp_type: &str) -> Option<String> {
    get_symbol(comp_type).map(|spec| format!("{}:{}", spec.lib, spec.part))
}

/// Map our canonical pin name to the KiCad pin number.
pub fn pin_number_for(comp_type: &str, pin_name: &str) -> Option<String> {
    get_symbol(comp_type).and_then(|spec| {
        spec.pins.iter().find(|p| p.ours == pin_name).map(|p| p.number.clone())
    })
}

/// Components KiCad can represent (MCUs included; unknown types skipped).
fn writable_components<'a>(
    model: &'a SchematicNetlistEngine,
) -> BTreeMap<String, &'a crate::cad_engine::SchematicComponent> {
    let mut out = BTreeMap::new();
    for (cid, c) in &model.components {
        let ctype_upper = c.comp_type.to_uppercase();
        if get_symbol(ctype_upper.as_str()).is_some() {
            out.insert(cid.clone(), c);
        }
    }
    out
}

/// Designator to use in KiCad.
pub fn kicad_refs(model: &SchematicNetlistEngine) -> BTreeMap<String, String> {
    let mut refs = BTreeMap::new();
    let mut power = 0u32;
    let mut comps: Vec<&crate::cad_engine::SchematicComponent> =
        model.components.values().collect();
    comps.sort_by(|a, b| a.name.cmp(&b.name));
    for comp in comps {
        if comp.comp_type.to_uppercase() == "GND" {
            power += 1;
            refs.insert(comp.comp_id.clone(), format!("#PWR{power:02}"));
        } else {
            refs.insert(comp.comp_id.clone(), comp.name.clone());
        }
    }
    refs
}

fn require_graph(model: &SchematicNetlistEngine) -> BTreeMap<String, &crate::cad_engine::SchematicComponent> {
    let comps = writable_components(model);
    if comps.is_empty() {
        panic!(
            "Nothing to export: place components on the schematic first. \
             (An empty canvas cannot produce a KiCad file.)"
        );
    }
    comps
}

fn write_file(output_path: &str, text: &str) -> std::io::Result<()> {
    let path = Path::new(output_path);
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir)?;
    }
    fs::write(output_path, text)
}

// ---------------------------------------------------------------------------
// Body text generation
// ---------------------------------------------------------------------------

fn body_text(spec: &KicadSymbol) -> Vec<String> {
    let mut out = Vec::new();
    for prim in &spec.body {
        match prim {
            KicadBodyPrim::Rect { x, y, w, h } => out.push(format!(
                r#"(rectangle (start {} {}) (end {} {}) (stroke (width 0.254) (type default)) (fill (type background)))"#,
                f(*x), f(*y), f(x + w), f(y + h)
            )),
            KicadBodyPrim::Circle { cx, cy, r } => out.push(format!(
                r#"(circle (center {} {}) (radius {}) (stroke (width 0.254) (type default)) (fill (type none)))"#,
                f(*cx), f(*cy), f(*r)
            )),
            KicadBodyPrim::Line { x1, y1, x2, y2 } => out.push(format!(
                r#"(polyline (pts (xy {} {}) (xy {} {})) (stroke (width 0.254) (type default)))"#,
                f(*x1), f(*y1), f(*x2), f(*y2)
            )),
            KicadBodyPrim::Poly { pts } => {
                let pts_str: String = pts
                    .iter()
                    .map(|(x, y)| format!(r#"(xy {} {})"#, f(*x), f(*y)))
                    .collect::<Vec<_>>()
                    .join(" ");
                out.push(format!(
                    r#"(polyline (pts {}) (stroke (width 0.254) (type default)) (fill (type background)))"#,
                    pts_str
                ));
            }
        }
    }
    out
}

fn lib_symbols_text(used_types: &[&str]) -> String {
    let mut blocks: Vec<String> = Vec::new();
    blocks.push("  (lib_symbols".to_string());
    for ctype in used_types {
        let spec = get_symbol(ctype).expect("symbol exists");
        let symbol_id = format!("{}:{}", spec.lib, spec.part);
        let ref_prefix = match *ctype {
            "R" => "R",
            "C" => "C",
            "L" => "L",
            "D" => "D",
            "MOSFET" => "Q",
            "GND" => "#PWR",
            _ => "U",
        };
        blocks.push(format!(
            r#"    (symbol "{}" (pin_numbers (hide yes)) (pin_names (offset 0.254)) (exclude_from_sim no) (in_bom yes) (on_board yes) (duplicate_pin_numbers_are_jumpers no))"#,
            symbol_id
        ));
        blocks.push(format!(
            r#"      (property "Reference" "{}" (at {} {} 0) (effects (font (size 1.27 1.27))))"#,
            ref_prefix,
            f(3.81),
            f(3.81)
        ));
        blocks.push(format!(
            r#"      (property "Value" "{}" (at {} -{} 0) (effects (font (size 1.27 1.27))))"#,
            spec.part,
            f(3.81),
            f(3.81)
        ));
        blocks.push(
            r#"      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))"#
                .to_string(),
        );
        blocks.push(
            r#"      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))"#
                .to_string(),
        );
        blocks.push(format!("      (symbol \"{}_0_1\"", spec.part));
        for line in body_text(&spec) {
            blocks.push(format!("        {line}"));
        }
        blocks.push("      )".to_string());
        blocks.push(format!("      (symbol \"{}_1_1\"", spec.part));
        for pin in &spec.pins {
            blocks.push(format!(
                r#"        (pin {} line (at {} {} {}) (length {}) (name "{}" (effects (font (size 1.27 1.27)))) (number "{}" (effects (font (size 1.27 1.27)))))"#,
                pin.etype,
                f(pin.x),
                f(pin.y),
                f(pin.angle),
                f(pin.length),
                pin.name,
                pin.number
            ));
        }
        blocks.push("      )".to_string());
    }
    blocks.push("  )".to_string());
    blocks.join("\n")
}

// ---------------------------------------------------------------------------
// 1. KiCad netlist (.net)
// ---------------------------------------------------------------------------

pub fn export_kicad_netlist(
    model: &SchematicNetlistEngine,
    output_path: &str,
) -> std::io::Result<String> {
    let comps = require_graph(model);
    let (net_of, _ground) = model._resolve_nets();
    let refs = kicad_refs(model);

    let mut lines: Vec<String> = Vec::new();
    lines.push("(export (version \"E\")".to_string());
    lines.push("  (design".to_string());
    lines.push(r#"    (source "WOSP Schematic Editor")"#.to_string());
    lines.push(format!(r#"    (date "{}")"#, today()));
    lines.push(r#"    (tool "WOSP Schematic Editor"))"#.to_string());
    lines.push("  (components".to_string());

    let mut comps_vec: Vec<&crate::cad_engine::SchematicComponent> =
        comps.values().copied().collect();
    comps_vec.sort_by(|a, b| a.name.cmp(&b.name));
    for comp in comps_vec {
        let spec = get_symbol(comp.comp_type.as_str()).expect("symbol exists for writable component");
        let footprint = if comp.footprint.is_empty() {
            spec.footprint.clone()
        } else {
            comp.footprint.clone()
        };
        let ref_ = &refs[&comp.comp_id];
        lines.push(format!(r#"    (comp (ref "{}")"#, ref_));
        lines.push(format!(r#"      (value "{}")"#, esc(&comp.value)));
        lines.push(format!(r#"      (footprint "{}")"#, esc(&footprint)));
        lines.push(format!(
            r#"      (libsource (lib "{}") (part "{}")"#,
            spec.lib, spec.part
        ));
        lines.push(format!(r#"        (description "{}"))"#, esc(&spec.desc)));
        lines.push(format!(
            r#"      (property "Reference" "{}" (at 0 0 0) (effects (font (size 1.27 1.27)) (justify left)))"#,
            ref_
        ));
        lines.push(format!(
            r#"      (property "Value" "{}" (at 0 0 0) (effects (font (size 1.27 1.27)) (justify left)))"#,
            esc(&comp.value)
        ));
        lines.push(format!(
            r#"      (property "Footprint" "{}" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))"#,
            esc(&footprint)
        ));
        lines.push(
            r#"      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))"#
                .to_string(),
        );
        lines.push(format!("      (tstamps \"/{}\"))", uid(&["ts", &comp.comp_id])));
    }
    lines.push("  )".to_string());

    // libparts for every distinct symbol used
    let mut used: Vec<&str> = comps.values().map(|c| c.comp_type.as_str()).collect();
    used.sort();
    used.dedup();
    lines.push("  (libparts".to_string());
    for ctype in used {
        let spec = get_symbol(ctype).expect("symbol exists");
        let pins: String = spec
            .pins
            .iter()
            .map(|p| {
                format!(
                    r#"(pin "{}" {} line (at {} {} {}) (length {}) (name "{}" (effects (font (size 1.27 1.27)))) (number "{}" (effects (font (size 1.27 1.27)))))"#,
                    p.number,
                    p.etype,
                    f(p.x),
                    f(p.y),
                    f(p.angle),
                    f(p.length),
                    p.name,
                    p.number
                )
            })
            .collect::<Vec<_>>()
            .join(" ");
        lines.push(format!(
            r#"    (libpart (lib "{}") (part "{}")"#,
            spec.lib, spec.part
        ));
        lines.push(format!(r#"      (description "{}")"#, esc(&spec.desc)));
        lines.push("      (fields".to_string());
        lines.push(
            r#"        (field (name "Reference" "U") (at 0 0 0) (effects (font (size 1.27 1.27)) hide))"#
                .to_string(),
        );
        lines.push(
            r#"        (field (name "Value") (at 0 0 0) (effects (font (size 1.27 1.27))))"#
                .to_string(),
        );
        lines.push(
            r#"        (field (name "Footprint") (at 0 0 0) (effects (font (size 1.27 1.27)) hide))"#
                .to_string(),
        );
        lines.push(
            r#"        (field (name "Datasheet") (at 0 0 0) (effects (font (size 1.27 1.27)) hide))"#
                .to_string(),
        );
        lines.push("      )".to_string());
        lines.push(format!("      (pins {}))", pins));
    }
    lines.push("  )".to_string());

    // nets, with real nodes
    lines.push("  (nets".to_string());
    let mut code = 0u32;
    let mut seen: BTreeMap<String, u32> = BTreeMap::new();
    let mut net_items: Vec<((String, String), String)> = net_of
        .iter()
        .map(|((cid, pin), net)| ((cid.clone(), pin.clone()), net.clone()))
        .collect();
    net_items.sort_by(|a, b| (a.1.as_str(), a.0.0.as_str()).cmp(&(b.1.as_str(), b.0.0.as_str())));
    for ((cid, pin), net) in &net_items {
        let comp = match model.components.get(cid) {
            Some(c) => c,
            None => continue,
        };
        if get_symbol(comp.comp_type.as_str()).is_none() {
            continue;
        }
        if pin_number_for(&comp.comp_type, pin).is_none() {
            continue;
        }
        if !seen.contains_key(net) {
            code += 1;
            seen.insert(net.clone(), code);
            lines.push(format!(r#"    (net (code "{}") (name "{}")"#, code, esc(net)));
        }
        let ref_ = &refs[cid];
        lines.push(format!(
            r#"      (node (ref "{}") (pin "{}") (pinfunction "~") (pintype "passive"))"#,
            ref_,
            pin_number_for(&comp.comp_type, pin).unwrap()
        ));
    }
    // Close each net that was opened
    for _code in seen.values() {
        lines.push("    )".to_string());
    }
    lines.push("  )".to_string());
    lines.push("  (groups)".to_string());
    lines.push(")".to_string());

    let text = lines.join("\n") + "\n";
    write_file(output_path, &text)?;
    Ok(output_path.to_string())
}

// ---------------------------------------------------------------------------
// 2. KiCad schematic (.kicad_sch)
// ---------------------------------------------------------------------------

pub fn export_kicad_schematic(
    model: &SchematicNetlistEngine,
    output_path: &str,
    origins: Option<BTreeMap<String, (f64, f64)>>,
    title: &str,
) -> std::io::Result<String> {
    let comps = require_graph(model);
    let mut used_types: Vec<&str> = comps.values().map(|c| c.comp_type.as_str()).collect();
    used_types.sort();
    used_types.dedup();
    let refs = kicad_refs(model);
    let root_uuid = uid(&["root"]);

    let mut lines: Vec<String> = Vec::new();
    lines.push("(kicad_sch".to_string());
    lines.push("  (version 20250114)".to_string());
    lines.push(r#"  (generator "eeschema")"#.to_string());
    lines.push(r#"  (generator_version "9.0")"#.to_string());
    lines.push(format!(r#"  (uuid "{}")"#, root_uuid));
    lines.push("  (paper \"A4\")".to_string());
    lines.push("  (title_block".to_string());
    lines.push(format!(r#"    (title "{}")"#, esc(title)));
    lines.push("    (company \"WOSP\")".to_string());
    lines.push("    (rev \"1\")".to_string());
    lines.push("  )".to_string());

    lines.push(lib_symbols_text(&used_types));

    let mut comps_vec: Vec<&crate::cad_engine::SchematicComponent> =
        comps.values().copied().collect();
    comps_vec.sort_by(|a, b| a.name.cmp(&b.name));
    for comp in comps_vec {
        let spec = get_symbol(comp.comp_type.as_str()).expect("symbol exists");
        let pos = symbol_origin(comp, &origins);
        let angle = (-(comp.rotation as i32) % 360 + 360) % 360;
        lines.push(format!(
            r#"  (symbol (lib_id "{}:{}") (at {} {} {}) (unit 1)"#,
            spec.lib,
            spec.part,
            f(pos.0),
            f(pos.1),
            f(angle as f64)
        ));
        lines.push("    (exclude_from_sim no)".to_string());
        lines.push("    (in_bom yes) (on_board yes)".to_string());
        lines.push("    (dnp no)".to_string());
        lines.push(format!(r#"    (uuid "{}")"#, uid(&["sym", &comp.comp_id])));
        lines.push(format!(
            r#"    (property "Reference" "{}" (at {} {} 0) (effects (font (size 1.27 1.27)) (justify left)))"#,
            refs[&comp.comp_id],
            f(pos.0),
            f(pos.1 - 3.81)
        ));
        lines.push(format!(
            r#"    (property "Value" "{}" (at {} {} 0) (effects (font (size 1.27 1.27)) (justify left)))"#,
            esc(&comp.value),
            f(pos.0),
            f(pos.1 + 3.81)
        ));
        lines.push(format!(
            r#"    (property "Footprint" "{}" (at {} {} 0) (effects (font (size 1.27 1.27)) hide))"#,
            esc(if comp.footprint.is_empty() {
                spec.footprint.as_str()
            } else {
                comp.footprint.as_str()
            }),
            f(pos.0),
            f(pos.1)
        ));
        lines.push(
            r#"    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))"#
                .to_string(),
        );
        for pin in &spec.pins {
            lines.push(format!(
                r#"    (pin "{}" (uuid "{}"))"#,
                pin.number,
                uid(&["pin", &comp.comp_id, &pin.number])
            ));
        }
        lines.push(format!(
            r#"    (instances (project "{}" (path "/{}" (reference "{}" (unit 1)))))"#,
            PROJECT_NAME,
            root_uuid,
            refs[&comp.comp_id]
        ));
        lines.push("  )".to_string());
    }

    // Wires + junctions from real symbol geometry
    let (net_of, _ground) = model._resolve_nets();
    let mut net_points: BTreeMap<String, Vec<(f64, f64)>> = BTreeMap::new();
    for wire in &model.wires {
        let a = split_ref(wire.get("from").map(|s| s.as_str()).unwrap_or(""));
        let b = split_ref(wire.get("to").map(|s| s.as_str()).unwrap_or(""));
        let pa = pin_point(model, &a, &origins);
        let pb = pin_point(model, &b, &origins);
        if pa.is_none() || pb.is_none() {
            continue;
        }
        let pa = pa.unwrap();
        let pb = pb.unwrap();
        lines.push(format!(
            r#"  (wire (pts (xy {} {}) (xy {} {})) (stroke (width 0) (type default)) (uuid "{}"))"#,
            f(pa.0),
            f(pa.1),
            f(pb.0),
            f(pb.1),
            uid(&[
                wire.get("from").map(|s| s.as_str()).unwrap_or(""),
                wire.get("to").map(|s| s.as_str()).unwrap_or(""),
            ])
        ));
        let net_name = net_of.get(&a).cloned().unwrap_or_else(|| "unconnected".to_string());
        net_points.entry(net_name.clone()).or_default().push(pa);
        net_points.entry(net_name.clone()).or_default().push(pb);
    }

    // Component pins count as connections too
    for ((cid, pin), net_name) in &net_of {
        let point = pin_point(model, &(cid.clone(), pin.clone()), &origins);
        if let Some(p) = point {
            net_points.entry(net_name.clone()).or_default().push(p);
        }
    }

    // A junction is required wherever three or more connections meet at one point
    let net_points_clone = net_points.clone();
    for (net_name, pts) in net_points_clone {
        let mut counts: BTreeMap<(String, String), i32> = BTreeMap::new();
        let mut spots: BTreeMap<(String, String), (f64, f64)> = BTreeMap::new();
        for (x, y) in pts {
            let key = (f(x), f(y));
            *counts.entry(key.clone()).or_insert(0) += 1;
            spots.entry(key).or_insert((x, y));
        }
        for (key, count) in counts {
            if count < 3 {
                continue;
            }
            let (x, y) = spots[&key];
            lines.push(format!(
                r#"  (junction (at {} {}) (diameter 0) (color 0 0 0 0) (uuid "{}"))"#,
                f(x),
                f(y),
                uid(&["junction", &net_name, &key.0, &key.1])
            ));
        }
    }

    // Carry human net names across as local labels on a point of each net
    for (net_name, pts) in net_points {
        if net_name == "0" || net_name.starts_with("NET_") || pts.is_empty() {
            continue;
        }
        let (x, y) = pts[0];
        lines.push(format!(
            r#"  (label "{}" (at {} {} 0) (fields_autoplaced yes) (effects (font (size 1.27 1.27)) (justify left bottom)) (uuid "{}"))"#,
            esc(&net_name),
            f(x),
            f(y),
            uid(&["label", &net_name])
        ));
    }

    lines.push(r#"  (sheet_instances (path "/" (page "1")))"#.to_string());
    lines.push("  (embedded_fonts no)".to_string());
    lines.push(")".to_string());

    let text = lines.join("\n") + "\n";
    write_file(output_path, &text)?;
    Ok(output_path.to_string())
}

// ---------------------------------------------------------------------------
fn symbol_origin(
    comp: &crate::cad_engine::SchematicComponent,
    origins: &Option<BTreeMap<String, (f64, f64)>>,
) -> (f64, f64) {
    if let Some(origins) = origins {
        if let Some(pos) = origins.get(&comp.comp_id) {
            return *pos;
        }
    }
    (comp.x * PX_TO_MM, comp.y * PX_TO_MM)
}

fn pin_offset(comp_type: &str, pin_name: &str) -> Option<(f64, f64)> {
    get_symbol(comp_type).and_then(|spec| {
        spec.pins
            .iter()
            .find(|p| p.ours == pin_name)
            .map(|p| (p.x, p.y))
    })
}

fn rotate_xy(x: f64, y: f64, angle_deg: f64) -> (f64, f64) {
    let rad = angle_deg.to_radians();
    (
        x * rad.cos() - y * rad.sin(),
        x * rad.sin() + y * rad.cos(),
    )
}

fn pin_point(
    model: &SchematicNetlistEngine,
    ref_: &(String, String),
    origins: &Option<BTreeMap<String, (f64, f64)>>,
) -> Option<(f64, f64)> {
    let (cid, pin) = ref_;
    let comp = model.components.get(cid)?;
    if get_symbol(comp.comp_type.as_str()).is_none() {
        return None;
    }
    let (ox, oy) = symbol_origin(comp, origins);
    let offset = pin_offset(&comp.comp_type, pin)?;
    let (dx, dy) = rotate_xy(offset.0, offset.1, -(comp.rotation as f64));
    Some((ox + dx, oy + dy))
}

fn split_ref(ref_: &str) -> (String, String) {
    if let Some((cid, pin)) = ref_.split_once(':') {
        (cid.to_string(), pin.to_string())
    } else {
        ("".to_string(), "".to_string())
    }
}

fn today() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(dur) => {
            let secs = dur.as_secs();
            let days = secs / 86400;
            let mut year = 1970;
            let mut remaining = days;
            loop {
                let days_in_year = if is_leap_year(year) { 366 } else { 365 };
                if remaining < days_in_year {
                    break;
                }
                remaining -= days_in_year;
                year += 1;
            }
            let month_days = if is_leap_year(year) {
                [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            } else {
                [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
            };
            let mut month = 0;
            for &md in &month_days {
                if remaining < md {
                    break;
                }
                remaining -= md;
                month += 1;
            }
            format!("{:04}-{:02}-{:02}", year, month + 1, remaining + 1)
        }
        Err(_) => "1970-01-01".to_string(),
    }
}

fn is_leap_year(year: i32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}
