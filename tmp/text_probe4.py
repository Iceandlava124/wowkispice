import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication, QLabel
app = QApplication(sys.argv[:1])

def hist(img):
    counts = {}
    for y in range(img.height()):
        for x in range(img.width()):
            v = img.pixel(x, y)
            counts[v] = counts.get(v, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:5]

lab = QLabel("Hxg 0123")
lab.setStyleSheet("color: #000000; background: #ffffff;")
lab.resize(300, 64)
lab.show(); app.processEvents()
img = lab.grab().toImage()
print("styled label:", img.width(), img.height(), [(hex(k), n) for k, n in hist(img)])

lab2 = QLabel("Hxg 0123")
lab2.resize(300, 64)
lab2.show(); app.processEvents()
img2 = lab2.grab().toImage()
print("plain label:", img2.width(), img2.height(), [(hex(k), n) for k, n in hist(img2)])

from PyQt5.QtGui import QPainter, QPixmap, QFont
pm = QPixmap(300, 64); pm.fill(Qt.white) if False else None
from PyQt5.QtCore import Qt
pm = QPixmap(300, 64); pm.fill(Qt.white)
p = QPainter(pm); p.setPen(Qt.black); p.setFont(QFont("Helvetica", 12))
p.drawText(10, 40, "Hxg 0123"); p.end()
print("painter text:", [(hex(k), n) for k, n in hist(pm.toImage())])
