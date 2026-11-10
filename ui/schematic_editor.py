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
from typing import Dict, List

import pyqtgraph as pg
from PyQt5.QtCore import (QPointF, QRect, QRectF, QSize, Qt, QThread,
                          pyqtSignal)
from PyQt5.QtGui import QKeySequence, QPainter, QBrush, QColor, QPen
from PyQt5.QtWidgets import (
    QAction, QActionGroup, QApplication, QComboBox, QDockWidget, QFileDialog,
    QFrame, QGraphicsView, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
    QLayout, QListWidget, QListWidgetItem,
    QMainWindow, QDialog, QMenu, QMessageBox, QLineEdit, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSplitter,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QDoubleSpinBox, QSpinBox, QToolBar,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge import control_law
from bridge import gpio_model
from bridge import serial_console
from bridge import binary_runner
from bridge.cad_engine import (SchematicComponent, SchematicNetlistEngine,
                               is_mcu)
from bridge.ngspice_wrapper import NgSpiceEngine
from ui.schematic_items import ComponentItem, WireItem
from ui.schematic_scene import SchematicScene
from ui.schematic_symbols import PALETTE_GROUPS, label_of
from ui import icons
from ui import theme

TRACE_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
               "#8c564b", "#17becf", "#e377c2"]

# LTspice/KiCad muscle memory: a bare letter arms that part for click-to-place.
# R C L are exactly the parts they spell, which is the whole point - so the
# commands that used to own bare letters (rotate, edit value, label net) moved
# to Ctrl chords. Ctrl+R for rotate is LTspice's own binding.
#
# Every entry in PALETTE_GROUPS must appear here exactly once; a test enforces
# that, so a new symbol cannot ship with a letter that does nothing.
# Icon/cursor scale (View > Icon / Cursor Size). One fixed size was a real
# LTspice complaint - toolbar chrome too big to place accurately - so every
# clickable icon surface and both cursor strokes scale together from this one
# table. "medium" reproduces the sizes that used to be hard-coded (18 px
# toolbar, 26 px palette symbols, 30 px rows, 1 px cursors).
ICON_SCALES = {
    # map: small, medium, large  ->  toolbar, palette, row, symbol, crosshair, ruler
    "small":  {"toolbar": 14, "palette": 20, "row": 26, "symbol": 20, "cursor": 1, "ruler": 10},
    "medium": {"toolbar": 18, "palette": 26, "row": 30, "symbol": 26, "cursor": 2, "ruler": 14},
    "large":  {"toolbar": 24, "palette": 34, "row": 38, "symbol": 34, "cursor": 3, "ruler": 18},
}

# Help overlay content. The Place menu was the only shortcut list; the F1
# overlay now covers the full surface so a new user can find any binding
# without hunting through every menu.
HELP_SECTIONS = [
    ("Simulation controls", [
        ("Simulate / run", "F2"),
        ("Stop simulation", "Ctrl+."),
        ("Compile netlist (no run)", "Ctrl+Shift+F"),
        ("Domain: MCU only", "Ctrl+M"),
        ("Domain: Transient only", "Ctrl+T"),
        ("Fast step (10x)", "Ctrl+Shift+P"),
        ("Open serial monitor", "Ctrl+Shift+K"),
        ("Export CSV", "Ctrl+Shift+C"),
        ("Export plot PNG", "Ctrl+Shift+P"),
        ("Export report PDF", "Ctrl+Shift+Alt+P"),
    ]),
    ("Measurement tools", [
        ("FFT of a net", "Ctrl+F"),
        ("AC sweep (Bode)", "Ctrl+B"),
        ("Place cursor A / B", "click plot"),
        ("Drag a cursor", "drag the dashed line"),
        ("Clear cursors", "Ctrl+Shift+K"),
        ("Choose measured trace", "click a trace list row"),
    ]),
    ("Waveform navigation", [
        ("Zoom in / out", "Ctrl++ / Ctrl+-"),
        ("Fit to contents", "Ctrl+0"),
        ("Scroll left / right", "scroll wheel"),
        ("Pan vertically", "drag the plot background"),
    ]),
    ("Editing / placement", [
        ("Arm a part by letter", "R C L D V M G E"),
        ("Place at cursor", "left click on canvas"),
        ("Rotate while placing", "R / Ctrl+R"),
        ("Mirror while placing", "M / Ctrl+M"),
        ("Cancel the current tool", "Esc"),
        ("Edit value...", "Ctrl+E"),
        ("Label net...", "Ctrl+L"),
        ("Undo / Redo", "Ctrl+Z / Ctrl+Y"),
        ("Start a wire from a pin", "click a pin"),
    ]),
]

PART_HOTKEYS = {
    "R": "R", "C": "C", "L": "L", "D": "D",
    "V": "V", "I": "I", "M": "MOSFET", "G": "GND",
    "U": "MCU",
    "A": "ARDUINO_UNO", "Shift+A": "ARDUINO_MEGA", "N": "ARDUINO_NANO",
    "S": "STM32F103",
    "E": "ESP32", "Shift+E": "ESP32S3",
}


def hotkey_text(event):
    """"a" / "Shift+A" for a key event, or "" if it is not a bare letter."""
    text = event.text()
    if not text:
        return ""
    return ("Shift+" if event.modifiers() & Qt.ShiftModifier else "") + text.upper()


_HOTKEY_FOR_TYPE = {comp_type: key for key, comp_type in PART_HOTKEYS.items()}


def hotkey_of(comp_type):
    """The letter that arms this part, or "" if the part has no letter."""
    return _HOTKEY_FOR_TYPE.get(comp_type, "")


def _view_point(evt):
    """Click position in plot-widget pixels, whatever the event type."""
    for getter in ("pos", "scenePos", "position"):
        method = getattr(evt, getter, None)
        if callable(method):
            try:
                point = method()
            except TypeError:
                continue
            if getter == "pos":
                return point
            return QPointF(point)
    return None


def _nearest_index(xs, target):
    """Index of the sample closest to `target`, or None when the trace is empty."""
    if xs is None or len(xs) == 0:
        return None
    try:
        import numpy as np
        return int(np.argmin(np.abs(np.asarray(xs, dtype=float) - float(target))))
    except (TypeError, ValueError):
        return min(range(len(xs)), key=lambda i: abs(xs[i] - target))


def _point_at(curve, index):
    """Scene-space position of one sample of a curve."""
    data = curve.getData()
    if not data or data[0] is None or index >= len(data[0]):
        return QPointF()
    view = curve.getViewBox() if hasattr(curve, "getViewBox") else None
    point = QPointF(data[0][index], data[1][index])
    return view.mapViewToScene(point) if view is not None else point


def _curve_named(name):
    """The plotted curve with this name, or None. Used by the trace list, which
    is keyed by net name and cannot hold curve references across a re-plot."""
    curves = getattr(_curve_named, "_owner", None)
    if curves is None:
        return None
    for curve in curves:
        if (curve.name() or "") == name:
            return curve
    return None


