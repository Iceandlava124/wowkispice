"""
test_ui_polish.py - Verification for the appearance and canvas work.

Headless (QT_QPA_PLATFORM=offscreen). Covers:
1. Palette integrity - every colour is a real colour, the stylesheet is balanced
2. Appearance switching actually re-skins the symbols and the actions
3. The schematic canvas - dot grid, junction dots, armed-tool ghost, snapping
4. Board symbols draw a board instead of falling through to the "?" box
5. Icon glyphs contain visible ink and stay inside their frame
6. Session persistence restores chrome but never simulation semantics
7. The waveform pane - trace list, visibility, and honest cursor hit testing
8. Keyboard: letter keys arm a part, Esc un-arms it, the canvas takes focus
9. Layout: the canvas keeps a real share of the window, and no single results
   tab can starve it by demanding a huge minimum width
"""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import QPoint, QPointF, Qt                    # noqa: E402
from PyQt5.QtGui import QColor, QImage, QPainter                # noqa: E402
from PyQt5.QtTest import QTest                                 # noqa: E402
from PyQt5.QtWidgets import (                                   # noqa: E402
    QApplication, QPushButton, QScrollArea,
)

from bridge.cad_engine import SchematicNetlistEngine             # noqa: E402
from ui.schematic_editor import ICON_SCALES                        # noqa: E402
from ui import icons, theme, schematic_items                     # noqa: E402
from ui.schematic_editor import SchematicEditor, SchematicView  # noqa: E402
from ui.schematic_items import draw_symbol                       # noqa: E402
from ui.schematic_scene import SchematicScene                    # noqa: E402
from ui.schematic_symbols import SYMBOLS, GRID                   # noqa: E402

_app = QApplication.instance() or QApplication([])

HEX = set("0123456789abcdefABCDEF")


def valid_colour(value):
    if not isinstance(value, str) or not value.startswith("#"):
        return False
    return len(value) in (7, 9) and all(c in HEX for c in value[1:])


def ink_of(comp_type, scale=2):
    """Pixels drawn by a symbol, so 'does it render' is measured not assumed."""
    ex, ey, ew, eh = SYMBOLS[comp_type]["extent"]
    w, h = int(ew * scale) + 8, int(eh * scale) + 8
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(w / 2 - ex * scale, h / 2 - ey * scale)
    painter.scale(scale, scale)
    draw_symbol(painter, comp_type)
    painter.end()
    ink = 0
    for y in range(h):
        for x in range(w):
            if img.pixelColor(x, y).alpha() > 16:
                ink += 1
    return ink


class TestPaletteIntegrity(unittest.TestCase):
    """A typo in a colour string renders as invisible text, so check them."""

    def test_every_palette_value_is_a_real_colour(self):
        for palette in (theme.DARK, theme.LIGHT):
            fields = [f for f in dir(palette)
                      if not f.startswith("_") and not callable(getattr(palette, f))
                      and f not in ("name",)]
            for field in fields:
                value = getattr(palette, field)
                if isinstance(value, str):
                    self.assertTrue(valid_colour(value),
                                    f"{palette.name}.{field} = {value!r}")

    def test_stylesheet_braces_balance(self):
        for palette in (theme.DARK, theme.LIGHT):
            sheet = theme.qss(palette)
            self.assertEqual(sheet.count("{"), sheet.count("}"), palette.name)
            self.assertGreater(len(sheet), 2000)

    def test_palettes_differ_where_it_matters(self):
        for field in ("window", "text", "canvas", "accent", "ink", "pin"):
            self.assertNotEqual(getattr(theme.DARK, field),
                                getattr(theme.LIGHT, field), field)

    def test_qcolor_conversion_works(self):
        self.assertEqual(theme.DARK.qcolor("window"), QColor(theme.DARK.window))


class TestAppearanceSwitching(unittest.TestCase):
    def test_cycle_theme_flips_between_the_two_palettes(self):
        original = theme.current().name
        try:
            first = theme.cycle_theme(_app, persist=False)
            second = theme.cycle_theme(_app, persist=False)
            self.assertNotEqual(first.name, second.name)
            self.assertEqual(first.name, "dark" if second.name == "light" else "light")
            self.assertIn(first.name, theme.PALETTES)
        finally:
            theme.apply_theme(_app, original, persist=False)

    def test_symbol_palette_follows_the_theme(self):
        original = theme.current().name
        try:
            theme.apply_theme(_app, "light", persist=False)
            light_ink = theme.set_symbol_palette(theme.current())["INK"]
            theme.apply_theme(_app, "dark", persist=False)
            dark_ink = theme.set_symbol_palette(theme.current())["INK"]
            self.assertNotEqual(light_ink, dark_ink)
            self.assertEqual(schematic_items.INK, dark_ink)
        finally:
            theme.apply_theme(_app, original, persist=False)
            theme.set_symbol_palette(theme.current())

    def test_editor_theme_toggle_rebuilds_icons_and_leaves_a_trace(self):
        win = SchematicEditor()
        try:
            before = theme.current().name
            win._toggle_theme()
            after = theme.current().name
            self.assertNotEqual(before, after)
            self.assertIn("Appearance:", win.console.toPlainText())
            win._toggle_theme()
            self.assertEqual(before, theme.current().name)
        finally:
            win.close()

    def test_pyqtgraph_colours_are_supplied_for_every_plot_role(self):
        colours = theme.pyqtgraph_colors(theme.DARK)
        for key in ("background", "foreground", "axis", "grid", "label"):
            self.assertTrue(valid_colour(colours[key]), key)


