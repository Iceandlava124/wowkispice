#!/usr/bin/env python3
"""
parity_netlist.py - cross-implementation diff of the sanitiser half of
bridge/ngspice_wrapper.py against the Rust port in
crates/wowkispice-core/src/netlist.rs.

One difference from parity_control_law.py's protocol: the include battery
reads FILES, so this driver creates a fixture set (deterministic names under
circuits/components, deleted afterwards), writes a manifest
(name<TAB>path per line) to a temp file, and passes its path to the Rust
binary, which builds the same battery entries from those manifest paths.
Everything else is computed directly.

For the sanitise_deck battery there is no engine-free Python function in the
module (load_circuit mixes the DLL call with the domestic phase), so the
driver recomputes the DOMESTIC phase from the module's own primitives
(_sanitise_line / _find_tstop), exactly as load_circuit does.  The doubled
"ngSpice_Circ rejected the untrusted netlist: " prefix on a failing deck
line is part of the battery and compared as text.

KEYS ARE INDEX-BASED (`line[17]`, `inc[3]`), like the control_law harness.
tstop / spice_seconds values are compared as doubles when both sides parse
as floats; everything else — sanitised lines and, most importantly, ALL
error messages — compares as text, so one paraphrased message fails run.

Run:  .venv/Scripts/python.exe crates/parity/python/parity_netlist.py <path-to-parity_netlist>
(the Rust binary is built from crates/parity/src/bin/parity_netlist.rs and
this driver invokes it with cwd=REPO so cwd-anchored candidates agree.)
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from typing import Dict, List, Tuple

# repo/crates/parity/python/this_file.py -> repo is four levels up.
REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, REPO)

from bridge.ngspice_wrapper import (  # noqa: E402  (path set above)
    NgSpiceEngine as E,
    _spice_seconds,
)

DECK_PREFIX = "ngSpice_Circ rejected the untrusted netlist: "

# ---------------------------------------------------------------- battery
# IDENTICAL content must exist in crates/parity/src/bin/parity_netlist.rs;
# a case that drifts on one side alone is reported as python-only or
# rust-only, a value that drifts is reported as a mismatch.

LINE_CASES = [
    "* comment",                                      # 0: passes through
    "",                                               # 1: blank passes
    "   ",                                            # 2: whitespace -> ""
    "+  .control",                                    # 3: one '+' strips
    "++ .control",                                    # 4: R3 gap
    ".control",                                       # 5: banned, no trailing space
    ".CONtrol",                                       # 6: banned, case-folded
    ".endc",                                          # 7
    ".ENDC extra",                                    # 8: regex branch
    ".tran 1n 10n",                                   # 9
    ".ac dec 5 1k 1MHz",                              # 10
    ".dc 0 1 0.1",                                    # 11
    ".op",                                            # 12
    ".model mymosfet MOSFET",                         # 13
    ".measure dc V(node)",                            # 14
    ".meas tran v(out) MAX",                          # 15: alias
    ".MEAS tran v(out) MIN",                          # 16: alias upper
    ".noise v(out) 1 100",                            # 17
    ".temp 27",                                       # 18
    ".save all",                                      # 19
    ".ic v(out)=0",                                   # 20
    ".nodeset v(node)=1",                             # 21
    ".step param X 1 10 1",                           # 22
    ".options noopiter",                              # 23
    ".param A=1",                                     # 24
    ".subckt X 1 2",                                  # 25
    ".ends",                                          # 26
    ".end",                                           # 27
    ".foo",                                           # 28: bare unknown passes
    ".foo bar",                                       # 29: unknown with args banned
    "run",                                            # 30
    "alter V1 = 5.0",                                 # 31
    "alter V1 = sin(t)",                              # 32
    "bg_run",                                         # 33
    "destroy",                                        # 34
    "R1 1 0 cmd(shell echo pwned)",                   # 35: banned command
    "R1 1 0 Cmd(big)",                                # 36: 'Cmd(' branch
    "* cmd(.control) inside comment",                 # 37: comment wins
    "V1 in 0 DC 1k",                                  # 38: element line
    ".include",                                       # 39: no file argument
    ".control ",                                      # 40: trailing space
    ".CONTROL reminder",                              # 41
    "\n.control",                                     # 42: LF-prefixed
    "  .control x",                                   # 43
]

CMD_CASES = [
    "run",                                            # 0
    "alter v1 = 5.0",                                 # 1
    "setplot tran1",                                  # 2
    "tran 1u 10m uic",                                # 3
    "   ",                                            # 4: empty command
    "shell echo hi",                                  # 5: banned verb
    "shell echo PWNED> C:\\wosp_parity_marker.txt",   # 6: vector 2
    'source "C:\\out.cir"',                           # 7
    'write "C:\\x.txt" v(out)',                       # 8
    'wrdata "C:\\x.txt" v(out)',                      # 9
    'hardcopy "C:\\x.png" v(out)',                    # 10
    "run\nshell echo PWNED",                          # 11: separator \n
    "run; shell echo PWNED",                          # 12
    "run | shell echo PWNED",                         # 13
    "run `shell echo PWNED`",                         # 14
    "run $x",                                         # 15
    "run <in",                                        # 16
    "run >out",                                       # 17
    "RUN",                                            # 18: verb folded, text raw
    "alter&stuff",                                    # 19: verb wins first
    "stop  ",                                         # 20: trailing space strip
]

SEC_CASES = [
    "1n", "5m", "10u", "2m", "5g", "7t", "3p", "12f",       # 0-7
    "meg", "300", "1u", "0",                               # 8-11
    "1.5k", ".5", "5.", "-3m", "+2M", "1e5", "2meg",       # 12-18
    "1e", "5mk", "abc", "1..0", "--1", "6G", "4H", "7N",   # 19-26
    "8K", "1e400", "2e-3",                                 # 27-29
]


# ---------------------------------------------------------------- fixtures


class Fixtures:
    """Deterministic temp libs under circuits/components, cleaned on exit."""

    PREFIX = "__tmp_parity_scan_"

    def __init__(self) -> None:
        self.paths: Dict[str, str] = {}
        self.created: List[str] = []
        comp = os.path.join(E.PROJECT_ROOT, "circuits", "components")

        def lib(name: str) -> str:
            return os.path.join(comp, self.PREFIX + name + ".lib")

        models = os.path.join(comp, "models.lib")
        outside = os.path.join(os.path.expanduser("~"), "not_allowed.lib")
        missing = lib("missing")
        if os.path.exists(missing):               # hygiene: from a dead run
            os.remove(missing)

        cycle = lib("cycle")
        with open(cycle, "w", encoding="utf-8", newline="\n") as fh:
            fh.write('.include "%s"\n' % cycle)
        self.created.append(cycle)

        nest_b = lib("nest_b")
        with open(nest_b, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(".model PAR NESTB(IS=1e-12 N=1.0)\n")
        self.created.append(nest_b)

        nest_a = lib("nest_a")
        with open(nest_a, "w", encoding="utf-8", newline="\n") as fh:
            fh.write('.include "%s"\n.model PAR NESTA(IS=1e-12 N=1.0)\n' % nest_b)
        self.created.append(nest_a)

        bad = lib("bad")
        with open(bad, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(
                "* tmp lib\n.control\n"
                "shell echo PWNED> Q:\\wosp_parity_marker.txt\n"
                ".endc\n.model PAR BAD(IS=1e-12 N=1.0)\n"
            )
        self.created.append(bad)

        self.paths = {
            "models": models,
            "outside": outside,
            "missing": missing,
            "cycle": cycle,
            "nest_a": nest_a,
            "nest_b": nest_b,
            "bad": bad,
        }

    def cleanup(self) -> None:
        for path in self.created:
            if os.path.exists(path):
                os.remove(path)


# ---------------------------------------------------------------- evaluators
# Value encoding: "OK:<value>" or "ERR:<python str(exception)>"; floats must
# round-trip identically through str(float) on the Python side and py_repr on
# the Rust side (both are the shortest round-trip decimal repr).
#
# Wire-escape (backslash first, then \n \r \t), applied by BOTH sides: some
# payloads embed real newlines/separators; comparing the escaped forms is
# the same text-equivalence.


def esc(v: str) -> str:
    return (
        v.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def line_value(line: str) -> str:
    try:
        return esc("OK:" + E._sanitise_line(line))
    except RuntimeError as exc:
        return esc("ERR:" + str(exc))


def cmd_value(command: str) -> str:
    try:
        return esc("OK:" + E.validate_cmd(command))
    except RuntimeError as exc:
        return esc("ERR:" + str(exc))


def sec_value(token: str) -> str:
    val = _spice_seconds(token)
    return "OK:" + str(val) if val is not None else "OK:None"


def deck_value(lines: List[str]) -> str:
    """load_circuit's domestic phase, from the module's own primitives."""
    try:
        sanitised: List[str] = []
        for raw in lines:
            if not raw.strip():
                continue
            sanitised.append(E._sanitise_line(raw))
    except RuntimeError as exc:
        return esc("ERR:" + DECK_PREFIX + str(exc))
    if not sanitised or not sanitised[0].startswith("*"):
        sanitised.insert(0, "* WOWKISPICE circuit")
    if not any(line.lower() == ".end" for line in sanitised):
        sanitised.append(".end")
    tstop = E._find_tstop(sanitised)
    return esc("OK:" + "\x1f".join(sanitised) + "\x1f" + str(tstop))


# ---------------------------------------------------------------- batteries


def build_rust_battery(fix: Fixtures) -> List[Tuple[str, str]]:
    """The include-family cases resolve real files, so they run through the
    same sanitiser with the fixtures in place (same module, same code path —
    what is diffed is the two implementations, not the batteries).
    Keys: inc[i]."""
    out: List[Tuple[str, str]] = []

    def inc(line: str) -> None:
        try:
            out.append(("inc[%d]" % len(out), esc("OK:" + E._sanitise_line(line))))
        except RuntimeError as exc:
            out.append(("inc[%d]" % len(out), esc("ERR:" + str(exc))))

    m = fix.paths["models"]
    inc('.include "%s"' % m)                       # 0: absolute, quoted
    inc(".include circuits/components/models.lib") # 1: relative, rewritten
    inc('.include "%s"' % fix.paths["outside"])    # 2: outside
    inc('.include "circuits/components/../../../secrets.lib"')  # 3
    inc(".include")                                # 4: no argument
    inc('.lib "%s"' % m)                           # 5: .lib inside
    inc('.lib "%s"' % fix.paths["outside"])        # 6: .lib outside
    inc('.include "%s"' % fix.paths["missing"])    # 7: not found
    inc('.include "%s"' % fix.paths["cycle"])      # 8: depth limit
    inc('.include "%s"' % fix.paths["bad"])        # 9: .control inside
    inc('.include "%s"' % fix.paths["nest_a"])     # 10: nested allowed
    inc('.inc "%s"' % m)                           # 11: .inc alias
    return out


def build_battery(fix: Fixtures) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for i, case in enumerate(LINE_CASES):
        out.append(("line[%d]" % i, line_value(case)))
    for i, case in enumerate(CMD_CASES):
        out.append(("cmd[%d]" % i, cmd_value(case)))
    for i, case in enumerate(SEC_CASES):
        out.append(("sec[%d]" % i, sec_value(case)))
    for key, value in build_rust_battery(fix):
        out.append((key, value))
    for i, case in enumerate(DECK_CASES):
        out.append(("deck[%d]" % i, deck_value(case)))
    return out


DECK_CASES = [
    ["* polarity", "V1 in 0 DC 1", "R1 in out 1k", ".op"],
    ["* tran", ".tran 1u 5m uic"],
    ["* bad", '.include "__tmp_parity_scan_bad.lib__PLACEHOLDER__"',
     "V1 in 0 DC 1", "R1 in out 1k", ".op", ".end"],
    [],
    ["V1 in 0 DC 1", ".ac dec 10 1 1e5"],
]


# ---------------------------------------------------------------- rust side


def run_rust_battery(binary: str, manifest: str) -> Dict[str, str]:
    """Runs the Rust binary with cwd=REPO; parses KEY<TAB>VALUE lines."""
    proc = subprocess.run(
        [binary, manifest],
        cwd=REPO,
        capture_output=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"parity_netlist (rust) exited {proc.returncode}\n{proc.stderr}")
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
        import shutil
        binary = shutil.which("parity_netlist") or ""
    if not binary or not os.path.exists(binary):
        raise SystemExit(
            "usage: parity_netlist.py <path-to-parity_netlist-binary>\n"
            "(the Rust executable built from "
            "crates/parity/src/bin/parity_netlist.rs)")

    fix = Fixtures()
    try:
        # The deck battery needs the bad-lib path; DECK_CASES[2] is filled
        # in here (it was a placeholder above).
        DECK_CASES[2][1] = '.include "%s"' % fix.paths["bad"]

        # Manifest for the Rust binary: name<TAB>path per line.
        fd, manifest = tempfile.mkstemp(prefix="wosp_parity_manifest_")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            for name, path in sorted(fix.paths.items()):
                fh.write(f"{name}\t{path}\n")

        py = dict(build_battery(fix))
        rs = run_rust_battery(binary, manifest)
    finally:
        if os.path.exists(manifest):
            os.remove(manifest)
        fix.cleanup()

    only_py = sorted(set(py) - set(rs))
    only_rs = sorted(set(rs) - set(py))
    mismatch = sorted(k for k in set(py) & set(rs)
                      if not values_agree(py[k], rs[k]))

    if not (only_py or only_rs or mismatch):
        print(f"PARITY OK — {len(py)} values identical between "
              f"bridge/ngspice_wrapper.py and crates/wowkispice-core/src/netlist.rs")
        return 0

    print("PARITY FAILED: bridge/ngspice_wrapper.py and "
          "crates/wowkispice-core/src/netlist.rs disagree\n")
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
            print(f"  {k}\n      python {describe_value(py[k])}\n"
                  f"      rust   {describe_value(rs[k])}")
        print()
    print(f"{len(mismatch)} differing, {len(only_py)} python-only, "
          f"{len(only_rs)} rust-only out of {len(set(py) | set(rs))} keys")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
