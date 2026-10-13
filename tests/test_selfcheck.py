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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELFCHECK = os.path.join(REPO, "tools", "selfcheck.py")


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


if __name__ == "__main__":
    unittest.main()
