"""
kicad_export.py - KiCad exporters driven by the actual schematic graph.

Two formats, both generated from bridge.cad_engine.SchematicNetlistEngine:

1. export_kicad_netlist()  -> KiCad netlist (.net, "export version E").
   Importable by Eeschema (Tools > Generate/Import Netlist) and is the format
   manufacturers and pick-and-place flows expect.

2. export_kicad_schematic() -> KiCad 8/9 schematic (.kicad_sch) with:
     - (lib_symbols ...) generated for every symbol we emit
     - one symbol instance per placed component, at its real coordinates
     - wires between real pin points, junctions where 3+ pins meet
     - deterministic UUIDs (uuid5) so re-exports are stable diffs

Pin numbers follow the standard KiCad libraries so that if the user's KiCad has
those libs installed the symbols resolve to the real ones:

    Device:R / C / L            pins 1,2
    Simulation_SPICE:VSOURCE    pin 1 = +, pin 2 = -
    Device:D                    pin 2 = A (anode), pin 1 = K (cathode)
    Device:Q_NMOS_GDS           pin 1 = G, pin 2 = D, pin 3 = S
    power:GND                   pin 1

Coordinates: the caller supplies schematic-unit pin positions (the editor passes
its live canvas positions), so rotation is preserved exactly.

    python -c "from bridge.kicad_export import export_kicad_schematic; ..."
"""

import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

from bridge.cad_engine import SchematicNetlistEngine

