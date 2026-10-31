"""
test_datasheet_symbols.py - datasheet diagrams and the square-with-pins
fallback for the schematic editor's symbol layer.

Body precedence under test (ui/schematic_items.draw_symbol):
1. datasheets/<TYPE>.png exists -> the datasheet's own diagram is drawn.
2. a type that declares pins but has no dedicated drawing -> a plain
   square with each pin stubbed to the body edge (not the "?" box).
3. a type with no pin data at all -> the honest "?" box (unchanged).
4. tools/extract_datasheet_img.py copies images out of a datasheet PDF,
   names them <PREFIX>.png for the editor's convention, and copies
   nothing (exit-1 path) when the PDF has no extractable images.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QApplication

import ui.schematic_items as si
import ui.schematic_symbols as sym
from tools.extract_datasheet_img import extract_images, main

INK_SUM = 0xD6 + 0xDD + 0xE5          # INK line colour brightness
IMG_RED = 300                          # red datasheet pixels are far brighter


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _paint(comp_type, size=240):
    """Render a symbol body centred on a black canvas; returns the QImage."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(QColor("#000000"))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(size / 2.0, size / 2.0)
    si.draw_symbol(painter, comp_type)
    painter.end()
    return img


def _sum_at(img, x, y):
    px = img.pixelColor(120 + int(x), 120 + int(y))
    return px.red() + px.green() + px.blue()


def _count_color(img, pred, step=2):
    hits = 0
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            if pred(img.pixelColor(x, y)):
                hits += 1
    return hits


# ------------------------------------------------------------ image branch

def test_datasheet_image_is_drawn_when_the_file_exists(app, tmp_path,
                                                       monkeypatch):
    """datasheets/R.png wins over the hand-drawn resistor."""
    Image.new("RGB", (60, 40), (255, 0, 0)).save(tmp_path / "R.png")
    monkeypatch.setattr(si, "DATASHEET_DIR", str(tmp_path))
    si.clear_datasheet_cache()
    try:
        assert si.datasheet_image_path("R") == str(tmp_path / "R.png")
        img = _paint("R")
        reds = _count_color(img, lambda c: c.red() > 200 and c.green() < 60
                            and c.blue() < 60, step=1)
        # The image is fitted into R's extent (100x52 minus 6-unit margins),
        # so several hundred red pixels must land on the canvas.
        assert reds > 500, reds
    finally:
        si.clear_datasheet_cache()


def test_without_a_datasheet_the_dedicated_symbol_still_draws(app):
    """No datasheets/R.png anywhere -> the zigzag resistor, zero image pixels."""
    si.clear_datasheet_cache()
    assert si.datasheet_image_path("R") is None
    img = _paint("R")
    reds = _count_color(img, lambda c: c.red() > 200 and c.green() < 60
                        and c.blue() < 60, step=1)
    assert reds == 0, reds
    assert _sum_at(img, -24, 0) > 0 or _sum_at(img, -21, -7) > 0


# ------------------------------------------------- square-with-pins fallback

def test_pinned_type_without_drawing_gets_square_with_pins(app):
    """A pins-declaring type with no dedicated drawing is a body with stubs."""
    sym.SYMBOLS["TESTBOX"] = {
        "label": "Generic Part", "prefix": "X", "value": "",
        "pins": [("1", -30, 0), ("2", 30, 0)],
        "extent": (-50, -26, 100, 52),
    }
    try:
        img = _paint("TESTBOX")
        # Stub lines run from each pin to the body edge: (-30 -> -20) crosses
        # x = -24, which the old 40x28 "?" box never reached.
        assert _sum_at(img, -24, 0) > INK_SUM / 2, "left pin not stubbed"
        assert _sum_at(img, 24, 0) > INK_SUM / 2, "right pin not stubbed"
        # The body top edge sits above the old box: miny-14 = -14 for y=0 pins
        # (box height 28); assert the body outline is drawn at its left edge.
        assert _sum_at(img, -20, 0) > 0, "body edge missing"
    finally:
        sym.SYMBOLS.pop("TESTBOX", None)


def test_type_without_pins_keeps_the_question_box(app):
    sym.SYMBOLS["NOBOX"] = {
        "label": "No Pins", "prefix": "X", "value": "",
        "pins": [], "extent": (-40, -26, 80, 52),
    }
    try:
        img = _paint("NOBOX")
        assert _sum_at(img, -20, 0) > 0, "box outline missing"
        assert _sum_at(img, -30, 0) == 0, "pins drawn for a pinless type"
    finally:
        sym.SYMBOLS.pop("NOBOX", None)


def test_builtin_boards_still_take_the_dedicated_board_drawing(app):
    """Regression: footprint boards keep the notched board body."""
    img = _paint("ESP32S3")
    # Board body spans x = +/-58 with stubs out to the pins at +/-70.
    assert _sum_at(img, -64, 0) > 0, "board pin stub missing"


# ----------------------------------------------------------------- extractor

def _make_pdf_with_image(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    fig = plt.figure(figsize=(2, 2))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(np.linspace(0, 1, 96).reshape(8, 12))
    ax.axis("off")
    fig.savefig(str(path), format="pdf")
    plt.close(fig)
    return str(path)


def test_extractor_copies_the_image_with_the_component_prefix(tmp_path):
    pdf = _make_pdf_with_image(tmp_path / "part.pdf")
    out = tmp_path / "out"
    written = extract_images(pdf, str(out), prefix="TESTPART")
    assert written, "no image extracted from a matplotlib PDF"
    target = out / "TESTPART.png"
    assert str(target) in written
    with Image.open(target) as im:
        assert im.size[0] > 0 and im.size[1] > 0


def test_extractor_copies_nothing_for_a_pdf_without_images(tmp_path):
    from pypdf import PdfWriter
    blank = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with open(blank, "wb") as fh:
        writer.write(fh)
    out = tmp_path / "out2"
    assert extract_images(str(blank), str(out)) == []
    # CLI contracts: exit 1 for "no images" and for a missing file.
    assert main([str(blank), "-o", str(out)]) == 1
    assert main([str(tmp_path / "missing.pdf")]) == 1
    assert not os.path.isdir(out) or not os.listdir(out)


def test_cli_roundtrip_exit_zero_with_prefix(tmp_path):
    pdf = _make_pdf_with_image(tmp_path / "part2.pdf")
    out = tmp_path / "out3"
    assert main([pdf, "-o", str(out), "--prefix", "CLIPART"]) == 0
    assert (out / "CLIPART.png").is_file()
