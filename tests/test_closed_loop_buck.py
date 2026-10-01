"""
test_closed_loop_buck.py - Automated unit test for Closed-loop buck converter regulation.
"""

import sys
import os
import unittest
import numpy as np

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.mock_controller import run_closed_loop_simulation


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