# --------------------------------------------------------------------------
# Symbol table: our canonical pin name -> KiCad pin number + placement
# --------------------------------------------------------------------------
# (ours, kicad_number, x, y, angle, length, electrical_type, name_label)
#
# Pin offsets are expressed in KiCad millimetres and deliberately mirror the
# editor canvas (1 canvas grid cell = 10 px = 2.54 mm), so an exported symbol
# sits where you drew it. Wire endpoints are computed as
# `symbol origin + rotated pin offset`, which is exactly what KiCad does when it
# resolves connectivity - get this wrong and every pin reads as unconnected.
KICAD_SYMBOLS: Dict[str, Dict[str, Any]] = {
    "R": {
        "lib": "Device", "part": "R", "desc": "Resistor", "footprint": "Resistor_SMD:R_0603_1608Metric",
        "body": [("rect", -5.08, -1.27, 10.16, 2.54)],
        "pins": [
            ("1", "1", -7.62, 0.0, 0, 2.54, "passive", "~"),
            ("2", "2", 7.62, 0.0, 180, 2.54, "passive", "~"),
        ],
    },
    "C": {
        "lib": "Device", "part": "C", "desc": "Capacitor", "footprint": "Capacitor_SMD:C_0603_1608Metric",
        "body": [("line", -1.524, -2.794, -1.524, 2.794), ("line", 1.524, -2.794, 1.524, 2.794)],
        "pins": [
            ("1", "1", -7.62, 0.0, 0, 5.842, "passive", "~"),
            ("2", "2", 7.62, 0.0, 180, 5.842, "passive", "~"),
        ],
    },
    "L": {
        "lib": "Device", "part": "L", "desc": "Inductor", "footprint": "Inductor_SMD:L_0805_2012Metric",
        "body": [("rect", -5.08, -1.27, 10.16, 2.54)],
        "pins": [
            ("1", "1", -7.62, 0.0, 0, 2.54, "passive", "~"),
            ("2", "2", 7.62, 0.0, 180, 2.54, "passive", "~"),
        ],
    },
    "V": {
        "lib": "Simulation_SPICE", "part": "VDC", "desc": "Voltage source",
        "footprint": "",
        "body": [("circle", 0.0, 0.0, 3.81), ("line", -1.905, -1.27, -1.905, 1.27),
                 ("line", -1.905, 0.0, -0.635, 0.0), ("line", 0.635, 0.0, 1.905, 0.0),
                 ("line", 1.905, -1.27, 1.905, 1.27)],
        "pins": [
            ("+", "1", -7.62, 0.0, 0, 3.81, "passive", "+"),
            ("-", "2", 7.62, 0.0, 180, 3.81, "passive", "-"),
        ],
    },
    "I": {
        "lib": "Simulation_SPICE", "part": "IDC", "desc": "Current source",
        "footprint": "",
        "body": [("circle", 0.0, 0.0, 3.81), ("line", -2.54, 0.0, 1.27, 0.0),
                 ("line", 0.0, -1.27, 1.27, 0.0), ("line", 0.0, 1.27, 1.27, 0.0)],
        "pins": [
            ("+", "1", -7.62, 0.0, 0, 3.81, "passive", "+"),
            ("-", "2", 7.62, 0.0, 180, 3.81, "passive", "-"),
        ],
    },
    "D": {
        "lib": "Device", "part": "D", "desc": "Diode", "footprint": "Diode_SMD:D_SOD-123",
        "body": [("poly", [(0.0, 2.54), (0.0, -2.54), (3.81, 0.0), (0.0, 2.54)]),
                 ("line", 3.81, -2.54, 3.81, 2.54)],
        "pins": [
            ("A", "2", -7.62, 0.0, 0, 3.81, "passive", "A"),
            ("K", "1", 7.62, 0.0, 180, 3.81, "passive", "K"),
        ],
    },
    "MOSFET": {
        # KiCad's Device:Q_NMOS numbers its pins D/G/S (no numeric pin numbers)
        "lib": "Device", "part": "Q_NMOS", "desc": "N-MOSFET",
        "footprint": "Package_TO_SOT_THT:TO-220-3",
        "body": [("rect", -2.54, -5.08, 5.08, 10.16), ("line", -2.54, 0.0, -7.62, 0.0),
                 ("line", -2.54, -5.08, -7.62, -5.08), ("line", -2.54, 5.08, -7.62, 5.08)],
        "pins": [
            ("D", "D", 0.0, -7.62, 90, 2.54, "passive", "D"),
            ("G", "G", -7.62, 0.0, 180, 2.54, "input", "G"),
            ("S", "S", 0.0, 7.62, 270, 2.54, "passive", "S"),
        ],
    },
    "GND": {
        "lib": "power", "part": "GND", "desc": "Power symbol, ground",
        "footprint": "",
        "body": [("line", 0.0, 0.0, 0.0, 2.54), ("line", -2.54, 2.54, 2.54, 2.54),
                 ("line", -1.524, 3.81, 1.524, 3.81), ("line", -0.762, 5.08, 0.762, 5.08)],
        "pins": [("1", "1", 0.0, 0.0, 90, 0.0, "power_in", "GND")],
    },
    "MCU": {
        "lib": "WOSP", "part": "MCU_GENERIC", "desc": "WOSP co-simulation MCU",
        "footprint": "",
        "body": [("rect", -10.16, -7.62, 20.32, 15.24)],
        "pins": [
            ("GPIO18", "1", -15.24, -5.08, 0, 5.08, "bidirectional", "GPIO18"),
            ("GPIO17", "2", -15.24, 0.0, 0, 5.08, "bidirectional", "GPIO17"),
            ("ADC0", "3", -15.24, 5.08, 0, 5.08, "input", "ADC0"),
            ("GPIO5", "4", 15.24, -5.08, 180, 5.08, "bidirectional", "GPIO5"),
            ("GND", "5", 15.24, 5.08, 180, 5.08, "power_in", "GND"),
        ],
    },
}

# 1 canvas pixel (grid unit) expressed in KiCad schematic millimetres
PX_TO_MM = 0.254
MCU_PIN_PITCH_MM = 2.54


