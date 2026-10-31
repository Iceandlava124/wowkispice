"""test_qemu_monitor_unit.py - Unit tests for the QEMU monitor client.

Track A (no emulator binary): every test here runs against
``tests/fakes/fake_hmp_qemu.py`` -- a TEST DOUBLE that speaks QEMU's HMP
stdio protocol (banner, ``(qemu) `` prompt, echo, replies) -- launched
through the REAL ``QemuMonitor.start()``. That means these tests genuinely
exercise ``start()`` / ``_hmp()`` / ``read_gate()`` / ``Error:`` handling,
the reply timeouts and the dropped-pipe path, but they verify PROTOCOL
HANDLING ONLY: a green run says nothing about real firmware, real ADC
physics or the real emulator.

The real-emulator contract lives in ``tests/test_qemu_monitor_qemu.py``
under the ``qemu`` marker (Track B, tools/run_emulator_tests.ps1).

Client facts these tests are derived from (bridge/qemu_monitor.py):
  * start() Popen's ``[qemu, -display none, -machine esp32, -monitor stdio,
    -serial none]`` (line 87) and waits for the ``(qemu) `` prompt with
    timeout 10.0 s (line 106, prompt constant at line 128);
  * _hmp() writes ``cmd + "\\n"``, waits the prompt (10 s, line 235), strips
    ANSI, drops the echo line (``cmd in line``, line 239) and returns the
    first remaining line, ``""`` for a silent success reply;
  * set_adc1_value() raises when the reply starts with "error" (line 187);
  * read_gate() takes the first ``0x[0-9a-fA-F]+`` token of the ``xp``
    reply and tests bit 18 (lines 201-204), raising QemuMonitorError when
    no token parses;
  * a closed pipe is QemuMonitorError (``process is not running``, line 227;
    BrokenPipeError, line 231) and a non-executable binary is
    QemuMonitorError("cannot execute ...", line 97).
"""

import os
import re
import socket
import subprocess
import sys
import time

import pytest

sys.path.insert(0, ".")

from bridge.qemu_monitor import (  # noqa: E402
    FirmwareCouplingCycle,
    QemuMonitor,
    QemuMonitorError,
    cycle_adc_and_gate,
    sweep_report,
)

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
FAKE_SCRIPT = os.path.join(TESTS_DIR, "fakes", "fake_hmp_qemu.py")

# The two HMP command strings the firmware patch fixes. The fake records
# every command it receives, so tests assert on what ACTUALLY arrived on the
# wire rather than on a string the test built itself.
QOM_SET_2012 = "qom-set /machine/peripheral/sens adc1-value 2012"
XP_CMD = "xp /1wx 0x3FF44004"


def launch_fake(tmp_path, monkeypatch, mode="normal", xp_value=None,
                drop_after=None):
    """Return a launcher path that QemuMonitor.start() can Popen.

    On Windows that is a generated ``.cmd`` wrapper in tmp_path calling
    sys.executable on the fake script (Popen runs .cmd through cmd.exe, and
    start() only needs ``os.path.exists`` to hold); elsewhere a shebang
    wrapper. All QEMU argv the wrapper receives is forwarded untouched.
    The fake's behaviour is configured through FAKE_HMP_* env vars, which
    the child inherits from the test process.
    """
    record = tmp_path / "commands.log"
    monkeypatch.setenv("FAKE_HMP_MODE", mode)
    monkeypatch.setenv("FAKE_HMP_RECORD", str(record))
    if xp_value is not None:
        monkeypatch.setenv("FAKE_HMP_XP_VALUE", xp_value)
    if drop_after is not None:
        monkeypatch.setenv("FAKE_HMP_DROP_AFTER", str(drop_after))
    monkeypatch.delenv("WOSP_QEMU", raising=False)

    if os.name == "nt":
        launcher = tmp_path / "fake_qemu.cmd"
        launcher.write_text(
            '@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, FAKE_SCRIPT),
            encoding="utf-8")
    else:
        launcher = tmp_path / "fake_qemu"
        launcher.write_text(
            '#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, FAKE_SCRIPT),
            encoding="utf-8")
        os.chmod(str(launcher), 0o755)
    return str(launcher), str(record)


def recorded_commands(record_path):
    if not os.path.exists(record_path):
        return []
    with open(record_path) as fh:
        return [line.strip() for line in fh if line.strip()]


