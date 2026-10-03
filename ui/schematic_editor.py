"""
schematic_editor.py - WOSP flagship application window.

LTspice-style layout:
    top     menu + toolbar (Run = F2)
    left    component palette (passives, sources, semiconductors, MCU)
    centre  schematic editor (QGraphicsScene)
    right   waveform viewer (pyqtgraph)
    bottom  console + generated netlist

Simulate flow (F2):
    scene.model.compile_netlist()  ->  bridge.ngspice_wrapper.NgSpiceEngine
      -> ngSpice_Circ + "run"  ->  vectors  ->  pyqtgraph traces
"""

import json
import os
import sys
from typing import Dict

import pyqtgraph as pg
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QKeySequence, QPainter, QBrush, QColor
from PyQt5.QtWidgets import (
    QAction, QApplication, QComboBox, QDockWidget, QFileDialog, QGraphicsView,
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMenu, QMessageBox, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QDoubleSpinBox, QToolBar,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge import control_law
from bridge import gpio_model
from bridge import serial_console
from bridge.cad_engine import (SchematicComponent, SchematicNetlistEngine,
                               is_mcu)
from bridge.ngspice_wrapper import NgSpiceEngine
from ui.schematic_items import ComponentItem, WireItem
from ui.schematic_scene import SchematicScene
from ui.schematic_symbols import PALETTE_GROUPS, label_of

TRACE_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
               "#8c564b", "#17becf", "#e377c2"]


def _fmt(value, digits=3):
    """Format a measured number for the inspector table ('' when absent)."""
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


class _ProfileRunner:
    """
    Turn a declared GPIO profile into a pin-voltage function of time.

    Used by MCU-only mode, where there is no solver to generate a PULSE source
    and the waveform has to be built here instead. The same declared values go
    through gpio_model, so this cannot invent behaviour the netlist would not
    have produced.
    """

    def __init__(self, spec):
        self.spec = spec
        self.normalized = gpio_model.normalize_profile(spec)

    def __call__(self, _sense: float, time_s: float) -> float:
        s = self.normalized
        if s["mode"] == "static":
            return float(s["vhigh"]) if s["level"] else 0.0
        period = 1.0 / float(s["freq_hz"])
        phase = (time_s + float(s["phase_s"])) % period
        return float(s["vhigh"]) if phase < period * float(s["duty"]) else 0.0


class _SimWorker(QThread):
    """
    Runs a blocking solver call off the GUI thread.

    Without this, ngSpice_Command("run") freezes the interface: the window
    stops repainting, the progress bar never moves, and - because Qt cannot
    dispatch the click - the Stop button is unreachable.
    """

    progress = pyqtSignal(float, int)
    finished = pyqtSignal(object, str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.result = None
        self.error = ""

    def run(self):
        try:
            self.result = self._fn()
        except Exception as exc:                      # report, never crash the UI
            self.error = str(exc)
        self.finished.emit(self.result, self.error)


class SchematicView(QGraphicsView):
    """QGraphicsView with LTspice-ish navigation: wheel = zoom, drag = pan,
    and click-to-place when a palette tool is armed."""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def mousePressEvent(self, event):
        scene = self.scene()
        if event.button() == Qt.LeftButton and scene is not None and scene.armed_type:
            scene.place_component(scene.armed_type, self.mapToScene(event.pos()))
            event.accept()
            return
        item = self.itemAt(event.pos())
        if item is not None and event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.ControlModifier:
                # Ctrl+click: additive select, no drag-to-move.
                scene.toggle_selection(item)
                event.accept()
                return
            if isinstance(item, ComponentItem) and scene.last_click_was_double(item, event):
                scene.rotate_item(item)
                event.accept()
                return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def fit_to_contents(self):
        rect = self.scene().itemsBoundingRect()
        if rect.isEmpty():
            self.resetTransform()
            return
        self.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)


