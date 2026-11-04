#!/usr/bin/env python3
"""
parity_measurements.py - cross-implementation diff of bridge/measurements.py
against the Rust port in crates/wowkispice-core/src/measurements.rs.

One fixed battery of waveform-analysis inputs, computed twice (Python vs
Rust), over one identical key space.  Keys are index-based (s[i], c[i],
r[i], t[i], st[i], rf[i], sm[i], f[i], thd[i], b[i], pm[i], p[i], sc[i]).
Floats are compared as doubles; strings as text.

Run:  .venv/Scripts/python.exe crates/parity/python/parity_measurements.py <path-to-parity_measurements>
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Tuple

REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, REPO)

from bridge import measurements as m  # noqa: E402

BINARY_NAME = "parity_measurements"


# ---------------------------------------------------------------- synthetic inputs (identical to Rust side)

T_SINE: List[float] = [i * 1e-5 for i in range(5001)]
V_SINE: List[float] = [math.sin(2 * math.pi * 1000.0 * t) for t in T_SINE]

T_SQ: List[float] = [i * 1e-5 for i in range(5001)]
V_SQ: List[float] = [1.0 if ((t * 1000.0) % 1.0) < 0.5 else 0.0 for t in T_SQ]

TAU = 1e-3
T_RC: List[float] = [i * 5e-6 for i in range(2001)]
V_RC: List[float] = [1.0 - math.exp(-t / TAU) for t in T_RC]

T_STEP: List[float] = [i * 5e-6 for i in range(3001)]
V_STEP: List[float] = []
for t in T_STEP:
    if t < 3.0 * TAU:
        V_STEP.append(1.0 - math.exp(-t / TAU))
    elif 4.0 * TAU <= t < 4.2 * TAU:
        V_STEP.append(1.25)
    else:
        V_STEP.append(1.0)

T_RF: List[float] = [i * 1e-6 for i in range(2000)]
V_RF: List[float] = [0.0 if t < 1e-3 else 5.0 for t in T_RF]


# ---------------------------------------------------------------- Python-side battery

def enc_opt_f64(v):
    if v is None:
        return "None"
    return f"{v:.10e}"


def enc_vec_f64(v):
    return "|".join(f"{x:.10e}" for x in v)


def enc_cursor(r):
    return (
        f"t1={enc_opt_f64(r['t1'])}|v1={enc_opt_f64(r['v1'])}|"
        f"t2={enc_opt_f64(r['t2'])}|v2={enc_opt_f64(r['v2'])}|"
        f"dt={enc_opt_f64(r['dt'])}|dv={enc_opt_f64(r['dv'])}|"
        f"slope={enc_opt_f64(r['slope'])}|inv_dt={enc_opt_f64(r['inv_dt'])}|"
        f"inv_dv={enc_opt_f64(r['inv_dv'])}"
    )


def enc_stats(s):
    return (
        f"points={s['points']}|mean={enc_opt_f64(s.get('mean'))}|"
        f"rms={enc_opt_f64(s.get('rms'))}|min={enc_opt_f64(s.get('min'))}|"
        f"max={enc_opt_f64(s.get('max'))}|p2p={enc_opt_f64(s.get('p2p'))}|"
        f"duty={enc_opt_f64(s.get('duty'))}|first_crossing_s={enc_opt_f64(s.get('first_crossing_s'))}"
    )


def enc_step(m):
    return (
        f"points={m['points']}|v_start={enc_opt_f64(m['v_start'])}|"
        f"v_final={enc_opt_f64(m['v_final'])}|step_v={enc_opt_f64(m['step_v'])}|"
        f"direction={m['direction']}|delay_s={enc_opt_f64(m['delay_s'])}|"
        f"rise_s={enc_opt_f64(m['rise_s'])}|overshoot_pct={m['overshoot_pct']:.10e}|"
        f"undershoot_pct={m['undershoot_pct']:.10e}|"
        f"settling_s={enc_opt_f64(m['settling_s'])}|"
        f"slew_v_ms={enc_opt_f64(m['slew_v_ms'])}"
    )


def enc_fft(f):
    mag0 = f["magnitude"][0] if f["magnitude"] else 0.0
    freq0 = f["freqs"][0] if f["freqs"] else 0.0
    return (
        f"dominant_hz={enc_opt_f64(f.get('dominant_hz'))}|n={f.get('n', 0)}|"
        f"sample_rate_hz={f.get('sample_rate_hz', 0.0):.10e}|"
        f"noise_floor={f.get('noise_floor', 0.0):.10e}|bin_width_hz={f.get('bin_width_hz', 0.0):.10e}|"
        f"mag0={mag0:.10e}|freq0={freq0:.10e}"
    )


def enc_bode(b):
    gain0 = b["gain_db"][0] if b["gain_db"] else 0.0
    phase0 = b["phase_deg"][0] if b["phase_deg"] else 0.0
    return (
        f"peak_db={enc_opt_f64(b['peak_db'])}|peak_hz={enc_opt_f64(b['peak_hz'])}|"
        f"gain0={gain0:.10e}|phase0={phase0:.10e}"
    )


def enc_power(p):
    return (
        f"p_in_w={p['p_in_w']:.10e}|p_out_w={p['p_out_w']:.10e}|"
        f"loss_w={p['loss_w']:.10e}|efficiency={enc_opt_f64(p['efficiency'])}"
    )


def battery() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []

    # s[i]: sample_at
    out.append(("s[0]", enc_opt_f64(m.sample_at(T_SINE, V_SINE, 0.5, True))))
    out.append(("s[1]", enc_opt_f64(m.sample_at(T_SINE, V_SINE, 1.25, True))))
    out.append(("s[2]", enc_opt_f64(m.sample_at(T_SINE, V_SINE, -5.0, True))))
    out.append(("s[3]", enc_opt_f64(m.sample_at(T_SINE, V_SINE, 99.0, False))))

    # c[i]: cursor_readout
    out.append(("c[0]", enc_cursor(m.cursor_readout(T_SINE, V_SINE, 0.0, 0.0, 1e-3, 1.0))))
    out.append(("c[1]", enc_cursor(m.cursor_readout(T_SINE, V_SINE, 0.5, None, None, None))))
    out.append(("c[2]", enc_cursor(m.cursor_readout([], [], 0.0, 0.0, None, None))))

    # r[i]: format_readout
    out.append(("r[0]", m.format_readout(m.cursor_readout(T_SINE, V_SINE, 0.0, 0.0, 1e-3, 1.0))))

    # t[i]: trace_stats
    out.append(("t[0]", enc_stats(m.trace_stats(T_SINE, V_SINE, None))))
    out.append(("t[1]", enc_stats(m.trace_stats(T_SQ, V_SQ, 0.5))))
    out.append(("t[2]", enc_stats(m.trace_stats([], [], None))))

    # st[i]: settling_time
    out.append(("st[0]", enc_opt_f64(m.settling_time(T_RC, V_RC, 5.0, 0.02, None))))
    out.append(("st[1]", enc_opt_f64(m.settling_time(T_STEP, V_STEP, 1.0, 0.02, None))))

    # rf[i]: rise_fall_time
    rf = m.rise_fall_time(T_RF, V_RF, 0.0, 5.0, 0.5)
    out.append(("rf[0]", f"rise={enc_opt_f64(rf['rise_s'])}|fall={enc_opt_f64(rf['fall_s'])}"))

    # sm[i]: step_metrics
    out.append(("sm[0]", enc_step(m.step_metrics(T_RC, V_RC, 0.02))))
    out.append(("sm[1]", enc_step(m.step_metrics(T_STEP, V_STEP, 0.02))))
    out.append(("sm[2]", enc_step(m.step_metrics(T_RC, [2.5] * 50, 0.02))))

    # f[i]: fft_spectrum
    out.append(("f[0]", enc_fft(m.fft_spectrum(T_SINE, V_SINE, "blackman"))))
    out.append(("f[1]", enc_fft(m.fft_spectrum(T_SQ, V_SQ, "blackman"))))
    out.append(("f[2]", enc_fft(m.fft_spectrum([0.0, 1e-6], [0.0, 1.0], "blackman"))))

    # thd[i]: thd
    f0 = m.fft_spectrum(T_SINE, V_SINE, "blackman")
    out.append(("thd[0]", enc_opt_f64(m.thd(f0["freqs"], f0["magnitude"], 1000.0, 20))))
    f1 = m.fft_spectrum(T_SQ, V_SQ, "blackman")
    out.append(("thd[1]", enc_opt_f64(m.thd(f1["freqs"], f1["magnitude"], 1000.0, 20))))

    # b[i]: bode_from_ac
    freqs = [10.0, 100.0, 1000.0, 10000.0, 100000.0]
    rc = 1e-4
    re = [1.0 / math.sqrt(1 + (2 * math.pi * f * rc) ** 2) for f in freqs]
    im = [0.0] * len(freqs)
    b = m.bode_from_ac(freqs, re, im, 1.0)
    out.append(("b[0]", enc_bode(b)))

    # pm[i]: phase_margin
    pm = m.phase_margin([1.0, 100.0], [-0.1, -20.0], [-5.0, -80.0])
    out.append(("pm[0]", f"crossover={enc_opt_f64(pm['crossover_hz'])}|"
                   f"gain={enc_opt_f64(pm['gain_at_crossover_db'])}|"
                   f"pm={enc_opt_f64(pm['phase_margin_deg'])}|"
                   f"gm={enc_opt_f64(pm['gain_margin_db'])}"))

    # p[i]: power_metrics
    out.append(("p[0]", enc_power(m.power_metrics(12.0, 0.275, 3.3, 1.0))))
    out.append(("p[1]", enc_power(m.power_metrics(3.3, 1.0, 12.0, 1.0))))

    # sc[i]: series_current
    out.append(("sc[0]", enc_vec_f64(m.series_current([0.0, 1.0], [5.0, 10.0], 1000.0))))

    return out


# ---------------------------------------------------------------- rust side


def run_rust_battery(binary: str, manifest: str) -> Dict[str, str]:
    proc = subprocess.run(
        [binary, manifest],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"parity_measurements (rust) exited {proc.returncode}\n{proc.stderr}"
        )
    result: Dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        if "\t" not in line:
            raise SystemExit(f"malformed rust output line (no tab): {line!r}")
        key, value = line.split("\t", 1)
        if key in result:
            raise SystemExit(f"duplicate key from rust: {key}")
        result[key] = value
    return result


def values_agree(a: str, b: str) -> bool:
    """Compare two battery values field-by-field.

    Values are pipe-separated records of key=value pairs. Each field's value
    (after the '=') is compared as a float (with abs+rel tolerance for
    1-2 ULP summation-order noise) when both sides parse as floats,
    otherwise as exact text.
    """
    fa = a.split("|")
    fb = b.split("|")
    if len(fa) != len(fb):
        return False
    for x, y in zip(fa, fb):
        # Extract value after '=' if present
        xv = x.split("=", 1)[1] if "=" in x else x
        yv = y.split("=", 1)[1] if "=" in y else y
        try:
            fx, fy = float(xv), float(yv)
            if fx != fy and abs(fx - fy) > max(1e-9 * max(abs(fx), abs(fy)), 1e-12):
                return False
        except ValueError:
            if x != y:
                return False
    return True


def describe_value(v: str) -> str:
    try:
        f = float(v)
    except ValueError:
        return repr(v)
    return f"{v!r} ({f!r})"


def main(argv: List[str]) -> int:
    if len(argv) > 1:
        binary = argv[1]
    else:
        binary = shutil.which(BINARY_NAME) or ""
    if not binary or not os.path.exists(binary):
        raise SystemExit(
            f"usage: parity_measurements.py <path-to-parity_measurements>\n"
            f"(the Rust executable built from "
            f"crates/parity/src/bin/parity_measurements.rs)"
        )

    fd, manifest = tempfile.mkstemp(prefix="wosp_parity_manifest_")
    try:
        # The measurements battery is pure-array; no fixture files needed.
        # Write an empty manifest (the Rust binary ignores it for this battery).
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("")

        py: Dict[str, str] = {}
        py.update(dict(battery()))
        rs = run_rust_battery(binary, manifest)
    finally:
        if os.path.exists(manifest):
            os.remove(manifest)

    only_py = sorted(set(py) - set(rs))
    only_rs = sorted(set(rs) - set(py))
    mismatch = sorted(k for k in set(py) & set(rs) if not values_agree(py[k], rs[k]))

    if not (only_py or only_rs or mismatch):
        print(f"PARITY OK — {len(py)} values identical between "
              f"bridge/measurements.py and crates/wowkispice-core/src/measurements.rs")
        return 0

    print("PARITY FAILED: bridge/measurements.py and "
          "crates/wowkispice-core/src/measurements.rs disagree\n")
    if only_py:
        print(f"keys only in Python ({len(only_py)}):")
        for k in only_py[:40]:
            print(f"  {k} = {describe_value(py[k])}")
        print()
    if only_rs:
        print(f"keys only in Rust ({len(only_rs)}):")
        for k in only_rs[:40]:
            print(f"  {k} = {describe_value(rs[k])}")
        print()
    if mismatch:
        print(f"values that differ ({len(mismatch)}):")
        for k in mismatch[:60]:
            print(f"  {k}\n      python {describe_value(py[k])}\n      rust   {describe_value(rs[k])}")
        print()
    print(f"{len(mismatch)} differing, {len(only_py)} python-only, "
          f"{len(only_rs)} rust-only out of {len(set(py) | set(rs))} keys")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
