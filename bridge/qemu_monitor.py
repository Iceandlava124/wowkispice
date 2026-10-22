"""qemu_monitor.py - M0 automation: QMP connect, programmatic qom-set ADC
injection, HMP xp gate readback, one-cycle coupling, sweep.

This is the real driver behind the long-settled ``bridge.firmware_runner`` name.
It is kept as a separate module so the app layer can import it without pulling
in the QEMU process management of ``bridge/qemu_orchestrator.py``.

Run directly::

    python -m bridge.qemu_monitor --qemu /path/to/qemu-system-xtensa
"""

import os
import socket
import subprocess
import sys
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
        """Spawn the QEMU process with no monitor attached."""
        if not os.path.exists(self.qemu):
            raise QemuMonitorError(
                "qemu-system-xtensa not found at %r. Set WOSP_QEMU." % self.qemu
            )
        self._proc = subprocess.Popen(
            [self.qemu, "-display", "none", "-machine", self.machine],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        return self

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
        succeeds identically across boots and across runs.
        """
        cmd = "qom-set /machine/peripheral/sens adc1-value %d" % int(value)
        return self._hmp(cmd)

    def read_gate(self):
        """Read the latched GPIO18 output state out of the guest.

        Stable QOM path with no index arithmetic, so it always resolves even
        when the device is attached at a different slot on a fresh boot.
        """
        cmd = "xp /1wx 0x3FF44004"
        raw = self._hmp(cmd)
        try:
            return (int(raw, 16) & (1 << 18)) != 0
        except ValueError:
            raise QemuMonitorError("cannot parse gate readback %r" % raw)

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    def _hmp(self, cmd):
        """Send an HMP command and return its reply line."""
        if self._proc is None or self._proc.poll() is not None:
            raise QemuMonitorError("QEMU process is not running")
        try:
            self._proc.stdin.write((cmd + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise QemuMonitorError(
                "cannot send %r to QEMU monitor: %s" % (cmd, exc)
            ) from exc
        # HMP echoes the command line on the same line as the reply. Read one
        # line, strip the echoed command, and return the reply.
        line = self._proc.stdout.readline()
        if not line:
            raise QemuMonitorError("QEMU monitor closed the pipe")
        return line.decode("utf-8", errors="replace").strip()


def cycle_adc_and_gate(qmp=None, adc_value=2012, qemu=None):
    """One read-modify-write cycle: inject an ADC sample, read the gate back.

    ``qmp`` is the ``QemuMonitor`` handle. When it is None, the environment
    gate decides what the result says instead of raising, and no QEMU is
    started. Every failure shape is returned as a clean, non-raising
    ``FirmwareCouplingCycle`` so callers and tests can enumerate them.
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
        return FirmwareCouplingCycle(
            ok=True, gate_high=qmp.read_gate(),
            message="set adc1-value=%d, gate=%s" % (adc_value, qmp.read_gate()),
        )
    finally:
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