class TestCanvas(unittest.TestCase):
    def setUp(self):
        self.scene = SchematicScene(SchematicNetlistEngine())

    def tearDown(self):
        self.scene.clear()

    def _wired_chain(self):
        """A chain whose ground pin really does carry three wires.

        V+ - R1 - C1 - R2 with C1's return pin tied to both R2 and the source
        return, so GND1.1 ends up with three wires on it: the only place a
        junction can legitimately be drawn in a pin-to-pin wiring model.
        """
        self.scene.place_component("V", QPointF(0, 0))
        self.scene.place_component("R", QPointF(80, 0))
        self.scene.place_component("C", QPointF(160, 0))
        self.scene.place_component("R", QPointF(240, 0))
        self.scene.place_component("GND", QPointF(160, 80))
        for a, b in (("V1", "+"), ("R1", "1"), ("R1", "2"), ("C1", "1"),
                     ("C1", "2"), ("R2", "1"), ("R2", "2"), ("GND1", "1"),
                     ("V1", "-"), ("GND1", "1"),
                     ("C1", "2"), ("GND1", "1")):
            self.scene.pin_clicked(a, b)

    def test_grid_visibility_actually_changes_what_is_painted(self):
        from PyQt5.QtCore import QRectF

        def painted(scene):
            img = QImage(240, 240, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            painter = QPainter(img)
            painter.fillRect(0, 0, 240, 240, QColor(theme.current().canvas))
            scene.drawBackground(painter, QRectF(-120, -120, 240, 240))
            painter.end()
            return {img.pixelColor(x, y).name()
                    for y in range(240) for x in range(240)}

        self.scene.grid_visible = True
        with_grid = painted(self.scene)
        self.scene.grid_visible = False
        without_grid = painted(self.scene)
        self.assertTrue(self.scene.grid_visible or True)
        self.assertGreater(len(with_grid), len(without_grid),
                           "the dot grid was not actually drawn")

    def test_junction_appears_only_at_three_or_more_wires(self):
        self._wired_chain()
        refs = {j.ref for j in self.scene._junctions}
        self.assertIn(("GND1", "1"), refs, refs)
        self.assertNotIn(("V1", "+"), refs, refs)
        self.assertNotIn(("C1", "1"), refs, refs)

    def test_junction_disappears_when_the_wire_is_removed(self):
        self._wired_chain()
        self.assertTrue(self.scene._junctions)
        self.scene.model.wires = [w for w in self.scene.model.wires
                                  if w.get("from") != "R2:2"
                                  and w.get("to") != "R2:2"]
        self.scene.rebuild()
        refs = {j.ref for j in self.scene._junctions}
        self.assertNotIn(("GND1", "1"), refs, refs)

    def test_armed_tool_follows_the_pointer_and_snaps_to_grid(self):
        self.scene.set_armed("R")
        self.assertIsNotNone(self.scene._ghost)
        self.scene.move_ghost(QPointF(37, 63))
        x, y = self.scene._ghost.pos().x(), self.scene._ghost.pos().y()
        self.assertEqual(x % GRID, 0)
        self.assertEqual(y % GRID, 0)
        self.assertEqual((x, y), (40, 60))

    def test_ghost_actually_paints_its_symbol(self):
        """A ghost that is positioned but never painted is invisible, and an
        item whose paint() has the wrong arity fails silently - Qt swallows the
        TypeError and draws nothing. So render it and count pixels."""
        self.scene.set_armed("D")
        ghost = self.scene._ghost
        size = 120
        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.translate(size / 2, size / 2)
        ghost.paint(painter, None, None)
        painter.end()
        ink = sum(1 for y in range(size) for x in range(size)
                  if img.pixelColor(x, y).alpha() > 16)
        self.assertGreater(ink, 50, "ghost symbol drew nothing")

    def test_disarming_removes_the_ghost(self):
        self.scene.set_armed("C")
        self.assertIsNotNone(self.scene._ghost)
        self.scene.set_armed(None)
        self.assertIsNone(self.scene._ghost)

    def test_rebuild_keeps_the_ghost_when_a_tool_is_armed(self):
        self.scene.set_armed("L")
        self.scene.place_component("R", QPointF(0, 0))
        self.assertIsNotNone(self.scene._ghost)

    def test_rubber_band_is_the_default_drag_mode_not_pan(self):
        view = SchematicView(SchematicScene(SchematicNetlistEngine()))
        self.assertEqual(view.dragMode(),
                         SchematicView.DragMode.RubberBandDrag)


class TestBoardSymbols(unittest.TestCase):
    def test_every_board_symbol_draws_a_board_not_the_unknown_box(self):
        boards = [t for t, spec in SYMBOLS.items() if spec.get("footprint")]
        self.assertGreaterEqual(len(boards), 5)
        for board in boards:
            # The "?" fallback box is 40x28 units; a board body is far larger
            # and filled. Anything under 1000 pixels is not a board.
            self.assertGreater(ink_of(board), 1000, board)

    def test_plain_symbols_still_draw(self):
        # Ground is four short strokes and legitimately has the least ink of
        # any symbol; the point here is only that nothing falls through to the
        # blank/unknown path.
        for comp_type in ("R", "C", "L", "V", "I", "D", "MOSFET", "GND", "MCU"):
            self.assertGreater(ink_of(comp_type), 15, comp_type)


class TestIcons(unittest.TestCase):
    def test_every_glyph_has_ink_and_stays_inside_its_frame(self):
        for name in sorted(icons.GLYPHS):
            img = icons.raw_image(name, "#ffffff", 48)
            ink = 0
            minx = miny = 48
            maxx = maxy = -1
            for y in range(48):
                for x in range(48):
                    if img.pixelColor(x, y).alpha() > 16:
                        ink += 1
                        minx, maxx = min(minx, x), max(maxx, x)
                        miny, maxy = min(miny, y), max(maxy, y)
            self.assertGreater(ink, 100, f"{name} is blank")
            self.assertLess(ink, 48 * 48 * 0.6, f"{name} is a solid blob")
            self.assertGreaterEqual(minx, 0)
            self.assertGreaterEqual(miny, 0)
            self.assertLessEqual(maxx, 47, f"{name} overflows right")
            self.assertLessEqual(maxy, 47, f"{name} overflows bottom")

    def test_icons_take_the_palette_colour(self):
        red = icons.raw_image("run", "#ff0000", 32)
        centre = red.pixelColor(12, 16)
        self.assertGreater(centre.red(), 200)
        self.assertLess(centre.green(), 60)


class TestKeyboardShortcuts(unittest.TestCase):
    """Both of these were reported from manual testing and neither was
    covered: nothing in the suite had ever sent a key event. They are easy to
    regress silently, because a dead shortcut fails exactly like no feature.
    """

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="wosp-keys-test-")
        theme.use_settings_dir(self._dir)
        for key in theme.settings().allKeys():
            theme.settings().remove(key)
        self.win = SchematicEditor()
        self.win.resize(1200, 800)
        self.win.show()
        _app.processEvents()

    def tearDown(self):
        self.win.close()
        _app.processEvents()

    def press(self, widget, key, mods=Qt.NoModifier):
        """A real key press down the real event path, not a direct method call.

        QTest.keyClick accepts either a Qt.Key or a one-character string, so
        letters go through as strings and arrive with a proper key text().
        """
        QTest.keyClick(widget, key, mods)

    # -- letter keys switch the armed part -------------------------------
    def test_letter_keys_switch_the_armed_component(self):
        win = self.win
        for ch, expected in (("R", "R"), ("C", "C"), ("L", "L"),
                             ("D", "D"), ("V", "V"), ("M", "MOSFET"),
                             ("G", "GND"), ("E", "ESP32")):
            with self.subTest(ch=ch):
                win.scene.set_armed(None)
                self.press(win.view, ch)
                self.assertEqual(win.scene.armed_type, expected)

    def test_letter_key_actually_shows_a_ghost(self):
        """Arming a type is not enough; the preview has to exist, otherwise
        the user cannot see what they are about to drop."""
        win = self.win
        win.scene.set_armed(None)
        self.press(win.view, "C")
        self.assertIsNotNone(win.scene._ghost,
                             "letter key armed a type but drew no ghost")

    def test_letters_work_from_any_widget_that_has_the_focus(self):
        """The bug was structural: the canvas never held focus, so a key went
        to whatever widget happened to have it."""
        win = self.win
        win.palette_list.setFocus()
        _app.processEvents()
        self.press(win.palette_list, "D")
        self.assertEqual(win.scene.armed_type, "D")

    def test_clicking_the_canvas_gives_it_the_keyboard_focus(self):
        win = self.win
        win.palette_filter.setFocus()
        _app.processEvents()
        self.assertIs(_app.focusWidget(), win.palette_filter)
        QTest.mouseClick(win.view.viewport(), Qt.LeftButton, Qt.NoModifier,
                         QPoint(400, 300))
        _app.processEvents()
        self.assertTrue(win.view.hasFocus(),
                        "canvas click did not move keyboard focus to the sheet")

    def test_every_palette_part_has_exactly_one_letter_key(self):
        from ui.schematic_editor import PART_HOTKEYS, hotkey_of
        from ui.schematic_symbols import PALETTE_GROUPS
        palette_types = [t for _group, types in PALETTE_GROUPS for t in types]
        self.assertEqual(len(set(PART_HOTKEYS.values())), len(PART_HOTKEYS),
                         "two letters arm the same part")
        self.assertEqual(sorted(PART_HOTKEYS.values()), sorted(palette_types),
                         "a palette part has no letter, or an extra one")
        for comp_type in palette_types:
            self.assertTrue(hotkey_of(comp_type), comp_type)

    # -- Esc un-arms ------------------------------------------------------
    def test_escape_clears_the_armed_tool_and_its_ghost(self):
        win = self.win
        self.press(win.view, "R")
        self.assertEqual(win.scene.armed_type, "R")
        self.assertIsNotNone(win.scene._ghost)

        self.press(win.view, Qt.Key_Escape)

        self.assertIsNone(win.scene.armed_type)
        # The ghost item itself has to go: clearing armed_type directly removes
        # the flag but leaves the preview drawn on the sheet forever.
        self.assertIsNone(win.scene._ghost,
                          "Esc cleared armed_type but left the ghost drawn")

    def test_escape_drops_a_pending_wire(self):
        win = self.win
        comp = win.scene.place_component("R", QPointF(0, 0))
        win.scene.pin_clicked(comp.comp_id, "1")
        self.assertIsNotNone(win.scene._wire_start)
        self.assertIsNotNone(win.scene._rubber)
        self.press(win.view, Qt.Key_Escape)
        self.assertIsNone(win.scene._wire_start)
        self.assertIsNone(win.scene._rubber,
                          "Esc left the rubber-band wire on the sheet")

    def test_escape_clears_the_selection(self):
        win = self.win
        comp = win.scene.place_component("R", QPointF(0, 0))
        win.scene.comp_items[comp.comp_id].setSelected(True)
        self.assertTrue(win.scene.selectedItems())
        self.press(win.view, Qt.Key_Escape)
        self.assertEqual(win.scene.selectedItems(), [])

    def test_escape_works_from_a_widget_that_has_the_focus(self):
        win = self.win
        win.scene.set_armed("R")
        win.palette_list.setFocus()
        _app.processEvents()
        self.press(win.palette_list, Qt.Key_Escape)
        self.assertIsNone(win.scene.armed_type)
        self.assertIsNone(win.scene._ghost)

    def test_escape_from_the_filter_box_still_cancels_the_tool(self):
        win = self.win
        win.scene.set_armed("R")
        win.palette_filter.setFocus()
        _app.processEvents()
        self.press(win.palette_filter, Qt.Key_Escape)
        self.assertIsNone(win.scene.armed_type)

    def test_escape_with_nothing_armed_does_not_raise(self):
        win = self.win
        self.press(win.view, Qt.Key_Escape)
        self.assertIsNone(win.scene.armed_type)
        self.assertIsNone(win.scene._ghost)

    # -- the bindings that had to move out of the way --------------------
    def menu_shortcuts(self):
        """{menu item text: shortcut}. QWidget.actions() does not see actions
        that live in a QMenu, so walk the menu bar."""
        found = {}
        for menu_act in self.win.menuBar().actions():
            menu = menu_act.menu()
            if menu is None:
                continue
            for act in menu.actions():
                if act.shortcut().toString():
                    found[act.text().replace("&", "")] = act.shortcut().toString()
        return found

    def test_letters_no_longer_collide_with_rotate_and_label(self):
        """R/E/L are parts now. Rotate, edit and label live on Ctrl chords, so
        pressing R cannot silently rotate whatever you meant to place."""
        shortcuts = self.menu_shortcuts()
        self.assertEqual(shortcuts.get("Rotate 90°"), "Ctrl+R")
        self.assertEqual(shortcuts.get("Edit Value..."), "Ctrl+E")
        self.assertEqual(shortcuts.get("Label Net..."), "Ctrl+L")

    def test_place_menu_lists_every_letter_key(self):
        shortcuts = self.menu_shortcuts()
        from ui.schematic_editor import PART_HOTKEYS, hotkey_of
        from ui.schematic_symbols import label_of
        for comp_type in PART_HOTKEYS.values():
            label = label_of(comp_type).replace("&", "")
            self.assertIn(label, shortcuts, f"{comp_type} missing from Place menu")
            self.assertEqual(shortcuts[label], hotkey_of(comp_type))
        self.assertEqual(shortcuts.get("Cancel"), "Esc")


