"""setup.ps1 must refuse bytes it did not actually download.

Measured before this job (log entries #276 and #278):

  #278 V1/V3 - setup.ps1's own fetch line (default User-Agent, default
      redirect limit) returned HTTP 200 with an HTML page instead of the
      archive: ``error=none``, 132747 bytes, ``title=[Download
      ngspice-47_dll_64.7z (ngspice)]``, ``match_pinned=False``. Two attempts,
      two different HTML bodies. The old code only compared the SHA-256 when
      an expected hash was supplied and, even then, merely *warned*
      ("Continuing - the bind check in step 4 is the real test"), so the HTML
      flowed on into py7zr extraction.
  #276 - ``-MaximumRedirection 8 -UserAgent 'WISP-R1-probe/1.0'`` returned the
      real file: 4385088 bytes, sha256 equal to the pin, magic
      ``377abcaf271c0004`` (the 7z signature 37 7A BC AF 27 1C).

The tests below therefore exercise the validation function exactly as it
ships: the function body is extracted from setup.ps1 itself and run in a
child PowerShell, so a regression in the script text cannot hide behind a
reimplementation in the test.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP = os.path.join(REPO, "setup.ps1")

# The 7z signature, byte for byte, as measured from the real ngspice archive
# in log entry #276 (magic_hex=377abcaf271c0004).
SEVEN_ZIP_MAGIC = bytes((0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C))

# A body shaped like the one SourceForge actually served in #278.
HTML_BODY = (
    "<!doctype html>\n<html class=\"no-js\" lang=\"en\">\n<head>\n"
    "  <meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\" />\n"
    "  <title>Download ngspice-47_dll_64.7z (ngspice)</title>\n"
    "</head>\n<body>The file you requested is on a mirror.</body>\n</html>\n"
).encode("utf-8")

WIN_ONLY = pytest.mark.skipif(
    sys.platform != "win32",
    reason="setup.ps1 and powershell.exe are Windows-only")


def _validation_source():
    """The shipped validation function, extracted from setup.ps1 itself."""
    with open(SETUP, encoding="utf-8") as fh:
        src = fh.read()
    match = re.search(r"function\s+Test-NgspiceArchive\s*\{.*?\n\}", src, re.S)
    assert match, (
        "function Test-NgspiceArchive not found in setup.ps1 - the download "
        "path no longer has a validation step to test")
    magic = re.search(r"\$SevenZipMagic\s*=\s*@\([^)]*\)", src)
    assert magic, "the 7z signature constant is missing from setup.ps1"
    # The function reads $SevenZipMagic from the script scope, so the driver
    # has to define it from setup.ps1's own literal, not from the test.
    return magic.group(0) + "\r\n" + match.group(0)


def _run_validation(path, expect_sha=""):
    """Run the extracted function against one file; return (rc, output)."""
    body = _validation_source()
    script = (
        "$ErrorActionPreference = 'Stop'\r\n"
        + body + "\r\n"
        "try {\r\n"
        "  Test-NgspiceArchive -Path $args[0] -Name 'ngspice-test.7z' "
        "-ExpectSha $args[1]\r\n"
        "  exit 0\r\n"
        "}\r\n"
        "catch {\r\n"
        "  [Console]::Error.WriteLine($_.Exception.Message)\r\n"
        "  exit 7\r\n"
        "}\r\n"
    )
    handle, script_path = tempfile.mkstemp(suffix=".ps1")
    os.close(handle)
    with open(script_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(script)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script_path, str(path), expect_sha],
            capture_output=True, text=True, errors="replace", timeout=120)
        return proc.returncode, (proc.stdout + proc.stderr)
    finally:
        os.remove(script_path)


@WIN_ONLY
def test_html_body_is_rejected_even_without_a_pinned_checksum(tmp_path):
    """The #278 failure: SourceForge's HTML page, no expected hash (the
    console-archive call passes an empty pin), must not be accepted."""
    bad = tmp_path / "ngspice-47_64.7z"
    bad.write_bytes(HTML_BODY)
    rc, out = _run_validation(str(bad), "")
    assert rc == 7, out
    assert "not a 7z archive" in out, out
    # The bad bytes must not survive to be picked up as a cache hit.
    assert not bad.exists(), "rejected file was left on disk for the cache"


@WIN_ONLY
def test_short_file_is_rejected(tmp_path):
    """A truncated/partial write (or an empty error page) must not pass."""
    bad = tmp_path / "ngspice-47_dll_64.7z"
    bad.write_bytes(SEVEN_ZIP_MAGIC[:3])
    rc, out = _run_validation(str(bad), "")
    assert rc == 7, out
    assert not bad.exists(), "rejected file was left on disk for the cache"


@WIN_ONLY
def test_checksum_mismatch_throws_instead_of_warning(tmp_path):
    """Owner-approved fail-fast: a hash mismatch used to be a yellow warning
    that let the archive through; it must now abort with a non-zero exit."""
    good = tmp_path / "ngspice-47_dll_64.7z"
    good.write_bytes(SEVEN_ZIP_MAGIC + b"not-the-real-archive")
    wrong = hashlib.sha256(b"some other bytes").hexdigest()
    rc, out = _run_validation(str(good), wrong)
    assert rc == 7, out
    assert "Checksum mismatch" in out, out
    assert not good.exists(), "mismatched file was left on disk for the cache"


@WIN_ONLY
def test_real_archive_with_matching_checksum_is_accepted(tmp_path):
    """The happy path must stay open: correct magic plus correct pin passes
    and leaves the file in place for extraction."""
    ok = tmp_path / "ngspice-47_dll_64.7z"
    payload = SEVEN_ZIP_MAGIC + b"payload"
    ok.write_bytes(payload)
    pin = hashlib.sha256(payload).hexdigest()
    rc, out = _run_validation(str(ok), pin)
    assert rc == 0, out
    assert ok.exists(), "a valid archive must not be deleted"


def _archive_source():
    """Both shipped functions that produce the value setup.ps1 extracts with,
    taken from setup.ps1 itself (same rule as _validation_source)."""
    with open(SETUP, encoding="utf-8") as fh:
        src = fh.read()
    magic = re.search(r"\$SevenZipMagic\s*=\s*@\([^)]*\)", src)
    assert magic, "the 7z signature constant is missing from setup.ps1"
    parts = [magic.group(0)]
    for name in ("Test-NgspiceArchive", "Get-NgspiceArchive"):
        match = re.search(r"function\s+%s\s*\{.*?\n\}" % re.escape(name),
                          src, re.S)
        assert match, f"function {name} not found in setup.ps1"
        parts.append(match.group(0))
    return "\r\n".join(parts)


def _run_get_archive(root, expect_sha=""):
    """Call the shipped Get-NgspiceArchive and report the full pipeline
    output as COUNT= and VALUE= lines."""
    script = (
        "$ErrorActionPreference = 'Stop'\r\n"
        "function Write-Step($m) {}\r\n"
        "function Write-Ok($m) {}\r\n"
        "function Write-Warn2($m) {}\r\n"
        "$Root = $args[0]\r\n"
        + _archive_source() + "\r\n"
        "$out = @(Get-NgspiceArchive -Name 'ngspice-7z.7z' "
        "-ExpectSha $args[1])\r\n"
        "Write-Output ('COUNT=' + $out.Count)\r\n"
        "foreach ($item in $out) { Write-Output ('VALUE=' + $item) }\r\n"
        "exit 0\r\n"
    )
    handle, script_path = tempfile.mkstemp(suffix=".ps1")
    os.close(handle)
    with open(script_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(script)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script_path, str(root), expect_sha],
            capture_output=True, text=True, errors="replace", timeout=120)
        return proc.returncode, (proc.stdout + proc.stderr)
    finally:
        os.remove(script_path)


def _cached_archive(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    payload = SEVEN_ZIP_MAGIC + b"cached-archive-bytes"
    (tools / "ngspice-7z.7z").write_bytes(payload)
    return payload


@WIN_ONLY
def test_get_ngspice_archive_returns_exactly_one_path_without_a_pin(tmp_path):
    """R1 run 1 (job R1-VERIFY-RUN1C): the console-archive call passes an
    empty pin, so Get-NgspiceArchive takes the no-pin cache branch, calls the
    validator, then returns the path. The validator's `return $true` used to
    leak into the same pipeline, so the caller received TWO values and setup
    handed the string 'True' to py7zr:

        FileNotFoundError: [Errno 2] No such file or directory: 'True'

    One call must yield exactly one output item: the archive path."""
    _cached_archive(tmp_path)
    rc, out = _run_get_archive(str(tmp_path), "")
    assert rc == 0, out
    counts = [ln for ln in out.splitlines() if ln.startswith("COUNT=")]
    values = [ln[len("VALUE="):] for ln in out.splitlines()
              if ln.startswith("VALUE=")]
    assert counts == ["COUNT=1"], out
    assert len(values) == 1 and values[0].endswith("ngspice-7z.7z"), out
    assert "True" not in values, (
        "a boolean leaked into the return value: %r" % (values,))


@WIN_ONLY
def test_get_ngspice_archive_returns_exactly_one_path_with_a_pin(tmp_path):
    """Control: the checksum-verified cache hit returns one path today and
    must keep doing so - the fix must not change this branch's shape."""
    payload = _cached_archive(tmp_path)
    pin = hashlib.sha256(payload).hexdigest()
    rc, out = _run_get_archive(str(tmp_path), pin)
    assert rc == 0, out
    counts = [ln for ln in out.splitlines() if ln.startswith("COUNT=")]
    values = [ln[len("VALUE="):] for ln in out.splitlines()
              if ln.startswith("VALUE=")]
    assert counts == ["COUNT=1"], out
    assert len(values) == 1 and values[0].endswith("ngspice-7z.7z"), out


