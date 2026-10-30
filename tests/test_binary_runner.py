"""
test_binary_runner.py - tests for binary runner (firmware-in-the-loop cosim)
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import control_law
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


class _RecordingMonitor(object):
    """Stand-in for bridge.qemu_monitor.QemuMonitor: no process, instant
    answers, every injected ADC count recorded."""

    def __init__(self, qemu=None, machine=None, **kw):
        self.injected = []
        self.gate = True

    def _reader_loop(self):
        return

    def _wait_prompt(self, timeout=None):
        return

    def set_adc1_value(self, counts):
        self.injected.append(int(counts))

    def read_gate(self):
        return self.gate

    def stop(self):
        return


def _forced_3v3_graph():
    """A schematic whose vout is a hard 3.3 V source, with a control law on
    GPIO18 so the netlist carries an `external` source and the cosim
    callback fires on every solver step. vout is therefore known exactly:
    3.3 V into the board's 2:1 divider is 1.65 V at the ADC pin, i.e. 2048
    counts (netlist Rfb_top/Rfb_bot, firmware 12-bit/3.3 V reference)."""
    g = SchematicNetlistEngine()
    g.add_component(SchematicComponent("V1", "V", "V1", "3.3", -160, 0))
    g.add_component(SchematicComponent("R1", "R", "R1", "10", 0, 0))
    g.add_component(SchematicComponent("R2", "R", "R2", "10k", 0, 160))
    g.add_component(SchematicComponent("GND1", "GND", "GND", "", 0, 80))
    g.add_component(SchematicComponent("U1", "MCU", "U1", "ESP32", -260, 0))
    g.add_wire("V1:+", "R1:1", "vout")
    g.add_wire("V1:-", "GND1:1", "gnd")
    g.add_wire("R1:2", "GND1:1", "gnd")
    g.add_wire("U1:GPIO18", "R2:1", "gate")
    g.add_wire("R2:2", "GND1:1", "gnd")
    g.control_laws["U1"] = control_law.make_law({
        "kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
        "target_v": 3.3, "hysteresis_v": 0.165, "divider": 0.5,
        "vref": 3.3, "adc_bits": 12}).spec
    return g


def _run_with_fake_monitor(pin_specs=None):
    """Run run_binary_cosim end-to-end with a fake firmware + fake monitor.

    Returns (run, monitor). The monitor is patched at binary_runner's own
    import site, so line `mon = QemuMonitor(...)` gets the recorder."""
    graph = _forced_3v3_graph()
    holder = {}
    real = binary_runner.QemuMonitor

    def factory(*a, **kw):
        m = _RecordingMonitor(*a, **kw)
        holder["mon"] = m
        return m

    binary_runner.QemuMonitor = factory
    try:
        with tempfile.TemporaryDirectory() as td:
            fw = os.path.join(td, "flash.bin")
            with open(fw, "wb") as fh:
                fh.write(b"\x00" * 64)
            qcmd = os.path.join(td, "fake-qemu.cmd")
            with open(qcmd, "w") as fh:
                fh.write("@echo off\r\nexit /b 0\r\n")
            run = binary_runner.run_binary_cosim(
                graph,
                pin_specs if pin_specs is not None
                else {"GPIO18": {"sense_net": "vout"}},
                firmware_image=fw, qemu=qcmd,
                duration_ms=0.1, sync_poll_interval=0.001,
                sync_poll_timeout=0.05)
    finally:
        binary_runner.QemuMonitor = real
    return run, holder.get("mon")


class TestLaunchPath(unittest.TestCase):
    """Job A (Q3 red-to-green): the QEMU spawn line must reference
    `subprocess`. Today line 128 says `subsubprocess.DEVNULL`, raising
    NameError inside the launcher's own try block; the exception is
    swallowed into a warning, so the run silently stops before the monitor
    ever exists. No test reached that line (all previous tests bail on a
    missing image or a missing WOSP_QEMU)."""

    def test_spawn_line_does_not_name_error(self):
        run, _mon = _run_with_fake_monitor()
        bad = [w for w in run.warnings
               if "subsubprocess" in w or "is not defined" in w]
        self.assertEqual(bad, [],
                         "the QEMU launch died on a NameError: %r" % bad)


if __name__ == "__main__":
    unittest.main()
