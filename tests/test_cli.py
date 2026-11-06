"""Tests for the headless ``wosp`` CLI.

These exercise dispatch and the real code paths that can run without QEMU.
The QEMU-backed commands are replaced at their import site, so the test
proves the CLI passes the right arguments and reports the result honestly.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.cad_engine import SchematicComponent, SchematicNetlistEngine
from bridge.cosim_runner import CosimRun
from tools import cli
from tools.golden_trace import GoldenTrace


def _model_dict(with_law=True):
    g = SchematicNetlistEngine()
    g.add_component(SchematicComponent("V1", "V", "V1", "3.3", -160, 0))
    g.add_component(SchematicComponent("R1", "R", "R1", "10", 0, 0))
    g.add_component(SchematicComponent("GND1", "GND", "GND", "", 0, 80))
    g.add_component(SchematicComponent("U1", "ESP32", "U1", "ESP32", -260, 0))
    g.add_wire("V1:+", "R1:1", "vout")
    g.add_wire("R1:2", "GND1:1", "gnd")
    g.add_wire("V1:-", "GND1:1", "gnd")
    g.add_wire("U1:GPIO18", "R1:1", "gate")
    if with_law:
        g.control_laws["U1"] = {
            "kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
            "target_v": 3.3, "hysteresis_v": 0.165, "divider": 0.5,
            "vref": 3.3, "adc_bits": 12,
        }
    return g.to_dict()


def _fake_run(aborted=False):
    run = CosimRun()
    run.time = [0.0, 0.0005, 0.001]
    run.traces = {"vout": [3.3, 3.3, 3.3]}
    run.nets = ["vout"]
    run.netlist = ["* cli test"]
    run.callback_hits = 3
    run.aborted = aborted
    return run


class TestCliDispatch(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_version_is_zero_and_identifies_the_tool(self):
        code, out, _err = self._run(["version"])
        self.assertEqual(code, 0)
        self.assertIn("WOWKISPICE", out)

    def test_no_command_prints_help_and_fails(self):
        code, out, _err = self._run([])
        self.assertEqual(code, 1)
        self.assertIn("usage:", out.lower())

    def test_help_exits_zero(self):
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_golden_trace_without_subcommand_is_an_error(self):
        code, _out, err = self._run(["golden-trace"])
        self.assertEqual(code, 1)
        self.assertIn("capture", err)


class TestModelLoading(unittest.TestCase):
    def test_json_schematic_round_trips(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "model.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(_model_dict(), fh)
            model = cli._load_model(path)
        self.assertIn("U1", model.components)
        self.assertEqual(cli._pin_specs_from_model(model),
                         {"GPIO18": {"sense_net": "vout"}})

    def test_a_netlist_is_rejected_with_a_clear_error(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "model.cir")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("V1 in 0 1\n.end\n")
            with self.assertRaises(ValueError) as ctx:
                cli._load_model(path)
        self.assertIn("component graph", str(ctx.exception))

    def test_model_without_a_law_reports_nothing_to_close(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "model.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(_model_dict(with_law=False), fh)
            with mock.patch("builtins.print"):
                code = cli.run_cosim_binary(type("A", (), {
                    "model": path, "qemu": "/no/qemu", "firmware": None,
                    "duration_ms": 1.0, "tstep_us": 1.0, "output": None})())
        self.assertEqual(code, 1)


class TestCosimCommand(unittest.TestCase):
    def test_output_json_contains_time_traces_and_run_state(self):
        with tempfile.TemporaryDirectory() as td:
            model_path = os.path.join(td, "model.json")
            out_path = os.path.join(td, "trace.json")
            with open(model_path, "w", encoding="utf-8") as fh:
                json.dump(_model_dict(), fh)

            seen = {}

            def fake(model, pin_specs, **kwargs):
                seen["pins"] = pin_specs
                seen["kwargs"] = kwargs
                return _fake_run()

            args = type("A", (), {
                "model": model_path, "qemu": "/no/qemu", "firmware": None,
                "duration_ms": 1.0, "tstep_us": 0.5, "output": out_path})()
            with mock.patch("bridge.binary_runner.run_binary_cosim",
                            side_effect=fake):
                code = cli.run_cosim_binary(args)

            self.assertEqual(code, 0)
            self.assertEqual(seen["pins"], {"GPIO18": {"sense_net": "vout"}})
            with open(out_path, encoding="utf-8") as fh:
                data = json.load(fh)
        self.assertEqual(data["time"], [0.0, 0.0005, 0.001])
        self.assertEqual(data["traces"], {"vout": [3.3, 3.3, 3.3]})
        self.assertFalse(data["aborted"])
        self.assertEqual(data["callback_hits"], 3)


class TestGateFlipCommand(unittest.TestCase):
    def test_missing_files_are_reported(self):
        args = type("A", (), {
            "qemu": "/no/qemu", "firmware": "/no/fw.bin",
            "low_adc": 1500, "high_adc": 2500, "settle_delay": 0.0})()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.run_gate_flip_test(args), 1)

    def test_delegates_to_the_tested_binary_runner(self):
        with tempfile.TemporaryDirectory() as td:
            qemu = os.path.join(td, "qemu")
            fw = os.path.join(td, "fw.bin")
            for path in (qemu, fw):
                with open(path, "wb") as fh:
                    fh.write(b"\x00")
            args = type("A", (), {
                "qemu": qemu, "firmware": fw, "low_adc": 1500,
                "high_adc": 2500, "settle_delay": 0.0})()
            result = {"ok": True, "counts": {}, "errors": [],
                      "gates": [{"adc": 1500, "gate": True},
                                {"adc": 2500, "gate": False}]}
            with mock.patch("bridge.binary_runner.test_gate_flip",
                            return_value=result) as call:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = cli.run_gate_flip_test(args)
        self.assertEqual(code, 0)
        self.assertEqual(call.call_args.kwargs["low_adc"], 1500)


class TestGoldenCommands(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.td = self._td.name
        self.addCleanup(self._td.cleanup)
        self.patch = mock.patch("tools.golden_trace.GOLDEN_DIR",
                                __import__("pathlib").Path(self.td))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def _write_model(self):
        path = os.path.join(self.td, "model.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(_model_dict(), fh)
        return path

    def test_capture_refuses_a_run_with_no_trace(self):
        args = type("A", (), {
            "name": "empty", "model": self._write_model(), "qemu": "/no/qemu",
            "firmware": None, "duration_ms": 1.0, "tstep_us": 0.5})()
        with mock.patch("bridge.binary_runner.run_binary_cosim",
                        return_value=CosimRun()):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli._capture_golden(args, GoldenTrace), 1)
        self.assertFalse((GoldenTrace("empty").golden_path).exists())

    def test_capture_records_provenance_and_saves_the_trace(self):
        args = type("A", (), {
            "name": "cli_capture", "model": self._write_model(),
            "qemu": "/no/qemu", "firmware": None,
            "duration_ms": 1.0, "tstep_us": 0.5})()
        with mock.patch("bridge.binary_runner.run_binary_cosim",
                        return_value=_fake_run()):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    cli._capture_golden(args, GoldenTrace), 0)
        time, traces, meta = GoldenTrace("cli_capture").load()
        self.assertEqual(time, [0.0, 0.0005, 0.001])
        self.assertEqual(traces["vout"], [3.3, 3.3, 3.3])
        self.assertIn("captured_at", meta)
        self.assertIn("command", meta)
        self.assertIn("firmware_sha256", meta)

    def test_compare_matches_and_reports_mismatches(self):
        GoldenTrace("cli_compare").save(
            [0.0, 0.001], {"vout": [3.3, 3.3]})
        trace = os.path.join(self.td, "trace.json")
        with open(trace, "w", encoding="utf-8") as fh:
            json.dump({"time": [0.0, 0.001], "traces": {"vout": [3.3, 3.3]}},
                      fh)
        args = type("A", (), {
            "name": "cli_compare", "trace": trace, "tolerances": None})()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli._compare_golden(args, GoldenTrace), 0)

        with open(trace, "w", encoding="utf-8") as fh:
            json.dump({"time": [0.0, 0.001], "traces": {"vout": [3.3, 5.0]}},
                      fh)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli._compare_golden(args, GoldenTrace), 1)

    def test_compare_rejects_invalid_tolerance_json(self):
        GoldenTrace("cli_tol").save([0.0], {"vout": [3.3]})
        trace = os.path.join(self.td, "trace.json")
        with open(trace, "w", encoding="utf-8") as fh:
            json.dump({"time": [0.0], "traces": {"vout": [3.3]}}, fh)
        args = type("A", (), {
            "name": "cli_tol", "trace": trace, "tolerances": "{not json"})()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli._compare_golden(args, GoldenTrace), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
