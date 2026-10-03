"""
schematic_symbols.py - Component symbol library for the WOSP schematic editor.

Pure data (no Qt import) so it can be validated headlessly against the netlist
compiler in bridge/cad_engine.py.

Pin names here MUST match the canonical pin names the compiler expects
(SchematicNetlistEngine._CANONICAL_PINS), otherwise wires resolve to the wrong
SPICE terminal.

Coordinate convention: component origin is the symbol centre, +x right, +y down.
Pin coordinates are multiples of GRID so placed parts stay on the snap grid.
"""

GRID = 10

# type -> {
#   label:   palette text
#   prefix:  auto designator prefix (next free "<prefix><n>" is used)
#   value:   default value string handed to the netlist compiler
#   pins:    [(pin_name, x, y), ...] in canonical compiler order
#   extent:  (x, y, w, h) bounding box incl. label space
# }
SYMBOLS = {
    "R": {
        "label": "Resistor",
        "prefix": "R",
        "value": "10k",
        "pins": [("1", -30, 0), ("2", 30, 0)],
        "extent": (-50, -26, 100, 52),
    },
    "C": {
        "label": "Capacitor",
        "prefix": "C",
        "value": "100n",
        "pins": [("1", -30, 0), ("2", 30, 0)],
        "extent": (-50, -26, 100, 52),
    },
    "L": {
        "label": "Inductor",
        "prefix": "L",
        "value": "47u",
        "pins": [("1", -30, 0), ("2", 30, 0)],
        "extent": (-50, -26, 100, 52),
    },
    "V": {
        "label": "Voltage Source",
        "prefix": "V",
        "value": "12",
        "pins": [("+", -30, 0), ("-", 30, 0)],
        "extent": (-50, -26, 100, 52),
    },
    "I": {
        "label": "Current Source",
        "prefix": "I",
        "value": "1m",
        "pins": [("+", -30, 0), ("-", 30, 0)],
        "extent": (-50, -26, 100, 52),
    },
    "D": {
        "label": "Diode",
        "prefix": "D",
        "value": "",
        "pins": [("A", -30, 0), ("K", 30, 0)],
        "extent": (-50, -26, 100, 52),
    },
    "MOSFET": {
        "label": "MOSFET (N-Channel)",
        "prefix": "M",
        "value": "",
        "pins": [("D", 0, -30), ("G", -30, 0), ("S", 0, 30)],
        "extent": (-50, -46, 100, 92),
    },
    "GND": {
        "label": "Ground",
        "prefix": "GND",
        "value": "",
        "pins": [("1", 0, 0)],
        "extent": (-20, -26, 40, 52),
    },
    "MCU": {
        "label": "MCU (generic, co-sim)",
        "prefix": "U",
        "value": "ESP32",
        "pins": [
            ("GPIO18", -60, -20),
            ("GPIO17", -60, 0),
            ("ADC0", -60, 20),
            ("GPIO5", 60, -20),
            ("GND", 60, 20),
        ],
        "extent": (-80, -50, 160, 100),
    },
}

# Board-specific MCU symbols. The pin lists are the real header pin names, so a
# GPIO profile written against an Arduino sketch ("D5") means the same thing
# here. Boards are described as (left pins, right pins) and laid out on a grid.
_BOARD_PITCH = 10          # editor grid units between pin rows


def _board_pins(number, prefix, count, start=0):
    return [f"{prefix}{i}" for i in range(start, start + count)]


