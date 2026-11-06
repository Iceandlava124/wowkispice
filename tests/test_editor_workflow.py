"""
test_editor_workflow.py - editor features beyond the basic place/wire/run loop.

Covers what this tranche added:
1. Board-specific MCU symbols (Arduino / STM32 / ESP32) netlist and export
2. LTspice gestures - Ctrl+click multi-select, click-to-rotate, Ctrl+Y
3. The editable netlist pane (edit, run, import-as-components)
4. Simulation mode + accuracy presets + progress + abort
5. Pin mapping view and the UART serial console
"""

import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QApplication, QInputDialog, QMessageBox

from bridge import kicad_export
from bridge.cad_engine import SchematicComponent, SchematicNetlistEngine, is_mcu
from bridge.ngspice_wrapper import NgSpiceEngine
from ui.schematic_editor import SchematicEditor
from ui.schematic_scene import SchematicScene
from ui.schematic_symbols import PALETTE_GROUPS, SYMBOLS

_app = QApplication.instance() or QApplication([])


def arduino_circuit(comp_type="ARDUINO_UNO"):
    """U1.D5 -> R1 -> GND: an LED drive on a real board symbol.

    Deliberately has no voltage source. Putting one on the same net as an MCU
    pin would short two ideal voltage sources, which ngspice correctly
    refuses to solve.
    """
    g = SchematicNetlistEngine()
    g.add_component(SchematicComponent("U1", comp_type, "U1", "ATmega328P", -200, 0))
    g.add_component(SchematicComponent("R1", "R", "R1", "330", 100, 0))
    g.add_component(SchematicComponent("GND1", "GND", "GND", "", 100, 80))
    g.add_wire("U1:D5", "R1:1", "led")
    g.add_wire("R1:2", "GND1:1", "gnd")
    g.add_wire("U1:GND", "GND1:1", "gnd")
    return g


class DialogTrap:
    """Modal dialogs hang a headless test, so record calls and auto-cancel."""

    def __init__(self):
        self.messages = []
        self._saved = {}

    def __enter__(self):
        for name in ("information", "warning", "critical", "question"):
            self._saved[("msg", name)] = getattr(QMessageBox, name)

            def make(kind):
                def handler(parent, title, text, *a, **k):
                    self.messages.append((kind, title, text))
                    return QMessageBox.Ok
                return handler
            setattr(QMessageBox, name, staticmethod(make(name)))

        for name in ("getItem", "getText", "getMultiLineText"):
            self._saved[("in", name)] = getattr(QInputDialog, name)
            setattr(QInputDialog, name, staticmethod(lambda *a, **k: ("", False)))
        return self

    def __exit__(self, *exc):
        for (kind, name), fn in self._saved.items():
            if kind == "msg":
                setattr(QMessageBox, name, fn)
            else:
                setattr(QInputDialog, name, fn)
        return False

    def warned(self, fragment):
        # Match on the title as well as the body: several paths put the whole
        # explanation in the window title.
        return any(fragment.lower() in (str(m[1]) + " " + str(m[2])).lower()
                   for m in self.messages)


