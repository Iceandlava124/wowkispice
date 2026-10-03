"""
firmware.py - Load and inspect MCU firmware images (.hex / .elf).

What this DOES: parse the image and report what is really in it - format,
byte size, load address, entry point, section names, SHA-256. Those are facts
read out of the file, not guesses.

What this does NOT do (yet): execute the firmware. Running a real ESP32/AVR
binary needs an instruction-set emulator (Renode, QEMU) or a compiled-to-Python
transpiler; neither exists in this repo. GPIO behaviour during co-simulation
comes from a declared pin profile (see bridge/gpio_model.py) which is honest
about being a model rather than pretending to be the binary.

Parsers are deliberately dependency-free and defensive: a malformed file raises
FirmwareParseError with a human-readable reason rather than producing junk.
"""

import hashlib
import os
import struct
from typing import Dict, List, Optional, Tuple


class FirmwareParseError(ValueError):
    """Raised when an image cannot be parsed, with a readable reason."""


class FirmwareImage:
    """A parsed firmware image plus the metadata we can state as fact."""

    def __init__(self, path: str, fmt: str, data: bytes = b"",
                 entry_point: int = 0, load_address: int = 0,
                 sections: Optional[List[Dict[str, object]]] = None):
        self.path = path
        self.format = fmt                    # "ihex" | "elf"
        self.data = data
        self.entry_point = entry_point
        self.load_address = load_address
        self.sections = sections or []
        self.sha256 = hashlib.sha256(data).hexdigest() if data else ""

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def summary(self) -> str:
        parts = [f"{self.name}", f"{self.size_bytes} bytes", f"sha256:{self.sha256[:12]}"]
        if self.load_address:
            parts.append(f"load 0x{self.load_address:08X}")
        if self.entry_point:
            parts.append(f"entry 0x{self.entry_point:08X}")
        return ", ".join(parts)

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "entry_point": self.entry_point,
            "load_address": self.load_address,
            "sha256": self.sha256,
            "sections": self.sections,
        }


# --------------------------------------------------------------------------
# Intel HEX
# --------------------------------------------------------------------------
def parse_intel_hex(text: str) -> Tuple[bytes, int, int]:
    """
    Parse Intel HEX. Returns (data, load_address, entry_point).

    Supports record types 00 (data), 01 (EOF), 02 (extended segment address),
    04 (extended linear address) and 03/05 (start address).
    """
    memory: Dict[int, int] = {}
    base = 0
    entry = 0
    saw_eof = False

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if saw_eof:
            raise FirmwareParseError(f"line {lineno}: data after EOF record")
        if not line.startswith(":"):
            raise FirmwareParseError(f"line {lineno}: record does not start with ':'")
        try:
            payload = bytes.fromhex(line[1:])
        except ValueError:
            raise FirmwareParseError(f"line {lineno}: invalid hex digits")
        if len(payload) < 5:
            raise FirmwareParseError(f"line {lineno}: record too short ({len(payload)} bytes)")

        count = payload[0]
        if len(payload) != count + 5:
            raise FirmwareParseError(
                f"line {lineno}: length byte {count} does not match record size")
        address = (payload[1] << 8) | payload[2]
        rectype = payload[3]
        data = payload[4:4 + count]
        checksum = sum(payload) & 0xFF
        if checksum != 0:
            raise FirmwareParseError(f"line {lineno}: bad checksum")

        if rectype == 0x00:
            for i, byte in enumerate(data):
                memory[base + address + i] = byte
        elif rectype == 0x01:
            saw_eof = True
        elif rectype == 0x02:
            base = int.from_bytes(data, "big") << 4
        elif rectype == 0x04:
            base = int.from_bytes(data, "big") << 16
        elif rectype in (0x03, 0x05):
            entry = int.from_bytes(data, "big")
        # 0x06 not supported by most toolchains; ignore silently

    if not memory:
        raise FirmwareParseError("no data records found (is this a code-only HEX?)")

    load_address = min(memory)
    blob = bytes(memory[addr] for addr in range(min(memory), max(memory) + 1))
    return blob, load_address, entry


# --------------------------------------------------------------------------
# ELF
# --------------------------------------------------------------------------
_ELF_MACHINES = {0x03: "x86", 0x08: "MIPS", 0x14: "PowerPC", 0x15: "PowerPC64",
                 0x28: "ARM", 0x3E: "x86-64", 0xB7: "AArch64", 0xF3: "RISC-V",
                 0x5E: "Xtensa"}


