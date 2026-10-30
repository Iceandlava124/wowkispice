"""test_solver_error_handling.py - R5: bad decks must not look like success.

Row R5 of SCORECARD v1: "malformed or non-convergent netlist gives a clear
error within timeout; NaN/Inf can never reach the ADC conversion."

Measured before this file existed (logs/cmd/r5_probe.py and r5_probe4.py,
agentlog jobs R5-01-PROBE .. R5-01-PROBE4):

  * a malformed deck (`this is not a netlist line`, `R1`, `0`) loaded and
    ran with NO exception in 0.04 s, while ngspice printed
    `Error: circuit not parsed.` to its output stream;
  * `.op` on two conflicting voltage sources returned rc 0 in 0.05 s with
    `Error: The operating point could not be simulated successfully.`,
    `DC solution failed -` and `run simulation(s) aborted` in the log;
  * a transient with a contradictory initial condition returned rc 0 with
    `doAnalyses: TRAN:  Timestep too small` and `run simulation(s) aborted`;
  * a healthy control deck printed the banner, `Doing analysis`,
    `Using SPARSE` and `No. of Data Rows : 1` and nothing else.

ngspice returns 0 from both `ngSpice_Circ` and `ngSpice_Command` in all of
those cases, so the return code cannot report a failure; only the captured
output stream can. These tests are the reproduction: they fail on the tree
that produced the measurements above.

Second measurement, after the first version of the detector (jobs R5-01-
PROBE5 .. R5-01-PROBE8): the `Timestep too small` line is NOT by itself a
failure. Three decks printed it AFTER `No. of Data Rows` with a reported
time equal to their own .tran tstop, and all three held a complete,
correct result:

  * RC precision, .tran 10u 5m  -> 565 rows to 5 ms, RMSE 0.544 mV
  * DC motor,     .tran 200u 100m -> 555 rows to 100 ms, final speed 194.81
  * .ic v(out)=1e9, .tran 1n 10n -> 106 rows to 10 ns (and at 10u it does
    not complain at all), values finite

while a run that really dies reports a time below tstop or no time at all
(the conflicting-sources operating point). So a marker at/after tstop with
rows produced is dropped, and everything else still raises - see
TestCompletedTransientIsNotAFailure for the other side of that rule.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bridge.control_law import _to_counts

try:
    from bridge.binary_runner import _adc_counts_from_voltage
except ImportError:  # pragma: no cover - binary_runner is optional here
    _adc_counts_from_voltage = None

from bridge.ngspice_wrapper import NgSpiceEngine, resolve_ngspice_library


def _engine():
    """Build an engine on the real library, or skip naming what was tried."""
    lib, tried = resolve_ngspice_library()
    if lib is None:
        pytest.skip("ngspice shared library not found; tried: "
                    + "; ".join(tried))
    return NgSpiceEngine()


# Decks below are the measured cases, byte for byte as the probes ran them.
MALFORMED_DECK = [
    "* g",
    "this is not a netlist line",
    "R1",
    "0",
    ".end",
]

NONCONVERGENT_OP = [
    "* p",
    "V1 a 0 5",
    "V2 a 0 10",
    "R1 a 0 1",
    ".op",
    ".end",
]

NONCONVERGENT_TRAN = [
    "* i",
    "V1 a 0 5",
    "V2 a 0 10",
    "R1 a 0 1",
    ".tran 1n 10n",
    ".end",
]

# The deck that probe4 called 'unsolvable' is not: probe7 extended its stop
# time and it always reached it (10n, 100n, 10u - marker time == tstop each
# time, finite values, and no marker at all at 10u). It is a COMPLETED run
# that complains afterwards, so it belongs on the other side of the rule.
CONTRADICTORY_IC_TRAN = [
    "* i",
    "V1 in 0 5",
    "R1 in 0 1",
    "C1 in out 1u",
    ".ic v(out)=1e9",
    ".tran 1n 10n uic",
    ".end",
]

# Measured complete: 565 rows to tstop = 5 ms, RMSE 0.544 mV against the
# analytical step response (logs/cmd/r5_probe5.py).
COMPLETED_TRAN = [
    "* RC",
    "Vstep in 0 PWL(0 0 1u 3.3000)",
    "R1 in out 1000.0",
    "C1 out 0 1.0u IC=0",
    ".tran 10u 5m uic",
    ".end",
]

HEALTHY_DECK = [
    "* ok",
    "V1 in 0 5",
    "R1 in out 2k",
    "R2 out 0 2k",
    ".op",
    ".end",
]


class TestMalformedNetlistRaises:
    """A deck ngspice cannot parse must fail the load, not pass silently."""

    @pytest.mark.timeout(30)
    @pytest.mark.req("CO-09")
    def test_malformed_deck_raises_a_clear_error(self):
        engine = _engine()
        with pytest.raises(RuntimeError) as ctx:
            engine.load_circuit(MALFORMED_DECK)
        msg = str(ctx.value)
        # ngspice names the line it objected to during load: the `Error on
        # line 2 or its substitute:` header plus the text on the next line.
        assert "error on line" in msg.lower(), (
            "the error must quote what ngspice actually said, got: %s" % msg)
        assert "line 2" in msg.lower(), (
            "the error must say which line failed, got: %s" % msg)

    @pytest.mark.timeout(30)
    def test_error_names_the_offending_text(self):
        engine = _engine()
        with pytest.raises(RuntimeError) as ctx:
            engine.load_circuit(MALFORMED_DECK)
        assert "this is not a netlist line" in str(ctx.value), (
            "the caller must be able to find the bad line")


class TestNonConvergentAnalysisRaises:
    """A deck with no solution must fail the run, not return rc 0."""

    @pytest.mark.timeout(30)
    @pytest.mark.req("CO-08")
    def test_conflicting_sources_op_raises(self):
        engine = _engine()
        engine.load_circuit(NONCONVERGENT_OP)
        with pytest.raises(RuntimeError) as ctx:
            engine.cmd("run")
        msg = str(ctx.value)
        # The log quotes whichever line the solver reached first; measured
        # order for this deck is `Transient op failed, timestep too small`,
        # then the operating-point and DC-solution failures.
        assert ("operating point could not be simulated successfully"
                in msg or "dc solution failed" in msg
                or "timestep too small" in msg), (
            "the error must quote the convergence failure, got: %s" % msg)

    @pytest.mark.timeout(30)
    def test_non_convergent_transient_raises(self):
        """Two sources shorted together with no `uic`: the operating point
        cannot be found, so the run stops before it produces anything. The
        measured first lines are `Transient op failed, timestep too small`
        (no `time =`, because it died in the operating point, not the sweep)
        and `The operating point could not be simulated successfully.`"""
        engine = _engine()
        engine.load_circuit(NONCONVERGENT_TRAN)
        with pytest.raises(RuntimeError) as ctx:
            engine.cmd("run")
        msg = str(ctx.value)
        assert ("timestep too small" in msg or "aborted" in msg
                or "operating point" in msg), (
            "the error must quote the transient failure, got: %s" % msg)

    @pytest.mark.timeout(30)
    def test_error_arrives_within_the_timeout(self):
        """The row asks for a clear error within timeout: measure it."""
        import time
        engine = _engine()
        engine.load_circuit(NONCONVERGENT_OP)
        start = time.monotonic()
        with pytest.raises(RuntimeError):
            engine.cmd("run")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, (
            "failure surfaced only after %.2f s" % elapsed)


class TestHealthyDeckStillRuns:
    """Guards the fix against an over-broad error matcher."""

    @pytest.mark.timeout(30)
    def test_healthy_deck_raises_nothing(self):
        engine = _engine()
        engine.load_circuit(HEALTHY_DECK)
        engine.cmd("run")
        rows = [str(l) for l in engine.output_logs
                if "No. of Data Rows" in str(l)]
        assert rows, "the healthy control must actually produce results"

    @pytest.mark.timeout(30)
    def test_warnings_are_not_errors(self):
        """`Warning: can't find the initialization file spinit.` is printed
        by every engine on this box and must never be treated as failure."""
        engine = _engine()
        engine.load_circuit(HEALTHY_DECK)
        engine.cmd("run")
        warns = [str(l) for l in engine.output_logs if "Warning:" in str(l)]
        assert warns, "expected the benign spinit warning to be present"
        # ...and the run still succeeded, which is the assertion above.


class TestCompletedTransientIsNotAFailure:
    """The other side of the same rule: a run that reached its stop time and
    produced its rows must not be reported as a failure, or three healthy
    physics tests fail (they did, on the first detector - see the docstring).
    """

    @pytest.mark.timeout(30)
    def test_completed_rc_transient_does_not_raise(self):
        engine = _engine()
        engine.load_circuit(COMPLETED_TRAN)
        engine.cmd("run")                       # must not raise
        import numpy as np
        t = np.array(engine.get_vector_array("time"))
        v = np.array(engine.get_vector_array("out"))
        assert len(t) > 100, "the completed run must still hold its data"
        assert abs(float(t[-1]) - 0.005) < 1e-9, (
            "expected the transient to reach its 5 ms stop time, got %r"
            % float(t[-1]))
        assert bool(np.all(np.isfinite(v))), "the completed data must be finite"

    @pytest.mark.timeout(30)
    def test_contradictory_ic_deck_is_a_completed_run(self):
        """probe7: this deck always reaches tstop (marker time == tstop for
        10n, 100n and 10u), so raising on it was the detector's false
        positive, not a solver failure."""
        engine = _engine()
        engine.load_circuit(CONTRADICTORY_IC_TRAN)
        engine.cmd("run")                       # must not raise
        rows = [str(l) for l in engine.output_logs
                if "No. of Data Rows" in str(l)]
        assert rows, "the run must have produced data"

    @pytest.mark.timeout(30)
    def test_tstop_is_read_from_the_deck(self):
        """_find_tstop must understand SPICE suffixes: `.tran 10u 5m` is a
        5 ms stop time, not '5m' and not an error."""
        from bridge.ngspice_wrapper import NgSpiceEngine
        assert NgSpiceEngine._find_tstop(COMPLETED_TRAN) == pytest.approx(0.005)
        assert NgSpiceEngine._find_tstop(NONCONVERGENT_OP) is None


class TestFailureReportClassifier:
    """_failure_report is a pure function, so the rule itself is testable
    without the shared library - including the cases no real deck has yet
    produced on this machine.
    """

    COMPLETED = [
        "stdout No. of Data Rows : 565",
        "stderr doAnalyses: TRAN:  Timestep too small; time = 0.005, "
        "timestep = 0: cause unrecorded.",
        "stderr run simulation(s) aborted",
    ]
    EARLY_ABORT = [
        "stdout No. of Data Rows : 210",
        "stderr doAnalyses: TRAN:  Timestep too small; time = 0.002, "
        "timestep = 0: cause unrecorded.",
        "stderr run simulation(s) aborted",
    ]
    NO_ROWS = [
        "stderr doAnalyses: TRAN:  Timestep too small; time = 0.005, "
        "timestep = 0: cause unrecorded.",
        "stderr run simulation(s) aborted",
    ]

    def test_completed_run_reports_nothing(self):
        assert NgSpiceEngine._failure_report(self.COMPLETED, 0.005) is None

    def test_abort_before_tstop_still_reports(self):
        report = NgSpiceEngine._failure_report(self.EARLY_ABORT, 0.005)
        assert report is not None
        assert "timestep too small" in report.lower()

    def test_no_rows_means_not_completed(self):
        """The marker's own claim is not enough: without data rows the run
        produced nothing to hand back, so it stays a failure."""
        report = NgSpiceEngine._failure_report(self.NO_ROWS, 0.005)
        assert report is not None

    def test_unknown_tstop_fails_closed(self):
        assert NgSpiceEngine._failure_report(self.COMPLETED, None) is not None

    def test_operating_point_failure_still_reports(self):
        """A marker with no `time =` can never be read as 'reached the end'."""
        lines = ["stdout No. of Data Rows : 10",
                 "stderr Error: Transient op failed, timestep too small",
                 "stderr Error: The operating point could not be "
                 "simulated successfully."]
        report = NgSpiceEngine._failure_report(lines, 1e-8)
        assert report is not None
        assert "operating point" in report.lower()

    def test_the_line_after_a_suppressed_marker_goes_with_it(self):
        """The companion `run simulation(s) aborted` must not survive as a
        failure on its own once its marker is dropped."""
        assert NgSpiceEngine._failure_report(self.COMPLETED, 0.005) is None


class TestNonFiniteNeverBecomesACount:
    """NaN/Inf must never reach the ADC conversion and produce a count."""

    @pytest.mark.parametrize("bad", [float("nan"),
                                     float("inf"),
                                     float("-inf")])
    @pytest.mark.timeout(30)
    def test_control_law_conversion_rejects_non_finite(self, bad):
        with pytest.raises((ValueError, OverflowError, ArithmeticError)):
            _to_counts(bad, 3.3, 12)

    @pytest.mark.parametrize("bad", [float("nan"),
                                     float("inf"),
                                     float("-inf")])
    @pytest.mark.timeout(30)
    def test_binary_runner_conversion_rejects_non_finite(self, bad):
        if _adc_counts_from_voltage is None:  # pragma: no cover
            pytest.skip("bridge.binary_runner does not export the helper")
        with pytest.raises((ValueError, OverflowError, ArithmeticError)):
            _adc_counts_from_voltage(bad)

    @pytest.mark.timeout(30)
    def test_a_finite_value_still_converts(self):
        """The rejection must not swallow the working path: 1.65 V into a
        3.3 V 12-bit converter is exactly half scale."""
        assert _to_counts(1.65, 3.3, 12) == 2048
        if _adc_counts_from_voltage is not None:  # pragma: no cover
            # binary_runner takes the voltage BEFORE the 0.5 divider, and
            # the documented law is v_pin = sense * divider: 3.3 V at vout
            # (half scale through the 2:1 divider) must map to 2048.
            assert _adc_counts_from_voltage(3.3) == 2048

    @pytest.mark.timeout(30)
    def test_conversion_of_nan_cannot_silently_clamp(self):
        """A regression that maps NaN to 0 (a plausible 'clamp' fix) would
        drive the gate to its low state forever; this must fail instead."""
        for bad in (float("nan"), float("inf")):
            result = None
            try:
                result = _to_counts(bad, 3.3, 12)
            except (ValueError, OverflowError, ArithmeticError):
                continue
            raise AssertionError(
                "non-finite input produced a count instead of an error: %r"
                % (result,))
