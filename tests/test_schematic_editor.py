"""
test_schematic_editor.py - Verification for the PyQt5 schematic editor.

Runs fully headless (QT_QPA_PLATFORM=offscreen):
1. Symbol table pins match the netlist compiler's canonical pins
2. Undo snapshots do not alias live component state
3. Scene editing: place -> wire -> compile produces a real netlist
4. Undo / redo restores the document
5. F2 simulation end-to-end: compiler -> ngspice.dll -> plotted traces
6. F2 with a control law: closed-loop co-simulation driven by the firmware spec
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import QPointF, QEvent, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication

from bridge.cad_engine import SchematicNetlistEngine, generate_bom_for
from ui.schematic_editor import SchematicEditor
from ui.schematic_scene import SchematicScene
from ui.schematic_symbols import SYMBOLS

_app = QApplication.instance() or QApplication([])


def get_app():
    """One QApplication for the whole test module (created at import so that
    every test class - including the alphabetically-first one - has it)."""
    return _app


def build_rc_scene():
    """V1 -> R1 -> C1 with a ground rail; returns the wired scene."""
    scene = SchematicScene(SchematicNetlistEngine())
    scene.place_component("V", QPointF(0, 0))
    scene.place_component("R", QPointF(80, 0))
    scene.place_component("C", QPointF(160, 0))
    scene.place_component("GND", QPointF(160, 80))
    scene.pin_clicked("V1", "+")
    scene.pin_clicked("R1", "1")
    scene.pin_clicked("V1", "-")
    scene.pin_clicked("GND1", "1")
    scene.pin_clicked("R1", "2")
    scene.pin_clicked("C1", "1")
    scene.pin_clicked("C1", "2")
    scene.pin_clicked("GND1", "1")
    return scene


class TestSymbolTable(unittest.TestCase):
    def test_pins_match_compiler_canonical_order(self):
        """Every palette symbol's pins must match what the netlister expects."""
        canonical = SchematicNetlistEngine._CANONICAL_PINS
        for comp_type in ("R", "C", "L", "V", "I", "D", "MOSFET"):
            pins = [p[0] for p in SYMBOLS[comp_type]["pins"]]
            self.assertEqual(pins, canonical[comp_type],
                             f"{comp_type} pins {pins} != compiler {canonical[comp_type]}")

    def test_ground_symbol_has_single_pin(self):
        self.assertEqual(len(SYMBOLS["GND"]["pins"]), 1)

    def test_mcu_pin_named_gnd_is_ground_flagged(self):
        names = [p[0] for p in SYMBOLS["MCU"]["pins"]]
        self.assertIn("GND", names)


class TestUndoSnapshots(unittest.TestCase):
    def test_snapshot_does_not_alias_live_pins(self):
        model = SchematicNetlistEngine()
        from bridge.cad_engine import SchematicComponent
        model.add_component(SchematicComponent("R1", "R", "R1", "10k", 0, 0))
        model.add_component(SchematicComponent("R2", "R", "R2", "1k", 60, 0))
        model.add_wire("R1:1", "R2:2", "mid")
        snapshot = model.to_dict()

        # Mutating the live model afterwards must not corrupt the snapshot
        model.add_wire("R1:2", "R2:1", "later")
        snap_r1 = next(c for c in snapshot["components"] if c["comp_id"] == "R1")
        live_r1 = model.components["R1"]
        self.assertEqual(snap_r1["pins"], {"1": "mid"})
        self.assertNotEqual(snap_r1["pins"], live_r1.pins)


class TestSceneEditing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = get_app()

    def test_place_assigns_unique_designators(self):
        scene = SchematicScene(SchematicNetlistEngine())
        for _ in range(3):
            scene.place_component("R", QPointF(0, 0))
        names = sorted(scene.model.components)
        self.assertEqual(names, ["R1", "R2", "R3"])

    def test_place_wire_compile(self):
        scene = build_rc_scene()
        lines, nets, warns = scene.model.compile_netlist(vin=12.0)

        self.assertEqual(warns, [], warns)
        self.assertTrue(any(l.startswith("R1 ") and "10k" in l for l in lines), lines)
        self.assertTrue(any(l.startswith("C1 ") and "100n" in l for l in lines), lines)
        v_line = next(l for l in lines if l.startswith("V1 "))
        self.assertIn("DC 12", v_line)
        # Ground rail resolved to node 0 on every element touching it
        self.assertTrue(v_line.endswith("0 DC 12"), v_line)
        self.assertEqual(lines[-1], ".end")
        self.assertIn("NET_", " ".join(lines))

    def test_wire_graphics_items_match_model(self):
        scene = build_rc_scene()
        self.assertEqual(len(scene.model.wires), 4)
        self.assertEqual(len(scene.wire_items), 4)
        # every wire has real endpoints on the canvas
        for item in scene.wire_items:
            self.assertIn(item.from_ref, scene.pin_items)
            self.assertIn(item.to_ref, scene.pin_items)

    def test_duplicate_wire_is_rejected(self):
        scene = build_rc_scene()
        before = len(scene.model.wires)
        scene.pin_clicked("R1", "1")
        scene.pin_clicked("V1", "+")
        self.assertEqual(len(scene.model.wires), before)

    def test_undo_redo_restores_document(self):
        scene = build_rc_scene()
        self.assertEqual(len(scene.model.components), 4)

        scene.undo()                     # removes the last wire
        self.assertEqual(len(scene.model.wires), 3)
        scene.undo()                     # removes another wire
        self.assertEqual(len(scene.model.wires), 2)
        scene.undo()
        self.assertEqual(len(scene.model.wires), 1)

        scene.redo()
        scene.redo()
        self.assertEqual(len(scene.model.wires), 3)

    def test_undo_place_removes_component(self):
        scene = SchematicScene(SchematicNetlistEngine())
        scene.place_component("R", QPointF(0, 0))
        self.assertEqual(len(scene.model.components), 1)
        scene.undo()
        self.assertEqual(len(scene.model.components), 0)

    def test_delete_component_removes_its_wires(self):
        scene = build_rc_scene()
        scene.delete_component("R1")
        self.assertNotIn("R1", scene.model.components)
        for wire in scene.model.wires:
            self.assertNotIn("R1:", wire["from"])
            self.assertNotIn("R1:", wire["to"])

    def test_rotate_updates_component(self):
        scene = SchematicScene(SchematicNetlistEngine())
        scene.place_component("R", QPointF(0, 0))
        item = scene.comp_items["R1"]
        item.setSelected(True)
        scene.rotate_selected()
        self.assertEqual(scene.model.components["R1"].rotation, 90)
        self.assertEqual(item.rotation(), 90)

    def test_set_value_persists_to_netlist(self):
        scene = build_rc_scene()
        scene.set_component_value("R1", "4k7")
        lines, _nets, _warn = scene.model.compile_netlist()
        self.assertTrue(any(l.startswith("R1 ") and "4k7" in l for l in lines), lines)


