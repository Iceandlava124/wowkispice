"""fake_hmp_qemu.py - TEST DOUBLE for `qemu-system-xtensa -monitor stdio`.

THIS IS A TEST DOUBLE, NOT AN EMULATOR. It implements just enough of QEMU's
human-monitor (HMP) stdio protocol to verify that bridge/qemu_monitor.py
speaks that protocol correctly: banner, "(qemu) " prompt, command echo,
reply lines, and the failure modes a real QEMU can exhibit (Error: replies,
dropped pipes, silence, garbage). It executes no firmware, models no ESP32,
knows nothing about ADC physics or GPIO hardware -- a green test here says
NOTHING about real firmware or the real emulator. The real-emulator
contract lives in tests/test_qemu_monitor_qemu.py under the `qemu` marker.

Configuration (environment variables; the argv that QemuMonitor.start()
builds -- `-display none -machine ... -monitor stdio -serial none` --
is accepted and ignored):

  FAKE_HMP_MODE          normal | error | drop | silent | garbage
                         (default: normal)
                           normal  - qom-set replies with silence (QEMU's
                                     success behaviour), xp replies with a
                                     realistic "000000003ff44004: 0xVALUE" line
                           error   - qom-set replies with an HMP Error: line
                           drop    - answers the first N commands, then
                                     closes both pipes and exits (a crashed
                                     QEMU); N = FAKE_HMP_DROP_AFTER
                           silent  - prints not even the banner (a wedged QEMU)
                           garbage - xp replies with text no parser can use
  FAKE_HMP_RECORD        if set, every command received is appended to this
                         file, one per line (tests assert on what arrived)
  FAKE_HMP_XP_VALUE      0x-value in the xp reply; default 0x00040000
                         (bit 18 set -> gate True), use 0x00000000 for False
  FAKE_HMP_DROP_AFTER    commands answered before dropping in `drop` mode
                         (default 1; 0 drops immediately after the banner)
  FAKE_HMP_STAY_ALIVE    when set, EOF on stdin does NOT end the process: it
                         keeps running until it is explicitly killed. Models
                         the peer that survives its wrapper dying, which is
                         the leak QemuMonitor.stop() has to prevent
                         (tests/test_qemu_monitor_unit.py::
                         test_stop_tears_down_the_whole_process_tree).
                         Without it a leaked fake exits on its own when the
                         client's pipe closes, so old and fixed teardown look
                         identical.
  FAKE_HMP_FIRMWARE      when set, the double also models exactly ONE firmware
                         rule so the R7 harness (tools/loop_repeat.py) can be
                         driven end to end: it writes the boot markers and a
                         TELEMETRY line to the -serial file: it is given, and
                         `xp` reflects the last `qom-set ... adc1-value N` by
                         main.c's rule - gate ON when N < 1995, OFF when
                         N > 2030, hold in between. Still a double: it proves
                         the harness logic, never firmware behaviour.
  FAKE_HMP_UART          when set to "empty", the -serial file stays empty
                         even in FAKE_HMP_FIRMWARE mode (no boot markers, no
                         TELEMETRY): proves tools/loop_repeat.py depends on
                         no firmware log text (owner decision 1).
"""

import os
import sys
import time

PROMPT = "(qemu) "


def _write(text):
    """Write to stdout and flush: the client reads a pipe, not a terminal."""
    sys.stdout.write(text)
    sys.stdout.flush()


def main():
    mode = os.environ.get("FAKE_HMP_MODE", "normal")
    record = os.environ.get("FAKE_HMP_RECORD")
    xp_value = os.environ.get("FAKE_HMP_XP_VALUE", "0x00040000")
    drop_after = int(os.environ.get("FAKE_HMP_DROP_AFTER", "1"))
    stay_alive = os.environ.get("FAKE_HMP_STAY_ALIVE")
    firmware = os.environ.get("FAKE_HMP_FIRMWARE")

    if firmware:
        # Boot sentinel + a TELEMETRY line, written to the -serial file.
        # tools/loop_repeat.py no longer reads them (owner decision 1); the
        # double still models them, and FAKE_HMP_UART=empty removes even
        # these so a test can prove the harness needs no log text at all.
        uart = None
        argv = sys.argv[1:]
        for i, a in enumerate(argv):
            if a == "-serial" and i + 1 < len(argv) and \
                    argv[i + 1].startswith("file:"):
                uart = argv[i + 1][len("file:"):]
        if uart and os.environ.get("FAKE_HMP_UART") != "empty":
            repo = os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))
            if repo not in sys.path:
                sys.path.insert(0, repo)
            from bridge.qemu_orchestrator import BOOT_MARKERS
            with open(uart, "w") as fh:
                for marker in BOOT_MARKERS:
                    fh.write(marker + "\n")
                fh.write("TELEMETRY: loop=10000 adc=0 gate=OFF "
                         "thresh=[1995,2030] mode=adaptive\n")

    # main.c's rule, applied only in firmware mode: <1995 ON, >2030 OFF,
    # inside the band the previous state is held (hysteresis).
    gate_on = bool(int(xp_value, 16) & 0x40000)
    last_adc = None

    if mode == "silent":
        # A wedged QEMU: no banner, no prompt, no replies, ever. The client's
        # documented 10 s prompt timeout is what must fire here.
        while True:
            time.sleep(1)

    # QEMU-style banner, then the first prompt (no trailing newline, like
    # QEMU: the prompt is not a line, it is a marker).
    _write("QEMU emulator version 9.2.2 (fake_hmp_qemu TEST DOUBLE - protocol only)\n")
    _write("Copyright (c) 2003-2008 Fabrice Bellard (fake)\n")
    _write(PROMPT)

    commands = 0
    while True:
        if mode == "drop" and commands >= drop_after:
            # Crash after N commands: both pipes close, process exits.
            os._exit(0)
        line = sys.stdin.readline()
        if not line:
            if stay_alive:
                # The client's end closed, but this peer does not go away:
                # only an explicit kill of the process tree ends it.
                while True:
                    time.sleep(0.5)
            return 0                      # the client closed its end
        cmd = line.strip()
        if record:
            with open(record, "a") as fh:  # exactly what the client sent
                fh.write(cmd + "\n")
        commands += 1

        if firmware and cmd.startswith("qom-set") and "adc1-value" in cmd:
            parts = cmd.split()
            try:
                last_adc = int(parts[parts.index("adc1-value") + 1])
            except (ValueError, IndexError):
                last_adc = None

        # QEMU's readline echoes the typed command back before replying;
        # the client skips lines that contain the command text.
        _write(cmd + "\n")

        if mode == "error" and cmd.startswith("qom-set"):
            _write("Error: property 'adc1-value' not found in instruction 'qom-set'\n")
        elif mode == "garbage" and cmd.startswith("xp"):
            _write("garbage that is neither address nor value: no hex token here\n")
        elif cmd.startswith("xp"):
            # Real HMP xp formatting: "<addr>: <value>".
            value = xp_value
            if firmware and last_adc is not None:
                if last_adc < 1995:
                    gate_on = True
                elif last_adc > 2030:
                    gate_on = False
                value = "0x00040000" if gate_on else "0x00000000"
            _write("000000003ff44004: %s\n" % value)
        # qom-set's success reply is silence: only the echo precede the prompt.

        _write(PROMPT)


if __name__ == "__main__":
    raise SystemExit(main())