class SchematicEditor(QMainWindow):
    """The flagship editor window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("WOSP Schematic Editor")
        self.resize(1280, 820)

        self.model = SchematicNetlistEngine()
        self.scene = SchematicScene(self.model, self)
        self.view = SchematicView(self.scene, self)
        self.ng = None                      # lazily created NgSpiceEngine

        self._build_ui()
        self._build_actions()
        self._netlist_edited = False
        self.netlist_editor.textChanged.connect(self._on_netlist_edited)
        self._running = False
        self._abort = False
        self._mode = "Co-simulation"
        self._tstep_factor = 1.0
        self._duration_factor = 1.0
        self._run_duration_ms = 0.0
        self._serial = serial_console.SerialConsole()
        self._serial_text = ""
        self._install_cursor_clicks()
        self.scene.status.connect(self.statusBar().showMessage)
        self.scene.documentChanged.connect(self._refresh_netlist_view)
        self.scene.itemMenuRequested.connect(self._show_component_menu)
        self.scene.itemEditValue.connect(self._edit_item_value)
        self.scene.documentChanged.connect(self._refresh_gpio_inspector)
        self.scene.documentChanged.connect(self.refresh_pin_map)

        self.log("WOSP editor ready. Pick a part on the left, click to place, "
                 "click pin->pin to wire, F2 to simulate.")
        self._refresh_netlist_view()
        self.netlist_editor.setPlainText(self._generated_netlist_text())

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_netlist_editor(self):
        """
        Editable SPICE netlist pane.

        LTspice lets you hand-edit the netlist and run it. The direction that
        is *not* offered here is netlist -> schematic: a hand-written line has
        no pin coordinates, so there is nothing to draw. Edits flow forward into
        the solver, and the read-only view next door always shows what the
        schematic currently generates.
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        row = QHBoxLayout()
        refresh = QPushButton("Reset to schematic")
        refresh.setToolTip("Discard edits and show the netlist the schematic generates")
        refresh.clicked.connect(self._reset_netlist_editor)
        run_here = QPushButton("Run this netlist")
        run_here.setToolTip("Simulate the edited netlist instead of the schematic")
        run_here.clicked.connect(self.run_edited_netlist)
        adopt = QPushButton("Import as components")
        adopt.setToolTip("Create components from the edited netlist (new schematic)")
        adopt.clicked.connect(self.import_netlist_as_components)
        row.addWidget(refresh)
        row.addWidget(run_here)
        row.addWidget(adopt)
        row.addStretch(1)
        layout.addLayout(row)

        self.netlist_editor = QPlainTextEdit()
        self.netlist_editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.netlist_editor.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self.netlist_editor)

        self.netlist_status = QLabel(
            "Read-only generated netlist is on the previous tab. Edits here are "
            "what gets simulated.")
        self.netlist_status.setWordWrap(True)
        layout.addWidget(self.netlist_status)
        return panel

    # Timestep / duration multipliers per accuracy preset. These change only the
    # solver settings, never the circuit, so a run stays reproducible.
    SPEED_PRESETS = {
        #            tstep divisor, duration divisor
        "Accurate": (0.25, 1.0),
        "Balanced": (1.0, 1.0),
        "Fast": (4.0, 0.25),
    }

    def _apply_speed_preset(self, name):
        factor_t, factor_d = self.SPEED_PRESETS.get(name, (1.0, 1.0))
        self._tstep_factor = factor_t
        self._duration_factor = factor_d
        self.statusBar().showMessage(
            f"Accuracy '{name}': timestep x{factor_t:g}, duration x{factor_d:g}")

    def effective_tstep_us(self):
        return self.tstep_box.value() * getattr(self, "_tstep_factor", 1.0)

    def effective_duration_ms(self):
        return self.duration_box.value() * getattr(self, "_duration_factor", 1.0)

    def _on_mode_changed(self, mode):
        self._mode = mode
        self.log(f"Simulation mode: {mode}")
        if mode == "MCU only" and not self.model.control_laws:
            self.log("  note: no control law is attached, so there is no MCU "
                     "behaviour to run (right-click an MCU).")

    def _run_in_worker(self, fn):
        """
        Run a blocking solver call on a worker thread, keeping the UI alive.

        The caller's contract is unchanged - this returns once the work is done
        - but the event loop keeps turning, so Stop is clickable and the
        progress bar actually repaints.
        """
        app = QApplication.instance()
        if app is None:                 # headless: no event loop to pump
            return fn(), ""
        worker = _SimWorker(fn, self)
        worker.finished.connect(lambda *_: None)
        worker.progress.connect(self._on_progress)
        worker.start()
        self._worker = worker
        while worker.isRunning():
            app.processEvents()
            worker.wait(10)
        app.processEvents()
        self._worker = None
        return worker.result, worker.error

    def stop_simulation(self):
        """
        Ask ngspice to stop the current run.

        Runs on the GUI thread while the solver is on a worker, so the command
        can actually reach ngspice; it interrupts at the next timestep.
        """
        if not self._running:
            return
        self._abort = True
        if self.ng is not None:
            self.ng.request_stop()
        self.statusBar().showMessage("Stopping simulation...")
        self.log("Stop requested; ngspice will halt at the next timestep.")

    # ------------------------------------------------------------------
    # Pin map and serial console
    # ------------------------------------------------------------------
    def refresh_pin_map(self):
        """Show every declared MCU pin: role, net, and what drives it."""
        self.pinmap_table.clear()
        mcus = sorted((c for c in self.model.components.values()
                       if is_mcu(c.comp_type)), key=lambda c: c.name)
        if not mcus:
            self.pinmap_status.setText("Place an MCU to see its pin map.")
            return
        total = 0
        for comp in mcus:
            for row in gpio_model.pin_map(self.model, comp.comp_id,
                                          self.model.gpio_profiles,
                                          self.model.control_laws):
                total += 1
                self.pinmap_table.addTopLevelItem(QTreeWidgetItem([
                    row["pin"], row["net"] or "-", row["direction"], row["role"],
                    row["behaviour"], "yes" if row["wired"] else "no"]))
        unwired = sum(1 for i in range(self.pinmap_table.topLevelItemCount())
                      if self.pinmap_table.topLevelItem(i).text(5) == "no")
        note = (f"{len(mcus)} MCU(s), {total} wired pin(s). Hardware column is "
                f"inferred from the pin name; only the datasheet is definitive.")
        if unwired:
            note += f" {unwired} pin(s) are declared but not wired."
        self.pinmap_status.setText(note)

    def _import_uart_log(self):
        """Load a captured UART/serial log into the console."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import UART log", "",
            "Text/serial logs (*.log *.txt);;All files (*.*)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                self._serial.write(f.read())
        except OSError as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.log(f"Imported UART log from {os.path.basename(path)}")
        self._render_serial()

    def clear_serial(self):
        self._serial.clear()
        self._render_serial()

    def _render_serial(self):
        text = self.serial_filter.text().strip()
        self._serial_text = "\n".join(self._serial.grep(text) if text
                                      else self._serial.lines)
        self.serial_view.setPlainText(self._serial_text)
        info = self._serial.summary()
        status = f"{info['lines']} line(s)"
        if info["truncated"]:
            status += f" - showing the last {info['lines']} of {self._serial.total_seen}"
        if text:
            status += f" matching {text!r}"
        self.serial_status.setText(status)

    def _refresh_serial_filter(self, _text):
        self._render_serial()

    def _on_netlist_edited(self):
        """Mark the pane dirty so a schematic edit stops overwriting it."""
        generated = self.netlist_view.toPlainText()
        self._netlist_edited = self.netlist_editor.toPlainText() != generated
        if self._netlist_edited:
            self.netlist_status.setText(
                "Edited - F2 still simulates the schematic; use "
                "'Run this netlist' to simulate these edits.")

    def _generated_netlist_text(self):
        lines, _nets, _warns = self.model.compile_netlist(
            vin=self.vin_box.value(), tstep_us=self.tstep_box.value(),
            duration_ms=self.duration_box.value())
        return "\n".join(lines)

    def _reset_netlist_editor(self):
        self.netlist_editor.setPlainText(self._generated_netlist_text())
        self._netlist_edited = False
        self.netlist_status.setText("Reset to the schematic's netlist.")
        self.log("Netlist editor reset to the schematic's generated netlist.")

    def edited_netlist(self):
        """The netlist the editor pane currently holds, as a list of lines."""
        text = self.netlist_editor.toPlainText()
        return [l for l in (raw.strip() for raw in text.splitlines()) if l]

    def run_edited_netlist(self):
        """Simulate the hand-edited netlist rather than the compiled schematic."""
        lines = self.edited_netlist()
        if not lines:
            QMessageBox.warning(self, "Netlist is empty",
                                "The editor pane has no content to run.")
            return
        if not any(l.lower() == ".end" for l in lines):
            lines.append(".end")
        if self.ng is None:
            try:
                self.ng = NgSpiceEngine(verbose=False)
            except Exception as exc:
                self.log(f"ERROR: cannot start ngspice: {exc}")
                return
        try:
            self.ng.load_circuit(lines)
            self.ng.cmd("run")
            times = self.ng.get_vector_array("time")
        except Exception as exc:
            self.log(f"ERROR: edited netlist failed: {exc}")
            QMessageBox.warning(self, "Netlist failed", str(exc))
            return
        if not times:
            QMessageBox.warning(self, "No results",
                                "ngspice ran but produced no time vector. "
                                "Check the netlist for errors.")
            return
        self.plot.clear()
        self._curves = []
        self._last_time = list(times)
        self._last_traces = {}
        for i, vec in enumerate(self._probe_vectors(lines)):
            values = self.ng.get_vector_array(vec)
            if len(values) != len(times):
                continue
            self._last_traces[vec] = list(values)
            self._curves.append(self.plot.plot(
                [t * 1000.0 for t in times], values,
                pen=pg.mkPen(TRACE_COLORS[i % len(TRACE_COLORS)], width=2), name=vec))
        self.plot.setTitle(f"Edited netlist - {len(self._last_traces)} vectors")
        self._click_points = []
        self.refresh_cursors()
        self.log(f"Ran hand-edited netlist: {len(times)} points, "
                 f"{len(self._last_traces)} vectors plotted.")

    @staticmethod
    def _probe_vectors(lines):
        """Node names an edited netlist declares, excluding ground."""
        nodes = set()
        for line in lines:
            if not line or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 3 and parts[0][:1].upper() in ("R", "C", "L", "V", "I", "D", "S"):
                for node in parts[1:3]:
                    if node.upper() not in ("0", "GND"):
                        nodes.add(node)
        return sorted(nodes)

    def import_netlist_as_components(self):
        """
        Build a fresh schematic from the edited netlist.

        Components are laid out on a grid; wires are not reconstructed, because
        a SPICE line describes connectivity, not topology - reconstructing
        wires would mean guessing where the designer wanted them.
        """
        lines = self.edited_netlist()
        if not lines:
            QMessageBox.warning(self, "Netlist is empty", "Nothing to import.")
            return
        model = SchematicNetlistEngine()
        counters: Dict[str, int] = {}
        skipped = 0
        for line in lines:
            if line.startswith("*") or line.startswith("."):
                continue
            parts = line.split()
            designator = parts[0]
            letter = designator[:1].upper()
            comp_type = {"R": "R", "C": "C", "L": "L", "V": "V", "I": "I",
                         "D": "D", "S": "SWITCH", "M": "MOSFET", "W": "SWITCH"}.get(letter)
            if comp_type is None or len(parts) < 3:
                skipped += 1
                continue
            prefix = {"SWITCH": "S", "MOSFET": "M"}.get(comp_type, letter)
            counters[prefix] = counters.get(prefix, 0) + 1
            name = f"{prefix}{counters[prefix]}"
            value = " ".join(parts[3:]) if len(parts) > 3 else ""
            col = (counters[prefix] - 1) % 4
            row = len(model.components) // 4
            model.add_component(SchematicComponent(
                comp_id=name, comp_type=comp_type, name=name, value=value,
                x=col * 120, y=row * 90))
        if not model.components:
            QMessageBox.warning(
                self, "Nothing imported",
                "No two-terminal or source elements were found. Controls "
                "(.model/.tran) and subcircuit calls are not importable.")
            return
        self.scene.push_undo()
        self.model.clear()
        self.model.load_dict(model.to_dict())
        self.scene.rebuild()
        self.view.fit_to_contents()
        msg = f"Imported {len(model.components)} component(s) from the netlist."
        if skipped:
            msg += f" {skipped} line(s) skipped (models, directives, subcircuits)."
        msg += " Wires were not reconstructed - reconnect them on the canvas."
        self.netlist_status.setText(msg)
        self.log(msg)

    def _build_ui(self):
        # Left: component palette
        palette = QWidget()
        pal_layout = QVBoxLayout(palette)
        pal_layout.addWidget(QLabel("<b>Components</b>"))
        self.palette_list = QListWidget()
        self._palette_types = []
        for group, types in PALETTE_GROUPS:
            header = QListWidgetItem(f"— {group} —")
            header.setFlags(Qt.NoItemFlags)
            header.setForeground(QBrush(QColor("#8a9099")))
            self.palette_list.addItem(header)
            for comp_type in types:
                item = QListWidgetItem(f"   {label_of(comp_type)}")
                self.palette_list.addItem(item)
                self._palette_types.append(comp_type)
        self.palette_list.currentRowChanged.connect(self._on_palette_selected)
        pal_layout.addWidget(self.palette_list)
        palette.setMaximumWidth(220)

        # Right: waveform viewer
        self.plot = pg.PlotWidget(background="w", title="Waveforms (F2 to simulate)")
        self.plot.addLegend()
        self.plot.setLabel("bottom", "Time", units="ms")
        self.plot.setLabel("left", "Node voltage", units="V")
        self._click_points = []
        self._last_time = []
        self._last_traces = {}
        self._cursor_lines = []
        self._curves = []

        results_tabs = QTabWidget()
        self.mcu_tab = QWidget()
        mcu_layout = QVBoxLayout(self.mcu_tab)
        self.firmware_label = QLabel("<b>Firmware</b><br>No MCU placed yet.")
        self.firmware_label.setWordWrap(True)
        mcu_layout.addWidget(self.firmware_label)
        self.gpio_table = QTreeWidget()
        self.gpio_table.setHeaderLabels(
            ["MCU", "Pin", "Net", "Declared behaviour", "V min", "V max",
             "Duty", "Edges", "Measured f", "Reg err (counts)"])
        self.gpio_table.setRootIsDecorated(False)
        mcu_layout.addWidget(self.gpio_table)
        self.law_label = QLabel()
        self.law_label.setWordWrap(True)
        mcu_layout.addWidget(self.law_label)
        results_tabs.addTab(self.mcu_tab, "MCU / GPIO")

        # Pin mapping: what each pin is, what drives it, what it reads.
        pinmap_tab = QWidget()
        pinmap_layout = QVBoxLayout(pinmap_tab)
        self.pinmap_table = QTreeWidget()
        self.pinmap_table.setHeaderLabels(
            ["Pin", "Net", "Hardware", "Role", "Behaviour", "Wired"])
        self.pinmap_table.setRootIsDecorated(False)
        pinmap_layout.addWidget(self.pinmap_table)
        self.pinmap_status = QLabel("Place an MCU to see its pin map.")
        self.pinmap_status.setWordWrap(True)
        pinmap_layout.addWidget(self.pinmap_status)
        results_tabs.addTab(pinmap_tab, "Pin Map")

        # Serial console: whatever the firmware printed over its UART.
        serial_tab = QWidget()
        serial_layout = QVBoxLayout(serial_tab)
        self.serial_view = QPlainTextEdit()
        self.serial_view.setReadOnly(True)
        self.serial_view.setMaximumBlockCount(20000)
        self.serial_view.setStyleSheet("font-family: Consolas, monospace;")
        serial_layout.addWidget(self.serial_view)
        serial_row = QHBoxLayout()
        self.serial_filter = QLineEdit()
        self.serial_filter.setPlaceholderText("filter (substring, case-insensitive)")
        self.serial_filter.textChanged.connect(self._refresh_serial_filter)
        serial_row.addWidget(self.serial_filter, 1)
        open_uart = QPushButton("Import UART log...")
        open_uart.clicked.connect(self._import_uart_log)
        serial_row.addWidget(open_uart)
        clear_uart = QPushButton("Clear")
        clear_uart.clicked.connect(self.clear_serial)
        serial_row.addWidget(clear_uart)
        serial_layout.addLayout(serial_row)
        self.serial_status = QLabel(
            "No UART captured yet. Import a capture from a real run.")
        self.serial_status.setWordWrap(True)
        serial_layout.addWidget(self.serial_status)
        results_tabs.addTab(serial_tab, "Serial")

        # Measurement readout sits under the transient plot, the way an LTspice
        # ruler reports what you have dragged across.
        self.measure_label = QLabel("no cursors placed")
        self.measure_label.setWordWrap(True)
        self.measure_label.setStyleSheet("font-family: Consolas, monospace;")

        transient_panel = QWidget()
        transient_layout = QVBoxLayout(transient_panel)
        transient_layout.setContentsMargins(0, 0, 0, 0)
        transient_layout.addWidget(self.plot)
        transient_layout.addWidget(self.measure_label)
        results_tabs.addTab(transient_panel, "Waveforms")

        # FFT tab: filled from the transient run that is already in the engine.
        self.fft_plot = pg.PlotWidget(background="w",
                                      title="FFT - run a transient first")
        self.fft_plot.addLegend()
        self.fft_plot.setLabel("bottom", "Frequency", units="Hz")
        self.fft_plot.setLabel("left", "Magnitude", units="dB")
        self.fft_info = QLabel("No spectrum yet.")
        self.fft_info.setWordWrap(True)
        fft_panel = QWidget()
        fft_layout = QVBoxLayout(fft_panel)
        fft_layout.setContentsMargins(0, 0, 0, 0)
        fft_layout.addWidget(self.fft_plot)
        fft_layout.addWidget(self.fft_info)
        results_tabs.addTab(fft_panel, "FFT")

        # Bode tab: runs its own .ac sweep on demand.
        bode_panel = QWidget()
        bode_layout = QVBoxLayout(bode_panel)
        bode_controls = QHBoxLayout()
        bode_controls.addWidget(QLabel(" Output net "))
        self.bode_net_box = QComboBox()
        self.bode_net_box.setEditable(True)
        bode_controls.addWidget(self.bode_net_box, 1)
        bode_controls.addWidget(QLabel(" Start Hz "))
        self.bode_start_box = QDoubleSpinBox()
        self.bode_start_box.setRange(0.001, 1e9)
        self.bode_start_box.setDecimals(3)
        self.bode_start_box.setValue(1.0)
        bode_controls.addWidget(self.bode_start_box)
        bode_controls.addWidget(QLabel(" Stop Hz "))
        self.bode_stop_box = QDoubleSpinBox()
        self.bode_stop_box.setRange(0.01, 1e12)
        self.bode_stop_box.setDecimals(1)
        self.bode_stop_box.setValue(1e6)
        bode_controls.addWidget(self.bode_stop_box)
        bode_run = QPushButton("Run AC Sweep")
        bode_run.clicked.connect(self.run_bode)
        bode_controls.addWidget(bode_run)
        bode_layout.addLayout(bode_controls)

        self.bode_plot = pg.PlotWidget(background="w", title="Bode plot")
        self.bode_plot.addLegend()
        self.bode_plot.setLabel("bottom", "Frequency", units="Hz")
        self.bode_plot.setLabel("left", "Gain", units="dB")
        self.bode_phase = pg.PlotWidget(background="w", title="Phase")
        self.bode_phase.setLabel("bottom", "Frequency", units="Hz")
        self.bode_phase.setLabel("left", "Phase", units="deg")
        self.bode_phase.setMaximumHeight(180)
        self.bode_info = QLabel("No sweep yet.")
        self.bode_info.setWordWrap(True)
        bode_layout.addWidget(self.bode_plot, 3)
        bode_layout.addWidget(self.bode_phase, 1)
        bode_layout.addWidget(self.bode_info)
        results_tabs.addTab(bode_panel, "Bode")

        self.center_split = QSplitter(Qt.Horizontal)
        self.center_split.addWidget(self.view)
        self.center_split.addWidget(results_tabs)
        self.center_split.setStretchFactor(0, 3)
        self.center_split.setStretchFactor(1, 2)

        main_split = QSplitter(Qt.Horizontal)
        main_split.addWidget(palette)
        main_split.addWidget(self.center_split)
        main_split.setStretchFactor(1, 1)

        # Bottom dock: console + netlist
        bottom = QTabWidget()
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(2000)
        bottom.addTab(self.console, "Console")
        self.netlist_view = QPlainTextEdit()
        self.netlist_view.setReadOnly(True)
        bottom.addTab(self.netlist_view, "SPICE Netlist")
        bottom.addTab(self._build_netlist_editor(), "Netlist Editor")
        dock = QDockWidget("Console & Netlist", self)
        dock.setWidget(bottom)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

        self.setCentralWidget(main_split)
        self.statusBar().showMessage("Ready")

        # Sim settings in a toolbar
        toolbar = QToolBar("Simulate")
        self.addToolBar(toolbar)
        toolbar.addWidget(QLabel(" Vin (V) "))
        self.vin_box = QDoubleSpinBox(); self.vin_box.setRange(0, 1000); self.vin_box.setValue(12.0)
        toolbar.addWidget(self.vin_box)
        toolbar.addSeparator()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(150)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        toolbar.addWidget(self.progress)
        toolbar.addWidget(QLabel("  tstep (us) "))
        self.tstep_box = QDoubleSpinBox(); self.tstep_box.setRange(0.001, 10000); self.tstep_box.setDecimals(3); self.tstep_box.setValue(1.0)
        toolbar.addWidget(self.tstep_box)
        toolbar.addWidget(QLabel("  duration (ms) "))
        self.duration_box = QDoubleSpinBox(); self.duration_box.setRange(0.01, 10000); self.duration_box.setDecimals(2); self.duration_box.setValue(5.0)
        toolbar.addWidget(self.duration_box)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" mode "))
        self.mode_box = QComboBox()
        self.mode_box.addItems(["Transient only", "MCU only", "Co-simulation"])
        self.mode_box.setCurrentText("Co-simulation")   # default, not index 0
        self.mode_box.setToolTip(
            "Transient only: pure analog, MCU pins are ignored.\n"
            "MCU only: run the GPIO/control-law behaviour with no analog solving.\n"
            "Co-simulation: MCU pins driven from inside the solver (the default "
            "whenever a control law is attached).")
        toolbar.addWidget(self.mode_box)
        toolbar.addWidget(QLabel(" accuracy "))
        self.speed_box = QComboBox()
        self.speed_box.addItems(["Accurate", "Balanced", "Fast"])
        self.speed_box.setCurrentText("Balanced")
        self.speed_box.setToolTip(
            "Fast: larger timestep and shorter run, for a quick look.\n"
            "Accurate: small timestep, best for settling and ripple.\n"
            "Balanced: the default.")
        self.speed_box.currentTextChanged.connect(self._apply_speed_preset)
        toolbar.addWidget(self.speed_box)
        toolbar.addSeparator()
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.setToolTip("Abort the running simulation (Ctrl+C)")
        self.stop_button.clicked.connect(self.stop_simulation)
        toolbar.addWidget(self.stop_button)

        # Simulation mode drives which path F2 takes.
        self.mode_box.currentTextChanged.connect(self._on_mode_changed)

    # ------------------------------------------------------------------
    # Menus, toolbar, shortcuts
    # ------------------------------------------------------------------
    def _action(self, text, slot, shortcut=None, tip=""):
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        if tip:
            act.setStatusTip(tip)
        return act

    def _build_actions(self):
        run_act = self._action("▶  Run Simulation", self.run_simulation, "F2",
                               "Compile the schematic and solve it in ngspice")
        self.toolbar_run = QToolBar("Run")
        self.addToolBar(self.toolbar_run)
        self.toolbar_run.addAction(run_act)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self._action("&New Schematic", self.new_document, "Ctrl+N"))
        file_menu.addAction(self._action("&Open...", self.open_document, "Ctrl+O"))
        file_menu.addAction(self._action("&Save", self.save_document, "Ctrl+S"))
        file_menu.addAction(self._action("Save &As...", lambda: self.save_document(True)))
        file_menu.addSeparator()
        file_menu.addAction(self._action("&Export SPICE Netlist (.cir)...", self.export_netlist))
        file_menu.addAction(self._action("Export &KiCad Schematic (.kicad_sch)...", self.export_kicad_schematic))
        file_menu.addAction(self._action("Export KiCad &Netlist (.net)...", self.export_kicad_netlist))
        file_menu.addAction(self._action("Export &BOM (.csv)...", self.export_bom))
        file_menu.addSeparator()
        file_menu.addAction(self._action("E&xit", self.close))

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self._action("&Undo", self.scene.undo, "Ctrl+Z"))
        edit_menu.addAction(self._action("&Redo", self.scene.redo, "Ctrl+Y"))
        edit_menu.addAction(self._action("Redo (alternate)", self.scene.redo, "Ctrl+Shift+Z"))
        edit_menu.addSeparator()
        edit_menu.addAction(self._action("&Delete Selection", self.scene.delete_selected, "Del"))
        edit_menu.addAction(self._action("R&otate 90°", self.scene.rotate_selected, "R"))
        edit_menu.addAction(self._action("&Edit Value...", self.edit_selected_value, "E"))
        edit_menu.addAction(self._action("&Label Net...", self.label_selected_net, "L"))

        sim_menu = self.menuBar().addMenu("&Simulate")
        sim_menu.addAction(run_act)
        sim_menu.addAction(self._action("Run &FFT of selected net", self.run_fft, "Ctrl+F"))
        sim_menu.addAction(self._action("Run &Bode / AC Sweep", self.run_bode, "Ctrl+B"))
        sim_menu.addAction(self._action("Clear Cursors", self.clear_cursors, "Ctrl+K"))
        sim_menu.addSeparator()
        sim_menu.addAction(self._action("Re-&Fit View", self.view.fit_to_contents, "Ctrl+0"))

        results_menu = self.menuBar().addMenu("&Results")
        results_menu.addAction(self._action("Export Results as &CSV...", self.export_results_csv))
        results_menu.addAction(self._action("Export &Waveform Plot as PNG...", lambda: self.export_plot_image("waveforms")))
        results_menu.addAction(self._action("Export &FFT Plot as PNG...", lambda: self.export_plot_image("fft")))
        results_menu.addAction(self._action("Export &Bode Plot as PNG...", lambda: self.export_plot_image("bode")))
        results_menu.addSeparator()
        results_menu.addAction(self._action("Save Plot as &PDF...", lambda: self.export_plot_pdf()))

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self._action("&Gestures / Shortcuts", self.show_help))

    # ------------------------------------------------------------------
    # Console helpers
    # ------------------------------------------------------------------
    def log(self, msg):
        self.console.appendPlainText(str(msg))

    def _refresh_netlist_view(self):
        try:
            self.netlist_view.setPlainText(self._generated_netlist_text())
            # Keep the editor in step unless the user has unsaved edits.
            if not getattr(self, "_netlist_edited", False):
                self.netlist_editor.setPlainText(self.netlist_view.toPlainText())
        except Exception as exc:                      # never let a UI refresh crash
            self.netlist_view.setPlainText(f"<netlist generation failed: {exc}>")

    # ------------------------------------------------------------------
    # Palette / edits
    # ------------------------------------------------------------------
    def _component_rows(self):
        """Rows of real components (group headers carry NoItemFlags)."""
        return [r for r in range(self.palette_list.count())
                if self.palette_list.item(r).flags() != Qt.NoItemFlags]

    def _on_palette_selected(self, row):
        rows = self._component_rows()
        if row in rows:
            self.scene.armed_type = self._palette_types[rows.index(row)]
            self.view.setCursor(Qt.CrossCursor)
            self.statusBar().showMessage(
                f"Placing {label_of(self.scene.armed_type)} - click the canvas (Esc to stop)")
        else:
            self.scene.armed_type = None
            self.view.setCursor(Qt.ArrowCursor)

    def edit_selected_value(self):
        items = [i for i in self.scene.selectedItems() if isinstance(i, ComponentItem)]
        if items:
            self._edit_item_value(items[0])

    def _edit_item_value(self, item):
        value, ok = QInputDialog.getText(self, "Edit Value",
                                         f"{item.comp.name} ({item.comp.comp_type}) value:",
                                         text=item.comp.value)
        if ok:
            self.scene.set_component_value(item.comp.comp_id, value.strip())

    def _show_component_menu(self, item, global_pos):
        """Right-click menu on a placed component."""
        comp = item.comp
        menu = QMenu(self)
        menu.addAction("Edit Value...", lambda: self._edit_item_value(item))
        menu.addAction("Rotate 90\u00b0", lambda: self.scene.rotate_selected())
        menu.addSeparator()

        if is_mcu(comp.comp_type):
            menu.addAction("Load Firmware (.hex / .elf)...",
                           lambda: self._load_firmware(comp))
            menu.addAction("Import Control Law from Firmware (.c)...",
                           lambda: self._import_control_law(comp))
            menu.addAction("Set Control Law (JSON)...",
                           lambda: self._set_control_law(comp))
            menu.addAction("Set GPIO Pin Profile (JSON)...",
                           lambda: self._set_gpio_profile(comp))
            menu.addSeparator()
            menu.addAction("Clear Control Law", lambda: self._clear_control_law(comp))
            menu.addAction("Clear GPIO Profile",
                           lambda: self._clear_gpio_profile(comp))
            menu.addSeparator()

        menu.addAction("Delete", lambda: self.scene.delete_selected())
        menu.exec_(global_pos)

    # ------------------------------------------------------------------
    # MCU: firmware + GPIO profiles
    # ------------------------------------------------------------------
    def _load_firmware(self, comp):
        from bridge import firmware
        path, _ = QFileDialog.getOpenFileName(
            self, f"Firmware for {comp.name}", "",
            "Firmware images (*.hex *.ihex *.elf);;All files (*.*)")
        if not path:
            return
        try:
            image = firmware.load_firmware(path)
        except firmware.FirmwareParseError as exc:
            QMessageBox.warning(self, "Firmware not loaded", str(exc))
            self.log(f"Firmware load failed: {exc}")
            return
        self.model.firmware[comp.comp_id] = image.to_dict()
        self.scene.push_undo()
        self.scene.rebuild()
        self.log(f"Loaded firmware for {comp.name}: {image.summary()}")
        self.log("  Note: the binary itself is not executed. Use "
                 "'Import Control Law from Firmware (.c)' to drive a pin from the "
                 "real decision logic in the firmware source.")

    # ------------------------------------------------------------------
    # Closed-loop control laws
    # ------------------------------------------------------------------
    def _import_control_law(self, comp):
        """
        Build a control law from a real firmware C source.

        The ADC thresholds and gate pin are read out of the file's #defines, so
        the simulated pin follows the firmware's own decision boundary.
        """
        from bridge import control_law

        path, _ = QFileDialog.getOpenFileName(
            self, f"Control Law for {comp.name}", "firmware",
            "Firmware source (*.c *.cpp *.h);;All files (*.*)")
        if not path:
            return
        net_of, _ground = self.model._resolve_nets()
        nets = sorted({n for n in net_of.values() if n and n != "0"})
        if not nets:
            QMessageBox.warning(
                self, "No sense net",
                "This schematic has no analog nets to read back. Wire the "
                "controller to a node first (label it, e.g. 'vout').")
            return
        sense_net, ok = QInputDialog.getItem(
            self, f"Control Law for {comp.name}",
            "Which net does this firmware read back?", nets, 0, False)
        if not ok:
            return
        try:
            spec = control_law.law_from_firmware_source_exact(path, sense_net)
        except control_law.ControlLawError as exc:
            QMessageBox.warning(self, "Cannot import control law", str(exc))
            self.log(f"Control law import failed: {exc}")
            return
        self.scene.push_undo()
        self.model.control_laws[comp.comp_id] = spec
        self.scene.rebuild()
        self.log(f"Control law for {comp.name} imported from "
                 f"{os.path.basename(path)}: {control_law.describe_law(spec)}")
        if spec["pin"] not in comp.pins:
            self.log(f"  warning: firmware drives {spec['pin']}, which is not "
                     f"wired in this schematic - the law cannot run until it is.")

    def _set_control_law(self, comp):
        from bridge import control_law, firmware
        current = self.model.control_laws.get(comp.comp_id, {})
        text, ok = QInputDialog.getMultiLineText(
            self, f"Control Law for {comp.name}",
            "JSON: {kind: hysteretic|pwm, pin, sense_net, target_v, "
            "hysteresis_v, divider, vhigh, vref, adc_bits, carrier_hz}\n"
            'e.g. {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",\n'
            '      "target_v": 3.3, "hysteresis_v": 0.05, "divider": 0.5}',
            json.dumps(current, indent=2) if current else "")
        if not ok or not text.strip():
            return
        try:
            spec = firmware.parse_pin_profile(text)   # same JSON reader
            control_law.normalize_law(spec)           # validate before storing
        except (firmware.FirmwareParseError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid control law", str(exc))
            self.log(f"Control law rejected: {exc}")
            return
        self.scene.push_undo()
        self.model.control_laws[comp.comp_id] = spec
        self.scene.rebuild()
        self.log(f"Control law for {comp.name}: {control_law.describe_law(spec)}")

    def _clear_control_law(self, comp):
        if comp.comp_id not in self.model.control_laws:
            return
        self.scene.push_undo()
        self.model.control_laws.pop(comp.comp_id, None)
        self.scene.rebuild()
        self.log(f"Cleared control law for {comp.name}")

    def _set_gpio_profile(self, comp):
        from bridge import firmware, gpio_model
        current = self.model.gpio_profiles.get(comp.comp_id, {})
        text, ok = QInputDialog.getMultiLineText(
            self, f"GPIO Profile for {comp.name}",
            "JSON: pin -> {mode: static|square, freq_hz, duty, vhigh, level}\n"
            'e.g. {"GPIO18": {"mode": "square", "freq_hz": 1000, "duty": 0.5}}',
            ", ".join(f'"{p}": {s}' for p, s in current.items()) if current else "")
        if not ok or not text.strip():
            return
        try:
            profile = firmware.parse_pin_profile(text)
            for pin, spec in profile.items():          # validate before storing
                gpio_model.normalize_profile(spec)
        except (firmware.FirmwareParseError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid profile", str(exc))
            self.log(f"GPIO profile rejected: {exc}")
            return
        self.scene.push_undo()
        self.model.gpio_profiles[comp.comp_id] = profile
        self.scene.rebuild()
        self.log(f"GPIO profile for {comp.name}: " +
                 ", ".join(gpio_model.describe_pin(p, s) for p, s in profile.items()))

    def _clear_gpio_profile(self, comp):
        if comp.comp_id not in self.model.gpio_profiles:
            return
        self.scene.push_undo()
        self.model.gpio_profiles.pop(comp.comp_id, None)
        self.scene.rebuild()
        self.log(f"Cleared GPIO profile for {comp.name}")

    # ------------------------------------------------------------------
    def _refresh_gpio_inspector(self, measurements=None, run=None):
        """Fill the GPIO tab from the graph; optional measured data after a run."""
        from bridge import control_law, gpio_model

        self.gpio_table.clear()
        mcus = [c for c in self.model.components.values()
                if is_mcu(c.comp_type)]
        if not mcus:
            self.firmware_label.setText("<b>Firmware</b><br>No MCU placed yet.")
            self.law_label.setText("")
            return

        fw_bits = []
        for comp in sorted(mcus, key=lambda c: c.name):
            fw = self.model.firmware.get(comp.comp_id)
            if fw:
                fw_bits.append(f"<b>{comp.name}</b>: {os.path.basename(str(fw.get('path', '')))} "
                               f"— {fw.get('size_bytes', 0)} bytes, "
                               f"sha256 {str(fw.get('sha256', ''))[:12]}")
            else:
                fw_bits.append(f"<b>{comp.name}</b>: no firmware loaded")
        self.firmware_label.setText("<b>Firmware</b><br>" + "<br>".join(fw_bits))

        for comp in sorted(mcus, key=lambda c: c.name):
            profile = self.model.gpio_profiles.get(comp.comp_id, {})
            law_spec = self.model.control_laws.get(comp.comp_id)
            for pin in sorted(comp.pins):
                node = self._pin_net(comp.comp_id, pin)
                measured = (measurements or {}).get((comp.comp_id, pin), {})
                if node == "0" or pin in ("GND", "0", "gnd"):
                    declared = "ground"
                    reg_err = "-"
                else:
                    if law_spec and pin == law_spec.get("pin"):
                        from bridge import control_law
                        declared = control_law.describe_law(law_spec)
                    else:
                        declared = gpio_model.describe_pin(pin, profile.get(pin, {}))
                    if "switches" in measured:
                        reg_err = str(measured.get("switches", "-")) + " sw"
                    else:
                        reg_err = "-"
                if run is not None and law_spec and pin == law_spec.get("pin"):
                    err = run.regulation(pin).get("mean_error_counts")
                    reg_err = ("-" if err is None else f"{err:+.1f}")
                row = [comp.name, pin, node or "-", declared,
                       _fmt(measured.get("v_min")), _fmt(measured.get("v_max")),
                       "-" if measured.get("duty") is None else f"{measured['duty'] * 100:.1f}%",
                       str(measured.get("transitions", "-")),
                       "-" if not measured.get("freq") else f"{measured['freq']:.1f} Hz",
                       reg_err]
                self.gpio_table.addTopLevelItem(QTreeWidgetItem(row))

        law_bits = []
        for comp in sorted(mcus, key=lambda c: c.name):
            spec = self.model.control_laws.get(comp.comp_id)
            if spec:
                law_bits.append(f"<b>{comp.name}</b>: {control_law.describe_law(spec)}"
                                + (f" <i>(from {spec['source']})</i>"
                                   if spec.get("source") else ""))
        self.law_label.setText(
            "<b>Control laws (closed loop)</b><br>" + "<br>".join(law_bits)
            if law_bits else
            "<b>Control laws</b><br>None - right-click an MCU to import one from "
            "firmware source or paste a spec.")

    def _pin_net(self, comp_id, pin):
        """Net name a pin resolves to, using the same compiler the netlist uses."""
        net_of, _ground = self.model._resolve_nets()
        return net_of.get((comp_id, pin))

    def label_selected_net(self):
        wires = [i for i in self.scene.selectedItems() if isinstance(i, WireItem)]
        if not wires:
            self.log("Select a wire first, then label the net (L).")
            return
        wire_item = wires[0]
        match = next((w for w in self.model.wires
                      if self.scene._parse_ref(w.get("from", "")) == wire_item.from_ref and
                      self.scene._parse_ref(w.get("to", "")) == wire_item.to_ref), None)
        if match is None:
            return
        name, ok = QInputDialog.getText(self, "Label Net", "Net name:", text=match.get("net", ""))
        if ok and name.strip():
            self.scene.label_wire(match, name.strip())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def new_document(self):
        self.scene.clear_document()
        self.log("New schematic.")

    def save_document(self, force_dialog=False):
        path = None if force_dialog else getattr(self, "_current_path", None)
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save Schematic",
                                                  "schematic.wsk", "Schematic (*.wsk *.json)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model.to_dict(), f, indent=2)
        self._current_path = path
        self.statusBar().showMessage(f"Saved {path}")
        self.log(f"Saved schematic -> {path}")

    def open_document(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Schematic", "",
                                              "Schematic (*.wsk *.json)")
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            self.model.load_dict(json.load(f))
        self.scene.rebuild()
        self._current_path = path
        self.log(f"Opened {path}")

    def export_netlist(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export SPICE Netlist",
                                              "circuit.cir", "SPICE netlist (*.cir)")
        if not path:
            return
        lines, nets, warns = self.model.compile_netlist(
            vin=self.vin_box.value(), tstep_us=self.tstep_box.value(),
            duration_ms=self.duration_box.value())
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        self.log(f"Exported netlist -> {path}")
        for w in warns:
            self.log("  warning: " + w)

    def export_kicad_schematic(self):
        from bridge.kicad_export import export_kicad_schematic as _export
        path, _ = QFileDialog.getSaveFileName(self, "Export KiCad Schematic",
                                              "schematic.kicad_sch", "KiCad schematic (*.kicad_sch)")
        if not path:
            return
        try:
            _export(self.model, path, title=self._document_title())
        except ValueError as exc:
            QMessageBox.warning(self, "Nothing to export", str(exc))
            return
        self.log(f"Exported KiCad schematic -> {path}")

    def export_kicad_netlist(self):
        from bridge.kicad_export import export_kicad_netlist as _export
        path, _ = QFileDialog.getSaveFileName(self, "Export KiCad Netlist",
                                              "schematic.net", "KiCad netlist (*.net)")
        if not path:
            return
        try:
            _export(self.model, path)
        except ValueError as exc:
            QMessageBox.warning(self, "Nothing to export", str(exc))
            return
        self.log(f"Exported KiCad netlist -> {path}")

    def _document_title(self):
        return os.path.basename(getattr(self, "_current_path", "") or "WOSP Schematic")

    def export_bom(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export BOM", "bom.csv", "CSV (*.csv)")
        if not path:
            return
        from bridge.cad_engine import generate_bom_for
        rows = generate_bom_for(self.model)
        self.log(f"BOM has {len(rows)} line(s).")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("Designator,Type,Value,Qty\n")
            for row in rows:
                f.write(f"{row['Designator']},{row['Type']},{row['Value']},{row['Qty']}\n")
        self.log(f"Exported BOM -> {path}")

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------
    def _begin_run(self, duration_ms):
        """Common preamble: arm progress reporting and the Stop button."""
        self._running = True
        self._abort = False
        self.stop_button.setEnabled(True)
        self.progress.setValue(0)
        self._run_duration_ms = duration_ms
        if self.ng is not None:
            self.ng._stop_requested = False
            self.ng.timestep_count = 0
            self.ng.progress_callback = self._on_progress

    def _end_run(self):
        self._running = False
        self.stop_button.setEnabled(False)
        aborted = bool(getattr(self.ng, "_stop_requested", False)) if self.ng else False
        if self.ng is not None:
            self.ng.progress_callback = None
        # The last accepted timestep is always a little short of tstop, so a
        # finished run would otherwise sit at 99% looking unfinished.
        if not aborted:
            self.progress.setValue(100)

    def _on_progress(self, sim_time, steps):
        """Called from ngspice's sync callback on every accepted timestep."""
        if self._abort:
            return
        duration = getattr(self, "_run_duration_ms", 0.0)
        pct = int(100.0 * sim_time * 1000.0 / duration) if duration else 0
        self.progress.setValue(min(100, max(0, pct)))
        self.statusBar().showMessage(
            f"Simulating {sim_time * 1000:.3f} / {duration:.2f} ms "
            f"({steps} steps)")

    def run_mcu_only(self, laws):
        """
        Run the MCU behaviour with no analog solve.

        This is the mode that shows what the firmware does on its own: the
        law's logic levels, edge count and duty cycle over the sim window,
        with no circuit loading the pins. The pin is driven open-circuit, so
        this deliberately does *not* claim to predict anything about a circuit.
        """
        from bridge import gpio_model

        declared_profiles = {}
        for profile in self.model.gpio_profiles.values():
            for pin, spec in profile.items():
                declared_profiles.setdefault(pin, spec)
        if not laws and not declared_profiles:
            QMessageBox.information(
                self, "MCU only",
                "No MCU behaviour is declared.\n\nRight-click an MCU to import a "
                "control law from firmware source, or set a GPIO pin profile.")
            return
        duration_ms = self.effective_duration_ms()
        steps = max(2, int(duration_ms * 1000.0 / self.effective_tstep_us()))
        dt = duration_ms / steps / 1000.0
        self.log(f"=== MCU-only run: {steps} steps of {dt * 1e6:.3f} us ===")

        traces: Dict[str, List[float]] = {}
        # A control law reads feedback, so it needs a circuit; a declared GPIO
        # profile does not. MCU-only mode runs whichever the user supplied.
        specs = dict(laws)
        for comp_id, profile in self.model.gpio_profiles.items():
            for pin, spec in profile.items():
                specs.setdefault(pin, spec)
        if not specs:
            QMessageBox.information(
                self, "MCU only",
                "No MCU behaviour is declared.\n\nRight-click an MCU to import a "
                "control law from firmware source, or set a GPIO pin profile.")
            return
        for pin, spec in specs.items():
            try:
                if isinstance(spec, dict) and str(spec.get("kind", "")) in (
                        "hysteretic", "pwm"):
                    law = control_law.make_law(spec)
                    runner, label = law.update, law.describe()
                else:
                    runner = _ProfileRunner(spec)
                    label = gpio_model.describe_pin(pin, spec)
            except (control_law.ControlLawError, ValueError) as exc:
                self.log(f"  {pin}: rejected ({exc})")
                continue
            times, values = [], []
            sense = 0.0
            for i in range(steps):
                sense = runner(sense, i * dt)
                times.append(i * dt)
                values.append(sense)
            traces[pin] = values
            info = gpio_model.analyze_pin(times, values)
            freq = gpio_model.measured_frequency(times, values)
            self.log(f"  {pin}: {info['transitions']} edges, "
                     f"duty {info['duty'] * 100:.1f}%, "
                     f"{'%.2f Hz' % freq if freq else 'no oscillation'}"
                     + (f", final {'HIGH' if values[-1] > 0 else 'LOW'}"
                        if values else ""))
            self.log(f"     {label}")

        if not traces:
            return
        self.plot.clear()
        self._curves = []
        first = next(iter(traces))
        total = max(len(v) for v in traces.values())
        times_s = [i * dt for i in range(total)]
        self._last_time = times_s
        self._last_traces = traces
        for i, (pin, values) in enumerate(traces.items()):
            self._curves.append(self.plot.plot(
                [t * 1000.0 for t in times_s[:len(values)]], values,
                pen=pg.mkPen(TRACE_COLORS[i % len(TRACE_COLORS)], width=2),
                name=f"{pin} (pin)"))
        self.plot.setTitle(f"MCU only - {len(traces)} pin(s), no analog solve")
        self._click_points = []
        self.refresh_cursors()
        self.log("MCU-only mode: pins are open-circuit, so these traces show "
                 "firmware behaviour only, not circuit response.")

    def run_simulation(self):
        from bridge import gpio_model
        vin = self.vin_box.value()
        mode = getattr(self, "_mode", "Co-simulation")
        laws = {str(spec["pin"]): spec
                for comp_id, spec in self.model.control_laws.items()
                if comp_id in self.model.components}

        if mode == "MCU only":
            self.run_mcu_only(laws)
            return
        if mode == "Transient only":
            laws = {}          # MCU pins must not drive the analog solve
        elif laws:
            self.run_closed_loop(laws)
            return
        elif self.model.control_laws:
            self.log("A control law is attached but its MCU pin is not wired; "
                     "running transient only.")

        lines, nets, warns = self.model.compile_netlist(
            vin=vin, tstep_us=self.effective_tstep_us(),
            duration_ms=self.effective_duration_ms(),
            mcu_pins="ignore" if mode == "Transient only" else "drive")
        self.netlist_view.setPlainText("\n".join(lines))
        self.log(f"Compiled {len(lines)} netlist line(s); probe nets: {nets or '(none)'}")
        for w in warns:
            self.log("warning: " + w)

        if self.ng is None:
            try:
                self.ng = NgSpiceEngine(verbose=False)
            except Exception as exc:
                self.log(f"ERROR: cannot start ngspice: {exc}")
                return

        try:
            self._begin_run(self.effective_duration_ms())

            def _solve():
                self.ng.load_circuit(lines)
                self.ng.cmd("run")
                return self.ng.get_vector_array("time")

            time_v, err = self._run_in_worker(_solve)
            if err:
                self.log(f"ERROR: ngspice failed: {err}")
                return
        except Exception as exc:
            self.log(f"ERROR: ngspice failed: {exc}")
            return
        finally:
            aborted = getattr(self.ng, "_stop_requested", False)
            self._end_run()

        if aborted:
            self.log("Simulation stopped early at the user's request.")
            self.statusBar().showMessage("Simulation stopped")
        if not time_v:
            self.log("ERROR: simulation produced no time vector (check the netlist/warnings above).")
            return

        self.plot.clear()
        for i, net in enumerate(nets):
            try:
                values = self.ng.get_vector_array(net)
            except Exception:
                continue
            if len(values) != len(time_v):
                continue
            color = TRACE_COLORS[i % len(TRACE_COLORS)]
            self._curves.append(
                self.plot.plot([t * 1000.0 for t in time_v], values,
                               pen=pg.mkPen(color, width=2), name=net))
        self.plot.setTitle(f"Waveforms - {len(nets)} nets, {len(time_v)} points")
        self.log(f"Simulation complete: {len(time_v)} points plotted.")

        # Keep the solved data for cursors, FFT and CSV export.
        self._last_time = list(time_v)
        self._last_traces = {n: list(self.ng.get_vector_array(n)) for n in nets}
        for name in self._last_traces:
            if self.bode_net_box.findText(name) < 0:
                self.bode_net_box.addItem(name)
        self._click_points = []
        self.refresh_cursors()

        # Feed the GPIO inspector from what the solver actually produced
        measurements = {}
        for comp in [c for c in self.model.components.values() if is_mcu(c.comp_type)]:
            for pin in comp.pins:
                node = self._pin_net(comp.comp_id, pin)
                if not node or node == "0" or pin in ("GND", "0", "gnd"):
                    continue
                values = self.ng.get_vector_array(node)
                if len(values) != len(time_v):
                    continue
                info = gpio_model.analyze_pin(time_v, values)
                info["freq"] = gpio_model.measured_frequency(time_v, values)
                measurements[(comp.comp_id, pin)] = info
        if measurements:
            self._refresh_gpio_inspector(measurements)
            self.log(f"GPIO inspector updated for {len(measurements)} pin(s).")
        self.statusBar().showMessage(f"Simulated {len(time_v)} points across {len(nets)} nets")

    def _install_cursor_clicks(self):
        """Left-click on the transient plot drops a cursor; two make a ruler."""
        self._click_points = []

        def on_click(plot, points, _evt=None):
            if not points:
                return
            view = plot.getViewBox()
            x = view.mapSceneToView(points[0]).x()
            self._click_points.append(x)
            if len(self._click_points) > 2:
                self._click_points = self._click_points[-2:]
            self.refresh_cursors()

        self.plot.scene().sigMouseClicked.connect(on_click)

    def clear_cursors(self):
        self._click_points = []
        self.refresh_cursors()
        self.log("Cursors cleared.")

    # ------------------------------------------------------------------
    # Cursor measurement, FFT, Bode
    # ------------------------------------------------------------------
    def cursor_readout(self) -> dict:
        """
        What the ruler across the transient plot says right now.

        Two cursors are placed by clicking the plot; without them there is
        nothing to measure, so it says so instead of inventing numbers.
        """
        from bridge import measurements
        times = getattr(self, "_last_time", None)
        if not times or len(self.cursor_x()) < 1:
            self.measure_label.setText(
                "click the waveform plot to place cursor A, then again for cursor B")
            return {}
        xs = sorted(self.cursor_x())
        net = self._net_under_cursors()
        values = getattr(self, "_last_traces", {}).get(net)
        if not values:
            self.measure_label.setText(
                "cursor is not on a plotted trace - pick a net from the legend")
            return {}
        readout = measurements.cursor_readout(times, values, xs[0])
        if len(xs) > 1:
            readout = measurements.cursor_readout(times, values, xs[0], None, xs[1])
        stats = measurements.trace_stats(times, values)
        text = f"{net}: " + measurements.format_readout(readout)
        text += (f"   |  min {stats['min']:.3f} V  max {stats['max']:.3f} V"
                 f"  rms {stats['rms']:.3f} V  p-p {stats['p2p']:.3f} V")
        self.measure_label.setText(text)
        return readout

    def cursor_x(self):
        """Cursor positions in data coordinates."""
        return [float(x) for x in getattr(self, "_click_points", [])]

    def _net_under_cursors(self):
        """
        Which trace the ruler is measuring.

        pyqtgraph has no public way to ask "which curve is under this pixel",
        so this uses the first plotted trace and names it in the readout. The
        legend is clickable, so re-ordering changes which one you measure.
        """
        if not getattr(self, "_curves", None):
            return ""
        return self._curves[0].name() or ""

    def refresh_cursors(self):
        """Redraw the cursor lines; called after a new run."""
        for line in list(getattr(self, "_cursor_lines", [])):
            self.plot.removeItem(line)
        self._cursor_lines = []
        for x in sorted(self.cursor_x()):
            line = pg.InfiniteLine(pos=x, angle=90, movable=True,
                                   pen=pg.mkPen("#888", style=Qt.DashLine))
            line.sigPositionChanged.connect(lambda *_: self.cursor_readout())
            self.plot.addItem(line)
            self._cursor_lines.append(line)
        self.cursor_readout()

    def run_fft(self):
        """FFT of one net from the transient run already in the solver."""
        from bridge import analysis_runner

        traces = getattr(self, "_last_traces", {})
        if not traces:
            QMessageBox.information(self, "FFT",
                                    "Run a transient simulation first (F2).")
            return
        net = self.bode_net_box.currentText().strip()
        if net not in traces:
            net = QInputDialog.getItem(self, "FFT of which net?", "Net:",
                                       sorted(traces.keys()), 0, False)
        if net not in traces:
            return
        try:
            out = analysis_runner.run_fft(self.ng, net)
        except analysis_runner.AnalysisError as exc:
            QMessageBox.warning(self, "FFT failed", str(exc))
            self.log(f"FFT failed: {exc}")
            return

        import math
        freqs, mags = out["freqs"], out["magnitude"]
        # Skip DC and show magnitude in dB, which is how a spectrum is read.
        xs = [f for f in freqs if f > 0]
        ys = [20 * math.log10(m) if m > 1e-12 else -300.0
              for f, m in zip(freqs, mags) if f > 0]
        self.fft_plot.clear()
        if xs:
            self.fft_plot.plot(xs, ys, pen=pg.mkPen("#1f77b4"), name=net)
        self.fft_plot.setTitle(f"FFT of {net} ({out['window']} window)")
        thd = out.get("thd")
        self.fft_info.setText(
            f"dominant {out['dominant_hz']:.2f} Hz"
            f"   bin width {out['bin_width_hz']:.2f} Hz"
            f"   noise floor {out['noise_floor']:.2e}"
            + (f"   THD {thd * 100:.3f}%" if thd is not None else ""))
        self.log(f"FFT of {net}: dominant {out['dominant_hz']:.2f} Hz"
                 + (f", THD {thd * 100:.3f}%" if thd is not None else ""))

    def run_bode(self):
        """AC sweep of the schematic, drawn as gain and phase."""
        from bridge import analysis_runner

        net = self.bode_net_box.currentText().strip()
        if not net:
            _lines, nets, _w = self.model.compile_netlist()
            if not nets:
                QMessageBox.information(self, "Bode", "This schematic has no nets.")
                return
            self.bode_net_box.addItems(nets)
            net = nets[0]
        start = self.bode_start_box.value()
        stop = self.bode_stop_box.value()
        if stop <= start:
            QMessageBox.warning(self, "Bode", "Stop frequency must exceed start.")
            return
        try:
            out = analysis_runner.run_bode(self.model, net, start_hz=start,
                                           stop_hz=stop)
        except analysis_runner.AnalysisError as exc:
            QMessageBox.warning(self, "AC sweep failed", str(exc))
            self.log(f"Bode failed: {exc}")
            return

        self.bode_plot.clear()
        self.bode_phase.clear()
        self.bode_plot.plot(out["freqs"], out["gain_db"],
                            pen=pg.mkPen("#1f77b4"), name="gain")
        self.bode_phase.plot(out["freqs"], out["phase_deg"],
                             pen=pg.mkPen("#d62728"))
        self.bode_plot.setTitle(f"Bode - {net}")
        self.bode_plot.setLogMode(x=True)
        self.bode_phase.setLogMode(x=True)

        m = out["margins"]
        bits = [f"{len(out['freqs'])} points, peak {out['peak_db']:.2f} dB "
                f"at {out['peak_hz']:.3g} Hz"]
        if m["crossover_hz"] is not None:
            bits.append(f"unity-gain at {m['crossover_hz']:.3g} Hz, "
                        f"phase margin {m['phase_margin_deg']:.1f} deg")
        else:
            bits.append("no unity-gain crossover in range (phase margin undefined)")
        self.bode_info.setText("   ".join(bits))
        self.log("Bode: " + "   ".join(bits))
        self._refresh_netlist_view()

    # ------------------------------------------------------------------
    # Result export
    # ------------------------------------------------------------------
    def export_results_csv(self):
        """Every plotted trace as CSV, in the units the axes use."""
        traces = getattr(self, "_last_traces", {})
        times = getattr(self, "_last_time", None)
        if not times or not traces:
            QMessageBox.information(self, "Export", "Run a simulation first (F2).")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "results.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        nets = [n for n in traces if len(traces[n]) == len(times)]
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("time_s," + ",".join(nets) + "\n")
            for i, t in enumerate(times):
                f.write(f"{t:.9g}," + ",".join(f"{traces[n][i]:.9g}" for n in nets) + "\n")
        self.log(f"Exported {len(times)} points across {len(nets)} net(s) -> {path}")

    def export_plot_pdf(self):
        """
        Write the solved traces to a multi-page PDF.

        Rendered with matplotlib rather than grabbed from the widget: Qt's
        raster grab has no vector backend, so a "PDF" made that way is just a
        blurry bitmap in a wrapper. Each net gets a page with its statistics.
        """
        traces = getattr(self, "_last_traces", {})
        times = getattr(self, "_last_time", None)
        if not times or not traces:
            QMessageBox.information(self, "Export", "Run a simulation first (F2).")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export report",
                                              "report.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            from bridge import measurements
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.backends.backend_pdf as _pdf_backend
            import matplotlib.pyplot as plt

            good = [n for n in traces if len(traces[n]) == len(times)]
            with _pdf_backend.PdfPages(path) as pdf:
                for name in good:
                    fig, ax = plt.subplots(figsize=(8.27, 11.69))
                    ax.plot([t * 1000.0 for t in times], traces[name],
                            penwidth=0.8)
                    s = measurements.trace_stats(times, traces[name])
                    ax.set_title(f"{name}")
                    ax.set_xlabel("Time (ms)")
                    ax.set_ylabel("Voltage (V)")
                    ax.grid(True, alpha=0.3)
                    ax.text(0.99, 0.98,
                            f"min {s['min']:.4f} V   max {s['max']:.4f} V\n"
                            f"mean {s['mean']:.4f} V   rms {s['rms']:.4f} V\n"
                            f"p-p {s['p2p']:.4f} V   points {s['points']}",
                            transform=ax.transAxes, fontsize=8, va="top",
                            ha="right", family="monospace")
                    fig.tight_layout()
                    pdf.savefig(fig)
                    plt.close(fig)
        except Exception as exc:
            QMessageBox.warning(self, "PDF export failed", str(exc))
            self.log(f"PDF export failed: {exc}")
            return
        self.log(f"Exported {len(good)} page(s) -> {path}")

    def export_plot_image(self, which="waveforms"):
        """Save the active plot as a PNG."""
        plot = {"waveforms": self.plot, "fft": self.fft_plot,
                "bode": self.bode_plot}.get(which, self.plot)
        path, _ = QFileDialog.getSaveFileName(self, "Export plot", f"{which}.png",
                                              "PNG image (*.png)")
        if not path:
            return
        try:
            plot.grab().save(path, "PNG")
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.log(f"Exported {which} plot -> {path}")

    # ------------------------------------------------------------------
    # Closed-loop co-simulation
    # ------------------------------------------------------------------
    def run_closed_loop(self, laws):
        """
        Run with MCU pins driven from inside the solver.

        The MCU pin is an `external` source, so ngspice calls back into
        bridge/cosim_runner.py at every timestep; the law reads the simulated
        sense net and returns the pin voltage. The traces plotted are the ones
        the solver produced, not a reconstruction.
        """
        from bridge import cosim_runner

        if self.ng is None:
            try:
                self.ng = NgSpiceEngine(verbose=False)
            except Exception as exc:
                self.log(f"ERROR: cannot start ngspice: {exc}")
                return

        self.log("=== closed-loop co-simulation ===")
        for pin, spec in laws.items():
            from bridge import control_law
            self.log(f"  {pin}: {control_law.describe_law(spec)}")

        try:
            self._begin_run(self.effective_duration_ms())
            run = cosim_runner.run_cosim(
                self.model, laws,
                vin=self.vin_box.value(), tstep_us=self.effective_tstep_us(),
                duration_ms=self.effective_duration_ms(), engine=self.ng,
                progress_callback=self._on_progress,
                stop_flag=lambda: self._abort)
        except Exception as exc:
            self.log(f"ERROR: closed-loop run failed: {exc}")
            return
        finally:
            aborted = run.aborted if "run" in dir() else False
            self._end_run()

        if aborted:
            self.log("Closed-loop run stopped early at the user's request.")

        self.netlist_view.setPlainText("\n".join(run.netlist))
        self.plot.clear()
        self._curves = []
        for i, (net, values) in enumerate(run.traces.items()):
            if len(values) != len(run.time):
                continue
            self._curves.append(
                self.plot.plot([t * 1000.0 for t in run.time], values,
                               pen=pg.mkPen(TRACE_COLORS[i % len(TRACE_COLORS)], width=2),
                               name=net))
        for i, (pin, law) in enumerate(run.laws.items()):
            if not law.history_time:
                continue
            color = TRACE_COLORS[(len(run.traces) + i) % len(TRACE_COLORS)]
            self._curves.append(
                self.plot.plot([t * 1000.0 for t in law.history_time], law.history_pin,
                               pen=pg.mkPen(color, width=2, style=Qt.DashLine),
                               name=f"{pin} (pin)"))
        self.plot.setTitle(
            f"Closed loop - {len(run.traces)} nets, {len(run.time)} points, "
            f"{run.callback_hits} control callbacks")

        for line in run.summary_lines():
            self.log("  " + line)
        if not run.time:
            self.log("ERROR: no time vector; see warnings above.")
            self.statusBar().showMessage("Closed-loop run produced no data")
            return
        self.statusBar().showMessage(
            f"Closed-loop: {run.callback_hits} control callbacks over "
            f"{self.duration_box.value():.2f} ms")

        measurements = self._measure_from_run(run)
        self._refresh_gpio_inspector(measurements, run)
        self._last_time = list(run.time)
        self._last_traces = {n: list(v) for n, v in run.traces.items()}
        for name in self._last_traces:
            if self.bode_net_box.findText(name) < 0:
                self.bode_net_box.addItem(name)
        self._click_points = []
        self.refresh_cursors()
        self.log("GPIO inspector updated from the closed-loop run.")

    def _measure_from_run(self, run):
        """Per-pin measurements the solver actually produced."""
        from bridge import gpio_model

        measurements = {}
        for comp in self.model.components.values():
            if comp.comp_type.upper() != "MCU":
                continue
            for pin in comp.pins:
                node = self._pin_net(comp.comp_id, pin)
                if not node or node == "0" or pin in ("GND", "0", "gnd"):
                    continue
                law = run.laws.get(pin)
                if law is not None and law.history_time:
                    info = gpio_model.analyze_pin(law.history_time, law.history_pin)
                    info["counts"] = {
                        "min": min(law.history_counts),
                        "max": max(law.history_counts),
                        "last": law.history_counts[-1],
                    }
                    info["switches"] = law.switch_count
                    info["freq"] = gpio_model.measured_frequency(
                        law.history_time, law.history_pin)
                    measurements[(comp.comp_id, pin)] = info
                    continue
                values = run.traces.get(node)
                times = run.time
                if not values or len(values) != len(times):
                    continue
                info = gpio_model.analyze_pin(times, values)
                info["freq"] = gpio_model.measured_frequency(times, values)
                measurements[(comp.comp_id, pin)] = info
        return measurements

    # ------------------------------------------------------------------
    def show_help(self):
        QMessageBox.information(self, "Gestures", """
<b>WOSP editor gestures</b>
<ul>
<li>Pick a part on the left, then click the canvas to place it</li>
<li>Click pin -> click pin to wire; Esc cancels</li>
<li>Drag a part to move it (snaps to grid)</li>
<li><b>R</b> rotate 90&deg;, <b>Del</b> delete, <b>E</b> edit value, <b>L</b> label net</li>
<li><b>Ctrl+Z / Ctrl+Shift+Z</b> undo / redo</li>
<li><b>F2</b> run simulation in real ngspice</li>
<li>Wheel zooms the canvas; middle-drag pans</li>
</ul>
""")

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_R:
            self.scene.rotate_selected()
        elif key == Qt.Key_Delete:
            self.scene.delete_selected()
        elif key == Qt.Key_E:
            self.edit_selected_value()
        elif key == Qt.Key_L:
            self.label_selected_net()
        elif key == Qt.Key_K:
            self.clear_cursors()
        elif key == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            self.stop_simulation()
        elif key == Qt.Key_Escape:
            self.scene.cancel_wire()
            self.scene.armed_type = None
            self.view.setCursor(Qt.ArrowCursor)
            self.statusBar().showMessage("Cancelled")
        else:
            super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    win = SchematicEditor()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()