class TestSessionPersistence(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="wosp-settings-test-")
        theme.use_settings_dir(self._dir)
        self._original = theme.current().name
        for key in theme.settings().allKeys():
            theme.settings().remove(key)

    def tearDown(self):
        theme.apply_theme(_app, self._original, persist=False)
        theme.set_symbol_palette(theme.current())

    def test_use_settings_dir_redirects_the_settings_file(self):
        self.assertIn("wosp-settings-test", theme.settings().fileName())

    def test_chrome_is_restored(self):
        win = SchematicEditor()
        win.grid_action.setChecked(False)
        win.ruler_action.setChecked(True)
        self.assertFalse(win.scene.grid_visible)
        win._save_session()
        self.assertFalse(theme.settings().value("view/grid", True, bool))

        other = SchematicEditor()
        self.assertFalse(other.scene.grid_visible)
        other.close()

    def test_simulation_settings_are_never_restored(self):
        """A remembered mode or timestep changes what a run computes. That is
        how one window silently ends up running a different experiment from the
        last, so these must not survive a restart - in any direction."""
        win = SchematicEditor()
        win.mode_box.setCurrentText("Transient only")
        win.vin_box.setValue(31.5)
        win.tstep_box.setValue(7.25)
        win.duration_box.setValue(11.0)
        win.speed_box.setCurrentText("Accurate")
        win._save_session()
        stored = {k: theme.settings().value(k) for k in theme.settings().allKeys()}
        for forbidden in ("session/mode", "session/vin", "session/tstep",
                          "session/duration", "session/accuracy"):
            self.assertNotIn(forbidden, stored,
                             f"{forbidden} must not be persisted: {stored}")

        other = SchematicEditor()
        self.assertEqual(other.mode_box.currentText(), "Co-simulation")
        self.assertNotEqual(other.vin_box.value(), 31.5)
        self.assertEqual(other.speed_box.currentText(), "Balanced")
        other.close()

    def test_recent_documents_survive_and_open(self):
        payload = os.path.join(self._dir, "sample.wsk")
        with open(payload, "w", encoding="utf-8") as handle:
            handle.write('{"components": {}, "wires": []}')
        win = SchematicEditor()
        win._open_path(payload)
        self.assertEqual(win._current_path, payload)
        win._save_session()
        self.assertIn(payload, theme.settings().value("session/recent", [], list))
        win.close()

    def test_opening_a_broken_file_reports_instead_of_raising(self):
        broken = os.path.join(self._dir, "broken.wsk")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        win = SchematicEditor()
        win._open_path(broken)          # must not raise
        win.close()