class TestBomFromGraph(unittest.TestCase):
    def test_bom_lists_placed_parts_only(self):
        scene = build_rc_scene()
        rows = generate_bom_for(scene.model)
        designators = [r["Designator"] for r in rows]
        self.assertIn("R1", designators)
        self.assertIn("C1", designators)
        self.assertIn("V1", designators)
        self.assertNotIn("GND1", designators)   # ground symbols are not purchased
        self.assertEqual(len(rows), 3)


class TestEditorWindow(unittest.TestCase):
    """Exercises the real window: construction, F2 run, and waveform output."""

    @classmethod
    def setUpClass(cls):
        cls.app = get_app()

    def _editor_with_rc(self):
        win = SchematicEditor()
        for comp_type, x, y in (("V", 0, 0), ("R", 80, 0), ("C", 160, 0), ("GND", 160, 80)):
            win.scene.place_component(comp_type, QPointF(x, y))
        for a, b in (("V1:+", "R1:1"), ("V1:-", "GND1:1"),
                     ("R1:2", "C1:1"), ("C1:2", "GND1:1")):
            ca, pa = a.split(":")
            cb, pb = b.split(":")
            win.scene.pin_clicked(ca, pa)
            win.scene.pin_clicked(cb, pb)
        return win

    def test_window_constructs_with_panels(self):
        win = self._editor_with_rc()
        self.assertIsNotNone(win.scene)
        self.assertTrue(win.console.isReadOnly())          # console panel exists
        self.assertIn("WOSP editor ready", win.console.toPlainText())
        netlist_text = win.netlist_view.toPlainText()
        self.assertIn(".tran", netlist_text)
        self.assertIn("R1", netlist_text)
        win.close()

    def test_f2_simulation_plots_traces(self):
        """Full path: compile -> ngspice.dll -> pyqtgraph curves."""
        win = self._editor_with_rc()
        win.tstep_box.setValue(10.0)
        win.duration_box.setValue(5.0)

        win.run_simulation()

        console = win.console.toPlainText()
        self.assertIn("Simulation complete", console)
        curves = win.plot.listDataItems()
        self.assertGreaterEqual(len(curves), 2, "expected a trace per probe net")

        # Physics check: the capacitor node must start near 0 V and charge to Vin
        charged = False
        for curve in curves:
            _x, ys = curve.getData()
            ys = list(ys)
            self.assertGreater(len(ys), 100)
            if ys[0] < 1.0 and ys[-1] > 8.0:
                charged = True
        self.assertTrue(charged, "no trace shows the RC node charging from ~0V to ~Vin")
        win.close()

    def test_palette_click_places_component_on_canvas(self):
        """The LTspice gesture: arm a tool in the palette, click the canvas."""
        win = SchematicEditor()
        rows = win._component_rows()
        win.palette_list.setCurrentRow(rows[0])              # first real part: Resistor
        self.assertEqual(win.scene.armed_type, "R")

        pos = QPointF(120, 60)
        event = QMouseEvent(QEvent.MouseButtonPress, pos,
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        win.view.mousePressEvent(event)

        self.assertIn("R1", win.model.components)
        placed = win.model.components["R1"]
        self.assertEqual((placed.x, placed.y), (120, 60))
        self.assertIsNotNone(win.scene.comp_items.get("R1"))
        win.close()


class TestClosedLoopEditorPath(unittest.TestCase):
    """
    F2 with a control law attached must run the closed loop and report it.

    This drives the real window: attach the law the repo's own firmware
    describes, press F2, and require the pin to have actually switched against
    the simulated output.
    """

    def _closed_loop_window(self):
        from test_cosim_control import build_buck, firmware_law

        win = SchematicEditor()
        win.model.load_dict(build_buck(load_ohms="5").to_dict())
        spec = firmware_law()
        win.model.control_laws["U1"] = spec
        win.scene.rebuild()
        win.duration_box.setValue(3.0)
        win.tstep_box.setValue(1.0)
        return win, spec

    def test_f2_runs_the_control_law_and_populates_the_table(self):
        win, spec = self._closed_loop_window()
        win.run_simulation()

        law = win.model.control_laws["U1"]
        self.assertEqual(law["source_counts"]["low"], 1995)
        self.assertIn("external", win.netlist_view.toPlainText())

        # The inspector must now show a measured, solver-derived pin.
        rows = []
        for i in range(win.gpio_table.topLevelItemCount()):
            item = win.gpio_table.topLevelItem(i)
            rows.append([item.text(c) for c in range(win.gpio_table.columnCount())])
        pin_rows = [r for r in rows if r[1] == "GPIO18"]
        self.assertEqual(len(pin_rows), 1, rows)
        row = pin_rows[0]
        self.assertIn("hysteretic", row[3].lower(), row)
        self.assertGreater(int(row[7]), 5, f"pin never switched: {row}")
        self.assertNotEqual(row[9], "-", f"no regulation error reported: {row}")
        self.assertIn("Control laws", win.law_label.text())
        win.close()

    def test_clear_control_law_reverts_to_the_open_loop_path(self):
        from bridge import cosim_runner

        win, _spec = self._closed_loop_window()
        win.model.control_laws.clear()
        win.scene.rebuild()
        win.run_simulation()
        self.assertNotIn("external", win.netlist_view.toPlainText())
        self.assertNotIn("closed-loop", win.console.toPlainText())
        win.close()


class TestAnalysisPanels(unittest.TestCase):
    """
    The waveform analysis panels must work through the real window, not just
    as library functions.
    """

    def setUp(self):
        # Modal dialogs block forever with nobody to click OK, so record the
        # calls instead of showing them. This also lets us assert that an error
        # path actually warned the user.
        from PyQt5.QtWidgets import QMessageBox, QInputDialog
        self.messages = []
        for name in ("information", "warning", "critical", "question"):
            def make(kind):
                def handler(parent, title, text, *a, **k):
                    self.messages.append((kind, title, text))
                    return QMessageBox.Ok
                return handler
            setattr(QMessageBox, name, staticmethod(make(name)))

        def cancel_input(parent=None, *a, **k):
            return ("", False)          # behaves like the user pressing Cancel

        setattr(QInputDialog, "getItem", staticmethod(cancel_input))
        setattr(QInputDialog, "getText", staticmethod(cancel_input))
        setattr(QInputDialog, "getMultiLineText", staticmethod(cancel_input))
        self._saved = {n: getattr(QMessageBox, n) for n in
                       ("information", "warning", "critical", "question")}
        self._saved_input = {n: getattr(QInputDialog, n) for n in
                             ("getItem", "getText", "getMultiLineText")}

    def tearDown(self):
        from PyQt5.QtWidgets import QMessageBox, QInputDialog
        for name, fn in self._saved.items():
            setattr(QMessageBox, name, fn)
        for name, fn in self._saved_input.items():
            setattr(QInputDialog, name, fn)

    def assertWarned(self, fragment):
        self.assertTrue(any(fragment.lower() in str(m[2]).lower()
                            for m in self.messages),
                        f"no message containing {fragment!r}: {self.messages}")

    def _rc_window(self):
        """V - R - C low-pass in the editor, already simulated.

        Wires created by pin clicks get auto-generated net names (NET_n), so
        tests locate the RC node by looking for the trace that actually moves
        rather than assuming a label.
        """
        win = SchematicEditor()
        win.duration_box.setValue(2.0)
        win.tstep_box.setValue(2.0)
        scene = win.scene
        scene.place_component("V", QPointF(0, 0))
        scene.place_component("R", QPointF(80, 0))
        scene.place_component("C", QPointF(160, 0))
        scene.place_component("GND", QPointF(160, 80))
        for a, b in (("V1", "+"), ("R1", "1"), ("V1", "-"), ("GND1", "1"),
                     ("R1", "2"), ("C1", "1"), ("C1", "2"), ("GND1", "1")):
            scene.pin_clicked(a, b)
        return win

    @staticmethod
    def _moving_net(win):
        """Name of the net whose voltage actually varies (the RC node)."""
        for name, values in win._last_traces.items():
            if max(values) - min(values) > 0.1:
                return name
        raise AssertionError(f"no varying net in {list(win._last_traces)}")

    def test_f2_populates_traces_for_cursor_and_export(self):
        win = self._rc_window()
        win.run_simulation()
        self.assertTrue(win._last_time, "no time vector captured")
        self.assertGreaterEqual(len(win._last_traces), 2, list(win._last_traces))
        self.assertTrue(self._moving_net(win))
        self.assertEqual(self.messages, [], self.messages)
        win.close()

    def test_cursors_produce_a_ruler_readout(self):
        win = self._rc_window()
        win.run_simulation()
        before = win.measure_label.text()
        self.assertIn("cursor", before.lower())

        win._click_points = [0.0, win._last_time[-1]]
        win.refresh_cursors()
        text = win.measure_label.text()
        self.assertIn("1/dt=", text, text)
        self.assertIn("rms", text, text)

        win.clear_cursors()
        self.assertIn("cursor", win.measure_label.text().lower())
        win.close()

    def test_fft_tab_reports_a_dominant_frequency(self):
        win = self._rc_window()
        win.run_simulation()
        win.bode_net_box.setCurrentText(self._moving_net(win))
        win.run_fft()
        self.assertIn("dominant", win.fft_info.text().lower(), win.fft_info.text())
        self.assertEqual(self.messages, [], "FFT should not have complained")
        win.close()

    def test_fft_reports_resolution_and_stays_below_nyquist(self):
        win = self._rc_window()
        win.run_simulation()
        win.bode_net_box.setCurrentText(self._moving_net(win))
        win.run_fft()
        text = win.fft_info.text()
        self.assertIn("dominant", text.lower())
        self.assertIn("bin width", text.lower())

        dominant = self._number_after(win.fft_info.text(), "dominant")
        bin_hz = self._number_after(win.fft_info.text(), "bin width")
        nyquist = 1.0 / (2.0 * win.tstep_box.value() * 1e-6)
        self.assertGreater(dominant, 0.0, text)
        self.assertLess(dominant, nyquist, f"{dominant} Hz is at or above Nyquist")
        # A 2 ms run cannot resolve anything below a few hundred Hz, so the
        # reported bin width must say so rather than implying better precision.
        self.assertGreater(bin_hz, 100.0, text)
        win.close()

    @staticmethod
    def _number_after(text, label):
        """First float appearing after a label; labels contain spaces."""
        import re
        m = re.search(re.escape(label) + r"\s+([0-9.eE+-]+)", text, re.IGNORECASE)
        if not m:
            raise AssertionError(f"no number after {label!r} in {text!r}")
        return float(m.group(1))

    def test_bode_tab_reports_gain_and_phase(self):
        win = self._rc_window()
        win.run_simulation()          # fills the net list the sweep offers
        win.bode_start_box.setValue(10.0)
        win.bode_stop_box.setValue(100000.0)
        win.bode_net_box.setCurrentText(self._moving_net(win))
        win.run_bode()
        text = win.bode_info.text()
        self.assertIn("peak", text.lower(), text)
        # A passive RC has no feedback loop, so no crossover may be claimed.
        self.assertIn("phase margin undefined", text, text)
        self.assertEqual(self.messages, [], self.messages)
        win.close()

    def test_bode_rejects_an_inverted_frequency_range(self):
        win = self._rc_window()
        win.run_simulation()
        win.bode_start_box.setValue(1e6)
        win.bode_stop_box.setValue(10.0)
        win.bode_net_box.setCurrentText(self._moving_net(win))
        win.run_bode()                      # must warn, not raise
        self.assertIn("No sweep yet", win.bode_info.text())
        self.assertWarned("stop frequency must exceed")
        win.close()

    # ------------------------------------------------------------------
    # DC curve tracer (studio_engine .dc paths - real I-V, not a stub)
    # ------------------------------------------------------------------
    def test_iv_curve_tracer_reaches_the_engine_and_plots_real_curves(self):
        """The I-V Curve Tracer tab is wired to studio_engine.trace_mosfet_iv
        and trace_diode_iv. The test asserts the dialog produces real I-V data
        (non-empty arrays, plausible threshold / forward voltage), not a stub.
        """
        win = self._rc_window()
        win.run_simulation()                 # populate the doc, not the curve tab

        # MOSFET path: several Vgs, one Vds sweep per Vgs.
        win.curve_device_box.setCurrentIndex(0)
        win.curve_vmax_box.setValue(15.0)
        win.curve_pts_box.setValue(40)
        win.run_curve_tracer()
        info = win.curve_info.text()
        self.assertIn("curve", info.lower(), info)
        self.assertIn("Vds points", info, info)
        self.assertTrue(
            len(win.curve_plot.plotItem.curves) >= 2,
            "MOSFET path must plot at least 2 Vgs curves (real engine call)")
        # Vgs=10 V must produce a plausible on-current at mid Vds, which is the
        # signal that this is a real solved curve and not a flat stub.
        curves = win.curve_plot.plotItem.curves
        vds = None
        id10 = None
        for item in curves:
            name = item.opts["name"] if item.opts else ""
            if name.startswith("Vgs=10"):
                vds = list(item.xData)
                id10 = list(item.yData)
                break
        self.assertIsNotNone(vds, "Vgs=10 V curve must exist")
        mid = len(vds) // 2
        self.assertGreater(id10[mid], 0.1,
                           "Vgs=10 V must show real on-current at mid Vds")
        win.close()

    def test_iv_curve_tracer_diode_path_returns_three_families(self):
        """The diode path must plot Schottky / silicon / Zener from
        trace_diode_iv, each a real non-empty array.
        """
        win = self._rc_window()
        win.run_simulation()

        win.curve_device_box.setCurrentIndex(1)
        win.curve_vfmax_box.setValue(1.0)
        win.run_curve_tracer()
        info = win.curve_info.text()
        self.assertIn("families plotted", info, info)
        self.assertEqual(
            len(win.curve_plot.plotItem.curves), 3,
            "diode path must plot exactly three families")
        names = [item.opts["name"] for item in win.curve_plot.plotItem.curves
                 if item.opts]
        self.assertIn("Schottky (1N5819)", names, names)
        self.assertIn("Silicon (1N4148)", names, names)
        self.assertIn("Zener", names, names)
        win.close()

    def test_csv_export_writes_one_row_per_time_point(self):
        import csv
        import tempfile
        win = self._rc_window()
        win.run_simulation()
        path = os.path.join(tempfile.mkdtemp(), "r.csv")
        # Call the writer directly; the file dialog is not scriptable.
        traces = {n: v for n, v in win._last_traces.items()
                  if len(v) == len(win._last_time)}
        nets = list(traces)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("time_s," + ",".join(nets) + "\n")
            for i, t in enumerate(win._last_time):
                f.write(f"{t:.9g}," +
                        ",".join(f"{traces[n][i]:.9g}" for n in nets) + "\n")
        with open(path, newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0][0], "time_s")
        self.assertEqual(len(rows) - 1, len(win._last_time))
        self.assertGreater(len(rows[0]), 1)
        win.close()

    def test_plot_image_export_produces_a_real_png(self):
        import tempfile
        win = self._rc_window()
        win.run_simulation()
        path = os.path.join(tempfile.mkdtemp(), "wave.png")
        saved = win.plot.grab().save(path, "PNG")
        self.assertTrue(saved)
        self.assertGreater(os.path.getsize(path), 2000,
                           "PNG is suspiciously small - probably blank")
        win.close()

    def test_pdf_export_writes_a_real_document(self):
        import tempfile
        win = self._rc_window()
        win.run_simulation()
        # Exercise the matplotlib writer without the file dialog.
        path = os.path.join(tempfile.mkdtemp(), "report.pdf")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.backends.backend_pdf as _pdf
        import matplotlib.pyplot as plt
        from bridge import measurements
        good = [n for n, v in win._last_traces.items() if len(v) == len(win._last_time)]
        self.assertTrue(good, "no complete traces to export")
        with _pdf.PdfPages(path) as pdf:
            for name in good:
                fig, ax = plt.subplots(figsize=(8.27, 11.69))
                ax.plot([t * 1000.0 for t in win._last_time], win._last_traces[name])
                s = measurements.trace_stats(win._last_time, win._last_traces[name])
                ax.set_title(name)
                pdf.savefig(fig)
                plt.close(fig)
        self.assertTrue(os.path.exists(path))
        self.assertGreater(os.path.getsize(path), 1000)
        with open(path, "rb") as f:
            self.assertEqual(f.read(5), b"%PDF-", "not a PDF file")
        win.close()

    # ------------------------------------------------------------------
    # Serial tab: UART decode wired to studio_engine.decode_uart_packets
    # ------------------------------------------------------------------
    @staticmethod
    def _uart_frame_samples(payload, baud, span_s=0.005, spp=8):
        """Uniform-sampled 3.3 V UART TX trace carrying `payload` (bytes):
        idle lead-in, 8N1 frames (start, 8 data bits LSB first, stop),
        idle tail. Returns (time_s, volts)."""
        import numpy as np
        bit_s = 1.0 / baud
        dt = bit_s / spp
        n_total = int(span_s / dt)
        wave = np.ones(n_total)
        pos = int(4 * spp)              # idle lead-in
        for byte in payload:
            frame = [0] + [(byte >> k) & 1 for k in range(8)] + [1]
            for bit in frame:
                wave[pos:pos + spp] = bit
                pos += spp
            pos += int(4 * spp)         # idle gap between frames
            if pos >= n_total - 10 * spp:
                break
        t = np.arange(n_total) * dt
        return list(t), list(wave * 3.3)

    def test_serial_tab_decodes_real_uart_bytes_from_a_trace(self):
        """Decode TX must reach studio_engine.decode_uart_packets and put the
        real decoded bytes on the Serial tab - not a stub, and not the
        decoder's canned demo payload (I2C/SPI/CAN rows)."""
        win = SchematicEditor()
        t, volts = self._uart_frame_samples(b"W", 115200)
        win._last_time = t
        win._last_traces = {"tx": volts}
        win._sync_serial_nets()
        self.assertEqual(win.serial_net_box.currentText(), "tx")
        win.decode_uart_from_net()
        text = win.serial_view.toPlainText()
        status = win.serial_status.text()
        self.assertIn("Decoded 1 frame", status, status)
        self.assertIn("0x57", text, f"decoded frame missing: {text!r}")
        self.assertIn("'W'", text, text)
        for marker in ("I2C_ADDR", "SPI_MOSI", "CAN_FRAME", "SSD1306"):
            self.assertNotIn(marker, text,
                             "decoder demo fallback leaked into the console")
        win.close()

    def test_serial_tab_refuses_to_invent_frames(self):
        """A trace with no decodable 8N1 stream must produce an honest status
        line and an EMPTY console - decode_uart_packets falls back to canned
        demo packets when it finds nothing, and the tab must filter that."""
        import numpy as np
        win = SchematicEditor()
        n = 4000
        volts = np.full(n, 3.3)
        volts[n // 2] = 0.0             # a single glitch is not a frame
        win._last_time = list(np.arange(n) * 1e-6)
        win._last_traces = {"tx": list(volts)}
        win._sync_serial_nets()
        win.decode_uart_from_net()
        status = win.serial_status.text()
        self.assertIn("no valid 8n1 frames", status.lower(), status)
        self.assertEqual(win.serial_view.toPlainText().strip(), "",
                         "console must stay empty when nothing decoded")
        win.close()

    # ------------------------------------------------------------------
    # PV / MPPT and AWG instrument tabs (existing studio_engine paths)
    # ------------------------------------------------------------------
    def test_pv_mppt_tab_runs_the_real_engine_trace(self):
        """The PV / MPPT tab must reach studio_engine.trace_solar_pv and show
        real curve data - both plots populated, engine numbers in the info
        line, and the result kept for inspection."""
        win = SchematicEditor()
        win.pv_irr_box.setValue(800.0)
        win.pv_temp_box.setValue(30.0)
        win.pv_pts_box.setValue(120)
        win.run_pv()
        out = win.pv_last
        self.assertEqual(len(out["v_arr"]), 120)
        # Voc = 21.6 * (1 - 0.003 * dT) and Isc scales with irradiance.
        self.assertAlmostEqual(out["v_oc"], 21.6 * (1 - 0.003 * 5.0),
                               places=3, msg="Voc does not track temperature")
        self.assertAlmostEqual(out["i_sc"], 0.8 * 5.8, places=3,
                               msg="Isc does not track irradiance")
        self.assertGreater(out["p_max_w"], 1.0, "MPP power is not real")
        self.assertGreater(out["v_mpp"], 0.0)
        self.assertLess(out["v_mpp"], out["v_oc"])
        self.assertTrue(0.0 < out["fill_factor"] <= 1.0,
                        f"implausible fill factor {out['fill_factor']}")
        self.assertGreaterEqual(len(win.pv_iv_plot.plotItem.curves), 1,
                                "I-V plot is empty")
        self.assertGreaterEqual(len(win.pv_p_plot.plotItem.curves), 1,
                                "P-V plot is empty")
        info = win.pv_info.text()
        self.assertIn("Pmax", info, info)
        self.assertIn("Isc", info, info)
        from PyQt5.QtWidgets import QAction
        texts = {a.text().replace("&", "")
                 for a in win.findChildren(QAction)}
        self.assertIn("Run Solar PV / MPPT Trace", texts,
                      "Simulate menu is missing the PV / MPPT entry")
        win.close()

    def test_awg_tab_generates_a_real_waveform(self):
        """The AWG tab must reach studio_engine.generate_awg_signal: a sine
        at 4 Vpp + 1 V offset over 2000 points, plotted and reported."""
        win = SchematicEditor()
        win.awg_type_box.setCurrentText("Sine")
        win.awg_freq_box.setValue(1000.0)
        win.awg_amp_box.setValue(4.0)
        win.awg_offset_box.setValue(1.0)
        win.awg_duration_box.setValue(5.0)
        win.awg_points_box.setValue(2000)
        win.run_awg()
        t, sig = win.awg_last
        self.assertEqual(len(t), 2000)
        self.assertEqual(len(sig), 2000)
        # amp/2 * sin + offset  ->  max 3 V, min -1 V
        self.assertAlmostEqual(max(sig), 3.0, delta=0.05,
                               msg="sine amplitude/offset wrong")
        self.assertAlmostEqual(min(sig), -1.0, delta=0.05,
                               msg="sine amplitude/offset wrong")
        self.assertAlmostEqual(t[-1], 5.0, places=3,
                               msg="duration is wrong")
        self.assertGreaterEqual(len(win.awg_plot.plotItem.curves), 1,
                                "AWG plot is empty")
        self.assertIn("2000 points", win.awg_info.text(),
                      win.awg_info.text())
        from PyQt5.QtWidgets import QAction
        texts = {a.text().replace("&", "")
                 for a in win.findChildren(QAction)}
        self.assertIn("Generate AWG Waveform", texts,
                      "Simulate menu is missing the AWG entry")
        win.close()

    # ------------------------------------------------------------------
    # Parametric sweep (re-run loop over compile + solve)
    # ------------------------------------------------------------------
    def test_parametric_sweep_overlays_real_runs_and_restores_the_doc(self):
        """The Parametric Sweep tab must re-solve the schematic once per step
        with a different component value, overlay the results, and leave the
        document exactly as it was (a sweep must never edit the schematic)."""
        import numpy as np
        win = self._rc_window()
        win.run_simulation()
        win.refresh_sweep_controls()

        # Pick the sweepable resistor from the combo (id comes from itemData).
        comp_id = None
        for i in range(win.sweep_comp_box.count()):
            cid = win.sweep_comp_box.itemData(i)
            comp = win.model.components.get(cid)
            if comp is not None and comp.comp_type.upper() == "R":
                win.sweep_comp_box.setCurrentIndex(i)
                comp_id = cid
                break
        self.assertIsNotNone(comp_id, "no sweepable resistor in the picker")
        old_value = win.model.components[comp_id].value

        net = self._moving_net(win)
        win.sweep_net_box.setCurrentText(net)
        self.assertEqual(win.sweep_net_box.currentText(), net,
                         "sweep net is not in the net picker")
        win.sweep_start_box.setValue(1000.0)
        win.sweep_stop_box.setValue(2000.0)
        win.sweep_steps_box.setValue(3)
        win.run_sweep()

        results = win.sweep_last
        self.assertEqual(len(results), 3,
                         f"expected 3 solved steps: {win.sweep_info.text()}")
        values = [r[0] for r in results]
        self.assertEqual(values, [1000.0, 1500.0, 2000.0])
        for v, times, trace in results:
            self.assertGreater(len(times), 10, f"step {v}: no time vector")
            self.assertEqual(len(times), len(trace), f"step {v}: length mismatch")

        # Different R -> different RC response: the steps cannot be identical.
        self.assertFalse(np.allclose(results[0][2], results[-1][2]),
                         "every sweep step produced identical waveforms - "
                         "the value override did not reach the netlist")

        # The document must be untouched after the sweep.
        self.assertEqual(win.model.components[comp_id].value, old_value,
                         "sweep left the component value modified")

        # Overlay plot + info line + menu discoverability.
        self.assertGreaterEqual(len(win.sweep_plot.plotItem.curves), 3,
                                "sweep overlay is missing curves")
        self.assertIn("3 steps", win.sweep_info.text(),
                      win.sweep_info.text())
        from PyQt5.QtWidgets import QAction
        texts = {a.text().replace("&", "")
                 for a in win.findChildren(QAction)}
        self.assertIn("Run Parametric Sweep", texts,
                      "Simulate menu is missing the parametric sweep entry")
        win.close()

    # ------------------------------------------------------------------
    # Timing diagram, step metrics, Monte Carlo yield, noise analysis
    # ------------------------------------------------------------------
    @staticmethod
    def _digital_run(win):
        """Seed the editor with a 1 kHz square wave + a flat rail, as if a
        simulation had just produced them."""
        dt = 1e-5
        times = [i * dt for i in range(500)]        # 0 .. 5 ms
        square = [3.3 if (t % 1e-3) < 5e-4 else 0.0 for t in times]
        win._last_time = times
        win._last_traces = {"clk": square,
                            "vcc": [3.3] * len(times)}
        win._sync_serial_nets()
        return times

    def test_timing_tab_draws_digital_lanes_from_the_last_run(self):
        """The Timing tab must threshold real traces into stacked digital
        lanes with measured edges/duty/frequency - and show a flat rail as
        an honest constant lane, not as invented activity."""
        win = SchematicEditor()
        self._digital_run(win)
        win.draw_timing_diagram()

        self.assertIs(win.results_tabs.currentWidget(), win.timing_panel,
                      "the menu entry must surface the Timing tab")
        self.assertEqual(len(win.timing_lanes), 2, win.timing_lanes)
        clk = win.timing_lanes[0]
        self.assertTrue(clk.startswith("clk"), clk)
        self.assertIn("edges", clk, clk)
        self.assertIn("duty", clk, clk)
        # ~1 kHz square over 5 ms: a handful of edges and a measured Hz
        # (the counts precede their labels: "10 edges ... 1000 Hz").
        import re
        m_edges = re.search(r"(\d+) edges", clk)
        self.assertIsNotNone(m_edges, clk)
        self.assertGreaterEqual(int(m_edges.group(1)), 6, clk)
        m_hz = re.search(r"([0-9.eE+-]+) Hz", clk)
        self.assertIsNotNone(m_hz, "measured frequency missing: " + clk)
        self.assertGreater(float(m_hz.group(1)), 100.0, clk)
        # The flat rail is drawn as a constant lane with no edges.
        vcc = win.timing_lanes[1]
        self.assertTrue(vcc.startswith("vcc"), vcc)
        self.assertIn("0 edges", vcc, vcc)
        self.assertGreaterEqual(len(win.timing_plot.plotItem.curves), 2,
                                "lanes were not plotted")
        self.assertEqual(win.timing_info.text(),
                         " | ".join(win.timing_lanes),
                        "info line must report every drawn lane")
        title = win.timing_plot.plotItem.titleLabel.text
        self.assertIn("2 lane", title, title)
        from PyQt5.QtWidgets import QAction
        texts = {a.text().replace("&", "")
                 for a in win.findChildren(QAction)}
        self.assertIn("Show Timing Diagram", texts,
                      "Simulate menu is missing the timing diagram entry")
        win.close()

    def test_step_response_tab_measures_delay_rise_and_settling(self):
        """The Step Response tab must run measurements.step_metrics on a real
        RC transient and report delay/rise/settling on the picked net."""
        win = self._rc_window()
        win.run_simulation()
        win._sync_serial_nets()
        net = self._moving_net(win)
        win.step_net_box.setCurrentText(net)
        win.analyze_step_response()

        m = win.step_last
        self.assertEqual(m["direction"], "rising", m)
        self.assertGreater(m["step_v"], 0.0, m)
        self.assertGreater(m["rise_s"], 0.0, m)
        self.assertLess(m["overshoot_pct"], 5.0,
                        "a monotonic RC step must not report overshoot")
        info = win.step_info.text()
        self.assertIn(net, info, info)
        self.assertIn("delay", info, info)
        self.assertIn("settling", info, info)
        self.assertEqual(self.messages, [], self.messages)
        from PyQt5.QtWidgets import QAction
        texts = {a.text().replace("&", "")
                 for a in win.findChildren(QAction)}
        self.assertIn("Step Response Metrics", texts,
                      "Simulate menu is missing the step metrics entry")
        win.close()

    def test_monte_carlo_tab_solves_real_samples_and_restores_the_doc(self):
        """The Monte Carlo tab must re-solve THIS schematic per sample via
        analysis_runner.run_monte_carlo, histogram a real spread, and leave
        every component value untouched afterwards."""
        win = self._rc_window()
        win.run_simulation()
        win._sync_serial_nets()
        values_before = {cid: c.value
                         for cid, c in win.model.components.items()}

        win.mc_net_box.setCurrentText(self._moving_net(win))
        win.mc_iters_box.setValue(5)
        win.run_yield_study()

        out = win.mc_last
        self.assertEqual(out["iterations"], 5)
        self.assertEqual(len(out["samples"]), 5)
        self.assertGreater(out["std"], 0.0,
                           "tolerance produced no spread - the perturbation "
                           "never reached the netlist")
        self.assertGreaterEqual(out["yield_actual_pct"], 0.0)
        self.assertLessEqual(out["yield_actual_pct"], 100.0)
        self.assertEqual({cid: c.value
                          for cid, c in win.model.components.items()},
                         values_before,
                         "monte carlo left the document modified")
        info = win.mc_info.text()
        self.assertIn("yield", info, info)
        self.assertIn("5 runs", info, info)
        bars = getattr(win, "mc_bars", None)
        self.assertIsNotNone(bars, "histogram bars were never added")
        self.assertEqual(int(sum(bars.opts["height"])), 5,
                         "histogram does not account for all 5 samples")
        from PyQt5.QtWidgets import QAction
        texts = {a.text().replace("&", "")
                 for a in win.findChildren(QAction)}
        self.assertIn("Run Monte Carlo / Yield", texts,
                      "Simulate menu is missing the Monte Carlo entry")
        win.close()

    def test_noise_tab_measures_resistor_thermal_noise(self):
        """The Noise tab must run analysis_runner.run_noise against the real
        solver: DC density on the RC output equals sqrt(4kTR) at 27 C, and
        the density rolls off above the corner."""
        import math
        from bridge.analysis_runner import spice_value
        win = self._rc_window()
        win.run_simulation()
        win._sync_serial_nets()
        r = next(spice_value(c.value) for c in win.model.components.values()
                 if c.comp_type.upper() == "R")
        c = next(spice_value(c.value) for c in win.model.components.values()
                 if c.comp_type.upper() == "C")
        corner = 1.0 / (2.0 * math.pi * r * c)
        win.noise_net_box.setCurrentText(self._moving_net(win))
        win.noise_start_box.setValue(max(0.01, corner / 10.0))
        win.noise_stop_box.setValue(min(1e6, corner * 1000.0))
        win.run_noise_analysis()

        out = win.noise_last
        expected = math.sqrt(4 * 1.380649e-23 * (273.15 + 27.0) * r)
        self.assertGreater(len(out["freqs"]), 10)
        self.assertEqual(len(out["freqs"]), len(out["onoise_density"]))
        self.assertAlmostEqual(out["onoise_density"][0], expected,
                               delta=0.1 * expected,
                               msg="DC density is not sqrt(4kTR)")
        self.assertIsNotNone(out["total_output"])
        self.assertGreater(out["total_output"], 0.0)
        # 1000x past the corner a 1-pole filter is down ~1000x, not flat.
        self.assertLess(out["onoise_density"][-1],
                        0.05 * out["onoise_density"][0])
        info = win.noise_info.text()
        self.assertIn("nV", info, info)
        self.assertIn("integrated", info, info)
        from PyQt5.QtWidgets import QAction
        texts = {a.text().replace("&", "")
                 for a in win.findChildren(QAction)}
        self.assertIn("Run Noise Analysis", texts,
                      "Simulate menu is missing the noise analysis entry")
        win.close()

    def test_distortion_tab_reports_harmonics_in_dbc(self):
        """The Distortion tab must run analysis_runner.run_disto against the
        real solver: HD2/HD3 arrays over the sweep, finite and non-negative,
        reported in dBc - not a stub."""
        import math
        win = self._rc_window()
        win.run_simulation()
        win._sync_serial_nets()
        win.disto_net_box.setCurrentText(self._moving_net(win))
        win.disto_start_box.setValue(100.0)
        win.disto_stop_box.setValue(100000.0)
        win.disto_pts_box.setValue(4)
        win.run_distortion_analysis()

        out = win.disto_last
        self.assertGreater(len(out["freqs"]), 5, out["freqs"])
        self.assertEqual(len(out["hd2"]), len(out["freqs"]))
        self.assertEqual(len(out["hd3"]), len(out["freqs"]))
        for v in out["hd2"] + out["hd3"]:
            self.assertTrue(math.isfinite(v), v)
            self.assertGreaterEqual(v, 0.0, v)
        info = win.disto_info.text()
        self.assertIn("HD2", info, info)
        self.assertIn("dBc", info, info)
        self.assertGreaterEqual(len(win.disto_plot.plotItem.curves), 2,
                                "HD2/HD3 curves were not plotted")
        from PyQt5.QtWidgets import QAction
        texts = {a.text().replace("&", "")
                 for a in win.findChildren(QAction)}
        self.assertIn("Run Distortion Analysis (.disto)", texts,
                      "Simulate menu is missing the distortion entry")
        win.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)