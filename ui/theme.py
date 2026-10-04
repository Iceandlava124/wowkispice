"""
theme.py - one palette, one stylesheet, two appearances.

Everything visual in the editor reads its colours from a Palette here. Nothing
else hard-codes a colour, so switching appearance is apply_theme() and a repaint.
Dark is the default because long waveform sessions are easier on the eyes that
way; light is one menu click away and the choice is remembered between launches.

The schematic canvas is the awkward case: symbols are drawn in ink colours
defined in schematic_items. set_symbol_palette() rewrites those module globals so
the canvas follows the theme, and returns the scene list to repaint.
"""

from dataclasses import dataclass
import os

from PyQt5.QtGui import QColor, QFont
from PyQt5.QtCore import QSettings

APP_NAME = "WOSP"
ORG_NAME = "Wowkispice"
SETTINGS_VERSION = 1


@dataclass(frozen=True)
class Palette:
    name: str
    # chrome
    window: str          # QMainWindow background
    panel: str           # docks, tab bars, group boxes
    base: str            # inputs, list views, text panes
    alt: str             # hovered rows
    text: str            # primary foreground
    dim: str             # secondary foreground
    border: str          # frame / separator lines
    accent: str          # primary action, links, focus
    accent_text: str     # text drawn on accent
    selection: str       # selected row background
    selection_text: str
    hover: str           # toolbar button hover
    # canvas
    canvas: str          # schematic background
    canvas_dot: str      # grid dot at the minor pitch
    canvas_dot_major: str
    canvas_ruler_bg: str
    canvas_ruler_text: str
    canvas_ruler_line: str
    # waveform plot
    plot_bg: str
    plot_grid: str
    plot_axis: str
    plot_label: str
    # symbols on the canvas
    ink: str
    wire: str
    pin: str
    pin_hover: str
    symbol_label: str
    symbol_fill: str

    def q(self, key):
        return getattr(self, key)

    def qcolor(self, key) -> QColor:
        return QColor(getattr(self, key))


DARK = Palette(
    name="dark",
    window="#191d22",
    panel="#21262d",
    base="#14181c",
    alt="#2a313a",
    text="#d8dee6",
    dim="#8b95a3",
    border="#313944",
    accent="#3d8bfd",
    accent_text="#ffffff",
    selection="#2b5b96",
    selection_text="#ffffff",
    hover="#2c333c",
    canvas="#12151a",
    canvas_dot="#252c34",
    canvas_dot_major="#333d47",
    canvas_ruler_bg="#1b2027",
    canvas_ruler_text="#8b95a3",
    canvas_ruler_line="#3a434e",
    plot_bg="#12151a",
    plot_grid="#232a32",
    plot_axis="#6b7e94",
    plot_label="#9aa4b0",
    ink="#d6dde5",
    wire="#5aa9ff",
    pin="#ff6b5e",
    pin_hover="#4ade80",
    symbol_label="#9aa4b0",
    symbol_fill="#1d232b",
)

LIGHT = Palette(
    name="light",
    window="#eef0f3",
    panel="#f5f6f8",
    base="#ffffff",
    alt="#e6e9ee",
    text="#1b2026",
    dim="#5d6673",
    border="#c6ccd4",
    accent="#0a66c2",
    accent_text="#ffffff",
    selection="#c6def5",
    selection_text="#0b1b2b",
    hover="#dfe3e9",
    canvas="#ffffff",
    canvas_dot="#e6e9ee",
    canvas_dot_major="#cdd3db",
    canvas_ruler_bg="#f0f2f5",
    canvas_ruler_text="#5d6673",
    canvas_ruler_line="#c6ccd4",
    plot_bg="#ffffff",
    plot_grid="#e6e9ee",
    plot_axis="#3d454f",
    plot_label="#5d6673",
    ink="#1b2026",
    wire="#12498c",
    pin="#c0392b",
    pin_hover="#1a9850",
    symbol_label="#5d6673",
    symbol_fill="#eef3fb",
)

PALETTES = {"dark": DARK, "light": LIGHT}

_current = DARK


def current() -> Palette:
    return _current


def palette_named(name: str) -> Palette:
    return PALETTES.get(name, DARK)


def ui_font(size=9, bold=False):
    f = QFont("Segoe UI" if _current.name == "dark" else "Segoe UI", size)
    f.setBold(bold)
    return f


