"""
test_cosim_control.py - closed-loop MCU co-simulation.

The point of these tests is that the firmware-derived control loop really runs
inside the solver:

1. control-law spec validation and normalisation
2. importing a law from a real firmware C source (its own ADC constants)
3. the netlist emitting an `external` source for a law pin
4. end-to-end: a buck built from a schematic regulates because the pin reacts
   to the *simulated* feedback net, and the load changes the switching rate
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import control_law, cosim_runner
from bridge.cad_engine import SchematicComponent, SchematicNetlistEngine

FIRMWARE_MAIN_C = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "firmware", "esp32_buck_controller", "src", "main.c")


def build_buck(load_ohms="5", l_value="47u", c_value="100u"):
    """
    12 V -> 3.3 V hysteretic buck, exactly as the netlist compiler sees it:

        V1 -> S1(switch, gate from U1.GPIO18) -> L1 -> vout -> C1 || Rload
        D1 freewheels from sw_node to ground
    """
    g = SchematicNetlistEngine()
    g.add_component(SchematicComponent("V1", "V", "V1", "12", -160, 0))
    g.add_component(SchematicComponent("S1", "SWITCH", "S1", "", 0, 0))
    g.add_component(SchematicComponent("D1", "D", "D1", "", 60, 60))
    g.add_component(SchematicComponent("L1", "L", "L1", l_value, 120, 0))
    g.add_component(SchematicComponent("C1", "C", "C1", c_value, 200, 0))
    g.add_component(SchematicComponent("R1", "R", "R1", load_ohms, 260, 0))
    g.add_component(SchematicComponent("GND1", "GND", "GND", "", 0, 160))
    g.add_component(SchematicComponent("U1", "MCU", "U1", "ESP32", -260, 0))

    g.add_wire("V1:+", "S1:1", "in")
    g.add_wire("V1:-", "GND1:1", "gnd")
    g.add_wire("S1:2", "L1:1", "sw_node")
    g.add_wire("L1:2", "C1:1", "vout")
    g.add_wire("C1:2", "R1:1", "NET_LOAD")      # deliberately not "vout":
    g.add_wire("R1:2", "GND1:1", "gnd")          # sharing that label would short C1
    g.add_wire("D1:A", "GND1:1", "gnd")
    g.add_wire("D1:K", "S1:2", "sw_node")
    g.add_wire("U1:GPIO18", "S1:CTRL", "gate")
    return g


def firmware_law(sense_net="vout"):
    """The control law the real firmware in this repo describes."""
    return control_law.law_from_firmware_source_exact(
        FIRMWARE_MAIN_C, sense_net, divider=1.0)


class TestControlLawSpec(unittest.TestCase):
    def test_hysteretic_counts_come_from_target_and_hysteresis(self):
        law = control_law.make_law({
            "kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
            "target_v": 3.3, "hysteresis_v": 0.165, "divider": 0.5,
            "vref": 3.3, "adc_bits": 12})
        # (3.3 -+ 0.165) V through a 0.5 divider, 12-bit over a 3.3 V reference
        self.assertEqual(law.spec["low_counts"], 1945)
        self.assertEqual(law.spec["high_counts"], 2150)
        self.assertLess(law.low_counts, law.high_counts)

    def test_explicit_counts_are_preserved_verbatim(self):
        law = control_law.make_law({
            "kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
            "target_v": 1.0, "hysteresis_v": 0.01, "low_counts": 1995,
            "high_counts": 2030})
        self.assertEqual((law.low_counts, law.high_counts), (1995, 2030))

    def test_rejects_nonsense(self):
        base = {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout"}
        bad = [
            dict(base, kind="sine"),
            {**base, "hysteresis_v": 0},                       # no dead band
            {**base, "target_v": 1.0, "hysteresis_v": 2.0},    # band > target
            {**base, "vhigh": 99},
            {**base, "divider": 0},
            {**base, "low_counts": 3000, "high_counts": 100},
            {**base, "adc_bits": 40},
            {"kind": "hysteretic", "sense_net": "vout"},       # no pin
            {"kind": "hysteretic", "pin": "GPIO18"},           # no sense net
            {"kind": "pwm", "pin": "P1", "sense_net": "vout", "carrier_hz": 0},
        ]
        for spec in bad:
            with self.subTest(spec=spec):
                with self.assertRaises(control_law.ControlLawError):
                    control_law.normalize_law(spec)

    def test_describe_never_raises_on_junk(self):
        self.assertIn("invalid", control_law.describe_law({"kind": "banana"}))


class TestHystereticDecision(unittest.TestCase):
    """The decision table, checked directly at the counts boundary."""

    def setUp(self):
        self.law = control_law.make_law({
            "kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
            "target_v": 3.3, "hysteresis_v": 0.165, "divider": 0.5})
        self.lsb = 3.3 / 4095.0

    def counts_for(self, volts):
        return control_law._to_counts(volts * 0.5, 3.3, 12)

    def test_below_band_drives_high(self):
        below = self.counts_for(3.3 - 0.5)
        self.assertLess(below, self.law.low_counts)
        self.assertTrue(self.law.decide(below))

    def test_above_band_drives_low(self):
        above = self.counts_for(3.3 + 0.5)
        self.assertGreater(above, self.law.high_counts)
        self.assertFalse(self.law.decide(above))

    def test_inside_band_holds_previous_state(self):
        inside = (self.law.low_counts + self.law.high_counts) // 2
        self.law.level = True
        self.assertTrue(self.law.decide(inside))
        self.law.level = False
        self.assertFalse(self.law.decide(inside))

    def test_update_counts_switches_only_on_a_level_change(self):
        low = self.counts_for(0.0)
        high = self.counts_for(5.0)
        self.assertEqual(self.law.update(0.0, 0.0), 3.3)      # LOW counts -> HIGH
        self.assertEqual(self.law.switch_count, 1)
        self.assertEqual(self.law.update(5.0, 1e-6), 0.0)     # HIGH counts -> LOW
        self.assertEqual(self.law.switch_count, 2)
        self.law.update(5.0, 2e-6)                            # hold LOW
        self.assertEqual(self.law.switch_count, 2)
        # 0 V sense reads as 0 counts; 5 V through the 0.5 divider saturates nothing
        self.assertEqual(low, 0)
        self.assertEqual(high, 3102)


class TestFirmwareImport(unittest.TestCase):
    def test_reads_thresholds_and_gate_pin_from_real_source(self):
        consts = control_law.read_firmware_constants(FIRMWARE_MAIN_C)
        self.assertEqual(consts["pin"], "GPIO18")
        self.assertEqual(consts["low"], 1995)
        self.assertEqual(consts["high"], 2030)

    def test_imported_spec_keeps_the_file_counts(self):
        spec = firmware_law()
        self.assertEqual(spec["pin"], "GPIO18")
        self.assertEqual(spec["source"], "main.c")
        self.assertEqual(control_law.normalize_law(spec)["low_counts"], 1995)
        self.assertEqual(control_law.normalize_law(spec)["high_counts"], 2030)

    def test_missing_file_and_missing_constants_are_reported(self):
        with self.assertRaises(control_law.ControlLawError):
            control_law.read_firmware_constants("does/not/exist.c")
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "empty.c")
        with open(path, "w") as f:
            f.write("int main(void) { return 0; }\n")
        with self.assertRaises(control_law.ControlLawError) as ctx:
            control_law.read_firmware_constants(path)
        self.assertIn("ADC_LOW_THRESHOLD", str(ctx.exception))

    def test_inverted_thresholds_are_rejected(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "bad.c")
        with open(path, "w") as f:
            f.write("#define ADC_LOW_THRESHOLD 3000\n"
                    "#define ADC_HIGH_THRESHOLD 100\n"
                    "#define GATE_PIN GPIO_NUM_4\n")
        with self.assertRaises(control_law.ControlLawError):
            control_law.read_firmware_constants(path)


class TestNetlistEmission(unittest.TestCase):
    def test_law_pin_becomes_an_external_source(self):
        g = build_buck()
        g.control_laws["U1"] = firmware_law()
        lines, _nets, warns = g.compile_netlist()

        self.assertEqual(warns, [], warns)
        self.assertIn("VU1_GPIO18 gate 0 external", lines)
        self.assertTrue(any("CONTROL LAW" in l for l in lines))
        # The open-loop profile path must not also emit a waveform for that pin.
        self.assertFalse(any(l.startswith("VU1_GPIO18") and "PULSE" in l for l in lines))

    def test_law_targeting_an_unwired_pin_is_warned_not_hidden(self):
        g = build_buck()
        spec = firmware_law()
        spec["pin"] = "GPIO17"                 # not wired in build_buck()
        g.control_laws["U1"] = spec
        _lines, _nets, warns = g.compile_netlist()
        self.assertTrue(any("GPIO17" in w and "not wired" in w for w in warns), warns)

    def test_laws_survive_save_and_reload(self):
        g = build_buck()
        g.control_laws["U1"] = firmware_law()
        restored = SchematicNetlistEngine()
        restored.load_dict(g.to_dict())
        self.assertEqual(restored.control_laws["U1"]["source_counts"]["low"], 1995)

    def test_clear_removes_the_law(self):
        g = build_buck()
        g.control_laws["U1"] = firmware_law()
        self.assertIn("VU1_GPIO18 gate 0 external", g.compile_netlist()[0])

        g.control_laws.clear()
        self.assertEqual(g.control_laws, {})
        lines, _nets, _warns = g.compile_netlist()
        # No longer solver-driven; it falls back to the declared-profile path,
        # which idles an unprofiled pin LOW rather than floating it.
        mcu_lines = [l for l in lines if l.startswith("VU1_GPIO18")]
        self.assertEqual(mcu_lines, ["VU1_GPIO18 gate 0 DC 0"])
        self.assertFalse(any("CONTROL LAW" in l for l in lines))


class TestCosimEndToEnd(unittest.TestCase):
    """The real thing: a schematic regulated by a firmware-derived loop."""

    def test_buck_regulates_from_simulated_feedback(self):
        g = build_buck(load_ohms="5")
        spec = firmware_law()
        g.control_laws["U1"] = spec
        run = cosim_runner.run_cosim(g, {"GPIO18": spec},
                                      tstep_us=0.5, duration_ms=5.0)

        self.assertEqual(run.warnings, [], run.warnings)
        self.assertGreater(run.callback_hits, 1000, "control law never ran")

        law = run.laws["GPIO18"]
        self.assertGreater(law.switch_count, 20,
                           "pin never switched - not a closed loop")

        # Steady-state output must sit near the firmware's own target
        # (2048 counts of 3.3 V over a 1x divider = 1.6506 V).
        vout = run.traces.get("vout")
        self.assertIsNotNone(vout, "no vout trace")
        tail = vout[len(vout) // 2:]
        mean = sum(tail) / len(tail)
        self.assertAlmostEqual(mean, 1.62, delta=0.12,
                               msg=f"vout mean {mean:.4f} V off target")

        reg = run.regulation("GPIO18")
        self.assertLess(abs(reg["mean_error_counts"]), 200, reg)

    def test_output_is_regulated_across_a_load_sweep(self):
        """
        A load-aware loop, not a replayed waveform.

        Across a 10x load change the output must stay on target, and the pin's
        duty cycle must move - which can only happen if the pin is reacting to
        the circuit it is switching.
        """
        results = {}
        for load in ("5", "1.5", "0.5"):
            g = build_buck(load_ohms=load)
            spec = firmware_law()
            g.control_laws["U1"] = spec
            run = cosim_runner.run_cosim(g, {"GPIO18": spec},
                                          tstep_us=0.5, duration_ms=5.0)
            self.assertEqual(run.warnings, [], run.warnings)
            vout = run.traces["vout"]
            tail = vout[len(vout) // 2:]
            results[load] = (sum(tail) / len(tail),
                             run.laws["GPIO18"].stats()["duty"])

        for load, (mean, duty) in results.items():
            self.assertAlmostEqual(mean, 1.62, delta=0.10,
                                   msg=f"load {load}: vout {mean:.4f} V off target")
        # Heavier loading damps the tank, so the loop spends less time charging.
        self.assertGreater(results["5"][1], results["0.5"][1],
                           f"duty did not respond to load: {results}")

    def test_output_follows_the_requested_target(self):
        """
        Retuning the firmware's thresholds must move the operating point. A
        loop that ignored its thresholds could not do this.
        """
        means = {}
        for counts, expected in ((1024, 0.83), (3072, 2.48)):
            g = build_buck()
            spec = firmware_law()
            spec["low_counts"] = counts
            spec["high_counts"] = counts + 40
            spec.pop("source_counts", None)
            g.control_laws["U1"] = spec
            run = cosim_runner.run_cosim(g, {"GPIO18": spec},
                                          tstep_us=0.5, duration_ms=5.0)
            self.assertEqual(run.warnings, [], run.warnings)
            vout = run.traces["vout"]
            tail = vout[len(vout) // 2:]
            means[counts] = sum(tail) / len(tail)
            self.assertAlmostEqual(means[counts], expected, delta=0.12,
                                   msg=f"counts {counts}: vout {means[counts]:.4f} V")
        self.assertGreater(means[3072], means[1024])

    def test_unwired_law_pin_is_reported_rather_than_faked(self):
        g = build_buck()
        spec = firmware_law()
        spec["pin"] = "GPIO17"
        run = cosim_runner.run_cosim(g, {"GPIO17": spec}, tstep_us=1.0,
                                      duration_ms=1.0)
        self.assertTrue(any("external" in w for w in run.warnings), run.warnings)
        self.assertEqual(run.laws["GPIO17"].history_counts, [])

    def test_rejected_spec_yields_a_warning_not_a_crash(self):
        g = build_buck()
        run = cosim_runner.run_cosim(g, {"GPIO18": {"kind": "hysteretic"}},
                                      tstep_us=1.0, duration_ms=1.0)
        self.assertTrue(any("rejected" in w for w in run.warnings), run.warnings)
        self.assertEqual(run.laws, {})


class TestPwmLaw(unittest.TestCase):
    def test_duty_grows_as_feedback_falls(self):
        law = control_law.make_law({
            "kind": "pwm", "pin": "PWM0", "sense_net": "vout",
            "target_v": 3.3, "carrier_hz": 1000, "duty_gain": 0.5})
        low_error = None
        high_error = None
        for i in range(2000):
            law.update(3.0, i * 1e-7)         # close to target
            low_error = law.duty
            law.update(0.5, i * 1e-7)         # far below target
            high_error = law.duty
        self.assertGreater(high_error, low_error)
        self.assertLessEqual(high_error, 1.0)
        self.assertGreaterEqual(low_error, 0.0)

    def test_duty_saturates_rather_than_exceeding_one(self):
        law = control_law.make_law({
            "kind": "pwm", "pin": "PWM0", "sense_net": "vout",
            "target_v": 3.3, "duty_gain": 100.0})
        law.update(0.0, 0.0)
        self.assertLessEqual(law.duty, 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)