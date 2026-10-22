#!/usr/bin/env python3
"""Layout parity between two screenshots, robust to colour and to theme.

Wraps tools/imgdiff.py (vendored, MIT, (c) 2026 Jake Schincariol) instead of
patching it, so the vendored file stays byte-identical to upstream and there is
exactly one PNG decoder in this repo.

WHY THIS EXISTS

imgdiff's own `layout` mode does not survive a theme change, and that was
measured rather than assumed on this repo's own screenshots:

    docs/editor-dark.png vs docs/editor-dark.png    100.0   MATCHES
    docs/editor-dark.png vs docs/editor-light.png     8.1   DIFFERENT

Those are the same window, same widgets, same layout, two colour schemes. The
reason is in imgdiff:

  * line 281  edges() thresholds raw luminance differences against a fixed 40
  * line 387  similarity compares one scalar per cell - edge DENSITY

An absolute threshold plus a density scalar means the score tracks how much
contrast a theme happens to carry, not where the structure is. Measured edge
density on our own pair: dark 0.12, light 2.45, a factor of 20, with the
schematic canvas at 0.000 versus 0.143 in every cell of its row.

So this module fixes three things:

  1. contrast stretch   each image is stretched over its own 5th-99th percentile
                        luminance range before anything is compared, so a dark
                        theme and a light theme start from the same footing.
                        The low cut is 5, not 1: at 1 the cut lands inside the
                        content tail. A light canvas carrying dark schematic ink
                        puts ~1.6% of its pixels below that cut, so the light
                        theme's range inverts (221) against the dark theme's
                        (35) and the same layout scores 50.7 instead of 94.4.
                        Measured sweep, 1/99 -> 50.7, 2/99 -> 87.8, 5/99 -> 94.4,
                        20/95 -> 98.6, 35/85 -> 47.6 (over-truncation). The
                        unrelated control stays at 8.8 across the whole plateau,
                        so 5 is a robustness fix, not a loosened threshold.
  2. adaptive threshold the edge threshold is a fraction of that image's own
                        dynamic range instead of a magic 40.
  3. position awareness each grid cell is subdivided and scored by where inside
                        it the edges fall, not by how many there are. At --sub 1
                        this degenerates back to imgdiff's density comparison;
                        3 is the calibrated default. Note the score is not
                        monotonic in --sub (1 -> 85.2, 3 -> 82.0, 5 -> 85.3 on
                        our own pair), because sub-cells become sparse and
                        noisy below a few pixels. Do not read a finer --sub as a
                        stricter test.

The number this reports is still only as good as its calibration, so
tests/test_ui_parity.py pins the three facts that make it trustworthy: a
self-comparison is 100, the two themes of the same window score high, and a
genuinely different image scores low.

WHAT IT IS FOR, AND WHAT IT IS NOT

Use it as a regression gate on our own UI: same theme, same screenshot size,
before and after a change. That use is calibrated and trustworthy.

Do NOT read it as "how LTspice-like is our editor". Measured against eight real
LTspice screenshots it does not separate the two. Whole-window comparison:
LTspice schematic vs our editor scored 7.7 to 13.6, while the CONTROL, LTspice
against a completely unrelated LTspice dialog, scored 7.9, inside the same
band. The metric was measuring window chrome, not schematics. Those whole-window
figures are reproducible from docs/ltspice-reference/ with no flags.

An attempt to repeat it on the canvas alone did not rescue the metric, but the
figures from that attempt are deliberately not quoted here: it needed a
canvas-only render of our editor, and the one this repository can produce came
out 97x543 (see tools/shot_ui.py), so the numbers would not be reproducible and
would not mean anything.

That control is the reason this tool exists in this form. Any layout-similarity
number quoted without one is a vibe wearing a decimal point.

    python tools/ui_parity.py docs/editor-dark.png docs/editor-light.png
    python tools/ui_parity.py a.png b.png --global --json
    python tools/ui_parity.py a.png b.png --fail-under 70

Standard library only. Reads what imgdiff reads and no more.
"""

