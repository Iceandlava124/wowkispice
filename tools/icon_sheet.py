"""Render every vector glyph to one labelled contact sheet, for eyeballing the
icon set after an edit. Development aid: `python tools/icon_sheet.py`."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QRectF, Qt                     # noqa: E402
from PyQt5.QtGui import QColor, QPainter, QPixmap       # noqa: E402
from PyQt5.QtWidgets import QApplication                # noqa: E402

from ui import icons, theme                             # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "icon-sheet.png")
SIZE, PAD, COLS = 48, 8, 7


def main():
    app = QApplication.instance() or QApplication([])
    names = sorted(icons.GLYPHS)
    rows = (len(names) + COLS - 1) // COLS
    sheet = QPixmap(COLS * (SIZE + PAD) + PAD, rows * (SIZE + PAD + 14) + PAD)
    pal = theme.current()
    sheet.fill(QColor(pal.window))
    p = QPainter(sheet)
    p.setRenderHint(QPainter.Antialiasing, True)
    for i, name in enumerate(names):
        r, c = divmod(i, COLS)
        x = PAD + c * (SIZE + PAD)
        y = PAD + r * (SIZE + PAD + 14)
        p.drawPixmap(x, y, icons.pixmap(name, pal.text, SIZE))
        p.setPen(QColor(pal.dim))
        p.drawText(QRectF(x, y + SIZE, SIZE, 12),
                   Qt.AlignHCenter | Qt.AlignVCenter, name)
    p.end()
    sheet.save(OUT)
    print(f"{len(names)} glyphs -> {OUT}  ({sheet.width()}x{sheet.height()})")


if __name__ == "__main__":
    main()