@pytest.mark.timeout(30)
def test_monitor_client_sends_qom_set_and_gets_reply(tmp_path, monkeypatch):
    """The exact HMP commands reach the wire, byte for byte.

    Replaces the old version of this test, which asserted on strings the
    test itself constructed (a regex matched against its own literal) and
    could pass without any client code running. Here the fake emulator
    RECORDS what it receives and the assertions run on that record, so a
    change to the command format in bridge/qemu_monitor.py fails the test.
    """
    launcher, record = launch_fake(tmp_path, monkeypatch)
    mon = QemuMonitor(qemu=launcher)
    mon.start()
    try:
        mon.set_adc1_value(2012)
    finally:
        mon.stop()

    assert recorded_commands(record) == [QOM_SET_2012]

    # Same public error shape as before: with no live process the calls
    # raise QemuMonitorError rather than AttributeError or a hang.
    quiet = QemuMonitor(qemu="/no/such/qemu")
    with pytest.raises(QemuMonitorError):
        quiet.set_adc1_value(2012)
    with pytest.raises(QemuMonitorError):
        quiet.read_gate()


@pytest.mark.timeout(30)
def test_set_adc1_value_accepts_int_coercion(tmp_path, monkeypatch):
    """A numeric string is accepted because set_adc1_value does int(value):
    the wire still carries a bare decimal integer."""
    launcher, record = launch_fake(tmp_path, monkeypatch)
    mon = QemuMonitor(qemu=launcher)
    mon.start()
    try:
        mon.set_adc1_value("2012")
    finally:
        mon.stop()
    assert recorded_commands(record) == [QOM_SET_2012]


@pytest.mark.timeout(30)
@pytest.mark.parametrize("xp_value", ["0x00040000", "0x00040004"])
def test_read_gate_is_true_when_bit_18_set(tmp_path, monkeypatch, xp_value):
    """xp reply with bit 18 set -> True (gate ON)."""
    launcher, _record = launch_fake(tmp_path, monkeypatch, xp_value=xp_value)
    mon = QemuMonitor(qemu=launcher)
    mon.start()
    try:
        assert mon.read_gate() is True
        assert recorded_commands(_record) == [XP_CMD]
    finally:
        mon.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("xp_value", ["0x00000000", "0x00000004"])
def test_read_gate_is_false_when_bit_18_clear(tmp_path, monkeypatch, xp_value):
    """xp reply without bit 18 -> False (gate OFF)."""
    launcher, _record = launch_fake(tmp_path, monkeypatch, xp_value=xp_value)
    mon = QemuMonitor(qemu=launcher)
    mon.start()
    try:
        assert mon.read_gate() is False
        assert recorded_commands(_record) == [XP_CMD]
    finally:
        mon.stop()


@pytest.mark.timeout(30)
def test_error_reply_raises_qemu_monitor_error_with_reply_text(
        tmp_path, monkeypatch):
    """An HMP ``Error:`` reply is raised, carrying the reply text.

    This is the wrong-build case: a QEMU without the SENS adc1-value
    property must surface as a failure, not as a silent success.
    """
    launcher, record = launch_fake(tmp_path, monkeypatch, mode="error")
    mon = QemuMonitor(qemu=launcher)
    mon.start()
    try:
        with pytest.raises(QemuMonitorError) as excinfo:
            mon.set_adc1_value(2012)
        assert "Error:" in str(excinfo.value)
        assert "adc1-value" in str(excinfo.value)
        # The command really was sent before the rejection came back.
        assert recorded_commands(record) == [QOM_SET_2012]
    finally:
        mon.stop()


@pytest.mark.timeout(30)
def test_dropped_pipe_raises_qemu_monitor_error(tmp_path, monkeypatch):
    """A QEMU that exits mid-session is a clean QemuMonitorError.

    Not a hang (the poll()/pipe checks fire first) and not an AttributeError
    off a dead process handle.
    """
    launcher, _record = launch_fake(tmp_path, monkeypatch, mode="drop",
                                    drop_after=0)
    mon = QemuMonitor(qemu=launcher)
    mon.start()   # banner+prompt are written before the fake exits
    try:
        with pytest.raises(QemuMonitorError):
            mon.set_adc1_value(2012)
    finally:
        mon.stop()


