"""
test_golden_traces.py - Golden trace regression tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.golden_trace import GoldenTrace


class TestGoldenTraces(unittest.TestCase):
    def test_golden_trace_framework(self):
        """Test golden trace framework works"""
        gt = GoldenTrace("test_dummy")
        time = [0.0, 0.001, 0.002]
        traces = {"vout": [0.0, 1.5, 3.0]}
        gt.save(time, traces, {"test": True})
        
        loaded_time, loaded_traces, meta = gt.load()
        self.assertEqual(len(loaded_time), 3)
        self.assertIn("vout", loaded_traces)
        self.assertEqual(meta.get("test"), True)
        
        ok, errors = gt.compare(time, traces)
        self.assertTrue(ok)
        self.assertEqual(len(errors), 0)
    
    def test_golden_trace_tolerance(self):
        """Test golden trace comparison with tolerances"""
        gt = GoldenTrace("test_dummy2")
        time = [0.0, 0.001]
        traces = {"vout": [3.0, 3.1]}
        gt.save(time, traces)
        
        # Slightly different values within tolerance
        traces2 = {"vout": [3.01, 3.11]}
        ok, errors = gt.compare(time, traces2, tolerances={'voltage': 0.01})
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
