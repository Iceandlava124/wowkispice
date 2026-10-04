"""
qemu_orchestrator.py - Boot the real ESP32 firmware under Espressif's QEMU.

Renode was the original emulator target but it cannot decode the Xtensa
``entry`` instruction, which appears 393 times in an ordinary ESP-IDF build, so
it never executed a single instruction of our firmware. Espressif's own QEMU
fork runs the identical image through ROM, second-stage bootloader and
``app_main``.

Two ways to talk to QEMU, and the difference matters:

``boot_and_watch()`` runs the guest under normal TCG acceleration and simply
reads the console UART. This is the mode that actually executes firmware.

``probe_memory()`` runs the guest under ``accel=qtest`` purely to read and
write guest memory. **qtest does not execute the CPU.** QEMU wires the qtest
accelerator to ``dummy_start_vcpu_thread`` (accel/qtest/qtest.c ->
accel/dummy-cpus.c), so no real vCPU thread exists; ``clock_step`` only
advances the virtual clock and runs timer callbacks. Measured behaviour: 1.078 s
of virtual time elapses, the guest UART stays empty and DRAM never changes,
then QEMU blocks once the timers run out. So qtest is a memory poke tool here,
nothing more, and nothing in this module drives the guest with it.

Known gap, stated plainly rather than papered over: Espressif's QEMU models no
SAR ADC. ``SENS`` is one of ~24 ``unimplemented-device`` stubs, which decode
MMIO but discard writes, so nothing outside QEMU can inject a conversion
result. The firmware spins forever at ``while (!adc_oneshot_ll_get_event(...))``
in adc_oneshot_hal.c and the interrupt watchdog trips. ``probe_memory()``
demonstrates the hole precisely and will start passing once an
``esp32_sens.c`` model lands in QEMU's tree.

Run directly to boot the firmware and report::

    python -m bridge.qemu_orchestrator --qemu /path/to/qemu-system-xtensa
"""

import os
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.qtest_client import QtestClient, QtestError

__all__ = [
    "QemuSession", "boot_and_watch", "probe_memory", "ADC_UNMODELLED",
    "FLASH_IMAGE", "BOOT_MARKERS", "main",
]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(
    REPO_ROOT, "firmware", "esp32_buck_controller", ".pio", "build", "esp32dev"
)
FLASH_IMAGE = os.path.join(BUILD_DIR, "qemu_flash.bin")

# Lines main.c prints once it is genuinely running, used as the boot sentinel.
BOOT_MARKERS = (
    "BUCK_CTRL: Starting ESP32 Buck Converter Closed-Loop Controller",
    "BUCK_CTRL: Entering high-speed hysteretic control loop",
)

ADC_UNMODELLED = "SENS is an unimplemented-device: MMIO writes are discarded"


