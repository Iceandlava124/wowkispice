"""
test_firmware_gpio.py - MCU firmware loading and GPIO co-simulation.

1. Intel HEX parsing: real image, checksums, record types, error messages
2. ELF parsing: entry point, load address, loadable segments
3. GPIO profile validation and SPICE card generation
4. Logic analysis of a simulated pin (levels, duty, frequency)
5. End-to-end: a modelled GPIO pin drives real ngspice physics at the declared
   frequency and duty cycle
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge import firmware, gpio_model
from bridge.cad_engine import SchematicComponent, SchematicNetlistEngine
from bridge.ngspice_wrapper import NgSpiceEngine

def _hex_record(rectype, address, data):
    """Build a valid Intel HEX record (checksum computed, not hand-written)."""
    payload = bytes([len(data), (address >> 8) & 0xFF, address & 0xFF, rectype]) + bytes(data)
    checksum = (-sum(payload)) & 0xFF
    return ":" + payload.hex().upper() + f"{checksum:02X}"


# A tiny but genuine Intel HEX image: 16 bytes at 0x0800 plus 4 more, entry 0x0800
HEX_SAMPLE = "\n".join([
    _hex_record(0x00, 0x0800, bytes(range(0x10))),
    _hex_record(0x00, 0x0810, bytes([0x12, 0x34, 0x56, 0x78])),
    _hex_record(0x05, 0x0000, bytes([0x08, 0x00])),
    _hex_record(0x01, 0x0000, b""),
]) + "\n"


def build_mcu_circuit(profile):
    """U1.GPIO18 -> R1 -> GND, with a declared pin profile."""
    g = SchematicNetlistEngine()
    g.add_component(SchematicComponent("U1", "MCU", "U1", "ESP32", -100, 0))
    g.add_component(SchematicComponent("R1", "R", "R1", "1k", 60, 0))
    g.add_component(SchematicComponent("GND1", "GND", "GND", "", 60, 80))
    g.add_wire("U1:GPIO18", "R1:1", "gpio")
    g.add_wire("R1:2", "GND1:1", "gnd")
    g.add_wire("U1:GND", "GND1:1", "gnd")
    g.gpio_profiles["U1"] = {"GPIO18": profile}
    return g


class TestIntelHex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_parses_data_and_entry(self):
        data, load, entry = firmware.parse_intel_hex(HEX_SAMPLE)
        self.assertEqual(len(data), 20)          # 16 + 4 bytes
        self.assertEqual(load, 0x0800)
        self.assertEqual(entry, 0x0800)

    def test_bad_checksum_is_reported_with_line_number(self):
        first = HEX_SAMPLE.strip().splitlines()[0]
        corrupted = first[:-2] + ("00" if first[-2:] != "00" else "01")
        with self.assertRaises(firmware.FirmwareParseError) as ctx:
            firmware.parse_intel_hex(corrupted + "\n")
        self.assertIn("checksum", str(ctx.exception))

    def test_missing_eof_is_accepted_with_explicit_data(self):
        text = _hex_record(0x00, 0x0800, bytes([0x12, 0x34, 0x56, 0x78])) + "\n"
        data, load, _entry = firmware.parse_intel_hex(text)
        self.assertEqual(data, b"\x12\x34\x56\x78")
        self.assertEqual(load, 0x0800)

    def test_garbage_is_rejected(self):
        with self.assertRaises(firmware.FirmwareParseError):
            firmware.parse_intel_hex("not a hex file at all")


class TestElf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_parses_elf32_entry_and_segments(self):
        import struct
        # Build a minimal but valid ELF32 little-endian with one PT_LOAD
        ehsize, phentsize = 52, 32
        data_off = ehsize + phentsize
        payload = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        header = bytearray(ehsize)
        header[0:4] = b"\x7fELF"
        header[4] = 1        # 32-bit
        header[5] = 1        # little-endian
        header[6] = 1        # version
        struct.pack_into("<HHIIIIIHHHHHH", header, 16,
                         2,          # e_type ET_EXEC
                         0x28,       # e_machine ARM
                         1,          # e_version
                         0x08000041, # e_entry
                         ehsize,     # e_phoff
                         0,          # e_shoff
                         0,          # e_flags
                         ehsize, phentsize, 1, 40, 0, 0)
        phdr = struct.pack("<IIIIIIII", 1, data_off, 0x08000000, 0x08000000,
                           len(payload), len(payload), 5, 4)
        path = os.path.join(self.tmp, "fake.elf")
        with open(path, "wb") as f:
            f.write(bytes(header) + phdr + payload)

        image = firmware.load_firmware(path)
        self.assertEqual(image.format, "elf")
        self.assertEqual(image.size_bytes, 8)
        self.assertEqual(image.entry_point, 0x08000041)
        self.assertEqual(image.load_address, 0x08000000)
        self.assertEqual(image.data, payload)
        self.assertEqual(len(image.sha256), 64)

    def test_bad_magic_is_rejected(self):
        path = os.path.join(self.tmp, "bad.elf")
        with open(path, "wb") as f:
            f.write(b"NOPE" + b"\x00" * 60)
        with self.assertRaises(firmware.FirmwareParseError):
            firmware.load_firmware(path)

    def test_missing_file_is_reported(self):
        with self.assertRaises(firmware.FirmwareParseError):
            firmware.load_firmware(os.path.join(self.tmp, "nope.hex"))


class TestGpioProfile(unittest.TestCase):
    def test_static_pin_emits_dc_card(self):
        self.assertEqual(gpio_model.spice_card({"mode": "static", "level": 1}),
                         "DC 3.3")
        self.assertEqual(gpio_model.spice_card({"mode": "static", "level": 0}),
                         "DC 0")

    def test_square_pin_emits_pulse_with_right_period_and_duty(self):
        card = gpio_model.spice_card({"mode": "square", "freq_hz": 1000, "duty": 0.25})
        self.assertTrue(card.startswith("PULSE(0 3.3"))
        parts = card[len("PULSE("):-1].split()
        on_time, period = float(parts[5]), float(parts[6])
        self.assertAlmostEqual(period, 0.001, places=6)
        self.assertAlmostEqual(on_time / period, 0.25, places=3)

    def test_default_is_idle_low(self):
        self.assertEqual(gpio_model.spice_card(None), "DC 0")

    def test_rejects_nonsense(self):
        for bad in ({"mode": "sine"}, {"mode": "square", "freq_hz": 0},
                    {"mode": "square", "duty": 0}, {"vhigh": 99}):
            with self.assertRaises(ValueError):
                gpio_model.spice_card(bad)

    def test_pin_profile_json_parsing(self):
        profile = firmware.parse_pin_profile(
            '{"GPIO18": {"mode": "square", "freq_hz": 10, "duty": 0.5}}')
        self.assertIn("GPIO18", profile)
        with self.assertRaises(firmware.FirmwareParseError):
            firmware.parse_pin_profile("{not json")

    def test_describe_pin_is_human_readable(self):
        text = gpio_model.describe_pin("GPIO18", {"mode": "square",
                                                  "freq_hz": 1000, "duty": 0.5})
        self.assertIn("1000 Hz", text)
        self.assertIn("50%", text)


class TestLogicAnalysis(unittest.TestCase):
    def test_detects_levels_duty_and_frequency(self):
        # 5 us steps, toggling every 100 samples -> 1 kHz square wave
        times, values = [], []
        for i in range(2000):                    # 10 ms window
            times.append(i * 5e-6)
            values.append(3.3 if (i // 100) % 2 else 0.0)
        info = gpio_model.analyze_pin(times, values)
        self.assertGreater(info["transitions"], 10)
        self.assertAlmostEqual(info["duty"], 0.5, delta=0.06)
        self.assertAlmostEqual(info["v_max"], 3.3, places=3)
        freq = gpio_model.measured_frequency(times, values)
        self.assertAlmostEqual(freq, 1000.0, delta=40)

    def test_static_signal_has_no_transitions(self):
        times = [i * 1e-3 for i in range(10)]
        values = [3.3] * 10
        info = gpio_model.analyze_pin(times, values)
        self.assertEqual(info["transitions"], 0)
        self.assertIsNone(gpio_model.measured_frequency(times, values))


class TestGpioCosimEndToEnd(unittest.TestCase):
    """A modelled GPIO pin must drive real ngspice physics."""

    def test_pin_switches_the_analog_circuit(self):
        g = build_mcu_circuit({"mode": "square", "freq_hz": 1000, "duty": 0.5})
        lines, nets, warns = g.compile_netlist(tstep_us=2.0, duration_ms=5.0)

        self.assertTrue(any(l.startswith("VU1_GPIO18") and "PULSE" in l for l in lines), lines)
        self.assertEqual(warns, [], warns)
        self.assertIn("gpio", nets)

        engine = NgSpiceEngine(verbose=False)
        engine.load_circuit(lines)
        engine.cmd("run")
        times = engine.get_vector_array("time")
        values = engine.get_vector_array("gpio")

        self.assertGreater(len(times), 500)
        self.assertAlmostEqual(max(values), 3.3, delta=0.1)
        self.assertAlmostEqual(min(values), 0.0, delta=0.1)

        info = gpio_model.analyze_pin(times, values)
        self.assertAlmostEqual(info["duty"], 0.5, delta=0.05)
        freq = gpio_model.measured_frequency(times, values)
        self.assertAlmostEqual(freq, 1000.0, delta=40)

    def test_unprofiled_pin_is_reported_not_hidden(self):
        g = build_mcu_circuit({})
        lines, _nets, warns = g.compile_netlist()
        self.assertTrue(any("no GPIO profile" in w for w in warns), warns)

    def test_gnd_pin_is_not_turned_into_a_source(self):
        g = build_mcu_circuit({"mode": "square", "freq_hz": 1000, "duty": 0.5})
        lines, _nets, _warns = g.compile_netlist()
        gnd_sources = [l for l in lines if "GND" in l and l.startswith("V")]
        self.assertEqual(gnd_sources, [])

    def test_profiles_survive_save_and_reload(self):
        g = build_mcu_circuit({"mode": "square", "freq_hz": 250, "duty": 0.1})
        restored = SchematicNetlistEngine()
        restored.load_dict(g.to_dict())
        self.assertEqual(restored.gpio_profiles["U1"]["GPIO18"]["freq_hz"], 250)


if __name__ == "__main__":
    unittest.main(verbosity=2)