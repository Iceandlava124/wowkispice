"""
selfcheck.py - One command that answers: "can this machine run WOSP?"

Checks, in the order things usually break:
  1. interpreter   - version, and whether the repo's .venv is the one running
  2. dependencies  - numpy, matplotlib, pyqtgraph, pypdf, pytest, PyQt5
  3. ngspice       - the shared library is found, loads, and binds its C API
  4. known circuit - a real solve of two circuits with hand-checkable answers
  5. test runner   - tools/run_tests.py (full by default; --quick runs two suites)

Exit status is 0 only when every check passes, so it is usable as a gate.
Every failure prints its own remediation, so the output is the whole
instruction. Run it through run_selfcheck.bat (Windows) so the repo's .venv
is used when one exists.
"""

import argparse
import importlib
import importlib.metadata
import math
import os
import platform
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(REPO, "tools", "run_tests.py")
VENV_PYTHON = os.path.join(REPO, ".venv", "Scripts", "python.exe")
DEFAULT_TIMEOUT = 1800.0
DEPENDENCIES = ("numpy", "matplotlib", "pyqtgraph", "pypdf", "pytest", "PyQt5")

fails = []
warns = []


def report(state, name, detail=""):
    tag = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]"}[state]
    print("%s %-13s %s" % (tag, name, detail.rstrip()))
    if state == "fail":
        fails.append(name)
    elif state == "warn":
        warns.append(name)


# --------------------------------------------------------------------------
# 1. interpreter
# --------------------------------------------------------------------------
def check_interpreter():
    venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    detail = "Python %s (%s) at %s" % (
        platform.python_version(),
        "virtualenv" if venv else "system interpreter",
        sys.executable)
    if sys.version_info < (3, 10):
        report("fail", "interpreter", detail)
        print("        need Python >= 3.10; the verified target is 3.12")
        return
    report("ok", "interpreter", detail)
    if not venv and os.path.exists(VENV_PYTHON):
        report("warn", "interpreter",
               "the repo's .venv exists - prefer run_selfcheck.bat, or "
               ".venv\\Scripts\\python.exe tools\\selfcheck.py")


# --------------------------------------------------------------------------
# 2. dependencies
# --------------------------------------------------------------------------
def check_dependencies():
    versions, missing = [], []
    for name in DEPENDENCIES:
        try:
            importlib.import_module(name)
            if name == "PyQt5":
                importlib.import_module("PyQt5.QtWidgets")
        except Exception as exc:
            missing.append("%s (%s)" % (name, exc))
            continue
        try:
            versions.append("%s %s" % (name, importlib.metadata.version(name)))
        except importlib.metadata.PackageNotFoundError:
            versions.append(name)
    if missing:
        report("fail", "dependencies", "missing: " + ", ".join(missing))
        print("        install with: python -m pip install -r requirements.txt")
        print("        (or run setup.ps1 / setup.sh once)")
        return
    report("ok", "dependencies", ", ".join(versions))


# --------------------------------------------------------------------------
# 3. ngspice library load
# --------------------------------------------------------------------------
def check_ngspice():
    sys.path.insert(0, REPO)
    try:
        from bridge.ngspice_wrapper import NgSpiceEngine
    except Exception as exc:
        report("fail", "ngspice", "cannot import bridge.ngspice_wrapper: %s" % exc)
        return
    try:
        engine = NgSpiceEngine(verbose=False)
    except Exception as exc:
        lines = str(exc).splitlines() or [type(exc).__name__]
        report("fail", "ngspice", lines[0])
        for line in lines[1:8]:
            print("        " + line)
        return
    report("ok", "ngspice", "loaded %s" % engine.dll_path)


# --------------------------------------------------------------------------
# 4. known circuit with hand-checkable answers
# --------------------------------------------------------------------------
def _solve(lines, vector):
    """Solve a netlist on a fresh engine; return (time, vector) float lists."""
    from bridge.ngspice_wrapper import NgSpiceEngine

    engine = NgSpiceEngine(verbose=False)
    engine.load_circuit(lines)
    rc = engine.cmd("run")
    if rc != 0:
        raise RuntimeError("ngspice run returned %s" % rc)
    return engine.get_vector_array("time"), engine.get_vector_array(vector)


