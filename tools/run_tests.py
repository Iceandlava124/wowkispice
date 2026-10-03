"""
run_tests.py - Run every test suite and print one summary.

Each suite is a standalone unittest file, run in its own process so one suite's
global ngspice state cannot leak into the next (sharedspice is a process-wide
singleton, so that matters).
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

COUNT_RE = re.compile(r"Ran (\d+) test")
PER_SUITE_TIMEOUT = 300


def run_suite(path):
    """(name, passed_count, failure_text) for one suite."""
    name = os.path.basename(path)
    try:
        proc = subprocess.run([PYTHON, path], cwd=ROOT, timeout=PER_SUITE_TIMEOUT,
                              capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return name, 0, "TIMEOUT after %ds" % PER_SUITE_TIMEOUT
    out = proc.stdout + proc.stderr
    match = COUNT_RE.search(out)
    count = int(match.group(1)) if match else 0
    if proc.returncode != 0:
        return name, 0, out.strip()
    return name, count, None


def main():
    tests_dir = os.path.join(ROOT, "tests")
    suites = sorted(f for f in os.listdir(tests_dir)
                    if f.startswith("test_") and f.endswith(".py"))
    if not suites:
        print("no test_*.py files found in", tests_dir)
        return 1

    print("Running %d suite(s) with %s\n" % (len(suites), PYTHON))
    total = 0
    failures = []
    for suite in suites:
        name, count, error = run_suite(os.path.join(tests_dir, suite))
        if error:
            failures.append((name, error))
            print("  FAIL  %-28s %s" % (name, error.splitlines()[-1][:60]))
        else:
            total += count
            print("  ok    %-28s %d tests" % (name, count))

    print("\n" + "=" * 52)
    if failures:
        print("%d test(s) passed, %d suite(s) FAILED" % (total, len(failures)))
        for name, error in failures:
            print("\n--- %s ---\n%s" % (name, error))
        print("=" * 52)
        return 1
    print("%d tests passed, all suites green" % total)
    print("=" * 52)
    return 0


if __name__ == "__main__":
    sys.exit(main())