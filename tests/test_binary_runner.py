"""
test_binary_runner.py - tests for binary runner (firmware-in-the-loop cosim)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.cad_engine import SchematicNetlistEngine, SchematicComponent
from bridge import binary_runner


class TestBinaryRunner(unittest.TestCase):
    def test_import(self):
        self.assertTrue(callable(binary_runner.run_binary_cosim))
    
    def test_missing_qemu(self):
        g = SchematicNetlistEngine()
        g.add_component(SchematicComponent("V1", "V", "V1", "12", -160, 0))
        g.add_component(SchematicComponent("S1", "SWITCH", "S1", "", 0, 0))
        g.add_component(SchematicComponent("D1", "D", "D1", "", 60, 60))
        g.add_component(SchematicComponent("L1", "L", "L1", "47u", 120, 0))
        g.add_component(SchematicComponent("C1", "C", "C1", "100u", 200, 0))
        g.add_component(SchematicComponent("R1", "R", "R1", "10", 260, 0))
        g.add_component(SchematicComponent("GND1", "GND", "GND", "", 0, 160))
        g.add_component(SchematicComponent("U1", "MCU", "U1", "ESP32", -260, 0))
        g.add_wire("V1:+", "S1:1", "in")
        g.add_wire("V1:-", "GND1:1", "gnd")
        g.add_wire("S1:2", "L1:1", "sw_node")
        g.add_wire("L1:2", "C1:1", "vout")
        g.add_wire("C1:2", "R1:1", "NET_LOAD")
        g.add_wire("R1:2", "GND1:1", "gnd")
        g.add_wire("D1:A", "GND1:1", "gnd")
        g.add_wire("D1:K", "S1:2", "sw_node")
        g.add_wire("U1:GPIO18", "S1:CTRL", "gate")
        
        old = os.environ.get("WOSP_QEMU")
        try:
            os.environ.pop("WOSP_QEMU", None)
            run = binary_runner.run_binary_cosim(g, {"GPIO18": {"sense_net": "vout"}})
            self.assertIn("WOSP_QEMU", " ".join(run.warnings))
        finally:
            if old is not None:
                os.environ["WOSP_QEMU"] = old


class TestReadUntilStable(unittest.TestCase):
    """The gate half of the firmware callback (row R3).

    `_read_until_stable` is what the callback calls between injecting an ADC
    sample and reading the gate back, and nothing covered it before: these
    tests pin the three-reading rule, the timeout fallback and the
    swallowed-read-failure path.
    """

    class _ScriptedGate:
        def __init__(self, values=None, error=None):
            self.values = list(values or [])
            self.error = error
            self.calls = 0

        def read_gate(self):
            self.calls += 1
            if self.error is not None:
                raise self.error
            return self.values[min(self.calls - 1, len(self.values) - 1)]

    def test_waits_for_three_consecutive_identical_readings(self):
        fake = self._ScriptedGate(values=[False, True, True, True])
        out = binary_runner._read_until_stable(
            fake, timeout=2.0, poll_interval=0.001)
        self.assertTrue(out)
        # One flip, then three matching readings: the third match is what
        # ends the poll, so fewer than four reads means it gave up early.
        self.assertGreaterEqual(fake.calls, 4,
                                "returned before the readings had settled")

    def test_returns_the_last_read_when_it_never_settles(self):
        fake = self._ScriptedGate(values=[True, False, True, False])
        out = binary_runner._read_until_stable(
            fake, timeout=0.05, poll_interval=0.001)
        self.assertIsNotNone(out, "the timeout path returns the last read")
        self.assertIsInstance(out, bool)

    def test_a_failing_monitor_read_becomes_none_not_a_crash(self):
        fake = self._ScriptedGate(error=OSError("monitor died"))
        out = binary_runner._read_until_stable(
            fake, timeout=0.05, poll_interval=0.001)
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