def _make_board(label, value, left, right, footprint=""):
    """Build a two-column MCU symbol from pin-name lists."""
    rows = max(len(left), len(right))
    half = (rows // 2) * _BOARD_PITCH
    top = -half
    pins = []
    for i, name in enumerate(left):
        pins.append((name, -70, top + i * _BOARD_PITCH))
    for i, name in enumerate(right):
        pins.append((name, 70, top + i * _BOARD_PITCH))
    span = rows * _BOARD_PITCH
    return {
        "label": label,
        "prefix": "U",
        "value": value,
        "pins": pins,
        "extent": (-90, top - 20, 180, span + 40),
        "footprint": footprint,
    }


def _arduino_pins():
    """Uno and Nano share the ATmega328P header layout."""
    left = [f"D{i}" for i in range(10)] + [f"A{i}" for i in range(6)]
    right = [f"D{i}" for i in range(10, 14)] + ["5V", "3V3", "GND", "GND", "VIN", "AREF"]
    return left, right


def _mega_pins():
    left = [f"D{i}" for i in range(22)]
    right = ([f"D{i}" for i in range(22, 54)]
             + [f"A{i}" for i in range(16)]
             + ["5V", "3V3", "GND", "GND", "VIN", "AREF"])
    return left, right


def _stm32f103_pins():
    left = [f"PB{i}" for i in range(16)] + [f"PA{i}" for i in range(8)]
    right = ([f"PA{i}" for i in range(8, 16)] + ["3V3", "5V", "GND", "GND",
                                                 "NRST", "SWDIO", "SWCLK"])
    return left, right


def _esp32_pins():
    left = [f"GPIO{i}" for i in range(0, 16)]
    right = ([f"GPIO{i}" for i in range(16, 32)] + ["3V3", "5V", "GND", "GND",
                                                    "EN", "VP", "VN"])
    return left, right


_uno_left, _uno_right = _arduino_pins()
_mega_left, _mega_right = _mega_pins()
_f103_left, _f103_right = _stm32f103_pins()
_esp32_left, _esp32_right = _esp32_pins()

SYMBOLS.update({
    "ARDUINO_UNO": _make_board("Arduino Uno", "ATmega328P",
                               _uno_left, _uno_right, "Package_DIP:DIP-28_W7.62mm"),
    "ARDUINO_NANO": _make_board("Arduino Nano", "ATmega328P",
                                _uno_left, _uno_right, "Package_QFP:LQFP-48_7x7mm_P0.5mm"),
    "ARDUINO_MEGA": _make_board("Arduino Mega 2560", "ATmega2560",
                                _mega_left, _mega_right, "Package_QFP:LQFP-64_10x10mm_P0.5mm"),
    "STM32F103": _make_board("STM32F103C8 (blue pill)", "STM32F103C8T6",
                             _f103_left, _f103_right, "Package_QFP:LQFP-48_7x7mm_P0.5mm"),
    "ESP32": _make_board("ESP32 DevKit", "ESP32-WROOM-32",
                         _esp32_left, _esp32_right, "Module:ESP32-WROOM-32"),
    "ESP32S3": _make_board("ESP32-S3 DevKit", "ESP32-S3-WROOM-1",
                           _esp32_left, _esp32_right, "Module:ESP32-S3-WROOM-1"),
})

# Palette grouping, in display order.
PALETTE_GROUPS = [
    ("Passives", ["R", "C", "L"]),
    ("Sources", ["V", "I"]),
    ("Semiconductors", ["D", "MOSFET"]),
    ("Reference", ["GND"]),
    ("Arduino", ["ARDUINO_UNO", "ARDUINO_NANO", "ARDUINO_MEGA"]),
    ("STM32", ["STM32F103"]),
    ("Espressif", ["ESP32", "ESP32S3"]),
    ("Other MCU", ["MCU"]),
]


def pins_of(comp_type: str):
    """[(name, x, y)] for a type; empty tuple for unknown types."""
    spec = SYMBOLS.get(comp_type)
    return spec["pins"] if spec else []


def label_of(comp_type: str) -> str:
    spec = SYMBOLS.get(comp_type)
    return spec["label"] if spec else comp_type


def default_value_of(comp_type: str) -> str:
    spec = SYMBOLS.get(comp_type)
    return spec["value"] if spec else ""


def prefix_of(comp_type: str) -> str:
    spec = SYMBOLS.get(comp_type)
    return spec["prefix"] if spec else "X"


def extent_of(comp_type: str):
    spec = SYMBOLS.get(comp_type)
    return spec["extent"] if spec else (-40, -26, 80, 52)