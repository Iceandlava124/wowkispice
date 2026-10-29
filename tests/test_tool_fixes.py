"""Tests for the two queued tool fixes (J7 / J9).

1. tools/doctor.py must survive a cp1252/ASCII console (no non-ASCII glyphs)
   and must discover the ngspice library exactly the way
   bridge.ngspice_wrapper does, instead of its own dead-glob logic.
2. tools/check_traceability.py must exit non-zero when it parses zero
   requirements or finds zero marked tests (it used to print OK and exit 0).
"""
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCTOR = os.path.join(ROOT, "tools", "doctor.py")
TRACE = os.path.join(ROOT, "tools", "check_traceability.py")


# ---------------------------------------------------------------- doctor.py

@pytest.mark.timeout(120)
def test_doctor_runs_on_an_ascii_console():
    """A cp1252 console cannot encode check/cross glyphs; the report must not
    die mid-run with UnicodeEncodeError (reported by J11: doctor exits with a
    cp1252 crash on the checkmark).

    PYTHONIOENCODING=ascii makes any non-ASCII byte a hard error, which is a
    stricter version of the cp1252 console this reproduces.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "ascii"
    p = subprocess.run(
        [sys.executable, DOCTOR],
        cwd=ROOT, env=env, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    assert "UnicodeEncodeError" not in p.stderr, p.stderr[-2000:]
    assert "WOSP Environment Doctor" in p.stdout, p.stdout[:500]
    # The report must print the ASCII tags themselves: with
    # errors="replace" a reintroduced glyph would not crash, it would just
    # silently degrade to '?', so "no crash" alone is not enough evidence.
    assert "[OK]" in p.stdout, p.stdout[:1500]
    assert "[X]" in p.stdout or "Environment looks good" in p.stdout, p.stdout[-1500:]
    # 0 = all checks green, 1 = findings; both are legitimate doctor outcomes.
    assert p.returncode in (0, 1), p.stdout[-1000:]


@pytest.mark.timeout(30)
def test_doctor_source_is_pure_ascii():
    """Regression guard: every future glyph added to this file re-opens the
    cp1252 crash, so the source itself must stay ASCII."""
    with open(DOCTOR, encoding="utf-8") as fh:
        src = fh.read()
    offenders = sorted({ch for ch in src if ord(ch) > 127})
    assert not offenders, f"non-ASCII characters in doctor.py: {offenders!r}"


@pytest.mark.timeout(60)
def test_find_ngspice_honours_the_same_env_var_as_the_bridge(tmp_path, monkeypatch):
    """doctor must report the library the bridge would load, not a different
    candidate from its own glob list."""
    from bridge.toolchain_resolver import ToolchainResolver
    from bridge.ngspice_wrapper import resolve_ngspice_library

    fake = tmp_path / "libngspice-bridge-consistency.so"
    fake.write_bytes(b"")
    monkeypatch.setenv("WOSP_NGSPICE_LIB", str(fake))

    via_resolver = ToolchainResolver().find_ngspice()
    via_bridge, _tried = resolve_ngspice_library()
    assert via_bridge == str(fake), via_bridge
    assert via_resolver == via_bridge, (via_resolver, via_bridge)

    status = ToolchainResolver().get_status()
    assert status["ngspice"]["found"] is True
    assert status["ngspice"]["path"] == via_bridge


# --------------------------------------------------- check_traceability.py

# Column layout the parser understands: >= 5 cells, test refs in cells[4].
# The separator uses the '| ---' form the parser skips (a '|----' separator
# would otherwise be parsed as a bogus requirement row).
# Known limitation, out of this fix's scope: the refs regex
# `test_[A-Za-z0-9_]+::...` cannot match 'test_x.py::...' (the dot), so the
# Tests cell uses the extension-less form the regex does accept.
REQ_TABLE_5COL = (
    "# Requirements\n\n"
    "| ID | Requirement | Source | Design | Tests |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| REQ-1 | does a thing | src | impl | test_a::test_one |\n"
)

JUNIT_OK = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<testsuites><testsuite name="tests" tests="1">\n'
    '  <testcase classname="tests" name="test_a::test_one">\n'
    '    <system-out></system-out>\n'
    '    <properties><property name="req" value="REQ-1"/></properties>\n'
    '    <mark name="req" content="REQ-1"></mark>\n'
    '  </testcase>\n'
    '</testsuite></testsuites>\n'
)


def _scratch_tree(requirements_text):
    """Copy the real checker into a temp tree (scratch outside the repo)."""
    tmp = tempfile.mkdtemp(prefix="wosp-trace-")
    os.makedirs(os.path.join(tmp, "tools"))
    os.makedirs(os.path.join(tmp, "docs"))
    os.makedirs(os.path.join(tmp, "tests"))
    shutil.copy(TRACE, os.path.join(tmp, "tools", "check_traceability.py"))
    if requirements_text is not None:
        with open(os.path.join(tmp, "docs", "requirements.md"),
                  "w", encoding="utf-8", newline="\n") as fh:
            fh.write(requirements_text)
    return tmp


def _run(tree, *args):
    return subprocess.run(
        [sys.executable, os.path.join(tree, "tools", "check_traceability.py"), *args],
        cwd=tree, capture_output=True,
        encoding="utf-8", errors="replace",
    )


@pytest.mark.timeout(60)
def test_zero_requirements_parsed_is_a_failure():
    """A requirements file with no '| ID |' table parses to 0 rows: that must
    fail, not print OK and exit 0 (the false green J11 recorded)."""
    tree = _scratch_tree("# Requirements\n\nno table here\n")
    try:
        p = _run(tree)
        assert p.returncode != 0, p.stdout
        assert "parsed 0 requirements" in p.stdout, p.stdout
        assert "TRACEABILITY FAIL" in p.stdout, p.stdout
        assert "TRACEABILITY OK" not in p.stdout, p.stdout
    finally:
        shutil.rmtree(tree, ignore_errors=True)


@pytest.mark.timeout(60)
def test_missing_requirements_file_is_a_failure():
    tree = _scratch_tree(None)
    try:
        p = _run(tree)
        assert p.returncode != 0, p.stdout
        assert "cannot read" in p.stdout, p.stdout
        assert "TRACEABILITY OK" not in p.stdout, p.stdout
    finally:
        shutil.rmtree(tree, ignore_errors=True)


@pytest.mark.timeout(60)
def test_zero_marked_tests_is_a_failure():
    """Requirements exist but no junit/xml carries a @pytest.mark.req test:
    0 marked tests must fail, not pass with a shrug."""
    tree = _scratch_tree(REQ_TABLE_5COL)
    try:
        p = _run(tree)
        assert p.returncode != 0, p.stdout
        assert "0 tests carrying" in p.stdout, p.stdout
        assert "TRACEABILITY OK" not in p.stdout, p.stdout
    finally:
        shutil.rmtree(tree, ignore_errors=True)


@pytest.mark.timeout(60)
def test_a_complete_mapping_still_passes():
    """Control: with one requirement, one executed marked test and no skips
    the checker must still be able to exit 0 - the new guards fail closed,
    they do not make the tool permanently red."""
    tree = _scratch_tree(REQ_TABLE_5COL)
    try:
        junit = os.path.join(tree, "junit.xml")
        with open(junit, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(JUNIT_OK)
        p = _run(tree, junit)
        assert p.returncode == 0, p.stdout + p.stderr
        assert "TRACEABILITY OK" in p.stdout, p.stdout
    finally:
        shutil.rmtree(tree, ignore_errors=True)