def check_known_circuit():
    # 1) RC step: R=1k, C=1u -> tau=1 ms, 5 V step at t=0.
    #    Exact: v(tau) = 5*(1-1/e) = 3.1606 V, v(5*tau) = 5*(1-e^-5) = 4.9663 V.
    #    (This block documents the known-circuit oracle; the acceptance gate is
    #    that SELF-CHECK: PASS is printed only when both solves are inside
    #    tolerance.)
    rc_lines = [
        "* WOSP self-check: RC step",
        "V1 in 0 PWL(0 0 1u 5)",
        "R1 in out 1k",
        "C1 out 0 1u IC=0",
        ".tran 10u 5m uic",
        ".end",
    ]
    expected_tau = 5.0 * (1.0 - math.exp(-1.0))
    expected_5tau = 5.0 * (1.0 - math.exp(-5.0))
    try:
        t_rc, v_rc = _solve(rc_lines, "out")
    except Exception as exc:
        report("fail", "known circuit", "RC solve failed: %s" % exc)
        return
    if len(v_rc) < 100:
        report("fail", "known circuit",
               "RC solve produced only %d points" % len(v_rc))
        return
    tau = 1.0e-3
    i_tau = min(range(len(t_rc)), key=lambda i: abs(t_rc[i] - tau))
    v_tau, v_ramp = v_rc[i_tau], v_rc[-1]
    rc_ok = (abs(v_tau - expected_tau) <= expected_tau * 0.03
             and abs(v_ramp - expected_5tau) <= expected_5tau * 0.01)

    # 2) Resistive divider: 10 V across 1k/1k -> 5.000 V at the midpoint.
    div_lines = [
        "* WOSP self-check: resistor divider",
        "V1 in 0 DC 10",
        "R1 in mid 1k",
        "R2 mid 0 1k",
        ".tran 1u 10u uic",
        ".end",
    ]
    try:
        _t_div, v_div = _solve(div_lines, "mid")
        v_mid = v_div[-1] if v_div else float("nan")
    except Exception as exc:
        report("fail", "known circuit", "divider solve failed: %s" % exc)
        return
    div_ok = abs(v_mid - 5.0) <= 5.0 * 0.005

    detail = ("RC tau -> %.3f V (%.3f expected), 5*tau -> %.3f V (%.3f); "
              "divider -> %.3f V (5.000)"
              % (v_tau, expected_tau, v_ramp, expected_5tau, v_mid))
    if rc_ok and div_ok:
        report("ok", "known circuit", detail)
    else:
        report("fail", "known circuit", detail)
        print("        the solver ran but the physics is off - do not trust "
              "simulation results until this passes")


# --------------------------------------------------------------------------
# 5. test runner
# --------------------------------------------------------------------------
def _tail(path, count=12):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    return lines[-count:] if lines else []


def _summary_line(lines):
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and set(stripped) != {"="}:
            return stripped
    return ""


def check_runner(quick, timeout):
    env = dict(os.environ)
    env["WOSP_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="wosp-selfcheck-settings-")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    if quick:
        cmd = [sys.executable, "-m", "pytest",
               os.path.join("tests", "test_ngspice_bridge.py"),
               os.path.join("tests", "test_closed_loop_buck.py"),
               "-q", "-p", "no:cacheprovider"]
        label = "quick mode: 2 representative suites"
    else:
        cmd = [sys.executable, RUNNER]
        label = "full suite via tools/run_tests.py"

    print("[ .. ] %-13s running %s%s" % (
        "test runner", label,
        " (can take several minutes)" if not quick else ""))

    log = tempfile.NamedTemporaryFile(
        "w+", suffix=".log", delete=False, encoding="utf-8", errors="replace")
    started = time.monotonic()
    try:
        with log:
            proc = subprocess.run(cmd, cwd=REPO, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        report("fail", "test runner", "TIMEOUT after %.0f s" % timeout)
        return
    elapsed = time.monotonic() - started
    tail = _tail(log.name)
    if rc == 0:
        report("ok", "test runner",
               "%s in %.1f s" % (_summary_line(tail) or "exit 0", elapsed))
    else:
        report("fail", "test runner", "exit %d after %.1f s" % (rc, elapsed))
        for line in tail:
            print("        " + line.rstrip())


# --------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify this machine can run WOSP: interpreter, "
                    "dependencies, ngspice, a known solve, and the test runner.")
    parser.add_argument("--quick", action="store_true",
                        help="skip the full suite; run two representative "
                             "suites instead (seconds, not minutes)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="seconds allowed for the test-runner check "
                             "(default 1800)")
    args = parser.parse_args(argv)

    print("WOSP environment self-check")
    print("=" * 34)
    print("python : %s" % sys.executable)
    print("repo   : %s" % REPO)
    print()

    check_interpreter()
    check_dependencies()
    check_ngspice()
    check_known_circuit()
    check_runner(args.quick, args.timeout)

    print()
    print("-" * 34)
    if fails:
        print("SELF-CHECK: FAIL (%d of 5 checks failed: %s)"
              % (len(fails), ", ".join(fails)))
        print("Fix the [FAIL] lines above, then run this again.")
        return 1
    suffix = " (quick mode - full suite not run)" if args.quick else ""
    if warns:
        print("SELF-CHECK: PASS with %d warning(s)%s" % (len(warns), suffix))
    else:
        print("SELF-CHECK: PASS%s" % suffix)
    return 0


if __name__ == "__main__":
    sys.exit(main())
