#!/usr/bin/env python3
"""
parity_gpio_model.py - cross-implementation diff of bridge/gpio_model.py
against the Rust port in crates/wowkispice-core/src/gpio_model.rs.

One fixed battery of GPIO inputs, computed twice (Python vs Rust), over one
identical key space.  Keys are index-based (spice[i], desc[i], dir[i],
ana[i], freq[i]).  Floats are compared as doubles; strings as text.

Run:  .venv/Scripts/python.exe crates/parity/python/parity_gpio_model.py <path-to-parity_gpio_model>
"""

from __future__ import annotations

import math
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

from bridge import gpio_model as m  # noqa: E402

BINARY_NAME = "parity_gpio_model"


# ---------------------------------------------------------------- formatting helpers

def enc_opt_f64(v):
    if v is None:
        return "None"
    return f"{v:.10e}"


def enc_levels(levels):
    return "|".join(f"{t:.10e}:{l}" for t, l in levels)


# ---------------------------------------------------------------- synthetic inputs (identical to Rust side)

TIMES_SQUARE: List[float] = [i * 5e-6 for i in range(2000)]
VALS_SQUARE: List[float] = [3.3 if (i // 100) % 2 == 0 else 0.0 for i in range(2000)]

TIMES_STATIC: List[float] = [i * 1e-3 for i in range(10)]
VALS_STATIC: List[float] = [3.3] * 10


# ---------------------------------------------------------------- Python-side battery

def battery() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []

    # spice[i]: spice_card
    out.append(("spice[0]", m.spice_card({"mode": "static", "level": 1}, 1e-7)))
    out.append(("spice[1]", m.spice_card({"mode": "static", "level": 0}, 1e-7)))
    out.append(
        (
            "spice[2]",
            m.spice_card(
                {"mode": "square", "freq_hz": 1000, "duty": 0.25, "vhigh": 3.3},
                1e-7,
            ),
        )
    )
    out.append(("spice[3]", m.spice_card(None, 1e-7)))

    # desc[i]: describe_pin
    out.append(
        (
            "desc[0]",
            m.describe_pin("GPIO18", {"mode": "square", "freq_hz": 1000, "duty": 0.5}),
        )
    )
    out.append(
        ("desc[1]", m.describe_pin("GPIO5", {"mode": "static", "level": 1}))
    )

    # dir[i]: pin_direction
    out.append(("dir[0]", m.pin_direction("GND")))
    out.append(("dir[1]", m.pin_direction("VCC")))
    out.append(("dir[2]", m.pin_direction("A0")))
    out.append(("dir[3]", m.pin_direction("ADC1")))
    out.append(("dir[4]", m.pin_direction("GPIO18")))
    out.append(("dir[5]", m.pin_direction("D13")))
    out.append(("dir[6]", m.pin_direction("TX")))

    # ana[i]: analyze_pin
    info = m.analyze_pin(TIMES_SQUARE, VALS_SQUARE, 1.65)
    out.append(
        (
            "ana[0]",
            (
                f"points={info['points']}|transitions={info['transitions']}|"
                f"duty={info['duty']:.10e}|v_min={enc_opt_f64(info['v_min'])}|"
                f"v_max={enc_opt_f64(info['v_max'])}|levels={enc_levels(info['levels'])}"
            ),
        )
    )
    info = m.analyze_pin(TIMES_STATIC, VALS_STATIC, 1.65)
    out.append(
        (
            "ana[1]",
            (
                f"points={info['points']}|transitions={info['transitions']}|"
                f"duty={info['duty']:.10e}|v_min={enc_opt_f64(info['v_min'])}|"
                f"v_max={enc_opt_f64(info['v_max'])}|levels={enc_levels(info['levels'])}"
            ),
        )
    )

    # freq[i]: measured_frequency
    out.append(
        ("freq[0]", enc_opt_f64(m.measured_frequency(TIMES_SQUARE, VALS_SQUARE, 1.65)))
    )
    out.append(
        ("freq[1]", enc_opt_f64(m.measured_frequency(TIMES_STATIC, VALS_STATIC, 1.65)))
    )

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
            f"parity_gpio_model (rust) exited {proc.returncode}\n{proc.stderr}"
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
    """Compare two battery values field-by-field.

    Values are pipe-separated records of key=value pairs. Each field's value
    (after the '=') is compared as a float (with abs+rel tolerance for
    1-2 ULP summation-order noise) when both sides parse as floats,
    otherwise as exact text.
    """
    fa = a.split("|")
    fb = b.split("|")
    if len(fa) != len(fb):
        return False
    for x, y in zip(fa, fb):
        xv = x.split("=", 1)[1] if "=" in x else x
        yv = y.split("=", 1)[1] if "=" in y else y
        try:
            fx, fy = float(xv), float(yv)
            if fx != fy and abs(fx - fy) > max(1e-9 * max(abs(fx), abs(fy)), 1e-12):
                return False
        except ValueError:
            if x != y:
                return False
    return True


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
            f"usage: parity_gpio_model.py <path-to-parity_gpio_model>\n"
            f"(the Rust executable built from "
            f"crates/parity/src/bin/parity_gpio_model.rs)"
        )

    fd, manifest = tempfile.mkstemp(prefix="wosp_parity_manifest_")
    try:
        # The gpio_model battery is pure-array; no fixture files needed.
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
              f"bridge/gpio_model.py and crates/wowkispice-core/src/gpio_model.rs")
        return 0

    print("PARITY FAILED: bridge/gpio_model.py and "
          "crates/wowkispice-core/src/gpio_model.rs disagree\n")
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
