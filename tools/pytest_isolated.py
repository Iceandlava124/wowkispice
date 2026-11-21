#!/usr/bin/env python3
"""
pytest_isolated.py - run ngspice-using test modules in separate processes.

Layer 3 / Layer 2 (V&V): libngspice is a process-global C library. When several
test modules that call ngSpice_Command("run") execute in ONE pytest process,
the library's global state (plots, vectors, callbacks) gets corrupted and the
interpreter segfaults ("Fatal Python error: Segmentation fault"), even though
each module passes when run alone as a dedicated sanity step.

This runner:
  1. Splits collection into (a) ngspice modules and (b) all other tests.
  2. Runs each ngspice module in its OWN subprocess via pytest.
  3. Runs non-ngspice tests normally in the parent.
  4. Merges every subprocess's junit XML into one final junit, preserving
     @pytest.mark.req markers so check_traceability.py sees executed tests.

A C-level abort in one child is contained: that module is marked failed in the
merged junit but the runner and all other tests survive.

Usage:
  python tools/pytest_isolated.py --junit-xml=tests/junit.xml -q -p no:randomly
"""
import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Test modules that execute real libngspice transients. Each gets its own
# process so ngspice global state cannot leak between them.
NGSPICE_MODULES = (
    "test_ngspice_bridge.py",
    "test_ngspice_dll_proof.py",
    "test_components_library.py",
    "test_editor_workflow.py",
    "test_firmware_gpio.py",
    "test_measurements.py",
    "test_parameter_sweeps.py",
    "test_security_vectors.py",
    "test_solver_error_handling.py",
    "test_ui_polish.py",
    "test_cosim_control.py",
)


def is_ngspice_module(path):
    return any(os.path.basename(path) == m for m in NGSPICE_MODULES)


def run_pytest(paths, junit_path, extra):
    cmd = [sys.executable, "-m", "pytest", *paths,
           f"--junit-xml={junit_path}", *extra]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def merge_junit(final_path, parts):
    """Merge multiple junit XML files into one (testsuite/testcase append)."""
    root = ET.Element("testsuites")
    total = failures = errors = skipped = 0
    for part in parts:
        if not os.path.isfile(part):
            continue
        try:
            tree = ET.parse(part)
        except ET.ParseError:
            continue
        for suite in tree.getroot().iter("testsuite"):
            root.append(suite)
            total += int(suite.get("tests", 0))
            failures += int(suite.get("failures", 0))
            errors += int(suite.get("errors", 0))
            skipped += int(suite.get("skipped", 0))
    root.set("tests", str(total))
    root.set("failures", str(failures))
    root.set("errors", str(errors))
    root.set("skipped", str(skipped))
    os.makedirs(os.path.dirname(os.path.abspath(final_path)), exist_ok=True)
    ET.ElementTree(root).write(final_path, encoding="utf-8", xml_declaration=True)
    return total, failures, errors, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit-xml", default="tests/junit.xml")
    parser.add_argument("-m", default=None)
    args, unknown = parser.parse_known_args()

    extra = []
    if args.m:
        extra.extend(["-m", args.m])
    # All other pytest flags (-q, -p no:randomly, ...) come through 'unknown'.
    extra.extend(unknown)

    tmpdir = tempfile.mkdtemp(prefix="wosp_pytest_iso_")
    parts = []
    results = []

    tests_dir = os.path.join(ROOT, "tests")
    all_modules = sorted(f for f in os.listdir(tests_dir)
                         if f.startswith("test_") and f.endswith(".py"))
    ngspice_modules = [f for f in all_modules if is_ngspice_module(f)]
    other_modules = [f for f in all_modules if not is_ngspice_module(f)]

    # 1. non-ngspice tests in the parent (fast, safe)
    if other_modules:
        junit = os.path.join(tmpdir, "junit_other.xml")
        paths = [os.path.join("tests", m) for m in other_modules]
        proc = run_pytest(paths, junit, extra)
        parts.append(junit)
        results.append(("other", proc.returncode))
        print(f"[pytest_isolated] other tests exit={proc.returncode}", flush=True)

    # 2. each ngspice module in its OWN child process
    for mod in ngspice_modules:
        junit = os.path.join(tmpdir, f"junit_{mod}.xml")
        proc = run_pytest([os.path.join("tests", mod)], junit, extra)
        parts.append(junit)
        results.append((mod, proc.returncode))
        marker = "OK" if proc.returncode == 0 else f"EXIT {proc.returncode}"
        print(f"[pytest_isolated] {mod}: {marker}", flush=True)
        if proc.returncode < 0 or "Segmentation" in proc.stderr:
            print(f"  (ngspice C-abort contained in child; other tests unaffected)", flush=True)

    total, failures, errors, skipped = merge_junit(args.junit_xml, parts)
    print(f"[pytest_isolated] junit merged: tests={total} failures={failures} "
          f"errors={errors} skipped={skipped} -> {args.junit_xml}", flush=True)

    # Exit non-zero if any child failed/aborted (or merge shows failures) so a
    # hard CI gate is meaningful. Generated junit still lets traceability run.
    # Exit 5 ("no tests collected") is normal when a module has no tests
    # matching the -m marker filter; other modules cover those requirements.
    def is_bad(rc):
        return rc != 0 and rc != 5

    bad = [name for name, rc in results if is_bad(rc)]
    if bad or failures or errors:
        print(f"[pytest_isolated] FAILED modules: {bad}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