@WIN_ONLY
def test_every_validator_call_discards_its_boolean():
    """Source-level guard for the download branch, which no offline test can
    reach: every setup.ps1 call to Test-NgspiceArchive must discard the
    validator's `return $true`, or it joins Get-NgspiceArchive's own output
    and the caller receives two items (measured in R1 run 1: py7zr was handed
    the string 'True')."""
    with open(SETUP, encoding="utf-8") as fh:
        src = fh.read()
    calls = re.findall(r"^.*Test-NgspiceArchive -Path.*$", src, re.M)
    assert calls, "setup.ps1 no longer calls Test-NgspiceArchive"
    leaks = [line for line in calls
             if "$null = Test-NgspiceArchive" not in line]
    assert not leaks, "validator output is not discarded: %r" % leaks


@WIN_ONLY
def test_download_call_uses_the_profile_that_measured_green():
    """setup.ps1 must keep the fetch settings that worked in #276 and must not
    fall back to the default User-Agent / redirect limit that returned HTML in
    #278. This is a source-level guard, same idea as the ASCII guard for
    doctor.py: the profile is only pinned by the script text."""
    with open(SETUP, encoding="utf-8") as fh:
        src = fh.read()
    fetch = re.search(r"Invoke-WebRequest[^\r\n]*-OutFile[^\r\n]*", src)
    assert fetch, "setup.ps1 no longer fetches with Invoke-WebRequest"
    line = fetch.group(0)
    assert "-MaximumRedirection" in line, line
    assert "-UserAgent" in line, line
    assert "-UseBasicParsing" in line, line
