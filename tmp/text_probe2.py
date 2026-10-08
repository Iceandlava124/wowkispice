import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QPixmap, QPainter, QImage
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv[:1])
pm = QPixmap(300, 64)
pm.fill(Qt.white)
p = QPainter(pm)
print("painter active:", p.isActive())
p.setPen(Qt.black)
p.fillRect(QRectF(0, 0, 50, 20), Qt.black)
ret = p.drawText(QRectF(0, 0, 300, 64), int(Qt.AlignVCenter | Qt.AlignLeft), "Hxg 0123")
print("ret", ret)
p.end()
img = pm.toImage()
print("format", img.format(), "size", img.width(), img.height())
print("pixel(10,10)", hex(img.pixel(10, 10)), "pixel(150,32)", hex(img.pixel(150, 32)))
counts = {}
for y in range(img.height()):
    for x in range(img.width()):
        v = img.pixel(x, y)
        counts[v] = counts.get(v, 0) + 1
top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
print("top pixels:", [(hex(k), n) for k, n in top])