def _log_path(name):
    """Console logs must land on a local filesystem, not /mnt/c.

    drvfs refuses reads of a file another process still holds open
    (OSError 61, 'No data available'), and QEMU holds the console for the whole
    run. Keeping logs in the temp dir also stops them polluting the build dir.
    """
    return os.path.join(tempfile.gettempdir(), name)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class QemuSession:
    """A running QEMU ESP32, its console log, and optionally its qtest channel."""

    def __init__(self, proc, uart_path, client=None):
        self.proc = proc
        self.uart_path = uart_path
        self.client = client

    def uart_text(self):
        if not os.path.exists(self.uart_path):
            return ""
        with open(self.uart_path, "r", errors="replace") as fh:
            return fh.read()

    def close(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _launch(qemu, image, machine, uart_path, qtest):
    if not os.path.exists(qemu):
        raise FileNotFoundError(
            "qemu-system-xtensa not found at %r. Set WOSP_QEMU or pass --qemu." % qemu
        )
    if not os.path.exists(image):
        raise FileNotFoundError(
            "flash image %r missing; build it with esptool merge_bin "
            "(bootloader + partition table + app at their flash offsets)." % image
        )

    if os.path.exists(uart_path):
        os.remove(uart_path)

    cmd = [qemu, "-display", "none", "-serial", "file:%s" % uart_path,
           "-monitor", "none", "-machine", machine]
    if qtest:
        port = _free_port()
        cmd += ["-machine", "%s,accel=qtest" % machine,
                "-qtest", "tcp:127.0.0.1:%d,server=on,wait=off" % port]
    cmd += ["-drive", "file=%s,if=mtd,format=raw" % image]

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    client = None
    if qtest:
        try:
            client = QtestClient.connect_tcp("127.0.0.1", port)
        except QtestError:
            proc.kill()
            stderr = proc.stderr.read().decode(errors="replace")
            raise QtestError("qtest never came up. QEMU said:\n%s" % stderr[-2000:])
    return QemuSession(proc, uart_path, client)


def boot_and_watch(qemu, image=FLASH_IMAGE, machine="esp32",
                   markers=BOOT_MARKERS, timeout=30.0):
    """Boot the firmware under TCG and block until every marker hits the UART.

    Returns ``(session, missing)``. The session is still running, so the caller
    can inspect the console or the chip's state. Because qtest is not in play
    this is ordinary wall-clock execution; the ESP32 will panic on the
    interrupt watchdog once it reaches the unmodelled ADC read.
    """
    uart = _log_path("wosp_qemu_uart.log")
    session = _launch(qemu, image, machine, uart, qtest=False)
    deadline = time.monotonic() + timeout
    wanted = list(markers)
    while wanted and time.monotonic() < deadline:
        text = session.uart_text()
        wanted = [m for m in wanted if m not in text]
        if not wanted:
            break
        if session.proc.poll() is not None:
            break
        time.sleep(0.05)
    return session, list(wanted)


def probe_memory(qemu, image=FLASH_IMAGE, machine="esp32"):
    """Start QEMU in qtest mode purely to inspect memory-access semantics.

    The guest is *not* executed here; see the module docstring. Writes to RAM
    must round-trip. Writes to MMIO only round-trip if QEMU actually models
    that peripheral, so this doubles as a report of what the emulated chip can
    be *observed* through, which is exactly what a co-simulation bridge needs.
    """
    from bridge import esp32_regs as regs

    adc_payload = regs.sar1_result(0x0BAD)
    probes = [
        ("dram scratch", 0x3FFB0000, 0xDEADBEEF),
        ("SENS sar_meas_start1", regs.SENS_SAR_MEAS_START1_REG, adc_payload),
        ("GPIO out", regs.GPIO_OUT_REG, regs.gate_bit(18)),
        ("GPIO enable", regs.GPIO_ENABLE_REG, regs.gate_bit(18)),
    ]

    uart = _log_path("wosp_qemu_probe_uart.log")
    with _launch(qemu, image, machine, uart, qtest=True) as session:
        client = session.client
        rows = []
        for name, addr, value in probes:
            client.writel(addr, value)
            rows.append((name, addr, value, client.readl(addr)))

    retained = [r[0] for r in rows if r[3] == r[2]]
    return rows, retained


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    qemu = os.environ.get("WOSP_QEMU")
    if "--qemu" in args:
        qemu = args[args.index("--qemu") + 1]

    print("=" * 70)
    print("  WOSP / QEMU boot check")
    print("=" * 70)
    if not qemu:
        print(__doc__)
        print("ERROR: pass --qemu /path/to/qemu-system-xtensa or set WOSP_QEMU")
        return 2
    print("qemu  :", qemu)
    print("image :", FLASH_IMAGE)
    print()

    t0 = time.monotonic()
    session, missing = boot_and_watch(qemu)
    with session:
        text = session.uart_text()
        print("--- guest UART (%d bytes, %.1f s, %s) ---"
              % (len(text), time.monotonic() - t0, session.uart_path))
        for line in text.splitlines():
            print("  " + line)
        print()
        print("missing markers: %s" % (missing or "none"))

    print()
    print("--- memory channel probe (qtest, guest not executed) ---")
    print("  %-22s %-12s %-12s %-12s %s"
          % ("region", "address", "wrote", "read back", "retains writes?"))
    rows, retained = probe_memory(qemu)
    for name, addr, value, readback in rows:
        print("  %-22s 0x%08X   0x%08X   0x%08X   %s"
              % (name, addr, value, readback, "yes" if readback == value else "NO"))
    print()
    print("  modelled for observation: %s" % (", ".join(retained) or "none"))
    unmodelled = [r[0] for r in rows if r[3] != r[2]]
    if unmodelled:
        print("  unimplemented-device (writes discarded): %s" % ", ".join(unmodelled))
    print()
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())