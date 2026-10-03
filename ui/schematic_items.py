"""
schematic_items.py - QGraphicsItem classes for the schematic editor canvas.

PinItem       clickable terminal (child of a ComponentItem)
ComponentItem movable, rotatable symbol bound 1:1 to a bridge SchematicComponent
WireItem      orthogonal wire that tracks its two endpoint pins
"""

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen, QPainterPath
from PyQt5.QtWidgets import (QGraphicsItem, QGraphicsObject, QGraphicsEllipseItem,
                             QGraphicsPathItem)

from bridge.cad_engine import SchematicComponent
from ui.schematic_symbols import GRID, extent_of, pins_of

INK = QColor("#1b1f23")
WIRE_BLUE = QColor("#1f4e9c")
PIN_RED = QColor("#c0392b")
PIN_HOVER = QColor("#1a9850")
LABEL_GREY = QColor("#555f6a")
PIN_RADIUS = 4.0


# --------------------------------------------------------------------------
# Symbol drawing
# --------------------------------------------------------------------------
def _seg(painter: QPainter, x1, y1, x2, y2, width=2.0):
    painter.setPen(QPen(INK, width))
    painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def draw_symbol(painter: QPainter, comp_type: str):
    """Draw the component body (pins are drawn separately as PinItems)."""
    if comp_type == "R":
        _seg(painter, -30, 0, -18, 0)
        segs = 6
        step = 36.0 / segs
        for i in range(segs):
            x1 = -18 + i * step
            y1 = -7 if i % 2 == 0 else 7
            _seg(painter, x1, y1, x1 + step, y1)
        _seg(painter, 18, 0, 30, 0)

    elif comp_type == "C":
        _seg(painter, -30, 0, -6, 0)
        _seg(painter, 6, 0, 30, 0)
        _seg(painter, -6, -11, -6, 11)
        _seg(painter, 6, -11, 6, 11)

    elif comp_type == "L":
        _seg(painter, -30, 0, -16, 0)
        for x in (-16, -8, 0, 8):
            painter.setPen(QPen(INK, 2.0))
            painter.drawArc(QRectF(x, -6, 8, 12), 180 * 16, 180 * 16)
        _seg(painter, 16, 0, 30, 0)

    elif comp_type in ("V", "I"):
        _seg(painter, -30, 0, -14, 0)
        _seg(painter, 14, 0, 30, 0)
        painter.setPen(QPen(INK, 2.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(0, 0), 14, 14)
        if comp_type == "V":
            _seg(painter, -10, 0, -4, 0)
            _seg(painter, -7, -3, -7, 3)
            _seg(painter, 4, 0, 10, 0)
        else:
            _seg(painter, -8, 0, 8, 0)
            _seg(painter, 3, -4, 8, 0)
            _seg(painter, 3, 4, 8, 0)

    elif comp_type == "D":
        _seg(painter, -30, 0, -8, 0)
        _seg(painter, 8, 0, 30, 0)
        painter.setPen(QPen(INK, 2.0))
        painter.setBrush(QBrush(QColor("#f3d9a4")))
        tri = QPainterPath(QPointF(-8, -10))
        tri.lineTo(-8, 10)
        tri.lineTo(8, 0)
        tri.closeSubpath()
        painter.drawPath(tri)
        _seg(painter, 8, -10, 8, 10)

    elif comp_type == "MOSFET":
        _seg(painter, -30, 0, -18, 0)          # gate lead
        _seg(painter, -18, -12, -18, 12)       # gate plate
        _seg(painter, -18, 0, -10, 0)          # gate -> channel
        _seg(painter, -10, -16, -10, 16)       # channel
        _seg(painter, -10, -16, 0, -16)        # drain elbow
        _seg(painter, 0, -30, 0, -16)
        _seg(painter, -10, 16, 0, 16)          # source elbow
        _seg(painter, 0, 16, 0, 30)
        _seg(painter, -6, 11, -10, 16)         # body arrow (N-channel)
        _seg(painter, -6, 21, -10, 16)

    elif comp_type == "GND":
        _seg(painter, 0, 0, 0, 10)
        _seg(painter, -11, 10, 11, 10)
        _seg(painter, -7, 15, 7, 15)
        _seg(painter, -3, 20, 3, 20)

    elif comp_type == "MCU":
        painter.setPen(QPen(INK, 2.0))
        painter.setBrush(QBrush(QColor("#eef3fb")))
        painter.drawRect(QRectF(-40, -40, 80, 80))
        for _name, x, y in pins_of("MCU"):
            _seg(painter, -40 if x < 0 else 40, y, x, y, width=1.5)
        painter.drawText(QRectF(-40, -14, 80, 28), Qt.AlignCenter, "MCU")

    else:  # unknown type (e.g. loaded from a file) - keep it visible and honest
        painter.setPen(QPen(INK, 2.0))
        painter.setBrush(QBrush(QColor("#eeeeee")))
        painter.drawRect(QRectF(-20, -14, 40, 28))
        painter.drawText(QRectF(-20, -14, 40, 28), Qt.AlignCenter, "?")


# --------------------------------------------------------------------------
# Pins
# --------------------------------------------------------------------------
class PinItem(QGraphicsEllipseItem):
    """A clickable terminal. Clicking starts/finishes a wire."""

    def __init__(self, comp_id: str, pin_name: str, x: float, y: float):
        super().__init__(-PIN_RADIUS, -PIN_RADIUS, PIN_RADIUS * 2, PIN_RADIUS * 2)
        self.comp_id = comp_id
        self.pin_name = pin_name
        self.setPos(x, y)
        self.setBrush(QBrush(PIN_RED))
        self.setPen(QPen(QColor("#ffffff"), 1.0))
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.setToolTip(f"{comp_id}.{pin_name}")
        self.setCursor(Qt.PointingHandCursor)

    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(PIN_HOVER))
        self.update()

    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(PIN_RED))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene = self.scene()
            if scene is not None and hasattr(scene, "pin_clicked"):
                scene.pin_clicked(self.comp_id, self.pin_name)
            event.accept()
            return
        super().mousePressEvent(event)


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------
class ComponentItem(QGraphicsObject):
    """Symbol bound 1:1 to a bridge.cad_engine.SchematicComponent.

    QGraphicsObject (not QGraphicsItem) because it emits signals for the
    context menu / edit-value gestures - signals need a QObject.
    """

    menuRequested = pyqtSignal(object, object)   # (ComponentItem, QPoint global pos)
    editValueRequested = pyqtSignal(object)      # (ComponentItem)

    def __init__(self, comp: SchematicComponent):
        super().__init__()
        self.comp = comp
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(1)
        ex, ey, ew, eh = extent_of(comp.comp_type)
        self._bounding = QRectF(ex, ey, ew, eh)
        self.setToolTip(f"{comp.name} [{comp.comp_type}] = {comp.value}")
        self._make_pins()

    # -- pins ------------------------------------------------------------
    def _make_pins(self):
        for name, x, y in pins_of(self.comp.comp_type):
            pin = PinItem(self.comp.comp_id, name, x, y)
            pin.setParentItem(self)

    # -- Qt geometry -----------------------------------------------------
    def boundingRect(self) -> QRectF:
        return self._bounding

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        draw_symbol(painter, self.comp.comp_type)

        pins = pins_of(self.comp.comp_type)
        if pins:
            y_min = min(p[2] for p in pins)
            y_max = max(p[2] for p in pins)
        else:
            y_min, y_max = -20, 20
        rot = -self.comp.rotation

        painter.setPen(QPen(LABEL_GREY))
        # Designator above the symbol (kept upright through rotation)
        painter.save()
        painter.translate(0, y_min - 10)
        painter.rotate(rot)
        painter.drawText(QRectF(-self._bounding.width() / 2, -9,
                                self._bounding.width(), 18),
                         Qt.AlignHCenter | Qt.AlignVCenter, self.comp.name)
        painter.restore()
        # Value below the symbol
        if self.comp.value:
            painter.save()
            painter.translate(0, y_max + 14)
            painter.rotate(rot)
            painter.drawText(QRectF(-self._bounding.width() / 2, -9,
                                    self._bounding.width(), 18),
                             Qt.AlignHCenter | Qt.AlignVCenter, self.comp.value)
            painter.restore()

    # -- interaction -----------------------------------------------------
    def itemChange(self, change, value):
        if change == QGraphicsObject.ItemPositionChange:
            # Snap to the grid so wiring stays orthogonal-ish and readable
            return QPointF(round(value.x() / GRID) * GRID,
                           round(value.y() / GRID) * GRID)
        if change == QGraphicsObject.ItemPositionHasChanged:
            self.comp.x = self.pos().x()
            self.comp.y = self.pos().y()
            scene = self.scene()
            if scene is not None and hasattr(scene, "wires_changed"):
                scene.wires_changed(self)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            scene = self.scene()
            if scene is not None and hasattr(scene, "begin_component_drag"):
                scene.begin_component_drag(self)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene is not None and hasattr(scene, "end_component_drag"):
            scene.end_component_drag(self)

    def mouseDoubleClickEvent(self, event):
        self.editValueRequested.emit(self)
        event.accept()

    def contextMenuEvent(self, event):
        self.menuRequested.emit(self, event.screenPos())
        event.accept()


# --------------------------------------------------------------------------
# Wires
# --------------------------------------------------------------------------
class WireItem(QGraphicsPathItem):
    """Orthogonal wire between two (comp_id, pin_name) endpoints."""

    def __init__(self, from_ref, to_ref):
        super().__init__()
        self.from_ref = tuple(from_ref)
        self.to_ref = tuple(to_ref)
        self.setPen(QPen(WIRE_BLUE, 2.0))
        self.setZValue(-1)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setToolTip(f"{from_ref[0]}.{from_ref[1]} -> {to_ref[0]}.{to_ref[1]}")

    def refresh(self, pin_lookup):
        a = pin_lookup.get(self.from_ref)
        b = pin_lookup.get(self.to_ref)
        if a is None or b is None:
            return
        p0, p1 = a.scenePos(), b.scenePos()
        path = QPainterPath(p0)
        if abs(p0.y() - p1.y()) < 0.5:
            path.lineTo(p1)
        else:
            mid_x = (p0.x() + p1.x()) / 2.0
            path.lineTo(QPointF(mid_x, p0.y()))
            path.lineTo(QPointF(mid_x, p1.y()))
            path.lineTo(p1)
        self.setPath(path)