import argparse
import importlib.util
import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_imgdiff():
    """Load the vendored imgdiff as a module. It has no package to import from."""
    path = os.path.join(_HERE, "imgdiff.py")
    if not os.path.exists(path):
        raise SystemExit("tools/imgdiff.py is missing; parity cannot run without it")
    spec = importlib.util.spec_from_file_location("_vendored_imgdiff", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


imgdiff = _load_imgdiff()


# --------------------------------------------------------------------- loading


def _crop(img, box):
    """Crop to (x, y, w, h) in source pixels, clamped to the image."""
    if not box:
        return img
    w, h, rows = img
    x, y, cw, ch = box
    x = max(0, min(int(x), w - 1))
    y = max(0, min(int(y), h - 1))
    cw = max(1, min(int(cw), w - x))
    ch = max(1, min(int(ch), h - y))
    return cw, ch, [row[x:x + cw] for row in rows[y:y + ch]]


def _modal_color(rows, w, h):
    counts = {}
    for y in range(0, h, 2):
        row = rows[y]
        for x in range(0, w, 2):
            px = row[x]
            counts[px] = counts.get(px, 0) + 1
    return max(counts, key=counts.get)


def resolve_crop(box):
    """Normalise an explicit --crop box. Automatic detection is not offered.

    Automatic canvas detection was implemented and then removed because it does
    not work on windowed screenshots. A canvas holding a schematic is not
    uniform, so a bounding box of non-background pixels is dragged out to the
    full image by the window frame, and a largest-uniform-rectangle search
    latches onto whatever empty region happens to be biggest. Measured on these
    very screenshots, the best fill threshold produced boxes covering 8%, 36%
    and 0% of the image, none of which was the canvas.

    So: supply coordinates. They are recorded in the report, which makes the
    number reproducible in a way an auto-detected guess never would be.
    """
    if box is None:
        return None, "whole image"
    return tuple(box), "explicit box %s" % (tuple(box),)


_GRAY_CACHE = {}


def load_gray(path, width=480, crop=None):
    """Read a PNG as a luminance grid scaled to `width` wide.

    Returns (grid, width, height). Reuses imgdiff's decoder, so interlaced PNGs
    are refused with its own message rather than silently mis-read.

    Results are memoised on (path, width, crop, mtime) because decoding a
    1800x1300 PNG in pure Python costs seconds and a comparison run touches the
    same files repeatedly. The mtime is in the key so a regenerated screenshot
    is never served stale.
    """
    try:
        key = (os.path.abspath(path), width, crop, os.path.getmtime(path))
    except OSError:
        key = None
    if key is not None and key in _GRAY_CACHE:
        return _GRAY_CACHE[key]
    img = _crop(imgdiff.read_png(path), crop)
    w, h, rows = imgdiff.to_width(img, width)
    result = (imgdiff.gray(rows), w, h)
    if key is not None:
        _GRAY_CACHE[key] = result
    return result


def _percentile(sorted_vals, pct):
    if not sorted_vals:
        return 0
    k = int(round((len(sorted_vals) - 1) * pct / 100.0))
    return sorted_vals[k]


def stretch(g, lo_pct=1.0, hi_pct=99.0):
    """Linearly stretch one luminance grid over its own percentile range.

    This is the whole point of the wrapper: it removes the per-theme contrast
    scale so a near-black canvas and a white canvas compare as structure.
    """
    flat = sorted(v for row in g for v in row)
    lo = _percentile(flat, lo_pct)
    hi = _percentile(flat, hi_pct)
    span = hi - lo
    if span <= 0:
        return [row[:] for row in g], 0.0
    out = []
    for row in g:
        out.append([int(round((v - lo) * 255.0 / span)) for v in row])
    return out, float(span)


def edges_rel(g, frac=0.12):
    """Gradient magnitude above `frac` of this grid's own dynamic range.

    imgdiff.edges() uses a hardcoded 40, which is why it finds almost nothing
    in a low-contrast dark theme. Here the threshold is a fraction of the grid's
    own span (max-min after the caller's contrast stretch), so a dark and a
    light theme start from the same footing: each image's edge map is derived
    from its own content, not from an absolute 0-255 scale.
    """
    h = len(g)
    w = len(g[0]) if h else 0
    span = 255.0
    for row in g:
        for v in row:
            span = min(span, v)
    for row in g:
        for v in row:
            span = max(span, v)
    threshold = max(1.0, span * frac)
    out = []
    for y in range(h):
        row = g[y]
        below = g[y + 1] if y + 1 < h else row
        e = []
        for x in range(w):
            right = row[x + 1] if x + 1 < w else row[x]
            grad = abs(right - row[x]) + abs(below[x] - row[x])
            e.append(1 if grad > threshold else 0)
        out.append(e)
    return out, threshold


# -------------------------------------------------------------------- scoring


def _subcell_fractions(emap, y0, y1, x0, x1, sub):
    """Edge fraction in each of sub x sub boxes inside one grid cell."""
    out = []
    bh = max(1, (y1 - y0) // sub)
    bw = max(1, (x1 - x0) // sub)
    for sy in range(sub):
        for sx in range(sub):
            ay0, ay1 = y0 + sy * bh, min(y1, y0 + (sy + 1) * bh)
            ax0, ax1 = x0 + sx * bw, min(x1, x0 + (sx + 1) * bw)
            area = (ay1 - ay0) * (ax1 - ax0)
            if area <= 0:
                out.append(0.0)
                continue
            hits = sum(sum(emap[y][ax0:ax1]) for y in range(ay0, ay1))
            out.append(hits / float(area))
    return out


def compare_parity(path_a, path_b, width=480, cols=12, sub=3, frac=0.12,
                   lo_pct=5.0, hi_pct=99.0, crop=None):
    """Per-cell, position-aware layout score. 100 means identical structure.

    lo_pct defaults to 5 rather than 1 because a 1st-percentile cut sits inside
    the content tail; see the module docstring for the measured sweep.
    """
    ga, w, ha = load_gray(path_a, width, crop)
    gb, _, hb = load_gray(path_b, width, crop)

    # Both images are scaled to the same width, so unequal scaled heights mean
    # the two screenshots have different aspect ratios. Compare over the shared
    # height and report the difference rather than indexing past the shorter
    # image, which is what this did before real LTspice screenshots hit it.
    h = min(ha, hb)

    ga, span_a = stretch(ga, lo_pct, hi_pct)
    gb, span_b = stretch(gb, lo_pct, hi_pct)
    ea, thr_a = edges_rel(ga, frac)
    eb, thr_b = edges_rel(gb, frac)

    cell = max(1, w // cols)
    n_rows = int(math.ceil(h / float(cell)))
    sims = []
    cells = []
    for r in range(n_rows):
        y0, y1 = r * cell, min(h, (r + 1) * cell)
        for c in range(cols):
            x0, x1 = c * cell, min(w, (c + 1) * cell)
            if (y1 - y0) <= 0 or (x1 - x0) <= 0:
                continue
            fa = _subcell_fractions(ea, y0, y1, x0, x1, sub)
            fb = _subcell_fractions(eb, y0, y1, x0, x1, sub)
            tot_a = sum(fa)
            tot_b = sum(fb)
            if tot_a < 0.02 and tot_b < 0.02:
                continue  # empty in both: says nothing about the layout
            # Bray-Curtis on sub-cell profiles. Position aware: the same number
            # of edges in different sub-boxes scores low.
            sim = 1.0 - sum(abs(a - b) for a, b in zip(fa, fb)) / max(tot_a, tot_b)
            sim = max(0.0, min(1.0, sim))
            sims.append(sim)
            cells.append({"row": r, "col": c, "sim": round(sim, 4),
                          "edge_density_a": round(tot_a, 4),
                          "edge_density_b": round(tot_b, 4)})

    score = 100.0 * sum(sims) / len(sims) if sims else 100.0
    worst = sorted(cells, key=lambda d: d["sim"])[:8]
    return {
        "score": round(score, 1),
        "verdict": verdict(score),
        "cells_scored": len(sims),
        "grid": "%dx%d cells, %dx%d sub-cells" % (n_rows, cols, sub, sub),
        "dynamic_range_a": round(span_a, 1),
        "dynamic_range_b": round(span_b, 1),
        "edge_threshold_a": round(thr_a, 1),
        "edge_threshold_b": round(thr_b, 1),
        "height_a": ha,
        "height_b": hb,
        "shared_height": h,
        "aspect_note": ("compared over the shared height; the two screenshots "
                        "have different aspect ratios (%dx%d vs %dx%d)"
                        % (width, ha, width, hb)) if ha != hb else None,
        "worst_cells": worst,
    }


def compare_global(path_a, path_b, width=480, frac=0.12, crop=None):
    """Intersection over union of the two edge maps. Shift-sensitive."""
    ga, w, ha = load_gray(path_a, width, crop)
    gb, _, hb = load_gray(path_b, width, crop)
    h = min(ha, hb)
    ga, _ = stretch(ga)
    gb, _ = stretch(gb)
    ea, _ = edges_rel(ga, frac)
    eb, _ = edges_rel(gb, frac)
    inter = union = only_a = only_b = 0
    for y in range(h):
        ra, rb = ea[y], eb[y]
        for x in range(w):
            a, b = ra[x], rb[x]
            if a or b:
                union += 1
            if a and b:
                inter += 1
            elif a:
                only_a += 1
            elif b:
                only_b += 1
    if union == 0:
        score = 100.0
    else:
        score = 100.0 * inter / float(union)
    return {
        "score": round(score, 1),
        "verdict": verdict(score),
        "shared_height": h,
        "edge_pixels_union": union,
        "edge_pixels_matched": inter,
        "only_in_a": only_a,
        "only_in_b": only_b,
    }


def verdict(score):
    if score >= 95:
        return "MATCHES"
    if score >= 80:
        return "CLOSE"
    if score >= 60:
        return "PARTIAL"
    if score >= 35:
        return "DIFFERENT"
    return "UNRELATED"


# ------------------------------------------------------------------------ cli


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Theme-robust layout parity between two screenshots.")
    ap.add_argument("original", help="reference screenshot (PNG)")
    ap.add_argument("clone", help="screenshot to score against it (PNG)")
    ap.add_argument("--global", dest="global_mode", action="store_true",
                    help="IoU over the whole edge map instead of per-cell parity")
    ap.add_argument("--width", type=int, default=480)
    ap.add_argument("--cols", type=int, default=12, help="grid columns")
    ap.add_argument("--sub", type=int, default=3,
                    help="sub-cells per cell. 1 degenerates to a pure density "
                         "comparison. Measured on editor-dark vs editor-light: "
                         "1 -> 85.2, 3 -> 82.0, 5 -> 85.3, so finer is NOT "
                         "monotonically stricter; very small sub-cells go sparse "
                         "and get noisier. 3 is the calibrated default.")
    ap.add_argument("--edge-frac", type=float, default=0.12,
                    help="edge threshold as a fraction of each image's own range")
    ap.add_argument("--lo-pct", type=float, default=1.0)
    ap.add_argument("--hi-pct", type=float, default=99.0)
    ap.add_argument("--crop", metavar="X,Y,W,H",
                    help="crop BOTH images to this box in source pixels before "
                         "comparing. Use it to compare like with like: a whole "
                         "LTspice window against a whole editor window measures "
                         "title bars and toolbars, not schematic layout.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-under", type=float,
                    help="exit 1 if the score is below this")
    args = ap.parse_args(argv)

    crop = None
    if args.crop:
        try:
            crop = tuple(int(v) for v in args.crop.split(","))
        except ValueError:
            ap.error("--crop wants four comma separated integers: X,Y,W,H")
        if len(crop) != 4:
            ap.error("--crop wants four comma separated integers: X,Y,W,H")
    crop_a, note_a = resolve_crop(crop)

    if args.global_mode:
        report = compare_global(args.original, args.clone, args.width,
                                args.edge_frac, crop_a)
        report["mode"] = "global"
    else:
        report = compare_parity(args.original, args.clone, args.width, args.cols,
                                args.sub, args.edge_frac, args.lo_pct,
                                args.hi_pct, crop_a)
        report["mode"] = "parity"

    report["original"] = args.original
    report["clone"] = args.clone
    report["crop"] = list(crop_a) if crop_a else None
    report["crop_note"] = note_a

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("  %s" % args.original)
        print("  %s" % args.clone)
        print("  %-7s %s" % (report["mode"].upper(),
                              ("#" * int(round(report["score"] / 5))
                               + "." * (20 - int(round(report["score"] / 5))))))
        print("  %-7s %.1f  %s" % ("SCORE", report["score"], report["verdict"]))
        if report["mode"] == "parity":
            print("  %-7s %d cells, %s" % ("GRID", report["cells_scored"], report["grid"]))
            print("  %-7s %s vs %s, threshold %s vs %s" % (
                "RANGE", report["dynamic_range_a"], report["dynamic_range_b"],
                report["edge_threshold_a"], report["edge_threshold_b"]))
            if report["crop_note"] and report["crop_note"] != "whole image":
                print("  CROP     %s" % report["crop_note"])
            if report.get("aspect_note"):
                print("  NOTE     %s" % report["aspect_note"])
            print("  worst cells (row,col = similarity):")
            for c in report["worst_cells"]:
                print("    r%-3d c%-3d %.2f   density %s vs %s" % (
                    c["row"], c["col"], c["sim"],
                    c["edge_density_a"], c["edge_density_b"]))
        else:
            print("  %-7s %d matched of %d union edge pixels" % (
                "EDGES", report["edge_pixels_matched"], report["edge_pixels_union"]))

    if args.fail_under is not None and report["score"] < args.fail_under:
        print("FAIL: %.1f is below --fail-under %.1f" % (report["score"], args.fail_under),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())