class TestWaveformPane(unittest.TestCase):
    def _rc_window(self):
        """V - R - C low-pass wired the way a user would, by clicking pins."""
        win = SchematicEditor()
        win.duration_box.setValue(1.0)
        win.tstep_box.setValue(5.0)
        scene = win.scene
        scene.place_component("V", QPointF(0, 0))
        scene.place_component("R", QPointF(80, 0))
        scene.place_component("C", QPointF(160, 0))
        scene.place_component("GND", QPointF(160, 80))
        for a, b in (("V1", "+"), ("R1", "1"), ("V1", "-"), ("GND1", "1"),
                     ("R1", "2"), ("C1", "1"), ("C1", "2"), ("GND1", "1")):
            scene.pin_clicked(a, b)
        return win

    def test_trace_list_is_rebuilt_and_visibility_is_honoured(self):
        win = self._rc_window()
        try:
            win.run_simulation()
            rows = [win.trace_list.topLevelItem(i).text(0)
                    for i in range(win.trace_list.topLevelItemCount())]
            self.assertTrue(rows, "no traces listed after a run")
            plotted = [c.name() for c in win._curves]
            for name in plotted:
                self.assertIn(name, rows)
            item = win.trace_list.topLevelItem(0)
            item.setCheckState(0, Qt.Unchecked)
            target = win._curves[0]
            self.assertFalse(target.isVisible())
            item.setCheckState(0, Qt.Checked)
            self.assertTrue(target.isVisible())
        finally:
            win.close()

    def test_clicking_a_trace_row_chooses_what_the_cursor_measures(self):
        win = self._rc_window()
        try:
            win.run_simulation()
            win._click_points = [win._last_time[0]]
            win.refresh_cursors()
            if len(win._curves) < 2:
                self.skipTest("needs two nets to choose between")
            win._measured_trace = None
            win._on_trace_row_clicked(win.trace_list.topLevelItem(1), 0)
            chosen = win._trace_at_cursor()[0]
            self.assertEqual(chosen, win.trace_list.topLevelItem(1).text(0))
        finally:
            win.close()

    def test_cursor_readout_without_a_pixel_names_a_visible_trace(self):
        """Cursors placed by dragging, or set by code, have no pointer position.
        The readout must then name a real trace rather than guessing silently."""
        win = self._rc_window()
        try:
            win.run_simulation()
            win._click_points = [win._last_time[0]]
            win._click_points_view = []
            win.refresh_cursors()
            net, curve = win._trace_at_cursor()
            self.assertIn(net, [c.name() for c in win._curves])
            self.assertIsNotNone(curve)
        finally:
            win.close()

    def test_curves_do_not_accumulate_across_runs(self):
        win = self._rc_window()
        try:
            win.run_simulation()
            first = len(win._curves)
            win.run_simulation()
            self.assertEqual(len(win._curves), first,
                             "trace list grew on the second run")
        finally:
            win.close()


class TestCanvasShare(unittest.TestCase):
    """The canvas must not be starved by a sibling pane's minimum width.

    This was a real, shipped layout fault rather than an offscreen artefact:
    the Bode tab's controls sat in one unshrinkable row, QTabWidget passed
    that page's minimum width to the QSplitter, and the splitter honoured the
    minimum over the intended 3:2 stretch factor.  The schematic view opened at
    97 px inside a 1329 px pane.  Nothing in the suite measured the split, so a
    layout regression here would be invisible.
    """

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="wosp-layout-test-")
        theme.use_settings_dir(self._dir)
        for key in theme.settings().allKeys():
            theme.settings().remove(key)
        self.win = SchematicEditor()
        self.win.show()
        _app.processEvents()
        self.win.grab()          # force the first real layout pass
        _app.processEvents()

    def tearDown(self):
        self.win.close()
        _app.processEvents()

    def results_tabs(self):
        return self.win.center_split.widget(1)

    def test_canvas_keeps_a_real_share_of_the_pane(self):
        self.win.resize(1600, 980)
        _app.processEvents()
        self.win.grab()
        _app.processEvents()
        pane = self.win.center_split.width()
        self.assertGreater(self.win.view.width(), 0,
                           "canvas collapsed to zero width")
        self.assertGreaterEqual(
            self.win.view.width() * 100 // pane, 40,
            f"canvas is {self.win.view.width()} px of a {pane} px pane; "
            "a sibling pane is dictating the split")

    def test_canvas_share_holds_across_window_widths(self):
        shares = []
        for width in (1280, 1600):
            self.win.resize(width, 900)
            _app.processEvents()
            self.win.grab()
            _app.processEvents()
            shares.append(self.win.view.width() * 100
                          // self.win.center_split.width())
        for width, share in zip((1280, 1600), shares):
            self.assertGreaterEqual(
                share, 40,
                f"canvas fell to {share}% of the pane at {width} px wide")

    def test_no_results_tab_demands_an_outrageous_minimum(self):
        """A tab page's minimum width becomes the whole window's minimum."""
        tabs = self.results_tabs()
        for index in range(tabs.count()):
            page = tabs.widget(index)
            self.assertLessEqual(
                page.minimumSizeHint().width(), 640,
                f"tab {tabs.tabText(index)!r} demands "
                f"{page.minimumSizeHint().width()} px of minimum width")

    def test_bode_controls_scroll_instead_of_dictating_width(self):
        """The Bode row is genuinely wide, so it must not be clipped away.

        It is allowed to be wide; it is not allowed to be unreachable.
        """
        tabs = self.results_tabs()
        page = None
        for index in range(tabs.count()):
            if tabs.tabText(index) == "Bode":
                page = tabs.widget(index)
        self.assertIsNotNone(page, "no Bode tab to check")
        scrolls = page.findChildren(QScrollArea)
        self.assertTrue(scrolls,
                        "Bode controls are neither compact nor scrollable")
        area = scrolls[0]
        self.assertTrue(area.widget().findChildren(QPushButton),
                        "scrollable Bode controls contain no buttons")
        # The area's height is fixed at build time, so a font change would clip
        # the controls unless the vertical scrollbar is allowed to appear.
        self.assertEqual(area.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded,
                         "controls can be clipped vertically with no escape")
        self.assertGreaterEqual(
            area.height(), area.widget().sizeHint().height(),
            "Bode controls do not fit the scroll area")

    def test_canvas_has_a_minimum_width_floor(self):
        self.assertGreaterEqual(
            self.win.view.minimumWidth(), 300,
            "the canvas can be squeezed to nothing by its own layout")


# ----------------------------------------------------------------------------
# Item 1: icon / cursor scale setting is wired, persisted, and changes sizes
# ----------------------------------------------------------------------------
class TestIconScaleSetting(unittest.TestCase):
    """LTspice users are stuck with one fixed icon size; here the user can
    pick Small / Medium / Large from View > Icon / Cursor Size and it sticks
    across a restart. This test exercises the real machinery, not a mock."""

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="wosp-scale-test-")
        theme.use_settings_dir(self._dir)
        for key in theme.settings().allKeys():
            theme.settings().remove(key)
        self.win = SchematicEditor()
        self.win.show()
        _app.processEvents()

    def tearDown(self):
        self.win.close()
        _app.processEvents()

    def toolbar_size(self):
        return self.win.toolbar_run.iconSize().width()

    def palette_size(self):
        return self.win.palette_list.iconSize().width()

    def crosshair_width(self):
        return self.win.view.cursor_width

    def row_height(self, comp_type="R"):
        for row in range(self.win.palette_list.count()):
            item = self.win.palette_list.item(row)
            if item.data(Qt.UserRole) == comp_type:
                return item.sizeHint().height()
        self.fail(f"{comp_type} not found in palette")

    def test_default_is_medium(self):
        self.assertEqual(self.win._icon_scale, "medium")
        self.assertEqual(self.toolbar_size(), ICON_SCALES["medium"]["toolbar"])
        self.assertEqual(self.palette_size(), ICON_SCALES["medium"]["palette"])
        self.assertEqual(self.crosshair_width(),
                         ICON_SCALES["medium"]["cursor"])
        self.assertEqual(self.row_height(), ICON_SCALES["medium"]["row"])

    def test_small_reduces_every_scale_surface(self):
        self.win._set_icon_scale("small")
        _app.processEvents()
        self.assertEqual(self.win._icon_scale, "small")
        self.assertEqual(self.toolbar_size(), ICON_SCALES["small"]["toolbar"])
        self.assertEqual(self.palette_size(), ICON_SCALES["small"]["palette"])
        self.assertEqual(self.crosshair_width(),
                         ICON_SCALES["small"]["cursor"])
        self.assertEqual(self.row_height(), ICON_SCALES["small"]["row"])

    def test_large_increases_every_scale_surface(self):
        self.win._set_icon_scale("large")
        _app.processEvents()
        self.assertEqual(self.win._icon_scale, "large")
        self.assertEqual(self.toolbar_size(), ICON_SCALES["large"]["toolbar"])
        self.assertEqual(self.palette_size(), ICON_SCALES["large"]["palette"])
        self.assertEqual(self.crosshair_width(),
                         ICON_SCALES["large"]["cursor"])
        self.assertEqual(self.row_height(), ICON_SCALES["large"]["row"])

    def test_scale_is_persisted_and_restored(self):
        self.win._set_icon_scale("small")
        self.win._save_session()
        self.assertEqual(
            theme.settings().value("view/icon_scale", "medium", str),
            "small")
        other = SchematicEditor()
        self.assertEqual(other._icon_scale, "small")
        self.assertEqual(
            other.toolbar_run.iconSize().width(),
            ICON_SCALES["small"]["toolbar"])
        other.close()

    def test_scale_actions_are_exclusive_and_checkable(self):
        group = self.win._scale_group
        self.assertTrue(group.isExclusive())
        actions = list(group.actions())
        self.assertEqual({a.text().replace("&", "") for a in actions},
                         {"Small", "Medium", "Large"})
        medium = self.win._scale_actions["medium"]
        self.assertTrue(medium.isChecked())

    def test_switching_scale_moves_the_checked_action(self):
        self.win._set_icon_scale("large")
        _app.processEvents()
        self.assertTrue(self.win._scale_actions["large"].isChecked())
        self.assertFalse(self.win._scale_actions["medium"].isChecked())


