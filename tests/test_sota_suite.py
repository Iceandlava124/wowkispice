"""
test_sota_suite.py - Verification for State-of-the-Art (SOTA) Studio Capabilities
Tests:
1. CAD Netlist Compiler & Component Graph
2. KiCad 8 Schematic Exporter (.kicad_sch)
3. Bill of Materials (BOM) & Commercial Cost Estimator
4. Automated HTML / PDF Engineering Lab Report Generator
5. Monte Carlo Statistical Component Tolerance & Yield Analysis
6. Solar PV Curve Tracer & Maximum Power Point Tracker (MPPT)
7. Multi-Protocol Bus Packet Decoder (UART / I2C / SPI / CAN)
"""

import os
import sys
import unittest
import numpy as np

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.studio_engine import StudioSimulationEngine
from bridge.cad_engine import SchematicNetlistEngine, SchematicComponent
from bridge.report_generator import LabReportGenerator


class TestSOTASuite(unittest.TestCase):
    def setUp(self):
        self.engine = StudioSimulationEngine()
        self.cad = SchematicNetlistEngine()

    def test_01_cad_graph_and_spice_netlist_generation(self):
        """Test CAD component placement and SPICE netlist compilation."""
        c1 = SchematicComponent("U1", "MCU", "ESP32", "240MHz", 50, 80)
        c2 = SchematicComponent("Q1", "MOSFET", "IRF540N", "100V", 120, 80)
        self.cad.add_component(c1)
        self.cad.add_component(c2)
        self.cad.add_wire("U1:GPIO18", "Q1:GATE")

        # A complete RC low-pass built purely from the component graph
        v1 = SchematicComponent("V1", "V", "V1", "12", 50, 200)
        r1 = SchematicComponent("R1", "R", "R1", "10k", 120, 200)
        c3 = SchematicComponent("C1", "C", "C1", "100n", 190, 200)
        g1 = SchematicComponent("GND1", "GND", "GND", "", 190, 260)
        for comp in (v1, r1, c3, g1):
            self.cad.add_component(comp)
        self.cad.add_wire("V1:+", "R1:1", "in")
        self.cad.add_wire("V1:-", "GND1:1", "gnd")
        self.cad.add_wire("R1:2", "C1:1", "out")
        self.cad.add_wire("C1:2", "GND1:1", "gnd")
        # Fully wire the MOSFET so no unconnected-pin warnings fire
        self.cad.add_wire("Q1:DRAIN", "V1:+")
        self.cad.add_wire("Q1:SOURCE", "GND1:1")
        # Declared pin behaviour so the MCU drives a defined level (no warnings)
        self.cad.gpio_profiles["U1"] = {"GPIO18": {"mode": "static", "level": 1}}

        netlist, nets, warnings = self.cad.compile_netlist(vin=12.0)
        self.assertGreater(len(netlist), 5)
        self.assertTrue(any(line.startswith("V1 ") and "DC 12" in line for line in netlist), netlist)
        self.assertTrue(any(line.startswith("R1 ") and "10k" in line for line in netlist), netlist)
        self.assertTrue(any(line.startswith("C1 ") and "100n" in line for line in netlist), netlist)
        # MOSFET emitted as M-device: drain=in, gate=GPIO18 net, source/bulk=0
        self.assertTrue(any(line.startswith("MQ1 ") and "NMOS_MODEL" in line for line in netlist), netlist)
        # The MCU drives its wired pin as a real voltage source onto NET_1
        self.assertTrue(any(line.startswith("VU1_GPIO18 NET_1 0 DC") for line in netlist), netlist)
        self.assertTrue(any("* MCU U1" in line for line in netlist), netlist)
        self.assertIn("out", nets)             # probeable nodes returned for waveform plots
        self.assertTrue(any(line.startswith(".tran") for line in netlist))
        self.assertEqual(netlist[-1], ".end")
        self.assertEqual(warnings, [], warnings)  # fully wired circuit -> no warnings

        # An empty schematic falls back to the legacy reference buck converter
        empty = SchematicNetlistEngine()
        fallback, _, _ = empty.compile_netlist(vin=12.0)
        self.assertTrue(any("Vin in 0 DC 12.00" in line for line in fallback))
        self.assertTrue(any("S1 in sw_node gate 0 SW_MODEL" in line for line in fallback))

    def test_02_kicad_schematic_export(self):
        """Test export to standard KiCad schematic format (.kicad_sch)."""
        # Build a real circuit first: the export compiles the graph, it no
        # longer emits a canned reference sheet.
        v1 = SchematicComponent("V1", "V", "V1", "12", 0, 0)
        r1 = SchematicComponent("R1", "R", "R1", "10k", 80, 0)
        g1 = SchematicComponent("GND1", "GND", "GND", "", 80, 80)
        for comp in (v1, r1, g1):
            self.cad.add_component(comp)
        self.cad.add_wire("V1:+", "R1:1", "in")
        self.cad.add_wire("V1:-", "GND1:1", "gnd")
        self.cad.add_wire("R1:2", "GND1:1", "gnd")

        test_out = os.path.join(os.path.dirname(__file__), "temp_test_export.kicad_sch")
        self.cad.export_kicad_schematic(test_out)
        self.assertTrue(os.path.exists(test_out))

        with open(test_out, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("kicad_sch", content)
        self.assertIn('(lib_id "Device:R")', content)     # real placed parts
        self.assertIn('(lib_id "Simulation_SPICE:VDC")', content)
        self.assertEqual(content.count("(symbol (lib_id"), 3)
        self.assertEqual(content.count("(wire "), 3)

        # An empty schematic must refuse rather than fake a document
        from bridge.cad_engine import SchematicNetlistEngine
        with self.assertRaises(ValueError):
            SchematicNetlistEngine().export_kicad_schematic(test_out)

        # Cleanup
        if os.path.exists(test_out):
            os.remove(test_out)

    def test_03_bom_and_costing(self):
        """Test Bill of Materials generation with MPNs and cost computation."""
        # Build a small circuit with real components
        self.cad.clear()
        v1 = SchematicComponent("V1", "V", "V1", "12", 0, 0)
        r1 = SchematicComponent("R1", "R", "R1", "10k", 80, 0)
        c1 = SchematicComponent("C1", "C", "C1", "100n", 160, 0)
        g1 = SchematicComponent("GND1", "GND", "GND", "", 80, 80)
        for comp in (v1, r1, c1, g1):
            self.cad.add_component(comp)
        bom = self.cad.generate_bom()
        self.assertGreater(len(bom), 2)
        total_cost = sum(item["Extended Cost"] for item in bom)
        self.assertGreaterEqual(total_cost, 0.0)
        self.assertIn("MPN", bom[0])
        self.assertIn("Designator", bom[0])
        self.assertIn("Source", bom[0])
        self.assertEqual(bom[0]["Source"], "drawn schematic")

    def test_04_lab_report_generation(self):
        """Test automated HTML lab test report generation."""
        metrics = self.engine.run_simulation(duration_ms=4.0)
        html = LabReportGenerator.generate_html_report(metrics, project_name="SOTA Buck Test")
        
        self.assertIn("WOWKISPICE Co-Simulation Test Report", html)
        self.assertIn("Executive Summary", html)
        self.assertIn("Power & Thermal Dissipation Breakdown", html)
        self.assertIn("Phase Margin (PM)", html)

    def test_05_monte_carlo_yield_analysis(self):
        """Test Monte Carlo statistical tolerance analysis with component variations."""
        mc = self.engine.run_monte_carlo(iterations=30, l_tolerance_pct=10.0, c_tolerance_pct=20.0)
        self.assertEqual(mc["iterations"], 30)
        self.assertGreater(mc["v_mean"], 3.0)
        self.assertLess(mc["v_mean"], 3.6)
        self.assertGreater(mc["yield_pct"], 80.0)
        self.assertEqual(len(mc["v_samples"]), 30)

    def test_06_solar_pv_mppt_tracer(self):
        """Test Solar PV I-V and P-V curve tracer with Maximum Power Point extraction."""
        solar = StudioSimulationEngine.trace_solar_pv(irradiance_w_m2=1000.0, temp_c=25.0)
        self.assertGreater(solar["v_oc"], 18.0)
        self.assertGreater(solar["i_sc"], 4.0)
        self.assertGreater(solar["p_max_w"], 50.0)
        self.assertGreater(solar["v_mpp"], 12.0)
        self.assertLess(solar["v_mpp"], solar["v_oc"])

    def test_07_multi_protocol_bus_decoder(self):
        """Decode a real UART 8N1 byte stream from the bus decoder.

        The old body fed a 2 kHz square wave to the decoder at 115200 baud and
        asserted I2C/SPI/CAN frames came back.  That was wrong twice over: the
        square wave is only about one sample per bit at 115200 baud, so nothing
        is decodable, and no single digital line can yield I2C/SPI/CAN frames
        in the first place (those need SDA+SCL, MOSI+SCK and a CAN pair).  The
        old assertions could only pass on the canned demo packets -- the exact
        "invented frames" behaviour that was removed for the editor serial tab.
        This test builds a genuinely decodable 8N1 stream and checks the bytes.
        """
        baud = 9600
        samples_per_bit = 10
        dt_ms = (1000.0 / baud) / samples_per_bit

        def frame(byte):
            bits = [0] + [(byte >> k) & 1 for k in range(8)] + [1]
            return [b for b in bits for _ in range(samples_per_bit)]

        idle = [1] * (5 * samples_per_bit)
        sig = []
        sig += idle
        for byte in b"OK\n":
            sig += frame(byte)
            sig += idle
        sig = np.array(sig, dtype=float)
        time_ms = np.arange(len(sig)) * dt_ms
        packets = StudioSimulationEngine.decode_uart_packets(
            sig, time_ms, baud_rate=baud)
        
        types = [p["type"] for p in packets]
        self.assertEqual(set(types), {"UART_TX"},
                         "a single UART line can only produce UART_TX frames")
        self.assertEqual([p["hex"] for p in packets],
                         ["0x4F", "0x4B", "0x0A"])
        self.assertEqual([p["ascii"] for p in packets], ["O", "K", "<0A>"])
        for packet in packets:
            self.assertEqual(packet["parity"], "OK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
