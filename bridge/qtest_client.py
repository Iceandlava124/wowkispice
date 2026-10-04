"""
qtest_client.py - Minimal client for QEMU's built-in qtest protocol.

qtest is the control channel QEMU already ships for out-of-process test
harnesses. It gives an external process three things a plain HMP monitor
cannot:

  * byte-level read/write of guest memory,
  * deterministic control of *virtual* time via `clock_step`,
  * no interference with the guest's own scheduling.

That combination is what makes lockstep co-simulation possible: the host
advances ngspice by one time step, writes the resulting feedback voltage into
the emulated ADC, advances the ESP32 by the same amount of *virtual* time, and
reads the gate-drive pin back out. Nothing races the wall clock, so a run is
reproducible bit for bit.

Deliberately stdlib-only: this module has to import cleanly inside WSL (where
pip is unavailable) as well as on Windows.
"""

import socket
import time

__all__ = ["QtestClient", "QtestError", "QtestTimeout"]


class QtestError(RuntimeError):
    """QEMU replied FAIL to a command."""


class QtestTimeout(QtestError):
    """QEMU did not answer within the deadline."""


class QtestClient:
    """Line-oriented client for the qtest protocol.

    qtest is line based, but interleaves unsolicited async event lines that
    must be filtered out before the command response is parsed:

        [I +0.000000] OPENED
        [R +0.000587] clock_step
        [S +0.001227] OK 100000000

    Every reply is either ``OK ...``, ``FAIL ...`` or a bare hex blob.
    """

    def __init__(self, sock):
        self._sock = sock
        self._buf = b""
        self._events = []
        self.closed = False

    # ------------------------------------------------------------------ setup

    @classmethod
    def connect_tcp(cls, host, port, timeout=30.0, retry_seconds=20.0):
        """Connect to a QEMU started with ``-qtest tcp:host:port,server=on``.

        QEMU binds the socket asynchronously, so poll rather than assuming the
        port is live the instant the process is spawned.
        """
        deadline = time.monotonic() + retry_seconds
        last = None
        while time.monotonic() < deadline:
            try:
                sock = socket.create_connection((host, port), timeout=timeout)
            except OSError as exc:
                last = exc
                time.sleep(0.05)
            else:
                sock.settimeout(timeout)
                return cls(sock)
        raise QtestError(
            "could not reach qtest at %s:%d within %.1fs (%s)"
            % (host, port, retry_seconds, last)
        )

    @classmethod
    def connect_unix(cls, path, timeout=30.0, retry_seconds=20.0):
        """Connect to a QEMU started with ``-qtest unix:PATH,server=on``."""
        deadline = time.monotonic() + retry_seconds
        last = None
        while time.monotonic() < deadline:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(path)
            except OSError as exc:
                last = exc
                sock.close()
                time.sleep(0.05)
            else:
                sock.settimeout(timeout)
                return cls(sock)
        raise QtestError(
            "could not reach qtest at %s within %.1fs (%s)"
            % (path, retry_seconds, last)
        )

    # ------------------------------------------------------------- transport

    def _readline(self):
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise QtestError("qtest connection closed by QEMU")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("utf-8", errors="replace").strip()

    def command(self, cmd):
        """Send one command, skip async events, return the response line."""
        self._sock.sendall((cmd + "\n").encode("utf-8"))
        while True:
            line = self._readline()
            if not line:
                continue
            if line.startswith("["):
                # Unsolicited event, e.g. "[I +0.001] reset" or "[R ...] cmd".
                self._events.append(line)
                continue
            if line.startswith("FAIL"):
                raise QtestError("%s -> %s" % (cmd, line))
            return line

    def _ok_value(self, cmd):
        """Run a command that answers ``OK <value>`` and return <value>."""
        parts = self.command(cmd).split(None, 1)
        if len(parts) != 2:
            raise QtestError("%s -> %r, expected 'OK <value>'" % (cmd, self._buf))
        return parts[1].strip()

    # ---------------------------------------------------------------- memory

    def read(self, addr, size):
        """Read ``size`` bytes from guest address ``addr`` as bytes."""
        raw = self._ok_value("read 0x%x 0x%x" % (addr, size))
        return bytes.fromhex(raw)

    def write(self, addr, data):
        """Write ``data`` (bytes) to guest address ``addr``."""
        self.command("write 0x%x 0x%x 0x%s" % (addr, len(data), data.hex()))

    def readl(self, addr):
        """Read a 32-bit little-endian guest word."""
        return int(self._ok_value("readl 0x%x" % addr), 16)

    def readw(self, addr):
        return int(self._ok_value("readw 0x%x" % addr), 16)

    def readq(self, addr):
        return int(self._ok_value("readq 0x%x" % addr), 16)

    def writel(self, addr, value):
        self.command("writel 0x%x 0x%x" % (addr, value & 0xFFFFFFFF))

    def writew(self, addr, value):
        self.command("writew 0x%x 0x%x" % (addr, value & 0xFFFF))

    def writeq(self, addr, value):
        self.command("writeq 0x%x 0x%x" % (addr, value & 0xFFFFFFFFFFFFFFFF))

    # ----------------------------------------------------------------- clock

    def clock_step(self, ns=None):
        """Advance guest virtual time.

        With no argument QEMU jumps to the next timer deadline. Passing an
        explicit nanosecond count advances by exactly that much, which is what
        lockstep co-simulation wants: one ngspice step of dt.
        """
        cmd = "clock_step" if ns is None else "clock_step %d" % ns
        return int(self._ok_value(cmd))

    # ------------------------------------------------------------- lifecycle

    def events(self):
        """Async event lines observed so far, e.g. resets."""
        return list(self._events)

    def close(self):
        if not self.closed:
            try:
                self._sock.sendall(b"quit\n")
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False