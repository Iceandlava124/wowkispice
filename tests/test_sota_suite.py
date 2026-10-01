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

        netlist = self.cad.generate_spice_netlist(vin=12.0)
        self.assertGreater(len(netlist), 5)
        self.assertTrue(any("Vin in 0 DC 12.00" in line for line in netlist))
        self.assertTrue(any("S1 in sw_node gate 0 SW_MODEL" in line for line in netlist))

    def test_02_kicad_schematic_export(self):
        """Test export to standard KiCad schematic format (.kicad_sch)."""
        test_out = os.path.join(os.path.dirname(__file__), "temp_test_export.kicad_sch")
        self.cad.export_kicad_schematic(test_out)
        self.assertTrue(os.path.exists(test_out))
        
        with open(test_out, "r") as f:
            content = f.read()
        self.assertIn("kicad_sch", content)
        self.assertIn("ESP32-WROOM-32", content)
        self.assertIn("IRF540N", content)
        
        # Cleanup
        if os.path.exists(test_out):
            os.remove(test_out)

    def test_03_bom_and_costing(self):
        """Test Bill of Materials generation with MPNs and cost computation."""
        bom = self.cad.generate_bom()
        self.assertGreater(len(bom), 4)
        total_cost = sum(item["Extended Cost"] for item in bom)
        self.assertGreater(total_cost, 3.0)  # Total prototype cost > $3
        self.assertIn("MPN", bom[0])
        self.assertIn("Designator", bom[0])

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
        """Test Multi-Protocol Bus Packet Decoder (UART, I2C, SPI, CAN)."""
        time_ms = np.linspace(0, 5.0, 500)
        sig = np.array([1 if (i // 25) % 2 == 0 else 0 for i in range(500)])
        packets = StudioSimulationEngine.decode_uart_packets(sig, time_ms, baud_rate=115200)
        
        types = [p["type"] for p in packets]
        self.assertIn("UART_TX", types)
        self.assertIn("I2C_ADDR", types)
        self.assertIn("SPI_MOSI", types)
        self.assertIn("CAN_FRAME", types)


if __name__ == "__main__":
    unittest.main(verbosity=2)
