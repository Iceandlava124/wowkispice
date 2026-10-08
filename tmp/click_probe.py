import os, sys, traceback
sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("WOSP_SETTINGS_DIR", os.path.join(os.environ.get("TEMP", "."), "wosp-click-probe"))
from PyQt5.QtCore import QPointF, Qt, QPoint
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from ui import theme
theme.use_settings_dir(os.path.join(os.environ.get("TEMP", "."), "wosp-click-probe2"))
from ui.schematic_editor import SchematicEditor

def excepthook(t, v, tb):
    print("SLOT EXCEPTION:", t.__name__, v)
sys.excepthook = excepthook

win = SchematicEditor()
win.show(); app.processEvents()
scene = win.scene
scene.place_component("V", QPointF(0, 0))
scene.place_component("R", QPointF(80, 0))
scene.place_component("C", QPointF(160, 0))
scene.place_component("GND", QPointF(160, 80))
for a, b in (("V1", "+"), ("R1", "1"), ("V1", "-"), ("GND1", "1"),
             ("R1", "2"), ("C1", "1"), ("C1", "2"), ("GND1", "1")):
    scene.pin_clicked(a, b)
win.duration_box.setValue(1.0)
win.tstep_box.setValue(5.0)
win.run_simulation()
print("curves:", [c.name() for c in win._curves])
print("time range (s):", win._last_time[0], win._last_time[-1])

vb = win.plot.getViewBox()
# find pixel position of a mid-data point on the plot widget
mid_t_ms = (win._last_time[len(win._last_time)//2]) * 1000.0
scene_pt = vb.mapViewToScene(QPointF(mid_t_ms, 1.0))
pix = vb.mapFromScene(scene_pt)   # ViewBox coords
print("target data t(ms):", mid_t_ms, "-> viewbox pixel:", pix.x(), pix.y())
vp = win.plot.viewport()
# convert ViewBox coords to plot viewport coords: ViewBox usually fills plot

win.plot.setFocus()
QTest.mouseClick(win.plot.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(int(pix.x()), int(pix.y())))
app.processEvents()
print("_click_points:", getattr(win, "_click_points", None))
print("_click_points_view:", getattr(win, "_click_points_view", None))
print("measure:", win.measure_label.text()[:120])
win.close()