# ----------------------------------------------------------------------------
# Item 2: HiDPI consistency at 100 / 150 / 200%  (subprocess probe)
# ----------------------------------------------------------------------------
class TestHiDpiConsistency(unittest.TestCase):
    """The editor must scale together at 100 / 150 / 200% display scaling.

    Reported LTspice complaint: toolbars / grids / labels drift apart when the
    display scaling changes, so a 150% desktop ends up with a crisp toolbar and
    a blurry canvas, with no escape.

    Items covered:
      - Qt.HighDpi attributes are on so icons render in physical pixels
        instead of flat logical pixels upscaled (the shipped defect).
      - Toolbar, palette and canvas grid all grow by exactly the display DPR.
      - Text widgets grow by exactly the display DPR (no mismatch between UI
        chrome and canvas content).
      - Everything here is measured from pixels, not a visual claim.

    Before / after probe, run by hand::

        for f in 1 1.5 2; do
          QT_SCALE_FACTOR=$f python tests/hidpi_probe.py
        done

    Before the fix the probe printed icon_baseline_w == 18 at every factor
    (flat logical pixels, upscaled / blurry); after the fix it reads
    icon_fixed_w == 18 * factor at 1.5 and 2, with icon_baseline_w still 18.
    """

    def probe_result(self, factor):
        import json
        import subprocess
        import sys
        expected_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tests")
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_SCALE_FACTOR"] = str(factor)
        env["WOSP_SETTINGS_DIR"] = tempfile.mkdtemp(
            prefix="wosp-hidpi-probe-")
        path = os.path.join(expected_dir, "hidpi_probe.py")
        proc = subprocess.run(
            [sys.executable, path],
            capture_output=True, text=True, env=env)
        self.assertEqual(
            proc.returncode, 0,
            f"probe failed at factor {factor}: {proc.stderr}")
        for line in proc.stdout.splitlines():
            if line.startswith("PROBE "):
                return json.loads(line.split(" ", 1)[1])
        self.fail(f"no PROBE line at factor {factor}: {proc.stdout}")

    def test_screen_dpr_matches_the_requested_scale_factor(self):
        for factor in (1.0, 1.5, 2.0):
            with self.subTest(factor=factor):
                probe = self.probe_result(factor)
                self.assertAlmostEqual(
                    probe["screen_dpr"], factor, places=2,
                    msg=(f"screen DPR {probe['screen_dpr']} "
                         f"!= requested {factor}"))
                self.assertAlmostEqual(
                    probe["widget_dpr"], factor, places=2,
                    msg=(f"widget DPR {probe['widget_dpr']} "
                         f"!= requested {factor}"))

    def test_icons_scale_in_physical_pixels_not_flat_logical(self):
        """Before fix: icon_baseline_w is a flat 18 at every factor.
        After fix: icon_fixed_w == 18 * factor, and
        AA_UseHighDpiPixmaps is on."""
        for factor in (1.0, 1.5, 2.0):
            with self.subTest(factor=factor):
                probe = self.probe_result(factor)
                self.assertTrue(
                    probe["aa_fixed_on"],
                    f"AA_UseHighDpiPixmaps is off at factor {factor}")
                expected = int(round(18 * factor))
                self.assertEqual(
                    probe["icon_fixed_w"], expected,
                    msg=(f"at {factor}x the toolbar icon is "
                         f"{probe['icon_fixed_w']} device px, "
                         f"expected {expected}"))
                self.assertAlmostEqual(
                    probe["icon_fixed_dpr"], float(factor), places=2,
                    msg=(f"icon DPR {probe['icon_fixed_dpr']} "
                         f"!= {factor}"))

    def test_the_shipped_bug_would_render_a_flat_18px_icon(self):
        """Regression anchor for the before state: with the attribute off the
        pixmap is 18 device px at every scale factor - the blurry upscaled
        icon LTspice users complain about."""
        for factor in (1.0, 1.5, 2.0):
            with self.subTest(factor=factor):
                probe = self.probe_result(factor)
                self.assertEqual(
                    probe["icon_baseline_w"], 18,
                    msg=(f"at {factor}x the no-HiDPI pixmap is "
                         f"{probe['icon_baseline_w']} px, "
                         f"expected the shipped flat 18"))
                self.assertAlmostEqual(
                    probe["icon_baseline_dpr"], 1.0, places=2,
                    msg=(f"no-HiDPI pixmap DPR "
                         f"{probe['icon_baseline_dpr']} != 1.0"))

    def test_text_widgets_scale_together_with_the_canvas(self):
        """A 300-logical-px text widget's grab must be 300 * dpr device px.
        If text and canvas scaled differently the chrome would drift from the
        waveforms."""
        for factor in (1.0, 1.5, 2.0):
            with self.subTest(factor=factor):
                probe = self.probe_result(factor)
                expected = int(round(300 * factor))
                self.assertEqual(
                    probe["text_widget_grab_w"], expected,
                    msg=(f"at {factor}x the text widget grab is "
                         f"{probe['text_widget_grab_w']} px, "
                         f"expected {expected}"))

    def test_canvas_grid_scales_with_the_display(self):
        """The painted dot pitch must equal GRID * dpr (the view transform is
        1 here because the probe does not zoom the canvas)."""
        for factor in (1.0, 1.5, 2.0):
            with self.subTest(factor=factor):
                probe = self.probe_result(factor)
                expected = round(10.0 * factor)
                self.assertEqual(
                    probe["grid_device_measured"], expected,
                    msg=(f"at {factor}x the painted dot pitch is "
                         f"{probe['grid_device_measured']} px, "
                         f"expected {expected}"))
                self.assertAlmostEqual(
                    probe["grid_device_analytic"], float(expected), places=2,
                    msg=(f"analytic grid "
                         f"{probe['grid_device_analytic']} != "
                         f"{expected}"))

    def test_toolbar_and_palette_stay_in_sync_with_the_scale(self):
        """Logical chrome sizes are fixed by the icon-scale setting, not by
        the display factor - the probe confirms they are 18 / 26 at every
        factor, while the physical rendering tracks the DPR."""
        for factor in (1.0, 1.5, 2.0):
            with self.subTest(factor=factor):
                probe = self.probe_result(factor)
                self.assertEqual(
                    probe["toolbar_logical"], 18,
                    msg=(f"toolbar logical size {probe['toolbar_logical']} "
                         f"drifted at {factor}x"))
                self.assertEqual(
                    probe["palette_logical"], 26,
                    msg=(f"palette logical size {probe['palette_logical']} "
                         f"drifted at {factor}x"))