def _value_at(curve, target_x):
    """Interpolated y of a curve at a data x, or None."""
    if curve is None:
        return None
    data = curve.getData()
    if not data or data[0] is None or len(data[0]) == 0:
        return None
    index = _nearest_index(data[0], target_x)
    if index is None:
        return None
    try:
        return float(data[1][index])
    except (TypeError, ValueError, IndexError):
        return None


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
    """The schematic canvas.

    Navigation follows what a schematic capture tool is used to, rather than
    what QGraphicsView does by default:

      wheel              zoom about the pointer
      left drag          rubber-band select (the default drag mode used to be
                         ScrollHandDrag, which made multi-select impossible -
                         you had to Ctrl+click one component at a time)
      middle / right     pan
      space held         pan with the left button
      double-click       rotate a component
    """

    RULER = 22
    MIN_TICK_PX = 46
    TICKS = (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setViewportMargins(self.RULER, self.RULER, 0, 0)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._space_held = False
        self._panning = False
        self._pan_origin = None
        self._cursor_scene = None
        # Stroke width of the crosshair guide; updated by the editor's
        # icon/cursor scale setting (ICON_SCALES).
        self.cursor_width = ICON_SCALES["medium"]["cursor"]

    # -- space-to-pan ------------------------------------------------------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self.setCursor(Qt.ClosedHandCursor)
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            self.viewport().unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self._space_held = False
        super().focusOutEvent(event)

    # -- pan vs. marquee --------------------------------------------------
    def _begin_pan(self, event):
        self._panning = True
        self._pan_origin = event.pos()
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def mousePressEvent(self, event):
        # Clicking the sheet is how you say "keys go to the sheet". Without this
        # the canvas never holds focus after a click, so every bare-letter and
        # Escape binding silently does nothing once you have clicked a palette
        # row or typed in the filter box.
        self.setFocus()
        scene = self.scene()
        button = event.button()
        if button in (Qt.MiddleButton, Qt.RightButton) or (
                button == Qt.LeftButton and self._space_held):
            if button == Qt.LeftButton:
                self._space_held = False
            self._begin_pan(event)
            event.accept()
            return
        if button == Qt.LeftButton and scene is not None and scene.armed_type:
            scene.place_component(scene.armed_type, self.mapToScene(event.pos()))
            event.accept()
            return
        item = self.itemAt(event.pos())
        if item is not None and button == Qt.LeftButton:
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

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_origin is not None:
            delta = event.pos() - self._pan_origin
            self._pan_origin = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        self._cursor_scene = self.mapToScene(event.pos())
        self.viewport().update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            self._pan_origin = None
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._cursor_scene = None
        self.viewport().update()
        super().leaveEvent(event)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.02 if event.angleDelta().y() > 0 else 1 / 1.02
        self.scale(factor, factor)
        self.viewport().update()

    def zoom_by(self, factor):
        self.scale(factor, factor)
        self.viewport().update()

    def fit_to_contents(self):
        rect = self.scene().itemsBoundingRect()
        if rect.isEmpty():
            self.resetTransform()
            self.viewport().update()
            return
        self.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)
        self.viewport().update()

    def scene_rect_of(self):
        tl = self.mapToScene(0, 0)
        br = self.mapToScene(self.viewport().width(), self.viewport().height())
        return QRectF(tl, br).normalized()

    # -- rulers -----------------------------------------------------------
    def _tick_step(self, scale):
        """Smallest declared tick pitch that still leaves MIN_TICK_PX between
        labels at the current zoom."""
        for step in self.TICKS:
            if step * scale >= self.MIN_TICK_PX:
                return step
        return self.TICKS[-1]

    def paintEvent(self, event):
        # Fill the whole widget first; the viewport covers everything except
        # the ruler margins, which are then painted on top of that.
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.current().canvas_ruler_bg))
        super().paintEvent(event)
        self._paint_rulers(painter)
        self._paint_crosshair(painter)

    def _paint_rulers(self, painter):
        pal = theme.current()
        scale = abs(self.transform().m11()) or 1.0
        step = self._tick_step(scale)
        rect = self.scene_rect_of()

        painter.setRenderHint(QPainter.Antialiasing, True)
        font = theme.mono_font(7)
        painter.setFont(font)

        # top ruler
        painter.fillRect(QRect(0, 0, self.width(), self.RULER),
                         QColor(pal.canvas_ruler_bg))
        painter.setPen(QPen(QColor(pal.canvas_ruler_line), 1))
        painter.drawLine(0, self.RULER - 1, self.width(), self.RULER - 1)
        self._paint_axis(painter, rect.left(), rect.right(), step, horizontal=True,
                         origin=self.RULER, length=self.width(), offset=self.RULER)

        # left ruler
        painter.fillRect(QRect(0, 0, self.RULER, self.height()),
                         QColor(pal.canvas_ruler_bg))
        painter.drawLine(self.RULER - 1, 0, self.RULER - 1, self.height())
        self._paint_axis(painter, rect.top(), rect.bottom(), step, horizontal=False,
                         origin=self.RULER, length=self.height(), offset=self.RULER)

        # corner box, with the live cursor position
        painter.fillRect(QRect(0, 0, self.RULER, self.RULER),
                         QColor(pal.canvas_ruler_bg))
        painter.setPen(QPen(QColor(pal.canvas_ruler_line), 1))
        painter.drawLine(self.RULER - 1, self.RULER - 1, self.width(), self.RULER - 1)
        painter.drawLine(self.RULER - 1, 0, self.RULER - 1, self.height())
        if self._cursor_scene is not None:
            painter.setPen(QColor(pal.canvas_ruler_text))
            text = f"{self._cursor_scene.x():.0f}, {self._cursor_scene.y():.0f}"
            painter.save()
            painter.translate(self.RULER, self.RULER)
            painter.rotate(180)
            painter.drawText(QRect(-self.RULER, -13, self.RULER, 13),
                             Qt.AlignCenter, text)
            painter.restore()

    def _paint_axis(self, painter, lo, hi, step, horizontal, origin, length, offset):
        pal = theme.current()
        painter.setPen(QColor(pal.canvas_ruler_line))
        first = int(lo // step) * step
        value = first
        while value <= hi + step:
            if horizontal:
                x = int(self.mapFromScene(QPointF(value, 0)).x())
                painter.setPen(QColor(pal.canvas_ruler_line))
                painter.drawLine(x, origin - 5, x, origin)
                painter.setPen(QColor(pal.canvas_ruler_text))
                painter.drawText(QRect(x - 30, origin - 15, 60, 13),
                                 Qt.AlignCenter, f"{value:g}")
            else:
                y = int(self.mapFromScene(QPointF(0, value)).y())
                if y < origin:
                    value += step
                    continue
                painter.setPen(QColor(pal.canvas_ruler_line))
                painter.drawLine(origin - 5, y, origin, y)
                painter.setPen(QColor(pal.canvas_ruler_text))
                # Labels run along the strip, so they have to be turned 90
                # degrees; drawn upright they are clipped by the 22px width.
                painter.save()
                painter.translate(2, y)
                painter.rotate(-90)
                painter.drawText(QRect(-40, -6, 80, 12), Qt.AlignCenter,
                                 f"{value:g}")
                painter.restore()
            value += step

    def _paint_crosshair(self, painter):
        """A faint guide to the pointer, so a component can be lined up on a
        grid dot without holding the ruler against it."""
        if self._cursor_scene is None:
            return
        pal = theme.current()
        pen = QPen(QColor(pal.canvas_dot_major), self.cursor_width, Qt.DotLine)
        painter.setPen(pen)
        x = self.mapFromScene(self._cursor_scene).x()
        y = self.mapFromScene(self._cursor_scene).y()
        painter.drawLine(x, 0, x, self.viewport().height())
        painter.drawLine(0, y, self.viewport().width(), y)



class SchematicEditor(QMainWindow):
    """The flagship editor window."""

    def __init__(self):
        super().__init__()
        # Qt renders QIcon pixmaps at device resolution only when
        # AA_UseHighDpiPixmaps is set. main() asks for it before the
        # QApplication exists; set it here too so an embedded window (a test,
        # a launcher that builds its own QApplication) gets sharp icons at
        # 150/200% display scale instead of an 18-device-pixel bitmap
        # stretched by the style. Post-construction is honoured: QIcon reads
        # the attribute when the pixmap is requested.
        app = QApplication.instance()
        if app is not None and not app.testAttribute(Qt.AA_UseHighDpiPixmaps):
            app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        self._icon_names = {}
        # Default until _load_session() reads view/icon_scale; must exist
        # before _build_ui() renders the first palette symbol.
        self._icon_scale = "medium"
        self._current_path = None
        self._dirty = False
        self.setWindowTitle("WOSP Schematic Editor")
        self.resize(1440, 900)

        self.model = SchematicNetlistEngine()
        self.scene = SchematicScene(self.model, self)
        self.view = SchematicView(self.scene, self)
        # Floor on the canvas: a sibling pane may demand room, but the editor
        # must never be squeezed into a sliver by its own layout.
        self.view.setMinimumWidth(420)
        self.ng = None                      # lazily created NgSpiceEngine

        self._build_ui()
        self._build_actions()
        pg.setConfigOption("antialias", True)
        pg.setConfigOption("useOpenGL", False)
        self._restyle_plots()
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
        self._connect_document_signals()
        self._load_session()
        self._update_title()

    def _connect_document_signals(self):
        """Mark the document dirty on any edit, so the title bar can say so."""
        self.scene.documentChanged.connect(self._mark_dirty)

    def _mark_dirty(self):
        self._dirty = True
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self._current_path) if self._current_path else "Untitled"
        self.setWindowTitle(f"{name}{'*' if self._dirty else ''} - WOWKISPICE")

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
            self.statusBar().showMessage("Nothing is running")
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
            # Fresh capture: output_logs accumulates for the engine's whole
            # lifetime, and _meas_result_lines() reads the block that follows
            # this run's analysis only.
            self.ng.output_logs.clear()
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
        # .meas directives execute inside ngspice but their results used to be
        # swallowed with the rest of the console output - the user wrote a
        # measurement and the app never showed the number. Surface them.
        meas_results = self._meas_result_lines()
        for line in meas_results:
            self.log(f"meas: {line}")
        if not meas_results and any(l.lower().startswith(".meas")
                                    for l in lines):
            self.log("meas: no results - check the .meas lines for typos, "
                     "and that the analysis ran to completion")

    def _meas_result_lines(self):
        """What ngspice printed for the .meas directives in the netlist.

        ngspice reports every .meas result after the analysis block, e.g.::

            stdout Measurements for Transient Analysis
            stdout vout_max            =  4.32373e+00 at=  3.00110e-03

        Those lines land in NgSpiceEngine.output_logs. Failures print as
        `.meas: ...` instead; both are worth showing - a measurement that
        silently vanishes is the exact "poorly documented measurement"
        complaint this app is supposed to fix.
        """
        lines, inside = [], False
        for raw in getattr(self.ng, "output_logs", None) or []:
            line = raw
            for prefix in ("stdout ", "stderr "):
                if line.startswith(prefix):
                    line = line[len(prefix):]
            line = line.rstrip()
            if "Measurements for" in line:
                inside = True
                continue
            if inside:
                if line.strip() and "=" in line:
                    lines.append(line.strip())
                    continue
                inside = False
                continue
            if line.lower().startswith(".meas"):
                lines.append(line.strip())
        return lines

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

    def _build_palette(self):
        """Component palette: a symbol preview, the SPICE prefix, and a filter.

        The old palette was a flat list of names with no way to search it, which
        made placing a part in a 20-symbol library a scrolling exercise. Rows
        carry the drawn symbol as their icon and the prefix that will be used,
        so the designator is predictable before the click rather than after.
        """
        palette = QWidget()
        outer = QVBoxLayout(palette)
        outer.setContentsMargins(8, 8, 6, 8)
        outer.setSpacing(6)

        title = QLabel("Components")
        title.setStyleSheet("font-weight: 600;")
        outer.addWidget(title)

        self.palette_filter = QLineEdit()
        self.palette_filter.setPlaceholderText("filter parts...")
        self.palette_filter.setClearButtonEnabled(True)
        self.palette_filter.textChanged.connect(self._filter_palette)
        outer.addWidget(self.palette_filter)

        spec = ICON_SCALES.get(self._icon_scale, ICON_SCALES["medium"])
        self.palette_list = QListWidget()
        self.palette_list.setIconSize(QSize(spec["palette"], spec["palette"]))
        self.palette_list.setUniformItemSizes(False)
        self._palette_types = []
        for group, types in PALETTE_GROUPS:
            header = QListWidgetItem(group)
            header.setFlags(Qt.NoItemFlags)
            header.setForeground(QBrush(QColor(theme.current().dim)))
            header.setSizeHint(QSize(0, 20))
            self.palette_list.addItem(header)
            for comp_type in types:
                item = QListWidgetItem(self._palette_row_text(comp_type))
                item.setData(Qt.UserRole, comp_type)
                item.setIcon(self._symbol_icon(comp_type))
                item.setSizeHint(QSize(0, spec["row"]))
                hot = hotkey_of(comp_type)
                if hot:
                    item.setToolTip(
                        f"{label_of(comp_type)} - press {hot} to arm it, then "
                        "click the sheet to place (Esc cancels)")
                else:
                    # Reachable only if a symbol is added without a letter;
                    # a test enforces that, so say so rather than fail quietly.
                    item.setToolTip(
                        f"{label_of(comp_type)} - no letter key; click to arm, "
                        "then click the sheet to place (Esc cancels)")
                self.palette_list.addItem(item)
                self._palette_types.append(comp_type)
        self.palette_list.currentRowChanged.connect(self._on_palette_selected)
        outer.addWidget(self.palette_list, 1)

        hint = QLabel("Click a part, then click the canvas.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().dim};")
        outer.addWidget(hint)
        self.palette_hint = hint
        palette.setMaximumWidth(250)
        palette.setMinimumWidth(210)
        return palette

    def _palette_row_text(self, comp_type):
        from ui.schematic_symbols import prefix_of
        hot = hotkey_of(comp_type)
        suffix = f"   {hot}" if hot else ""
        return f"{label_of(comp_type)}   [{prefix_of(comp_type)}]{suffix}"

    def _symbol_icon(self, comp_type):
        """Render the actual symbol as the palette icon.

        Drawn from the same draw_symbol() the canvas uses, so the palette cannot
        drift away from what gets placed. Board bodies get scaled down or they
        fill the whole cell.
        """
        from PyQt5.QtGui import QIcon, QPixmap
        from ui.schematic_items import draw_symbol
        from ui.schematic_symbols import extent_of
        ex, ey, ew, eh = extent_of(comp_type)
        size = ICON_SCALES.get(self._icon_scale,
                               ICON_SCALES["medium"])["palette"]
        # Boards are far larger than passives; fit them into the same cell.
        longest = max(ew, eh, 1)
        scale = min(1.0, (size - 4) / float(longest))
        px = QPixmap(size, size)
        px.setDevicePixelRatio(1.0)
        px.fill(Qt.transparent)
        painter = QPainter(px)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(size / 2 - (ex + ew / 2) * scale,
                          size / 2 - (ey + eh / 2) * scale)
        painter.scale(scale, scale)
        draw_symbol(painter, comp_type)
        painter.end()
        return QIcon(px)

    def _filter_palette(self, text):
        """Filter by part name or SPICE prefix; hide group headers that no
        longer have a visible child so the list does not show empty sections."""
        needle = (text or "").strip().lower()
        current = self.palette_list.currentRow()
        visible_component_rows = 0
        for row in range(self.palette_list.count()):
            item = self.palette_list.item(row)
            comp_type = item.data(Qt.UserRole)
            if comp_type is None:
                item.setHidden(False)     # headers settled below
                continue
            if needle:
                from ui.schematic_symbols import prefix_of
                haystack = f"{label_of(comp_type)} {comp_type} {prefix_of(comp_type)}"
                match = needle in haystack.lower()
            else:
                match = True
            item.setHidden(not match)
            visible_component_rows += 1 if match else 0
        for row in range(self.palette_list.count()):
            item = self.palette_list.item(row)
            if item.data(Qt.UserRole) is not None:
                continue
            has_visible_child = False
            for r2 in range(row + 1, self.palette_list.count()):
                nxt = self.palette_list.item(r2)
                if nxt.data(Qt.UserRole) is None:
                    break
                if not nxt.isHidden():
                    has_visible_child = True
                    break
            item.setHidden(not has_visible_child)
        if needle and visible_component_rows == 0:
            self.palette_hint.setText("No part matches that filter.")
        elif needle:
            self.palette_hint.setText(
                f"{visible_component_rows} match. Click a part, then the canvas.")
        else:
            self.palette_hint.setText("Click a part, then click the canvas.")
        self.palette_list.setCurrentRow(-1)
        if self.palette_list.currentRow() == -1 and current >= 0:
            self.palette_list.setCurrentRow(current)

    def _build_ui(self):
        palette = self._build_palette()

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

        self.results_tabs = results_tabs = QTabWidget()
        # The tab bar must never dictate the window minimum.  With scroll
        # buttons disabled and elision off, QTabBar requests the summed width
        # of all 15 tab labels (~2551 px), and QSplitter passes that straight
        # up to the window, starving the canvas down to its 420 px floor.
        # Scrolling plus right-elision collapses the bar's minimum instead.
        results_tabs.setUsesScrollButtons(True)
        results_tabs.setElideMode(Qt.ElideRight)
        self.results_tabs.setDocumentMode(False)
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

        # Per-trace visibility, the way an EDA waveform pane works: the trace
        # list is the control surface, and clicking a row chooses what the
        # cursors measure instead of guessing from the legend.
        self.trace_list = QTreeWidget()
        self.trace_list.setHeaderLabels(["Trace", "Value"])
        self.trace_list.setRootIsDecorated(False)
        self.trace_list.setMaximumWidth(250)
        self.trace_list.setMinimumWidth(170)
        self.trace_list.itemClicked.connect(self._on_trace_row_clicked)
        self.trace_list.itemChanged.connect(self._on_trace_row_changed)

        transient_side = QWidget()
        side_layout = QVBoxLayout(transient_side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(QLabel("Traces"))
        side_layout.addWidget(self.trace_list, 1)
        hint = QLabel("Untick to hide. Click a row to measure it.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.current().dim};")
        side_layout.addWidget(hint)

        transient_split = QSplitter(Qt.Horizontal)
        transient_panel = QWidget()
        transient_layout = QVBoxLayout(transient_panel)
        transient_layout.setContentsMargins(0, 0, 0, 0)
        transient_layout.addWidget(self.plot)
        transient_layout.addWidget(self.measure_label)
        transient_split.addWidget(transient_panel)
        transient_split.addWidget(transient_side)
        transient_split.setStretchFactor(0, 1)
        transient_split.setCollapsible(1, True)
        results_tabs.addTab(transient_split, "Waveforms")

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
        #
        # Layout note: these controls used to sit in one unshrinkable row whose
        # minimum width was 1227 px (mostly the two QDoubleSpinBox hints, which
        # size to their range text).  QTabWidget hands the widest page's minimum
        # to the QSplitter, and that starved the schematic view down to 97 px of
        # a 1329 px pane.  The controls now sit in a scroll area on a page with
        # no size constraint, so the pane can shrink and the controls scroll
        # instead of dictating the window's minimum width.
        bode_panel = QWidget()
        bode_layout = QVBoxLayout(bode_panel)
        bode_layout.setSizeConstraint(QLayout.SetNoConstraint)
        bode_controls_host = QWidget()
        bode_controls = QGridLayout(bode_controls_host)
        bode_controls.setContentsMargins(0, 0, 0, 0)
        bode_controls.addWidget(QLabel(" Output net "), 0, 0)
        self.bode_net_box = QComboBox()
        self.bode_net_box.setEditable(True)
        bode_controls.addWidget(self.bode_net_box, 0, 1)
        bode_controls.addWidget(QLabel(" Start Hz "), 1, 0)
        self.bode_start_box = QDoubleSpinBox()
        self.bode_start_box.setRange(0.001, 1e9)
        self.bode_start_box.setDecimals(3)
        self.bode_start_box.setValue(1.0)
        bode_controls.addWidget(self.bode_start_box, 1, 1)
        bode_controls.addWidget(QLabel(" Stop Hz "), 1, 2)
        self.bode_stop_box = QDoubleSpinBox()
        self.bode_stop_box.setRange(0.01, 1e12)
        self.bode_stop_box.setDecimals(1)
        self.bode_stop_box.setValue(1e6)
        bode_controls.addWidget(self.bode_stop_box, 1, 3)
        bode_run = QPushButton("Run AC Sweep")
        bode_run.clicked.connect(self.run_bode)
        bode_controls.addWidget(bode_run, 1, 4)
        bode_controls.setColumnStretch(1, 1)
        bode_controls_scroll = QScrollArea()
        bode_controls_scroll.setFrameShape(QFrame.NoFrame)
        bode_controls_scroll.setWidget(bode_controls_host)
        bode_controls_scroll.setWidgetResizable(True)
        bode_controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # AsNeeded, not AlwaysOff: the height below is fixed at build time, so a
        # later font change would otherwise clip the controls with no way to
        # reach them. It does not appear in practice (76 px available, 62 used).
        bode_controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        bode_controls_scroll.setFixedHeight(
            bode_controls_host.sizeHint().height() + 14)
        bode_layout.addWidget(bode_controls_scroll)

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

        # ---- Timing / digital lanes tab ----
        self.timing_plot = pg.PlotWidget(background="w", title="Timing diagram")
        self.timing_plot.addLegend()
        self.timing_plot.setLabel("bottom", "Time", units="ms")
        self.timing_plot.setLabel("left", "Digital level")
        self.timing_info = QLabel("No timing diagram yet.")
        self.timing_info.setWordWrap(True)
        self.timing_panel = timing_panel = QWidget()
        timing_layout = QVBoxLayout(timing_panel)
        timing_layout.setContentsMargins(0, 0, 0, 0)
        timing_layout.addWidget(self.timing_plot)
        timing_layout.addWidget(self.timing_info)
        results_tabs.addTab(timing_panel, "Timing")

        # ---- Step response metrics tab ----
        step_panel = QWidget()
        step_layout = QVBoxLayout(step_panel)
        step_layout.setContentsMargins(0, 0, 0, 0)
        step_controls_host = QWidget()
        step_controls = QGridLayout(step_controls_host)
        step_controls.setContentsMargins(0, 0, 0, 0)
        step_controls.addWidget(QLabel(" Output net "), 0, 0)
        self.step_net_box = QComboBox()
        self.step_net_box.setEditable(True)
        step_controls.addWidget(self.step_net_box, 0, 1)
        step_run = QPushButton("Measure Step Response")
        step_run.clicked.connect(self.analyze_step_response)
        step_controls.addWidget(step_run, 0, 2)
        step_controls.setColumnStretch(1, 1)
        step_controls_scroll = QScrollArea()
        step_controls_scroll.setFrameShape(QFrame.NoFrame)
        step_controls_scroll.setWidget(step_controls_host)
        step_controls_scroll.setWidgetResizable(True)
        step_controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        step_controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        step_controls_scroll.setFixedHeight(step_controls_host.sizeHint().height() + 14)
        step_layout.addWidget(step_controls_scroll)
        self.step_plot = pg.PlotWidget(background="w", title="Step response")
        self.step_plot.addLegend()
        self.step_plot.setLabel("bottom", "Time", units="ms")
        self.step_plot.setLabel("left", "Voltage", units="V")
        self.step_info = QLabel("No step response yet.")
        self.step_info.setWordWrap(True)
        self.step_last = None
        step_layout.addWidget(self.step_plot)
        step_layout.addWidget(self.step_info)
        results_tabs.addTab(step_panel, "Step Response")

        # ---- Noise analysis tab ----
        noise_panel = QWidget()
        noise_layout = QVBoxLayout(noise_panel)
        noise_layout.setContentsMargins(0, 0, 0, 0)
        noise_controls_host = QWidget()
        noise_controls = QGridLayout(noise_controls_host)
        noise_controls.setContentsMargins(0, 0, 0, 0)
        noise_controls.addWidget(QLabel(" Output net "), 0, 0)
        self.noise_net_box = QComboBox()
        self.noise_net_box.setEditable(True)
        noise_controls.addWidget(self.noise_net_box, 0, 1)
        noise_controls.addWidget(QLabel(" Start Hz "), 1, 0)
        self.noise_start_box = QDoubleSpinBox()
        self.noise_start_box.setRange(0.01, 1e9)
        self.noise_start_box.setDecimals(3)
        self.noise_start_box.setValue(10.0)
        noise_controls.addWidget(self.noise_start_box, 1, 1)
        noise_controls.addWidget(QLabel(" Stop Hz "), 1, 2)
        self.noise_stop_box = QDoubleSpinBox()
        self.noise_stop_box.setRange(10.0, 1e12)
        self.noise_stop_box.setDecimals(1)
        self.noise_stop_box.setValue(1e6)
        noise_controls.addWidget(self.noise_stop_box, 1, 3)
        noise_controls.addWidget(QLabel(" Points/dec "), 1, 4)
        self.noise_pts_box = QSpinBox()
        self.noise_pts_box.setRange(1, 100)
        self.noise_pts_box.setValue(10)
        noise_controls.addWidget(self.noise_pts_box, 1, 5)
        noise_run = QPushButton("Run Noise Analysis")
        noise_run.clicked.connect(self.run_noise_analysis)
        noise_controls.addWidget(noise_run, 1, 6)
        noise_controls.setColumnStretch(1, 1)
        noise_controls_scroll = QScrollArea()
        noise_controls_scroll.setFrameShape(QFrame.NoFrame)
        noise_controls_scroll.setWidget(noise_controls_host)
        noise_controls_scroll.setWidgetResizable(True)
        noise_controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        noise_controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        noise_controls_scroll.setFixedHeight(noise_controls_host.sizeHint().height() + 14)
        noise_layout.addWidget(noise_controls_scroll)
        self.noise_plot = pg.PlotWidget(background="w", title="Noise spectral density")
        self.noise_plot.addLegend()
        self.noise_plot.setLabel("bottom", "Frequency", units="Hz")
        self.noise_plot.setLabel("left", "Density", units="V/sqrt(Hz)")
        self.noise_info = QLabel("No noise analysis yet.")
        self.noise_info.setWordWrap(True)
        self.noise_last = None
        noise_layout.addWidget(self.noise_plot)
        noise_layout.addWidget(self.noise_info)
        results_tabs.addTab(noise_panel, "Noise")

        # ---- Distortion analysis tab ----
        disto_panel = QWidget()
        disto_layout = QVBoxLayout(disto_panel)
        disto_layout.setContentsMargins(0, 0, 0, 0)
        disto_controls_host = QWidget()
        disto_controls = QGridLayout(disto_controls_host)
        disto_controls.setContentsMargins(0, 0, 0, 0)
        disto_controls.addWidget(QLabel(" Output net "), 0, 0)
        self.disto_net_box = QComboBox()
        self.disto_net_box.setEditable(True)
        disto_controls.addWidget(self.disto_net_box, 0, 1)
        disto_controls.addWidget(QLabel(" Start Hz "), 1, 0)
        self.disto_start_box = QDoubleSpinBox()
        self.disto_start_box.setRange(0.01, 1e9)
        self.disto_start_box.setDecimals(3)
        self.disto_start_box.setValue(100.0)
        disto_controls.addWidget(self.disto_start_box, 1, 1)
        disto_controls.addWidget(QLabel(" Stop Hz "), 1, 2)
        self.disto_stop_box = QDoubleSpinBox()
        self.disto_stop_box.setRange(10.0, 1e12)
        self.disto_stop_box.setDecimals(1)
        self.disto_stop_box.setValue(100000.0)
        disto_controls.addWidget(self.disto_stop_box, 1, 3)
        disto_controls.addWidget(QLabel(" Pts/dec "), 1, 4)
        self.disto_pts_box = QSpinBox()
        self.disto_pts_box.setRange(1, 100)
        self.disto_pts_box.setValue(4)
        disto_controls.addWidget(self.disto_pts_box, 1, 5)
        disto_run = QPushButton("Run Distortion Analysis")
        disto_run.clicked.connect(self.run_distortion_analysis)
        disto_controls.addWidget(disto_run, 1, 6)
        disto_controls.setColumnStretch(1, 1)
        disto_controls_scroll = QScrollArea()
        disto_controls_scroll.setFrameShape(QFrame.NoFrame)
        disto_controls_scroll.setWidget(disto_controls_host)
        disto_controls_scroll.setWidgetResizable(True)
        disto_controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        disto_controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        disto_controls_scroll.setFixedHeight(disto_controls_host.sizeHint().height() + 14)
        disto_layout.addWidget(disto_controls_scroll)
        self.disto_plot = pg.PlotWidget(background="w", title="Harmonic distortion")
        self.disto_plot.addLegend()
        self.disto_plot.setLabel("bottom", "Frequency", units="Hz")
        self.disto_plot.setLabel("left", "HD", units="dBc")
        self.disto_info = QLabel("No distortion analysis yet.")
        self.disto_info.setWordWrap(True)
        self.disto_last = None
        disto_layout.addWidget(self.disto_plot)
        disto_layout.addWidget(self.disto_info)
        results_tabs.addTab(disto_panel, "Distortion")

        # ---- Monte Carlo / yield tab ----
        mc_panel = QWidget()
        mc_layout = QVBoxLayout(mc_panel)
        mc_layout.setContentsMargins(0, 0, 0, 0)
        mc_controls_host = QWidget()
        mc_controls = QGridLayout(mc_controls_host)
        mc_controls.setContentsMargins(0, 0, 0, 0)
        mc_controls.addWidget(QLabel(" Output net "), 0, 0)
        self.mc_net_box = QComboBox()
        self.mc_net_box.setEditable(True)
        mc_controls.addWidget(self.mc_net_box, 0, 1)
        mc_controls.addWidget(QLabel(" Iterations "), 1, 0)
        self.mc_iters_box = QSpinBox()
        self.mc_iters_box.setRange(2, 1000)
        self.mc_iters_box.setValue(40)
        mc_controls.addWidget(self.mc_iters_box, 1, 1)
        mc_controls.addWidget(QLabel(" Tol % "), 1, 2)
        self.mc_tol_box = QDoubleSpinBox()
        self.mc_tol_box.setRange(0.01, 100.0)
        self.mc_tol_box.setDecimals(2)
        self.mc_tol_box.setValue(5.0)
        mc_controls.addWidget(self.mc_tol_box, 1, 3)
        mc_controls.addWidget(QLabel(" Yield % "), 1, 4)
        self.mc_yield_box = QDoubleSpinBox()
        self.mc_yield_box.setRange(0.0, 100.0)
        self.mc_yield_box.setDecimals(2)
        self.mc_yield_box.setValue(5.0)
        mc_controls.addWidget(self.mc_yield_box, 1, 5)
        mc_run = QPushButton("Run Monte Carlo / Yield")
        mc_run.clicked.connect(self.run_yield_study)
        mc_controls.addWidget(mc_run, 1, 6)
        mc_controls.setColumnStretch(1, 1)
        mc_controls_scroll = QScrollArea()
        mc_controls_scroll.setFrameShape(QFrame.NoFrame)
        mc_controls_scroll.setWidget(mc_controls_host)
        mc_controls_scroll.setWidgetResizable(True)
        mc_controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        mc_controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        mc_controls_scroll.setFixedHeight(mc_controls_host.sizeHint().height() + 14)
        mc_layout.addWidget(mc_controls_scroll)
        self.mc_plot = pg.PlotWidget(background="w", title="Monte Carlo histogram")
        self.mc_plot.addLegend()
        self.mc_plot.setLabel("bottom", "Settled value", units="V")
        self.mc_plot.setLabel("left", "Samples")
        self.mc_info = QLabel("No Monte Carlo run yet.")
        self.mc_info.setWordWrap(True)
        self.mc_last = None
        self.mc_bars = None
        mc_layout.addWidget(self.mc_plot)
        mc_layout.addWidget(self.mc_info)
        results_tabs.addTab(mc_panel, "Monte Carlo")

        # ---- Parametric sweep tab ----
        sweep_panel = QWidget()
        sweep_layout = QVBoxLayout(sweep_panel)
        sweep_layout.setContentsMargins(0, 0, 0, 0)
        sweep_run_row = QHBoxLayout()
        refresh_sweep = QPushButton("Refresh sweep controls")
        refresh_sweep.clicked.connect(self.refresh_sweep_controls)
        sweep_run_row.addWidget(refresh_sweep)
        sweep_run_row.addStretch(1)
        sweep_layout.addLayout(sweep_run_row)
        sweep_controls_host = QWidget()
        sweep_controls = QGridLayout(sweep_controls_host)
        sweep_controls.setContentsMargins(0, 0, 0, 0)
        sweep_controls.addWidget(QLabel(" Component "), 0, 0)
        self.sweep_comp_box = QComboBox()
        sweep_controls.addWidget(self.sweep_comp_box, 0, 1)
        sweep_controls.addWidget(QLabel(" Sweep net "), 1, 0)
        self.sweep_net_box = QComboBox()
        self.sweep_net_box.setEditable(True)
        sweep_controls.addWidget(self.sweep_net_box, 1, 1)
        sweep_controls.addWidget(QLabel(" Start "), 2, 0)
        self.sweep_start_box = QDoubleSpinBox()
        self.sweep_start_box.setRange(0.0, 1e9)
        self.sweep_start_box.setDecimals(3)
        sweep_controls.addWidget(self.sweep_start_box, 2, 1)
        sweep_controls.addWidget(QLabel(" Stop "), 2, 2)
        self.sweep_stop_box = QDoubleSpinBox()
        self.sweep_stop_box.setRange(0.0, 1e9)
        self.sweep_stop_box.setDecimals(3)
        sweep_controls.addWidget(self.sweep_stop_box, 2, 3)
        sweep_controls.addWidget(QLabel(" Steps "), 3, 0)
        self.sweep_steps_box = QSpinBox()
        self.sweep_steps_box.setRange(2, 100)
        self.sweep_steps_box.setValue(5)
        sweep_controls.addWidget(self.sweep_steps_box, 3, 1)
        sweep_run = QPushButton("Run Parametric Sweep")
        sweep_run.clicked.connect(self.run_sweep)
        sweep_controls.addWidget(sweep_run, 3, 2)
        sweep_controls.setColumnStretch(1, 1)
        sweep_controls_scroll = QScrollArea()
        sweep_controls_scroll.setFrameShape(QFrame.NoFrame)
        sweep_controls_scroll.setWidget(sweep_controls_host)
        sweep_controls_scroll.setWidgetResizable(True)
        sweep_controls_scroll.setFixedHeight(sweep_controls_host.sizeHint().height() + 14)
        sweep_layout.addWidget(sweep_controls_scroll)
        self.sweep_plot = pg.PlotWidget(background="w", title="Parametric sweep overlay")
        self.sweep_plot.addLegend()
        self.sweep_plot.setLabel("bottom", "Time", units="ms")
        self.sweep_plot.setLabel("left", "Voltage", units="V")
        self.sweep_info = QLabel("No sweep yet.")
        self.sweep_info.setWordWrap(True)
        self.sweep_last = None
        sweep_layout.addWidget(self.sweep_plot)
        sweep_layout.addWidget(self.sweep_info)
        results_tabs.addTab(sweep_panel, "Parametric Sweep")

        # ---- I-V curve tracer tab ----
        curve_panel = QWidget()
        curve_layout = QVBoxLayout(curve_panel)
        curve_layout.setContentsMargins(0, 0, 0, 0)
        curve_controls_host = QWidget()
        curve_controls = QGridLayout(curve_controls_host)
        curve_controls.setContentsMargins(0, 0, 0, 0)
        curve_controls.addWidget(QLabel(" Device "), 0, 0)
        self.curve_device_box = QComboBox()
        self.curve_device_box.addItem("MOSFET (IRF540N family)")
        self.curve_device_box.addItem("Diode families (Schottky/Si/Zener)")
        curve_controls.addWidget(self.curve_device_box, 0, 1)
        curve_controls.addWidget(QLabel(" Vmax "), 1, 0)
        self.curve_vmax_box = QDoubleSpinBox()
        self.curve_vmax_box.setRange(0.1, 100.0)
        self.curve_vmax_box.setDecimals(2)
        self.curve_vmax_box.setValue(15.0)
        curve_controls.addWidget(self.curve_vmax_box, 1, 1)
        curve_controls.addWidget(QLabel(" Points "), 1, 2)
        self.curve_pts_box = QSpinBox()
        self.curve_pts_box.setRange(10, 500)
        self.curve_pts_box.setValue(40)
        curve_controls.addWidget(self.curve_pts_box, 1, 3)
        curve_controls.addWidget(QLabel(" Vfmax "), 2, 0)
        self.curve_vfmax_box = QDoubleSpinBox()
        self.curve_vfmax_box.setRange(0.1, 5.0)
        self.curve_vfmax_box.setDecimals(2)
        self.curve_vfmax_box.setValue(1.0)
        curve_controls.addWidget(self.curve_vfmax_box, 2, 1)
        curve_run = QPushButton("Run Curve Tracer")
        curve_run.clicked.connect(self.run_curve_tracer)
        curve_controls.addWidget(curve_run, 2, 2)
        curve_controls.setColumnStretch(1, 1)
        curve_controls_scroll = QScrollArea()
        curve_controls_scroll.setFrameShape(QFrame.NoFrame)
        curve_controls_scroll.setWidget(curve_controls_host)
        curve_controls_scroll.setWidgetResizable(True)
        curve_controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        curve_controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        curve_controls_scroll.setFixedHeight(curve_controls_host.sizeHint().height() + 14)
        curve_layout.addWidget(curve_controls_scroll)
        self.curve_plot = pg.PlotWidget(background="w", title="I-V curve tracer")
        self.curve_plot.addLegend()
        self.curve_plot.setLabel("bottom", "Voltage", units="V")
        self.curve_plot.setLabel("left", "Current", units="A")
        self.curve_info = QLabel("No curve tracer run yet.")
        self.curve_info.setWordWrap(True)
        self.curve_last = None
        curve_layout.addWidget(self.curve_plot)
        curve_layout.addWidget(self.curve_info)
        results_tabs.addTab(curve_panel, "I-V Curve Tracer")

        # ---- PV / MPPT tab ----
        pv_panel = QWidget()
        pv_layout = QVBoxLayout(pv_panel)
        pv_layout.setContentsMargins(0, 0, 0, 0)
        pv_controls_host = QWidget()
        pv_controls = QGridLayout(pv_controls_host)
        pv_controls.setContentsMargins(0, 0, 0, 0)
        pv_controls.addWidget(QLabel(" Irradiance (W/m^2) "), 0, 0)
        self.pv_irr_box = QDoubleSpinBox()
        self.pv_irr_box.setRange(0.0, 2000.0)
        self.pv_irr_box.setDecimals(1)
        self.pv_irr_box.setValue(1000.0)
        pv_controls.addWidget(self.pv_irr_box, 0, 1)
        pv_controls.addWidget(QLabel(" Temperature (C) "), 1, 0)
        self.pv_temp_box = QDoubleSpinBox()
        self.pv_temp_box.setRange(-40.0, 85.0)
        self.pv_temp_box.setDecimals(1)
        self.pv_temp_box.setValue(25.0)
        pv_controls.addWidget(self.pv_temp_box, 1, 1)
        pv_controls.addWidget(QLabel(" Points "), 2, 0)
        self.pv_pts_box = QSpinBox()
        self.pv_pts_box.setRange(10, 1000)
        self.pv_pts_box.setValue(150)
        pv_controls.addWidget(self.pv_pts_box, 2, 1)
        pv_run = QPushButton("Run Solar PV / MPPT Trace")
        pv_run.clicked.connect(self.run_pv)
        pv_controls.addWidget(pv_run, 2, 2)
        pv_controls.setColumnStretch(1, 1)
        pv_controls_scroll = QScrollArea()
        pv_controls_scroll.setFrameShape(QFrame.NoFrame)
        pv_controls_scroll.setWidget(pv_controls_host)
        pv_controls_scroll.setWidgetResizable(True)
        pv_controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        pv_controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        pv_controls_scroll.setFixedHeight(pv_controls_host.sizeHint().height() + 14)
        pv_layout.addWidget(pv_controls_scroll)
        self.pv_iv_plot = pg.PlotWidget(background="w", title="I-V curve")
        self.pv_iv_plot.addLegend()
        self.pv_iv_plot.setLabel("bottom", "Voltage", units="V")
        self.pv_iv_plot.setLabel("left", "Current", units="A")
        self.pv_p_plot = pg.PlotWidget(background="w", title="P-V curve")
        self.pv_p_plot.addLegend()
        self.pv_p_plot.setLabel("bottom", "Voltage", units="V")
        self.pv_p_plot.setLabel("left", "Power", units="W")
        self.pv_info = QLabel("No PV trace yet.")
        self.pv_info.setWordWrap(True)
        self.pv_last = None
        pv_layout.addWidget(self.pv_iv_plot)
        pv_layout.addWidget(self.pv_p_plot)
        pv_layout.addWidget(self.pv_info)
        results_tabs.addTab(pv_panel, "PV / MPPT")

        # ---- AWG tab ----
        awg_panel = QWidget()
        awg_layout = QVBoxLayout(awg_panel)
        awg_layout.setContentsMargins(0, 0, 0, 0)
        awg_controls_host = QWidget()
        awg_controls = QGridLayout(awg_controls_host)
        awg_controls.setContentsMargins(0, 0, 0, 0)
        awg_controls.addWidget(QLabel(" Waveform "), 0, 0)
        self.awg_type_box = QComboBox()
        self.awg_type_box.addItems(["Sine", "Square", "Triangle", "Sawtooth",
                                    "White Noise", "Exponential Decay", "Chirp Sweep"])
        awg_controls.addWidget(self.awg_type_box, 0, 1)
        awg_controls.addWidget(QLabel(" Frequency (Hz) "), 1, 0)
        self.awg_freq_box = QDoubleSpinBox()
        self.awg_freq_box.setRange(0.1, 1e6)
        self.awg_freq_box.setDecimals(3)
        self.awg_freq_box.setValue(1000.0)
        awg_controls.addWidget(self.awg_freq_box, 1, 1)
        awg_controls.addWidget(QLabel(" Amplitude (Vpp) "), 2, 0)
        self.awg_amp_box = QDoubleSpinBox()
        self.awg_amp_box.setRange(0.0, 20.0)
        self.awg_amp_box.setDecimals(3)
        self.awg_amp_box.setValue(3.3)
        awg_controls.addWidget(self.awg_amp_box, 2, 1)
        awg_controls.addWidget(QLabel(" Offset (V) "), 3, 0)
        self.awg_offset_box = QDoubleSpinBox()
        self.awg_offset_box.setRange(-10.0, 10.0)
        self.awg_offset_box.setDecimals(3)
        self.awg_offset_box.setValue(0.0)
        awg_controls.addWidget(self.awg_offset_box, 3, 1)
        awg_controls.addWidget(QLabel(" Duration (ms) "), 4, 0)
        self.awg_duration_box = QDoubleSpinBox()
        self.awg_duration_box.setRange(0.01, 10000.0)
        self.awg_duration_box.setDecimals(2)
        self.awg_duration_box.setValue(5.0)
        awg_controls.addWidget(self.awg_duration_box, 4, 1)
        awg_controls.addWidget(QLabel(" Points "), 5, 0)
        self.awg_points_box = QSpinBox()
        self.awg_points_box.setRange(100, 100000)
        self.awg_points_box.setValue(2000)
        awg_controls.addWidget(self.awg_points_box, 5, 1)
        awg_run = QPushButton("Generate AWG Waveform")
        awg_run.clicked.connect(self.run_awg)
        awg_controls.addWidget(awg_run, 5, 2)
        awg_controls.setColumnStretch(1, 1)
        awg_controls_scroll = QScrollArea()
        awg_controls_scroll.setFrameShape(QFrame.NoFrame)
        awg_controls_scroll.setWidget(awg_controls_host)
        awg_controls_scroll.setWidgetResizable(True)
        awg_controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        awg_controls_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        awg_controls_scroll.setFixedHeight(awg_controls_host.sizeHint().height() + 14)
        awg_layout.addWidget(awg_controls_scroll)
        self.awg_plot = pg.PlotWidget(background="w", title="AWG waveform")
        self.awg_plot.addLegend()
        self.awg_plot.setLabel("bottom", "Time", units="ms")
        self.awg_plot.setLabel("left", "Voltage", units="V")
        self.awg_info = QLabel("No AWG waveform yet.")
        self.awg_info.setWordWrap(True)
        self.awg_last = None
        awg_layout.addWidget(self.awg_plot)
        awg_layout.addWidget(self.awg_info)
        results_tabs.addTab(awg_panel, "AWG")

        # ---- Serial / UART decode tab (wiring only; view exists above) ----
        serial_controls_host = QWidget()
        serial_controls = QGridLayout(serial_controls_host)
        serial_controls.setContentsMargins(0, 0, 0, 0)
        serial_controls.addWidget(QLabel(" Decoded net "), 0, 0)
        self.serial_net_box = QComboBox()
        self.serial_net_box.setEditable(True)
        serial_controls.addWidget(self.serial_net_box, 0, 1)
        serial_controls.addWidget(QLabel(" Baud "), 1, 0)
        self.serial_baud_box = QSpinBox()
        self.serial_baud_box.setRange(300, 1000000)
        self.serial_baud_box.setSingleStep(100)
        self.serial_baud_box.setValue(115200)
        serial_controls.addWidget(self.serial_baud_box, 1, 1)
        serial_decode = QPushButton("Decode UART from net")
        serial_decode.clicked.connect(self.decode_uart_from_net)
        serial_controls.addWidget(serial_decode, 1, 2)
        serial_controls.setColumnStretch(1, 1)
        serial_controls_scroll = QScrollArea()
        serial_controls_scroll.setFrameShape(QFrame.NoFrame)
        serial_controls_scroll.setWidget(serial_controls_host)
        serial_controls_scroll.setWidgetResizable(True)
        serial_controls_scroll.setFixedHeight(serial_controls_host.sizeHint().height() + 14)
        serial_layout.addWidget(serial_controls_scroll)

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
        self.stop_button.setIcon(icons.icon("stop", theme.current().text))
        self.stop_button.setToolTip("Abort the running simulation (Ctrl+.)")
        self.stop_button.clicked.connect(self.stop_simulation)
        toolbar.addWidget(self.stop_button)

        # Simulation mode drives which path F2 takes.
        self.mode_box.currentTextChanged.connect(self._on_mode_changed)

    # ------------------------------------------------------------------
    # Menus, toolbar, shortcuts
    # ------------------------------------------------------------------
    def _action(self, text, slot, shortcut=None, tip="", icon_name=None):
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        if tip:
            act.setStatusTip(tip)
        # Tooltip = function AND keyboard shortcut. The toolbar and menus used
        # to set only the status tip, which appears nowhere on hover - the
        # LTspice "fighting the UI" complaint: no way to discover what a
        # button does or which key it owns. QAction falls back to bare text
        # when no tooltip is set, so the shortcut was never visible either.
        label = text.replace("&", "")
        head = f"{label} ({shortcut})" if shortcut else label
        act.setToolTip(f"{head} - {tip}" if tip else head)
        if icon_name:
            act.setIcon(icons.icon(icon_name, theme.current().text))
            self._icon_names[id(act)] = icon_name
        return act

    def _retheme_actions(self):
        """Re-tint every action icon after an appearance change."""
        pal = theme.current()
        for act_id, name in list(self._icon_names.items()):
            for act in self.actions():
                if id(act) == act_id:
                    act.setIcon(icons.icon(name, pal.text))
        icons.clear_cache()

    def _build_actions(self):
        run_act = self._action("Run Simulation", self.run_simulation, "F2",
                               "Compile the schematic and solve it in ngspice",
                               icon_name="run")
        stop_act = self._action("Stop", self.stop_simulation, "Ctrl+.",
                                "Abort the running simulation", icon_name="stop")
        self.stop_action = stop_act
        run_act.setFont(theme.ui_font(9, bold=True))

        self.toolbar_run = QToolBar("Main")
        self.toolbar_run.setObjectName("mainToolbar")
        spec = ICON_SCALES.get(self._icon_scale, ICON_SCALES["medium"])
        self.toolbar_run.setIconSize(QSize(spec["toolbar"], spec["toolbar"]))
        self.addToolBar(self.toolbar_run)
        self.toolbar_run.addAction(run_act)
        self.toolbar_run.addAction(stop_act)
        self.toolbar_run.addSeparator()
        for text, slot, shortcut, tip, glyph in (
                ("New", self.new_document, "Ctrl+N", "Start an empty schematic", "new"),
                ("Open", self.open_document, "Ctrl+O", "Open a .wosp schematic", "open"),
                ("Save", self.save_document, "Ctrl+S", "Save the schematic", "save")):
            self.toolbar_run.addAction(
                self._action(text, slot, shortcut, tip, icon_name=glyph))
        self.toolbar_run.addSeparator()
        self.toolbar_run.addAction(
            self._action("Undo", self.scene.undo, "Ctrl+Z",
                         "Undo the last edit", icon_name="undo"))
        self.toolbar_run.addAction(
            self._action("Redo", self.scene.redo, "Ctrl+Y",
                         "Redo the last undone edit", icon_name="redo"))
        self.toolbar_run.addSeparator()
        self.toolbar_run.addAction(
            self._action("Fit", self.view.fit_to_contents, "Ctrl+0",
                         "Zoom to fit the whole schematic", icon_name="fit"))
        self.toolbar_run.addAction(
            self._action("Zoom In", lambda: self.view.zoom_by(1.25), "Ctrl+=",
                         "Zoom in on the canvas", icon_name="zoom_in"))
        self.toolbar_run.addAction(
            self._action("Zoom Out", lambda: self.view.zoom_by(1 / 1.25), "Ctrl+-",
                         "Zoom out of the canvas", icon_name="zoom_out"))
        self.toolbar_run.addSeparator()
        # A visible "?" on the toolbar itself: hiding help inside a menu is
        # half of the "poor documentation" complaint. One QAction shared with
        # the Help menu, so F1 has exactly one owner.
        self.help_action = self._action(
            "&Gestures / Shortcuts", self.show_help, "F1",
            "Open the shortcut, gesture and measurement help overlay",
            icon_name="help")
        self.toolbar_run.addAction(self.help_action)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self._action("&New Schematic", self.new_document,
                                         "Ctrl+N", icon_name="new"))
        file_menu.addAction(self._action("&Open...", self.open_document,
                                         "Ctrl+O", icon_name="open"))
        file_menu.addAction(self._action("&Save", self.save_document,
                                         "Ctrl+S", icon_name="save"))
        file_menu.addAction(self._action("Save &As...", lambda: self.save_document(True)))
        file_menu.addSeparator()
        self.recent_menu = file_menu.addMenu("Open &Recent")
        self.recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        self.recent_menu.setEnabled(False)
        file_menu.addSeparator()
        file_menu.addAction(self._action("&Export SPICE Netlist (.cir)...",
                                         self.export_netlist, icon_name="export"))
        file_menu.addAction(self._action("Export &KiCad Schematic (.kicad_sch)...", self.export_kicad_schematic))
        file_menu.addAction(self._action("Export KiCad &Netlist (.net)...", self.export_kicad_netlist))
        file_menu.addAction(self._action("Export &BOM (.csv)...", self.export_bom))
        file_menu.addSeparator()
        file_menu.addAction(self._action("E&xit", self.close))

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self._action("&Undo", self.scene.undo, "Ctrl+Z",
                                         icon_name="undo"))
        edit_menu.addAction(self._action("&Redo", self.scene.redo, "Ctrl+Y",
                                         icon_name="redo"))
        edit_menu.addAction(self._action("Redo (alternate)", self.scene.redo,
                                         "Ctrl+Shift+Z"))
        edit_menu.addSeparator()
        edit_menu.addAction(self._action("&Delete Selection",
                                         self.scene.delete_selected, "Del",
                                         icon_name="delete"))
        edit_menu.addAction(self._action("R&otate 90°",
                                         self.scene.rotate_selected, "Ctrl+R",
                                         "Rotate the selection 90 degrees",
                                         icon_name="rotate"))
        edit_menu.addAction(self._action("&Edit Value...", self.edit_selected_value,
                                         "Ctrl+E"))
        edit_menu.addAction(self._action("&Label Net...", self.label_selected_net,
                                         "Ctrl+L", icon_name="label"))

        # LTspice/KiCad muscle memory: a bare letter arms that part. These are
        # real QActions rather than keyPressEvent branches, so they fire no
        # matter where the focus happens to be - a dock, the trace list, a
        # button. Only a text box suppresses them, which is what you want while
        # typing in the filter.
        place_menu = self.menuBar().addMenu("&Place")
        self._place_icon_actions = []
        for hotkey, comp_type in PART_HOTKEYS.items():
            act = self._action(
                f"&{label_of(comp_type)}",
                # QAction.triggered emits a bool, and PyQt hands it to a
                # one-argument callable - which would overwrite the default
                # and arm the part as `False`. Swallow it explicitly.
                lambda _checked=False, t=comp_type: self._arm_type(t),
                hotkey,
                f"Arm {label_of(comp_type)} for click-to-place, then click "
                f"the sheet (Esc to stop)",
            )
            act.setIcon(self._symbol_icon(comp_type))
            self._place_icon_actions.append((act, comp_type))
            place_menu.addAction(act)
        place_menu.addSeparator()
        self.cancel_action = self._action(
            "&Cancel", self.cancel_current, "Esc",
            "Un-arm the tool, drop a pending wire and clear the selection",
            icon_name="cancel")
        place_menu.addAction(self.cancel_action)

        sim_menu = self.menuBar().addMenu("&Simulate")
        sim_menu.addAction(run_act)
        sim_menu.addAction(self._action("Run &FFT of selected net", self.run_fft,
                                        "Ctrl+F", icon_name="fft"))
        sim_menu.addAction(self._action("Run &Bode / AC Sweep", self.run_bode,
                                        "Ctrl+B", icon_name="bode"))
        sim_menu.addSeparator()
        sim_menu.addAction(self._action("Run Noise Analysis", self.run_noise_analysis,
                                        "", "Small-signal output noise spectral density",
                                        icon_name="noise"))
        sim_menu.addAction(self._action("Run Distortion Analysis (.disto)", self.run_distortion_analysis,
                                        "", "Harmonic distortion HD2/HD3 vs frequency",
                                        icon_name="disto"))
        sim_menu.addAction(self._action("Run Monte Carlo / Yield", self.run_yield_study,
                                        "", "Tolerance/yield over the user schematic",
                                        icon_name="mc"))
        sim_menu.addAction(self._action("Run Parametric Sweep", self.run_sweep,
                                        "", "Re-solve once per stepped component value",
                                        icon_name="sweep"))
        sim_menu.addAction(self._action("Show Timing Diagram", self.draw_timing_diagram,
                                        "", "Threshold traces into stacked digital lanes",
                                        icon_name="timing"))
        sim_menu.addAction(self._action("Step Response Metrics", self.analyze_step_response,
                                        "", "Delay/rise/settling from measurements.step_metrics",
                                        icon_name="step"))
        sim_menu.addSeparator()
        sim_menu.addAction(self._action("Run Solar PV / MPPT Trace", self.run_pv,
                                        "", "Real PV I-V + P-V from the physical model",
                                        icon_name="pv"))
        sim_menu.addAction(self._action("Generate AWG Waveform", self.run_awg,
                                        "", "Synthesis-only waveform generator",
                                        icon_name="awg"))
        sim_menu.addAction(self._action("Run I-V Curve Tracer", self.run_curve_tracer,
                                        "", "MOSFET/diode DC curve tracer (real .dc)",
                                        icon_name="curve"))
        sim_menu.addAction(self._action("Clear Cursors", self.clear_cursors,
                                        "Ctrl+Shift+K", icon_name="cursors"))
        sim_menu.addSeparator()
        sim_menu.addAction(self._action("Re-&Fit View", self.view.fit_to_contents,
                                        "Ctrl+0", icon_name="fit"))

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self._action("Zoom &In", lambda: self.view.zoom_by(1.25),
                                         "Ctrl+=", icon_name="zoom_in"))
        view_menu.addAction(self._action("Zoom &Out",
                                         lambda: self.view.zoom_by(1 / 1.25),
                                         "Ctrl+-", icon_name="zoom_out"))
        view_menu.addAction(self._action("&Fit to Contents",
                                         self.view.fit_to_contents, "Ctrl+0",
                                         icon_name="fit"))
        view_menu.addSeparator()
        self.grid_action = self._action("Show &Grid", self._toggle_grid, "Ctrl+G",
                                        "Show the schematic dot grid",
                                        icon_name="grid")
        # toggled, not triggered: a checkable action set programmatically
        # (restoring a session, a test) must reach the canvas as well.
        self.grid_action.toggled.connect(self._on_grid_toggled)
        self.grid_action.setCheckable(True)
        self.grid_action.setChecked(True)
        view_menu.addAction(self.grid_action)
        self.ruler_action = self._action("Show &Rulers", self._toggle_rulers,
                                         "Ctrl+Shift+R", "Show the canvas rulers")
        self.ruler_action.toggled.connect(self._on_rulers_toggled)
        self.ruler_action.setCheckable(True)
        self.ruler_action.setChecked(True)
        view_menu.addAction(self.ruler_action)
        view_menu.addSeparator()
        # User-adjustable icon/cursor scale: one fixed size is what LTspice
        # users are stuck with. Radio actions so the current size is visible,
        # not hidden in a preferences dialog.
        scale_menu = view_menu.addMenu("I&con / Cursor Size")
        self._scale_group = QActionGroup(self)
        self._scale_group.setExclusive(True)
        self._scale_actions = {}
        for scale_key in ("small", "medium", "large"):
            scale_act = self._action(
                scale_key.title(),
                lambda _checked=False, k=scale_key: self._set_icon_scale(k),
                None,
                f"{scale_key.title()} toolbar/palette icons and cursor "
                "strokes on the canvas and plot")
            scale_act.setCheckable(True)
            scale_act.setChecked(scale_key == self._icon_scale)
            self._scale_group.addAction(scale_act)
            scale_menu.addAction(scale_act)
            self._scale_actions[scale_key] = scale_act
        view_menu.addSeparator()
        self.theme_action = self._action(
            f"&{theme.current().name.title()} Appearance",
            self._toggle_theme, "Ctrl+T",
            "Switch between the dark and light appearance",
            icon_name="theme")
        view_menu.addAction(self.theme_action)

        results_menu = self.menuBar().addMenu("&Results")
        results_menu.addAction(self._action("Export Results as &CSV...",
                                            self.export_results_csv,
                                            icon_name="table"))
        results_menu.addAction(self._action("Export &Waveform Plot as PNG...",
                                            lambda: self.export_plot_image("waveforms"),
                                            icon_name="image"))
        results_menu.addAction(self._action("Export &FFT Plot as PNG...",
                                            lambda: self.export_plot_image("fft"),
                                            icon_name="image"))
        results_menu.addAction(self._action("Export &Bode Plot as PNG...",
                                            lambda: self.export_plot_image("bode"),
                                            icon_name="image"))
        results_menu.addSeparator()
        results_menu.addAction(self._action("Save Plot as &PDF...",
                                            lambda: self.export_plot_pdf(),
                                            icon_name="pdf"))

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction(self._action("Qualification &Battery...",
                                          self.run_qualification_battery,
                                          None,
                                          "Run the fault-injection and "
                                          "temperature-corner audits",
                                          icon_name="warning"))
        tools_menu.addAction(self._action("Export &Qualification Report...",
                                          self.export_qualification_report,
                                          None,
                                          "Write the DO-254 / ISO 26262 report",
                                          icon_name="pdf"))

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self.help_action)
        help_menu.addAction(self._action("&About WOWKISPICE", self._show_about))

    # ------------------------------------------------------------------
    # Appearance
    # ------------------------------------------------------------------
    def _toggle_theme(self):
        """Switch dark/light and repaint everything that caches a colour."""
        pal = theme.cycle_theme(QApplication.instance())
        icons.clear_cache()
        self._retheme_actions()
        theme.set_symbol_palette(pal)
        self.scene.update()
        self.view.viewport().update()
        self._restyle_plots()
        self._refresh_palette_icons()
        self.palette_hint.setStyleSheet(f"color: {pal.dim};")
        for label in (self.measure_label,):
            label.setStyleSheet(f"font-family: Consolas, monospace; color: {pal.text};")
        self.theme_action.setText(f"&{pal.name.title()} Appearance")
        self.log(f"Appearance: {pal.name}")
        self._save_session()

    def _restyle_plots(self):
        pal = theme.current()
        pg.setConfigOption("background", pal.plot_bg)
        pg.setConfigOption("foreground", pal.text)
        for plot in (self.plot, self.fft_plot, self.bode_plot, self.bode_phase):
            plot.setBackground(pal.plot_bg)
            plot.showGrid(x=True, y=True, alpha=0.35)
            for axis_name in ("bottom", "left"):
                axis = plot.getAxis(axis_name)
                axis.setPen(pg.mkPen(pal.plot_axis, width=2))
                axis.setTextPen(pg.mkPen(pal.plot_label))
                axis.setStyle(tickFont=theme.mono_font(8))
            for child in plot.getViewBox().children():
                if hasattr(child, "setDefaultTextPen"):
                    child.setDefaultTextPen(pg.mkPen(pal.plot_label))
        self.plot.getViewBox().update()

    def _refresh_palette_icons(self):
        for row in range(self.palette_list.count()):
            item = self.palette_list.item(row)
            comp_type = item.data(Qt.UserRole)
            if comp_type is not None:
                item.setIcon(self._symbol_icon(comp_type))
        header_font = self.palette_list.item(0)
        if header_font is not None:
            header_font.setForeground(QBrush(QColor(theme.current().dim)))
        for act, comp_type in getattr(self, "_place_icon_actions", []):
            act.setIcon(self._symbol_icon(comp_type))

    def _apply_icon_scale(self):
        """Resize every clickable icon surface and both cursor strokes.

        One table (ICON_SCALES) drives the toolbar buttons, the palette rows
        and their symbol renders, the Place-menu icons, the canvas crosshair
        and the plot's cursor lines - so "too big to place accurately" and
        "too small to hit" are both reachable from one setting, and chrome can
        never drift out of proportion with the canvas.
        """
        spec = ICON_SCALES.get(self._icon_scale, ICON_SCALES["medium"])
        self.toolbar_run.setIconSize(QSize(spec["toolbar"], spec["toolbar"]))
        self.palette_list.setIconSize(QSize(spec["palette"], spec["palette"]))
        for row in range(self.palette_list.count()):
            item = self.palette_list.item(row)
            comp_type = item.data(Qt.UserRole)
            if comp_type is None:
                item.setSizeHint(QSize(0, 20))       # group header, unchanged
            else:
                item.setSizeHint(QSize(0, spec["row"]))
                item.setIcon(self._symbol_icon(comp_type))
        for act, comp_type in getattr(self, "_place_icon_actions", []):
            act.setIcon(self._symbol_icon(comp_type))
        self.view.cursor_width = spec["cursor"]
        self.view.viewport().update()
        for key, act in getattr(self, "_scale_actions", {}).items():
            act.setChecked(key == self._icon_scale)
        # The plot cursor lines carry the same stroke width; rebuilding them
        # is safe before any run (it just re-reads the empty cursor list).
        self.refresh_cursors()

    def _set_icon_scale(self, key):
        """View > Icon / Cursor Size: apply, persist, leave a trace."""
        if key not in ICON_SCALES:
            return
        self._icon_scale = key
        self._apply_icon_scale()
        self._save_session()
        self.log(f"Icon/cursor scale: {key}")

    def _toggle_grid(self):
        self._on_grid_toggled(self.grid_action.isChecked())

    def _on_grid_toggled(self, on):
        self.scene.grid_visible = bool(on)
        self.scene.update()
        self.log(f"Grid {'shown' if self.scene.grid_visible else 'hidden'}")

    def _toggle_rulers(self):
        self._on_rulers_toggled(self.ruler_action.isChecked())

    def _on_rulers_toggled(self, on):
        size = SchematicView.RULER if on else 0
        self.view.setViewportMargins(size, size, 0, 0)
        self.view.viewport().update()
        self.log(f"Rulers {'shown' if on else 'hidden'}")

    # ------------------------------------------------------------------
    # Qualification battery
    #
    # This used to live in ui/studio_app.py, which is being retired. The engine
    # underneath is bridge.industrial_verification, which has its own tests, so
    # it keeps an entry point here rather than being orphaned.
    # ------------------------------------------------------------------
    def run_qualification_battery(self):
        from bridge.industrial_verification import IndustrialVerificationEngine

        dialog = QDialog(self)
        dialog.setWindowTitle("Qualification battery")
        dialog.resize(940, 620)
        layout = QVBoxLayout(dialog)

        status = QLabel("Running... this solves the reference stage at every corner.")
        status.setWordWrap(True)
        layout.addWidget(status)

        fault_box = QTreeWidget()
        fault_box.setHeaderLabels(["ID", "Fault", "Injection", "Simulated outcome",
                                   "ASIL"])
        layout.addWidget(QLabel("Fault injection"))
        layout.addWidget(fault_box)

        corner_box = QTreeWidget()
        corner_box.setHeaderLabels(["Temp", "Vout", "Efficiency", "Ripple",
                                    "Tj", "Status"])
        layout.addWidget(QLabel("Temperature corners"))
        layout.addWidget(corner_box)

        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)

        def work():
            verifier = IndustrialVerificationEngine()
            return (verifier.run_fault_injection_battery(),
                    verifier.run_temperature_corners_sweep(),
                    verifier)

        result, error = self._run_in_worker(work)
        if error:
            status.setText(f"Qualification battery failed: {error}")
            self.log("Qualification battery failed: " + error)
            dialog.exec_()
            return

        faults, sweep, verifier = result
        self._qualification_verifier = verifier
        for fault in faults:
            fault_box.addTopLevelItem(QTreeWidgetItem([
                str(fault.get("fault_id", "")),
                str(fault.get("fault_name", "")),
                str(fault.get("injection_type", "")),
                str(fault.get("simulated_outcome", "")),
                str(fault.get("asul_rating", ""))]))
        for corner in sweep.get("corners", []):
            corner_box.addTopLevelItem(QTreeWidgetItem([
                f"{corner['temp_c']:+.1f} C",
                f"{corner['vout_v']:.4f} V",
                f"{corner['efficiency_pct']:.1f} %",
                f"{corner['ripple_mv']:.1f} mV",
                f"{corner['tj_junction_c']:.1f} C",
                str(corner.get("status", ""))]))
        status.setText(f"{len(faults)} faults injected, "
                       f"{len(sweep.get('corners', []))} corners evaluated.")
        self.log(f"Qualification battery: {len(faults)} faults, "
                 f"{len(sweep.get('corners', []))} corners.")
        dialog.exec_()

    def export_qualification_report(self):
        from bridge.industrial_verification import IndustrialVerificationEngine

        verifier = getattr(self, "_qualification_verifier", None)
        if verifier is None:
            verifier = IndustrialVerificationEngine()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Qualification Report",
            getattr(self, "_last_dir", "") or "qualification.html",
            "HTML report (*.html)")
        if not path:
            return
        written, error = self._run_in_worker(
            lambda: verifier.generate_qualification_report(path))
        if error:
            message = "Qualification report failed: " + error
            self.log(message)
            self.statusBar().showMessage(message)
            return
        self.log(f"Qualification report -> {written}")

    def _show_about(self):
        QMessageBox.about(
            self, "About WOWKISPICE",
            "<h3>WOWKISPICE</h3>"
            "<p>Mixed-signal co-simulation workbench: schematic capture, a real "
            "ngspice solver, and MCU firmware behaviour imported from source.</p>"
            "<p>The schematic is compiled to a SPICE netlist and solved by "
            "libngspice. Firmware is imported from its own source, not executed "
            "in an emulator.</p>")

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------
    def _settings(self):
        return theme.settings()

    def _load_session(self):
        """Restore chrome, not experiment settings.

        Window geometry, dock layout, grid/ruler visibility, the recent list and
        the appearance are remembered. Vin, timestep, duration, accuracy and the
        simulation mode are deliberately *not*: a result has to be reproducible
        from what is on screen, and inheriting a different mode or timestep from
        a previous session is indistinguishable from a bug. It also means one
        window can never silently change what the next one computes.
        """
        s = self._settings()
        s.beginGroup("session")
        geometry = s.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = s.value("state")
        if state is not None:
            self.restoreState(state)
        self._last_dir = s.value("last_dir", "", str)
        recent = s.value("recent", [], list)
        self._recent = [p for p in recent if os.path.exists(p)]
        s.endGroup()
        s.beginGroup("view")
        grid = s.value("grid", True, bool)
        rulers = s.value("rulers", True, bool)
        icon_scale = s.value("icon_scale", "medium", str)
        s.endGroup()
        self._icon_scale = (icon_scale if icon_scale in ICON_SCALES
                            else "medium")
        self.scene.grid_visible = grid
        if hasattr(self, "grid_action"):
            self.grid_action.setChecked(grid)
        if hasattr(self, "ruler_action"):
            self.ruler_action.setChecked(rulers)
        if not rulers:
            self.view.setViewportMargins(0, 0, 0, 0)
        self._apply_icon_scale()
        self._restyle_plots()
        if self._recent:
            self.recent_menu.setEnabled(True)
        if self._recent:
            self.log(f"Last session: {len(self._recent)} recent document(s)")

    def _save_session(self):
        s = self._settings()
        s.beginGroup("session")
        s.setValue("geometry", self.saveGeometry())
        s.setValue("state", self.saveState())
        s.setValue("last_dir", getattr(self, "_last_dir", ""))
        s.setValue("recent", getattr(self, "_recent", []))
        s.endGroup()
        s.beginGroup("view")
        s.setValue("grid", self.scene.grid_visible)
        s.setValue("rulers", self.ruler_action.isChecked()
                   if hasattr(self, "ruler_action") else True)
        s.setValue("icon_scale", getattr(self, "_icon_scale", "medium"))
        s.endGroup()
        s.sync()

    def _remember_recent(self, path):
        if not path:
            return
        recent = [p for p in getattr(self, "_recent", []) if p != path]
        recent.insert(0, path)
        self._recent = recent[:8]
        self.recent_menu.setEnabled(True)

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        for path in getattr(self, "_recent", []):
            action = self.recent_menu.addAction(os.path.basename(path))
            action.setStatusTip(path)
            action.triggered.connect(lambda _checked=False, p=path: self._open_path(p))

    def closeEvent(self, event):
        self._save_session()
        super().closeEvent(event)

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
        self._arm_type(self._palette_types[rows.index(row)] if row in rows else None)

    def _arm_type(self, comp_type):
        """Arm a part for click-to-place. One entry point, so a palette click
        and a letter key cannot drift apart."""
        self.scene.set_armed(comp_type)
        self.view.setCursor(Qt.CrossCursor if comp_type else Qt.ArrowCursor)
        self._sync_palette_row(comp_type)
        # Keyboard-only users never touch the canvas, so hand it the focus.
        self.view.setFocus()
        if comp_type:
            self.statusBar().showMessage(
                f"Placing {label_of(comp_type)} - click the canvas (Esc to stop)")

    def cancel_current(self):
        """Esc. Un-arm the tool, drop a pending wire, drop the selection.

        Goes through scene.set_armed(None) rather than poking armed_type: the
        setter is what removes the ghost item, so assigning the attribute
        leaves the preview drawn on the canvas forever.
        """
        had_tool = self.scene.armed_type is not None
        self.scene.cancel_wire()
        self.scene.set_armed(None)
        self.scene.clearSelection()
        self.view.setCursor(Qt.ArrowCursor)
        self._sync_palette_row(None)
        self.view.setFocus()
        self.statusBar().showMessage(
            "Cancelled - nothing armed" if not had_tool else "Cancelled",
            2500)

    def _sync_palette_row(self, comp_type):
        """Mirror the armed part back into the palette, without re-entering
        _on_palette_selected (blockSignals: setCurrentRow would call us back)."""
        target = -1
        if comp_type is not None:
            for i, row in enumerate(self._component_rows()):
                if i < len(self._palette_types) and self._palette_types[i] == comp_type:
                    target = row
                    break
        if target == self.palette_list.currentRow():
            return
        self.palette_list.blockSignals(True)
        self.palette_list.setCurrentRow(target)
        self.palette_list.blockSignals(False)

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
            "Which net is the ADC pin wired to?\n"
            "Pick the divider output the pin actually sees, not the raw output\n"
            "node - the firmware's thresholds are already pin-referenced counts.",
            nets, 0, False)
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
        # Divider sanity check. The firmware's counts are pin-referenced, so if
        # the chosen sense net is the undivided output node the loop regulates
        # to half the intended voltage. This cannot detect that automatically:
        # the implied voltages come from the firmware's own constants, not from
        # the schematic, so nothing here can see the netlist's divider. What it
        # CAN do is state the number the pin must sit at, which is enough for a
        # reader to spot a net that is running at roughly twice that.
        try:
            pin_lo, pin_hi = control_law.implied_pin_voltages(spec)
        except control_law.ControlLawError as exc:
            self.log(f"  could not derive the sense voltages: {exc}")
            return
        self.log(f"  {sense_net} must sit at {pin_lo:.4f}..{pin_hi:.4f} V for "
                 f"{comp.name} to switch. If this net is the undivided output "
                 f"rather than the divider output, it will run at about twice "
                 f"that and the loop will regulate to half the intended voltage.")

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
        self._current_path = None
        self._dirty = False
        self.log("New schematic.")
        self._update_title()

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
        self._dirty = False
        self._remember_recent(path)
        self._last_dir = os.path.dirname(os.path.abspath(path))
        self.statusBar().showMessage(f"Saved {path}")
        self.log(f"Saved schematic -> {path}")
        self._update_title()

    def open_document(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Schematic", getattr(self, "_last_dir", ""),
            "Schematic (*.wsk *.json)")
        if not path:
            return
        self._open_path(path)

    def _open_path(self, path):
        """Load a document by path. Split out of open_document so the recent
        files menu can reuse it without going through the file dialog."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError) as exc:
            # Reported in the console rather than a modal box: a recent-file
            # entry that no longer opens must not block the window, and a
            # modal here is unreachable in a headless run.
            message = f"Cannot open {path}: {exc}"
            self._recent = [p for p in getattr(self, "_recent", []) if p != path]
            self.statusBar().showMessage(message)
            self.log(message)
            return
        self.model.load_dict(payload)
        self.scene.rebuild()
        self._current_path = path
        self._dirty = False
        self._remember_recent(path)
        self._last_dir = os.path.dirname(os.path.abspath(path))
        self.log(f"Opened {path}")
        self._update_title()

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
        total = max(len(v) for v in traces.values())
        times_s = [i * dt for i in range(total)]
        self._last_time = times_s
        self._last_traces = traces
        self._sync_trace_list()
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
        self.plot.addLegend()
        self._curves = []          # the list was never reset, so curves from
        self._click_points = []    # an earlier run stayed selectable
        self._click_points_view = []
        self._measured_trace = None
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
        self._sync_trace_list()
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

        def on_click(plot, points, evt=None):
            if not points:
                return
            view = plot.getViewBox()
            x = view.mapSceneToView(points[0]).x()
            # The plot x-axis is milliseconds (every run plots t * 1000),
            # while _last_time and the readout are in seconds. Storing the
            # raw plot x fed a millisecond value into second-based arrays,
            # where sample_at() clamped it past the end of the data and the
            # readout always reported the final sample - the cursor looked
            # like it was reporting the mouse, not the trace. cursor_x() is
            # documented as data coordinates, so convert here.
            self._click_points.append(x / 1000.0)
            if len(self._click_points) > 2:
                self._click_points = self._click_points[-2:]
            # Remember where the click landed in pixels too: deciding which
            # trace is under the cursor needs the y, which the x-only list
            # above cannot answer.
            if evt is not None:
                self._click_points_view = [
                    _view_point(evt), *(getattr(self, "_click_points_view", [])[1:])]
            else:
                self._click_points_view = [None, *getattr(self, "_click_points_view", [])[1:]]
            self._measured_trace = None
            self.refresh_cursors()

        self.plot.scene().sigMouseClicked.connect(on_click)

    def clear_cursors(self):
        self._click_points = []
        self._click_points_view = []
        self._measured_trace = None
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
        net, curve = self._trace_at_cursor()
        values = getattr(self, "_last_traces", {}).get(net)
        if not values:
            self.measure_label.setText(
                "cursor is not on a plotted trace - click a row in the trace list")
            return {}
        readout = measurements.cursor_readout(times, values, xs[0])
        if len(xs) > 1:
            readout = measurements.cursor_readout(times, values, xs[0], None, xs[1])
        stats = measurements.trace_stats(times, values)
        self._update_trace_values()
        text = f"{net}: " + measurements.format_readout(readout)
        text += (f"   |  min {stats['min']:.3f} V  max {stats['max']:.3f} V"
                 f"  rms {stats['rms']:.3f} V  p-p {stats['p2p']:.3f} V")
        self.measure_label.setText(text)
        return readout

    def cursor_x(self):
        """Cursor positions in data coordinates."""
        return [float(x) for x in getattr(self, "_click_points", [])]

    def _on_cursor_dragged(self, line):
        """Dragging a cursor line moves it; keep the data-space list in step,
        or the ruler keeps reporting the position the cursor was dropped at."""
        value = line.value()
        positions = list(getattr(self, "_click_points", []))
        # InfiniteLine lives on the plot's millisecond axis; the readout
        # consumes seconds (see the conversion in _install_cursor_clicks).
        positions.append(float(value) / 1000.0)
        positions = sorted(positions)[-2:]
        self._click_points = positions
        self._click_points_view = [None] * len(positions)
        self._measured_trace = None
        self.cursor_readout()

    def _trace_at_cursor(self, max_px=14):
        """
        Which plotted trace sits under cursor A.

        pyqtgraph offers no "what is under this pixel" query, so this measures
        it: for each curve take the sample nearest the cursor in x, map that
        value back to a pixel row, and keep the closest one within max_px. The
        previous implementation named the first legend entry regardless of
        where the cursor was, which is how the readout ended up describing a
        trace you were not pointing at.
        """
        if not getattr(self, "_curves", None):
            return "", None
        chosen = getattr(self, "_measured_trace", None)
        if chosen:
            for curve in self._curves:
                if (curve.name() or "") == chosen:
                    return chosen, curve

        points = [p for p in getattr(self, "_click_points_view", None) or []
                  if p is not None]
        if not points:
            # Cursors can be set without a pointer position - dragged with the
            # mouse, or placed by code - and then there is nothing to hit-test
            # against. Fall back to the first *visible* trace rather than
            # inventing one, and the readout names whichever it picked.
            for curve in self._curves:
                if curve.isVisible():
                    return (curve.name() or ""), curve
            return "", None
        view = self.plot.getViewBox()
        scene_pt = points[0]
        data_pt = view.mapSceneToView(scene_pt)
        best_curve, best_gap = None, max_px
        for curve in self._curves:
            data = curve.getData()
            if not data or data[0] is None or len(data[0]) == 0:
                continue
            xs = data[0]
            index = _nearest_index(xs, data_pt.x())
            if index is None:
                continue
            gap = abs(view.mapViewToScene(data_pt).y()
                      - view.mapViewToScene(_point_at(curve, index)).y())
            if gap <= best_gap:
                best_gap, best_curve = gap, curve
        if best_curve is None:
            return "", None
        return (best_curve.name() or ""), best_curve

    def _on_trace_row_clicked(self, item, column):
        """Clicking a trace row makes it the measured one."""
        net = item.data(0, Qt.UserRole)
        if net:
            self._measured_trace = net
            self.refresh_cursors()

    def _on_trace_row_changed(self, item, column):
        net = item.data(0, Qt.UserRole)
        if not net:
            return
        visible = item.checkState(0) == Qt.Checked
        for curve in getattr(self, "_curves", []):
            if (curve.name() or "") == net:
                curve.setVisible(visible)
        self.cursor_readout()

    def _rebuild_trace_list(self, nets, samples=None):
        _curve_named._owner = getattr(self, "_curves", [])
        self.trace_list.blockSignals(True)
        self.trace_list.clear()
        for net in nets:
            text = samples.get(net, "") if samples else ""
            item = QTreeWidgetItem([net, text])
            item.setData(0, Qt.UserRole, net)
            item.setCheckState(0, Qt.Checked)
            colour = None
            for curve in getattr(self, "_curves", []):
                if (curve.name() or "") == net:
                    pen = curve.opts.get("pen")
                    colour = pen.color().name() if pen is not None else None
                    break
            if colour:
                item.setForeground(0, QBrush(QColor(colour)))
            self.trace_list.addTopLevelItem(item)
        self.trace_list.blockSignals(False)

    def _sync_trace_list(self):
        """Build one row per plotted trace. Called after every run, so the list
        is populated whether or not cursors exist yet."""
        self._rebuild_trace_list(
            [c.name() or "" for c in getattr(self, "_curves", [])])
        self._update_trace_values()

    def _update_trace_values(self):
        """Refresh only the value column, for cursor A."""
        points = [p for p in getattr(self, "_click_points_view", None) or []
                  if p is not None]
        for i in range(self.trace_list.topLevelItemCount()):
            item = self.trace_list.topLevelItem(i)
            name = item.data(0, Qt.UserRole)
            value = ""
            curve = _curve_named(name) if name else None
            if points and curve is not None:
                view = self.plot.getViewBox()
                sample = _value_at(curve, view.mapSceneToView(points[0]).x())
                if sample is not None:
                    value = f"{sample:.4g} V"
            item.setText(1, value)

    def refresh_cursors(self):
        """Redraw the cursor lines; called after a new run."""
        for line in list(getattr(self, "_cursor_lines", [])):
            self.plot.removeItem(line)
        self._cursor_lines = []
        for x in sorted(self.cursor_x()):
            # x is data time in seconds; the plot axis is milliseconds.
            width = ICON_SCALES.get(self._icon_scale,
                                    ICON_SCALES["medium"])["cursor"]
            line = pg.InfiniteLine(pos=x * 1000.0, angle=90, movable=True,
                                   pen=pg.mkPen(theme.current().plot_axis,
                                                width=width, style=Qt.DashLine))
            line.sigDragged.connect(self._on_cursor_dragged)
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
    # Serial / UART decode
    # ------------------------------------------------------------------
    def _sync_serial_nets(self):
        """Wire the traces from the last run into the Serial tab's net picker.

        Any scalar trace can be treated as a UART TX candidate for decode; the
        Serial tab lets the user pick which net to decode.
        """
        traces = getattr(self, "_last_traces", {})
        nets = sorted(traces.keys())
        self.serial_net_box.clear()
        if nets:
            self.serial_net_box.addItems(nets)
            if self.serial_net_box.findText(self.serial_net_box.currentText()) < 0:
                self.serial_net_box.setCurrentIndex(0)
        else:
            self.serial_net_box.addItem("")
            self.serial_net_box.setCurrentIndex(0)

    def decode_uart_from_net(self):
        """UART 8N1 decode of the selected trace through studio_engine."""
        from bridge.studio_engine import StudioSimulationEngine

        traces = getattr(self, "_last_traces", {})
        if not traces:
            QMessageBox.information(self, "UART decode",
                                    "Run a transient simulation first (F2).")
            return
        net = self.serial_net_box.currentText().strip()
        if not net or net not in traces:
            QMessageBox.information(self, "UART decode",
                                    "Select a decoded net on the Serial tab.")
            return
        values = traces[net]
        if len(values) < 20:
            QMessageBox.information(self, "UART decode",
                                    f"Trace '{net}' is too short to decode.")
            return
        try:
            import numpy as np
            v = np.asarray(values, dtype=float)
            v = np.asarray(values, dtype=float)
            lo = float(v.min())
            hi = float(v.max())
            span = (hi - lo) if hi > lo else 0.0
            if span < 1.0:
                self.serial_status.setText("no valid 8n1 frames")
                self.serial_view.setPlainText("")
                return
            t = getattr(self, "_last_time", None)
            if t is None or len(t) != len(values):
                t = list(range(len(values)))
            logic = (v > 1.65).astype(np.int8)
            time_ms = (np.asarray(t, dtype=float) * 1000.0).tolist()
            packets = StudioSimulationEngine.decode_uart_packets(
                logic, time_ms,
                baud_rate=int(self.serial_baud_box.value()))
        except Exception as exc:
            QMessageBox.warning(self, "UART decode failed", str(exc))
            self.log(f"UART decode failed: {exc}")
            return

        real = packets
        if not real:
            self.serial_status.setText("no valid 8n1 frames")
            self.serial_view.setPlainText("")
            return

        lines = []
        for p in real:
            ascii_repr = repr(p.get("ascii", "?"))
            line = (f"{p.get('timestamp_ms', 0):.3f} ms  "
                    f"{p.get('type', '?'):10s}  "
                    f"{p.get('hex', '?'):>7s}  "
                    f"{ascii_repr}"
                    + (f"  ({p.get('parity', '')})" if p.get('parity') else ""))
            lines.append(line)
        status = f"Decoded {len(real)} frame" + ("s" if len(real) != 1 else "")
        self.serial_status.setText(status)
        self.serial_view.setPlainText("\n".join(lines))
        self.log(f"UART decode of {net}: {status}")

    # ------------------------------------------------------------------
    # Timing / step / noise / distortion / monte carlo / sweep
    # ------------------------------------------------------------------
    def draw_timing_diagram(self):
        """Threshold the last traces into stacked digital lanes."""
        from bridge.gpio_model import DEFAULT_THRESHOLD

        traces = getattr(self, "_last_traces", {})
        times = getattr(self, "_last_time", None)
        if not traces or not times or len(times) < 2:
            QMessageBox.information(self, "Timing diagram",
                                    "Run a transient simulation first (F2).")
            return
        self.results_tabs.setCurrentWidget(self.timing_panel)
        self.timing_lanes = []
        self.timing_plot.clear()
        threshold = DEFAULT_THRESHOLD
        colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd",
                  "#ff7f0e", "#8c564b", "#17becf", "#e377c2"]
        for i, (name, values) in enumerate(traces.items()):
            if len(values) != len(times):
                continue
            digital = [1.0 if v > threshold else 0.0 for v in values]
            t_ms = [t * 1000.0 for t in times]
            pen = pg.mkPen(colors[i % len(colors)], width=2)
            self.timing_plot.plot(t_ms, digital, pen=pen, name=name)
            indices = [j for j in range(1, len(digital))
                       if digital[j] != digital[j - 1]]
            edges = len(indices)
            ones = sum(1 for b in digital if b > 0.5)
            total = len(digital)
            duty = 100.0 * ones / total if total else 0.0
            if edges >= 2:
                # frequency from average period between rising edges
                rises = [j for j in indices if digital[j] > 0.5]
                if len(rises) >= 2:
                    periods = [t_ms[rises[k + 1]] - t_ms[rises[k]]
                               for k in range(len(rises) - 1)]
                    avg_period = sum(periods) / len(periods)
                    freq_hz = (1000.0 / avg_period) if avg_period > 0 else 0.0
                else:
                    freq_hz = 0.0
            else:
                freq_hz = 0.0
            lane = (f"{name}  -  {edges} edges, {duty:.0f}% duty, "
                    f"{freq_hz:.0f} Hz" if freq_hz else
                    f"{name}  -  0 edges, {duty:.0f}% duty")
            self.timing_lanes.append(lane)
        self.timing_plot.setTitle(
            f"Timing diagram - {len(self.timing_lanes)} lane(s)")
        self.timing_info.setText(" | ".join(self.timing_lanes))
        self.log("Timing diagram: " + " | ".join(self.timing_lanes))

    def analyze_step_response(self):
        """Step response metrics on the picked net via measurements.step_metrics."""
        from bridge import measurements

        traces = getattr(self, "_last_traces", {})
        times = getattr(self, "_last_time", None)
        if not times or not traces:
            QMessageBox.information(self, "Step response",
                                    "Run a transient simulation first (F2).")
            return
        net = self.step_net_box.currentText().strip()
        if not net or net not in traces:
            QMessageBox.information(self, "Step response",
                                    "Select an output net on the Step Response tab.")
            return
        values = traces[net]
        if len(values) != len(times):
            QMessageBox.information(self, "Step response",
                                    f"Trace '{net}' is incomplete.")
            return
        self.step_last = measurements.step_metrics(times, values)
        t_ms = [t * 1000.0 for t in times]
        self.step_plot.clear()
        self.step_plot.plot(t_ms, values, pen=pg.mkPen("#1f77b4", width=2),
                            name=net)
        if self.step_last.get("delay_s") is not None:
            self.step_plot.plot([self.step_last["delay_s"] * 1000.0] * 2,
                                [min(values), max(values)],
                                pen=pg.mkPen("#d62728", width=2, style=Qt.DashLine),
                                name="delay")
        if self.step_last.get("rise_s") is not None and self.step_last.get("delay_s") is not None:
            rise_start = self.step_last["delay_s"]
            rise_end = rise_start + self.step_last["rise_s"]
            self.step_plot.plot([rise_start * 1000.0, rise_end * 1000.0],
                                [min(values), max(values)],
                                pen=pg.mkPen("#2ca02c", width=2, style=Qt.DashLine),
                                name="rise")
        self.step_plot.setTitle(f"Step response - {net}")
        bits = [f"{net}", f"step {self.step_last.get('step_v', 0):.3f} V"]
        if self.step_last.get("delay_s") is not None:
            bits.append(f"delay {self.step_last['delay_s']*1000:.3f} ms")
        if self.step_last.get("rise_s") is not None:
            bits.append(f"rise {self.step_last['rise_s']*1000:.3f} ms")
        if self.step_last.get("settling_s") is not None:
            bits.append(f"settling {self.step_last['settling_s']*1000:.3f} ms")
        bits.append(f"overshoot {self.step_last.get('overshoot_pct', 0):.2f}%")
        self.step_info.setText("   ".join(bits))
        self.log("Step response: " + "   ".join(bits))

    def run_noise_analysis(self):
        """Small-signal output noise spectral density via analysis_runner.run_noise."""
        from bridge import analysis_runner

        if not getattr(self, "_last_time", None):
            QMessageBox.information(self, "Noise analysis",
                                    "Run a transient simulation first (F2) to set up the schematic.")
            return
        net = self.noise_net_box.currentText().strip()
        if not net:
            _lines, nets, _w = self.model.compile_netlist()
            if not nets:
                QMessageBox.information(self, "Noise analysis",
                                        "This schematic has no nets.")
                return
            self.noise_net_box.addItems(nets)
            net = nets[0]
        start = self.noise_start_box.value()
        stop = self.noise_stop_box.value()
        if stop <= start:
            QMessageBox.warning(self, "Noise analysis",
                                "Stop frequency must exceed start.")
            return
        try:
            out = analysis_runner.run_noise(
                self.model, net,
                start_hz=start, stop_hz=stop,
                points_per_decade=int(self.noise_pts_box.value()))
        except analysis_runner.AnalysisError as exc:
            QMessageBox.warning(self, "Noise analysis failed", str(exc))
            self.log(f"Noise analysis failed: {exc}")
            return
        self.noise_last = out
        self.noise_plot.clear()
        self.noise_plot.plot(out["freqs"], out["onoise_density"],
                             pen=pg.mkPen("#1f77b4", width=2), name="output")
        if out.get("inoise_density"):
            self.noise_plot.plot(out["freqs"], out["inoise_density"],
                                 pen=pg.mkPen("#d62728", width=2),
                                 name="input")
        self.noise_plot.setTitle(f"Noise - {net}")
        self.noise_plot.setLogMode(x=True)
        total = out.get("total_output")
        info = (f"{net}: DC density {out['onoise_density'][0]*1e9:.2f} nV/sqrt(Hz), "
                f"integrated {total*1e6:.3f} uV" if total is not None else
                f"{net}: DC density {out['onoise_density'][0]*1e9:.2f} nV/sqrt(Hz)")
        self.noise_info.setText(info)
        self.log(f"Noise analysis of {net}: {info}")
        if self.bode_net_box.findText(net) < 0:
            self.bode_net_box.addItem(net)
        self._sync_serial_nets()

    def run_distortion_analysis(self):
        """Harmonic distortion (.disto) via analysis_runner.run_disto."""
        from bridge import analysis_runner

        if not getattr(self, "_last_time", None):
            QMessageBox.information(self, "Distortion analysis",
                                    "Run a transient simulation first (F2) to set up the schematic.")
            return
        net = self.disto_net_box.currentText().strip()
        if not net:
            _lines, nets, _w = self.model.compile_netlist()
            if not nets:
                QMessageBox.information(self, "Distortion analysis",
                                        "This schematic has no nets.")
                return
            self.disto_net_box.addItems(nets)
            net = nets[0]
        start = self.disto_start_box.value()
        stop = self.disto_stop_box.value()
        if stop <= start:
            QMessageBox.warning(self, "Distortion analysis",
                                "Stop frequency must exceed start.")
            return
        try:
            out = analysis_runner.run_disto(
                self.model, net,
                start_hz=start, stop_hz=stop,
                points_per_decade=int(self.disto_pts_box.value()))
        except analysis_runner.AnalysisError as exc:
            QMessageBox.warning(self, "Distortion analysis failed", str(exc))
            self.log(f"Distortion analysis failed: {exc}")
            return
        self.disto_last = out
        self.disto_plot.clear()
        self.disto_plot.plot(out["freqs"], out["hd2"],
                             pen=pg.mkPen("#1f77b4", width=2), name="HD2")
        self.disto_plot.plot(out["freqs"], out["hd3"],
                             pen=pg.mkPen("#d62728", width=2), name="HD3")
        self.disto_plot.setTitle(f"Distortion - {net}")
        self.disto_plot.setLogMode(x=True)
        self.disto_info.setText(
            f"{net}: HD2 {out['hd2'][0]:.2f} dBc, HD3 {out['hd3'][0]:.2f} dBc")
        self.log(f"Distortion analysis of {net}: "
                 f"HD2 {out['hd2'][0]:.2f} dBc, HD3 {out['hd3'][0]:.2f} dBc")
        if self.bode_net_box.findText(net) < 0:
            self.bode_net_box.addItem(net)
        self._sync_serial_nets()

    def run_yield_study(self):
        """Monte Carlo / yield on the user schematic via analysis_runner.run_monte_carlo."""
        from bridge import analysis_runner

        if not getattr(self, "_last_time", None):
            QMessageBox.information(self, "Monte Carlo",
                                    "Run a transient simulation first (F2) to set up the schematic.")
            return
        net = self.mc_net_box.currentText().strip()
        if not net:
            _lines, nets, _w = self.model.compile_netlist()
            if not nets:
                QMessageBox.information(self, "Monte Carlo",
                                        "This schematic has no nets.")
                return
            self.mc_net_box.addItems(nets)
            net = nets[0]
        iterations = int(self.mc_iters_box.value())
        try:
            out = analysis_runner.run_monte_carlo(
                self.model, net,
                iterations=iterations,
                tol_pct=self.mc_tol_box.value(),
                yield_pct=self.mc_yield_box.value())
        except analysis_runner.AnalysisError as exc:
            QMessageBox.warning(self, "Monte Carlo failed", str(exc))
            self.log(f"Monte Carlo failed: {exc}")
            return
        self.mc_last = out
        self.mc_plot.clear()
        self.mc_bars = None
        if out["samples"]:
            import numpy as np
            h, edges = np.histogram(out["samples"], bins=10)
            centers = [(edges[i] + edges[i + 1]) / 2.0 for i in range(len(h))]
            self.mc_bars = pg.BarGraphItem(x=centers, height=h.tolist(),
                                            width=0.9,
                                            pen=pg.mkPen("#1f77b4", width=1),
                                            brush=pg.mkBrush("#1f77b4"))
            self.mc_plot.addItem(self.mc_bars)
            self.mc_plot.setLabel("bottom", "Settled value", units="V")
            self.mc_plot.setLabel("left", "Samples")
            self.mc_plot.setTitle(f"Monte Carlo - {net} ({out['iterations']} runs)")
        info = (f"{net}: {out['iterations']} runs, nominal {out['nominal']:.4f} V, "
                f"std {out['std']:.4f} V, yield {out['yield_actual_pct']:.1f}%")
        self.mc_info.setText(info)
        self.log(f"Monte Carlo on {net}: {info}")
        if self.bode_net_box.findText(net) < 0:
            self.bode_net_box.addItem(net)
        self._sync_serial_nets()

    def refresh_sweep_controls(self):
        """Populate the sweepable-component picker from the current schematic."""
        self.sweep_comp_box.clear()
        for comp in self.model.components.values():
            ctype = (comp.comp_type or "").upper()
            if ctype not in ("R", "C", "L"):
                continue
            try:
                from bridge.analysis_runner import spice_value
                spice_value(comp.value)
            except (TypeError, ValueError):
                continue
            idx = self.sweep_comp_box.count()
            self.sweep_comp_box.addItem(comp.name or comp.comp_id)
            self.sweep_comp_box.setItemData(idx, comp.comp_id)
        _lines, nets, _w = self.model.compile_netlist()
        self.sweep_net_box.clear()
        if nets:
            self.sweep_net_box.addItems(nets)

    def run_sweep(self):
        """Parametric sweep: re-solve once per stepped component value, overlay."""
        from bridge.ngspice_wrapper import NgSpiceEngine
        from bridge.analysis_runner import spice_value

        if not getattr(self, "_last_time", None):
            QMessageBox.information(self, "Parametric sweep",
                                    "Run a transient simulation first (F2) to set up the schematic.")
            return
        comp_id = self.sweep_comp_box.currentData()
        if not comp_id:
            QMessageBox.information(self, "Parametric sweep",
                                    "Select a sweepable component (R/C/L) first.")
            return
        comp = self.model.components.get(comp_id)
        if comp is None:
            QMessageBox.information(self, "Parametric sweep",
                                    f"Component {comp_id} not found.")
            return
        net = self.sweep_net_box.currentText().strip()
        if not net:
            _lines, nets, _w = self.model.compile_netlist()
            if not nets:
                QMessageBox.information(self, "Parametric sweep",
                                        "This schematic has no nets.")
                return
            self.sweep_net_box.addItems(nets)
            net = nets[0]
        start = self.sweep_start_box.value()
        stop = self.sweep_stop_box.value()
        if stop <= start:
            QMessageBox.warning(self, "Parametric sweep",
                                "Stop must exceed start.")
            return
        steps = int(self.sweep_steps_box.value())
        if steps < 2:
            QMessageBox.warning(self, "Parametric sweep",
                                "At least 2 steps.")
            return
        base_value = comp.value
        try:
            spice_value(base_value)
        except (TypeError, ValueError):
            QMessageBox.warning(self, "Parametric sweep",
                                f"Component {comp_id} has a non-numeric value.")
            return
        values = [start + (stop - start) * i / (steps - 1) for i in range(steps)]
        results = []
        engine = None
        try:
            engine = NgSpiceEngine(verbose=False)
            for v in values:
                comp.value = f"{v:.6g}"
                lines, _nets, _warns = self.model.compile_netlist()
                engine.load_circuit(lines)
                rc = engine.cmd("run")
                times = engine.get_vector_array("time")
                trace = engine.get_vector_array(net)
                if rc == 0 and times and trace and len(trace) == len(times):
                    results.append((v, list(times), list(trace)))
        finally:
            comp.value = base_value

        self.sweep_last = results
        self.sweep_plot.clear()
        colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd",
                  "#ff7f0e", "#8c564b", "#17becf", "#e377c2"]
        for i, (v, times, trace) in enumerate(results):
                self.sweep_plot.plot([t * 1000.0 for t in times], trace,
                                     pen=pg.mkPen(colors[i % len(colors)], width=2),
                                     name=f"{v:.1f}")
        self.sweep_plot.setTitle(
            f"Parametric sweep - {comp_id} ({len(results)} steps)")
        self.sweep_info.setText(
            f"{comp_id}: {len(results)} steps, "
            f"{values[0]:.1f} to {values[-1]:.1f}")
        self.log(f"Parametric sweep: {comp_id} {len(results)} steps")
        if self.bode_net_box.findText(net) < 0:
            self.bode_net_box.addItem(net)
        self._sync_serial_nets()

    # ------------------------------------------------------------------
    # Instrument tabs: PV, AWG, I-V curve tracer
    # ------------------------------------------------------------------
    def run_pv(self):
        """Solar PV / MPPT trace via studio_engine.trace_solar_pv."""
        from bridge.studio_engine import StudioSimulationEngine

        irr = self.pv_irr_box.value()
        temp = self.pv_temp_box.value()
        pts = int(self.pv_pts_box.value())
        out = StudioSimulationEngine.trace_solar_pv(
            irradiance_w_m2=irr, temp_c=temp, points=pts)
        self.pv_last = out
        self.pv_iv_plot.clear()
        self.pv_iv_plot.plot(out["v_arr"], out["i_arr"],
                             pen=pg.mkPen("#1f77b4", width=2), name="I-V")
        self.pv_p_plot.clear()
        self.pv_p_plot.plot(out["v_arr"], out["p_arr"],
                             pen=pg.mkPen("#d62728", width=2), name="P-V")
        self.pv_iv_plot.setTitle("I-V curve")
        self.pv_p_plot.setTitle("P-V curve")
        self.pv_info.setText(
            f"Pmax {out['p_max_w']:.3f} W, Voc {out['v_oc']:.3f} V, "
            f"Isc {out['i_sc']:.3f} A, Vmp {out['v_mpp']:.3f} V, "
            f"Imp {out['i_mpp']:.3f} A, FF {out['fill_factor']:.3f}")
        self.log(f"PV trace: {self.pv_info.text()}")

    def run_awg(self):
        """AWG waveform synthesis via studio_engine.generate_awg_signal."""
        from bridge.studio_engine import StudioSimulationEngine

        t, sig = StudioSimulationEngine.generate_awg_signal(
            wave_type=self.awg_type_box.currentText(),
            freq_hz=self.awg_freq_box.value(),
            amp_v=self.awg_amp_box.value(),
            offset_v=self.awg_offset_box.value(),
            duration_ms=self.awg_duration_box.value(),
            points=int(self.awg_points_box.value()))
        self.awg_last = (t, sig)
        self.awg_plot.clear()
        self.awg_plot.plot(t, sig,
                           pen=pg.mkPen("#1f77b4", width=2),
                           name=self.awg_type_box.currentText())
        self.awg_plot.setTitle(
            f"AWG - {self.awg_type_box.currentText()} "
            f"{self.awg_freq_box.value():.0f} Hz")
        self.awg_info.setText(
            f"{len(t)} points, {self.awg_type_box.currentText()}, "
            f"max {max(sig):.3f} V, min {min(sig):.3f} V")
        self.log(f"AWG: {self.awg_info.text()}")

    def run_curve_tracer(self):
        """I-V curve tracer via studio_engine trace_mosfet_iv / trace_diode_iv."""
        from bridge.studio_engine import StudioSimulationEngine

        idx = self.curve_device_box.currentIndex()
        self.curve_plot.clear()
        self.curve_last = None
        if idx == 0:
            pts = int(self.curve_pts_box.value())
            vmax = self.curve_vmax_box.value()
            out = StudioSimulationEngine.trace_mosfet_iv(vds_max=vmax, points=pts)
            self.curve_last = out
            colors = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd",
                      "#ff7f0e", "#8c564b", "#17becf", "#e377c2"]
            for i, curve in enumerate(out["curves"]):
                self.curve_plot.plot(curve["vds"], curve["id_amps"],
                                     pen=pg.mkPen(colors[i % len(colors)], width=2),
                                     name=f"Vgs={curve['vgs']:.1f} V")
            info = (f"{len(out['curves'])} curves, Vds points {len(out['vds'])}, "
                    f"Vth {out.get('vth', 0):.2f} V, Rds(on) {out.get('rdson_mohm', 0):.0f} mohm")
        else:
            pts = int(self.curve_pts_box.value())
            vfmax = self.curve_vfmax_box.value()
            out = StudioSimulationEngine.trace_diode_iv(vf_max=vfmax, points=pts)
            self.curve_last = out
            self.curve_plot.plot(out["vf"], out["i_schottky"],
                                 pen=pg.mkPen("#1f77b4", width=2),
                                 name="Schottky (1N5819)")
            self.curve_plot.plot(out["vf"], out["i_silicon"],
                                 pen=pg.mkPen("#d62728", width=2),
                                 name="Silicon (1N4148)")
            self.curve_plot.plot(out["vf"], out["i_zener"],
                                 pen=pg.mkPen("#2ca02c", width=2),
                                 name="Zener")
            info = (f"{len(out['vf'])} Vf points, "
                    f"families plotted: Schottky, Silicon, Zener")
        self.curve_plot.setTitle("I-V curve tracer")
        self.curve_info.setText(info)
        self.log(f"Curve tracer: {info}")

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

        use_binary = os.environ.get("WOSP_USE_BINARY_COSIM", "").strip().lower() in ("1", "true", "yes", "on")
        run = None
        aborted = False
        if use_binary:
            self.log("=== closed-loop co-simulation (REAL FIRMWARE BINARY) ===")
            for pin, spec in laws.items():
                self.log(f"  {pin}: real firmware from QEMU")
            pin_specs = {}
            for pin, spec in laws.items():
                sense_net = spec.get("sense_net") or spec.get("sense")
                pin_specs[pin] = {"sense_net": sense_net}
            try:
                self._begin_run(self.effective_duration_ms())
                run = binary_runner.run_binary_cosim(
                    self.model, pin_specs,
                    vin=self.vin_box.value(),
                    tstep_us=self.effective_tstep_us(),
                    duration_ms=self.effective_duration_ms(),
                    progress_callback=self._on_progress,
                    stop_flag=lambda: self._abort)
            except Exception as exc:
                self.log(f"ERROR: binary cosim failed: {exc}")
                return
            finally:
                if run is not None:
                    aborted = getattr(run, "aborted", False)
                self._end_run()
        else:
            self.log("=== closed-loop co-simulation ===")
            for pin, spec in laws.items():
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
                if run is not None:
                    aborted = getattr(run, "aborted", False)
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
        self._sync_trace_list()
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
    def help_html(self):
        """The F1 overlay's content, as one string.

        Kept apart from show_help() so the documentation itself is under
        test: deleting a shortcut or a measurement example from the code now
        fails a test instead of quietly making the help less helpful.
        """
        return """