class TestMcuBoardLibrary(unittest.TestCase):
    def test_every_board_is_recognised_as_an_mcu(self):
        for comp_type in ("MCU", "ARDUINO_UNO", "ARDUINO_NANO", "ARDUINO_MEGA",
                          "STM32F103", "ESP32", "ESP32S3"):
            with self.subTest(comp_type=comp_type):
                self.assertTrue(is_mcu(comp_type))
        self.assertFalse(is_mcu("R"))

    def test_editor_and_kicad_pin_counts_agree(self):
        """A symbol whose pins disagree with its KiCad twin exports wrong data."""
        for comp_type, _ in PALETTE_GROUPS:
            for board in _:
                with self.subTest(board=board):
                    self.assertIn(board, SYMBOLS)
                    self.assertIn(board.upper(), kicad_export.KICAD_SYMBOLS)
                    self.assertEqual(len(SYMBOLS[board]["pins"]),
                                     len(kicad_export.KICAD_SYMBOLS[board.upper()]["pins"]))

    def test_uno_exposes_the_real_header_pins(self):
        names = {p[0] for p in SYMBOLS["ARDUINO_UNO"]["pins"]}
        for pin in ("D0", "D5", "D13", "A0", "A5", "5V", "3V3", "GND", "AREF"):
            self.assertIn(pin, names)

    def test_mega_has_more_pins_than_the_uno(self):
        uno = len(SYMBOLS["ARDUINO_UNO"]["pins"])
        mega = len(SYMBOLS["ARDUINO_MEGA"]["pins"])
        self.assertGreater(mega, uno)
        mega_names = {p[0] for p in SYMBOLS["ARDUINO_MEGA"]["pins"]}
        self.assertIn("D53", mega_names)
        self.assertIn("A15", mega_names)

    def test_board_pin_drives_real_physics(self):
        g = arduino_circuit()
        g.gpio_profiles["U1"] = {"D5": {"mode": "square", "freq_hz": 1000,
                                         "duty": 0.5}}
        lines, nets, warns = g.compile_netlist()
        self.assertEqual(warns, [], warns)
        self.assertIn("VU1_D5 led 0 PULSE", "\n".join(lines))

        engine = NgSpiceEngine(verbose=False)
        engine.load_circuit(lines)
        engine.cmd("run")
        values = engine.get_vector_array("led")
        self.assertAlmostEqual(max(values), 3.3, delta=0.1)
        self.assertAlmostEqual(min(values), 0.0, delta=0.1)

    def test_board_exports_to_kicad_with_its_own_symbol(self):
        import tempfile
        g = arduino_circuit()
        out = os.path.join(tempfile.mkdtemp(), "a.kicad_sch")
        kicad_export.export_kicad_schematic(g, out)
        text = open(out, encoding="utf-8").read()
        self.assertIn("MCU_ARDUINO_UNO", text)
        self.assertIn('"D5"', text)
        self.assertNotIn("MCU_GENERIC", text)


class TestGestures(unittest.TestCase):
    def setUp(self):
        self.scene = SchematicScene(SchematicNetlistEngine())
        self.scene.place_component("R", QPointF(0, 0))
        self.scene.place_component("R", QPointF(120, 0))
        self.scene.place_component("R", QPointF(240, 0))

    def test_ctrl_click_toggles_additive_selection(self):
        r1 = self.scene.comp_items["R1"]
        r2 = self.scene.comp_items["R2"]
        self.scene.toggle_selection(r1)
        self.scene.toggle_selection(r2)
        self.assertTrue(r1.isSelected() and r2.isSelected())
        self.scene.toggle_selection(r2)
        self.assertTrue(r1.isSelected())
        self.assertFalse(r2.isSelected())

    def test_rotation_applies_to_every_selected_component(self):
        for cid in ("R1", "R2"):
            self.scene.comp_items[cid].setSelected(True)
        self.scene.rotate_selected()
        self.assertEqual(self.scene.model.components["R1"].rotation, 90)
        self.assertEqual(self.scene.model.components["R2"].rotation, 90)

    def test_double_click_detection_only_fires_on_a_repeat(self):
        item = self.scene.comp_items["R1"]
        self.assertFalse(self.scene.last_click_was_double(item, None))
        self.assertTrue(self.scene.last_click_was_double(item, None))
        # A click on a different item starts a new sequence.
        self.assertFalse(self.scene.last_click_was_double(
            self.scene.comp_items["R2"], None))

    def test_click_to_rotate_changes_one_component_only(self):
        before = self.scene.model.components["R2"].rotation
        self.scene.rotate_item(self.scene.comp_items["R1"])
        self.assertEqual(self.scene.model.components["R1"].rotation, 90)
        self.assertEqual(self.scene.model.components["R2"].rotation, before)

    def test_undo_restores_rotation(self):
        self.scene.rotate_item(self.scene.comp_items["R1"])
        self.scene.undo()
        self.assertEqual(self.scene.model.components["R1"].rotation, 0)