@pytest.mark.timeout(30)
def test_silent_emulator_times_out_within_documented_timeout(
        tmp_path, monkeypatch):
    """A wedged emulator that never speaks fails start() in ~10 s.

    The documented prompt timeout is 10.0 s (start() and _hmp()); this test
    proves the timeout exists by timing it, so removing it turns into a
    pytest-timeout failure instead of an infinite hang.
    """
    launcher, _record = launch_fake(tmp_path, monkeypatch, mode="silent")
    mon = QemuMonitor(qemu=launcher)
    start = time.monotonic()
    with pytest.raises(QemuMonitorError, match="no QEMU monitor prompt"):
        mon.start()
    elapsed = time.monotonic() - start
    assert elapsed < 13.0, "prompt wait exceeded the documented 10 s: %.1f s" % elapsed
    mon.stop()


@pytest.mark.timeout(30)
def test_garbage_xp_output_raises_qemu_monitor_error(tmp_path, monkeypatch):
    """Unparsable ``xp`` output is a QemuMonitorError, not a wrong answer."""
    launcher, _record = launch_fake(tmp_path, monkeypatch, mode="garbage")
    mon = QemuMonitor(qemu=launcher)
    mon.start()
    try:
        with pytest.raises(QemuMonitorError, match="cannot parse gate readback"):
            mon.read_gate()
    finally:
        mon.stop()


def test_non_executable_binary_raises_cannot_execute(tmp_path, monkeypatch):
    """A file that exists but cannot run (wrong architecture / not an exe)
    fails start() with QemuMonitorError naming it, not with a raw OSError."""
    monkeypatch.delenv("WOSP_QEMU", raising=False)
    bogus = tmp_path / "qemu-system-xtensa.exe"
    bogus.write_bytes(b"this is not an executable image\n" * 4)
    mon = QemuMonitor(qemu=str(bogus))
    with pytest.raises(QemuMonitorError, match="cannot execute"):
        mon.start()
    mon.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("mode", ["error", "drop", "garbage"])
def test_cycle_adc_and_gate_returns_ok_false_for_each_failure(
        tmp_path, monkeypatch, mode):
    """Every protocol failure comes back as ok=False with a readable message.

    cycle_adc_and_gate() must never raise -- its docstring promises "every
    failure shape is returned as a clean, non-raising FirmwareCouplingCycle".
    """
    drop = 0 if mode == "drop" else None
    launcher, _record = launch_fake(tmp_path, monkeypatch, mode=mode,
                                    drop_after=drop)
    mon = QemuMonitor(qemu=launcher)
    mon.start()
    cycle = cycle_adc_and_gate(qmp=mon, adc_value=2012)
    assert isinstance(cycle, FirmwareCouplingCycle)
    assert cycle.ok is False
    assert cycle.gate_high is None
    assert cycle.message
    mon.stop()


@pytest.mark.timeout(60)
def test_cycle_adc_and_gate_clean_failure_for_a_monitor_never_started(
        tmp_path, monkeypatch):
    """A monitor handle that was never started also yields ok=False."""
    launcher, _record = launch_fake(tmp_path, monkeypatch)
    mon = QemuMonitor(qemu=launcher)          # start() deliberately not called
    cycle = cycle_adc_and_gate(qmp=mon, adc_value=2012)
    assert isinstance(cycle, FirmwareCouplingCycle)
    assert cycle.ok is False
    assert cycle.message
    mon.stop()