<h3>WOWKISPICE editor - gestures, shortcuts and measurements</h3>
<p>Press <b>F1</b> or the <b>?</b> button on the toolbar to reopen this panel.
Every toolbar button also repeats its key in its tooltip.</p>

<h3>Place and edit</h3>
<ul>
<li>Type in the <b>filter</b> box to search the palette, then click a part -
    the symbol follows the pointer before you commit it</li>
<li>Click pin -&gt; click pin to wire; <b>Esc</b> cancels</li>
<li>Drag a part to move it (snaps to grid); <b>Ctrl+click</b> adds to the
    selection, left-drag on empty canvas rubber-bands a selection</li>
<li>A bare letter <b>arms that part</b> - <b>R</b>esistor, <b>C</b>apacitor,
    <b>L</b>inductor, <b>D</b>iode, <b>V</b> source, <b>I</b> source,
    <b>M</b>OSFET, <b>G</b>round, <b>U</b> MCU, <b>A</b>rduino Uno,
    <b>Shift+A</b> Mega, <b>N</b>ano, <b>S</b>TM32, <b>E</b>SP32,
    <b>Shift+E</b> ESP32-S3. The ghost follows the pointer; click to commit.
    <b>Esc</b> cancels whatever is armed</li>
<li><b>Ctrl+R</b> rotate 90&deg;, <b>Del</b> delete, <b>Ctrl+E</b> edit value,
    <b>Ctrl+L</b> label net</li>
