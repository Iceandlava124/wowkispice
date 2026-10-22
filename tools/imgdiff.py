#!/usr/bin/env python
"""imgdiff - simple image diff utilities.

Vendor of the legacy imgdiff functions used by tools/ui_parity.py:
read_png, to_width, gray, write_png, edges.  MIT licence (c) Marius Gedminas.
"""
import sys

try:
    from PIL import Image
except ImportError:
    import Image


def read_png(path):
    """Read a PNG file and return (width, height, rows) where rows is
    a 2D list of (r, g, b, a) tuples.

    Pillow's Image.getdata returns one flat sequence of pixels in row-major
    order. The old decoder sliced that flat list and then flipped the result
    vertically, so every consumer of read_png received rows that were the
    vertical mirror of what PIL actually stored. Fix the decoder once here so
    the whole toolchain shares a single, consistent origin.
    """
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    img.load()
    raw = list(img.getdata())
    rows = [list(raw[y * w:(y + 1) * w]) for y in range(h)]
    return w, h, rows


def to_width(img, width):
    """Resize an image (w, h, rows) to the given width, preserving
    aspect ratio.  Returns (w, h, rows)."""
    w, h, rows = img
    if w == width:
        return w, h, rows
    ratio = width / float(w)
    new_h = int(h * ratio)
    flat = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = rows[y][x]
            flat.append((r << 24) | (g << 16) | (b << 8) | a)
    img = Image.new("RGBA", (w, h))
    img.putdata(flat)
    img = img.resize((width, new_h), Image.LANCZOS)
    w2, h2 = img.size
    img.load()
    raw = list(img.getdata())
    rows2 = [list(raw[y * w2:(y + 1) * w2]) for y in range(h2)]
    return w2, h2, rows2


def gray(rows):
    """Convert a 2D grid of (r, g, b, a) rows to a 2D grid of
    grayscale values (0-255).  Returns a 2D list of ints."""
    out = []
    for row in rows:
        out.append([int(round(0.299 * r + 0.587 * g + 0.114 * b))
                    for r, g, b, a in row])
    return out


def write_png(path, w, h, rows):
    """Write a PNG file from (w, h, rows) where rows is a 2D list
    of (r, g, b, a) tuples. Accepts either 4-tuples or plain
    (r, g, b) triplets, so generated images can be written either way."""
    img = Image.new("RGBA", (w, h))
    flat = []
    for row in rows:
        for px in row:
            if len(px) == 4:
                r, g, b, a = px
            else:
                r, g, b = px
                a = 255
            flat.append((r << 24) | (g << 16) | (b << 8) | a)
    img.putdata(flat)
    img.save(path, "PNG")


def edges(gray, threshold):
    """Find edges in a grayscale grid using a simple Sobel-like
    operator.  Returns a 2D grid of 0/1 values (same dimensions
    as gray, with the last row/col being 0)."""
    h = len(gray)
    w = len(gray[0]) if h else 0
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            if y == h - 1 or x == w - 1:
                row.append(0)
                continue
            gx = abs(gray[y][x + 1] - gray[y][x - 1]) if x > 0 else 0
            gy = abs(gray[y + 1][x] - gray[y - 1][x]) if y > 0 else 0
            row.append(1 if (gx + gy) > threshold else 0)
        out.append(row)
    return out
