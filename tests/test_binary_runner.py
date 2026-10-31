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
            # Hermetic about the firmware image: a fresh clone has no
            # .pio/build/qemu_flash.bin (gitignored), and run_binary_cosim
            # reports the missing image BEFORE it ever looks at WOSP_QEMU.
            # Measured in the R1 clone install (entry #403): the test then
            # asserted on "firmware image not found" and failed, while the
            # dev tree passed for the wrong reason. A 64-byte stand-in makes
            # the assertion mean what it says in both trees.
            with tempfile.TemporaryDirectory() as td:
                fw = os.path.join(td, "flash.bin")
                with open(fw, "wb") as fh:
                    fh.write(b"\x00" * 64)
                run = binary_runner.run_binary_cosim(
                    g, {"GPIO18": {"sense_net": "vout"}}, firmware_image=fw)
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


class TestDividerSemantics(unittest.TestCase):
    """Q4 pinning: sense_net is the PRE-divider node (vout), so the ADC
    count must be `vout * divider`, matching bridge/control_law.py's
    documented `v_pin = sense_net * divider` and the board's 2:1 divider
    (circuits/buck_converter.cir: Rfb_top vout fb 100k / Rfb_bot fb 0
    100k) with main.c's 12-bit, 3.3 V-referenced ADC.

    With vout forced to exactly 3.3 V the pin sees 1.65 V, i.e. 2048
    counts. The inverted `v_sense / divider` maps the same node to
    6.6 V -> 4095 (clamped), so this test fails on the old arithmetic
    for every vout above 1.65 V.
    """

    def test_firmware_threshold_counts_round_trip_through_the_divider(self):
        """The two main.c thresholds, as voltages, must convert back to the
        same counts.

        main.c compares RAW counts: <1995 turns the gate ON, >2030 turns it
        OFF, on a 12-bit ADC whose 0..4095 counts span 0..3.3 V. So
        1995 counts = 1.6077 V and 2030 counts = 1.6359 V AT THE PIN, which
        through the board's 2:1 divider (Rfb_top/Rfb_bot) is vout = 3.2154 V
        and 3.2718 V. Feeding those sense-node voltages back through the
        conversion must reproduce 1995 and 2030 exactly; the inverted law
        (`v_sense / divider`) turns them into 7985/8124 -> clamped 4095.
        """
        vref, bits, max_counts = 3.3, 12, (1 << 12) - 1
        for counts in (1995, 2030):
            v_pin = counts / max_counts * vref
            vout = v_pin / 0.5
            self.assertAlmostEqual(v_pin,
                                   1.607693 if counts == 1995 else 1.635897,
                                   places=5,
                                   msg="pin voltage for %d counts" % counts)
            self.assertEqual(
                binary_runner._adc_counts_from_voltage(vout, vref=vref,
                                                       divider=0.5,
                                                       adc_bits=bits),
                counts,
                "round trip failed for %d counts (vout=%.6f V)"
                % (counts, vout))
        # The inverted law (`v_sense / divider`) maps those same two
        # sense-node voltages to 7985 and 8124 counts, both clamped to full
        # scale, so it can never land on the firmware's thresholds.
        for counts in (1995, 2030):
            vout = (counts / max_counts * vref) / 0.5
            inverted = int(round((vout / 0.5) / vref * max_counts))
            inverted = max(0, min(max_counts, inverted))
            self.assertEqual(inverted, max_counts,
                             "inverted law should saturate at %d counts "
                             "for vout=%.6f V" % (counts, vout))
            self.assertNotEqual(inverted, counts)

    def test_vout_3v3_reaches_the_adc_as_2048_counts(self):
        run, mon = _run_with_fake_monitor()
        self.assertIsNotNone(mon, "the monitor was never constructed")
        self.assertGreaterEqual(
            run.callback_hits, 1,
            "the external source never called back: %r" % run.warnings)
        self.assertTrue(mon.injected, "no ADC count was ever injected")
        self.assertEqual(mon.injected[-1], 2048,
                         "last injected count for vout=3.3 V: %r"
                         % (mon.injected[-5:],))
        self.assertNotIn(4095, mon.injected,
                         "3.3 V through a 0.5 divider must never clamp")


if __name__ == "__main__":
    unittest.main()