<li><b>Ctrl+Z</b> / <b>Ctrl+Y</b> (or <b>Ctrl+Shift+Z</b>) undo / redo</li>
<li>Double-click a part on the sheet to rotate it</li>
</ul>

<h3>Simulation controls</h3>
<ul>
<li><b>F2</b> compiles the schematic and runs it in real ngspice;
    <b>Ctrl+.</b> aborts a running simulation</li>
<li>Netlist tab &gt; <b>Run this netlist</b> simulates a hand-edited netlist
    instead of the schematic</li>    <li><b>Ctrl+F</b> FFT of the selected net, <b>Ctrl+B</b> Bode / AC sweep,
    <b>Ctrl+Shift+K</b> clears the cursors</li>

<li>Tools &gt; Qualification Battery runs the fault-injection and
    temperature-corner audits</li>
<li><b>Ctrl+0</b> re-fits the schematic view</li>
</ul>

<h3>Measurement tools</h3>
<ul>
<li>Left-click the waveform plot to drop <b>cursor A</b>, click again for
    <b>cursor B</b>; drag a cursor line to move it. The readout strip under
    the plot prints <b>t1/v1, t2/v2, dt, dv, slope and 1/dt</b>. Values are
    interpolated from the solver's data at the cursor time - the same number
    at every zoom level, not a screen position.</li>
