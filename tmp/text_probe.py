import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QPixmap, QPainter
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv[:1])
for dpr in (1.0, 1.5, 2.0):
    pm = QPixmap(int(300 * dpr), int(64 * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.white)
    p = QPainter(pm)
    p.setFont(app.font())
    p.setPen(Qt.black)
    rc = p.drawText(QRectF(0, 0, 300, 64), int(Qt.AlignVCenter | Qt.AlignLeft), "Hxg 0123")
    p.end()
    img = pm.toImage()
    rows = sum(1 for y in range(img.height())
               if any(img.pixel(x, y) != 0xFFFFFFFF for x in range(img.width())))
    print("dpr", dpr, "pm", pm.width(), pm.height(), "drawText ret", rc, "rows", rows)
# try without dpr metadata
pm = QPixmap(300, 64); pm.fill(Qt.white)
p = QPainter(pm); p.setFont(app.font()); p.setPen(Qt.black)
p.drawText(QRectF(0, 0, 300, 64), int(Qt.AlignVCenter | Qt.AlignLeft), "Hxg 0123"); p.end()
img = pm.toImage()
rows = sum(1 for y in range(img.height())
           if any(img.pixel(x, y) != 0xFFFFFFFF for x in range(img.width())))
print("no-dpr rows", rows)
# try DrawText without rect (point variant)
pm = QPixmap(300, 64); pm.fill(Qt.white)
p = QPainter(pm); p.setFont(app.font()); p.setPen(Qt.black)
p.drawText(10, 40, "Hxg 0123"); p.end()
img = pm.toImage()
rows = sum(1 for y in range(img.height())
           if any(img.pixel(x, y) != 0xFFFFFFFF for x in range(img.width())))
print("point-variant rows", rows)