def parse_elf(blob: bytes) -> Tuple[bytes, int, int, List[Dict[str, object]], str]:
    """
    Parse a 32- or 64-bit little/big-endian ELF header.

    Returns (loadable_bytes, entry_point, load_address, sections, machine).
    Only loadable segments are read - .text/.rodata/.data in practice.
    """
    if len(blob) < 52 or blob[:4] != b"\x7fELF":
        raise FirmwareParseError("not an ELF file (bad magic)")

    ei_class = blob[4]                       # 1 = 32-bit, 2 = 64-bit
    ei_data = blob[5]                        # 1 = little, 2 = big
    if ei_class not in (1, 2):
        raise FirmwareParseError(f"unknown ELF class {ei_class}")
    endian = "<" if ei_data == 1 else ">"

    if ei_class == 1:
        # Elf32_Ehdr after e_ident: type, machine, version, entry, phoff, shoff,
        # flags, ehsize, phentsize, phnum, shentsize, shnum, shstrndx
        fmt = endian + "HHIIIIIHHHHHH"
        (e_type, e_machine, _version, e_entry, e_phoff, e_shoff, _flags,
         _ehsize, _phentsize, e_phnum, _shentsize, e_shnum, e_shstrndx) = struct.unpack_from(fmt, blob, 16)
    else:
        fmt = endian + "HHIQQQIHHHHH"
        (e_type, e_machine, _version, e_entry, e_phoff, e_shoff, _flags,
         _ehsize, _phentsize, e_phnum, _shentsize, e_shnum, e_shstrndx) = struct.unpack_from(fmt, blob, 16)

    machine = _ELF_MACHINES.get(e_machine, f"machine 0x{e_machine:X}")

    # Section names (best effort; stripped images have none)
    #
    # Elf32_Shdr / Elf64_Shdr field order is:
    #   name(0) type(1) flags(2) addr(3) offset(4) size(5) link(6) info(7)
    #   addralign(8) entsize(9)
    # so `addr` is index 3 and `offset` is index 4. Getting these two the wrong
    # way round silently reports file offsets as load addresses.
    sections: List[Dict[str, object]] = []
    if e_shoff and e_shnum and _shentsize and e_shstrndx < e_shnum:
        shstr_hdr_off = e_shoff + e_shstrndx * _shentsize
        if shstr_hdr_off + _shentsize > len(blob):
            shstr_hdr_off = 0
        if ei_class == 1:
            (_n, _t, _f, _ad, shstr_off, shstr_size, *_r) = struct.unpack_from(
                endian + "IIIIIIIIII", blob, shstr_hdr_off)
        else:
            (_n, _t, _f, _ad, shstr_off, shstr_size, *_r) = struct.unpack_from(
                endian + "IIQQQQIIQQ", blob, shstr_hdr_off)

        names = b""
        if shstr_hdr_off and shstr_size and shstr_off + shstr_size <= len(blob):
            names = blob[shstr_off:shstr_off + shstr_size]

        for i in range(e_shnum):
            off = e_shoff + i * _shentsize
            if off + _shentsize > len(blob):
                break
            if ei_class == 1:
                (_nm, _ty, _fl, _addr, _offset, size, *_r) = struct.unpack_from(
                    endian + "IIIIIIIIII", blob, off)
            else:
                (_nm, _ty, _fl, _addr, _offset, size, *_r) = struct.unpack_from(
                    endian + "IIQQQQIIQQ", blob, off)

            name = ""
            if names and 0 <= _nm < len(names):
                end = names.find(b"\x00", _nm)
                if end == -1:
                    end = len(names)
                name = names[_nm:end].decode("ascii", "replace")

            sections.append({"name": name, "size": size,
                             "address": _addr, "offset": _offset})

    # Loadable program segments
    chunks: List[Tuple[int, bytes]] = []
    for i in range(e_phnum):
        off = e_phoff + i * _phentsize
        if ei_class == 1:
            (p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align) = struct.unpack_from(
                endian + "IIIIIIII", blob, off)
        else:
            (p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align) = struct.unpack_from(
                endian + "IIQQQQQQ", blob, off)
        if p_type == 1 and p_filesz:          # PT_LOAD
            chunks.append((p_vaddr, blob[p_offset:p_offset + p_filesz]))

    if not chunks:
        raise FirmwareParseError("ELF contains no loadable segments")
    chunks.sort(key=lambda c: c[0])
    payload = b"".join(data for _addr, data in chunks)
    return payload, e_entry, chunks[0][0], sections, machine


# --------------------------------------------------------------------------
def load_firmware(path: str) -> FirmwareImage:
    """Load a .hex / .elf image and return a FirmwareImage of verified metadata."""
    if not os.path.exists(path):
        raise FirmwareParseError(f"file not found: {path}")
    with open(path, "rb") as f:
        blob = f.read()
    if not blob:
        raise FirmwareParseError("file is empty")

    if blob[:2] == b"\x7fE" or path.lower().endswith(".elf"):
        data, entry, load, sections, machine = parse_elf(blob)
        image = FirmwareImage(path, "elf", data, entry, load, sections)
        image.machine = machine
        return image

    if path.lower().endswith((".hex", ".ihex")) or blob[:1] == b":":
        text = blob.decode("ascii", errors="replace")
        data, load, entry = parse_intel_hex(text)
        return FirmwareImage(path, "ihex", data, entry, load)

    raise FirmwareParseError(
        "unsupported image: expected Intel HEX (.hex) or ELF (.elf)")


def parse_pin_profile(text: str) -> Dict[str, Dict[str, object]]:
    """
    Parse a GPIO pin profile from JSON.

    Example:
        {
          "GPIO18": {"mode": "square", "freq_hz": 1000, "duty": 0.5, "vhigh": 3.3},
          "GPIO5":  {"mode": "static", "level": 1, "vhigh": 3.3}
        }
    """
    import json
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise FirmwareParseError(f"pin profile is not valid JSON: {exc}")
    if not isinstance(raw, dict):
        raise FirmwareParseError("pin profile must be a JSON object of pin -> spec")
    return raw