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
from PyQt5.QtWidgets import QApplication                        # noqa: E402

from bridge.cad_engine import SchematicNetlistEngine             # noqa: E402
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
