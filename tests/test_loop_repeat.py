"""tests/test_loop_repeat.py - the tracked R7 harness against the fake double.

R7's harness used to live in logs/cmd/ (gitignored), so a clone could not
reproduce the measurement (owner decision: move it to tools/loop_repeat.py).
This test runs the TRACKED script end to end against
tests/fakes/fake_hmp_qemu.py in its opt-in FAKE_HMP_FIRMWARE mode, where the
double writes the boot markers, answers HMP, and applies exactly one firmware
rule (main.c: gate ON when the injected count < 1995, OFF when > 2030, hold
in between) so the harness's flip logic is exercised.

It proves the harness runs and reports - NOT that real firmware behaves.
The real-emulator measurement stays in tools/run_emulator_tests.ps1 / R7.
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOP = os.path.join(ROOT, "tools", "loop_repeat.py")
FAKE = os.path.join(ROOT, "tests", "fakes", "fake_hmp_qemu.py")


def _run_one(fake_mode_env, timeout=120):
    env = dict(os.environ)
    env.update(fake_mode_env)
    return subprocess.run(
        [sys.executable, LOOP, FAKE, "1"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)


def _json_line(stdout):
    for line in stdout.splitlines():
        if line.startswith("R7_JSON:"):
            return json.loads(line[len("R7_JSON:"):])
    return None


def test_the_tracked_script_exists():
    assert os.path.isfile(LOOP), (
        "tools/loop_repeat.py is missing - R7 must be reproducible from a clone")


def test_one_run_against_the_fake_emulator(tmp_path):
    proc = _run_one({
        "FAKE_HMP_FIRMWARE": "1",
        "FAKE_HMP_RECORD": str(tmp_path / "record.txt"),
    })
    assert proc.returncode == 0, (
        "harness failed against the fake double\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (proc.stdout[-4000:], proc.stderr[-2000:]))

    data = _json_line(proc.stdout)
    assert data is not None, "no R7_JSON line:\n%s" % proc.stdout[-2000:]

    assert data["runs"] == 1
    assert data["runs_without_errors"] == 1, data["records"]
    assert data["flips_missed"] == 0, data["records"]
    assert data["panics"] == 0
    assert data["qemu_alive_at_end_runs"] == 1

    flips = data["flip_s_all"]
    assert flips and flips["n"] == 3, "LOW/HIGH/LOW expected: %r" % flips

    gate_lat = data["latency_read_gate_ms"]
    assert gate_lat and gate_lat["n"] >= 3, gate_lat
    assert gate_lat["max"] < 5000, "a fake answers instantly: %r" % gate_lat

    adc_lat = data["latency_set_adc_ms"]
    assert adc_lat and adc_lat["n"] == 4, adc_lat  # +1 readiness write

    reads = data["callbacks_per_run"]["gate_reads"]
    # readiness probe polls at least one gate read before the 3 measured ones
    assert reads and reads["min"] >= 4, reads
    # readiness write + 3 measured injections
    assert data["callbacks_per_run"]["adc_writes"] == [4]

    # owner decision (1): everything above must come from the MONITOR. The
    # fields the old UART tail produced are gone outright, and the run
    # succeeded without needing any firmware log line.
    assert "marker_to_telemetry_s" not in data
    assert "loop_rate_hz_est" not in data
    assert "telemetry_lines" not in data["callbacks_per_run"]
    assert "firmware_loop_max" not in data["callbacks_per_run"]
    assert data["records"][0].get("readiness_s") is not None
    # flip times are measured, never fabricated
    assert all(f["flip_s"] > 0
               for r in data["records"] for f in r["flips"]), data["records"]


def test_the_fake_receives_the_expected_commands(tmp_path):
    record = tmp_path / "record.txt"
    proc = _run_one({"FAKE_HMP_FIRMWARE": "1", "FAKE_HMP_RECORD": str(record)})
    assert proc.returncode == 0, proc.stdout[-2000:]
    sent = record.read_text().splitlines()
    adc_sets = [l for l in sent if l.startswith("qom-set") and "adc1-value" in l]
    # 4 writes: the readiness probe plus the measured LOW/HIGH/LOW
    assert len(adc_sets) == 4, sent
    assert any("1500" in l for l in adc_sets), sent
    assert any("2500" in l for l in adc_sets), sent
    assert any(l.startswith("xp") for l in sent), sent


def test_the_harness_needs_no_firmware_log_text(tmp_path):
    """Owner decision (1): with FAKE_HMP_UART=empty the double writes
    NOTHING to the serial file - no boot markers, no TELEMETRY, no
    "Raw ADC". The run must still succeed, because the harness derives
    readiness and every measurement from the monitor alone."""
    proc = _run_one({
        "FAKE_HMP_FIRMWARE": "1",
        "FAKE_HMP_UART": "empty",
        "FAKE_HMP_RECORD": str(tmp_path / "record.txt"),
    })
    assert proc.returncode == 0, (
        "harness must not depend on firmware log text\n"
        "STDOUT:\n%s\nSTDERR:\n%s" % (proc.stdout[-4000:], proc.stderr[-2000:]))
    data = _json_line(proc.stdout)
    assert data is not None, "no R7_JSON line:\n%s" % proc.stdout[-2000:]
    assert data["runs_without_errors"] == 1, data["records"]
    assert data["flips_missed"] == 0, data["records"]
    flips = data["flip_s_all"]
    assert flips and flips["n"] == 3, flips