def _mcu_symbol(part: str, desc: str, left, right, footprint: str = "") -> Dict[str, Any]:
    """
    Build a KiCad symbol for a microcontroller board.

    The generic MCU entry above hardcodes five ESP32 pins; a board with 60
    header pins needs its own symbol or the exported schematic would show pins
    the board does not have. Two columns, numbered sequentially, power pins
    typed as power_in so KiCad's ERC treats them correctly.
    """
    rows = max(len(left), len(right))
    height = max(rows * MCU_PIN_PITCH_MM, 10.16)
    top = height / 2.0
    pins = []
    number = 1
    for name in left:
        y = top - (len(left) and _row_y(name, left, rows)) * MCU_PIN_PITCH_MM
        pins.append((name, str(number), -10.16, y, 0, 2.54,
                     "power_in" if _is_power(name) else "bidirectional", name))
        number += 1
    for name in right:
        y = top - (len(right) and _row_y(name, right, rows)) * MCU_PIN_PITCH_MM
        pins.append((name, str(number), 10.16, y, 180, 2.54,
                     "power_in" if _is_power(name) else "bidirectional", name))
        number += 1
    return {
        "lib": "WOSP", "part": part, "desc": desc,
        "footprint": footprint,
        "body": [("rect", -10.16, -height / 2.0, 20.32, height)],
        "pins": pins,
    }


def _row_y(name, column, rows) -> float:
    """Vertical offset of a pin, top-aligned per column."""
    return float(column.index(name))


def _is_power(name: str) -> bool:
    return str(name).upper() in ("GND", "5V", "3V3", "VIN", "VCC", "AREF", "NRST")


def _mcu_symbols() -> Dict[str, Dict[str, Any]]:
    """Per-board MCU symbols, mirroring the editor palette."""
    out: Dict[str, Dict[str, Any]] = {}

    def arduino_pins():
        left = [f"D{i}" for i in range(10)] + [f"A{i}" for i in range(6)]
        right = ([f"D{i}" for i in range(10, 14)]
                 + ["5V", "3V3", "GND", "GND", "VIN", "AREF"])
        return left, right

    uno_left, uno_right = arduino_pins()
    out["ARDUINO_UNO"] = _mcu_symbol(
        "MCU_ARDUINO_UNO", "Arduino Uno (ATmega328P)", uno_left, uno_right,
        "Package_DIP:DIP-28_W7.62mm")
    out["ARDUINO_NANO"] = _mcu_symbol(
        "MCU_ARDUINO_NANO", "Arduino Nano (ATmega328P)", uno_left, uno_right,
        "Package_QFP:LQFP-48_7x7mm_P0.5mm")

    mega_left = [f"D{i}" for i in range(22)]
    mega_right = ([f"D{i}" for i in range(22, 54)] + [f"A{i}" for i in range(16)]
                  + ["5V", "3V3", "GND", "GND", "VIN", "AREF"])
    out["ARDUINO_MEGA"] = _mcu_symbol(
        "MCU_ARDUINO_MEGA", "Arduino Mega 2560", mega_left, mega_right,
        "Package_QFP:LQFP-64_10x10mm_P0.5mm")

    f103_left = [f"PB{i}" for i in range(16)] + [f"PA{i}" for i in range(8)]
    f103_right = ([f"PA{i}" for i in range(8, 16)]
                  + ["3V3", "5V", "GND", "GND", "NRST", "SWDIO", "SWCLK"])
    out["STM32F103"] = _mcu_symbol(
        "MCU_STM32F103", "STM32F103C8T6", f103_left, f103_right,
        "Package_QFP:LQFP-48_7x7mm_P0.5mm")

    esp_left = [f"GPIO{i}" for i in range(0, 16)]
    esp_right = ([f"GPIO{i}" for i in range(16, 32)]
                 + ["3V3", "5V", "GND", "GND", "EN", "VP", "VN"])
    out["ESP32"] = _mcu_symbol(
        "MCU_ESP32", "ESP32 DevKit (ESP32-WROOM-32)", esp_left, esp_right,
        "Module:ESP32-WROOM-32")
    out["ESP32S3"] = _mcu_symbol(
        "MCU_ESP32S3", "ESP32-S3 DevKit", esp_left, esp_right,
        "Module:ESP32-S3-WROOM-1")
    return out


KICAD_SYMBOLS.update(_mcu_symbols())

PROJECT_NAME = "wokispice"
NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def _uid(*parts) -> str:
    """Deterministic UUID so re-exporting the same schematic is a stable diff."""
    return str(uuid.uuid5(NS, "|".join(str(p) for p in parts)))


