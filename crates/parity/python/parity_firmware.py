#!/usr/bin/env python3
"""
parity_firmware.py - cross-implementation diff of bridge/firmware.py against
the Rust port in crates/wowkispice-core/src/firmware.rs.

One fixed battery, computed twice (Python vs Rust), over one identical key
space.  Keys are index-based (sha[i], ihex[i], elf[i]) plus named keys (pin.*,
fw.*).  Error strings are compared as text (verbatim parity contract);
SHA-256 hex digests and machine names too; floats only where noted.

Run:  .venv/Scripts/python.exe crates/parity/python/parity_firmware.py <path-to-parity_firmware>
(the Rust binary is built from crates/parity/src/bin/parity_firmware.rs and
this driver invokes it with cwd=REPO so file paths agree).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Tuple

REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, REPO)

from bridge import firmware as fw  # noqa: E402

BINARY_NAME = "parity_firmware"

# ---------------------------------------------------------------- battery inputs

SHA_CASES: List[bytes] = [
    b"",                          # the empty payload -> Python reports ""
    b"hello world",
    bytes([1, 2, 3, 4, 5, 6, 7, 8]),
]

PIN_OK_JSON = '{"GPIO18": {"mode": "square", "freq_hz": 1000.0, "duty": 0.5, "vhigh": 3.3}}'


def _hex_record(rectype: int, address: int, data: bytes) -> str:
    payload = bytearray([len(data), (address >> 8) & 0xFF, address & 0xFF, rectype])
    payload.extend(data)
    checksum = (-sum(payload)) & 0xFF
    return ":" + "".join(f"{b:02X}" for b in payload) + f"{checksum:02X}"


def ihex_sample() -> str:
    return "\n".join([
        _hex_record(0x00, 0x0800, bytes(range(16))),
        _hex_record(0x00, 0x0810, bytes([0x12, 0x34, 0x56, 0x78])),
        _hex_record(0x05, 0x0000, bytes([0x08, 0x00])),
        _hex_record(0x01, 0x0000, b""),
    ]) + "\n"


def ihex_no_eof() -> str:
    return _hex_record(0x00, 0x0800, bytes([0x12, 0x34, 0x56, 0x78])) + "\n"


def ihex_data_after_eof() -> str:
    return (
        _hex_record(0x00, 0x0800, bytes([0x11, 0x22])) + "\n"
        + _hex_record(0x01, 0x0000, b"") + "\n"
        + _hex_record(0x00, 0x0810, bytes([0x33])) + "\n"
    )


def ihex_bad_checksum() -> str:
    good = _hex_record(0x00, 0x0800, bytes([0x11, 0x22]))
    return good[:-2] + ("0" if good[-2:] != "0" else "1") + good[-1:]


def ihex_ext_linear() -> str:
    return "\n".join([
        _hex_record(0x04, 0x0000, bytes([0x00, 0x20])),
        _hex_record(0x00, 0x0000, bytes([0xAA, 0xBB])),
        _hex_record(0x05, 0x0000, bytes([0x00, 0x20])),
    ]) + "\n"


def ihex_battery() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for i, text in enumerate([
        ihex_sample(),
        ihex_bad_checksum(),
        "garbage\n",
        ihex_no_eof(),
        ihex_data_after_eof(),
        ":ZZ00008000\n",
        ":02000008\n",
        ":0500000800AABB\n",
        ":00000001FF\n",
        ihex_ext_linear(),
    ]):
        out.append((f"ihex[{i}]", ihex_value(text)))
    return out


def ihex_value(text: str) -> str:
    try:
        data, load, entry = fw.parse_intel_hex(text)
    except fw.FirmwareParseError as exc:
        return "ERR:" + str(exc)
    sha = hashlib.sha256(data).hexdigest() if data else ""
    return f"OK:{sha}:{load}:{entry}"


def elf32(entry: int, machine: int, load: int, payload: bytes) -> bytes:
    import struct

    blob = bytearray(84 + len(payload))
    blob[0:4] = b"\x7fELF"
    blob[4] = 1   # EI_CLASS 32-bit
    blob[5] = 1   # EI_DATA  little-endian
    blob[6] = 1   # EI_VERSION
    struct.pack_into("<HHIIIIIHHHHHH", blob, 16, 2, machine, 1, entry, 52, 0, 0, 52, 32, 1, 40, 0, 0)
    struct.pack_into("<IIIIIIII", blob, 52, 1, 84, load, load, len(payload), len(payload), 5, 4)
    blob[84:84 + len(payload)] = payload
    return bytes(blob)


def elf_battery() -> List[Tuple[str, str]]:
    payload = bytes([1, 2, 3, 4, 5, 6, 7, 8])
    out: List[Tuple[str, str]] = []
    out.append(("elf[0]", elf_value(elf32(0x08000041, 0x28, 0x08000000, payload))))
    bad = bytearray(elf32(0x08000041, 0x28, 0x08000000, payload))
    bad[1] = ord("X")
    out.append(("elf[1]", elf_value(bytes(bad))))
    badclass = bytearray(elf32(0x08000041, 0x28, 0x08000000, payload))
    badclass[4] = 3
    out.append(("elf[2]", elf_value(bytes(badclass))))
    noload = bytearray(elf32(0x08000041, 0x28, 0x08000000, payload))
    noload[44:46] = (0).to_bytes(2, "little")
    out.append(("elf[3]", elf_value(bytes(noload))))
    return out


def elf_value(blob: bytes) -> str:
    try:
        payload, entry, load, sections, machine = fw.parse_elf(blob)
    except fw.FirmwareParseError as exc:
        return "ERR:" + str(exc)
    sha = hashlib.sha256(payload).hexdigest() if payload else ""
    return f"OK:{sha}:{entry}:{load}:{machine}"


def sha_value(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest() if data else ""


def pin_value(text: str) -> str:
    raw = json.loads(text)
    if not isinstance(raw, dict):
        return "ERR:pin profile must be a JSON object of pin -> spec"
    spec = raw["GPIO18"]
    mode = str(spec.get("mode"))
    freq = float(spec.get("freq_hz"))
    duty = float(spec.get("duty"))
    return f"OK:GPIO18:{mode}:{float(freq)}:{float(duty)}"


PIN_NOT_OBJECT = "[1,2,3]"


def pin_battery() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    out.append(("pin.ok", pin_value(PIN_OK_JSON)))
    out.append(("pin.err.not_object", pin_value(PIN_NOT_OBJECT)))
    return out


# ---------------------------------------------------------------- fixtures

class Fixtures:
    """Deterministic temp image files for the load_firmware battery."""

    def __init__(self, tmpdir: str) -> None:
        self.hex_ok = os.path.join(tmpdir, "fw_ok.hex")
        self.hex_noend = os.path.join(tmpdir, "fw_noend.hex")
        self.elf_ok = os.path.join(tmpdir, "fw_ok.elf")
        self.bad_hex = os.path.join(tmpdir, "fw_bad.hex")
        self.bad_elf = os.path.join(tmpdir, "fw_bad.elf")
        self.empty = os.path.join(tmpdir, "fw_empty.bin")
        self.notimg = os.path.join(tmpdir, "fw_notimg.bin")
        self.missing = os.path.join(tmpdir, "fw_missing.hex")

        with open(self.hex_ok, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(ihex_sample())
        with open(self.hex_noend, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(ihex_no_eof())
        with open(self.elf_ok, "wb") as fh:
            fh.write(elf32(0x08000041, 0x28, 0x08000000, bytes([1, 2, 3, 4, 5, 6, 7, 8])))
        with open(self.bad_hex, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("garbage\n")
        with open(self.bad_elf, "wb") as fh:
            fh.write(b"NOPE" + b"\x00" * 40)
        with open(self.empty, "wb") as fh:
            fh.write(b"")
        with open(self.notimg, "wb") as fh:
            fh.write(b"plain text, not a hex or elf image at all")

    def cleanup(self) -> None:
        for path in [self.hex_ok, self.hex_noend, self.elf_ok, self.bad_hex, self.bad_elf, self.empty, self.notimg]:
            if os.path.exists(path):
                os.remove(path)


def fw_battery(fix: Fixtures) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    out.append(("fw.hex_ok", fw_value(fix.hex_ok)))
    out.append(("fw.hex_noend", fw_value(fix.hex_noend)))
    out.append(("fw.elf_ok", fw_value(fix.elf_ok)))
    out.append(("fw.bad_hex", fw_value(fix.bad_hex)))
    out.append(("fw.bad_elf", fw_value(fix.bad_elf)))
    out.append(("fw.empty", fw_value(fix.empty)))
    out.append(("fw.notimg", fw_value(fix.notimg)))
    out.append(("fw.missing", fw_value(fix.missing)))
    return out


def fw_value(path: str) -> str:
    try:
        image = fw.load_firmware(path)
    except fw.FirmwareParseError as exc:
        return "ERR:" + str(exc)
    sha = image.sha256
    if image.format == "elf":
        return f"OK:{sha}:{image.entry_point}:{image.load_address}:{image.machine}"
    return f"OK:{sha}:{image.load_address}:{image.entry_point}"


# ---------------------------------------------------------------- rust side


def run_rust_battery(binary: str, manifest: str) -> Dict[str, str]:
    proc = subprocess.run(
        [binary, manifest],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"parity_firmware (rust) exited {proc.returncode}\n{proc.stderr}"
        )
    result: Dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        if "\t" not in line:
            raise SystemExit(f"malformed rust output line (no tab): {line!r}")
        key, value = line.split("\t", 1)
        if key in result:
            raise SystemExit(f"duplicate key from rust: {key}")
        result[key] = value
    return result


def values_agree(a: str, b: str) -> bool:
    """Numerically where both sides parse as floats, otherwise as text."""
    try:
        return float(a) == float(b)
    except ValueError:
        return a == b


def describe_value(v: str) -> str:
    try:
        f = float(v)
    except ValueError:
        return repr(v)
    return f"{v!r} ({f!r})"


def main(argv: List[str]) -> int:
    if len(argv) > 1:
        binary = argv[1]
    else:
        binary = shutil.which(BINARY_NAME) or ""
    if not binary or not os.path.exists(binary):
        raise SystemExit(
            f"usage: parity_firmware.py <path-to-parity_firmware>\n"
            f"(the Rust executable built from "
            f"crates/parity/src/bin/parity_firmware.rs)"
        )

    tmpdir = tempfile.mkdtemp(prefix="wosp_fw_parity_")
    fix = Fixtures(tmpdir)
    fd, manifest = tempfile.mkstemp(prefix="wosp_parity_manifest_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            for name, path in sorted({
                "hex_ok": fix.hex_ok,
                "hex_noend": fix.hex_noend,
                "elf_ok": fix.elf_ok,
                "bad_hex": fix.bad_hex,
                "bad_elf": fix.bad_elf,
                "empty": fix.empty,
                "notimg": fix.notimg,
                "missing": fix.missing,
            }.items()):
                fh.write(f"{name}\t{path}\n")

        py: Dict[str, str] = {}
        py["sha[0]"] = sha_value(b"")
        py["sha[1]"] = sha_value(b"hello world")
        py["sha[2]"] = sha_value(bytes([1, 2, 3, 4, 5, 6, 7, 8]))
        py.update(dict(ihex_battery()))
        py.update(dict(elf_battery()))
        py.update(dict(pin_battery()))
        py.update(dict(fw_battery(fix)))

        rs = run_rust_battery(binary, manifest)
    finally:
        if os.path.exists(manifest):
            os.remove(manifest)
        fix.cleanup()
        shutil.rmtree(tmpdir, ignore_errors=True)

    only_py = sorted(set(py) - set(rs))
    only_rs = sorted(set(rs) - set(py))
    mismatch = sorted(k for k in set(py) & set(rs) if not values_agree(py[k], rs[k]))

    if not (only_py or only_rs or mismatch):
        print(f"PARITY OK — {len(py)} values identical between "
              f"bridge/firmware.py and crates/wowkispice-core/src/firmware.rs")
        return 0

    print("PARITY FAILED: bridge/firmware.py and "
          "crates/wowkispice-core/src/firmware.rs disagree\n")
    if only_py:
        print(f"keys only in Python ({len(only_py)}):")
        for k in only_py[:40]:
            print(f"  {k} = {describe_value(py[k])}")
        print()
    if only_rs:
        print(f"keys only in Rust ({len(only_rs)}):")
        for k in only_rs[:40]:
            print(f"  {k} = {describe_value(rs[k])}")
        print()
    if mismatch:
        print(f"values that differ ({len(mismatch)}):")
        for k in mismatch[:60]:
            print(f"  {k}\n      python {describe_value(py[k])}\n      rust   {describe_value(rs[k])}")
        print()
    print(f"{len(mismatch)} differing, {len(only_py)} python-only, "
          f"{len(only_rs)} rust-only out of {len(set(py) | set(rs))} keys")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
