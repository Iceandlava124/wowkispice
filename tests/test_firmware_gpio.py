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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The real ESP32 image produced by the firmware build. Not committed (it is a
# 3 MB build artifact); these tests skip when it has not been built.
REAL_ELF = os.path.join(REPO, "firmware", "esp32_buck_controller", ".pio",
                        "build", "esp32dev", "firmware.elf")

from bridge import firmware, gpio_model
from bridge.cad_engine import SchematicComponent, SchematicNetlistEngine
from bridge.ngspice_wrapper import NgSpiceEngine
import types
from bridge.qemu_monitor import QemuMonitor, QemuMonitorError, cycle_adc_and_gate, sweep_report

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


def _elf32_with_sections(machine=0x28, entry=0x08000041, load_vaddr=0x10000000):
    """Build a valid ELF32 carrying a real section table and shstrtab.

    Every section's virtual address is deliberately far from its file offset
    (0x40080000 vs 84), so a parser that confuses the two cannot pass.
    Returns (blob, text_vaddr, text_file_offset, text_size).
    """
    import struct
    ehsize, phentsize, shentsize = 52, 32, 40
    payload = bytes(range(8))
    phoff = ehsize
    data_off = phoff + phentsize                 # 84
    shstrtab = b"\x00.text\0.shstrtab\0"
    name_text, name_shstrtab = 1, 7
    shoff = 0x100
    shstr_off = shoff + 3 * shentsize
    text_vaddr = 0x40080000                      # != data_off on purpose

    blob = bytearray(shstr_off + len(shstrtab))
    blob[0:4] = b"\x7fELF"
    blob[4], blob[5], blob[6] = 1, 1, 1         # 32-bit, little-endian, v1
    struct.pack_into("<HHIIIIIHHHHHH", blob, 16,
                     2, machine, 1, entry,
                     phoff, shoff, 0,
                     ehsize, phentsize, 1,
                     shentsize, 3, 2)           # shnum=3, e_shstrndx=2
    struct.pack_into("<IIIIIIII", blob, phoff,
                     1, data_off, load_vaddr, load_vaddr,
                     len(payload), len(payload), 5, 4)
    blob[data_off:data_off + len(payload)] = payload

    struct.pack_into("<IIIIIIIIII", blob, shoff,
                     0, 0, 0, 0, 0, 0, 0, 0, 0, 0)                       # NULL
    struct.pack_into("<IIIIIIIIII", blob, shoff + shentsize,
                     name_text, 1, 6, text_vaddr, data_off, len(payload),
                     0, 0, 4, 0)                                          # .text
    struct.pack_into("<IIIIIIIIII", blob, shoff + 2 * shentsize,
                     name_shstrtab, 3, 0, 0, shstr_off, len(shstrtab),
                     0, 0, 1, 0)                                          # .shstrtab
    blob[shstr_off:shstr_off + len(shstrtab)] = shstrtab
    return bytes(blob), text_vaddr, data_off, len(payload)


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

    def test_section_names_addresses_and_offsets(self):
        blob, text_vaddr, text_off, text_size = _elf32_with_sections()
        _payload, _entry, _load, sections, machine = firmware.parse_elf(blob)
        self.assertEqual(machine, "ARM")
        self.assertEqual(len(sections), 3)
        self.assertEqual(sections[0]["name"], "")            # NULL section
        self.assertEqual(sections[1]["name"], ".text")
        self.assertEqual(sections[1]["address"], text_vaddr)  # 0x40080000
        self.assertEqual(sections[1]["offset"], text_off)     # 84
        self.assertEqual(sections[1]["size"], text_size)
        self.assertEqual(sections[2]["name"], ".shstrtab")
        self.assertEqual(sections[2]["offset"], 0x178)

    def test_section_address_is_not_confused_with_file_offset(self):
        blob, _v, _o, _s = _elf32_with_sections()
        _p, _e, _l, sections, _m = firmware.parse_elf(blob)
        self.assertNotEqual(sections[1]["address"], sections[1]["offset"])
        self.assertEqual(sections[1]["address"], 0x40080000)
        self.assertEqual(sections[1]["offset"], 84)

    def test_xtensa_machine_is_recognised(self):
        blob, _v, _o, _s = _elf32_with_sections(machine=0x5E)
        _p, _e, _l, _sections, machine = firmware.parse_elf(blob)
        self.assertEqual(machine, "Xtensa")

    def test_unknown_machine_falls_back_to_hex(self):
        blob, _v, _o, _s = _elf32_with_sections(machine=0x7777)
        _p, _e, _l, _sections, machine = firmware.parse_elf(blob)
        self.assertEqual(machine, "machine 0x7777")

    def test_truncated_section_table_does_not_crash(self):
        blob, _v, _o, _s = _elf32_with_sections()
        # Chop 20 bytes off the end: the tail of the third section header and
        # part of the shstrtab itself are gone. Parsing must degrade, not raise.
        _p, _e, _l, sections, _m = firmware.parse_elf(blob[:len(blob) - 20])
        self.assertEqual(len(sections), 2)     # stops before the incomplete entry
        # The name table is truncated too, so names degrade to empty rather
        # than raising or emitting "#N" placeholders.
        self.assertEqual(sections[1]["name"], "")
        self.assertEqual(sections[1]["address"], 0x40080000)

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


@unittest.skipUnless(os.path.exists(REAL_ELF),
                     "real firmware.elf not built - run: pio run "
                     "-d firmware/esp32_buck_controller")
class TestRealEsp32Firmware(unittest.TestCase):
    """The first real ELF this project has ever parsed.

    Build the image with:
        pio run -d firmware/esp32_buck_controller
    """

    def test_real_image_reports_xtensa_and_a_plausible_entry(self):
        image = firmware.load_firmware(REAL_ELF)
        self.assertEqual(image.format, "elf")
        self.assertEqual(image.machine, "Xtensa")
        self.assertNotEqual(image.entry_point, 0)
        self.assertEqual(image.entry_point & 0xFFF00000, 0x40000000)
        self.assertEqual(len(image.sha256), 64)
        self.assertGreater(image.size_bytes, 0)

    def test_real_image_section_names_all_resolve(self):
        image = firmware.load_firmware(REAL_ELF)
        self.assertGreater(len(image.sections), 10)
        for s in image.sections:
            # The old parser emitted "#3" style placeholders for every section.
            self.assertFalse(s["name"].startswith("#"), s)
        names = {s["name"] for s in image.sections}
        for expected in (".iram0.text", ".dram0.data", ".flash.text",
                         ".flash.rodata", ".shstrtab"):
            self.assertIn(expected, names)

    def test_real_image_addresses_are_memory_not_file_offsets(self):
        image = firmware.load_firmware(REAL_ELF)
        by_name = {s["name"]: s for s in image.sections}
        text = by_name[".iram0.text"]
        # Address lives in IRAM; offset lives near the start of a 3 MB file.
        self.assertGreater(text["address"], 0x40000000)
        self.assertLess(text["offset"], 0x100000)
        self.assertNotEqual(text["address"], text["offset"])
        # Code must really be mapped where the ELF says it is.
        rodata = by_name[".flash.rodata"]
        self.assertGreater(rodata["address"], 0x3F000000)
        self.assertGreater(rodata["size"], 0)

    def test_entry_point_lies_inside_a_known_code_section(self):
        image = firmware.load_firmware(REAL_ELF)
        by_name = {s["name"]: s for s in image.sections}
        code = by_name[".iram0.text"]
        self.assertGreaterEqual(image.entry_point, code["address"])
        self.assertLess(image.entry_point, code["address"] + code["size"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class QemuMonitorDouble:
    """Test double for QemuMonitor (tests/doubles-style).

cycle_adc_and_gate() drives the monitor through a three-method interface:
set_adc1_value(value), read_gate() -> bool, and stop(). This double
implements exactly that surface -- no process, no socket, no real QEMU --
so the coupling logic can be exercised without the binary. It is a DOUBLE,
not the real monitor; the real-QEMU path lives in
tests/test_qemu_monitor_qemu.py under the @qemu marker.

SCOPE: this double exists ONLY to check the wiring of cycle_adc_and_gate()
and sweep_report() -- that they call set_adc1_value() then read_gate() then
stop(), in that order, with the requested value. It deliberately verifies
no protocol, no QOM path, no xp parsing and no timing, so a green run here
is NOT emulator coverage and must not be counted as such. Protocol coverage
lives in tests/test_qemu_monitor_unit.py (fake HMP emulator) and in
tests/test_qemu_monitor_qemu.py (real QEMU, @qemu marker).
    """

    def __init__(self, gate_high=True, fail_on=None):
        self.gate_high = gate_high
        self.fail_on = fail_on          # method name that should raise
        self.injected = []              # every adc1-value written
        self.stopped = False            # stop() must be called exactly once
        self.calls = []                 # call ORDER: the wiring under test

    def set_adc1_value(self, value):
        self.calls.append("set_adc1_value")
        if self.fail_on == "set_adc1_value":
            raise QemuMonitorError("injected failure on set_adc1_value")
        self.injected.append(int(value))

    def read_gate(self):
        self.calls.append("read_gate")
        if self.fail_on == "read_gate":
            raise QemuMonitorError("injected failure on read_gate")
        return self.gate_high

    def stop(self):
        self.calls.append("stop")
        self.stopped = True



class TestQemuGateBridge(unittest.TestCase):
    """The automatic ngspice <-> QEMU bridge: adc1-value injection and gate
    readback through cycle_adc_and_gate() and sweep_report().

    ALL FOUR TESTS HERE USE QemuMonitorDouble AND ARE WIRING TESTS ONLY:
    they prove the coupling functions call set_adc1_value -> read_gate ->
    stop, in order, and never raise. They exercise no emulator, no HMP
    protocol and no firmware, and must not be counted as emulator coverage.
    Protocol behaviour is tested against the fake HMP emulator in
tests/test_qemu_monitor_unit.py; the real-emulator contract is in
tests/test_qemu_monitor_qemu.py under the @qemu marker.
    """

    def test_cycle_adc_and_gate_returns_a_clean_cycle(self):
        # A monitor that fails mid-cycle must still yield a clean, non-raising
        # cycle: ok=False, gate_high=None, and a readable message. The docstring
        # on cycle_adc_and_gate() promises "every failure shape is returned as a
        # clean, non-raising FirmwareCouplingCycle", so this asserts that.
        mon = QemuMonitorDouble(fail_on="set_adc1_value")
        cycle = cycle_adc_and_gate(mon, stop=True)
        self.assertFalse(cycle.ok)
        self.assertIsNone(cycle.gate_high)
        self.assertTrue(cycle.message)
        # A failed injection must not read the gate, but must still stop.
        self.assertEqual(mon.calls, ["set_adc1_value", "stop"])

    def test_cycle_adc_and_gate_flow(self):
        # A healthy double: one cycle injects the ADC value, reads the gate back,
        # and returns ok=True with the gate decision and the value in the message.
        mon = QemuMonitorDouble(gate_high=True)
        cycle = cycle_adc_and_gate(mon, adc_value=2012, stop=True)
        self.assertTrue(cycle.ok)
        self.assertTrue(cycle.gate_high)
        self.assertIn("2012", cycle.message)
        # The value really reached the monitor, and this cycle stopped it.
        self.assertEqual(mon.injected, [2012])
        self.assertTrue(mon.stopped)
        # WIRING, in order: inject first, read the gate back second, stop last.
        self.assertEqual(mon.calls,
                         ["set_adc1_value", "read_gate", "stop"])

    def test_sweep_report_returns_a_row_per_value(self):
        # sweep_report() must produce one row per requested ADC value, never
        # raising even when the monitor misbehaves on one of them.
        # The caller owns the monitor lifecycle (stop=False default); cycle
        # AdcAndGate does not stop the monitor.
        mon = QemuMonitorDouble(gate_high=True)
        rows = sweep_report(mon, [1900, 2012, 3456])
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertTrue(row.ok)
        # Each value goes through set -> read only (no stop called by cycle)
        self.assertEqual(mon.calls,
                         ["set_adc1_value", "read_gate"] * 3)
        self.assertEqual(mon.injected, [1900, 2012, 3456])

    def test_sweep_report_never_raises_even_when_monitor_fails(self):
        # A monitor that throws on every cycle still yields three clean failure
        # rows rather than an exception escaping sweep_report().
        # With the new contract, cycle_adc_and_gate does not stop the monitor
        # (stop=False is default); the monitor lifecycle is the caller's responsibility.
        rows = sweep_report(QemuMonitorDouble(fail_on="set_adc1_value"),
                            [1900, 2012, 3456])
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertFalse(row.ok)
            self.assertTrue(row.message)