class TestNetlistEditorPane(unittest.TestCase):
    def test_pane_starts_in_sync_with_the_schematic(self):
        win = SchematicEditor()
        self.assertIn(".end", win.netlist_editor.toPlainText())
        self.assertFalse(win._netlist_edited)
        win.close()

    def test_editing_marks_the_pane_dirty(self):
        win = SchematicEditor()
        win.netlist_editor.setPlainText("* edited\nR1 a b 1k\n.end")
        self.assertTrue(win._netlist_edited)
        win.close()

    def test_reset_restores_the_generated_netlist(self):
        win = SchematicEditor()
        win.netlist_editor.setPlainText("* junk")
        win._reset_netlist_editor()
        self.assertFalse(win._netlist_edited)
        self.assertNotIn("junk", win.netlist_editor.toPlainText())
        win.close()

    def test_edited_netlist_is_what_gets_simulated(self):
        with DialogTrap() as trap:
            win = SchematicEditor()
            win.netlist_editor.setPlainText(
                "* hand written\nV1 in 0 DC 5\nR1 in out 1k\n"
                "C1 out 0 1u IC=0\n.tran 1u 5m uic\n.end")
            win.run_edited_netlist()
            self.assertTrue(win._last_time, "no time vector")
            out = win._last_traces.get("out")
            self.assertIsNotNone(out, list(win._last_traces))
            self.assertAlmostEqual(max(out), 5.0, delta=0.1)
            self.assertLess(min(out), 0.1)
            self.assertFalse(trap.warned("failed"), trap.messages)
            win.close()

    def test_import_builds_components_from_the_netlist(self):
        win = SchematicEditor()
        win.netlist_editor.setPlainText(
            "* netlist\nV1 in 0 DC 12\nR1 in out 1k\n"
            "R2 out 0 2.2k\nC1 out 0 100n\n.tran 1u 1m uic\n.end")
        win.import_netlist_as_components()
        types = sorted(c.comp_type for c in win.model.components.values())
        self.assertEqual(types, ["C", "R", "R", "V"])
        values = sorted(c.value for c in win.model.components.values()
                        if c.comp_type == "R")
        self.assertEqual(values, ["1k", "2.2k"])
        win.close()

    def test_import_of_a_netlist_with_no_parts_is_reported(self):
        with DialogTrap() as trap:
            win = SchematicEditor()
            win.netlist_editor.setPlainText(".tran 1u 1m\n.end")
            win.import_netlist_as_components()
            self.assertTrue(trap.warned("nothing imported"), trap.messages)
            win.close()

    def test_probe_vectors_ignores_ground(self):
        lines = ["R1 in 0 1k", "C1 out GND 1u", "V1 a b DC 5"]
        found = SchematicEditor._probe_vectors(lines)
        self.assertIn("in", found)
        self.assertIn("out", found)
        self.assertNotIn("0", found)
        self.assertNotIn("GND", found)


