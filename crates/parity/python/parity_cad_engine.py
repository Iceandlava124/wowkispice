#!/usr/bin/env python3
"""
parity_cad_engine.py - cross-implementation diff of bridge/cad_engine.py
against the Rust port in crates/wowkispice-core/src/cad_engine.rs.

One fixed battery of schematic-graph facts, computed twice (Python vs Rust),
over one identical key space.  Strings are compared as text; counts as
integers; booleans print True/False.

Run:  .venv/Scripts/python.exe crates/parity/python/parity_cad_engine.py <path-to-parity_cad_engine>
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

from bridge import cad_engine as m  # noqa: E402

BINARY_NAME = "parity_cad_engine"


def battery() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []

    # im[i]: is_mcu
    for i, ct in enumerate(
        ["ESP32", "esp32", "ARDUINO_UNO", "STM32F103", "RP2040", "MCU",
         "CUSTOM", "R", "C", "GND", "V", "D"]
    ):
        out.append((f"im[{i}]", str(m.is_mcu(ct))))

    # sc[i]: SchematicComponent defaults / round-trip
    c = m.SchematicComponent("R1", "R", "R1", "10k", 0.0, 0.0)
    out.append((
        "sc[0]",
        f"comp_id={c.comp_id}|comp_type={c.comp_type}|name={c.name}|value={c.value}|"
        f"x={c.x}|y={c.y}|footprint={c.footprint}|mpn={c.mpn}|manufacturer={c.manufacturer}|"
        f"description={c.description}|values={c.values}|cost_usd={c.cost_usd}|"
        f"rotation={c.rotation}|pins_len={len(c.pins)}",
    ))

    pins = {"1": "in", "2": "out"}
    c = m.SchematicComponent(
        comp_id="R1", comp_type="R", name="R1", value="10k", x=10.5, y=20.5,
        footprint="Resistor_SMD:R_0603", mpn="ABC123", manufacturer="DigiKey",
        description="10k resistor", values="10k", cost_usd=0.15,
        pins=pins, rotation=90.0,
    )
    dict_ = c.to_dict()
    restored = m.SchematicComponent.from_dict(dict_)
    out.append((
        "sc[1]",
        f"comp_id={restored.comp_id}|name={restored.name}|value={restored.value}|"
        f"x={restored.x}|y={restored.y}|footprint={restored.footprint}|mpn={restored.mpn}|"
        f"manufacturer={restored.manufacturer}|cost_usd={restored.cost_usd}|"
        f"rotation={restored.rotation}|pins_len={len(restored.pins)}",
    ))

    # eng[i]: SchematicNetlistEngine
    g = m.SchematicNetlistEngine()
    g.add_component(m.SchematicComponent("V1", "V", "V1", "12", 0.0, 0.0))
    g.add_component(m.SchematicComponent("R1", "R", "R1", "1k", 80.0, 0.0))
    g.add_component(m.SchematicComponent("GND1", "GND", "GND", "", 80.0, 80.0))
    g.add_wire("V1:+", "R1:1", "in")
    g.add_wire("V1:-", "GND1:1", "gnd")
    g.add_wire("R1:2", "GND1:1", "gnd")

    lines, nets, warnings = g.compile_netlist()
    out.append((
        "eng[0]",
        f"lines={len(lines)}|nets={len(nets)}|warnings={len(warnings)}|"
        f"has_tran={'.tran' in ' '.join(lines)}|has_end={'.end' in ' '.join(lines)}",
    ))
    out.append(("eng[1]", "||".join(nets)))
    out.append(("eng[2]", "||".join(warnings)))

    # eng[3]: empty schematic → legacy buck
    g = m.SchematicNetlistEngine()
    lines, nets, warnings = g.compile_netlist()
    out.append((
        "eng[3]",
        f"lines={len(lines)}|nets={len(nets)}|warnings={len(warnings)}|"
        f"has_vin={'Vin' in ' '.join(lines)}|has_end={'.end' in ' '.join(lines)}",
    ))

    # eng[4]: unknown analysis panics
    g = m.SchematicNetlistEngine()
    g.add_component(m.SchematicComponent("R1", "R", "R1", "1k", 0.0, 0.0))
    try:
        g.compile_netlist(analysis="fourier")
        panicked = False
    except ValueError:
        panicked = True
    out.append(("eng[4]", str(panicked)))

    # eng[5]: unknown mcu_pins panics
    g = m.SchematicNetlistEngine()
    g.add_component(m.SchematicComponent("R1", "R", "R1", "1k", 0.0, 0.0))
    try:
        g.compile_netlist(mcu_pins="floating")
        panicked = False
    except ValueError:
        panicked = True
    out.append(("eng[5]", str(panicked)))

    # bom[i]: generate_bom_for
    g = m.SchematicNetlistEngine()
    g.add_component(m.SchematicComponent("R1", "R", "R1", "1k", 0.0, 0.0))
    g.add_component(m.SchematicComponent("C1", "C", "C1", "100n", 80.0, 0.0))
    g.add_component(m.SchematicComponent("GND1", "GND", "GND", "", 80.0, 80.0))
    rows = m.generate_bom_for(g)
    out.append(("bom[0]", f"rows={len(rows)}"))
    if rows:
        row = rows[0]
        out.append((
            "bom[1]",
            f"designator={row['Designator']}|type={row['Type']}|value={row['Value']}|"
            f"qty={row['Qty']}|cost={row['Unit Cost (USD)']}",
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
            f"parity_cad_engine (rust) exited {proc.returncode}\n{proc.stderr}"
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
            f"usage: parity_cad_engine.py <path-to-parity_cad_engine>\n"
            f"(the Rust executable built from "
            f"crates/parity/src/bin/parity_cad_engine.rs)"
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
              f"bridge/cad_engine.py and crates/wowkispice-core/src/cad_engine.rs")
        return 0

    print("PARITY FAILED: bridge/cad_engine.py and "
          "crates/wowkispice-core/src/cad_engine.rs disagree\n")
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
