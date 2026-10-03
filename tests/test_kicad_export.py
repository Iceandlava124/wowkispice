"""
test_kicad_export.py - Verification for the KiCad exporters.

Three layers:
1. Structure: balanced s-expressions, one symbol per component, real wires.
2. Pin mapping: our canonical pin names map to the pin numbers KiCad's own
   libraries use (Device:D is K=1/A=2, Device:Q_NMOS is numbered D/G/S).
3. Round-trip: if kicad-cli is installed, KiCad must actually load the file and
   resolve our wires into the nets the schematic intends. Skipped otherwise.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.cad_engine import SchematicComponent, SchematicNetlistEngine
from bridge.kicad_export import (
    KICAD_SYMBOLS, export_kicad_netlist, export_kicad_schematic, kicad_refs,
    pin_number_for,
)

KICAD_CLI_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\kicad-cli.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\KiCad\9.0\bin\kicad-cli.exe"),
    r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
    "/usr/bin/kicad-cli",
]


def find_kicad_cli():
    for path in KICAD_CLI_CANDIDATES:
        if path and os.path.exists(path):
            return path
    return None


def build_rc():
    """12 V -> 1k -> 'out' with 100nF to ground."""
    g = SchematicNetlistEngine()
    for c in [SchematicComponent("V1", "V", "V1", "12", 0, 0),
              SchematicComponent("R1", "R", "R1", "1k", 80, 0),
              SchematicComponent("C1", "C", "C1", "100n", 160, 0),
              SchematicComponent("GND1", "GND", "GND", "", 160, 80)]:
        g.add_component(c)
    g.add_wire("V1:+", "R1:1", "in")
    g.add_wire("V1:-", "GND1:1", "gnd")
    g.add_wire("R1:2", "C1:1", "out")
    g.add_wire("C1:2", "GND1:1", "gnd")
    return g


def balanced(text):
    depth = 0
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


class TestSchematicStructure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.model = build_rc()
        self.path = os.path.join(self.tmp, "out.kicad_sch")
        export_kicad_schematic(self.model, self.path)
        with open(self.path, encoding="utf-8") as f:
            self.text = f.read()

    def test_file_is_balanced_s_expression(self):
        self.assertTrue(balanced(self.text), "unbalanced parentheses")

    def test_one_symbol_per_component(self):
        self.assertEqual(self.text.count("(symbol (lib_id"), len(self.model.components))

    def test_wires_come_from_the_graph(self):
        self.assertEqual(self.text.count("(wire "), len(self.model.wires))

    def test_junction_where_three_pins_meet(self):
        # 'gnd' ties V1-, C1 and the ground symbol: three points, so a junction
        self.assertIn("(junction (at", self.text)

    def test_power_symbol_uses_pwr_reference(self):
        refs = kicad_refs(self.model)
        self.assertTrue(refs["GND1"].startswith("#PWR"))
        self.assertEqual(refs["R1"], "R1")
        self.assertIn(f'(property "Reference" "{refs["GND1"]}"', self.text)

    def test_named_nets_survive_as_labels(self):
        self.assertIn('(label "in"', self.text)
        self.assertIn('(label "out"', self.text)

    def test_export_is_deterministic(self):
        second = os.path.join(self.tmp, "again.kicad_sch")
        export_kicad_schematic(build_rc(), second)
        with open(second, encoding="utf-8") as f:
            other = f.read()
        self.assertEqual(self.text.replace("out.kicad_sch", ""),
                         other.replace("again.kicad_sch", ""))

    def test_empty_schematic_refuses_instead_of_faking(self):
        empty = SchematicNetlistEngine()
        with self.assertRaises(ValueError):
            export_kicad_schematic(empty, os.path.join(self.tmp, "empty.kicad_sch"))


class TestPinMapping(unittest.TestCase):
    def test_diode_matches_kicad_convention(self):
        # Device:D: pin 1 is the cathode, pin 2 the anode
        self.assertEqual(pin_number_for("D", "K"), "1")
        self.assertEqual(pin_number_for("D", "A"), "2")

    def test_sources_map_to_kicad_parts(self):
        self.assertEqual(KICAD_SYMBOLS["V"]["part"], "VDC")
        self.assertEqual(KICAD_SYMBOLS["I"]["part"], "IDC")
        self.assertEqual(pin_number_for("V", "+"), "1")
        self.assertEqual(pin_number_for("V", "-"), "2")

    def test_mosfet_pins_match_library_numbering(self):
        # KiCad 10 Device:Q_NMOS numbers pins D/G/S, not 1/2/3
        self.assertEqual(KICAD_SYMBOLS["MOSFET"]["part"], "Q_NMOS")
        self.assertEqual(pin_number_for("MOSFET", "G"), "G")

    def test_every_symbol_has_pin_offsets(self):
        for ctype, spec in KICAD_SYMBOLS.items():
            for ours, _number, x, y, *_rest in spec["pins"]:
                self.assertIsNotNone(pin_number_for(ctype, ours),
                                     f"{ctype} pin {ours} unmapped")


class TestNetlistExport(unittest.TestCase):
    def test_netlist_contains_components_and_nets(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "out.net")
        export_kicad_netlist(build_rc(), path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertTrue(balanced(text))
        self.assertIn('(comp (ref "R1")', text)
        self.assertIn('(net (code "1")', text)
        self.assertIn('(libpart (lib "Device") (part "R")', text)


@unittest.skipUnless(find_kicad_cli(), "kicad-cli not installed")
class TestRealKiCadRoundTrip(unittest.TestCase):
    """KiCad itself must load the file and agree about our connectivity."""

    def test_kicad_resolves_the_intended_nets(self):
        cli = find_kicad_cli()
        tmp = tempfile.mkdtemp()
        sch = os.path.join(tmp, "rt.kicad_sch")
        net = os.path.join(tmp, "rt.net")
        export_kicad_schematic(build_rc(), sch)

        result = subprocess.run([cli, "sch", "export", "netlist", "--output", net, sch],
                                capture_output=True, text=True, timeout=120)
        self.assertTrue(os.path.exists(net),
                        f"kicad-cli could not load the schematic:\n{result.stdout}\n{result.stderr}")

        with open(net, encoding="utf-8") as f:
            text = f.read()
        self.assertIn('(name "/in")', text)    # V1+ and R1 share a net
        self.assertIn('(name "/out")', text)   # R1 and C1 share a net
        self.assertIn('(name "Net-(V1--)")', text)  # ground rail


if __name__ == "__main__":
    unittest.main(verbosity=2)