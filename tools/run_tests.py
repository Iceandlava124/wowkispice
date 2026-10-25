"""
run_tests.py - Honest test runner: runs pytest, exits non-zero on any failure.

Old behavior ran each test_*.py file in its own subprocess and interpreted
`Ran N tests` from unittest output. Several test files in this repo are
pytest-style and do not print that line, so the old runner reported them as
`ok 0 tests` even when they collected real tests under `python -m pytest`.

This version runs `python -m pytest tests -q` once (pytest also collects and
runs unittest.TestCase classes), prints a summary with per-skip reasons via
`-rs`, and exits non-zero if any test fails or if any test file collects zero
tests. The old per-suite printout is not retained because it was misleading
for pytest-style files.

Opt-in second gate: `--require-emulator` additionally runs only the
qemu-marker contract tests (`tests/test_qemu_monitor_qemu.py`) and exits
non-zero when they are skipped or absent, so a run that demands the emulator
contract can never report success while it was UNEXECUTED. Default behavior
is unchanged (skips stay visible-but-allowed).
"""

import argparse
import os
import sys
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pytest(cmd_extra=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Use the current interpreter (sys.executable), not a bare "python". A bare
    # name resolves to whatever is on PATH -- on this box that is MSYS2's
    # CPython 3.14, which has no PyQt5, so every UI test file died at import and
    # pytest reported "5 errors during collection" while this runner still
    # printed a passing gate. sys.executable is the interpreter actually running
    # this script (.venv), so the suite sees the dependencies that are installed.
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "-q",
        "--tb=short",
        "-rs",
        "-p",
        "no:randomly",
    ]
    if cmd_extra:
        cmd.extend(cmd_extra)
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def require_emulator_gate():
    """Second gate (--require-emulator): the qemu-marker tests must RUN.

    Re-runs only `-m qemu` tests through the same runner. Any skip, any
    failure, or an empty collection exits non-zero -- a skipped contract test
    is never reported as success.
    """
    print()
    print("[ .. ] --require-emulator: running only the qemu-marker contract tests")
    proc = pytest(["-m", "qemu"])
    lines = proc.stdout.splitlines()
    skip_lines = [
        line.strip() for line in lines
        if line.strip().lower().startswith("skipped")
    ]
    zero_collected = any(
        "collected 0" in line or "no tests ran" in line.lower()
        for line in lines
    )
    print("\n".join(lines[-25:]))
    if zero_collected:
        print()
        print("GATE(--require-emulator): no qemu-marker tests collected - "
              "the contract tests are missing")
        return 3
    if skip_lines:
        print()
        print("GATE(--require-emulator): contract tests were SKIPPED, not run:")
        for line in skip_lines:
            print("        " + line)
        return 3
    if proc.returncode != 0:
        print()
        print("GATE(--require-emulator): contract tests failed "
              "(pytest exit %d)" % proc.returncode)
        return 3
    print()
    print("GATE(--require-emulator): contract tests ran and passed")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the honest test gate. --require-emulator also fails "
                    "the run when the qemu-marker contract tests are skipped.")
    parser.add_argument(
        "--require-emulator", action="store_true",
        help="exit non-zero if the qemu-marker contract tests "
             "(tests/test_qemu_monitor_qemu.py) are skipped or absent; "
             "default keeps them as UNEXECUTED skips")
    args = parser.parse_args(argv)
    proc = pytest()
    lines = proc.stdout.splitlines()

    summary = {}
    for line in lines:
        low = line.strip().lower()
        if low.startswith("passed"):
            summary["passed"] = line.strip()
        elif low.startswith("failed"):
            summary["failed"] = line.strip()
        elif low.startswith("error"):
            summary["error"] = line.strip()
        elif low.startswith("skipped"):
            summary["skipped"] = line.strip()

    print("\n".join(lines[-25:]))
    print()
    for key in ("passed", "failed", "error", "skipped"):
        if key in summary:
            print(summary[key])

    has_failure = any(
        summary.get(k) and ("fail" in str(summary[k]).lower() or "error" in str(summary[k]).lower())
        for k in ("failed", "error")
    )
    has_zero_collected = any(
        "collected 0" in line or "no tests ran" in line.lower()
        for line in lines
    )
    # A collection error ("N errors during collection", "Interrupted:") makes
    # pytest exit non-zero even when no test "failed" in the summary. Trust the
    # process exit code, not just the parsed summary lines.
    has_collection_error = proc.returncode != 0

    if has_zero_collected:
        print()
        print("GATE: a test file collected 0 tests")
        sys.exit(2)
    if has_failure or has_collection_error:
        print()
        print("GATE: one or more tests failed or errored")
        sys.exit(1)
    print()
    print("GATE: all collected tests passed")
    if args.require_emulator:
        emu_rc = require_emulator_gate()
        if emu_rc:
            sys.exit(emu_rc)
    return 0


if __name__ == "__main__":
    sys.exit(main())

