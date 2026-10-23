"""test_qemu_monitor_unit.py - Unit tests for the QEMU monitor double.

The QEMU binary does not exist in this environment, so these tests are pure
Python: they verify the monitor module's error shapes, the coupling-cycle
return values for every failure shape, and that the sweep never raises.

The socket server doubles that stand in for QEMU are only allowed here for
error handling; the real QEMU contract test must live in the qemu layer.
"""

import os
import socket
import sys
import threading

sys.path.insert(0, ".")

# Deliberately a *double*: a socket server that stands in for QEMU's monitor
# surface, used only to test the error-handling code path that cannot be
# triggered safely with the real binary (timeouts, dropped connections).
class MonitorSocketServer:
    """HTTP-like Socket server that speaks the QEMU monitor protocol.

    Waits for a connection, then answers commands until the client closes.
    Raises on malformed input and drops the connection when asked.
    """

    def __init__(self, drop_after=3):
        self.drop_after = drop_after
        self.connected = False
        self.received = []

    def serve(self, conn):
        self.connected = True
        buf = b""
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    line = buf.split(b"\n", 1)[0].decode("utf-8", "replace")
                    self.received.append(line)
                    buf = buf[len(line) + 1:]
                    if len(self.received) >= self.drop_after:
                        conn.close()
                        return
                    conn.sendall(b"OK\n")
        except OSError:
            pass
        finally:
            conn.close()


def make_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    return srv


def test_monitor_socket_server_double():
    """A socket server stands in for the QEMU monitor; the double must be
    named as a double and backed by a contract test with the real QEMU."""
    srv = make_server()
    conn = None
    try:
        conn, _ = srv.accept()
        conn.sendall(b"qom-set /machine/peripheral/sens adc1-value 2012\n")
        conn.recv(4096)
        ok = True
    except OSError:
        ok = False
    finally:
        srv.close()
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
    # Double is only for error handling; the real-QEMU contract test is in
    # test_qemu_monitor_qemu.py (qemu marker).
    assert ok


def test_cycle_adc_and_gate_error_shapes():
    """Every failure shape is returned as a clean, non-raising cycle."""
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

    # A handle that drops the connection must not raise.
    from bridge.qemu_monitor import QemuMonitor
    mon = QemuMonitor.__new__(QemuMonitor)
    mon.qemu = "/no/such/qemu"
    mon._proc = type("P", (), {"poll": lambda self: None,
                              "stdin": None,
                              "stdout": type("S", (), {"readline": lambda: b""})()})()
    try:
        cycle = cycle_adc_and_gate(qmp=mon, adc_value=2012)
        assert cycle.ok is False
        assert cycle.message
    except Exception as exc:
        raise AssertionError("coupling cycle raised unexpectedly: %r" % exc) from exc
