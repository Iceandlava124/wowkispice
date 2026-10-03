"""
screenshot_editor.py - Render the schematic editor offscreen for docs/verification.

Builds a small demo circuit, runs it through the real ngspice solver, grabs the
window to PNG and reports how much was actually drawn (ink pixel count), so a
blank or broken render fails loudly instead of silently producing a nice-looking
empty image.

    python tools/screenshot_editor.py [output.png]
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QApplication

from ui.schematic_editor import SchematicEditor


def build_demo(window):
    """12 V source -> 2.2k -> node 'out' with 100nF to ground, plus a load resistor."""
    scene = window.scene
    for comp_type, x, y in (("V", -60, 0), ("R", 20, 0), ("C", 100, 0),
                            ("R", 100, 60), ("GND", 100, 120), ("MCU", -60, 120)):
        scene.place_component(comp_type, QPointF(x, y))
    for a, b in (("V1:+", "R1:1"), ("V1:-", "GND1:1"),
                 ("R1:2", "C1:1"), ("C1:2", "GND1:1"),
                 ("R1:2", "R2:1"), ("R2:2", "GND1:1")):
        ca, pa = a.split(":")
        cb, pb = b.split(":")
        scene.pin_clicked(ca, pa)
        scene.pin_clicked(cb, pb)


def count_ink(pixmap):
    """Rough count of non-white pixels: proof the canvas actually rendered."""
    image = pixmap.toImage()
    ink = 0
    step = 4
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            if image.pixelColor(x, y).lightness() < 200:
                ink += 1
    return ink


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "docs/editor-demo.png"
    app = QApplication.instance() or QApplication([])

    window = SchematicEditor()
    window.resize(1400, 860)
    build_demo(window)
    window.tstep_box.setValue(10.0)
    window.duration_box.setValue(5.0)
    window.run_simulation()
    window.show()
    app.processEvents()

    curves = window.plot.listDataItems()
    netlist, _nets, warns = window.model.compile_netlist()
    print("netlist:")
    print("\n".join(netlist))
    print("warnings:", warns)
    print("plotted curves:", len(curves))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    pixmap = window.grab()
    pixmap.save(out_path)
    ink = count_ink(pixmap)
    print(f"saved {out_path} ({pixmap.width()}x{pixmap.height()}), ink pixels sampled: {ink}")

    if not curves:
        print("FAIL: no waveform traces were plotted")
        return 1
    if ink < 1000:
        print("FAIL: window rendered essentially blank")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())