class TestSimulationControls(unittest.TestCase):
    def setUp(self):
        with DialogTrap():
            self.win = SchematicEditor()
            self.win.model.load_dict(arduino_circuit().to_dict())
            self.win.model.gpio_profiles["U1"] = {
                "D5": {"mode": "square", "freq_hz": 1000, "duty": 0.5}}
            self.win.scene.rebuild()
            self.win.duration_box.setValue(1.0)
            self.win.tstep_box.setValue(5.0)

    def tearDown(self):
        self.win.close()

    def test_accuracy_presets_scale_timestep_and_duration(self):
        self.win.speed_box.setCurrentText("Balanced")
        self.assertAlmostEqual(self.win.effective_tstep_us(), 5.0)
        self.win.speed_box.setCurrentText("Fast")
        self.assertGreater(self.win.effective_tstep_us(), 5.0)
        self.assertLess(self.win.effective_duration_ms(), 1.0)
        self.win.speed_box.setCurrentText("Accurate")
        self.assertLess(self.win.effective_tstep_us(), 5.0)
        self.assertAlmostEqual(self.win.effective_duration_ms(), 1.0)

    def test_progress_reaches_complete_after_a_run(self):
        self.win.speed_box.setCurrentText("Balanced")
        self.win.mode_box.setCurrentText("Transient only")
        self.win.run_simulation()
        self.assertEqual(self.win.progress.value(), 100)
        self.assertFalse(self.win.stop_button.isEnabled())

    def test_transient_only_ignores_the_mcu_profile(self):
        self.win.mode_box.setCurrentText("Transient only")
        self.win.run_simulation()
        traces = self.win._last_traces
        self.assertTrue(traces, "no traces")
        for name, values in traces.items():
            self.assertLess(max(values) - min(values), 1e-6,
                            f"{name} is modulated in transient-only mode")
        self.assertIn("NOT driven", self.win.netlist_view.toPlainText())

    def test_mcu_only_mode_reports_firmware_behaviour_without_solving(self):
        with DialogTrap() as trap:
            self.win.mode_box.setCurrentText("MCU only")
            self.win.run_simulation()
            self.assertIn("D5", self.win._last_traces)
            values = self.win._last_traces["D5"]
            self.assertGreater(max(values), 3.0)
            self.assertLess(min(values), 0.1)
            title = self.win.plot.getPlotItem().titleLabel.text
            self.assertIn("no analog solve", title)
            self.assertFalse(trap.warned("nothing to run"), trap.messages)

    def test_mcu_only_without_a_law_says_so(self):
        win = SchematicEditor()
        with DialogTrap() as trap:
            win.mode_box.setCurrentText("MCU only")
            win.run_simulation()
            self.assertTrue(trap.warned("no mcu behaviour"), trap.messages)
        win.close()

    def test_stop_button_tells_the_solver_to_stop(self):
        """The UI path must actually reach ngspice, not just flip a flag."""
        win = self.win
        calls = []
        win.ng = type("FakeEngine", (), {
            "request_stop": lambda self: calls.append(1) or True,
            "progress_callback": None, "timestep_count": 0,
            "_stop_requested": False})()
        win._running = True
        win.stop_simulation()
        self.assertTrue(win._abort)
        self.assertEqual(len(calls), 1, "request_stop was never called")
        win._running = False

    def test_request_stop_aborts_a_long_run_early(self):
        """
        Solver-level abort: a 400 ms run must not run to completion.

        Driven from a hook that only touches the engine. Calling UI methods
        from inside the solver callback re-enters Qt and deadlocks, which is
        why the real Stop button runs on the GUI thread while the solver runs
        on a worker.
        """
        engine = NgSpiceEngine(verbose=False)
        steps = []
        engine.progress_callback = lambda t, n: steps.append(n)
        engine.load_circuit(["* long run", "V1 in 0 DC 1", "R1 in 0 1k",
                             ".tran 1u 400m uic", ".end"])
        stopper = threading.Thread(target=_sleep_then_stop, args=(engine, 0.2))
        stopper.start()
        engine.cmd("run")
        stopper.join()
        self.assertTrue(engine.stop_requested)
        # A full run needs ~1.6M steps; stopping early must be far fewer.
        self.assertLess(engine.timestep_count, 1_000_000,
                        "run completed despite the interrupt")
        engine.progress_callback = None


def _sleep_then_stop(engine, delay):
    time.sleep(delay)
    engine.request_stop()

    def test_stop_is_a_no_op_when_nothing_is_running(self):
        self.win._running = False
        self.win.stop_simulation()          # must not raise or set the engine flag