def mono_font(size=9, bold=False):
    f = QFont("Cascadia Mono")
    if f.family() == "Cascadia Mono":            # not present on every machine
        f = QFont("Consolas", size)
    else:
        f.setPointSize(size)
    f.setStyleHint(QFont.Monospace)
    f.setBold(bold)
    return f


def qss(p: Palette) -> str:
    """The application-wide stylesheet. Qt has no cascade, so every role the
    editor uses is spelled out here - change one and all of them follow."""
    return f"""
QWidget {{
    background: {p.window};
    color: {p.text};
    font-size: 9pt;
}}
QMainWindow, QDialog {{ background: {p.window}; }}

QLabel {{ background: transparent; }}
QLabel[muted="true"] {{ color: {p.dim}; }}

QToolTip {{
    background: {p.alt};
    color: {p.text};
    border: 1px solid {p.border};
    padding: 4px 6px;
}}

/* ---- toolbars ---------------------------------------------------- */
QToolBar {{
    background: {p.panel};
    border: 0px;
    border-bottom: 1px solid {p.border};
    spacing: 2px;
    padding: 3px 4px;
}}
QToolBar QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 7px;
    color: {p.text};
}}
QToolBar QToolButton:hover {{ background: {p.hover}; border-color: {p.border}; }}
QToolBar QToolButton:pressed {{ background: {p.accent}; color: {p.accent_text}; }}
QToolBar QToolButton:disabled {{ color: {p.dim}; }}
QToolBar::separator {{
    background: {p.border};
    width: 1px;
    margin: 4px 6px;
}}
QToolBar QLabel {{ color: {p.dim}; padding-right: 2px; }}
QToolBar QDoubleSpinBox, QToolBar QComboBox {{ min-width: 62px; }}

/* ---- menus ------------------------------------------------------- */
QMenuBar {{ background: {p.panel}; border-bottom: 1px solid {p.border}; }}
QMenuBar::item {{ padding: 5px 10px; background: transparent; }}
QMenuBar::item:selected {{ background: {p.hover}; }}
QMenu {{ background: {p.panel}; border: 1px solid {p.border}; padding: 4px; }}
QMenu::item {{ padding: 5px 26px 5px 22px; border-radius: 3px; }}
QMenu::item:selected {{ background: {p.accent}; color: {p.accent_text}; }}
QMenu::item:disabled {{ color: {p.dim}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 8px; }}

/* ---- docks and tabs ---------------------------------------------- */
QDockWidget {{ titlebar-close-icon: none; font-weight: 600; }}
QDockWidget::title {{
    background: {p.panel};
    padding: 6px 10px;
    border-bottom: 1px solid {p.border};
    color: {p.dim};
}}
QTabWidget::pane {{
    border: 1px solid {p.border};
    background: {p.window};
    top: -1px;
}}
QTabBar::tab {{
    background: {p.window};
    color: {p.dim};
    padding: 6px 14px;
    border: 1px solid {p.border};
    border-bottom: 0px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {p.panel}; color: {p.text}; }}
QTabBar::tab:hover:!selected {{ background: {p.alt}; color: {p.text}; }}

/* ---- inputs ------------------------------------------------------ */
QPushButton {{
    background: {p.alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 4px;
    padding: 5px 12px;
    min-height: 18px;
}}
QPushButton:hover {{ background: {p.hover}; border-color: {p.accent}; }}
QPushButton:pressed {{ background: {p.accent}; color: {p.accent_text}; }}
QPushButton:disabled {{ color: {p.dim}; border-color: {p.border}; }}
QPushButton[primary="true"] {{
    background: {p.accent};
    color: {p.accent_text};
    border-color: {p.accent};
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: {p.accent}; }}
QPushButton[primary="true"]:disabled {{ background: {p.alt}; color: {p.dim}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QComboBox {{
    background: {p.base};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {p.selection};
    selection-color: {p.selection_text};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QAbstractSpinBox:focus, QComboBox:focus {{ border-color: {p.accent}; }}
QLineEdit:disabled, QPlainTextEdit:disabled {{ color: {p.dim}; }}

QComboBox::drop-down {{ border: 0px; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {p.panel};
    color: {p.text};
    border: 1px solid {p.border};
    selection-background-color: {p.selection};
    selection-color: {p.selection_text};
    outline: 0px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {p.alt};
    border: 0px;
    width: 14px;
}}
QDoubleSpinBox::up-button {{ subcontrol-position: top right; }}
QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; }}

/* ---- list / tree views ------------------------------------------- */
QListWidget, QTreeWidget, QTreeView {{
    background: {p.base};
    alternate-background-color: {p.window};
    border: 1px solid {p.border};
    border-radius: 4px;
    outline: 0px;
}}
QListWidget::item {{ padding: 4px 6px; border-radius: 3px; }}
QListWidget::item:hover {{ background: {p.alt}; }}
QListWidget::item:selected {{ background: {p.selection}; color: {p.selection_text}; }}
QTreeWidget::item, QTreeView::item {{ padding: 3px 2px; }}
QTreeWidget::item:hover, QTreeView::item:hover {{ background: {p.alt}; }}
QTreeWidget::item:selected, QTreeView::item:selected {{
    background: {p.selection}; color: {p.selection_text};
}}
QHeaderView::section {{
    background: {p.panel};
    color: {p.dim};
    padding: 5px 8px;
    border: 0px;
    border-right: 1px solid {p.border};
    border-bottom: 1px solid {p.border};
    font-weight: 600;
}}
QTreeWidget::branch {{ background: transparent; }}

/* ---- scrollbars -------------------------------------------------- */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0px; }}
QScrollBar::handle {{ background: {p.border}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:hover {{ background: {p.dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0px; height: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ background: {p.window}; border: 0px; }}

/* ---- misc -------------------------------------------------------- */
QProgressBar {{
    background: {p.base};
    border: 1px solid {p.border};
    border-radius: 4px;
    text-align: center;
    height: 16px;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 3px; }}
QStatusBar {{
    background: {p.panel};
    border-top: 1px solid {p.border};
    color: {p.dim};
}}
QStatusBar::item {{ border: 0px; }}
QSplitter::handle {{ background: {p.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background: {p.accent}; }}
QGroupBox {{
    border: 1px solid {p.border};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0px 4px;
    color: {p.dim};
}}
QCheckBox, QRadioButton {{ background: transparent; spacing: 6px; }}
QMenuBar {{ font-size: 9pt; }}
"""