@pytest.mark.timeout(60)
def test_sweep_report_one_row_per_value_over_a_single_monitor(
        tmp_path, monkeypatch):
    """sweep_report() must return one OK row per value over a running monitor
    that is started ONCE and left RUNNING afterwards.

    The monitor must NEVER be stopped inside a cycle: the caller (the
    automatic ngspice<->QEMU bridge) drives the life cycle.
    """
    import bridge.qemu_monitor as qm

    launcher, record = launch_fake(tmp_path, monkeypatch)
    launches = []
    real_popen = qm.subprocess.Popen

    def spy(*args, **kwargs):
        launches.append(args)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(qm.subprocess, "Popen", spy)

    mon = QemuMonitor(qemu=launcher)
    mon.start()
    try:
        before = mon._proc.poll()
        assert before is None, "monitor must be running before the sweep"
        rows = sweep_report(mon, [1900, 2012, 3456])
    finally:
        pass

    assert len(launches) == 1, "sweep restarted the emulator: %d launches" % len(launches)
    assert len(rows) == 3, "expected one row per value, got %d" % len(rows)
    for row in rows:
        assert isinstance(row, FirmwareCouplingCycle), row
        assert row.ok is True, row.message
        assert isinstance(row.gate_high, bool), row.message
    # every requested value reached the running monitor, in order
    # Filter for only qom-set ADC value commands (ignore xp debug output etc)
    qom_sets = [c for c in recorded_commands(record) if c.startswith('qom-set')]
    assert qom_sets == [
        "qom-set /machine/peripheral/sens adc1-value 1900",
        "qom-set /machine/peripheral/sens adc1-value 2012",
        "qom-set /machine/peripheral/sens adc1-value 3456",
    ], f"expected three qom-set ADC values, got: {qom_sets}"
    # the monitor is still alive after the sweep (only the caller stops it)
    assert mon._proc.poll() is None, "cycle_adc_and_gate() stopped the monitor"

    # Assertion (b): one cycle_adc_and_gate call with default stop=False
    # leaves the monitor running
    mon2 = QemuMonitor(qemu=launcher)
    mon2.start()
    before2 = mon2._proc.poll()
    assert before2 is None, "monitor must be running before cycle"
    cycle = cycle_adc_and_gate(qmp=mon2, adc_value=2012)  # stop=False default
    assert cycle.ok is True, cycle.message
    # Monitor should still be running after a single cycle with stop=False
    assert mon2._proc.poll() is None, "cycle_adc_and_gate() with stop=False stopped the monitor"
    mon2.stop()

    # Assertion (c): the same call with stop=True leaves it stopped
    mon3 = QemuMonitor(qemu=launcher)
    mon3.start()
    before3 = mon3._proc.poll()
    assert before3 is None, "monitor must be running before cycle"
    cycle = cycle_adc_and_gate(qmp=mon3, adc_value=2012, stop=True)  # stop=True
    assert cycle.ok is True, cycle.message
    # Monitor should be stopped after cycle with stop=True
    assert mon3._proc is None, "cycle_adc_and_gate() with stop=True did not stop the monitor"
    # No need to call mon3.stop() - it was already stopped by cycle with stop=True

def test_cycle_adc_and_gate_error_shapes():
    """Every failure shape is returned as a clean, non-raising cycle.

    Environment-gate shapes only (no env, bad path, host:port string that
    never dials a socket, handle that dies mid-cycle). Protocol behaviour
    is covered by the fake-emulator tests above; the real-QEMU contract is
    in test_qemu_monitor_qemu.py.
    """
    from bridge.qemu_monitor import cycle_adc_and_gate, FirmwareCouplingCycle

    # No QEMU env -> clean failure, no exception.
    cycle = cycle_adc_and_gate()
    assert isinstance(cycle, FirmwareCouplingCycle)
    assert cycle.ok is False
    assert cycle.gate_high is None

    # WOSP_QEMU points at a binary that cannot attach -> clean failure.
    cycle = cycle_adc_and_gate(qemu="/no/such/qemu")
    assert cycle.ok is False
    assert cycle.message

    # A host:port string is not a valid QEMU path: it must fail the
    # environment gate as a clean, non-raising cycle -- not attempt a
    # connection, not hang, and not raise.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(5.0)
    port = srv.getsockname()[1]
    try:
        cycle = cycle_adc_and_gate(qemu="127.0.0.1:%d" % port, adc_value=2012)
        assert isinstance(cycle, FirmwareCouplingCycle)
        assert cycle.ok is False
        assert cycle.gate_high is None
        assert cycle.message
    finally:
        try:
            srv.close()
        except OSError:
            pass

    # A live monitor handle that dies mid-cycle: set_adc1_value raises -> the
    # exception must come back as ok=False with the reason, never escape.
    class DyingMonitor:
        def set_adc1_value(self, value):
            raise QemuMonitorError("monitor died mid-cycle")

        def read_gate(self):
            raise AssertionError("read_gate must not run after set failure")

        def stop(self):
            self.stopped = True

    monitor = DyingMonitor()
    cycle = cycle_adc_and_gate(qmp=monitor, adc_value=2012)
    assert isinstance(cycle, FirmwareCouplingCycle)
    assert cycle.ok is False
    assert cycle.gate_high is None
    assert cycle.message == "monitor died mid-cycle"
    # Note: cycle_adc_and_gate does not stop the monitor (caller owns lifecycle)
    # monitor.stopped may be False; caller must call monitor.stop() explicitly