def _f(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def lib_id_for(comp_type: str) -> Optional[str]:
    spec = KICAD_SYMBOLS.get(comp_type.upper())
    return f"{spec['lib']}:{spec['part']}" if spec else None


def pin_number_for(comp_type: str, pin_name: str) -> Optional[str]:
    """Map our canonical pin name to the KiCad pin number."""
    spec = KICAD_SYMBOLS.get(comp_type.upper())
    if not spec:
        return None
    for ours, number, *_rest in spec["pins"]:
        if ours == pin_name:
            return number
    return None


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def _writable_components(model: SchematicNetlistEngine) -> Dict[str, Any]:
    """Components KiCad can represent (MCUs included; unknown types skipped)."""
    from bridge.cad_engine import is_mcu
    out = {}
    for cid, c in model.components.items():
        ctype = c.comp_type.upper()
        if ctype in KICAD_SYMBOLS or (is_mcu(ctype) and ctype in KICAD_SYMBOLS):
            out[cid] = c
    return out


def kicad_refs(model: SchematicNetlistEngine) -> Dict[str, str]:
    """
    Designator to use in KiCad.

    KiCad requires power symbols to be referenced '#PWRxx' - anything else is
    reported as an annotation error - so ground symbols are renamed on export
    (their WOSP designator is kept in the console/BOM, not in the ref).
    """
    refs: Dict[str, str] = {}
    power = 0
    for comp in sorted(model.components.values(), key=lambda c: c.name):
        if comp.comp_type.upper() == "GND":
            power += 1
            refs[comp.comp_id] = f"#PWR{power:02d}"
        else:
            refs[comp.comp_id] = comp.name
    return refs


def _require_graph(model: SchematicNetlistEngine) -> Dict[str, Any]:
    comps = _writable_components(model)
    if not comps:
        raise ValueError(
            "Nothing to export: place components on the schematic first. "
            "(An empty canvas cannot produce a KiCad file.)")
    return comps


# --------------------------------------------------------------------------
# 1. KiCad netlist (.net)
# --------------------------------------------------------------------------
def export_kicad_netlist(model: SchematicNetlistEngine, output_path: str) -> str:
    """Write a KiCad netlist (export version E) built from the schematic graph."""
    comps = _require_graph(model)
    net_of, _ground = model._resolve_nets()
    refs = kicad_refs(model)

    lines = [
        '(export (version "E")',
        "  (design",
        '    (source "WOSP Schematic Editor")',
        f'    (date "{_today()}")',
        '    (tool "WOSP Schematic Editor"))',
        "  (components",
    ]
    for comp in sorted(comps.values(), key=lambda c: c.name):
        spec = KICAD_SYMBOLS[comp.comp_type.upper()]
        footprint = comp.footprint or spec["footprint"]
        ref = refs[comp.comp_id]
        lines += [
            f'    (comp (ref "{ref}")',
            f'      (value "{_esc(comp.value)}")',
            f'      (footprint "{_esc(footprint)}")',
            f'      (libsource (lib "{spec["lib"]}") (part "{spec["part"]}")',
            f'        (description "{_esc(spec["desc"])}"))',
            f'      (property "Reference" "{ref}" (at 0 0 0) (effects (font (size 1.27 1.27)) (justify left)))',
            f'      (property "Value" "{_esc(comp.value)}" (at 0 0 0) (effects (font (size 1.27 1.27)) (justify left)))',
            f'      (property "Footprint" "{_esc(footprint)}" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
            '      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
            f'      (tstamps "/{_uid("ts", comp.comp_id)}"))',
        ]
    lines.append("  )")

    # libparts for every distinct symbol used
    used = sorted({c.comp_type.upper() for c in comps.values()})
    lines.append("  (libparts")
    for ctype in used:
        spec = KICAD_SYMBOLS[ctype]
        pins = " ".join(
            f'(pin "{number}" {etype} line (at {x} {y} {angle}) (length {length}) '
            f'(name "{name}" (effects (font (size 1.27 1.27)))) '
            f'(number "{number}" (effects (font (size 1.27 1.27)))))'
            for _ours, number, x, y, angle, length, etype, name in spec["pins"]
        )
        lines += [
            f'    (libpart (lib "{spec["lib"]}") (part "{spec["part"]}")',
            f'      (description "{_esc(spec["desc"])}")',
            '      (fields (field (name "Reference" "U") (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
            '             (field (name "Value") (at 0 0 0) (effects (font (size 1.27 1.27))))',
            '             (field (name "Footprint") (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
            '             (field (name "Datasheet") (at 0 0 0) (effects (font (size 1.27 1.27)) hide)))',
            f"      (pins {pins}))",
        ]
    lines.append("  )")

    # nets, with real nodes
    lines.append("  (nets")
    code = 0
    seen = {}
    for (cid, pin), net in sorted(net_of.items(), key=lambda kv: (kv[1], kv[0])):
        comp = model.components.get(cid)
        if comp is None or comp.comp_type.upper() not in KICAD_SYMBOLS:
            continue
        number = pin_number_for(comp.comp_type, pin)
        if number is None:
            continue
        if net not in seen:
            code += 1
            seen[net] = code
            lines.append(f'    (net (code "{code}") (name "{_esc(net)}")')
        lines.append(f'      (node (ref "{refs[cid]}") (pin "{number}") (pinfunction "~") (pintype "passive"))')
    for net, c in seen.items():                      # close each net
        lines.append("    )")
    lines.append("  )")
    lines.append("  (groups)")
    lines.append(")")

    return _write(output_path, "\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# 2. KiCad schematic (.kicad_sch)
# --------------------------------------------------------------------------
def _body_text(spec) -> List[str]:
    out = []
    for prim in spec["body"]:
        if prim[0] == "rect":
            _, x, y, w, h = prim
            out.append(f'(rectangle (start {_f(x)} {_f(y)}) (end {_f(x + w)} {_f(y + h)}) '
                       "(stroke (width 0.254) (type default)) (fill (type background)))")
        elif prim[0] == "circle":
            _, cx, cy, r = prim
            out.append(f"(circle (center {_f(cx)} {_f(cy)}) (radius {_f(r)}) "
                       "(stroke (width 0.254) (type default)) (fill (type none)))")
        elif prim[0] == "line":
            _, x1, y1, x2, y2 = prim
            out.append(f"(polyline (pts (xy {_f(x1)} {_f(y1)}) (xy {_f(x2)} {_f(y2)})) "
                       "(stroke (width 0.254) (type default)))")
        elif prim[0] == "poly":
            pts = " ".join(f"(xy {_f(x)} {_f(y)})" for x, y in prim[1])
            out.append(f"(polyline (pts {pts}) (stroke (width 0.254) (type default)) "
                       "(fill (type background)))")
    return out


def _lib_symbols_text(used_types: List[str]) -> str:
    blocks = ["  (lib_symbols"]
    for ctype in used_types:
        spec = KICAD_SYMBOLS[ctype]
        symbol_id = f"{spec['lib']}:{spec['part']}"
        ref_prefix = "R" if ctype in ("R",) else ("C" if ctype == "C" else
                        ("L" if ctype == "L" else ("D" if ctype == "D" else
                        ("Q" if ctype == "MOSFET" else ("#PWR" if ctype == "GND" else "U")))))
        blocks.append(f'    (symbol "{symbol_id}" (pin_numbers (hide yes)) '
                      "(pin_names (offset 0.254)) (exclude_from_sim no) "
                      "(in_bom yes) (on_board yes) (duplicate_pin_numbers_are_jumpers no)")
        blocks.append(f'      (property "Reference" "{ref_prefix}" (at 0 {_f(3.81)} 0) '
                      "(effects (font (size 1.27 1.27))))")
        blocks.append(f'      (property "Value" "{spec["part"]}" (at 0 -{_f(3.81)} 0) '
                      "(effects (font (size 1.27 1.27))))")
        blocks.append('      (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))')
        blocks.append('      (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))')
        blocks.append(f'      (symbol "{spec["part"]}_0_1"')
        for line in _body_text(spec):
            blocks.append(f"        {line}")
        blocks.append("      )")
        blocks.append(f'      (symbol "{spec["part"]}_1_1"')
        for ours, number, x, y, angle, length, etype, name in spec["pins"]:
            blocks.append(
                f'        (pin {etype} line (at {_f(x)} {_f(y)} {angle}) (length {_f(length)}) '
                f'(name "{name}" (effects (font (size 1.27 1.27)))) '
                f'(number "{number}" (effects (font (size 1.27 1.27)))))')
        blocks.append("      )")
        blocks.append("    )")
    blocks.append("  )")
    return "\n".join(blocks)


def export_kicad_schematic(
    model: SchematicNetlistEngine,
    output_path: str,
    origins: Optional[Dict[str, Tuple[float, float]]] = None,
    title: str = "WOSP Schematic",
) -> str:
    """
    Write a KiCad 9/10 schematic from the graph.

    Symbol positions come from the component's canvas coordinates (scaled by
    PX_TO_MM) or from the optional `origins` override, expressed in mm.
    Wire endpoints are derived as `origin + rotated pin offset`, which is how
    KiCad itself resolves pin connectivity - so rotation is preserved.
    """
    comps = _require_graph(model)
    used_types = sorted({c.comp_type.upper() for c in comps.values()})
    refs = kicad_refs(model)
    root_uuid = _uid("root")

    head = [
        "(kicad_sch",
        "  (version 20250114)",
        '  (generator "eeschema")',
        '  (generator_version "9.0")',
        f'  (uuid "{root_uuid}")',
        '  (paper "A4")',
        "  (title_block",
        f'    (title "{_esc(title)}")',
        '    (company "WOSP")',
        '    (rev "1")',
        "  )",
    ]
    lines = head + [_lib_symbols_text(used_types)]

    for comp in sorted(comps.values(), key=lambda c: c.name):
        spec = KICAD_SYMBOLS[comp.comp_type.upper()]
        pos = _symbol_origin(comp, origins)
        angle = -int(comp.rotation or 0) % 360
        lines += [
            f'  (symbol (lib_id "{spec["lib"]}:{spec["part"]}") '
            f'(at {_f(pos[0])} {_f(pos[1])} {angle}) (unit 1)',
            "    (exclude_from_sim no)",
            "    (in_bom yes) (on_board yes)",
            "    (dnp no)",
            f'    (uuid "{_uid("sym", comp.comp_id)}")',
            f'    (property "Reference" "{refs[comp.comp_id]}" (at {_f(pos[0])} {_f(pos[1] - 3.81)} 0) '
            "(effects (font (size 1.27 1.27)) (justify left)))",
            f'    (property "Value" "{_esc(comp.value)}" (at {_f(pos[0])} {_f(pos[1] + 3.81)} 0) '
            "(effects (font (size 1.27 1.27)) (justify left)))",
            f'    (property "Footprint" "{_esc(comp.footprint or spec["footprint"])}" '
            f'(at {_f(pos[0])} {_f(pos[1])} 0) (effects (font (size 1.27 1.27)) hide))',
            '    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))',
        ]
        for _ours, number, *_rest in spec["pins"]:
            lines.append(f'    (pin "{number}" (uuid "{_uid("pin", comp.comp_id, number)}"))')
        lines.append(
            f'    (instances (project "{PROJECT_NAME}" (path "/{root_uuid}" '
            f'(reference "{refs[comp.comp_id]}") (unit 1))))')
        lines.append("  )")

    # Wires + junctions from real symbol geometry
    net_of, _ground = model._resolve_nets()
    net_points: Dict[str, List[Tuple[float, float]]] = {}
    for wire in model.wires:
        a = _split_ref(wire.get("from", ""))
        b = _split_ref(wire.get("to", ""))
        pa = _pin_point(model, a, origins)
        pb = _pin_point(model, b, origins)
        if pa is None or pb is None:
            continue
        lines.append(
            f"  (wire (pts (xy {_f(pa[0])} {_f(pa[1])}) (xy {_f(pb[0])} {_f(pb[1])})) "
            f'(stroke (width 0) (type default)) (uuid "{_uid("wire", wire.get("from"), wire.get("to"))}"))')
        net_name = net_of.get(a) or "unconnected"
        net_points.setdefault(net_name, []).append(pa)
        net_points.setdefault(net_name, []).append(pb)

    # Component pins count as connections too, so a T made of two wires landing
    # on a third pin still gets a junction (this is the usual ground rail).
    for (cid, pin), net_name in net_of.items():
        point = _pin_point(model, (cid, pin), origins)
        if point is not None:
            net_points.setdefault(net_name, []).append(point)

    # A junction is required wherever three or more connections meet at one point
    for net_name, pts in sorted(net_points.items()):
        counts: Dict[str, int] = {}
        spots: Dict[str, Tuple[float, float]] = {}
        for x, y in pts:
            key = (_f(x), _f(y))
            counts[key] = counts.get(key, 0) + 1
            spots.setdefault(key, (x, y))
        for key, count in sorted(counts.items()):
            if count < 3:
                continue
            x, y = spots[key]
            lines.append(
                f"  (junction (at {_f(x)} {_f(y)}) (diameter 0) (color 0 0 0 0) "
                f'(uuid "{_uid("junction", net_name, key)}"))')

    # Carry human net names across as local labels on a point of each net
    for net_name, pts in sorted(net_points.items()):
        if net_name == "0" or net_name.startswith("NET_") or not pts:
            continue
        x, y = pts[0]
        lines.append(
            f'  (label "{_esc(net_name)}" (at {_f(x)} {_f(y)} 0) (fields_autoplaced yes)'
            " (effects (font (size 1.27 1.27)) (justify left bottom))"
            f' (uuid "{_uid("label", net_name)}"))')

    lines.append('  (sheet_instances (path "/" (page "1")))')
    lines.append("  (embedded_fonts no)")
    lines.append(")")

    return _write(output_path, "\n".join(lines) + "\n")


# --------------------------------------------------------------------------
def _symbol_origin(comp, origins=None) -> Tuple[float, float]:
    """Symbol placement in mm (KiCad schematic units)."""
    if origins and comp.comp_id in origins:
        return tuple(origins[comp.comp_id])
    return (comp.x * PX_TO_MM, comp.y * PX_TO_MM)


def _pin_offset(comp_type: str, pin_name: str) -> Optional[Tuple[float, float]]:
    spec = KICAD_SYMBOLS.get(comp_type.upper())
    if not spec:
        return None
    for ours, _number, x, y, *_rest in spec["pins"]:
        if ours == pin_name:
            return (x, y)
    return None


def _rotate_xy(x: float, y: float, angle_deg: float) -> Tuple[float, float]:
    import math
    rad = math.radians(angle_deg)
    return (x * math.cos(rad) - y * math.sin(rad),
            x * math.sin(rad) + y * math.cos(rad))


def _pin_point(model, ref, origins=None) -> Optional[Tuple[float, float]]:
    """Absolute mm position of a pin, matching KiCad's own connectivity math."""
    cid, pin = ref
    comp = model.components.get(cid)
    if comp is None or comp.comp_type.upper() not in KICAD_SYMBOLS:
        return None
    offset = _pin_offset(comp.comp_type, pin)
    if offset is None:
        return None
    ox, oy = _symbol_origin(comp, origins)
    # Canvas rotation is clockwise; KiCad angles are counter-clockwise.
    dx, dy = _rotate_xy(offset[0], offset[1], -float(comp.rotation or 0))
    return (ox + dx, oy + dy)


def _split_ref(ref: str) -> Tuple[str, str]:
    if ":" not in ref:
        return ("", "")
    cid, pin = ref.split(":", 1)
    return (cid, pin)


def _esc(text) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _today() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


def _write(output_path: str, text: str) -> str:
    directory = os.path.dirname(os.path.abspath(output_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    return output_path