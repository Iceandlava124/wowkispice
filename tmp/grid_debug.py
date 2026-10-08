import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QColor

app = QApplication(sys.argv[:1])
from ui import theme
from ui.schematic_editor import SchematicEditor
from ui.schematic_scene import GRID

win = SchematicEditor()
win.show()
app.processEvents()
view = win.view
img = view.grab().toImage()
w, h = img.width(), img.height()
bg = theme.current().canvas
br, bgc, bb = (int(bg[1:3],16), int(bg[3:5],16), int(bg[5:7],16))
print("factor", os.environ.get("QT_SCALE_FACTOR"), "img", w, h, "dpr", img.devicePixelRatio(), "bg", bg, "GRID", GRID, "RULER", getattr(view,'RULER',None))
# sample some pixels across a horizontal line where dots should be
transform = abs(view.transform().m11())
print("transform", transform)
# find distinct colors histogram
from collections import Counter
cnt = Counter()
for y in range(30, h-30, 7):
    for x in range(30, w-30, 1):
        c = img.pixel(x, y)
        cnt[hex(c)] += 1
print("top colors:", cnt.most_common(8))
# dot column counts with several thresholds
for thr in (3, 6, 14):
    cols = []
    for x in range(30, w-30):
        hits = 0
        for y in range(30, h-30, 2):
            c = img.pixel(x, y)
            r, g, b = (c>>16)&0xFF, (c>>8)&0xFF, c&0xFF
            if abs(r-br) > thr or abs(g-bgc) > thr or abs(b-bb) > thr:
                hits += 1
        if hits: cols.append(x)
    runs = []
    if cols:
        start = prev = cols[0]
        for x in cols[1:]:
            if x - prev > 1:
                runs.append(start); start = x
            prev = x
        runs.append(start)
    gaps = sorted(runs[i+1]-runs[i] for i in range(len(runs)-1))
    print("thr", thr, "ncols", len(cols), "nruns", len(runs), "gaps", gaps[:12])
win.close()
