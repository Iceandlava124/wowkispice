"""qemu_monitor.py - M0 automation: QMP connect, programmatic qom-set ADC
injection, HMP xp gate readback, one-cycle coupling, sweep.

This is the real driver behind the long-settled ``bridge.firmware_runner`` name.
It is kept as a separate module so the app layer can import it without pulling
in the QEMU process management of ``bridge/qemu_orchestrator.py``.

Run directly::

    python -m bridge.qemu_monitor --qemu /path/to/qemu-system-xtensa
"""

import os
import re
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class QemuMonitorError(RuntimeError):
    """Raised when the QEMU monitor cannot be reached or used."""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class QemuMonitor:
    """Attach to a running QEMU ESP32 and drive it programmatically.

    The monitor is a thin wrapper around QEMU's HMP/QMP surface that the app
    layer uses when it wants to push an ADC sample into the emulated chip and
    read the resulting gate state back. It deliberately does not start or stop
    the QEMU process; that belongs to ``bridge/qemu_orchestrator.py``.
    """

    def __init__(self, qemu, machine="esp32", port=None):
        self.qemu = qemu
        self.machine = machine
        self.port = port or _free_port()
        self._proc = None
        # Monitor byte buffer filled by the reader thread; _hmp() consumes it
        # up to the HMP prompt. Both are (re)initialised in start().
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._cursor = 0
        self._reader_thread = None

    # ---------------------------------------------------------------
    # Environment gate
    # ---------------------------------------------------------------

    @classmethod
    def configured(cls):
        """Return True when a QEMU binary is reachable on this machine."""
        qemu = os.environ.get("WOSP_QEMU")
        if not qemu:
            return False
        return os.path.exists(qemu)

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    def start(self):
        """Spawn QEMU with its HMP monitor attached to stdio.

        The monitor MUST be requested explicitly (``-monitor stdio``): with
        ``-display none`` and no monitor argument QEMU attaches the HMP
        console to a virtual console that no host pipe can reach, so every
        later HMP command would block forever.
        """
        if not os.path.exists(self.qemu):
            raise QemuMonitorError(
                "qemu-system-xtensa not found at %r. Set WOSP_QEMU." % self.qemu
            )
        try:
            self._proc = subprocess.Popen(
                [self.qemu, "-display", "none", "-machine", self.machine,
                 "-monitor", "stdio", "-serial", "none"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            # Typical case: a Linux qemu-system-xtensa pointed at from
            # Windows (it must then run under WSL -- see SETUP.md Part F).
            raise QemuMonitorError(
                "cannot execute %r: %s" % (self.qemu, exc)
            ) from exc
        self._buf = bytearray()
        self._cursor = 0
        self._lock = threading.Lock()
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        # Consume the banner and stop at the first "(qemu) " prompt so every
        # later _hmp() call reads only its own reply.
        self._wait_prompt(timeout=10.0)
        return self

    def _reader_loop(self):
        """Pump monitor bytes into the buffer until QEMU closes the pipe.

        A thread (not select) because this must work on POSIX and Windows
        pipes alike, and HMP emits data in bursts: the prompt has no trailing
        newline, so a line-oriented read would block on it forever.
        """
        try:
            while True:
                chunk = self._proc.stdout.read(1)
                if not chunk:
                    break
                with self._lock:
                    self._buf.extend(chunk)
        except (ValueError, OSError):
            # Pipe closed under us (QEMU exited); the poll() checks in _hmp
            # turn that into a normal QemuMonitorError.
            pass

    _PROMPT = b"(qemu) "

    def _wait_prompt(self, timeout=10.0):
        """Return the raw bytes between now and the next HMP prompt.

        Raises QemuMonitorError when the prompt never arrives, so a wedged
        monitor is a clean failure instead of a hung test.
        """
        deadline = time.monotonic() + timeout
        cursor = self._cursor
        while True:
            with self._lock:
                idx = self._buf.find(self._PROMPT, cursor)
                if idx != -1:
                    reply = bytes(self._buf[self._cursor:idx])
                    self._cursor = idx + len(self._PROMPT)
                    return reply
                cursor = len(self._buf)
            if time.monotonic() >= deadline:
                raise QemuMonitorError(
                    "no QEMU monitor prompt within %.0fs" % timeout
                )
            time.sleep(0.01)

    def stop(self):
        """Terminate the QEMU process, if it is running."""
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    # ---------------------------------------------------------------
    # ADC injection / gate readback
    # ---------------------------------------------------------------

    def set_adc1_value(self, value):
        """Write ``value`` into /machine/peripheral/sens adc1-value.

        The QOM path is the fixed one the firmware patch exposes, so the call
        succeeds identically across boots and across runs. A patched-in
        property that is missing (wrong QEMU build) comes back as an HMP
        ``Error:`` reply; that is raised, not swallowed, because it means the
        emulator under test does not implement the contract.
        """
        cmd = "qom-set /machine/peripheral/sens adc1-value %d" % int(value)
        reply = self._hmp(cmd)
        if reply.lower().startswith("error"):
            raise QemuMonitorError("monitor rejected %r: %s" % (cmd, reply))
        return reply

    def read_gate(self):
        """Read the latched GPIO18 output state out of the guest.

        Stable QOM path with no index arithmetic, so it always resolves even
        when the device is attached at a different slot on a fresh boot.
        """
        cmd = "xp /1wx 0x3FF44004"
        raw = self._hmp(cmd)
        # HMP `xp` prints "<addr>: <value>", e.g.
        # "000000003ff44004: 0x00000000" -- grab the 0x-prefixed value.
        match = re.search(r"0x[0-9a-fA-F]+", raw)
        token = match.group(0) if match else raw
        try:
            return (int(token, 16) & (1 << 18)) != 0
        except ValueError:
            raise QemuMonitorError("cannot parse gate readback %r" % raw)

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    # ANSI escape sequences QEMU's readline emits while echoing typed
    # characters one at a time (erase-to-end-of-line, cursor-left, ...).
    _ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[A-Za-z]")

    def _hmp(self, cmd):
        """Send an HMP command and return its first real reply line.

        QEMU's readline echoes every typed character back with ANSI erase
        sequences, then prints the reply (if any) and a new "(qemu) " prompt
        with no trailing newline. So: write the command, wait for the prompt,
        strip the ANSI noise, drop the echo (it contains the command text),
        and return the first remaining line -- "" when the command's success
        reply is silence, as qom-set's is.
        """
        if self._proc is None or self._proc.poll() is not None:
            raise QemuMonitorError("QEMU process is not running")
        try:
            self._proc.stdin.write((cmd + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise QemuMonitorError(
                "cannot send %r to QEMU monitor: %s" % (cmd, exc)
            ) from exc
        raw = self._wait_prompt(timeout=10.0)
        text = self._ANSI_RE.sub("", raw.decode("utf-8", errors="replace"))
        for line in text.splitlines():
            line = line.strip()
            if not line or cmd in line or line == "(qemu)":
                continue  # echo of the typed command, or an empty separator
            return line
        return ""


def cycle_adc_and_gate(qmp=None, adc_value=2012, qemu=None, stop=False):
    """One read-modify-write cycle: inject an ADC sample, read the gate back.

    ``qmp`` is the ``QemuMonitor`` handle. When it is None, the environment
    gate decides what the result says instead of raising, and no QEMU is
    started. Every failure shape is returned as a clean, non-raising
    ``FirmwareCouplingCycle`` so callers and tests can enumerate them.

    ``stop`` selects who owns the QEMU life-cycle:
      * False (default) - the caller owns it. A failed second cycle must not
        kill the monitor, and sweep_report() over one running handle is the
        supported shape. Only ``QemuMonitorError`` (the protocol surface a
        handle exposes) is caught and reported as ok=False; other bugs
        escape so they cannot be hidden.
      * True          - the cycle itself owns the process (tests, one-shot
        helpers). The handle is stopped in a finally block, so a failure just
        below never leaves the monitor dead or running away.
    """
    if qmp is None:
        if qemu is None:
            qemu = os.environ.get("WOSP_QEMU")
        if qemu is None or not os.path.exists(qemu):
            return FirmwareCouplingCycle(
                ok=False, gate_high=None,
                message="WOSP_QEMU not configured",
            )
        # qmp is None but WOSP_QEMU points at a real binary. The contract is
        # that nothing is started here: the harness is signalling it cannot
        # attach a monitor to a guest it has not launched. Return the clean
        # failure instead of spawning QEMU.
        return FirmwareCouplingCycle(
            ok=False, gate_high=None,
            message="no qmp handle",
        )
    try:
        qmp.set_adc1_value(adc_value)
        gate = qmp.read_gate()
        return FirmwareCouplingCycle(
            ok=True, gate_high=gate,
            message="set adc1-value=%d, gate=%s" % (adc_value, gate),
        )
    except QemuMonitorError as exc:
        # The protocol surface a handle exposes failed (process gone, pipe
        # closed, unparsable readback). Return the clean, non-raising row so
        # callers can enumerate the failure instead of watching the run die.
        return FirmwareCouplingCycle(ok=False, gate_high=None, message=str(exc))
    finally:
        if stop:
            qmp.stop()


@dataclass
class FirmwareCouplingCycle:
    ok: bool
    gate_high: Optional[bool] = None
    message: str = ""


def sweep_report(qmp, adc_values: List[int]) -> List[FirmwareCouplingCycle]:
    """Run one cycle per value and report the gate transitions.

    A sweep never raises: every bad entry is reported as a clean failure row.
    """
    rows = []
    for value in adc_values:
        try:
            row = cycle_adc_and_gate(qmp=qmp, adc_value=value)
        except Exception as exc:  # noqa: BLE001
            rows.append(FirmwareCouplingCycle(ok=False, message=str(exc)))
        else:
            rows.append(row)
    return rows


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    qemu = os.environ.get("WOSP_QEMU")
    if "--qemu" in args:
        qemu = args[args.index("--qemu") + 1]
    if not qemu:
        print(__doc__)
        print("ERROR: pass --qemu /path/to/qemu-system-xtensa or set WOSP_QEMU")
        return 2
    with QemuMonitor(qemu) as mon:
        print(mon.set_adc1_value(2012))
        print("gate:", mon.read_gate())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
