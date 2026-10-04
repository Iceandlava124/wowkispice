"""Check the vector glyph set renders real ink: every glyph must have visible
pixels inside the frame and must not bleed to the edge. Catches a blank path,
a path drawn outside the unit square, or a colour that matches the background.

Development aid: `python tools/check_icons.py`"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication                # noqa: E402

from ui import icons                                     # noqa: E402

SIZE = 64
MIN_INK = 0.004          # fraction of pixels - below this the glyph is a speck
MAX_INK = 0.55           # above this it is a blob, not an icon
EDGE = 0.02              # ink this close to the frame is drawn off-centre


def main():
    QApplication.instance() or QApplication([])
    bad = []
    detail = []
    for name in sorted(icons.GLYPHS):
        img = icons.raw_image(name, "#ffffff", SIZE)
        total = SIZE * SIZE
        ink = 0
        minx = miny = SIZE
        maxx = maxy = -1
        for y in range(SIZE):
            for x in range(SIZE):
                if img.pixelColor(x, y).alpha() > 16:
                    ink += 1
                    minx, maxx = min(minx, x), max(maxx, x)
                    miny, maxy = min(miny, y), max(maxy, y)
        frac = ink / total
        problems = []
        detail.append((name, ink, frac))
        if frac < MIN_INK:
            problems.append(f"blank or nearly blank ({frac:.4f})")
        if frac > MAX_INK:
            problems.append(f"solid blob ({frac:.4f})")
        if maxx < 0:
            problems.append("nothing drawn")
        else:
            if minx < SIZE * EDGE or miny < SIZE * EDGE:
                problems.append(f"touches top/left edge ({minx},{miny})")
            if maxx > SIZE * (1 - EDGE) or maxy > SIZE * (1 - EDGE):
                problems.append(f"touches bottom/right edge ({maxx},{maxy})")
        if problems:
            bad.append((name, problems))
    for name, problems in bad:
        print(f"FAIL {name}: {'; '.join(problems)}")
    for name, ink, frac in sorted(detail, key=lambda d: d[2]):
        print(f"  {name:<10} ink {ink:6d}  {frac:6.3%}")
    print(f"{len(icons.GLYPHS) - len(bad)}/{len(icons.GLYPHS)} glyphs pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
