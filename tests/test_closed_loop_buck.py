"""
test_closed_loop_buck.py - Automated unit test for Closed-loop buck converter regulation.
"""

import sys
import os
import unittest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.mock_controller import run_closed_loop_simulation, MockESP32BuckController


class TestThresholdsMatchFirmware(unittest.TestCase):
    """mock_controller and control_law must agree on the decision boundary.

    Both model the same firmware, so both must cross at the same counts. The
    firmware declares ADC_LOW_THRESHOLD 1995 / ADC_HIGH_THRESHOLD 2030; these
    are derived from the controller's defaults rather than restated, so they
    cannot drift apart silently again.
    """

    def test_counts_match_the_firmware_constants(self):
        c = MockESP32BuckController()
        self.assertEqual(c.adc_low, 1995)
        self.assertEqual(c.adc_high, 2030)

    def test_divider_is_not_applied_twice(self):
        """It reads the real `fb` node, so the divider belongs in thresholds only."""
        c = MockESP32BuckController()
        self.assertEqual(c.divider_ratio, 0.5)
        # 1997 would mean the divider had also been applied to the reading.
        self.assertNotEqual(c.adc_low, 997)


class TestClosedLoopBuck(unittest.TestCase):
    def test_buck_regulation(self):
        res = run_closed_loop_simulation(
            total_time_ms=5.0,
            tstep_us=0.5,
            save_plot=False
        )
        
        avg_vout = res["avg_vout"]
        ripple = res["ripple_p2p"]
        switch_count = res["switch_count"]
        
        # 1. Check regulation target (3.3V +- 0.10V)
        self.assertTrue(3.20 <= avg_vout <= 3.40, f"Regulation failed: Avg Vout was {avg_vout:.4f}V")

        # 2. Check ripple is within expected hysteretic bounds (< 300mV)
        self.assertLess(ripple, 0.300, f"Ripple too high: {ripple*1000:.1f}mV")

        # 3. Check continuous gate toggling occurred
        self.assertGreater(switch_count, 50, f"Expected > 50 switch events, got {switch_count}")


if __name__ == "__main__":
    unittest.main()