def apply_theme(app, name: str = None, persist: bool = True):
    """Install a palette as the process-wide appearance. Returns the palette."""
    global _current
    name = name or _current.name
    _current = palette_named(name)
    app.setStyleSheet(qss(_current))
    if persist:
        settings().setValue("appearance/name", _current.name)
    return _current


def cycle_theme(app, persist: bool = True):
    """Dark -> light -> dark. Returns the palette now in effect."""
    other = "light" if _current.name == "dark" else "dark"
    return apply_theme(app, other, persist=persist)


def settings() -> QSettings:
    """The one QSettings instance the editor uses.

    The format is passed explicitly rather than relying on
    QSettings.setDefaultFormat(), which PyQt5 does not honour for the
    (org, app) constructor - it silently falls back to the Windows registry
    and use_settings_dir() would have no effect.
    """
    return QSettings(QSettings.IniFormat, QSettings.UserScope, ORG_NAME, APP_NAME)


def use_settings_dir(path: str) -> str:
    """Point QSettings at an explicit directory and use the INI backend.

    Two callers: a portable install that ships next to its executable, and the
    test runner, which needs each suite to start from an empty profile. Without
    this, one suite's window-close writes settings that the next suite reads
    back and silently changes what a simulation does.
    """
    path = os.path.abspath(path)
    os.makedirs(path, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, path)
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, path)
    return path


_settings_dir = os.environ.get("WOSP_SETTINGS_DIR")
if _settings_dir:
    use_settings_dir(_settings_dir)


def set_symbol_palette(p) -> dict:
    """Rewrite the ink colours in schematic_items to match this palette.

    Returns the mapping that was written, so the caller can assert it applied
    and repaint the canvas. Imported lazily: theme.py must stay importable
    without the symbol layer for headless use.
    """
    from ui import schematic_items
    mapping = {
        "INK": QColor(p.ink),
        "WIRE_BLUE": QColor(p.wire),
        "PIN_RED": QColor(p.pin),
        "PIN_HOVER": QColor(p.pin_hover),
        "LABEL_GREY": QColor(p.symbol_label),
        "CANVAS_BG": QColor(p.canvas),
    }
    for key, value in mapping.items():
        setattr(schematic_items, key, value)
    return mapping


def pyqtgraph_colors(p) -> dict:
    """The handful of pyqtgraph theme keys the editor sets explicitly."""
    return {
        "background": p.plot_bg,
        "foreground": p.text,
        "axis": p.plot_axis,
        "grid": p.plot_grid,
        "label": p.plot_label,
    }