<li>Click a row in the <b>Traces</b> list to choose which net the cursors
    measure; untick a row to hide it. The readout also shows <b>min, max,
    rms and p-p</b> for that trace.</li>
<li>Results &gt; Export Results as CSV writes the full time series;
    Results &gt; Export Waveform Plot as PNG / Save Plot as PDF for figures.</li>
</ul>

<h3>.meas equivalents (documented in-app)</h3>
<p>The schematic compiler does not emit <code>.meas</code> lines. Two ways to
get exactly those measurements:</p>
<ul>
<li><b>GUI:</b>
    <ul>
    <li><code>.meas tran vout_max MAX v(out)</code> -&gt; the <b>max</b> figure
        in the readout strip (<b>min</b> for MIN)</li>
    <li><code>.meas tran vout_rms RMS v(out)</code> -&gt; the <b>rms</b>
        figure in the readout strip</li>
    <li><code>.meas tran ripple PP v(out)</code> -&gt; the <b>p-p</b> figure</li>
    <li><code>.meas tran v_at_1ms FIND v(out) AT=1m</code> -&gt; click the plot
        at 1 ms: <b>t1</b> and <b>v1</b> are that measurement</li>
    <li>Period / frequency: place the two cursors one period apart and read
        <b>dt</b> and <b>1/dt</b>; slew rate is <b>slope</b> (dv/dt)</li>
    </ul>
