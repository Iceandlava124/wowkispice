#!/usr/bin/env python3
"""WOSP install sanity check: boot, inject an ADC sample, watch the gate react.

This automates exactly what the manual QEMU monitor session does:

  1. boots the patched qemu-system-xtensa with the buck-controller firmware,
  2. waits for the real control loop to print its first sample (gate ON),
  3. injects an ADC value through the QOM property at
     /machine/peripheral/sens (adc1-value),
  4. requires the firmware's printed sample to change and its own
     1995/2030 hysteresis to move the gate accordingly,
  5. shuts the emulator down and exits 0 on PASS.

Usage:
    python tools/demo_closed_loop.py [--qemu PATH] [--value 3456]

QEMU is located from --qemu, then $WOSP_QEMU, then the usual build locations
(a sibling qemu-build checkout, or ~/qemu-esp in WSL). On Windows, if QEMU is
a Linux ELF (the normal case: it is built inside WSL), the whole demo is
re-executed inside WSL automatically.

Exit codes: 0 = PASS, 1 = behaviour mismatch, 2 = setup problem (see SETUP.md).
"""
import argparse
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLASH = os.path.join(REPO, "firmware", "esp32_buck_controller", ".pio",
                     "build", "esp32dev", "qemu_flash.bin")
QOM_PATH = "/machine/peripheral/sens"   # fixed; verified identical across boots
BOOT_MARKER = "Entering high-speed hysteretic control loop"
PANIC_RE = re.compile(r"Guru Meditation|Interrupt wdt timeout", re.I)

# Firmware thresholds, from firmware/esp32_buck_controller/src/main.c
ADC_LOW, ADC_HIGH = 1995, 2030


def say(msg):
    print("  " + msg, flush=True)


def step(msg):
    print("\n== " + msg, flush=True)


def is_elf(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"\x7fELF"
    except OSError:
        return False


def to_wsl_path(path):
    """Windows path -> WSL path; already-posix paths pass through."""
    if path.startswith("/"):
        return path
    path = os.path.abspath(path)
    drive, rest = os.path.splitdrive(path)
    if not drive:
        return path
    return "/mnt/" + drive[0].lower() + rest.replace("\\", "/")


def find_qemu(explicit):
    candidates = []
    if explicit:
        candidates.append(explicit)
    elif os.environ.get("WOSP_QEMU"):
        candidates.append(os.environ["WOSP_QEMU"])
    else:
        candidates += [
            os.path.normpath(os.path.join(
                REPO, "..", "qemu-build",
                "qemu-esp_develop_9.2.2_20260417", "build",
                "qemu-system-xtensa")),
            os.path.expanduser("~/qemu-esp/build/qemu-system-xtensa"),
            os.path.expanduser(
                "~/qemu-esp_develop_9.2.2_20260417/build/qemu-system-xtensa"),
        ]
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


def reexec_in_wsl(qemu):
    """Windows cannot exec a Linux ELF; run this same script inside WSL."""
    if not shutil.which("wsl"):
        print("FAIL: QEMU at %s is a Linux binary but `wsl` was not found.\n"
              "      Install WSL2 (see SETUP.md) or pass --qemu pointing at a "
              "QEMU built inside WSL." % qemu, file=sys.stderr)
        return 2
    inner = [sys.executable and "python3",
             to_wsl_path(os.path.abspath(__file__)),
             "--qemu", to_wsl_path(qemu)]
    cmd = ["wsl", "-e", "bash", "-lc",
           " ".join(shlex.quote(x) for x in inner if x)]
    return subprocess.call(cmd)


def hmp_connect(port, attempts=40):
    for _ in range(attempts):
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=3)
            sock.settimeout(4)
            return sock
        except OSError:
            time.sleep(0.5)
    return None


def hmp_cmd(sock, cmd, wait=1.5):
    """Send one HMP command; return response lines (readline echo stripped)."""
    sock.sendall(cmd.encode() + b"\n")
    time.sleep(wait)
    out = b""
    while True:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        out += chunk
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]|\r", "", out.decode(errors="replace"))
    lines = []
    for line in text.splitlines():
        if not line.strip() or "(qemu)" in line or "monitor - type" in line:
            continue
        if "qom-" in line and not line[0].isdigit() and not line.startswith("Error"):
            continue  # echo of the command we typed
        lines.append(line)
    return lines


def wait_for_log(path, pattern, timeout, poll=0.5):
    """Return the first line matching pattern, or None on timeout."""
    rx = re.compile(pattern)
    deadline = time.time() + timeout
    seen = 0
    while time.time() < deadline:
        try:
            with open(path, "r", errors="replace") as fh:
                data = fh.read()
        except OSError:
            data = ""
        if len(data) > seen:
            for line in data[seen:].splitlines():
                if rx.search(line):
                    return line
            seen = len(data)
        time.sleep(poll)
    return None


