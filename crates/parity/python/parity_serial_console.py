#!/usr/bin/env python3
"""
parity_serial_console.py - cross-implementation diff of bridge/serial_console.py
against the Rust port in crates/wowkispice-core/src/serial_console.rs.

One fixed battery of UART-console inputs, computed twice (Python vs Rust),
over one identical key space.  Keys are index-based (pu[i], sc[i], gs[i],
clear[i]).  Strings are compared as text; counts as integers.

Run:  .venv/Scripts/python.exe crates/parity/python/parity_serial_console.py <path-to-parity_serial_console>
"""

from __future__ import annotations

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

from bridge import serial_console as m  # noqa: E402

BINARY_NAME = "parity_serial_console"


def enc_lines(lines: List[str]) -> str:
    return "||".join(lines)


def enc_text(s: str) -> str:
    return s.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")


def battery() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []

    # pu[i]: parse_uart
    out.append(("pu[0]", enc_lines(m.parse_uart(""))))
    out.append(("pu[1]", enc_lines(m.parse_uart("hello"))))
    out.append(("pu[2]", enc_lines(m.parse_uart("a\nb\nc"))))
    out.append(("pu[3]", enc_lines(m.parse_uart("a\r\nb\r\nc\r\n"))))
    out.append(("pu[4]", enc_lines(m.parse_uart("a\r\nb\nc\r\nd"))))
    out.append(("pu[5]", enc_lines(m.parse_uart("a\n\nb\n\n"))))
    out.append(("pu[6]", enc_lines(m.parse_uart("  a  \n\tb\t\n"))))
    out.append(("pu[7]", enc_lines(m.parse_uart("a\nb"))))

    # sc[i]: SerialConsole behavior
    c = m.SerialConsole(10)
    c.write("line1\nline2\nline3\n")
    out.append((
        "sc[0]",
        f"count={c.count}|total_seen={c.total_seen}|text={enc_text(c.text())}|dropped={c.dropped}",
    ))

    c = m.SerialConsole(3)
    c.write("a\nb\nc\nd\ne\n")
    out.append((
        "sc[1]",
        f"count={c.count}|total_seen={c.total_seen}|dropped={c.dropped}|text={enc_text(c.text())}",
    ))

    c = m.SerialConsole()
    out.append(("sc[2]", f"max_lines={c.max_lines}"))

    c = m.SerialConsole(0)  # clamps to 1
    c.write("x\ny\nz\n")
    out.append((
        "sc[3]",
        f"count={c.count}|total_seen={c.total_seen}|dropped={c.dropped}|text={enc_text(c.text())}",
    ))

    # ---- gs[i]: grep + summary
    c = m.SerialConsole(10)
    c.write("Error: something failed\nWarning: be careful\ninfo: all good\n")
    hits = c.grep("error")
    s = c.summary()
    out.append((
        "gs[0]",
        f"hits={enc_lines(hits)}|lines={s['lines']}|dropped={s['dropped']}|"
        f"truncated={s['truncated']}|max_lines={s['max_lines']}",
    ))

    c = m.SerialConsole(10)
    c.write("hello world\n")
    hits = c.grep("xyz")
    s = c.summary()
    out.append((
        "gs[1]",
        f"hits={enc_lines(hits)}|lines={s['lines']}|dropped={s['dropped']}|"
        f"truncated={s['truncated']}|max_lines={s['max_lines']}",
    ))

    # ---- clear + text round-trip
    c = m.SerialConsole(10)
    c.write("line1\nline2\n")
    c.clear()
    out.append((
        "clear[0]",
        f"count={c.count}|total_seen={c.total_seen}|text={enc_text(c.text())}",
    ))

    return out


# ---------------------------------------------------------------- rust side


def run_rust_battery(binary: str, manifest: str) -> Dict[str, str]:
    proc = subprocess.run(
        [binary, manifest],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"parity_serial_console (rust) exited {proc.returncode}\n{proc.stderr}"
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
    return a == b


def describe_value(v: str) -> str:
    return repr(v)


def main(argv: List[str]) -> int:
    if len(argv) > 1:
        binary = argv[1]
    else:
        binary = shutil.which(BINARY_NAME) or ""
    if not binary or not os.path.exists(binary):
        raise SystemExit(
            f"usage: parity_serial_console.py <path-to-parity_serial_console>\n"
            f"(the Rust executable built from "
            f"crates/parity/src/bin/parity_serial_console.rs)"
        )

    fd, manifest = tempfile.mkstemp(prefix="wosp_parity_manifest_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("")

        py: Dict[str, str] = {}
        py.update(dict(battery()))
        rs = run_rust_battery(binary, manifest)
    finally:
        if os.path.exists(manifest):
            os.remove(manifest)

    only_py = sorted(set(py) - set(rs))
    only_rs = sorted(set(rs) - set(py))
    mismatch = sorted(k for k in set(py) & set(rs) if not values_agree(py[k], rs[k]))

    if not (only_py or only_rs or mismatch):
        print(f"PARITY OK — {len(py)} values identical between "
              f"bridge/serial_console.py and crates/wowkispice-core/src/serial_console.rs")
        return 0

    print("PARITY FAILED: bridge/serial_console.py and "
          "crates/wowkispice-core/src/serial_console.rs disagree\n")
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
