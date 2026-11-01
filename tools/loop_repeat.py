"""loop_repeat.py - R7: the monitor loop on the real emulator, N measured runs.

TRACKED on purpose: it used to live in logs/cmd/, which .gitignore covers,
so a clone could not reproduce the R7 measurement (owner decision). It runs
INSIDE WSL next to the patched qemu-system-xtensa, through the same code
path the contract tests use (bridge.qemu_monitor.QemuMonitor, the boot command
of bridge.binary_runner.test_gate_flip). It also runs against the test
double tests/fakes/fake_hmp_qemu.py in FAKE_HMP_FIRMWARE mode, which is what
tests/test_loop_repeat.py does to keep the harness itself honest. One run:

    boot firmware -> prove the control loop runs (text-free readiness probe)
    -> inject LOW/HIGH/LOW -> record gate-flip times, every monitor
    round-trip latency, callback counts, and whether QEMU stayed alive.

Prints one JSON line prefixed R7_JSON: with per-run records and aggregates.
Definitions recorded with the numbers:
  * flip time   - seconds from qom-set injection until read_gate() first
                  reports the state that injection must produce
                  (main.c: <1995 -> ON, >2030 -> OFF);
  * latency     - wall time of one read_gate() or set_adc1_value() HMP
                  round trip through the bridge;
  * callbacks   - successful monitor replies (reader-loop callbacks): every
                  gate read and ADC write the monitor answered.

MEASUREMENT NOTE (owner decision, 2026-11-01): the harness reads NO
firmware log text for boot, readiness, measurement or verdict - the image
actually built prints neither "TELEMETRY: loop=" nor any line this harness
requires. What the removed 25 s tail was for: catch the firmware's first
"TELEMETRY: loop=10000" print (the counter prints every 10000 iterations)
to derive marker-to-telemetry time and loop_rate_hz_est. No recorded R7
measurement ever needed that line: #207 logged telemetry_lines 0 on all 10
runs with marker_to_telemetry_s null - every flip, latency and callback
count came from the monitor - and #208's 10/10 contract-gate runs used no
UART text; on the built image the wait cost 25.1 s of a 29.4 s run (#505).
The only remaining UART read is the end-of-run ESP-IDF crash-banner scan
("Guru Meditation"/"PANIC"): it can only ADD failures, never make a run
pass, and it is framework output, not a main.c log line.

R7_FLASH overrides the firmware image path; the fake-double tests point
it at a dummy image in tmp_path so they need no gitignored build
artifact (owner decision 4, 2026-11-01).

Usage: python3 tools/loop_repeat.py <qemu-path> [runs]
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/ -> repo root
sys.path.insert(0, REPO)

from bridge.qemu_monitor import QemuMonitor            # noqa: E402

FLASH = os.environ.get("R7_FLASH") or os.path.join(
    REPO, "firmware", "esp32_buck_controller", ".pio",
    "build", "esp32dev", "qemu_flash.bin")
LOW, HIGH = 1500, 2500        # firmware thresholds (main.c): <1995 ON, >2030 OFF
BOOT_DEADLINE = 20.0   # readiness probe only: boot-to-loop slack for the
                       # first below-threshold injection to flip the gate
FLIP_BOUND = 5.0       # measured injections 2/3 (documented R7 flip bound)
POLL = 0.01

# Calibrated against the firmware's own UART prints: with adc < 1995 the
# firmware turns the gate on and read_gate() reports True (see
# tests/test_qemu_monitor_qemu.py, Track B). Adjusted only if the smoke run
# contradicts it.
EXPECTED = {LOW: True, HIGH: False}


def boot(qemu, tag):
    """Spawn QEMU and wire a QemuMonitor exactly like test_gate_flip does.

    No firmware log line is waited for: the HMP prompt proves QEMU is up,
    and control-loop readiness is proved functionally in one_run by the
    readiness probe flipping the gate (owner decision 1).
    """
    uart = os.path.join(tempfile.gettempdir(), "r7-uart-%s.log" % tag)
    if os.path.exists(uart):
        os.remove(uart)
    args = [qemu]
    if qemu.endswith(".py"):
        # A Python test double (tests/fakes/fake_hmp_qemu.py) cannot be
        # spawned directly on Windows, so hand it to the interpreter.
        args = [sys.executable, qemu]
    cmd = args + ["-display", "none", "-serial", "file:" + uart,
                  "-monitor", "stdio", "-machine", "esp32",
                  "-drive", "file=%s,if=mtd,format=raw" % FLASH]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)

    mon = QemuMonitor(qemu)
    mon._proc = proc
    mon._buf = bytearray()
    mon._cursor = 0
    mon._lock = threading.Lock()
    mon._reader_thread = threading.Thread(target=mon._reader_loop, daemon=True)
    mon._reader_thread.start()
    mon._wait_prompt(timeout=10.0)
    time.sleep(0.5)
    return mon, proc, uart, time.monotonic()


def one_run(qemu, index):
    rec = {"run": index, "errors": [], "flips": [], "latencies": [],
           "callbacks": {"gate_reads": 0, "adc_writes": 0},
           "gate_states": [], "qemu_alive_at_end": False}
    mon = proc = None
    started = time.monotonic()
    try:
        mon, proc, uart, ready_at = boot(qemu, "run%d" % index)
        rec["boot_s"] = round(ready_at - started, 3)

        # Readiness probe (text-free): a below-threshold injection must flip
        # the gate ON within BOOT_DEADLINE or the control loop never ran.
        t_ready = time.monotonic()
        t = time.monotonic()
        mon.set_adc1_value(LOW)
        rec["latencies"].append(
            {"op": "set_adc", "ms": round((time.monotonic() - t) * 1000, 3)})
        rec["callbacks"]["adc_writes"] += 1
        deadline = t_ready + BOOT_DEADLINE
        ready = False
        while time.monotonic() < deadline:
            t = time.monotonic()
            gate = mon.read_gate()
            rec["latencies"].append(
                {"op": "read_gate", "ms": round((time.monotonic() - t) * 1000, 3)})
            rec["callbacks"]["gate_reads"] += 1
            if gate is True:
                ready = True
                break
            time.sleep(POLL)
        if not ready:
            rec["errors"].append(
                "control loop never flipped the gate ON within %.0fs"
                % BOOT_DEADLINE)
            return rec
        rec["readiness_s"] = round(time.monotonic() - t_ready, 3)

        for value in (LOW, HIGH, LOW):
            t_inject = time.monotonic()
            t = time.monotonic()
            mon.set_adc1_value(value)
            rec["latencies"].append(
                {"op": "set_adc", "ms": round((time.monotonic() - t) * 1000, 3)})
            rec["callbacks"]["adc_writes"] += 1

            expected = EXPECTED[value]
            deadline = t_inject + FLIP_BOUND
            flip_s = None
            while time.monotonic() < deadline:
                t = time.monotonic()
                gate = mon.read_gate()
                rec["latencies"].append(
                    {"op": "read_gate", "ms": round((time.monotonic() - t) * 1000, 3)})
                rec["callbacks"]["gate_reads"] += 1
                rec["gate_states"].append([value, gate])
                if gate is expected:
                    flip_s = round(time.monotonic() - t_inject, 4)
                    break
                time.sleep(POLL)
            rec["flips"].append({"adc": value, "expected": expected,
                                 "flip_s": flip_s})
            if flip_s is None:
                rec["errors"].append(
                    "no flip to %s within %.1fs at adc=%d" % (expected, FLIP_BOUND, value))
            time.sleep(0.05)

        # End-of-run crash scan - the ONLY UART read left (see MEASUREMENT
        # NOTE): the ESP-IDF crash banner can only add failures; no
        # measurement or verdict depends on any firmware log line.
        text = ""
        if os.path.exists(uart):
            try:
                with open(uart, errors="replace") as fh:
                    text = fh.read()
            except OSError as exc:
                rec["errors"].append("uart read failed: %s" % exc)
        rec["panics"] = text.count("Guru Meditation") + text.count("PANIC")
        rec["qemu_alive_at_end"] = proc.poll() is None
    except Exception as exc:                      # noqa: BLE001 - record, keep running
        rec["errors"].append("%s: %s" % (type(exc).__name__, exc))
    finally:
        for p in (mon, proc):
            if p is None:
                continue
            try:
                p.stop() if hasattr(p, "stop") else p.terminate()
            except Exception:                     # noqa: BLE001
                pass
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception:                     # noqa: BLE001
                pass
        rec["run_s"] = round(time.monotonic() - started, 3)
    return rec


def stats(values):
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)

    def pct(p):
        return ordered[min(n - 1, int(round(p * (n - 1))))]
    return {"n": n, "min": ordered[0],
            "mean": round(sum(ordered) / n, 4),
            "p50": pct(0.50), "p95": pct(0.95), "max": ordered[-1]}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    qemu = sys.argv[1]
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    if not os.path.isfile(FLASH):
        print("R7_JSON:" + json.dumps({"errors": ["flash missing: " + FLASH]}))
        return 2

    records = []
    for i in range(1, runs + 1):
        rec = one_run(qemu, i)
        records.append(rec)
        flips = [f["flip_s"] for f in rec["flips"]]
        print("run %2d: boot=%.2fs flips=%s errors=%s"
              % (i, rec.get("boot_s", -1), flips, rec["errors"] or "-"))

    all_flips = [f["flip_s"] for r in records for f in r["flips"]
                 if f["flip_s"] is not None]
    missed = [f for r in records for f in r["flips"] if f["flip_s"] is None]
    lat_gate = [l["ms"] for r in records for l in r["latencies"]
                if l["op"] == "read_gate"]
    lat_adc = [l["ms"] for r in records for l in r["latencies"]
               if l["op"] == "set_adc"]
    ok_runs = sum(1 for r in records if not r["errors"])
    out = {
        "runs": runs, "runs_without_errors": ok_runs,
        "flash": FLASH, "qemu": qemu,
        "flip_s_all": stats(all_flips), "flips_missed": len(missed),
        "latency_read_gate_ms": stats(lat_gate),
        "latency_set_adc_ms": stats(lat_adc),
        "callbacks_per_run": {
            "gate_reads": stats([r["callbacks"]["gate_reads"] for r in records]),
            "adc_writes": sorted({r["callbacks"]["adc_writes"] for r in records}),
        },
        "panics": sum(r.get("panics", 0) for r in records),
        "qemu_alive_at_end_runs": sum(1 for r in records if r["qemu_alive_at_end"]),
        "records": records,
    }
    print("R7_JSON:" + json.dumps(out))
    failures = [e for r in records for e in r["errors"]]
    return 0 if (ok_runs == runs and not missed and out["panics"] == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
