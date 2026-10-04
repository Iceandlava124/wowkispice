"""Calibration tests for tools/ui_parity.py.

A layout-similarity number is only worth quoting if the metric has been pinned
at both ends. These tests are the reason the number can be believed: they lock
the upper bound, the theme-invariance that the vendored imgdiff cannot do, the
negative control, and the fact that the score is actually position sensitive.

The theme case is a regression test with teeth. tools/imgdiff.py scores our own
two themes of the same window at 8.1/100 because it thresholds absolute
luminance and compares per-cell edge density, so it measures contrast profile
rather than layout. ui_parity stretches each image over its own percentile
range first, which moves that same pair to 94.4. If someone "simplifies" the
wrapper back into density-only scoring, this fails.

The percentile cut is 5 rather than 1 for a measured reason, and it is the
reason this pair now exercises a real canvas. The Bode tab used to demand so
much width that the schematic canvas opened 97 px wide, so the reference
screenshots were almost entirely chrome. Once the canvas was fixed (see
TestCanvasShare in test_ui_polish.py) the light screenshot carries ~1.6% dark
ink, and a 1st-percentile low cut inverted its range against the dark theme's,
dropping this pair to 50.7. The unrelated control is 8.8 either way.
"""

import importlib.util
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DARK = os.path.join(ROOT, "docs", "editor-dark.png")
LIGHT = os.path.join(ROOT, "docs", "editor-light.png")
ICON_SHEET = os.path.join(ROOT, "docs", "icon-sheet.png")
LTSPICE_SCHEMATIC = os.path.join(ROOT, "docs", "ltspice-reference",
                                 "01-schematic-lt8609s.png")
LTSPICE_DIALOG = os.path.join(ROOT, "docs", "ltspice-reference",
                              "06-voltage-source.png")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


parity = _load("ui_parity", os.path.join(ROOT, "tools", "ui_parity.py"))
imgdiff = _load("vendored_imgdiff", os.path.join(ROOT, "tools", "imgdiff.py"))


def _have(*paths):
    return all(os.path.exists(p) for p in paths)


class TestCalibration(unittest.TestCase):

    @unittest.skipUnless(_have(DARK, LIGHT, ICON_SHEET),
                         "docs/ reference screenshots not present")
    def test_identical_images_score_100(self):
        report = parity.compare_parity(DARK, DARK)
        self.assertEqual(report["score"], 100.0)
        self.assertEqual(report["verdict"], "MATCHES")

    @unittest.skipUnless(_have(DARK, LIGHT), "docs/ reference screenshots not present")
    def test_two_themes_of_one_window_score_close(self):
        """The whole reason this wrapper exists."""
        report = parity.compare_parity(DARK, LIGHT)
        self.assertGreater(
            report["score"], 70.0,
            "same window in two themes scored %.1f; contrast profile is leaking "
            "back into the layout score" % report["score"])

    @unittest.skipUnless(_have(DARK, LIGHT), "docs/ reference screenshots not present")
    def test_stretch_survives_a_canvas_with_dark_ink_on_light(self):
        """The case that pinned the low percentile cut at 5.

        A light canvas with a small dark population inverts its 1st-99th
        percentile range against a dark theme's. If someone lowers the cut back
        to 1, this fails before the score test does.
        """
        light_span = parity.compare_parity(DARK, LIGHT)["dynamic_range_b"]
        dark_span = parity.compare_parity(DARK, LIGHT)["dynamic_range_a"]
        self.assertLess(
            max(light_span, dark_span) / float(min(light_span, dark_span)), 4.0,
            "the two themes' dynamic ranges differ by more than 4x "
            "(dark %.1f, light %.1f); the stretch cut is inside the content tail"
            % (dark_span, light_span))

    @unittest.skipUnless(_have(DARK, LIGHT), "docs/ reference screenshots not present")
    def test_vendored_imgdiff_fails_that_same_case(self):
        """Pins why the wrapper is needed, so it is never deleted as redundant.

        If a future imgdiff release fixes this, this test tells us the wrapper
        can go. Until then it must keep failing.
        """
        ga = imgdiff.gray(imgdiff.to_width(imgdiff.read_png(DARK), 480)[2])
        gb = imgdiff.gray(imgdiff.to_width(imgdiff.read_png(LIGHT), 480)[2])
        ea = imgdiff.edges(ga, 40)
        eb = imgdiff.edges(gb, 40)
        dense_a = sum(sum(r) for r in ea)
        dense_b = sum(sum(r) for r in eb)
        # imgdiff compares densities, so a large density gap is what destroys
        # its score on this pair.
        self.assertGreater(
            abs(dense_a - dense_b) / float(max(dense_a, dense_b)), 0.5,
            "imgdiff now handles this pair; the wrapper may be redundant")

    @unittest.skipUnless(_have(DARK, ICON_SHEET), "docs/ screenshots not present")
    def test_unrelated_image_scores_low(self):
        report = parity.compare_parity(DARK, ICON_SHEET)
        self.assertLess(report["score"], 30.0)
        self.assertIn(report["verdict"], ("UNRELATED", "DIFFERENT"))

    @unittest.skipUnless(_have(DARK, LIGHT), "docs/ reference screenshots not present")
    def test_metric_discriminates_same_from_different(self):
        """Close together: one window vs another window, far from: unrelated."""
        same = parity.compare_parity(DARK, LIGHT)["score"]
        different = parity.compare_parity(DARK, ICON_SHEET)["score"]
        self.assertGreater(same - different, 50.0)