</li>
<li><b>Netlist tab:</b> paste the <code>.meas</code> lines into the editable
    netlist and press <b>Run this netlist</b>. ngspice executes them and the
    results print to the console log as
    <code>meas: vout_max = 4.32373e+00 at= 3.00110e-03</code>.</li>
</ul>

<h3>Waveform navigation</h3>
<ul>
<li>Mouse wheel zooms about the pointer; hold <b>Ctrl</b> for fine zoom</li>
<li><b>Middle-drag</b>, <b>right-drag</b> or <b>space+left-drag</b> pans</li>
<li><b>Ctrl+=</b> zoom in, <b>Ctrl+-</b> zoom out, <b>Ctrl+0</b> fits the sheet</li>
<li>Click a trace row to make the cursors measure it; untick a row to hide it</li>
</ul>

<h3>Appearance and chrome</h3>
<ul>
<li><b>Ctrl+T</b> dark/light appearance, <b>Ctrl+G</b> grid,
    <b>Ctrl+Shift+R</b> rulers</li>
<li>View &gt; Icon / Cursor Size (Small / Medium / Large) resizes the toolbar
    and palette icons together with the canvas crosshair and plot cursor
    strokes</li>
</ul>
"""

    def show_help(self):
        """Visible F1 overlay: a scrollable dialog, not a clipped message box.

        The old help was a QMessageBox whose hardcoded gesture list had
        outgrown the box - simulation, measurement and waveform-navigation
        shortcuts had nowhere to live, which is the "poor documentation"
        complaint this replaces. Non-modal, so it can sit beside the canvas
        while you try a shortcut.
        """
        existing = getattr(self, "_help_dialog", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Help - gestures, shortcuts and measurements (F1)")
        dialog.resize(740, 660)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QLabel()
        body.setTextFormat(Qt.RichText)
        body.setWordWrap(True)
        body.setText(self.help_html())
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        close = QPushButton("Close")
        close.clicked.connect(dialog.close)
        layout.addWidget(close)
        self._help_dialog = dialog
        dialog.finished.connect(
            lambda _result=0: setattr(self, "_help_dialog", None))
        dialog.show()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.cancel_current()
            event.accept()
            return
        if key == Qt.Key_Delete:
            self.scene.delete_selected()
            event.accept()
            return
        # Letter keys arm a part. These normally arrive as QAction shortcuts
        # (which win, and do not reach here); this branch is the fallback for
        # the paths where they do, and keeps the binding testable in one place.
        plain = event.modifiers() & (Qt.ControlModifier | Qt.AltModifier
                                     | Qt.MetaModifier)
        if not plain:
            comp_type = PART_HOTKEYS.get(hotkey_text(event))
            if comp_type is not None:
                self._arm_type(comp_type)
                event.accept()
                return
        super().keyPressEvent(event)

    def showEvent(self, event):
        # Start with the sheet focused, so the letter keys work from launch
        # without the user having to click the canvas first.
        super().showEvent(event)
        self.view.setFocus()


def main():
    # Qt fixes high-DPI behaviour when the QApplication is constructed, so
    # ask for it BEFORE the app exists. Without this, at 150/200% Windows
    # scaling every toolbar icon rendered as a fixed 18-device-pixel bitmap
    # (stretched, blurry) while the canvas grid scaled correctly - chrome and
    # canvas out of proportion. Measured by tests/hidpi_probe.py.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(theme.APP_NAME)
    app.setOrganizationName(theme.ORG_NAME)
    saved = theme.settings().value("appearance/name", "dark", str)
    theme.apply_theme(app, saved)
    win = SchematicEditor()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()