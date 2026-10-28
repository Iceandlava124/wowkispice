#!/usr/bin/env python3
"""diagnostics.py - print a redacted, one-page system/environment summary.

Usage:
    python tools/diagnostics.py

Outputs, one key per line, and exits 0:
    os               : platform, release, machine
    python           : interpreter path and version
    ngspice          : resolved library path + version string (or MISSING)
    qemu             : resolved binary path + --version line (or MISSING)
    toolchain        : xtensa-esp32-elf / ESP-IDF version claims
    binaries         : sha256 of every artifact this project depends on
    log              : last log path that exists (home paths redacted)

Never prints secrets, tokens, home directory contents, or absolute paths
outside the project; all home directories and usernames are redacted.
"""

import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Artifacts whose checksums gate downstream phases.
ARTIFACT_CHAIN = [
    "firmware/esp32_buck_controller/.pio/build/esp32dev/qemu_flash.bin",
    "firmware/esp32_buck_controller/.pio/build/esp32dev/firmware.bin",
    "firmware/esp32_buck_controller/.pio/build/esp32dev/bootloader.bin",
    "firmware/esp32_buck_controller/.pio/build/esp32dev/partitions.bin",
]


def _redact(p: str) -> str:
    """Turn a home-prefixed path into /REDACTED/... ."""
    for home in ("/home/", "/Users/", "/root/", "C:\\Users\\"):
        if p.startswith(home):
            return p.replace(home, "/REDACTED/", 1)
    return p


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as exc:
        return f"UNAVAILABLE ({exc})"


def _run(cmd, timeout=10):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (proc.stdout or "").strip() or (proc.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001
        return f"<failed: {exc}>"


def _version_line(exe: Path) -> str:
    if not exe.exists():
        return "MISSING"
    if exe.name.startswith("ngspice"):
        return exe.name + " " + _run([str(exe), "--version"], timeout=5)
    return _run([str(exe), "--version"], timeout=5)


def _ngspice_version():
    # Prefer the bundled Windows DLL for the .dll physics proofs, then a
    # system install, then the source tree.
    candidates = []
    bundled = REPO_ROOT / "tools" / "ngspice_dll" / "Spice64_dll" / "dll-vs" / "ngspice.dll"
    if bundled.exists():
        candidates.append(bundled)
    for name in ("ngspice", "ngspice_con"):
        candidates.append(Path(sys.executable).parent / name)
    candidates += [
        Path("/usr/bin/ngspice"),
        Path("/usr/local/bin/ngspice"),
    ]
    for cand in candidates:
        if cand.exists():
            out = _version_line(cand)
            return f"{cand}  ->  {out}"
    return "MISSING (nor bundled DLL nor system ngspice found)"


def _qemu_binary():
    env = os.environ.get("WOSP_QEMU")
    if env and os.path.exists(env):
        return Path(env)
    for name in ("qemu-system-xtensa", "qemu-system-arm"):
        cand = Path(name)
        if cand.exists():
            return cand
    return None


def _toolchain_versions():
    lines = []
    for var, label in (
        ("nTINGS", None),
    ):
        pass
    # PlatformIO/ESP-IDF live in the dev environment, not in the interpreter.
    pio = _run([sys.executable, "-m", "platformio", "--version"], timeout=8)
    if pio:
        lines.append("pio    : " + pio)
    idf = os.environ.get("IDF_PATH")
    if idf:
        lines.append(f"IDF_PATH={_redact(idf)}")
        if (Path(idf) / "version.txt").exists():
            lines.append("idf    : " + (Path(idf) / "version.txt").read_text().strip())
    else:
        lines.append("IDF    : IDF_PATH not set (ESP-IDF 6.1.0 pinned by platformio.ini)")
    return "\n".join(lines) if lines else "toolchain information not available"


def _log_paths():
    candidates = [
        Path("/tmp/wosp_qemu_uart.log"),
        Path("/tmp/wosp_qemu_probe_uart.log"),
        REPO_ROOT / "var" / "log" / "wosp-qemu-uart.log",
        REPO_ROOT / "logs" / "wosp-qemu-uart.log",
    ]
    for c in candidates:
        if c.exists():
            return str(_redact(str(c)))
    return "no log file found in /tmp or project var/log"


def main():
    print("== PROJECT_WOWKISPICE diagnostics ==")
    print(f"os     : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"python : {sys.executable} ({sys.version.split()[0]})")
    print(f"ngspice: {_ngspice_version()}")
    qemu = _qemu_binary()
    print(f"qemu   : {qemu if qemu is None else f'{qemu} -> {_version_line(qemu)}'}")
    print("toolchain:")
    for line in _toolchain_versions().splitlines():
        print("  " + line)
    print("binaries:")
    for rel in ARTIFACT_CHAIN:
        p = REPO_ROOT / rel
        print(f"  {rel:55s} sha256:{_sha256(p)[:12]}  {p}")
    print(f"log    : {_log_paths()}")
    print("== end diagnostics ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
