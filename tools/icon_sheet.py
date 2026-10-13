"""
icons.py - vector toolbar icons, drawn at runtime.

No .png/.svg files ship with the repo: every icon is a QPainterPath painted at
4x and scaled down, which keeps it crisp at any DPI and means a theme change
re-colours the whole toolbar by passing a different pen colour.
"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QColor, QIcon, QImage, QPainter, QPainterPath, QPen,
                         QPixmap, QPolygonF)

_SUPERSAMPLE = 4
SIZE = 32


def _pen(p, w, color):
    p.setPen(QPen(color, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)


def _poly(points, close=True):
    """QPainterPath.lineTo() returns None in PyQt5, so paths are built by
    hand rather than by chaining. Every glyph below uses these two."""
    path = QPainterPath(QPointF(*points[0]))
    for pt in points[1:]:
        path.lineTo(QPointF(*pt))
    if close:
        path.closeSubpath()
    return path


def _pts(points, close=False):
    """drawPolyline() wants a QPolygonF, not a QPainterPath."""
    pts = [QPointF(*pt) for pt in points]
    if close:
        pts.append(pts[0])
    return QPolygonF(pts)


def _curve(start, segments, close=False):
    """segments: [(c1, c2, end), ...] with each point an (x, y) pair."""
    path = QPainterPath(QPointF(*start))
    for c1, c2, end in segments:
        path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*end))
    if close:
        path.closeSubpath()
    return path


def _dot(p, x, y, r, color):
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(x, y), r, r)
    p.setBrush(Qt.NoBrush)


# --------------------------------------------------------------------------
# Each glyph draws inside the unit square, origin top-left, y down.
# --------------------------------------------------------------------------
def _run(p, c):
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawPath(_poly([(0.30, 0.16), (0.84, 0.50), (0.30, 0.84)]))


def _stop(p, c):
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawRoundedRect(QRectF(0.26, 0.26, 0.48, 0.48), 0.06, 0.06)


def _cancel(p, c):
    """The Esc affordance: a ring with a slash - 'stop what you were doing'."""
    _pen(p, 0.09, c)
    p.drawEllipse(QRectF(0.18, 0.18, 0.64, 0.64))
    p.drawLine(QPointF(0.37, 0.37), QPointF(0.63, 0.63))


def _new(p, c):
    _pen(p, 0.09, c)
    p.drawPolyline(_pts([(0.24, 0.12), (0.60, 0.12), (0.78, 0.30),
                          (0.78, 0.88), (0.24, 0.88), (0.24, 0.12)],
                         close=False))
    _pen(p, 0.07, c)
    p.drawLine(QPointF(0.60, 0.12), QPointF(0.60, 0.30))
    p.drawLine(QPointF(0.60, 0.30), QPointF(0.78, 0.30))


def _open(p, c):
    _pen(p, 0.09, c)
    p.drawPath(_poly([(0.14, 0.82), (0.14, 0.26), (0.40, 0.26), (0.48, 0.38),
                      (0.86, 0.38), (0.86, 0.82)]))


def _save(p, c):
    _pen(p, 0.09, c)
    p.drawRoundedRect(QRectF(0.18, 0.18, 0.64, 0.64), 0.06, 0.06)
    _pen(p, 0.08, c)
    p.drawRect(QRectF(0.34, 0.18, 0.32, 0.26))
    p.drawRect(QRectF(0.30, 0.56, 0.40, 0.26))


def _export(p, c):
    _pen(p, 0.09, c)
    p.drawRoundedRect(QRectF(0.16, 0.42, 0.52, 0.42), 0.05, 0.05)
    p.drawLine(QPointF(0.50, 0.68), QPointF(0.50, 0.16))
    p.drawPolyline(_pts([(0.32, 0.34), (0.50, 0.14), (0.68, 0.34)],
                         close=False))


def _undo(p, c):
    _pen(p, 0.09, c)
    p.drawArc(QRectF(0.24, 0.22, 0.56, 0.56), 30 * 16, 250 * 16)
    p.drawPolyline(_pts([(0.22, 0.44), (0.22, 0.22), (0.44, 0.24)],
                         close=False))


def _redo(p, c):
    p.save()
    p.translate(1.0, 0.0)
    p.scale(-1.0, 1.0)
    _undo(p, c)
    p.restore()


def _delete(p, c):
    _pen(p, 0.09, c)
    p.drawLine(QPointF(0.20, 0.28), QPointF(0.80, 0.28))
    p.drawPolyline(_pts([(0.38, 0.20), (0.62, 0.20)], close=False))
    p.drawPolyline(_pts([(0.28, 0.28), (0.33, 0.84), (0.67, 0.84),
                          (0.72, 0.28)], close=False))
    _pen(p, 0.06, c)
    p.drawLine(QPointF(0.44, 0.40), QPointF(0.44, 0.72))
    p.drawLine(QPointF(0.56, 0.40), QPointF(0.56, 0.72))


def _rotate(p, c):
    _pen(p, 0.09, c)
    p.drawArc(QRectF(0.24, 0.24, 0.54, 0.54), 60 * 16, 260 * 16)
    p.drawPolyline(_pts([(0.78, 0.20), (0.80, 0.42), (0.58, 0.40)],
                         close=False))


def _label(p, c):
    _pen(p, 0.09, c)
    p.drawPath(_poly([(0.16, 0.50), (0.52, 0.14), (0.88, 0.50),
                      (0.52, 0.86)]))
    _dot(p, 0.48, 0.50, 0.07, c)


def _waveform(p, c):
    _pen(p, 0.09, c)
    p.drawPath(_curve((0.08, 0.50), [
        ((0.26, 0.10), (0.34, 0.90), (0.52, 0.50)),
        ((0.70, 0.12), (0.80, 0.88), (0.94, 0.48)),
    ]))


def _fft(p, c):
    for i, h in enumerate((0.26, 0.48, 0.74, 0.44, 0.30)):
        x = 0.16 + i * 0.17
        _pen(p, 0.09, c)
        p.drawLine(QPointF(x, 0.86), QPointF(x, 0.86 - h))


def _bode(p, c):
    _pen(p, 0.09, c)
    p.drawLine(QPointF(0.10, 0.16), QPointF(0.10, 0.88))
    p.drawLine(QPointF(0.10, 0.88), QPointF(0.92, 0.88))
    path = _curve((0.16, 0.72), [((0.42, 0.72), (0.52, 0.20), (0.88, 0.20))])
    p.drawPath(path)


def _cursors(p, c):
    _pen(p, 0.08, c)
    p.drawLine(QPointF(0.36, 0.08), QPointF(0.36, 0.92))
    p.drawPolyline(_pts([(0.36, 0.08), (0.26, 0.22), (0.46, 0.22)],
                         close=False))
    p.drawPolyline(_pts([(0.36, 0.92), (0.26, 0.78), (0.46, 0.78)],
                         close=False))
    p.drawLine(QPointF(0.68, 0.30), QPointF(0.68, 0.70))
    p.drawPolyline(_pts([(0.68, 0.70), (0.58, 0.60), (0.78, 0.60)],
                         close=False))


def _fit(p, c):
    _pen(p, 0.09, c)
    for x, y, dx, dy in ((0.14, 0.14, 1, 1), (0.86, 0.14, -1, 1),
                         (0.14, 0.86, 1, -1), (0.86, 0.86, -1, -1)):
        p.drawLine(QPointF(x, y), QPointF(x + dx * 0.22, y))
        p.drawLine(QPointF(x, y), QPointF(x, y + dy * 0.22))


def _zoom(p, c, plus=True):
    _pen(p, 0.09, c)
    p.drawEllipse(QPointF(0.44, 0.44), 0.28, 0.28)
    p.drawLine(QPointF(0.65, 0.65), QPointF(0.90, 0.90))
    if plus:
        p.drawLine(QPointF(0.30, 0.44), QPointF(0.58, 0.44))
        p.drawLine(QPointF(0.44, 0.30), QPointF(0.44, 0.58))
    else:
        p.drawLine(QPointF(0.30, 0.44), QPointF(0.58, 0.44))


def _zoom_out(p, c):
    _zoom(p, c, plus=False)


def _grid(p, c):
    _pen(p, 0.07, c)
    for i in (0.22, 0.46, 0.70):
        p.drawLine(QPointF(i, 0.14), QPointF(i, 0.86))
        p.drawLine(QPointF(0.14, i), QPointF(0.86, i))


def _theme(p, c):
    _pen(p, 0.09, c)
    p.drawEllipse(QPointF(0.50, 0.50), 0.36, 0.36)
    p.save()
    p.setClipRect(QRectF(0.50, 0.14, 0.36, 0.72))
    p.fillPath(_disc(0.50, 0.50, 0.36), c)
    p.restore()


def _disc(x, y, r):
    path = QPainterPath()
    path.addEllipse(QPointF(x, y), r, r)
    return path


def _chip(p, c):
    _pen(p, 0.09, c)
    p.drawRoundedRect(QRectF(0.26, 0.26, 0.48, 0.48), 0.05, 0.05)
    _pen(p, 0.07, c)
    for t in (0.36, 0.50, 0.64):
        p.drawLine(QPointF(0.26, t), QPointF(0.14, t))
        p.drawLine(QPointF(0.74, t), QPointF(0.86, t))
        p.drawLine(QPointF(t, 0.26), QPointF(t, 0.14))
        p.drawLine(QPointF(t, 0.74), QPointF(t, 0.86))


def _table(p, c):
    _pen(p, 0.09, c)
    p.drawRoundedRect(QRectF(0.14, 0.20, 0.72, 0.60), 0.04, 0.04)
    _pen(p, 0.07, c)
    p.drawLine(QPointF(0.14, 0.40), QPointF(0.86, 0.40))
    p.drawLine(QPointF(0.14, 0.60), QPointF(0.86, 0.60))
    p.drawLine(QPointF(0.42, 0.20), QPointF(0.42, 0.80))


def _pdf(p, c):
    _pen(p, 0.09, c)
    p.drawRoundedRect(QRectF(0.22, 0.12, 0.56, 0.76), 0.05, 0.05)
    _pen(p, 0.09, c)
    p.drawPath(_curve((0.34, 0.62), [
        ((0.34, 0.48), (0.34, 0.42), (0.46, 0.42)),
        ((0.56, 0.42), (0.56, 0.56), (0.44, 0.56)),
    ]))
    p.drawLine(QPointF(0.34, 0.56), QPointF(0.34, 0.62))


def _image(p, c):
    _pen(p, 0.09, c)
    p.drawRoundedRect(QRectF(0.14, 0.20, 0.72, 0.60), 0.05, 0.05)
    _dot(p, 0.34, 0.38, 0.06, c)
    p.drawPolyline(_pts([(0.18, 0.74), (0.40, 0.50), (0.58, 0.66),
                          (0.68, 0.56), (0.84, 0.74)], close=False))


def _help(p, c):
    _pen(p, 0.09, c)
    p.drawEllipse(QPointF(0.50, 0.50), 0.38, 0.38)
    p.drawPath(_curve((0.36, 0.38), [
        ((0.38, 0.24), (0.66, 0.24), (0.64, 0.42)),
        ((0.62, 0.56), (0.50, 0.54), (0.50, 0.64)),
    ]))
    _dot(p, 0.50, 0.76, 0.06, c)


def _warning(p, c):
    _pen(p, 0.09, c)
    p.drawPath(_poly([(0.50, 0.14), (0.92, 0.84), (0.08, 0.84)]))
    _pen(p, 0.09, c)
    p.drawLine(QPointF(0.50, 0.40), QPointF(0.50, 0.60))
    _dot(p, 0.50, 0.72, 0.05, c)


GLYPHS = {
    "run": _run, "stop": _stop, "cancel": _cancel,
    "new": _new, "open": _open, "save": _save,
    "export": _export, "undo": _undo, "redo": _redo, "delete": _delete,
    "rotate": _rotate, "label": _label, "waveform": _waveform, "fft": _fft,
    "bode": _bode, "cursors": _cursors, "fit": _fit, "zoom_in": _zoom,
    "zoom_out": _zoom_out, "grid": _grid, "theme": _theme, "chip": _chip,
    "table": _table, "pdf": _pdf, "image": _image, "help": _help,
    "warning": _warning,
}


# --------------------------------------------------------------------------
# The editor demands a real PNG for every glyph above, so the unified icon
# sheet is built from the same paths rather than being a separate artwork file.
# --------------------------------------------------------------------------


def _make_image():
    image = QImage(SIZE * _SUPERSAMPLE, SIZE * _SUPERSAMPLE,
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(_SUPERSAMPLE)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(_SUPERSAMPLE, _SUPERSAMPLE)
    for name, fn in GLYPHS.items():
        fn(p, QColor("#d6dde5"))
    p.end()
    return image


def _save_sheet(path, cols=8):
    from PyQt5.QtGui import QImageWriter
    image = _make_image()
    writer = QImageWriter(path, "png")
    writer.setQuality(100)
    writer.write(image)
    return path


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "tools/icon_sheet.png"
    _save_sheet(out)