# --------------------------------------------------------------------------
# Process-tree teardown (Windows): stop() must not leave the fake behind
# --------------------------------------------------------------------------

def _fake_pids():
    """PIDs of live processes whose command line mentions the fake.

    The command line, not the image name: pytest itself is python.exe, so
    only a CIM query can tell the fake's children from everything else.
    Read-only, roughly a second per call.

    Two traps both hit while writing this test:
      * the pattern must be ASSEMBLED FROM PARTS and the query must drop its
        own ``$PID`` -- a literal ``fake_hmp_qemu`` in this command line made
        the query match itself, so every call returned a phantom orphan and
        the test failed on its own probe (PIDs 22836, 32516: one per call,
        different every time, gone by the time the details were fetched);
      * ``.ProcessId`` of a zero-match query prints nothing, so an empty
        result is a valid, readable "no fakes".
    """
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "$p = '*' + 'fake_hmp' + '_qemu*'; "
         "(Get-CimInstance Win32_Process | Where-Object "
         "{ $_.ProcessId -ne $PID -and $_.CommandLine -like $p }).ProcessId"],
        capture_output=True, text=True, timeout=40, errors="replace")
    pids = set()
    for token in re.split(r"[\s,]+", (out.stdout or "").strip()):
        if token.isdigit():
            pids.add(int(token))
    return pids


def _fake_pid_details(pids):
    """Command lines + parents for the survivors, for a self-explaining failure."""
    if not pids:
        return ""
    ids = ",".join(str(p) for p in sorted(pids))
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in @(%s) } | "
         "ForEach-Object { '{0} ppid={1} {2}' -f $_.ProcessId, $_.ParentProcessId, "
         "($_.CommandLine -replace '\\s+', ' ') }" % ids],
        capture_output=True, text=True, timeout=40, errors="replace")
    return " | ".join(line.strip()[:180] for line in (out.stdout or "").splitlines()
                      if line.strip())


@pytest.mark.timeout(90)
@pytest.mark.skipif(os.name != "nt",
                    reason="the leak is Windows-specific: Popen(.cmd) makes "
                           "cmd.exe the direct child, so terminate() spares "
                           "the python that actually runs the fake")
def test_stop_tears_down_the_whole_process_tree(tmp_path, monkeypatch):
    """stop() must take the fake's python processes with it, not just cmd.exe.

    Measured before the fix: every full suite run left a pair of orphaned
    ``fake_hmp_qemu`` pythons behind with a dead parent (read-only listing
    job ORPHAN-LIST: ages 33/38/86 min, parent_alive=False, while the
    machine sat under the owner's 2 GB RAM floor).

    The test snapshots which fake PIDs exist BEFORE this test starts, so an
    orphan leaked by an earlier test can neither fail it nor mask one: the
    assertion is only that THIS monitor's processes are gone afterwards.
    """
    launcher, record = launch_fake(tmp_path, monkeypatch)
    # The peer must not disappear on its own when the wrapper's pipe closes:
    # that EOF-driven exit is exactly what masked the leak (a run with the
    # PRE-FIX stop() passed until this was set). Only an explicit kill of
    # the whole tree may end it.
    monkeypatch.setenv("FAKE_HMP_STAY_ALIVE", "1")
    before = _fake_pids()

    mon = QemuMonitor(qemu=launcher)
    mon.start()
    try:
        mon.set_adc1_value(2012)
        started = _fake_pids() - before
        assert started, "the fake never started; this test would prove nothing"
    finally:
        mon.stop()

    leaked = set()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        leaked = _fake_pids() - before
        if not leaked:
            break
        time.sleep(0.2)
    assert not leaked, ("stop() left orphaned fake qemu processes: %s"
                        % (_fake_pid_details(leaked) or sorted(leaked)))
    # The teardown must not have broken the protocol path either.
    assert recorded_commands(record) == [QOM_SET_2012]
