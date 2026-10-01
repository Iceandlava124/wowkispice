"""
test_industrial_verification.py - Automated Test Battery for Industrial-Grade Verification (DO-254 / ISO 26262)
Verifies:
1. Temperature Corner Sweeps (-40°C to +125°C Automotive AEC-Q100)
2. Dynamic Step-Load Response & Settling Time Analysis
3. Hardware Fault Injection (FIT) & Safety Mitigation (OVP, OCP, FMEA)
4. Requirements Traceability Matrix (RTM) & Process Capability (Cpk >= 1.33)
5. Industrial Qualification HTML Report Generation
"""

import os
import sys
import unittest

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.industrial_verification import IndustrialVerificationEngine


class TestIndustrialVerification(unittest.TestCase):
    def setUp(self):
        self.verifier = IndustrialVerificationEngine()

    def test_01_temperature_corners_sweep(self):
        """Verify temperature sweep across -40°C to +125°C AEC-Q100 Grade 1."""
        sweep = self.verifier.run_temperature_corners_sweep([-40.0, 25.0, 85.0, 125.0])
        self.assertEqual(len(sweep["corners"]), 4)
        self.assertTrue(sweep["all_passed"])
        self.assertLess(sweep["max_junction_c"], 150.0)  # Silicon junction limit
        
        # Verify cold vs hot output regulation within 5%
        for corner in sweep["corners"]:
            self.assertGreaterEqual(corner["vout_v"], 3.135)
            self.assertLessEqual(corner["vout_v"], 3.465)
            self.assertGreater(corner["efficiency_pct"], 70.0)

    def test_02_dynamic_step_transient_characterization(self):
        """Verify step response undershoot, overshoot, and settling time under sudden load."""
        step = self.verifier.characterize_step_transient(rload_initial=10.0, rload_step=2.0)
        self.assertTrue(step["compliant"])
        self.assertLess(step["undershoot_pct"], 10.0)
        self.assertLess(step["overshoot_pct"], 10.0)
        self.assertLess(step["settling_time_ms"], 4.0)

    def test_03_hardware_fault_injection_battery(self):
        """Verify FMEA fault injection battery and safety containment."""
        faults = self.verifier.run_fault_injection_battery()
        self.assertEqual(len(faults), 4)
        for f in faults:
            self.assertEqual(f["safety_verdict"], "SAFE_CONTAINED")
            self.assertIn("ASIL", f["asul_rating"])
            self.assertIn("FIT-", f["fault_id"])

    def test_04_rtm_and_process_capability_cpk(self):
        """Verify Requirements Traceability Matrix and statistical capability Cpk >= 1.33."""
        rtm_data = self.verifier.evaluate_requirements_traceability()
        self.assertEqual(rtm_data["overall_status"], "QUALIFIED")
        self.assertGreaterEqual(rtm_data["cpk"], 1.33)
        self.assertEqual(len(rtm_data["rtm"]), 5)
        for req in rtm_data["rtm"]:
            self.assertEqual(req["compliance"], "COMPLIANT")

    def test_05_industrial_qualification_report_generation(self):
        """Verify DO-254 / ISO 26262 Industrial Qualification Report generation."""
        test_out = os.path.join(os.path.dirname(__file__), "temp_qual_report.html")
        html = self.verifier.generate_qualification_report(output_path=test_out)
        
        self.assertTrue(os.path.exists(test_out))
        self.assertIn("INDUSTRIAL QUALIFICATION &amp; SAFETY REPORT", html.replace("&", "&amp;"))
        self.assertIn("DO-254 / ISO 26262", html)
        self.assertIn("Extreme Temperature Corners Sweep", html)
        self.assertIn("Failure Mode &amp; Effects Analysis", html.replace("&", "&amp;"))
        
        if os.path.exists(test_out):
            os.remove(test_out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
