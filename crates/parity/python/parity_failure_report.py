#!/usr/bin/env python3
"""
parity_failure_report.py - cross-implementation diff of bridge/ngspice_wrapper._failure_report
against the Rust port in crates/wowkispice-core/src/ngspice_wrapper.rs.

One fixed battery of ngspice output lines, computed twice (Python vs Rust),
over one identical key space.  Reports print "none" when no failure is
detected, "some(<text>)" when a failure report is produced.

Run:  .venv/Scripts/python.exe crates/parity/python/parity_failure_report.py <path-to-parity_failure_report>
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

from bridge import ngspice_wrapper as m  # noqa: E402

BINARY_NAME = "parity_failure_report"


def battery() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []

    completed = [
        "stdout No. of Data Rows : 565",
        "stderr doAnalyses: TRAN:  Timestep too small; time = 0.005, timestep = 0: cause unrecorded.",
        "stderr run simulation(s) aborted",
    ]
    early_abort = [
        "stdout No. of Data Rows : 210",
        "stderr doAnalyses: TRAN:  Timestep too small; time = 0.002, timestep = 0: cause unrecorded.",
        "stderr run simulation(s) aborted",
    ]
    no_rows = [
        "stderr doAnalyses: TRAN:  Timestep too small; time = 0.005, timestep = 0: cause unrecorded.",
        "stderr run simulation(s) aborted",
    ]
    op_failure = [
        "stdout No. of Data Rows : 10",
        "stderr Error: Transient op failed, timestep too small",
        "stderr Error: The operating point could not be simulated successfully.",
    ]

    def report(lines: List[str], tstop) -> str:
        r = m.NgSpiceEngine._failure_report(lines, tstop)
        return "none" if r is None else f"some({r})"

    # completed run with tstop=0.005 -> none
    out.append(("completed_tstop_0005", report(completed, 0.005)))
    # completed run with tstop=None -> some
    out.append(("completed_tstop_none", report(completed, None)))
    # early abort before tstop -> some
    out.append(("early_abort_tstop_0005", report(early_abort, 0.005)))
    # no rows -> some
    out.append(("no_rows_tstop_0005", report(no_rows, 0.005)))
    # operating point failure -> some
    out.append(("op_failure_tstop_1e-8", report(op_failure, 1e-8)))
    # companion line check
    out.append(("completed_companion_tstop_0005", report(completed, 0.005)))

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
            f"parity_failure_report (rust) exited {proc.returncode}\n{proc.stderr}"
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
            f"usage: parity_failure_report.py <path-to-parity_failure_report>\n"
            f"(the Rust executable built from "
            f"crates/parity/src/bin/parity_failure_report.rs)"
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
              f"bridge/ngspice_wrapper._failure_report and "
              f"crates/wowkispice-core/src/ngspice_wrapper._failure_report")
        return 0

    print("PARITY FAILED: bridge/ngspice_wrapper._failure_report and "
          "crates/wowkispice-core/src/ngspice_wrapper._failure_report disagree\n")
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
