"""Probe the editor's HiDPI numbers at the current QT_SCALE_FACTOR.

Run by TestHiDpiConsistency (tests/test_ui_polish.py) as a subprocess three
times - QT_SCALE_FACTOR=1, 1.5 and 2 - and prints one JSON line:

    PROBE {...}

Measurements gathered here (the assertions live in the test):

  screen_dpr / widget_dpr   the OS display scale actually in effect
  icon_baseline_w           toolbar pixmap with AA_UseHighDpiPixmaps OFF -
                            the shipped-bug measurement: a flat 18 device
                            pixels at every scale factor (upscaled/blurry)
  icon_fixed_w/_dpr         the same pixmap with the fix ON: 18 * factor
  text_widget_grab_w        device-pixel width of a 300-logical-px text
                            widget's grab: the surface real text renders
                            into (glyphs themselves cannot rasterise
                            headless - the offscreen font DB is empty)
  grid_device_measured      dot pitch in device pixels found by clustering
                            the painted dot columns of a canvas screenshot
  grid_device_analytic      GRID * zoom * dpr, for cross-checking

Each scale factor needs its own QApplication (Qt fixes scaling at app
construction), hence the subprocess.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Never touch the user's real profile: closing the editor saves a session.
os.environ.setdefault("WOSP_SETTINGS_DIR",
                      tempfile.mkdtemp(prefix="wosp-hidpi-probe-"))

from PyQt5.QtCore import Qt           # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402


def _text_widget_grab_w(app):
    """Device-pixel width of a 300-logical-pixel-wide text widget's grab.

    Headless caveat: the offscreen platform's font database has no families,
    so glyphs do not rasterise anywhere in this environment (QPainter.drawText
    and QLabel both draw zero ink - measured). What CAN be measured is the
    surface real text renders into: a widget grab is the device-pixel buffer
    behind the widget, and it must be 300 * dpr wide at 150/200% - that is
    exactly why an on-screen label's glyphs come out scaled, with QFontMetrics
    staying constant in logical pixels (font_h in the output).
    """
    from PyQt5.QtWidgets import QLabel
    label = QLabel("Hxg 0123")
    label.setFont(app.font())
    label.setStyleSheet("color: #000000; background: #ffffff;")
    label.resize(300, 64)
    label.show()
    app.processEvents()
    width = label.grab().toImage().width()
    label.close()
    return width


def _grid_spacing(img):
    """Dot pitch in device pixels, from the painted canvas itself.

    The grabbed image is in DEVICE pixels, so the logical ruler width has to
    be scaled too - otherwise the light ruler strips fall inside the scan
    region at 150/200% and every column "hits", hiding the dot pitch.
    """
    from ui import theme
    from ui.schematic_scene import GRID  # noqa: F401  (documented relationship)
    w, h = img.width(), img.height()
    dpr = img.devicePixelRatio()
    margin = int((22 + 8) * dpr)          # SchematicView.RULER + breathing room
    if w <= 2 * margin + 40 or h <= 2 * margin + 40:
        return None
    bg = theme.current().canvas
    br, bgc, bb = (int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16))
    cols = []
    for x in range(margin, w - margin):
        for y in range(margin, h - margin, 2):
            c = img.pixel(x, y)
            r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
            if abs(r - br) > 6 or abs(g - bgc) > 6 or abs(b - bb) > 6:
                cols.append(x)
                break
    if len(cols) < 4:
        return None
    # One dot spans several adjacent columns, so cluster them first: gaps
    # between raw columns would measure dot width, not grid pitch.
    runs = [cols[0]]
    prev = cols[0]
    for x in cols[1:]:
        if x - prev > 1:
            runs.append(x)
        prev = x
    if len(runs) < 3:
        return None
    gaps = sorted(runs[i + 1] - runs[i] for i in range(len(runs) - 1))
    return gaps[len(gaps) // 2] or None


def main():
    app = QApplication(sys.argv[:1])
    from ui import theme                       # noqa: F401  (env applied)
    from ui.schematic_editor import SchematicEditor
    from ui.schematic_scene import GRID

    win = SchematicEditor()
    win.show()
    app.processEvents()

    # Toolbar icon: logical size requested, physical pixels actually rendered.
    # SchematicEditor.__init__ turns AA_UseHighDpiPixmaps on, so this first
    # query is the AFTER state; toggling the attribute off and re-querying
    # reproduces the BEFORE state (what shipped).
    toolbar = win.toolbar_run
    logical = toolbar.iconSize().width()
    run_act = toolbar.actions()[0]
    pm_fixed = run_act.icon().pixmap(logical, logical)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, False)
    pm_baseline = run_act.icon().pixmap(logical, logical)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    fixed_on = bool(app.testAttribute(Qt.AA_UseHighDpiPixmaps))

    pal_size = win.palette_list.iconSize().width()

    # Canvas grid: scene-space step -> device pixels at the current zoom.
    view = win.view
    transform = abs(view.transform().m11())
    dpr = float(win.devicePixelRatioF())
    grid_device = GRID * transform * dpr

    img = view.grab().toImage()
    spacing = _grid_spacing(img)
    text_w = _text_widget_grab_w(app)

    out = {
        "factor": float(os.environ.get("QT_SCALE_FACTOR", "1")),
        "screen_dpr": app.primaryScreen().devicePixelRatio(),
        "widget_dpr": dpr,
        "aa_fixed_on": fixed_on,
        "font_h": app.fontMetrics().height(),
        "toolbar_logical": logical,
        "palette_logical": pal_size,
        "icon_baseline_w": int(pm_baseline.width()),
        "icon_baseline_dpr": float(pm_baseline.devicePixelRatio()),
        "icon_fixed_w": int(pm_fixed.width()),
        "icon_fixed_dpr": float(pm_fixed.devicePixelRatio()),
        "text_widget_grab_w": text_w,
        "view_logical_w": view.width(),
        "view_transform": transform,
        "grid_device_analytic": grid_device,
        "grid_device_measured": spacing,
        "canvas_img_w": img.width(),
    }
    print("PROBE " + json.dumps(out))
    win.close()


if __name__ == "__main__":
    main()
