"""
test_selfcheck.py - The environment self-check must itself work.

tools/selfcheck.py is the first command a new user runs, so it gets the same
treatment as everything else: a test. The quick mode is used so the suite
stays fast; it still exercises the interpreter, dependency, ngspice and
known-circuit checks, and the test-runner check against two real suites.
"""

import os
import subprocess
import sys
import tempfile
import unittest

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELFCHECK = os.path.join(REPO, "tools", "selfcheck.py")
SELFCHECK_BAT = os.path.join(REPO, "run_selfcheck.bat")


class TestSelfcheck(unittest.TestCase):

    def test_quick_selfcheck_reports_pass(self):
        env = dict(os.environ)
        env["WOSP_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="wosp-selfcheck-test-")
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        proc = subprocess.run(
            [sys.executable, SELFCHECK, "--quick"],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
        output = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, output[-2000:])
        self.assertIn("SELF-CHECK: PASS", output)
        for stage in ("interpreter", "dependencies", "ngspice",
                      "known circuit", "test runner"):
            self.assertIn(stage, output,
                          f"self-check output never mentions {stage!r}")

    def test_non_venv_python_reexecutes_into_the_project_venv(self):
        """The gate must not depend on whichever python is on PATH.

        Starting tools/selfcheck.py with the base interpreter (the one the
        venv was created from) must re-exec under .venv and still pass. This
        is the path a reader takes when they run `python tools/selfcheck.py`
        from a clean shell, which is what earlier failures got wrong.
        """
        base = getattr(sys, "_base_executable", "")
        if (not base or not os.path.isfile(base)
                or os.path.samefile(base, sys.executable)):
            self.skipTest("no distinct base interpreter available")
        env = dict(os.environ)
        env.pop("VIRTUAL_ENV", None)
        env.pop("WOSP_SELFCHECK_REEXEC", None)
        env["WOSP_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="wosp-reexec-")
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        proc = subprocess.run(
            [base, SELFCHECK, "--quick"],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
        output = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, output[-2000:])
        self.assertIn("using the project interpreter:", output)
        self.assertIn(os.path.join(REPO, ".venv"), output)
        self.assertIn("SELF-CHECK: PASS", output)

    @pytest.mark.timeout(120)
    @unittest.skipUnless(sys.platform == "win32",
                         "run_selfcheck.bat is Windows-only")
    def test_bat_propagates_the_exit_code(self):
        """run_selfcheck.bat must return selfcheck.py's own exit status.

        Measured before the fix: a fresh clone printed
        ``SELF-CHECK: FAIL (3 of 5 checks failed: ...)`` from the bat and
        still reported ``exit=0`` (log entry #277), so nothing downstream
        could gate on it. An unknown flag makes selfcheck.py exit 2 through
        argparse in a fraction of a second, so the propagation is checked
        without running the suite the self-check would otherwise launch.
        """
        proc = subprocess.run(
            ["cmd", "/c", SELFCHECK_BAT, "--not-a-real-flag"],
            cwd=REPO, capture_output=True, text=True, errors="replace",
            timeout=100)
        output = proc.stdout + proc.stderr
        self.assertNotIn("SELF-CHECK: PASS", output, output[-2000:])
        self.assertEqual(proc.returncode, 2, output[-2000:])

    @pytest.mark.timeout(180)
    @unittest.skipUnless(sys.platform == "win32",
                         "run_selfcheck.bat is Windows-only")
    def test_bat_still_returns_zero_on_pass(self):
        """The other half of the contract: a green quick self-check must still
        exit 0 through the same propagation path (exit 2 here would mean the
        bat started carrying python's status into the wrong place)."""
        env = dict(os.environ)
        env["WOSP_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="wosp-selfcheck-bat-")
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        proc = subprocess.run(
            ["cmd", "/c", SELFCHECK_BAT, "--quick"],
            cwd=REPO, env=env, capture_output=True, text=True,
            errors="replace", timeout=150)
        output = proc.stdout + proc.stderr
        self.assertIn("SELF-CHECK: PASS", output, output[-2000:])
        self.assertEqual(proc.returncode, 0, output[-2000:])


if __name__ == "__main__":
    unittest.main()