class TestLtspiceControl(unittest.TestCase):
    """Pins the reason this is not an LTspice-similarity score.

    Measured against real LTspice screenshots, the whole-window score for
    LTspice-vs-our-editor landed in the same band as LTspice-vs-an-unrelated-
    LTspice-dialog. The control is what disqualifies the naive number, so it is
    asserted here: if a future change makes the two diverge sharply, the tool
    has become capable of something it currently is not, and the docstring
    needs rewriting rather than the test.

    LOCAL-ONLY CALIBRATION. The screenshots are ADI's copyrighted images, so
    docs/ltspice-reference/ is gitignored and this test skips for anyone who
    clones the repo (verified: 11 pass, 1 skip, exit 0). The repository ships no
    third-party images. See "Third-party material" in docs/systems-map.md.
    """

    @unittest.skipUnless(_have(LTSPICE_SCHEMATIC, LTSPICE_DIALOG, DARK),
                         "docs/ltspice-reference/ screenshots not present")
    def test_control_sits_in_the_same_band(self):
        control = parity.compare_parity(LTSPICE_SCHEMATIC, LTSPICE_DIALOG)["score"]
        versus_us = parity.compare_parity(LTSPICE_SCHEMATIC, DARK)["score"]
        self.assertLess(
            abs(versus_us - control), 10.0,
            "LTspice vs us (%.1f) and LTspice vs its own dialog (%.1f) now "
            "diverge; the tool may now measure something real, so update the "
            "docstring" % (versus_us, control))


class TestPositionSensitivity(unittest.TestCase):
    """A density-only metric cannot see a shift. This one must."""

    def test_shifting_the_structure_lowers_the_score(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            def build(shift):
                rows = []
                for y in range(120):
                    row = []
                    for x in range(200):
                        on = any(b + shift <= x < b + shift + 20 and 20 <= y < 100
                                 for b in (30, 100, 170))
                        row.append((0, 0, 0) if on else (255, 255, 255))
                    rows.append(row)
                p = os.path.join(tmp, "s%d.png" % shift)
                imgdiff.write_png(p, 200, 120, rows)
                return p
            still = parity.compare_parity(build(0), build(0))["score"]
            shifted = parity.compare_parity(build(0), build(40))["score"]
        self.assertEqual(still, 100.0)
        self.assertLess(shifted, still,
                        "a 40px shift did not lower the score, so the metric is "
                        "blind to position and is just comparing density")


class TestStretch(unittest.TestCase):

    def test_stretch_maps_a_dark_image_onto_the_full_range(self):
        g = [[10, 12], [14, 16]]
        out, span = parity.stretch(g)
        self.assertAlmostEqual(span, 6.0, places=3)
        self.assertEqual(min(v for row in out for v in row), 0)
        self.assertEqual(max(v for row in out for v in row), 255)

    def test_stretch_survives_a_flat_image(self):
        out, span = parity.stretch([[7, 7], [7, 7]])
        self.assertEqual(span, 0.0)
        self.assertEqual(out, [[7, 7], [7, 7]])

    def test_stretch_preserves_ordering(self):
        g = [[0, 128, 255]]
        out, _ = parity.stretch(g)
        self.assertLess(out[0][0], out[0][1])
        self.assertLess(out[0][1], out[0][2])


class TestVerdicts(unittest.TestCase):
    def test_bands_do_not_overlap_or_gap(self):
        pairs = [(100, "MATCHES"), (95, "MATCHES"), (94.9, "CLOSE"),
                 (80, "CLOSE"), (79.9, "PARTIAL"), (60, "PARTIAL"),
                 (59.9, "DIFFERENT"), (35, "DIFFERENT"), (34.9, "UNRELATED"),
                 (0, "UNRELATED")]
        for score, expected in pairs:
            self.assertEqual(parity.verdict(score), expected, score)


if __name__ == "__main__":
    unittest.main()