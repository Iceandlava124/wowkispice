import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication

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
dpr = img.devicePixelRatio()
margin = int((getattr(view, "RULER", 22) + 8) * dpr)
print("factor", os.environ.get("QT_SCALE_FACTOR"), "img", w, h, "dpr", dpr, "margin", margin)
for thr in (3, 6, 14):
    cols = []
    for x in range(margin, w - margin):
        hits = 0
        for y in range(margin, h - margin, 2):
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
    print("thr", thr, "ncols", len(cols), "nruns", len(runs),
          "median gap", gaps[len(gaps)//2] if gaps else None, "gaps", gaps[:14])
win.close()
