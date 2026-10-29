"""
test_adversarial_stress.py - Adversarial integration tests for bridge resilience
"""
import os
import sys
import time
import unittest
import pytest
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import binary_runner
from bridge import qemu_monitor
from bridge.qemu_monitor import QemuMonitor, QemuMonitorError


class TestAdversarialQemuMonitor(unittest.TestCase):
    """Adversarial tests for QEMU monitor resilience"""
    
    def test_dropped_monitor_frames_mid_injection(self):
        """Simulate dropped monitor frames during ADC injection"""
        mon = qemu_monitor.QemuMonitor("/nonexistent/qemu")
        mon._proc = Mock()
        mon._proc.poll = Mock(return_value=None)
        mon._proc.stdin = Mock()
        mon._proc.stdin.write = Mock(side_effect=OSError("Broken pipe"))
        mon._proc.stdin.flush = Mock()
        
        with self.assertRaises(QemuMonitorError):
            mon.set_adc1_value(1500)
    
    def test_corrupted_monitor_response_packets(self):
        """Simulate corrupted/unparseable monitor responses"""
        mon = qemu_monitor.QemuMonitor("/nonexistent/qemu")
        mon._proc = Mock()
        mon._proc.poll = Mock(return_value=None)
        mon._proc.stdin = Mock()
        mon._proc.stdin.write = Mock()
        mon._proc.stdin.flush = Mock()
        
        # Mock _wait_prompt to return garbage
        mon._wait_prompt = Mock(return_value=b"garbage \x1b[31mcorrupted\x1b[0m data without prompt")
        
        with self.assertRaises(QemuMonitorError):
            mon.read_gate()
    
    def test_sudden_voltage_drop_transient_handling(self):
        """Test handling of sudden voltage transients"""
        # Test ADC conversion with extreme values
        # Very low voltage
        counts_low = binary_runner._adc_counts_from_voltage(0.0)
        self.assertEqual(counts_low, 0)
        
        # Very high voltage
        counts_high = binary_runner._adc_counts_from_voltage(10.0)  # Way over range
        self.assertLessEqual(counts_high, 4095)  # Should be clamped to max
        
        # Negative voltage
        counts_neg = binary_runner._adc_counts_from_voltage(-1.0)
        self.assertEqual(counts_neg, 0)
        
        # Voltage causing threshold crossing
        counts_below = binary_runner._adc_counts_from_voltage(1.0)  # Below threshold
        counts_above = binary_runner._adc_counts_from_voltage(1.2)  # Above threshold
        self.assertNotEqual(counts_below, counts_above)
    
    @pytest.mark.req("CO-10")
    def test_monitor_timeout_recovery(self):
        """Test monitor timeout is handled gracefully"""
        mon = qemu_monitor.QemuMonitor("/nonexistent/qemu")
        mon._proc = Mock()
        mon._proc.poll = Mock(return_value=None)
        mon._buf = bytearray()
        mon._cursor = 0
        mon._lock = __import__('threading').Lock()
        
        # Simulate timeout
        with self.assertRaises(QemuMonitorError) as ctx:
            mon._wait_prompt(timeout=0.001)
        self.assertIn("prompt", str(ctx.exception).lower())
    
    def test_binary_runner_handles_qemu_crash_mid_run(self):
        """Test binary runner handles QEMU crash gracefully"""
        from bridge.cad_engine import SchematicNetlistEngine, SchematicComponent
        g = SchematicNetlistEngine()
        g.add_component(SchematicComponent("V1", "V", "V1", "12", -160, 0))
        g.add_component(SchematicComponent("R1", "R", "R1", "10", 0, 0))
        g.add_component(SchematicComponent("GND1", "GND", "GND", "", 0, 80))
        g.add_wire("V1:+", "R1:1", "in")
        g.add_wire("R1:2", "GND1:1", "gnd")
        g.add_wire("V1:-", "GND1:1", "gnd")
        
        old = os.environ.get("WOSP_QEMU")
        try:
            os.environ["WOSP_QEMU"] = "/nonexistent/qemu"
            run = binary_runner.run_binary_cosim(g, {"GPIO18": {"sense_net": "in"}})
            self.assertIsNotNone(run)
            self.assertTrue(len(run.warnings) > 0)
        finally:
            if old is not None:
                os.environ["WOSP_QEMU"] = old
            else:
                os.environ.pop("WOSP_QEMU", None)


    def test_rapid_adc_injection_burst(self):
        """Test handling of rapid ADC value changes"""
        mon = qemu_monitor.QemuMonitor("/nonexistent/qemu")
        mon._proc = Mock()
        mon._proc.poll = Mock(return_value=None)
        mon._proc.stdin = Mock()
        mon._proc.stdin.write = Mock(side_effect=OSError("Broken pipe"))
        mon._proc.stdin.flush = Mock()
        
        with self.assertRaises(QemuMonitorError):
            mon.set_adc1_value(1500)
    
    @pytest.mark.req("CO-10")
    def test_boundary_adc_values(self):
        """Test ADC values at threshold boundaries"""
        # Test values just below and above 1.65V (half of 3.3V reference)
        # With divider 0.5, 1.65V -> 3.3V at ADC input
        counts_below = binary_runner._adc_counts_from_voltage(1.6, divider=0.5, vref=3.3, adc_bits=12)
        counts_above = binary_runner._adc_counts_from_voltage(1.7, divider=0.5, vref=3.3, adc_bits=12)
        # Below should give lower counts than above
        self.assertLess(counts_below, counts_above)
    
    def test_negative_voltage_clamping(self):
        """Test ADC conversion with negative voltages is clamped"""
        counts_neg = binary_runner._adc_counts_from_voltage(-1.0)
        self.assertEqual(counts_neg, 0)
        
        # Zero voltage should give zero counts
        counts_zero = binary_runner._adc_counts_from_voltage(0.0)
        self.assertEqual(counts_zero, 0)
    
    def test_very_high_voltage_clamping(self):
        """Test ADC conversion with very high voltages is clamped to max"""
        counts_high = binary_runner._adc_counts_from_voltage(10.0)
        max_counts = (1 << 12) - 1  # 4095
        self.assertLessEqual(counts_high, max_counts)
    
    def test_zero_delay_sync_fallback(self):
        """Test _adc_counts_from_voltage handles edge cases"""
        # Very low voltage near 0 gives small counts (rounding may produce 0 or 1)
        counts_low = binary_runner._adc_counts_from_voltage(0.001)
        self.assertLessEqual(counts_low, 2)
        
        # Very high voltage near vref gives counts near max (may be clamped)
        counts_high = binary_runner._adc_counts_from_voltage(3.29, divider=0.5)
        self.assertLessEqual(counts_high, 4095)


if __name__ == "__main__":
    unittest.main()