class TestPinMappingAndSerial(unittest.TestCase):
    def test_pin_map_lists_every_declared_pin(self):
        from bridge.gpio_model import pin_map
        g = arduino_circuit()
        gpio_profiles = {"U1": {"D5": {"mode": "square", "freq_hz": 1000,
                                       "duty": 0.5}}}
        pins = pin_map(g, "U1", gpio_profiles)
        names = [p["pin"] for p in pins]
        self.assertIn("D5", names)
        self.assertIn("GND", names)
        d5 = next(p for p in pins if p["pin"] == "D5")
        self.assertEqual(d5["role"], "output")
        self.assertTrue(d5["wired"])
        self.assertIn("1000 Hz", d5["behaviour"])
        gnd = next(p for p in pins if p["pin"] == "GND")
        self.assertEqual(gnd["direction"], "power")

    def test_pin_map_flags_an_unwired_pin_as_absent(self):
        from bridge.cad_engine import SchematicComponent, SchematicNetlistEngine
        from bridge.gpio_model import pin_map
        g = SchematicNetlistEngine()
        g.add_component(SchematicComponent("U1", "ARDUINO_UNO", "U1",
                                           "ATmega328P", -200, 0))
        self.assertEqual(pin_map(g, "U1", {}), [])
        self.assertEqual(pin_map(g, "U1", {}, {}), [])
        self.assertEqual(pin_map(g, "NOPE", {}), [])

    def test_pin_map_reports_a_non_mcu_as_empty(self):
        from bridge.gpio_model import pin_map
        g = SchematicNetlistEngine()
        g.add_component(SchematicComponent("R1", "R", "R1", "1k", 0, 0))
        self.assertEqual(pin_map(g, "R1", {}), [])

    def test_serial_console_collects_uart_lines(self):
        from bridge.serial_console import SerialConsole, parse_uart
        text = "BUCK_CTRL: Loop: 10000 | Raw ADC: 2010 | Gate: ON\r\nReady\r\n"
        lines = parse_uart(text)
        self.assertEqual(len(lines), 2)
        self.assertIn("Gate: ON", lines[0])
        self.assertEqual(lines[1], "Ready")

        console = SerialConsole()
        console.write(text)
        self.assertEqual(console.count, 2)
        self.assertIn("Gate: ON", console.text())

    def test_serial_console_grows_line_traceable_to_the_firmware(self):
        from bridge.serial_console import SerialConsole
        console = SerialConsole(max_lines=3)
        for i in range(6):
            console.write(f"line {i}\n")
        self.assertLessEqual(console.count, 3)
        self.assertIn("line 5", console.text())


class TestPinMapAndSerialPanels(unittest.TestCase):
    """The Pin Map and Serial tabs in the real window."""

    def setUp(self):
        self.win = SchematicEditor()
        self.win.model.load_dict(arduino_circuit().to_dict())
        self.win.model.gpio_profiles["U1"] = {
            "D5": {"mode": "square", "freq_hz": 1000, "duty": 0.5}}
        self.win.scene.rebuild()

    def tearDown(self):
        self.win.close()

    def _rows(self):
        return [[self.win.pinmap_table.topLevelItem(i).text(c)
                 for c in range(6)]
                for i in range(self.win.pinmap_table.topLevelItemCount())]

    def test_pin_map_table_lists_the_wired_pins(self):
        rows = self._rows()
        names = [r[0] for r in rows]
        self.assertIn("D5", names)
        self.assertIn("GND", names)
        d5 = next(r for r in rows if r[0] == "D5")
        self.assertEqual(d5[1], "led")
        self.assertEqual(d5[3], "output")
        self.assertIn("1000 Hz", d5[4])
        self.assertEqual(d5[5], "yes")

    def test_pin_map_marks_ground_as_a_power_rail(self):
        gnd = next(r for r in self._rows() if r[0] == "GND")
        self.assertEqual(gnd[2], "power")
        self.assertIn("ground", gnd[4])

    def test_pin_map_status_admits_the_hardware_column_is_inferred(self):
        self.assertIn("inferred", self.win.pinmap_status.text().lower())

    def test_pin_map_says_so_when_there_is_no_mcu(self):
        win = SchematicEditor()
        win.model.clear()
        win.refresh_pin_map()
        self.assertEqual(win.pinmap_table.topLevelItemCount(), 0)
        self.assertIn("Place an MCU", win.pinmap_status.text())
        win.close()

    def test_serial_console_displays_and_filters(self):
        self.win._serial.write(
            "BUCK_CTRL: Loop: 10000 | Raw ADC: 2010 | Gate: ON\r\n"
            "boot ok\r\nESP_ERROR: brownout\r\n")
        self.win._render_serial()
        self.assertEqual(self.win.serial_view.toPlainText().count("\n"), 2)
        self.assertIn("3 line(s)", self.win.serial_status.text())

        self.win.serial_filter.setText("gate")
        self.win._refresh_serial_filter("gate")
        text = self.win.serial_view.toPlainText()
        self.assertIn("Gate: ON", text)
        self.assertNotIn("brownout", text)
        self.assertIn("matching", self.win.serial_status.text())

    def test_clear_empties_the_console(self):
        self.win._serial.write("something\n")
        self.win._render_serial()
        self.win.clear_serial()
        self.assertEqual(self.win.serial_view.toPlainText(), "")
        self.assertEqual(self.win._serial.count, 0)