def run_demo(qemu, value, boot_timeout, gate_timeout):
    if not os.path.isfile(FLASH):
        print("FAIL: flash image missing:\n      %s\n"
              "      Build the firmware first (SETUP.md, Part D)." % FLASH,
              file=sys.stderr)
        return 2

    tmp = tempfile.gettempdir()          # keep logs off drvfs (see orchestrator)
    uart = os.path.join(tmp, "wosp-demo-uart.log")
    errlog = os.path.join(tmp, "wosp-demo-qemu.log")
    for f in (uart, errlog):
        try:
            os.remove(f)
        except OSError:
            pass

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    step("[1/6] Starting the emulator")
    say("qemu:  " + qemu)
    say("flash: " + FLASH)
    say("serial log: " + uart)
    cmd = [qemu, "-display", "none",
           "-serial", "file:" + uart,
           "-monitor", "tcp:127.0.0.1:%d,server=on,wait=off" % port,
           "-machine", "esp32",
           "-drive", "file=%s,if=mtd,format=raw" % FLASH]
    with open(errlog, "w") as err:
        proc = subprocess.Popen(cmd, stdout=err, stderr=err)

    hmp = None
    try:
        step("[2/6] Waiting for the QEMU monitor")
        hmp = hmp_connect(port)
        if hmp is None:
            print("FAIL: monitor never came up; QEMU said:\n" +
                  open(errlog).read()[-1500:], file=sys.stderr)
            return 1
        say("monitor on 127.0.0.1:%d" % port)

        step("[3/6] Booting ROM -> bootloader -> app_main() (takes ~10-30 s)")
        line = wait_for_log(uart, re.escape(BOOT_MARKER), boot_timeout)
        if not line:
            print("FAIL: control loop never started (timeout %ds).\n"
                  "      Serial tail:\n%s" %
                  (boot_timeout, tail(uart, 12)), file=sys.stderr)
            return 1
        say("firmware reached the control loop")

        step("[4/6] First sample from the control loop")
        line = wait_for_log(uart, r"Raw ADC: \d+ \| Gate: (ON|OFF)",
                            boot_timeout)
        if not line:
            print("FAIL: no control-loop sample printed.\n      Serial tail:\n%s"
                  % tail(uart, 12), file=sys.stderr)
            return 1
        say("sample: " + line.strip())
        if "Gate: ON" not in line:
            print("FAIL: expected the initial sample (adc=0, below the 1995 "
                  "threshold) to show Gate: ON.\n      Got: %s" % line,
                  file=sys.stderr)
            return 1

        expected_gate = "OFF" if value > ADC_HIGH else "ON"
        step("[5/6] Injecting adc1-value = %d via qom-set" % value)
        reply = hmp_cmd(hmp, "qom-set %s adc1-value %d" % (QOM_PATH, value))
        if any(l.startswith("Error") for l in reply):
            print("FAIL: qom-set rejected: %s\n"
                  "      (Is this the patched QEMU? See SETUP.md Part E.)"
                  % reply, file=sys.stderr)
            return 1
        got = hmp_cmd(hmp, "qom-get %s adc1-value" % QOM_PATH)
        say("qom-get confirms: %s" % (got[-1] if got else "?"))
        if not got or got[-1].strip() != str(value):
            print("FAIL: property did not stick: %s" % got, file=sys.stderr)
            return 1

        step("[6/6] Waiting for the firmware to react (expect Gate: %s)"
             % expected_gate)
        pattern = r"Raw ADC: %d \| Gate: %s" % (value, expected_gate)
        line = wait_for_log(uart, pattern, gate_timeout)
        if not line:
            print("FAIL: firmware never printed '%s'.\n      Serial tail:\n%s"
                  % (pattern, tail(uart, 12)), file=sys.stderr)
            return 1
        say("sample: " + line.strip())

        body = open(uart, errors="replace").read()
        panics = len(PANIC_RE.findall(body))
        loops = len(re.findall(r"BUCK_CTRL: Loop", body))
        print("\n---- demo result ----")
        print("  control-loop samples observed : %d" % loops)
        print("  injected adc1-value           : %d" % value)
        print("  gate                          : ON -> %s" % expected_gate)
        print("  panics                        : %d" % panics)
        print("  serial log                    : %s" % uart)
        if panics:
            print("FAIL: guest panicked (watchdog).", file=sys.stderr)
            return 1
        print("PASS: the install boots the firmware, takes injected analog "
              "values and reacts. --")
        return 0
    finally:
        if hmp is not None:
            try:
                hmp.close()
            except OSError:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def tail(path, n=12):
    try:
        with open(path, errors="replace") as fh:
            lines = fh.read().splitlines()
        return "\n".join("      " + l for l in lines[-n:]) or "      (empty)"
    except OSError:
        return "      (no serial log)"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--qemu", help="path to qemu-system-xtensa "
                                   "(default: $WOSP_QEMU, then known locations)")
    ap.add_argument("--value", type=int, default=3456,
                    help="ADC sample to inject (default 3456, above the "
                         "firmware's 2030 threshold, so the gate must turn OFF)")
    ap.add_argument("--boot-timeout", type=int, default=90)
    ap.add_argument("--gate-timeout", type=int, default=45)
    args = ap.parse_args()

    qemu = find_qemu(args.qemu)
    if not qemu:
        print("FAIL: qemu-system-xtensa not found. Searched:\n"
              "      --qemu, $WOSP_QEMU, sibling qemu-build checkout, "
              "~/qemu-esp.\n      Build it per SETUP.md Part E, then pass "
              "--qemu or set WOSP_QEMU.", file=sys.stderr)
        return 2

    # Windows cannot exec a Linux ELF: the child WSL process prints its own
    # banner, so delegate before printing ours.
    if os.name == "nt" and (not os.path.isfile(qemu) or is_elf(qemu)):
        return reexec_in_wsl(qemu)

    print("WOSP closed-loop demo (boot -> inject ADC -> gate reacts)")
    try:
        return run_demo(qemu, args.value, args.boot_timeout, args.gate_timeout)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
