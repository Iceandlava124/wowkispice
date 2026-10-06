"""
test_ngspice_dll_proof.py - Automated gate for the ngspice.dll physics proof.

This is the test-suite counterpart to tools/prove_physics_engine.py. It runs
the same three hard-gated physics proofs through pytest so the DLL execution
proof becomes part of the automated qualification gate instead of only a manual
standalone demo.

The proof script is written to raise on any failure, so the test harness simply
calls it and treats a raised exception as a test failure. Each proof is also
available as a standalone test function for finer-grained reporting when a
single proof fails.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from tools.prove_physics_engine import (
    prove_ngspice_execution,
    RLC_FREQ_TOLERANCE,
    RLC_ENVELOPE_TOLERANCE,
)

from bridge.ngspice_wrapper import NgSpiceEngine


def _shared_ngspice_available():
    """Separate helper so the skip path is explicit in the test output."""
    try:
        NgSpiceEngine(verbose=False)
        return True
    except Exception:
        return False


def test_proof_script_runs_to_completion():
    """End-to-end gate: the proof harness exits cleanly with every proof verified.

    This is the automated equivalent of running `tools/prove_physics_engine.py`
    and checking that it does not raise.
    """
    if not _shared_ngspice_available():
        pytest.skip("ngspice.dll not available for physics proof")
    prove_ngspice_execution()


def _random_seed_from_timer():
    import time
    return int(time.perf_counter_ns() % 100000)


def test_proof2_dynamic_rc_circuit():
    """Prove ngspice.dll solves a dynamically-generated random RC circuit.

    Matches tools/prove_physics_engine.py [PROOF 2]: arbitrary, non-hardcoded
    R/C/Vin generated from timer entropy, then compared point-by-point against
    the analytical 1st-order ODE with RMSE < 20 mV.
    """
    if not _shared_ngspice_available():
        pytest.skip("ngspice.dll not available for physics proof")

    entropy_seed = _random_seed_from_timer()
    np.random.seed(entropy_seed)

    r_val = float(np.random.uniform(1200.0, 8500.0))
    c_val = float(np.random.uniform(0.5e-6, 4.7e-6))
    vin = float(np.random.uniform(3.5, 18.0))

    tau = r_val * c_val
    duration = 5.0 * tau
    tstep = tau / 100.0

    netlist = [
        f"* Dynamic Proof Circuit - Seed {entropy_seed}",
        f"Vstep in 0 PWL(0 0 1u {vin:.4f})",
        f"R1 in out {r_val:.4f}",
        f"C1 out 0 {c_val*1e6:.6f}u IC=0",
        f".tran {tstep*1e6:.2f}u {duration*1000:.3f}m uic",
        ".end",
    ]

    engine = NgSpiceEngine(verbose=False)
    engine.load_circuit(netlist)
    engine.cmd("run")

    time_vec = np.array(engine.get_vector_array("time"))
    vout_sim = np.array(engine.get_vector_array("out"))

    assert len(time_vec) > 100, "Proof 2 produced too few time points to compare"

    vout_analytical = vin * (1.0 - np.exp(-time_vec / tau))
    rmse = float(np.sqrt(np.mean((vout_sim - vout_analytical) ** 2)))
    max_err = float(np.max(np.abs(vout_sim - vout_analytical)))

    assert rmse < 0.02, (
        f"Physics solver deviation too high: RMSE={rmse*1000:.3f} mV "
        f"(max err {max_err*1000:.3f} mV, Vin={vin:.2f} V, seed={entropy_seed})"
    )


def test_proof3_underdamped_rlc_ringing():
    """Prove ngspice.dll solves both frequency AND damping of a 2nd-order RLC tank.

    Matches tools/prove_physics_engine.py [PROOF 3]:
      - measured damped ringing frequency within 3% of theory
      - measured envelope decay alpha within 10% of theory
    """
    if not _shared_ngspice_available():
        pytest.skip("ngspice.dll not available for physics proof")

    r_rlc = 1.6
    l_rlc = 100.0e-6
    c_rlc = 10.0e-6
    step_v = 5.0

    w0 = 1.0 / np.sqrt(l_rlc * c_rlc)
    alpha = r_rlc / (2.0 * l_rlc)
    zeta = alpha / w0
    wd = np.sqrt(w0**2 - alpha**2)
    fd_expected = wd / (2.0 * np.pi)

    netlist = [
        "* 2nd-Order Underdamped RLC Proof",
        f"Vstep in 0 PWL(0 0 1u {step_v})",
        f"R1 in n1 {r_rlc}",
        f"L1 n1 out {l_rlc*1e6:.1f}u IC=0",
        f"C1 out 0 {c_rlc*1e6:.1f}u IC=0",
        ".tran 0.5u 2m uic",
        ".end",
    ]

    engine = NgSpiceEngine(verbose=False)
    engine.load_circuit(netlist)
    engine.cmd("run")

    t_rlc = np.array(engine.get_vector_array("time"))
    v_rlc = np.array(engine.get_vector_array("out"))

    settled = float(np.median(v_rlc[-max(2, len(v_rlc) // 10):]))
    tol = 0.01 * abs(settled)

    diffs = np.diff(v_rlc)
    maxima = np.where((diffs[:-1] > 0) & (diffs[1:] < 0))[0] + 1
    minima = np.where((diffs[:-1] < 0) & (diffs[1:] > 0))[0] + 1

    extrema = sorted(
        [(float(t_rlc[i]), float(v_rlc[i])) for i in maxima if v_rlc[i] > settled + tol]
        + [(float(t_rlc[i]), float(v_rlc[i])) for i in minima if v_rlc[i] < settled - tol]
    )

    assert len(extrema) >= 5, (
        f"Proof 3 could not be evaluated: only {len(extrema)} ringing extrema "
        f"deviating more than {tol:.3f} V from settled {settled:.4f} V "
        f"in {len(v_rlc)} samples (need 5). Nothing is proven."
    )

    t_ex = np.array([e[0] for e in extrema])
    a_ex = np.array([abs(e[1] - settled) for e in extrema])
    half_period = float(np.mean(np.diff(t_ex)))
    measured_fd = 1.0 / (2.0 * half_period)
    freq_error_pct = abs(measured_fd - fd_expected) / fd_expected * 100.0

    assert freq_error_pct < RLC_FREQ_TOLERANCE * 100, (
        f"2nd-order RLC frequency deviation too high: "
        f"measured={measured_fd:.1f} Hz, expected={fd_expected:.1f} Hz, "
        f"error={freq_error_pct:.2f}% (target < {RLC_FREQ_TOLERANCE*100:.1f}%)"
    )

    envelope_alpha = float(np.log(a_ex[0] / a_ex[-1]) / (t_ex[-1] - t_ex[0]))
    envelope_error_pct = abs(envelope_alpha - alpha) / alpha * 100.0

    assert envelope_error_pct < RLC_ENVELOPE_TOLERANCE * 100, (
        f"RLC envelope decay does not match theoretical damping: "
        f"measured={envelope_alpha:.1f} Np/s, expected={alpha:.1f} Np/s, "
        f"error={envelope_error_pct:.2f}% (target < {RLC_ENVELOPE_TOLERANCE*100:.0f}%)"
    )