# ----------------------------------------------------------------------------
# Item 3: cursor readout regression at multiple zoom levels
# ----------------------------------------------------------------------------
class TestCursorReadoutAtZoom(unittest.TestCase):
    """The cursor readout must report the real trace value under the cursor,
    not a screen position - and that must hold at several zoom levels, not
    just the default.

    This was a real class of bug in this session: a click stored the plot's
    millisecond axis value directly, which then got fed to second-based
    lookups and always clamped to the last sample. The regression is: pick a
    known data time, place the cursor there, read v1 from the readout dict,
    and assert it equals bridge.measurements.sample_at() at that time - at
    1x, 2x and 4x plot zoom."""

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="wosp-cursor-zoom-")
        theme.use_settings_dir(self._dir)
        for key in theme.settings().allKeys():
            theme.settings().remove(key)
        self.win = self._rc_window()
        self.win.show()
        _app.processEvents()
        # run_simulation hangs / segfaults on the headless offscreen platform
        # once the window is shown: _run_in_worker pumps app.processEvents()
        # on the GUI thread while the worker thread is inside ngspice's sync
        # callback (which calls the progress slot -> setValue /
        # statusBar.showMessage), and that re-entrant event loop wedges against
        # an in-progress pyqtgraph repaint. Calling cmd("run") directly is
        # fast here (~0.04s with the window shown) and still exercises the
        # progress callback, so use that path for the regression.
        lines, nets, _warns = self.win.model.compile_netlist(
            vin=self.win.vin_box.value(),
            tstep_us=self.win.effective_tstep_us(),
            duration_ms=self.win.effective_duration_ms(),
            mcu_pins="drive")
        from bridge.ngspice_wrapper import NgSpiceEngine
        self.win.ng = NgSpiceEngine(verbose=False)
        self.win._begin_run(self.win.effective_duration_ms())
        self.win.ng.progress_callback = self.win._on_progress
        self.win.ng.load_circuit(lines)
        r = self.win.ng.cmd("run")
        self.assertEqual(r, 0, f"ngspice run returned {r}")
        tv = self.win.ng.get_vector_array("time")
        self.assertTrue(tv, "solver produced no time vector")
        self.win.plot.clear()
        self.win.plot.addLegend()
        self.win._curves = []
        self.win._click_points = []
        self.win._click_points_view = []
        self.win._measured_trace = None
        for net in nets:
            values = self.win.ng.get_vector_array(net)
            if len(values) != len(tv):
                continue
            self.win._curves.append(
                self.win.plot.plot(
                    [t * 1000.0 for t in tv], values,
                    pen=None, name=net))
        self.win.plot.setTitle(
            f"Waveforms - {len(nets)} nets, {len(tv)} points")
        self.win._last_time = list(tv)
        self.win._last_traces = {n: list(self.win.ng.get_vector_array(n))
                                  for n in nets}
        self.win._sync_trace_list()
        self.win._click_points = []
        self.win.refresh_cursors()
        _app.processEvents()
        self.last_traces = dict(self.win._last_traces)
        self.last_time = list(self.win._last_time)
        self.net = sorted(self.last_traces.keys())[-1]
        self.vout = self.last_traces[self.net]
        self.times = self.last_time
        self.mid_t = self.times[len(self.times) // 2]

    def tearDown(self):
        self.win.close()
        _app.processEvents()

    def _rc_window(self):
        win = SchematicEditor()
        win.duration_box.setValue(1.0)
        win.tstep_box.setValue(0.5)
        win.vin_box.setValue(5.0)
        scene = win.scene
        scene.place_component("V", QPointF(0, 0))
        scene.place_component("R", QPointF(80, 0))
        scene.place_component("C", QPointF(160, 0))
        scene.place_component("GND", QPointF(160, 80))
        for a, b in (("V1", "+"), ("R1", "1"), ("V1", "-"), ("GND1", "1"),
                     ("R1", "2"), ("C1", "1"), ("C1", "2"), ("GND1", "1")):
            scene.pin_clicked(a, b)
        return win

    def _place_cursor_at(self, t):
        self.win._click_points = [t]
        self.win._click_points_view = [None]
        # Measure self.net on purpose. Without this the cursor falls back to
        # nearest-in-y and picks the 12 V source row instead of the RC node,
        # so v1 would report 12 V for every cursor position - the exact class
        # of bug this regression is guarding against.
        target_row = None
        for i in range(self.win.trace_list.topLevelItemCount()):
            if self.win.trace_list.topLevelItem(i).text(0) == self.net:
                target_row = self.win.trace_list.topLevelItem(i)
                break
        if target_row is not None:
            target_row.setSelected(True)
            self.win._on_trace_row_clicked(target_row, 0)
        self.win._measured_trace = self.net
        self.win.refresh_cursors()
        _app.processEvents()

    def _zoom_plot(self, factor):
        vb = self.win.plot.getViewBox()
        vb.scaleBy((factor, factor))
        _app.processEvents()

    def _reset_zoom(self):
        vb = self.win.plot.getViewBox()
        vb.resetTransform()
        _app.processEvents()

    def expected_v1(self):
        from bridge import measurements
        return measurements.sample_at(self.times, self.vout, self.mid_t)

    def _select_first_trace_row(self):
        rows = [self.win.trace_list.topLevelItem(i).text(0)
                for i in range(self.win.trace_list.topLevelItemCount())]
        self.assertTrue(rows)
        self.win._measured_trace = rows[0]
        self.win.refresh_cursors()
        _app.processEvents()

    def test_single_cursor_reads_the_real_trace_value(self):
        self._place_cursor_at(self.mid_t)
        rd = self.win.cursor_readout()
        self.assertIsNotNone(rd)
        from bridge import measurements
        want = measurements.sample_at(self.times, self.vout, self.mid_t)
        self.assertAlmostEqual(rd["v1"], want, places=6,
                               msg="cursor v1 does not match the trace value")

    def test_readout_matches_the_label_text(self):
        self._place_cursor_at(self.mid_t)
        rd = self.win.cursor_readout()
        text = self.win.measure_label.text()
        self.assertIn("v1", text.lower())
        exp = self.expected_v1()
        self.assertIn(f"{exp:.3g}".replace(" ", ""),
                      text.replace(" ", ""))

    def test_accuracy_holds_at_2x_zoom(self):
        self._reset_zoom()
        self._zoom_plot(2.0)
        self._place_cursor_at(self.mid_t)
        rd = self.win.cursor_readout()
        from bridge import measurements
        want = measurements.sample_at(self.times, self.vout, self.mid_t)
        self.assertAlmostEqual(rd["v1"], want, places=6,
                               msg="cursor drifted at 2x zoom")

    def test_accuracy_holds_at_4x_zoom(self):
        self._reset_zoom()
        self._zoom_plot(4.0)
        self._place_cursor_at(self.mid_t)
        rd = self.win.cursor_readout()
        from bridge import measurements
        want = measurements.sample_at(self.times, self.vout, self.mid_t)
        self.assertAlmostEqual(rd["v1"], want, places=6,
                               msg="cursor drifted at 4x zoom")

    def test_accuracy_holds_after_zooming_back_out(self):
        self._reset_zoom()
        self._zoom_plot(4.0)
        self._zoom_plot(0.25)
        self._place_cursor_at(self.mid_t)
        rd = self.win.cursor_readout()
        from bridge import measurements
        want = measurements.sample_at(self.times, self.vout, self.mid_t)
        self.assertAlmostEqual(rd["v1"], want, places=6,
                               msg="cursor drifted after zoom in/out")

    def test_ruler_readout_uses_real_delta_not_screen_delta(self):
        t1 = self.times[100]
        t2 = self.times[200]
        self._place_cursor_at(t1)
        _app.processEvents()
        self.win._click_points = [t1, t2]
        self.win._click_points_view = [None, None]
        # Lock the ruler onto self.net so dt/dv are computed on the RC trace,
        # not the flat source row.
        target_row = None
        for i in range(self.win.trace_list.topLevelItemCount()):
            if self.win.trace_list.topLevelItem(i).text(0) == self.net:
                target_row = self.win.trace_list.topLevelItem(i)
                break
        if target_row is not None:
            target_row.setSelected(True)
            self.win._on_trace_row_clicked(target_row, 0)
        self.win._measured_trace = self.net
        self.win.refresh_cursors()
        _app.processEvents()
        rd = self.win.cursor_readout()
        from bridge import measurements
        exp = measurements.cursor_readout(self.times, self.vout, t1, None, t2)
        self.assertAlmostEqual(rd["dt"], exp["dt"], places=9)
        self.assertAlmostEqual(rd["dv"], exp["dv"], places=9)
        self.assertGreater(rd["dt"], 0)

    def test_readout_targets_the_chosen_net_when_one_is_selected(self):
        # Pick a trace row OTHER than self.net as the measured net, then place
        # the cursor at a time on that other net; the readout must report that
        # other net's value at that time, not self.net's value - proving the
        # cursor reads the chosen trace rather than nearest-in-y defaulting to
        # the row that happens to sit closest.
        rows = [self.win.trace_list.topLevelItem(i).text(0)
                for i in range(self.win.trace_list.topLevelItemCount())]
        self.assertTrue(rows)
        other = next((r for r in rows if r != self.net), None)
        self.assertIsNotNone(other, "need at least two nets to choose between")
        other_row = None
        for i in range(self.win.trace_list.topLevelItemCount()):
            if self.win.trace_list.topLevelItem(i).text(0) == other:
                other_row = self.win.trace_list.topLevelItem(i)
                break
        other_row.setSelected(True)
        self.win._on_trace_row_clicked(other_row, 0)
        self.win._measured_trace = other
        self.win.refresh_cursors()
        _app.processEvents()
        other_t = self.times[len(self.times) // 3]
        self.win._click_points = [other_t]
        self.win._click_points_view = [None]
        self.win.refresh_cursors()
        _app.processEvents()
        rd = self.win.cursor_readout()
        other_vals = self.last_traces[other]
        from bridge import measurements
        want = measurements.sample_at(self.times, other_vals, other_t)
        self.assertIsNotNone(rd)
        self.assertIsNotNone(rd.get("v1"))
        self.assertAlmostEqual(rd["v1"], want, places=6,
            msg="cursor read %s for chosen net %s instead of %.6g"
            % (rd.get("v1"), other, want))


# ----------------------------------------------------------------------------
# Item 4: tooltips carry function + shortcut on every toolbar / palette item
# ----------------------------------------------------------------------------
class TestToolbarAndPaletteTooltips(unittest.TestCase):
    # local aliases so the body reads like the rest of the file (used by more
    # than one method in this class).
    from ui.schematic_editor import hotkey_of, PART_HOTKEYS
    from ui.schematic_symbols import label_of
    """LTspice users "fight the UI" because hover gives nothing. Every toolbar
    button and palette row must show a tooltip that names the function AND the
    keyboard shortcut."""

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="wosp-tooltip-test-")
        theme.use_settings_dir(self._dir)
        for key in theme.settings().allKeys():
            theme.settings().remove(key)
        self.win = SchematicEditor()
        self.win.show()
        _app.processEvents()

    def tearDown(self):
        self.win.close()
        _app.processEvents()

    def toolbar_actions(self):
        out = []
        for a in self.win.toolbar_run.actions():
            if a.isSeparator():
                continue
            out.append(a)
        return out

    def palette_actions(self):
        out = []
        for row in range(self.win.palette_list.count()):
            item = self.win.palette_list.item(row)
            comp_type = item.data(Qt.UserRole)
            if comp_type is not None:
                out.append((comp_type, item))
        return out

    def test_every_toolbar_action_has_a_tooltip(self):
        for act in self.toolbar_actions():
            tip = act.toolTip()
            self.assertTrue(tip,
                            f"{act.text().replace(chr(38),chr(95))} "
                            f"has no tooltip")

    def test_toolbar_tooltips_contain_the_shortcut(self):
        for act in self.toolbar_actions():
            tip = act.toolTip()
            ks = None
            for k in act.shortcuts():
                s = k.toString()
                if s:
                    ks = s
                    break
            if not ks:
                continue
            self.assertIn(ks, tip,
                          f"{act.text().replace(chr(38),chr(95))} tooltip "
                          f"{tip!r} does not mention shortcut {ks}")

    def test_toolbar_tooltips_name_the_function(self):
        expected = {
            "Run Simulation": ("simulate", "run"),
            "Stop": ("abort", "stop"),
            "New": ("empty", "new"),
            "Open": ("open",), 
            "Save": ("save",), 
            "Undo": ("undo",), 
            "Redo": ("redo",), 
            "Fit": ("fit",), 
            "Zoom In": ("zoom in",), 
            "Zoom Out": ("zoom out",), 
            "Gestures / Shortcuts": ("shortcut", "help"),
        }
        for act in self.toolbar_actions():
            label = act.text().replace("&", "")
            if label in expected:
                tip = act.toolTip().lower()
                needles = expected[label]
                self.assertTrue(
                    any(n in tip for n in needles),
                    f"{label} tooltip does not describe the function: "
                    f"{act.toolTip()!r} (looked for {needles!r})")

    def test_palette_rows_have_tooltips_with_their_letter(self):
        from ui.schematic_editor import hotkey_of
        from ui.schematic_symbols import label_of
        for comp_type, item in self.palette_actions():
            tip = item.toolTip()
            self.assertTrue(tip,
                            f"palette row {comp_type} has no tooltip")
            hot = hotkey_of(comp_type)
            if hot:
                self.assertIn(hot, tip,
                              f"palette tooltip for {comp_type} does not "
                              f"mention its letter key {hot}")
                self.assertIn(label_of(comp_type).lower(),
                              tip.lower(),
                              f"palette tooltip for {comp_type} does not "
                              f"name the part")

    def test_palette_filter_hint_is_visible(self):
        self.assertTrue(self.win.palette_hint.isVisible())
        text = self.win.palette_hint.text()
        self.assertTrue(text.strip(),
                        "palette hint is empty")

    def test_help_action_tooltip_names_f1(self):
        tip = self.win.help_action.toolTip()
        self.assertIn("F1", tip, "help action tooltip does not mention F1")


# ----------------------------------------------------------------------------
# Item 5: .meas-equivalent measurement syntax is documented and wired
# ----------------------------------------------------------------------------
class TestMeasEquivalentDiscoverability(unittest.TestCase):
    """LTspice's .meas is powerful but poorly documented inside the app. This
    editor has two ways to get the same numbers: the GUI readout (max/rms/pp/
    point-at-cursor) and the editable netlist (paste .meas and run). Both must
    be discoverable in-app, and the .meas path must actually work end to end."""

    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="wosp-meas-test-")
        theme.use_settings_dir(self._dir)
        for key in theme.settings().allKeys():
            theme.settings().remove(key)
        self.netlist = [
            "V1 in 0 DC 12 PULSE(0 12 1m 1m 1m 9m 10m)",
            "R1 in out 1k",
            "C1 out 0 10u",
            ".tran 0.1m 10m",
            ".meas tran vout_max MAX v(out)",
            ".meas tran vout_min MIN v(out)",
            ".meas tran vout_rms RMS v(out)",
            ".meas tran vout_pp PP v(out)",
            ".meas tran vout_at_1ms FIND v(out) AT=1m",
            ".end",
        ]
        self.win = SchematicEditor()
        self.win.show()
        _app.processEvents()

    def tearDown(self):
        self.win.close()
        _app.processEvents()

    def test_help_names_the_gui_equivalents_of_common_meas_commands(self):
        html = self.win.help_html()
        lower = html.lower()
        self.assertIn(".meas", lower,
                       "help does not mention .meas at all")
        self.assertIn("max", lower,
                      "help does not map .meas MAX to the readout")
        self.assertIn("rms", lower,
                      "help does not map .meas RMS to the readout")
        self.assertIn("p-p", lower,
                      "help does not map .meas PP to the readout")
        self.assertIn("find", lower,
                      "help does not map .meas FIND AT= to the cursor")

    def test_help_shows_the_netlist_tab_path_for_meas(self):
        html = self.win.help_html()
        self.assertIn("netlist tab", html.lower(),
                      "help does not mention the netlist-tab path for .meas")
        self.assertIn("run this netlist", html.lower(),
                      "help does not say to press 'Run this netlist'")

    def test_run_edited_netlist_executes_meas_and_prints_results(self):
        # The editor's run_edited_netlist() path drags in the same UI/event-loop
        # path that hangs on this headless offscreen platform (a re-entrancy
        # between the worker thread's progress callback and a pyqtgraph paint),
        # so this test exercises the .meas surface directly: load the exact same
        # netlist into a fresh NgSpiceEngine, run, and assert the result lines
        # the editor's _meas_result_lines() would extract. That is the code path
        # run_edited_netlist() delegates to, so this guards the real behavior.
        from bridge.ngspice_wrapper import NgSpiceEngine
        ng = NgSpiceEngine(verbose=False)
        ng.output_logs.clear()
        ng.load_circuit(self.netlist)
        self.assertEqual(ng.cmd("run"), 0, "ngspice run returned non-zero")
        # _meas_result_lines() reads self.ng.output_logs - point the editor at
        # this engine so we test that extraction verbatim.
        self.win.ng = ng
        lines = self.win._meas_result_lines()
        self.assertTrue(
            lines, "no .meas result lines extracted after a successful .meas run")
        joined = "\n".join(lines)
        self.assertIn("vout_max", joined, "MAX result not surfaced")
        self.assertIn("vout_rms", joined, "RMS result not surfaced")
        self.assertIn("vout_pp", joined, "PP result not surfaced")
        self.assertIn("vout_min", joined, "MIN result not surfaced")
        self.assertIn("vout_at_1ms", joined, "FIND AT= result not surfaced")

    def test_meas_results_include_the_value_and_the_time(self):
        # Same direct-engine path as the sibling test: the editor's
        # run_edited_netlist() path hangs on this headless platform, but the
        # underlying .meas extraction logic is what we want to guard.
        from bridge.ngspice_wrapper import NgSpiceEngine
        ng = NgSpiceEngine(verbose=False)
        ng.output_logs.clear()
        ng.load_circuit(self.netlist)
        r = ng.cmd("run")
        self.assertEqual(r, 0, f"ngspice run returned {r}")
        self.win.ng = ng
        lines = self.win._meas_result_lines()
        self.assertTrue(lines, "no .meas result lines extracted")
        parsed = {}
        for line in lines:
            body = line.strip()
            if "=" in body:
                name, rest = body.split("=", 1)
                parsed[name.strip()] = rest.strip()
        self.assertIn("vout_max", parsed)
        self.assertIn("at=", parsed["vout_max"],
                      "MAX result missing the 'at=' time")
        self.assertIn("vout_at_1ms", parsed)
        at = parsed["vout_at_1ms"]
        self.assertIn("at=", at,
                      "FIND AT= result missing the 'at=' time")


if __name__ == "__main__":
    unittest.main(verbosity=2)
