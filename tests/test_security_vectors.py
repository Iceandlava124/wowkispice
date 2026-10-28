"""test_security_vectors.py - SECURITY.md exploit vectors, executed for real.

Row R4 of SCORECARD v1 requires every exploit vector listed in SECURITY.md to
have a marker-file or file-read test that passes. Before job R4-01 those
results were one-off hand runs (logs/cmd/s3a_child.py, job S3A-EXPLOIT); no
test re-ran them, so a regression could silently restore any vector.

One test per row of the SECURITY.md table:

  #  vector                                          blocked by
  1  .control + shell inside a netlist               directive allowlist
  2  cmd("shell ...")                                cmd() allowlist (R4-01)
  3  cmd('source "<file>"')                          cmd() allowlist (R4-01)
  4  .include of a file outside circuits/components  include allowlist
  5  cmd('write "<path>" ...')                       cmd() allowlist (R4-01)
  6  cmd('wrdata "<path>" ...')                      cmd() allowlist (R4-01)
  7  cmd('hardcopy "<path>" ...')                    cmd() allowlist (R4-01)
  8  bare "shell ... > marker" in element position   ngspice parser
  9  .control + shell inside an ALLOWED include      included-content scan

Markers live in a per-test temporary directory, never in the repo, so
"marker absent" is a claim about the filesystem rather than about captured
output. Where a vector is supposed to be stopped before ngspice sees it, the
test also proves that: ngSpice_Command / ngSpice_Circ are shadowed with
recorders and the test asserts the recorder was never called.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bridge.ngspice_wrapper import NgSpiceEngine, resolve_ngspice_library


def _engine():
    """Build an engine on the real library, or skip naming what was tried."""
    lib, tried = resolve_ngspice_library()
    if lib is None:
        pytest.skip("ngspice shared library not found; tried: "
                    + "; ".join(tried))
    return NgSpiceEngine()


def _record_and_block(engine):
    """Shadow the two C entry points; record calls instead of executing them.

    Returns the list of recorded calls. A test asserting `calls == []` proves
    the payload never reached ngspice at all - that is the "file never read"
    form of evidence for the include/source vectors.
    """
    calls = []

    def command_spy(cmd):
        calls.append(("ngSpice_Command", cmd))
        return 0

    def circ_spy(deck):
        calls.append(("ngSpice_Circ", list(deck)))
        return 0

    engine.lib.ngSpice_Command = command_spy
    engine.lib.ngSpice_Circ = circ_spy
    return calls


class _MarkerCase(unittest.TestCase):
    """Shared marker-file plumbing; markers never touch the repository."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="wosp_r4_vectors_")
        self._libs = []

    def tearDown(self):
        for path in self._libs:
            if os.path.exists(path):
                os.remove(path)
        for name in os.listdir(self._tmp):
            os.remove(os.path.join(self._tmp, name))
        os.rmdir(self._tmp)

    def marker(self, name):
        return os.path.join(self._tmp, "marker_%s.txt" % name)

    def payload(self, name, text="PWNED"):
        return os.path.join(self._tmp, "payload_%s.cir" % name)

    def allowed_lib(self, name, content):
        path = os.path.join(NgSpiceEngine.PROJECT_ROOT, "circuits",
                            "components", "__tmp_r4_vec_%s.lib" % name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        self._libs.append(path)
        return path


class TestNetlistVectors(_MarkerCase):
    """Vectors whose payload travels inside a netlist."""

    @pytest.mark.timeout(60)
    def test_vector1_control_block_is_rejected_and_never_runs(self):
        engine = _engine()
        calls = _record_and_block(engine)
        marker = self.marker("v1")
        deck = [
            "* v1 .control block with shell",
            "V1 in 0 5",
            ".control",
            "shell echo PWNED> " + marker,
            ".endc",
            ".end",
        ]
        with pytest.raises(RuntimeError) as ctx:
            engine.load_circuit(deck)
        self.assertIn(".control", str(ctx.value))
        self.assertFalse(os.path.exists(marker),
                         "vector 1 executed: marker file created")
        self.assertEqual(calls, [], "the deck reached ngspice despite the ban")

    @pytest.mark.timeout(60)
    def test_vector4_include_outside_allowlist_is_not_read(self):
        engine = _engine()
        calls = _record_and_block(engine)
        marker = self.marker("v4")
        outside = os.path.join(self._tmp, "outside_include.lib")
        with open(outside, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("sentinel_outside_xyz\n.control\n"
                     "shell echo PWNED> %s\n.endc\n" % marker)
        deck = ["* v4", 'V1 in 0 5', '.include "%s"' % outside,
                "R1 in out 1k", ".op", ".end"]
        with pytest.raises(RuntimeError) as ctx:
            engine.load_circuit(deck)
        msg = str(ctx.value)
        self.assertIn("outside allowed directories", msg)
        self.assertFalse(os.path.exists(marker),
                         "vector 4 executed: marker file created")
        self.assertEqual(calls, [], "the outside include reached ngspice")

    @pytest.mark.timeout(60)
    def test_vector9_control_inside_allowed_include_is_rejected(self):
        engine = _engine()
        calls = _record_and_block(engine)
        marker = self.marker("v9")
        lib = self.allowed_lib("control", (
            "* tmp lib\n"
            ".control\n"
            "shell echo PWNED> %s\n"
            ".endc\n"
            ".model R4VEC D(IS=1e-12 N=1.0)\n" % marker
        ))
        with pytest.raises(RuntimeError) as ctx:
            engine.load_circuit(["* v9", 'V1 in 0 5', '.include "%s"' % lib,
                                 "R1 in out 1k", ".op", ".end"])
        msg = str(ctx.value)
        self.assertIn(".control", msg)
        self.assertIn(os.path.basename(lib), msg)
        self.assertFalse(os.path.exists(marker),
                         "vector 9 executed: marker file created")
        self.assertEqual(calls, [], "the payload reached ngspice")

    @pytest.mark.timeout(60)
    def test_vector8_element_position_shell_never_executes(self):
        """A bare `shell ...` line is not a directive; ngspice parses it as an
        element and errors out. Either outcome is acceptable here - the claim
        under test is only that no marker appears."""
        engine = _engine()
        marker = self.marker("v8")
        deck = ["* v8", "V1 in 0 5", "shell echo PWNED> " + marker,
                "R1 in out 1k", ".op", ".end"]
        try:
            engine.load_circuit(deck)
            engine.cmd("run")
        except RuntimeError:
            pass
        self.assertFalse(os.path.exists(marker),
                         "vector 8 executed: marker file created")
        engine.cmd("destroy")


class TestCommandVectors(_MarkerCase):
    """Vectors that travel through NgSpiceEngine.cmd().

    Before job R4-01 cmd() passed its string straight to ngSpice_Command and
    vector 2 created the marker on the sanitiser draft as well as on HEAD.
    Each test asserts both halves of the fix: the command is refused, and the
    refusal happens before the library is entered.
    """

    @pytest.mark.timeout(60)
    def test_vector2_shell_command_is_rejected(self):
        engine = _engine()
        calls = _record_and_block(engine)
        marker = self.marker("v2")
        with pytest.raises(RuntimeError) as ctx:
            engine.cmd("shell echo PWNED> " + marker)
        msg = str(ctx.value)
        self.assertIn("shell", msg)
        self.assertIn("allowlist", msg)
        self.assertFalse(os.path.exists(marker),
                         "vector 2 executed: marker file created")
        self.assertEqual(calls, [], "the shell command reached ngspice")

    @pytest.mark.timeout(60)
    def test_vector3_source_command_is_rejected_blind(self):
        engine = _engine()
        calls = _record_and_block(engine)
        payload = self.payload("v3")
        with open(payload, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("* sentinel_outside_xyz\n.end\n")
        with pytest.raises(RuntimeError) as ctx:
            engine.cmd('source "%s"' % payload)
        self.assertIn("source", str(ctx.value))
        self.assertEqual(calls, [],
                         "ngspice was asked to source a file: it may read it")

    @pytest.mark.timeout(60)
    def test_vector5_write_cannot_create_a_file(self):
        engine = _engine()
        calls = _record_and_block(engine)
        target = self.payload("v5_out")
        with pytest.raises(RuntimeError) as ctx:
            engine.cmd('write "%s" v(out)' % target)
        self.assertIn("write", str(ctx.value))
        self.assertFalse(os.path.exists(target))
        self.assertEqual(calls, [])

    @pytest.mark.timeout(60)
    def test_vector6_wrdata_cannot_create_a_file(self):
        engine = _engine()
        calls = _record_and_block(engine)
        target = self.payload("v6_out")
        with pytest.raises(RuntimeError) as ctx:
            engine.cmd('wrdata "%s" v(out)' % target)
        self.assertIn("wrdata", str(ctx.value))
        self.assertFalse(os.path.exists(target))
        self.assertEqual(calls, [])

    @pytest.mark.timeout(60)
    def test_vector7_hardcopy_cannot_create_a_file(self):
        engine = _engine()
        calls = _record_and_block(engine)
        target = self.payload("v7_out")
        with pytest.raises(RuntimeError) as ctx:
            engine.cmd('hardcopy "%s" v(out)' % target)
        self.assertIn("hardcopy", str(ctx.value))
        self.assertFalse(os.path.exists(target))
        self.assertEqual(calls, [])

    @pytest.mark.timeout(60)
    def test_command_separators_are_rejected(self):
        """A newline or ';' inside one cmd() string can carry a second
        command past any first-token check."""
        engine = _engine()
        calls = _record_and_block(engine)
        for payload in ("run\nshell echo PWNED",
                        "run; shell echo PWNED",
                        "run | shell echo PWNED",
                        "run `shell echo PWNED`"):
            with pytest.raises(RuntimeError):
                engine.cmd(payload)
        self.assertEqual(calls, [])

    @pytest.mark.timeout(60)
    def test_legitimate_commands_still_pass_the_guard(self):
        """The guard must not break the commands the code actually sends."""
        for ok in ("run", "bg_run", "reset", "destroy", "stop", "setplot",
                   "setplot tran1", "alter v1 = 5.0", "alter rload 10k",
                   "tran 1u 10m uic"):
            self.assertEqual(NgSpiceEngine.validate_cmd(ok), ok.strip())


class TestLocalSocketBinding(unittest.TestCase):
    """Every bind/listen/-monitor in this repository is loopback only."""

    LOOPBACK = ("127.0.0.1", "localhost", "::1")
    BIND_RE = re.compile(r"\.bind\(\s*\(\s*([\"'])(.+?)\1")
    TCP_ARG_RE = re.compile(r"tcp:([A-Za-z0-9_.:\[\]]*):(\d+)")
    FILES = ("bridge", "ui", "tools", "tests")

    def _sources(self):
        found = []
        for sub in self.FILES:
            base = os.path.join(ROOT, sub)
            for name in sorted(os.listdir(base)):
                if name.endswith(".py"):
                    found.append(os.path.join(base, name))
        return found

    @pytest.mark.timeout(30)
    def test_every_bind_target_is_loopback(self):
        offenders = []
        for path in self._sources():
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    m = self.BIND_RE.search(line)
                    if m and m.group(2) not in self.LOOPBACK:
                        offenders.append("%s:%d %s" % (
                            os.path.relpath(path, ROOT), lineno, line.strip()))
        self.assertEqual(offenders, [],
                         "non-loopback bind targets: %s" % offenders)

    @pytest.mark.timeout(30)
    def test_every_tcp_endpoint_is_loopback(self):
        offenders = []
        for path in self._sources():
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for host, port in self.TCP_ARG_RE.findall(text):
                if host not in self.LOOPBACK:
                    offenders.append("%s tcp:%s:%s" % (
                        os.path.relpath(path, ROOT), host, port))
        self.assertEqual(offenders, [],
                         "non-loopback QEMU tcp endpoints: %s" % offenders)

    @pytest.mark.timeout(30)
    def test_no_wildcard_address_anywhere(self):
        # Needle assembled at runtime so this file does not match itself.
        # An IPv6 wildcard bind ("::") is already caught as a non-loopback
        # target by test_every_bind_target_is_loopback.
        wildcard = "0.0.0." + "0"
        offenders = []
        for path in self._sources():
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    if wildcard in line:
                        offenders.append("%s:%d" % (
                            os.path.relpath(path, ROOT), lineno))
        self.assertFalse(offenders, "wildcard listeners: "
                         + "; ".join(offenders))


class TestTrackedFileHygiene(unittest.TestCase):
    """No absolute user paths and no credential-shaped strings in git."""

    # Requires a real user/account segment, so bare prefixes and the
    # redaction helpers in tools/diagnostics.py do not false-positive.
    USER_PATH_RE = re.compile(
        r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"'`)]+)"
        r"|/(?:home|Users)/([^/\s\"'`)]+)")
    SECRET_RES = (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"ghp_[A-Za-z0-9]{36}"),
        re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*"
                   r"['\"][A-Za-z0-9/+_-]{16,}['\"]"),
    )

    def _tracked(self):
        out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True)
        self.assertEqual(out.returncode, 0, out.stdout)
        return [line for line in out.stdout.splitlines() if line.strip()]

    @pytest.mark.timeout(60)
    def test_no_absolute_user_paths_in_tracked_files(self):
        hits = []
        for rel in self._tracked():
            path = os.path.join(ROOT, rel)
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    if self.USER_PATH_RE.search(line):
                        hits.append("%s:%d" % (rel, lineno))
        self.assertFalse(hits, "absolute user paths in tracked files: "
                         + "; ".join(hits))

    @pytest.mark.timeout(60)
    def test_no_credential_shaped_strings_in_tracked_files(self):
        hits = []
        for rel in self._tracked():
            path = os.path.join(ROOT, rel)
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    for pattern in self.SECRET_RES:
                        if pattern.search(line):
                            hits.append("%s:%d %s" % (rel, lineno,
                                                      pattern.pattern))
                            break
        self.assertFalse(hits, "credential-shaped strings: "
                         + "; ".join(hits))


if __name__ == "__main__":
    unittest.main()
