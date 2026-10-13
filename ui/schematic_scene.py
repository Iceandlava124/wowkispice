"""
schematic_scene.py - Editing model for the schematic editor canvas.

Owns the component/wire items, the wiring gesture and undo/redo. State lives
in a bridge.cad_engine.SchematicNetlistEngine; this class mirrors it as
graphics items and keeps the two in sync.

Undo uses full-document snapshots (engine.to_dict / load_dict) - the schematic
is small enough that this is simpler and more reliable than command objects.
"""

import re

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPainterPath
from PyQt5.QtWidgets import QApplication, QGraphicsPathItem, QGraphicsScene

from bridge.cad_engine import SchematicComponent, SchematicNetlistEngine
from ui.schematic_items import ComponentItem, GhostItem, JunctionItem, WireItem
from ui.schematic_symbols import GRID, SYMBOLS, default_value_of, prefix_of

UNDO_LIMIT = 100
GRID_MAJOR_EVERY = 5       # every fifth dot is drawn brighter
MIN_DOT_ZOOM = 0.55        # below this the grid is dropped rather than smeared


class SchematicScene(QGraphicsScene):
    """Component placement, wiring, selection edits and undo/redo."""

    status = pyqtSignal(str)
    documentChanged = pyqtSignal()
    itemMenuRequested = pyqtSignal(object, object)   # (ComponentItem, QPoint global)
    itemEditValue = pyqtSignal(object)                # (ComponentItem)

    def __init__(self, model: SchematicNetlistEngine = None, parent=None):
        super().__init__(parent)
        self.model = model if model is not None else SchematicNetlistEngine()
        self.armed_type = None            # palette tool armed for click-to-place
        self.comp_items = {}              # comp_id -> ComponentItem
        self.pin_items = {}               # (comp_id, pin_name) -> PinItem
        self.wire_items = []              # list[WireItem]
        self._wire_start = None           # pending wire origin
        self._rubber = None               # temporary wire preview
        self._undo = []
        self._redo = []
        self._drag_snapshot = None
        self._drag_committed = False
        self._junctions = []
        self._ghost = None
        self.grid_visible = True
        self.setSceneRect(-2000, -1500, 4000, 3000)
        self.rebuild()

    # ------------------------------------------------------------------
    # Model <-> graphics
    # ------------------------------------------------------------------
    def rebuild(self):
        """Recreate every graphics item from the engine's current state."""
        self._clear_rubber()
        self._clear_ghost()
        self.clear()
        self.comp_items.clear()
        self.pin_items.clear()
        self.wire_items.clear()
        self._junctions.clear()

        for comp in self.model.components.values():
            item = ComponentItem(comp)
            item.setPos(comp.x, comp.y)
            item.setRotation(comp.rotation)
            item.menuRequested.connect(self._on_item_menu)
            item.editValueRequested.connect(self._on_item_edit)
            self.addItem(item)
            self.comp_items[comp.comp_id] = item
            # PinItems are children created by ComponentItem; index them by ref
            for child in item.childItems():
                pin_name = getattr(child, "pin_name", None)
                if pin_name is not None:
                    self.pin_items[(child.comp_id, pin_name)] = child

        for wire in self.model.wires:
            a, b = self._parse_ref(wire.get("from", "")), self._parse_ref(wire.get("to", ""))
            if a in self.pin_items and b in self.pin_items:
                w_item = WireItem(a, b)
                self.addItem(w_item)
                w_item.refresh(self.pin_items)
                self.wire_items.append(w_item)

        self._refresh_junctions()
        if self.armed_type:
            self._show_ghost(self.armed_type)
        self.documentChanged.emit()

    @staticmethod
    def _parse_ref(ref: str):
        if ":" not in ref:
            return None
        cid, pin = ref.split(":", 1)
        return (cid, pin)

    def _on_item_menu(self, item, pos):
        self.itemMenuRequested.emit(item, pos)

    def _on_item_edit(self, item):
        self.itemEditValue.emit(item)

    def _item_for_pin(self, comp_id, pin_name):
        return self.comp_items.get(comp_id)

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------
    def capture(self):
        return self.model.to_dict()

    def push_undo(self):
        self._undo.append(self.capture())
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            self.status.emit("Nothing to undo")
            return
        self._redo.append(self.capture())
        self.model.load_dict(self._undo.pop())
        self.rebuild()
        self.status.emit("Undo")

    def redo(self):
        if not self._redo:
            self.status.emit("Nothing to redo")
            return
        self._undo.append(self.capture())
        self.model.load_dict(self._redo.pop())
        self.rebuild()
        self.status.emit("Redo")

    # Called by ComponentItem before a drag starts, so a no-op click
    # (press + release without moving) does not pollute the undo stack.
    def begin_component_drag(self, item):
        self._drag_snapshot = self.capture()
        self._drag_committed = False

    def end_component_drag(self, item):
        self._drag_snapshot = None
        self._drag_committed = False

    def _commit_drag_if_moved(self):
        if self._drag_snapshot is not None and not self._drag_committed:
            self._undo.append(self._drag_snapshot)
            if len(self._undo) > UNDO_LIMIT:
                self._undo.pop(0)
            self._redo.clear()
            self._drag_committed = True

    # ------------------------------------------------------------------
    # Placement
    # ------------------------------------------------------------------
    def next_designator(self, prefix):
        used = set()
        for name in self.model.components:
            m = re.match(rf"^{re.escape(prefix)}(\d+)$", name)
            if m:
                used.add(int(m.group(1)))
        n = 1
        while n in used:
            n += 1
        return f"{prefix}{n}"

    def place_component(self, comp_type, pos, name=None, value=None):
        """Add a component of `comp_type` at scene position `pos`."""
        if comp_type not in SYMBOLS:
            self.status.emit(f"Unknown component type: {comp_type}")
            return None
        name = name or self.next_designator(prefix_of(comp_type))
        value = default_value_of(comp_type) if value is None else value
        comp = SchematicComponent(
            comp_id=name, comp_type=comp_type, name=name, value=value,
            x=round(pos.x() / GRID) * GRID, y=round(pos.y() / GRID) * GRID,
        )
        self.push_undo()
        self.model.add_component(comp)
        self.rebuild()
        item = self.comp_items.get(name)
        if item is not None:
            item.setSelected(True)
        self.status.emit(f"Placed {name} ({comp_type}) = {value}")
        return comp

    def delete_component(self, comp_id):
        if comp_id in self.model.components:
            self.push_undo()
            self.model.remove_component(comp_id)
            self.rebuild()
            self.status.emit(f"Deleted {comp_id}")

    def delete_selected(self):
        comps = [i.comp.comp_id for i in self.selectedItems()
                 if isinstance(i, ComponentItem)]
        wires = [w for w in self.model.wires
                 if self._wire_selected(w)]
        if not comps and not wires:
            return
        self.push_undo()
        for comp_id in comps:
            self.model.remove_component(comp_id)
        if wires:
            keep = [w for w in self.model.wires if w not in wires]
            self.model.wires = keep
        self.rebuild()
        self.status.emit("Deleted selection")

    def _wire_selected(self, wire):
        for item in self.selectedItems():
            if isinstance(item, WireItem):
                if item.from_ref == self._parse_ref(wire.get("from", "")) and \
                   item.to_ref == self._parse_ref(wire.get("to", "")):
                    return True
        return False

    def rotate_selected(self):
        items = [i for i in self.selectedItems() if isinstance(i, ComponentItem)]
        if not items:
            return
        self.push_undo()
        for item in items:
            item.comp.rotation = (item.comp.rotation + 90) % 360
            item.setRotation(item.comp.rotation)
        self._refresh_all_wires()
        self.status.emit(f"Rotated {len(items)} component(s)")

    def rotate_item(self, item):
        """Rotate one component in place (used by click-to-rotate)."""
        if not isinstance(item, ComponentItem):
            return
        self.push_undo()
        item.comp.rotation = (item.comp.rotation + 90) % 360
        item.setRotation(item.comp.rotation)
        self._refresh_all_wires()
        self.status.emit(f"{item.comp.name} rotated to {item.comp.rotation} deg")

    def toggle_selection(self, item):
        """
        LTspice-style additive select.

        A plain click replaces the selection; Ctrl+click adds or removes one
        item so a group can be rotated, moved or deleted together.
        """
        if item is None:
            return
        item.setSelected(not item.isSelected())

    def last_click_was_double(self, item, event) -> bool:
        """
        True when this press is the second click on the same item.

        QGraphicsView already turns a double-click into a QEvent.GraphicsScene
        DoubleClick, which arrives *after* the press, so the press handler
        cannot see it. Tracking clicks here is what makes click-to-rotate work
        without stealing single-click drag-to-move.
        """
        from PyQt5.QtCore import QDateTime
        now = QDateTime.currentMSecsSinceEpoch()
        same = getattr(self, "_last_click_item", None) is item
        elapsed = now - getattr(self, "_last_click_ms", -(10 ** 9))
        # Record this click before deciding, so the *next* press compares
        # against it. Forgetting to store the item would make a second click
        # never register as a double click.
        self._last_click_item = item
        self._last_click_ms = now
        return same and elapsed < QApplication.doubleClickInterval()

    def set_component_value(self, comp_id, value):
        comp = self.model.components.get(comp_id)
        if comp is None or comp.value == value:
            return
        self.push_undo()
        comp.value = value
        item = self.comp_items.get(comp_id)
        if item is not None:
            item.setToolTip(f"{comp.name} [{comp.comp_type}] = {value}")
            item.update()
        self.status.emit(f"{comp_id} = {value}")
        self.documentChanged.emit()

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def pin_clicked(self, comp_id, pin_name):
        ref = (comp_id, pin_name)
        if self._wire_start is None:
            self._wire_start = ref
            self._rubber = QGraphicsPathItem()
            from ui.schematic_items import WIRE_BLUE
            self._rubber.setPen(QPen(WIRE_BLUE, 1.5, Qt.DashLine))
            self._rubber.setZValue(5)
            self.addItem(self._rubber)
            self.status.emit(f"Wire from {comp_id}.{pin_name} - click target pin (Esc cancels)")
            return

        if self._wire_start == ref:
            self.cancel_wire()
            return

        start, self._wire_start = self._wire_start, None
        self._clear_rubber()

        duplicate = any(
            self._parse_ref(w.get("from", "")) == start and
            self._parse_ref(w.get("to", "")) == ref
            for w in self.model.wires
        ) or any(
            self._parse_ref(w.get("from", "")) == ref and
            self._parse_ref(w.get("to", "")) == start
            for w in self.model.wires
        )
        if duplicate:
            self.status.emit("Those pins are already wired")
            return

        self.push_undo()
        self.model.add_wire(f"{start[0]}:{start[1]}", f"{ref[0]}:{ref[1]}")
        self.rebuild()
        self.status.emit(
            f"Wired {start[0]}.{start[1]} -> {ref[0]}.{ref[1]} "
            "(name the net with right-click for a readable label)"
        )

    def cancel_wire(self):
        self._wire_start = None
        self._clear_rubber()
        self.status.emit("Wire cancelled")

    def _clear_rubber(self):
        if self._rubber is not None:
            self.removeItem(self._rubber)
            self._rubber = None

    def label_wire(self, wire, net_name):
        """Give a wire a human-readable net name (shown in the netlist)."""
        self.push_undo()
        wire["net"] = net_name
        # Keep the component pin->net map consistent with the new label
        for ref in (wire.get("from", ""), wire.get("to", "")):
            parsed = self._parse_ref(ref)
            if parsed and parsed[0] in self.model.components:
                self.model.components[parsed[0]].pins[parsed[1]] = net_name
        self.rebuild()
        self.status.emit(f"Net renamed to {net_name}")

    def wires_changed(self, moved_item=None):
        self._commit_drag_if_moved()
        self._refresh_all_wires()

    def _refresh_all_wires(self):
        for wire in self.wire_items:
            wire.refresh(self.pin_items)
        self._refresh_junctions()

    def _refresh_junctions(self):
        """Put a dot on every pin carrying three or more wires."""
        counts = {}
        for wire in self.model.wires:
            for ref in (self._parse_ref(wire.get("from", "")),
                        self._parse_ref(wire.get("to", ""))):
                if ref is not None:
                    counts[ref] = counts.get(ref, 0) + 1
        wanted = {ref for ref, n in counts.items() if n >= 3}
        for junction in list(self._junctions):
            if junction.ref not in wanted:
                self.removeItem(junction)
                self._junctions.remove(junction)
        live = {j.ref for j in self._junctions}
        for ref in wanted - live:
            pin = self.pin_items.get(ref)
            if pin is None:
                continue
            junction = JunctionItem(pin.scenePos().x(), pin.scenePos().y())
            junction.ref = ref
            self.addItem(junction)
            self._junctions.append(junction)

    # ------------------------------------------------------------------
    # Armed palette tool: the symbol follows the pointer before committing
    # ------------------------------------------------------------------
    def _show_ghost(self, comp_type):
        if self._ghost is None:
            self._ghost = GhostItem(comp_type)
            self.addItem(self._ghost)
        else:
            self._ghost.set_comp_type(comp_type)
        self._ghost.setVisible(True)

    def _clear_ghost(self):
        if self._ghost is not None:
            self.removeItem(self._ghost)
            self._ghost = None

    def set_armed(self, comp_type):
        """Arm (or disarm, with None) the click-to-place tool."""
        self.armed_type = comp_type
        if comp_type:
            self._show_ghost(comp_type)
        else:
            self._clear_ghost()

    def move_ghost(self, scene_pos):
        if self._ghost is not None:
            self._ghost.move_snap(scene_pos)
            return self._ghost.pos()
        return None

    def mouseMoveEvent(self, event):
        if self._ghost is not None:
            self.move_ghost(event.scenePos())
        if self._wire_start is not None and self._rubber is not None:
            start_item = self.pin_items.get(self._wire_start)
            if start_item is not None:
                p0 = start_item.scenePos()
                p1 = event.scenePos()
                path = QPainterPath(p0)
                path.lineTo(p1)
                self._rubber.setPath(path)
                self.status.emit(
                    f"Wiring {self._wire_start[0]}.{self._wire_start[1]} -> "
                    f"({p1.x():.0f}, {p1.y():.0f})"
                )
            event.accept()
            return
        super().mouseMoveEvent(event)

    # ------------------------------------------------------------------
    # Appearance
    # ------------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF):
        """A dot grid, not a line grid.

        A line per grid cell turns into grey mush when you zoom out, and the
        grid is only ever a placement aid - dots read as alignment points the
        way they do in a modern EDA tool. The palette is looked up per paint,
        so switching appearance needs nothing but a repaint.
        """
        from ui import theme
        pal = theme.current()
        painter.fillRect(rect, QColor(pal.canvas))
        if not self.grid_visible:
            return
        if painter.worldTransform().m11() < MIN_DOT_ZOOM:
            return
        step = GRID
        left = int(rect.left()) - (int(rect.left()) % step)
        top = int(rect.top()) - (int(rect.top()) % step)
        minor, major = [], []
        y = top
        row = int(top // step)
        while y < rect.bottom():
            x = left
            col = int(left // step)
            while x < rect.right():
                bucket = major if (row % GRID_MAJOR_EVERY == 0
                                   and col % GRID_MAJOR_EVERY == 0) else minor
                bucket.append(QPointF(x, y))
                x += step
                col += 1
            y += step
            row += 1
        radius = 1.0 / max(painter.worldTransform().m11(), 0.001)
        radius = min(max(radius, 0.5), 2.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(pal.canvas_dot))
        for dot in minor:
            painter.drawEllipse(dot, radius, radius)
        painter.setBrush(QColor(pal.canvas_dot_major))
        major_radius = radius * 1.6
        for dot in major:
            painter.drawEllipse(dot, major_radius, major_radius)

    def clear_document(self):
        self.push_undo()
        self.model.clear()
        self.rebuild()
        self.status.emit("New empty schematic")