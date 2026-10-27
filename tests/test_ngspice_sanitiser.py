"""test_ngspice_sanitiser.py - Sanitiser validation tests"""
import os
import subprocess
import sys
import tempfile
import unittest

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.ngspice_wrapper import NgSpiceEngine


class TestNgspiceSanitiser(unittest.TestCase):
    """Sanitiser tests for untrusted netlist input."""

    def test_control_banned(self):
        ".control should be rejected"
        with self.assertRaises(RuntimeError) as ctx:
            NgSpiceEngine._sanitise_line(".control")
        self.assertIn(".control", str(ctx.exception))

    def test_endc_banned(self):
        ".endc should be rejected"
        with self.assertRaises(RuntimeError) as ctx:
            NgSpiceEngine._sanitise_line(".endc")
        self.assertIn(".endc", str(ctx.exception))

    def test_tran_allowed(self):
        ".tran should be allowed"
        result = NgSpiceEngine._sanitise_line(".tran 1n 10n")
        self.assertEqual(result, ".tran 1n 10n")

    def test_ac_allowed(self):
        ".ac should be allowed"
        result = NgSpiceEngine._sanitise_line(".ac dec 5 1k 1MHz")
        self.assertEqual(result, ".ac dec 5 1k 1MHz")

    def test_dc_allowed(self):
        ".dc should be allowed"
        result = NgSpiceEngine._sanitise_line(".dc 0 1 0.1")
        self.assertEqual(result, ".dc 0 1 0.1")

    def test_op_allowed(self):
        ".op should be allowed"
        result = NgSpiceEngine._sanitise_line(".op")
        self.assertEqual(result, ".op")

    def test_model_allowed(self):
        ".model should be allowed"
        result = NgSpiceEngine._sanitise_line(".model mymosfet MOSFET")
        self.assertEqual(result, ".model mymosfet MOSFET")

    def test_measure_allowed(self):
        ".measure should be allowed"
        result = NgSpiceEngine._sanitise_line(".measure dc V(node)")
        self.assertEqual(result, ".measure dc V(node)")

    def test_run_allowed(self):
        "run command should be allowed in Cmd_ALLOWED"
        result = NgSpiceEngine._sanitise_line("run")
        self.assertEqual(result, "run")

    def test_alter_allowed(self):
        "alter command should be allowed (newly added)"
        result = NgSpiceEngine._sanitise_line("alter V1 = 5.0")
        self.assertEqual(result, "alter V1 = 5.0")

    def test_bg_run_allowed(self):
        "bg_run command should be allowed"
        result = NgSpiceEngine._sanitise_line("bg_run")
        self.assertEqual(result, "bg_run")

    def test_destroy_allowed(self):
        "destroy command should be allowed"
        result = NgSpiceEngine._sanitise_line("destroy")
        self.assertEqual(result, "destroy")

    def test_unknown_directive_passes(self):
        "Unknown directives that are not .control/.endc pass through"
        result = NgSpiceEngine._sanitise_line(".foo")
        # Unknown directives pass - they're not in the allowlist but not explicitly banned either
        # This is acceptable since the netlist will fail at ngSpice_Circ load time
        self.assertEqual(result, ".foo")

    def test_control_with_whitespace_banned(self):
        ".control with leading space should still be banned"
        with self.assertRaises(RuntimeError) as ctx:
            NgSpiceEngine._sanitise_line("  .control")
        self.assertIn(".control", str(ctx.exception))

    def test_alter_with_equation(self):
        "alter with various equations should be allowed"
        result = NgSpiceEngine._sanitise_line("alter V1 = sin(t)")
        self.assertEqual(result, "alter V1 = sin(t)")

    def test_sanitise_line_preserves_comments(self):
        "Comment lines starting with * should pass through"
        result = NgSpiceEngine._sanitise_line("* This is a comment")
        self.assertEqual(result, "* This is a comment")

    def test_sanitise_line_preserves_blanks(self):
        "Blank lines should pass through"
        result = NgSpiceEngine._sanitise_line("")
        self.assertEqual(result, "")


class TestMeasAlias(unittest.TestCase):
    """J4: .meas is ngspice's short form of .measure and must not be rejected.

    The netlist in tests/test_ui_polish.py:1346-1350 uses `.meas tran ...`
    verbatim, so the allowlist must contain the alias or the editor's own
    measurement workflow fails at load time.
    """

    @pytest.mark.timeout(30)
    def test_meas_alias_is_allowed(self):
        line = ".meas tran vout_max MAX v(out)"
        self.assertEqual(NgSpiceEngine._sanitise_line(line), line)

    @pytest.mark.timeout(30)
    def test_meas_alias_is_allowed_case_insensitive(self):
        line = ".MEAS tran vout_min MIN v(out)"
        self.assertEqual(NgSpiceEngine._sanitise_line(line), line)


