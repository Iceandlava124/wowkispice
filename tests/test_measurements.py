"""
test_measurements.py - waveform analysis and post-simulation metrics.

Two layers are checked:

1. Pure functions over synthetic arrays, where the expected answer is known
   analytically (cursors, stats, settling time, FFT of a known tone, THD of a
   known waveform, Bode of a known RC).
2. The same analysis driven through a real ngspice run, to prove the plumbing
   - not just the maths - is wired correctly.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import analysis_runner, measurements
from bridge.cad_engine import SchematicComponent, SchematicNetlistEngine
from bridge.ngspice_wrapper import NgSpiceEngine


def sine(freq, amp=1.0, duration=0.02, step=1e-5):
    n = int(duration / step) + 1
    times = [i * step for i in range(n)]
    values = [amp * math.sin(2 * math.pi * freq * t) for t in times]
    return times, values


def square(freq, amp=1.0, duty=0.5, duration=0.02, step=1e-5):
    n = int(duration / step) + 1
    times = [i * step for i in range(n)]
    values = [amp if ((t * freq) % 1.0) < duty else 0.0 for t in times]
    return times, values


def rc_schematic(r_value="1k", c_value="100n"):
    """V - R - C low-pass. -3 dB corner is 1/(2*pi*R*C)."""
    g = SchematicNetlistEngine()
    g.add_component(SchematicComponent("V1", "V", "V1", "1", -100, 0))
    g.add_component(SchematicComponent("R1", "R", "R1", r_value, 0, 0))
    g.add_component(SchematicComponent("C1", "C", "C1", c_value, 100, 0))
    g.add_component(SchematicComponent("GND1", "GND", "GND", "", 0, 100))
    g.add_wire("V1:+", "R1:1", "in")
    g.add_wire("V1:-", "GND1:1", "gnd")
    g.add_wire("R1:2", "C1:1", "out")
    g.add_wire("C1:2", "GND1:1", "gnd")
    return g


class TestCursors(unittest.TestCase):
    def test_sample_at_interpolates_between_points(self):
        times = [0.0, 1.0, 2.0, 3.0]
        values = [0.0, 10.0, 20.0, 30.0]
        self.assertAlmostEqual(measurements.sample_at(times, values, 0.5), 5.0)
        self.assertAlmostEqual(measurements.sample_at(times, values, 1.25), 12.5)

    def test_sample_at_clamps_outside_the_window(self):
        times = [0.0, 1.0]
        values = [3.0, 9.0]
        self.assertEqual(measurements.sample_at(times, values, -5.0), 3.0)
        self.assertEqual(measurements.sample_at(times, values, 99.0), 9.0)
        self.assertIsNone(measurements.sample_at(times, values, -5.0, clamp=False))
        self.assertIsNone(measurements.sample_at(times, values, 99.0, clamp=False))

    def test_readout_reports_dt_dv_and_reciprocals(self):
        times = [0.0, 1e-3, 2e-3]
        values = [0.0, 1.0, 4.0]
        r = measurements.cursor_readout(times, values, 0.0, 0.0, 1e-3, 1.0)
        self.assertAlmostEqual(r["dt"], 1e-3)
        self.assertAlmostEqual(r["dv"], 1.0)
        self.assertAlmostEqual(r["inv_dt"], 1000.0)
        self.assertAlmostEqual(r["inv_dv"], 1.0)
        self.assertAlmostEqual(r["slope"], 1000.0)

    def test_single_cursor_has_no_differences(self):
        times = [0.0, 1.0]
        values = [0.0, 1.0]
        r = measurements.cursor_readout(times, values, 0.5)
        self.assertAlmostEqual(r["t1"], 0.5)
        self.assertIsNone(r.get("inv_dt"))
        self.assertIsNone(r.get("dt"))

    def test_empty_trace_is_reported_not_crashed(self):
        r = measurements.cursor_readout([], [], 0, 0)
        self.assertIsNone(r["t1"])
        self.assertIn("no trace", measurements.format_readout(r))

    def test_format_is_human_readable(self):
        times = [0.0, 1e-3]
        values = [0.0, 1.0]
        text = measurements.format_readout(
            measurements.cursor_readout(times, values, 0.0, 0.0, 1e-3, 1.0))
        self.assertIn("t1=", text)
        self.assertIn("1/dt=", text)
        self.assertIn("1kHz", text)


class TestTraceStats(unittest.TestCase):
    def test_mean_rms_and_peak_to_peak(self):
        times, values = sine(1000.0, amp=2.0, duration=0.02)
        s = measurements.trace_stats(times, values)
        self.assertAlmostEqual(s["mean"], 0.0, delta=0.01)
        self.assertAlmostEqual(s["rms"], 2.0 / math.sqrt(2), delta=0.02)
        self.assertAlmostEqual(s["p2p"], 4.0, delta=0.05)

    def test_duty_is_measured_against_a_threshold(self):
        times, values = square(1000.0, duty=0.25)
        s = measurements.trace_stats(times, values, threshold=0.5)
        self.assertAlmostEqual(s["duty"], 0.25, delta=0.01)

    def test_empty_trace_does_not_divide_by_zero(self):
        s = measurements.trace_stats([], [])
        self.assertEqual(s["points"], 0)
        self.assertIsNone(s["mean"])

    def test_settling_time_finds_the_entry_point(self):
        # Charges toward 5 V with tau = 1 ms; 2% band entered at ~3.9 tau.
        step = 1e-6
        tau = 1e-3
        times = [i * step for i in range(int(0.02 / step))]
        values = [5.0 * (1 - math.exp(-t / tau)) for t in times]
        settled = measurements.settling_time(times, values, 5.0, tolerance=0.02)
        self.assertIsNotNone(settled)
        self.assertAlmostEqual(settled, -tau * math.log(0.02), delta=0.2e-3)

    def test_settling_time_is_none_when_it_never_settles(self):
        times = [i * 1e-6 for i in range(100)]
        values = [t * 1000 for t in times]        # a ramp: never settles
        self.assertIsNone(measurements.settling_time(times, values, 1.0))

    def test_rise_fall_time_scales_with_the_actual_amplitude(self):
        times = [i * 1e-6 for i in range(2000)]
        values = [0.0 if t < 1e-3 else 5.0 for t in times]
        r = measurements.rise_fall_time(times, values, 0.0, 5.0, fraction=0.5)
        # 50% threshold is crossed exactly at the 1 ms edge.
        self.assertAlmostEqual(r["rise_s"], 1e-3, delta=2e-6)


class TestFft(unittest.TestCase):
    def test_dominant_frequency_of_a_pure_tone(self):
        times, values = sine(1000.0, duration=0.05, step=1e-5)
        out = measurements.fft_spectrum(times, values)
        self.assertAlmostEqual(out["dominant_hz"], 1000.0, delta=5.0)

    def test_pure_tone_has_negligible_thd(self):
        """The classic false-positive: leakage counted as distortion."""
        times, values = sine(1000.0, duration=0.05, step=1e-5)
        out = measurements.fft_spectrum(times, values)
        thd = measurements.thd(out["freqs"], out["magnitude"], 1000.0)
        self.assertIsNotNone(thd)
        self.assertLess(thd, 0.005, f"pure sine reported {thd * 100:.3f}% THD")

    def test_square_wave_thd_matches_theory(self):
        """
        An ideal 50% square wave has THD = sqrt(1/9 + 1/25 + 1/49 + ...) ~ 0.49.
        A finite number of sampled edges keeps it a little below that.
        """
        times, values = square(1000.0, duty=0.5, duration=0.05, step=1e-5)
        out = measurements.fft_spectrum(times, values)
        thd = measurements.thd(out["freqs"], out["magnitude"], 1000.0)
        self.assertAlmostEqual(thd, 0.4937, delta=0.12)

    def test_quarter_duty_is_worse_than_half(self):
        times_a, val_a = square(1000.0, duty=0.5, duration=0.05, step=1e-5)
        times_b, val_b = square(1000.0, duty=0.25, duration=0.05, step=1e-5)
        a = measurements.fft_spectrum(times_a, val_a)
        b = measurements.fft_spectrum(times_b, val_b)
        thd_a = measurements.thd(a["freqs"], a["magnitude"], 1000.0)
        thd_b = measurements.thd(b["freqs"], b["magnitude"], 1000.0)
        self.assertGreater(thd_b, thd_a)

    def test_too_short_a_trace_reports_empty_rather_than_failing(self):
        out = measurements.fft_spectrum([0.0, 1e-6], [0.0, 1.0])
        self.assertEqual(out["freqs"], [])
        self.assertIsNone(out["dominant_hz"])

    def test_unknown_window_is_rejected(self):
        times, values = sine(1000.0, duration=0.01, step=1e-5)
        with self.assertRaises(ValueError):
            measurements.fft_spectrum(times, values, window="gaussian")


class TestBodeMaths(unittest.TestCase):
    def test_rc_response_matches_analytic_gain_and_phase(self):
        """First-order low-pass: |H| = 1/sqrt(1+(wRC)^2), phase = -atan(wRC)."""
        freqs = [10.0, 100.0, 1000.0, 10000.0, 100000.0]
        rc = 1e-4                       # R*C for 1k and 100n, in seconds
        corner = 1.0 / (2 * math.pi * rc)
        self.assertAlmostEqual(corner, 1591.55, delta=0.01)
        re = [1.0 / math.sqrt(1 + (2 * math.pi * f * rc) ** 2) for f in freqs]
        im = [0.0] * len(freqs)
        out = measurements.bode_from_ac(freqs, re, im)
        self.assertAlmostEqual(out["gain_db"][0], 0.0, delta=0.01)
        expected = 20 * math.log10(1.0 / math.sqrt(1 + (2 * math.pi * 10000 * rc) ** 2))
        self.assertAlmostEqual(out["gain_db"][3], expected, delta=0.01)

    def test_phase_is_unwrapped_across_the_negative_axis(self):
        freqs = [1.0, 2.0, 3.0]
        re = [1.0, -1.0, 1.0]
        im = [1.0, 1e-9, -1.0]           # crosses behind the origin
        out = measurements.bode_from_ac(freqs, re, im)
        spread = max(out["phase_deg"]) - min(out["phase_deg"])
        self.assertLess(spread, 360.0, f"phase jumped {spread} deg: {out['phase_deg']}")

    def test_passive_filter_reports_no_phase_margin_rather_than_a_fake_one(self):
        out = measurements.phase_margin([1.0, 100.0], [-0.1, -20.0], [-5.0, -80.0])
        self.assertIsNone(out["phase_margin_deg"])
        self.assertIsNone(out["crossover_hz"])


class TestPowerMetrics(unittest.TestCase):
    def test_efficiency_of_a_halving_regulator(self):
        m = measurements.power_metrics(12.0, 0.275, 3.3, 1.0)
        self.assertAlmostEqual(m["efficiency"], 3.3 / 3.3, delta=0.02)
        self.assertGreater(m["loss_w"], 0)

    def test_impossible_efficiency_is_refused(self):
        m = measurements.power_metrics(3.3, 1.0, 12.0, 1.0)     # a gain, not a reg
        self.assertIsNone(m["efficiency"])
        self.assertIsNotNone(m["loss_w"])

    def test_series_current_from_ohms_law(self):
        currents = measurements.series_current([0.0, 1.0], [5.0, 10.0], 1000.0)
        self.assertAlmostEqual(currents[0], 0.005)
        self.assertAlmostEqual(currents[1], 0.01)


class TestAgainstRealSolver(unittest.TestCase):
    """The analysis must work on data a real solver produced."""

    def _run(self, model, **kwargs):
        lines, _nets, warns = model.compile_netlist(**kwargs)
        engine = NgSpiceEngine(verbose=False)
        engine.load_circuit(lines)
        engine.cmd("run")
        return engine, warns

    def test_fft_of_a_real_1khz_source(self):
        g = SchematicNetlistEngine()
        g.add_component(SchematicComponent("V1", "V", "V1", "SIN(0 1 1k)", -100, 0))
        g.add_component(SchematicComponent("R1", "R", "R1", "1k", 0, 0))
        g.add_component(SchematicComponent("GND1", "GND", "GND", "", 0, 100))
        g.add_wire("V1:+", "R1:1", "out")
        g.add_wire("V1:-", "GND1:1", "gnd")
        g.add_wire("R1:2", "GND1:1", "gnd")

        engine, _ = self._run(g, tstep_us=0.5, duration_ms=10.0)
        out = analysis_runner.run_fft(engine, "out")
        self.assertAlmostEqual(out["dominant_hz"], 1000.0, delta=10.0)
        self.assertLess(out["thd"], 0.01, f"pure source THD {out['thd']}")

    def test_bode_of_a_real_rc_matches_theory(self):
        g = rc_schematic("1k", "100n")
        out = analysis_runner.run_bode(g, "out", start_hz=10.0, stop_hz=1e5,
                                       points_per_decade=50)
        # At 100 kHz the analytic gain is 1/(2*pi*f*R*C) = -35.96 dB.
        idx = min(range(len(out["freqs"])),
                  key=lambda i: abs(out["freqs"][i] - 1e5))
        self.assertAlmostEqual(out["gain_db"][idx], -35.96, delta=0.3)
        # At the corner the phase must be ~-45 degrees.
        corner = 1.0 / (2 * math.pi * 1000 * 100e-9)
        idx = min(range(len(out["freqs"])),
                  key=lambda i: abs(out["freqs"][i] - corner))
        self.assertAlmostEqual(out["phase_deg"][idx], -45.0, delta=3.0)

    def test_ac_analysis_emits_an_ac_card_and_stamps_the_source(self):
        g = rc_schematic()
        lines, _nets, _warns = g.compile_netlist(analysis="ac", ac_start_hz=1.0,
                                                 ac_stop_hz=1e5)
        self.assertTrue(any(".ac " in l for l in lines), lines)
        self.assertTrue(any("AC 1" in l for l in lines if l.startswith("V1")), lines)
        self.assertFalse(any(l.startswith(".tran") for l in lines), lines)

    def test_unknown_analysis_is_rejected(self):
        # "noise" used to be the example of an unknown analysis; it is now a
        # real supported mode (wired in the analysis-mode audit pass), so the
        # rejection check uses an analysis that genuinely does not exist.
        with self.assertRaises(ValueError):
            rc_schematic().compile_netlist(analysis="fourier")

    def test_noise_and_disto_cards_compile(self):
        g = rc_schematic()
        lines, _nets, _warns = g.compile_netlist(
            analysis="noise", noise_output_net="out",
            ac_start_hz=10.0, ac_stop_hz=1e5)
        self.assertTrue(any(l.startswith(".noise V(out) ") for l in lines),
                        lines)
        self.assertFalse(any(l.startswith(".tran") for l in lines), lines)
        self.assertTrue(any("AC 1" in l for l in lines
                            if l.startswith("V1")), lines)
        # .noise without a target net must fail loudly, not guess one.
        with self.assertRaises(ValueError):
            rc_schematic().compile_netlist(analysis="noise")

        lines, _nets, _warns = g.compile_netlist(
            analysis="disto", ac_start_hz=100.0, ac_stop_hz=1e5)
        self.assertTrue(any(l.startswith(".disto dec ") for l in lines),
                        lines)
        self.assertTrue(any(l.startswith(".ac dec") for l in lines), lines)
        self.assertTrue(any("distof1" in l for l in lines), lines)
        self.assertFalse(any(l.startswith(".tran") for l in lines), lines)

    def test_missing_vector_is_reported_not_silently_empty(self):
        g = rc_schematic()
        with self.assertRaises(analysis_runner.AnalysisError):
            analysis_runner.run_bode(g, "no_such_net", start_hz=10.0, stop_hz=1e4)


class TestStepMetrics(unittest.TestCase):
    """step_metrics against answers known analytically."""

    def test_analytic_rc_step(self):
        tau = 1e-3
        n = 2001
        times = [i * 5e-6 for i in range(n)]           # 0 .. 10 ms = 10 tau
        values = [1.0 - math.exp(-t / tau) for t in times]
        m = measurements.step_metrics(times, values)
        self.assertEqual(m["direction"], "rising")
        self.assertAlmostEqual(m["v_final"], 1.0, delta=0.01)
        # 50% crossing of an exponential RC step is tau*ln2 ...
        self.assertAlmostEqual(m["delay_s"], tau * math.log(2.0),
                               delta=0.01 * tau)
        # ... and its 10-90% rise time is tau*ln9.
        self.assertAlmostEqual(m["rise_s"], tau * math.log(9.0),
                               delta=0.05 * tau)
        self.assertLess(m["overshoot_pct"], 1.0,
                        "monotonic rise must not report overshoot")
        self.assertLess(m["undershoot_pct"], 1.0,
                        "a monotonic rise must not report its own approach "
                        "as undershoot")
        # enters the +/-2% band at tau*ln(50) and stays there.
        self.assertAlmostEqual(m["settling_s"], tau * math.log(50.0),
                               delta=0.1 * tau)
        # slew is the same 80% swing over the sampled 10-90% rise; linear
        # interpolation on an exponential lands a hair off the identity.
        self.assertAlmostEqual(m["slew_v_ms"], 0.8 / (m["rise_s"] * 1000.0),
                               delta=1e-4)

    def test_ringy_step_reports_overshoot(self):
        tau = 1e-3
        n = 3001
        times = [i * 5e-6 for i in range(n)]           # 0 .. 15 ms
        values = []
        for t in times:
            if t < 3 * tau:
                values.append(1.0 - math.exp(-t / tau))
            elif 4 * tau <= t < 4.2 * tau:
                values.append(1.25)                    # 25% bump on plateau
            else:
                values.append(1.0)
        m = measurements.step_metrics(times, values)
        self.assertAlmostEqual(m["overshoot_pct"], 25.0, delta=1.0)
        self.assertLess(m["undershoot_pct"], 1.0)
        self.assertIsNotNone(m["settling_s"])

    def test_flat_trace_reports_no_step(self):
        times = [i * 1e-5 for i in range(50)]
        m = measurements.step_metrics(times, [2.5] * 50)
        self.assertIsNone(m["direction"])
        self.assertIsNone(m["delay_s"])
        self.assertIsNone(m["settling_s"])


class TestNoiseAndYield(unittest.TestCase):
    """Noise analysis and per-schematic Monte Carlo against the real solver."""

    def test_noise_matches_resistor_thermal_noise(self):
        """RC low-pass: output noise density at DC must equal sqrt(4kTR)
        (ngspice runs at TEMP = 27 C), and must roll off above the corner."""
        g = rc_schematic("1k", "1u")
        # corner = 159 Hz; sweep two decades past it so the 1-pole rolloff
        # is unambiguous (10 kHz would only roll off ~63x).
        out = analysis_runner.run_noise(g, "out", start_hz=0.1,
                                        stop_hz=1e5,
                                        points_per_decade=10)
        k = 1.380649e-23
        temp = 273.15 + 27.0
        expected = math.sqrt(4 * k * temp * 1000.0)    # R = 1k
        self.assertGreater(len(out["freqs"]), 10)
        self.assertEqual(len(out["freqs"]), len(out["onoise_density"]))
        self.assertAlmostEqual(out["onoise_density"][0], expected,
                               delta=0.05 * expected)
        # corner = 1/(2*pi*1k*1u) ~ 159 Hz; at 100 kHz a 1-pole filter has
        # rolled off ~630x, not stayed flat.
        self.assertLess(out["onoise_density"][-1],
                        0.01 * out["onoise_density"][0])
        self.assertIsNotNone(out["total_output"])
        self.assertGreater(out["total_output"], 0.0)

    def test_monte_carlo_perturbs_the_schematic_and_restores_it(self):
        g = rc_schematic("1k", "1u")
        out = analysis_runner.run_monte_carlo(
            g, "out", iterations=8, tol_pct=10.0, yield_pct=5.0, seed=7)
        self.assertEqual(out["iterations"], 8)
        self.assertEqual(len(out["samples"]), 8)
        self.assertGreater(out["std"], 0.0,
                           "tolerance produced no spread - the perturbation "
                           "never reached the netlist")
        self.assertGreater(out["max"], out["min"])
        self.assertGreaterEqual(out["yield_actual_pct"], 0.0)
        self.assertLessEqual(out["yield_actual_pct"], 100.0)
        self.assertEqual(g.components["R1"].value, "1k",
                         "monte carlo left R1 modified")
        self.assertEqual(g.components["C1"].value, "1u",
                         "monte carlo left C1 modified")


class TestDistortion(unittest.TestCase):
    """`.disto` harmonic ratios end to end: biased diode + load, real solver."""

    def test_distortion_reports_hd2_hd3(self):
        g = SchematicNetlistEngine()
        g.add_component(SchematicComponent("V1", "V", "V1", "0.5", -100, 0))
        g.add_component(SchematicComponent("D1", "D", "D1", "", 0, 0))
        g.add_component(SchematicComponent("R1", "R", "R1", "1k", 100, 0))
        g.add_component(SchematicComponent("GND1", "GND", "GND", "", 0, 100))
        g.add_wire("V1:+", "D1:A", "a")
        g.add_wire("D1:K", "R1:1", "out")
        g.add_wire("R1:2", "GND1:1", "gnd")
        g.add_wire("V1:-", "GND1:1", "gnd")

        out = analysis_runner.run_disto(g, "out", start_hz=100.0,
                                        stop_hz=1e4, points_per_decade=4)
        self.assertGreater(len(out["freqs"]), 5)
        self.assertEqual(len(out["hd2"]), len(out["freqs"]))
        self.assertEqual(len(out["hd3"]), len(out["freqs"]))
        for ratio in out["hd2"] + out["hd3"]:
            self.assertTrue(math.isfinite(ratio), ratio)
            self.assertGreaterEqual(ratio, 0.0, ratio)
        self.assertGreater(max(out["hd2"]), 0.0,
                           "a biased diode must produce some second harmonic")


if __name__ == "__main__":
    unittest.main(verbosity=2)