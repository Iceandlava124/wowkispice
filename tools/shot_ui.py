"""Render the editor offscreen to PNG, in either appearance, with a sample
circuit on the canvas. Development/documentation aid:
    python tools/shot_ui.py dark

A --canvas mode that grabs only the canvas view was tried and removed. It
emitted a 97x543 image: win.view measured 97 px wide inside a 1329 px parent.
That narrow view was NOT an offscreen artefact - it was a real layout fault,
where the Bode tab's unshrinkable control row set the whole right pane's
minimum width. It is fixed (see TestCanvasShare in tests/test_ui_polish.py)
and win.view now measures 681 px at 1600x980. A canvas-only grab is therefore
viable again; check win.view.width() before trusting one.

Both docs/editor-dark.png and docs/editor-light.png must be regenerated from the
same code. tools/ui_parity.py calibrates against that pair, and a half-updated
pair reads as a theme regression that does not exist.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QPointF                      # noqa: E402
from PyQt5.QtWidgets import QApplication              # noqa: E402

from ui import theme                                  # noqa: E402

SAMPLE_PARTS = (("V", (0, 0)), ("R", (90, 0)), ("C", (180, 0)),
                ("R", (270, 0)), ("C", (360, 0)), ("GND", (90, 90)),
                ("ESP32", (210, 190)))
SAMPLE_WIRES = (("V1", "+"), ("R1", "1"), ("R1", "2"), ("C1", "1"),
                ("C1", "2"), ("R2", "1"), ("R2", "2"), ("C2", "1"),
                ("C2", "2"), ("GND1", "1"), ("V1", "-"))


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "dark"
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        ROOT, "docs", f"editor-{name}.png")

    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app, name, persist=False)
    from ui.schematic_editor import SchematicEditor

    win = SchematicEditor()
    win.resize(1600, 980)
    win.show()
    app.processEvents()
    for comp_type, pos in SAMPLE_PARTS:
        win.scene.place_component(comp_type, QPointF(*pos))
    for a, b in SAMPLE_WIRES:
        win.scene.pin_clicked(a, b)
    win.scene.set_armed("D")              # show the armed-tool preview
    win.scene.move_ghost(QPointF(460, 130))
    win.view.fit_to_contents()
    app.processEvents()
    win.grab().save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()