class TestIncludeAllowlist(unittest.TestCase):
    """J4: .include/.lib/.inc are allowed only inside ALLOWED_INCLUDE_DIRS.

    Default policy: no directory outside the set. The set exists because
    tests/test_components_library.py:16,34 loads
    circuits/components/models.lib through `.include`.
    """

    LIB = os.path.join(NgSpiceEngine.PROJECT_ROOT,
                       "circuits", "components", "models.lib")
    ALLOWED = os.path.join(NgSpiceEngine.PROJECT_ROOT,
                           "circuits", "components")

    @pytest.mark.timeout(30)
    def test_allowlist_is_exactly_the_known_library_directory(self):
        """Default policy check: exactly one directory, nothing else."""
        real = {os.path.realpath(d) for d in NgSpiceEngine.ALLOWED_INCLUDE_DIRS}
        self.assertEqual(real, {os.path.realpath(self.ALLOWED)})

    @pytest.mark.timeout(30)
    def test_the_listed_library_file_really_exists(self):
        """The allowlisted path must be a real file, not a invented one."""
        self.assertTrue(os.path.isfile(self.LIB),
                        f"missing library: {self.LIB}")

    @pytest.mark.timeout(30)
    def test_include_of_the_listed_library_is_allowed(self):
        line = f'.include "{self.LIB}"'
        self.assertEqual(NgSpiceEngine._sanitise_line(line), line)

    @pytest.mark.timeout(30)
    def test_include_relative_to_repo_root_is_allowed(self):
        """J3c/3b: a repo-relative include is accepted AND rewritten to the
        validated absolute path, so ngspice reads exactly the file that was
        checked, whatever the process working directory is.

        Old assertion (this job's first draft): the line round-trips
        unchanged. That allowed ngspice to resolve the same relative string
        against ITS cwd instead - see the rewrite in _sanitise_line.
        """
        line = '.include circuits/components/models.lib'
        result = NgSpiceEngine._sanitise_line(line)
        expected_abs = os.path.realpath(self.LIB)
        self.assertEqual(result, '.include ' + expected_abs)
        # the rewritten target must live under the repo, never under cwd
        self.assertTrue(result.endswith(expected_abs))

    @pytest.mark.timeout(30)
    def test_include_outside_allowed_dirs_is_rejected(self):
        outside = os.path.join(os.path.expanduser("~"), "not_allowed.lib")
        with self.assertRaises(RuntimeError) as ctx:
            NgSpiceEngine._sanitise_line(f'.include "{outside}"')
        msg = str(ctx.exception)
        self.assertIn("outside allowed directories", msg)
        self.assertIn(outside, msg)

    @pytest.mark.timeout(30)
    def test_include_traversal_out_of_allowed_dir_is_rejected(self):
        """'..' must collapse before the check, not after it."""
        raw = "circuits/components/../../../secrets.lib"
        with self.assertRaises(RuntimeError) as ctx:
            NgSpiceEngine._sanitise_line(f'.include "{raw}"')
        self.assertIn("outside allowed directories", str(ctx.exception))

    @pytest.mark.timeout(30)
    def test_include_without_argument_is_rejected(self):
        with self.assertRaises(RuntimeError) as ctx:
            NgSpiceEngine._sanitise_line(".include")
        self.assertIn("no file argument", str(ctx.exception))

    @pytest.mark.timeout(30)
    def test_lib_inside_allowed_dir_is_allowed(self):
        line = f'.lib "{self.LIB}"'
        self.assertEqual(NgSpiceEngine._sanitise_line(line), line)

    @pytest.mark.timeout(30)
    def test_lib_outside_allowed_dirs_is_rejected(self):
        outside = os.path.join(os.path.expanduser("~"), "not_allowed.lib")
        with self.assertRaises(RuntimeError) as ctx:
            NgSpiceEngine._sanitise_line(f'.lib "{outside}"')
        self.assertIn("outside allowed directories", str(ctx.exception))


