import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QPixmap, QPainter, QFont, QFontDatabase
from PyQt5.QtWidgets import QApplication, QLabel

app = QApplication(sys.argv[:1])
f = app.font()
print("app font:", f.family(), "pointSizeF", f.pointSizeF(), "pixelSize", f.pixelSize())
families = QFontDatabase().families()[:10]
print("families:", families)

def ink(font, text="Hxg 0123"):
    pm = QPixmap(300, 64); pm.fill(Qt.white)
    p = QPainter(pm); p.setFont(font); p.setPen(Qt.black)
    p.drawText(QRectF(0, 0, 300, 64), int(Qt.AlignVCenter | Qt.AlignLeft), text)
    p.end()
    img = pm.toImage()
    return sum(1 for y in range(64) for x in range(300) if img.pixel(x, y) != 0xFFFFFFFF)

print("app font ink:", ink(f))
print("default QFont ink:", ink(QFont()))
print("Sans Serif 14 ink:", ink(QFont("Sans Serif", 14)))
if families:
    print("first family ink:", ink(QFont(families[0], 14)))
# label widget render as control
lab = QLabel("Hxg 0123")
lab.resize(300, 40)
lab.show()
app.processEvents()
img = lab.grab().toImage()
print("label ink:", sum(1 for y in range(img.height()) for x in range(img.width())
                        if img.pixel(x, y) not in (0xFFFFFFFF, 0x00FFFFFF)))