class TestBinaryCosimBranch(unittest.TestCase):
    """WOSP_USE_BINARY_COSIM must route the editor through the firmware path.

    The QEMU half is replaced with a synthetic CosimRun: this pins the UI
    wiring (which kwargs are passed, how warnings and aborts are surfaced,
    and that a launcher exception cannot leave run/aborted unbound).
    """

    def setUp(self):
        self.win = SchematicEditor()
        self.win.model.load_dict(arduino_circuit().to_dict())
        self.win.scene.rebuild()
        self.win.ng = SimpleNamespace(
            _stop_requested=False, timestep_count=0, progress_callback=None)

    def tearDown(self):
        self.win.close()

    @staticmethod
    def _fake_run(aborted=False):
        from bridge.cosim_runner import CosimRun
        run = CosimRun()
        run.time = [0.0, 0.0005, 0.001]
        run.traces = {"led": [0.0, 3.3, 3.3]}
        run.nets = ["led"]
        run.netlist = ["* firmware-in-the-loop run"]
        run.callback_hits = 3
        run.aborted = aborted
        run.warnings = ["synthetic warning"]
        return run

    def test_binary_mode_passes_the_model_and_uses_the_returned_run(self):
        from bridge import binary_runner
        run = self._fake_run()
        seen = {}

        def fake(model, pin_specs, **kwargs):
            seen["model"] = model
            seen["pin_specs"] = pin_specs
            seen["kwargs"] = kwargs
            return run

        with mock.patch.dict(os.environ, {"WOSP_USE_BINARY_COSIM": "1"}), \
                mock.patch.object(binary_runner, "run_binary_cosim",
                                  side_effect=fake):
            self.win.run_closed_loop({"D5": {"sense_net": "led"}})

        self.assertIs(seen["model"], self.win.model)
        self.assertEqual(seen["pin_specs"], {"D5": {"sense_net": "led"}})
        self.assertEqual(seen["kwargs"]["vin"], 12.0)
        self.assertIn("REAL FIRMWARE BINARY",
                      self.win.console.toPlainText())
        self.assertIn("* firmware-in-the-loop run",
                      self.win.netlist_view.toPlainText())
        self.assertEqual(self.win._last_traces["led"], [0.0, 3.3, 3.3])
        self.assertFalse(self.win._running)
        self.assertEqual(self.win.progress.value(), 100)

    def test_binary_warning_reaches_the_console(self):
        from bridge import binary_runner
        with mock.patch.dict(os.environ, {"WOSP_USE_BINARY_COSIM": "1"}), \
                mock.patch.object(binary_runner, "run_binary_cosim",
                                  return_value=self._fake_run()):
            self.win.run_closed_loop({"D5": {"sense_net": "led"}})
        self.assertIn("synthetic warning", self.win.console.toPlainText())

    def test_binary_abort_is_reported(self):
        from bridge import binary_runner
        with mock.patch.dict(os.environ, {"WOSP_USE_BINARY_COSIM": "1"}), \
                mock.patch.object(binary_runner, "run_binary_cosim",
                                  return_value=self._fake_run(aborted=True)):
            self.win.run_closed_loop({"D5": {"sense_net": "led"}})
        self.assertIn("stopped early", self.win.console.toPlainText())

    def test_launcher_exception_does_not_leave_run_unbound(self):
        from bridge import binary_runner
        with mock.patch.dict(os.environ, {"WOSP_USE_BINARY_COSIM": "1"}), \
                mock.patch.object(binary_runner, "run_binary_cosim",
                                  side_effect=RuntimeError("no emulator")):
            self.win.run_closed_loop({"D5": {"sense_net": "led"}})
        # The old finally block read `run` before assignment and raised a
        # NameError that masked this message.
        self.assertIn("ERROR: binary cosim failed: no emulator",
                      self.win.console.toPlainText())
        self.assertFalse(self.win._running)
        self.assertFalse(self.win.stop_button.isEnabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