class TestIncludedFileContent(unittest.TestCase):
    """3b: the sanitiser must inspect the LINES of an included file.

    Measured before this fix (logs/out entry for job S3B-INCLUDE): a temp
    library placed inside circuits/components, containing a .control block
    with `shell echo PWNED> <marker>`, loaded and RAN on both HEAD and the
    draft - marker file created, `PWNED` printed. Checking only the
    top-level netlist lines was therefore insufficient.
    """

    TMP_PREFIX = "__tmp_s3b_scan_"

    def _lib(self, name):
        return os.path.join(NgSpiceEngine.PROJECT_ROOT, "circuits",
                            "components", self.TMP_PREFIX + name + ".lib")

    def setUp(self):
        self.marker = os.path.join(tempfile.gettempdir(),
                                   "wosp_s3b_marker.txt")
        if os.path.exists(self.marker):
            os.remove(self.marker)
        self._created = []

    def tearDown(self):
        for path in self._created:
            if os.path.exists(path):
                os.remove(path)
        # belt: nothing from this class may survive in the repo dir
        leftovers = [p for p in (
            os.path.join(os.path.dirname(self._lib("x")), f)
            for f in os.listdir(os.path.dirname(self._lib("x")))
        ) if os.path.basename(p).startswith(self.TMP_PREFIX)]
        assert not leftovers, f"temp libs not cleaned up: {leftovers}"

    def _write(self, name, content):
        path = self._lib(name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        self._created.append(path)
        return path

    @pytest.mark.timeout(30)
    def test_control_block_inside_included_file_is_rejected(self):
        lib = self._write("control", (
            "* tmp lib\n"
            ".control\n"
            f"shell echo PWNED> {self.marker}\n"
            ".endc\n"
            ".model S3B D(IS=1e-12 N=1.0)\n"
        ))
        with self.assertRaises(RuntimeError) as ctx:
            NgSpiceEngine._sanitise_line(f'.include "{lib}"')
        msg = str(ctx.exception)
        self.assertIn(".control", msg)
        self.assertIn(os.path.basename(lib), msg,
                      "the error must name the offending file")

    @pytest.mark.timeout(60)
    def test_engine_load_rejects_it_and_marker_never_appears(self):
        """Full app path: NgSpiceEngine.load_circuit must refuse the deck so
        ngspice is never handed the payload. The marker assertion is the
        observable from the empirical exploit - it would catch a regression
        that lets ngspice run the deck before validation finishes."""
        lib = self._write("engine", (
            "* tmp lib\n"
            ".control\n"
            f"shell echo PWNED> {self.marker}\n"
            ".endc\n"
            ".model S3B D(IS=1e-12 N=1.0)\n"
        ))
        engine = NgSpiceEngine(verbose=False)
        with self.assertRaises(RuntimeError):
            engine.load_circuit([
                "* 3b",
                f'.include "{lib}"',
                "V1 in 0 DC 1",
                "R1 in out 1k",
                ".op",
                ".end",
            ])
        self.assertFalse(
            os.path.exists(self.marker),
            "the .control payload inside the include must never execute")

    @pytest.mark.timeout(30)
    def test_nested_include_inside_allowlist_is_allowed(self):
        b = self._write("nest_b", ".model NESTB D(IS=1e-12 N=1.0)\n")
        a = self._write("nest_a",
                        f'.include "{b}"\n.model NESTA D(IS=1e-12 N=1.0)\n')
        line = f'.include "{a}"'
        self.assertEqual(NgSpiceEngine._sanitise_line(line), line)

    @pytest.mark.timeout(30)
    def test_self_including_file_hits_the_depth_limit(self):
        """A cycle must fail fast with the depth message, not recurse."""
        x_path = self._lib("cycle")
        self._write("cycle", '.include "' + x_path + '"\n')
        with self.assertRaises(RuntimeError) as ctx:
            NgSpiceEngine._sanitise_line('.include "' + x_path + '"')
        self.assertIn("nesting exceeds", str(ctx.exception))

    @pytest.mark.timeout(30)
    def test_missing_file_inside_allowed_dir_is_rejected(self):
        missing = self._lib("never_written")
        self.assertFalse(os.path.exists(missing))
        with self.assertRaises(RuntimeError) as ctx:
            NgSpiceEngine._sanitise_line(f'.include "{missing}"')
        self.assertIn("not found", str(ctx.exception))


class TestIncludeCwdIndependence(unittest.TestCase):
    """3c: the same include decisions from a different working directory.

    ALLOWED_INCLUDE_DIRS is anchored at PROJECT_ROOT = repo root derived from
    the wrapper file's own location (bridge/..), never from cwd; and the
    validated line is rewritten to an absolute path, so ngspice reads exactly
    the checked file even when the process started elsewhere.
    """

    @pytest.mark.timeout(60)
    def test_decisions_are_identical_from_a_foreign_cwd(self):
        script = f'''\
import os, sys
sys.path.insert(0, {ROOT!r})
from bridge.ngspice_wrapper import NgSpiceEngine as E
lib = os.path.join(E.PROJECT_ROOT, "circuits", "components", "models.lib")
assert os.path.isfile(lib), "fixture missing"
r = E._sanitise_line(".include " + lib)
assert r == ".include " + os.path.realpath(lib), r
r2 = E._sanitise_line(".include circuits/components/models.lib")
assert r2.endswith(os.path.realpath(lib)), r2
assert os.getcwd() != E.PROJECT_ROOT, "cwd not foreign"
ok = False
try:
    E._sanitise_line('.include "C:\\\\outside_allowed.lib"')
except RuntimeError as e:
    ok = "outside allowed directories" in str(e)
assert ok, "outside include not rejected from foreign cwd"
print("CWD_PROOF", os.getcwd())
print("ROOT_PROOF", E.PROJECT_ROOT)
print("ALL_CHECKS_PASSED")
'''
        foreign = tempfile.mkdtemp(prefix="wosp_foreign_cwd_")
        p = subprocess.run(
            [sys.executable, "-c", script],
            cwd=foreign,
            capture_output=True,
            encoding="utf-8", errors="replace",
            timeout=50,
        )
        out = p.stdout + p.stderr
        assert p.returncode == 0, out
        assert "ALL_CHECKS_PASSED" in out, out
        assert "CWD_PROOF" in out and "ROOT_PROOF" in out, out
        assert foreign in out, "cwd proof missing"


if __name__ == "__main__":
    unittest.main()