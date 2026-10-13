"""
prove_physics_engine.py - Irrefutable Live Proof of ngspice.dll C Solver Execution
Demonstrates to a skeptical reviewer that:
1. ngspice.dll is physically loaded into RAM with real OS memory pointers.
2. Arbitrary, non-hardcoded circuit parameters (R, C, L, Vin generated dynamically)
   are compiled into SPICE netlists on the fly.
3. Raw IEEE-754 double-precision floats are extracted directly from C memory pointers.
4. Simulated voltages match theoretical ODEs point-by-point across the entire time series.
5. 2nd-Order Underdamped RLC Ringing matches both the exact damped frequency
   omega_d and the envelope decay rate alpha.

Every proof is a hard gate: if a measurement cannot be taken, the script raises
rather than printing a clean summary. A proof that cannot fail proves nothing.
"""

import os
import sys
import time
import ctypes
import numpy as np

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.ngspice_wrapper import NgSpiceEngine


RLC_FREQ_TOLERANCE = 0.03       # 3% on the damped frequency
RLC_ENVELOPE_TOLERANCE = 0.10   # 10% on the decay rate
RLC_MIN_PEAKS = 5               # enough ringing extrema to average a period over


def prove_ngspice_execution():
    print("=" * 80)
    print(" [PROOF 1] C-API DLL IN-MEMORY POINTER INSPECTION")
    print("=" * 80)
    
    engine = NgSpiceEngine(verbose=False)
    dll_handle = engine.lib._handle
    print(f" [+] ngspice.dll physical OS handle:     0x{dll_handle:016X}")
    print(f" [+] ngSpice_Init C function address:   0x{ctypes.cast(engine.lib.ngSpice_Init, ctypes.c_void_p).value:016X}")
    print(f" [+] ngSpice_Command function address:  0x{ctypes.cast(engine.lib.ngSpice_Command, ctypes.c_void_p).value:016X}")
    print(f" [+] ngGet_Vec_Info function address:   0x{ctypes.cast(engine.lib.ngGet_Vec_Info, ctypes.c_void_p).value:016X}")

    print("\n" + "=" * 80)
    print(" [PROOF 2] DYNAMIC RANDOM RC CIRCUIT (Zero Hardcoding Possible)")
    print("=" * 80)
    
    # Generate completely non-hardcoded, arbitrary random parameters using system timer entropy
    entropy_seed = int(time.perf_counter_ns() % 100000)
    np.random.seed(entropy_seed)
    
    r_val = float(np.random.uniform(1200.0, 8500.0))    # e.g. 3842.1 Ohm
    c_val = float(np.random.uniform(0.5e-6, 4.7e-6))    # e.g. 2.13 uF
    vin = float(np.random.uniform(3.5, 18.0))           # e.g. 11.74 V
    
    tau = r_val * c_val
    duration = 5.0 * tau
    tstep = tau / 100.0
    
    print(f" [*] Dynamic Random Parameters (Seed = {entropy_seed}):")
    print(f"     - Resistor R1:        {r_val:.2f} Ohm")
    print(f"     - Capacitor C1:       {c_val*1e6:.3f} uF")
    print(f"     - Step Input Vin:     {vin:.2f} V")
    print(f"     - Time Constant Tau:  {tau*1000:.3f} ms")
    print(f"     - Total Sim Duration: {duration*1000:.3f} ms (5 Tau)")

    netlist = [
        f"* Dynamic Proof Circuit - Seed {entropy_seed}",
        f"Vstep in 0 PWL(0 0 1u {vin:.4f})",
        f"R1 in out {r_val:.4f}",
        f"C1 out 0 {c_val*1e6:.6f}u IC=0",
        f".tran {tstep*1e6:.2f}u {duration*1000:.3f}m uic",
        ".end"
    ]

    print("\n [*] Feeding generated SPICE netlist into ngspice.dll:")
    for line in netlist:
        print(f"     > {line}")

    engine.load_circuit(netlist)
    engine.cmd("run")

    # Read raw C pointer from ngspice memory
    vec_ptr = engine.lib.ngGet_Vec_Info(b"out")
    raw_addr = ctypes.cast(vec_ptr, ctypes.c_void_p).value
    v_info = vec_ptr.contents
    data_buffer_addr = ctypes.cast(v_info.v_realdata, ctypes.c_void_p).value

    print(f"\n [+] ngspice C VectorInfo struct returned at RAM address: 0x{raw_addr:016X}")
    print(f" [+] Raw float64 vector data pointer in C heap:         0x{data_buffer_addr:016X}")
    print(f" [+] Total integration time steps solved by ngspice:     {v_info.v_length}")

    time_vec = np.array(engine.get_vector_array("time"))
    vout_sim = np.array(engine.get_vector_array("out"))

    # Compute independent analytical ODE: V(t) = Vin * (1 - exp(-t / tau))
    vout_analytical = vin * (1.0 - np.exp(-time_vec / tau))
    residuals = np.abs(vout_sim - vout_analytical)
    rmse = np.sqrt(np.mean(residuals**2))
    max_err = np.max(residuals)

    print("\n [*] Sampling 5 Points Across the Transient Time Series:")
    print(f"     {'Time (ms)':>10} | {'SPICE Solved (V)':>16} | {'Analytical ODE (V)':>18} | {'Error (mV)':>12}")
    print("     " + "-" * 62)
    sample_indices = np.linspace(0, len(time_vec) - 1, 6, dtype=int)[1:]
    for idx in sample_indices:
        t_ms = time_vec[idx] * 1000.0
        v_sp = vout_sim[idx]
        v_an = vout_analytical[idx]
        err_mv = abs(v_sp - v_an) * 1000.0
        print(f"     {t_ms:10.3f} | {v_sp:16.4f} | {v_an:18.4f} | {err_mv:12.3f}")

    print(f"\n [+] Root-Mean-Square Error (RMSE) across all {len(time_vec)} steps: {rmse*1000:.3f} mV")
    print(f" [+] Maximum Absolute Error: {max_err*1000:.3f} mV "
          f"({max_err / vin * 100:.4f}% of full scale)")
    assert len(time_vec) > 100, "Proof 2 produced too few time points to compare"
    assert rmse < 0.02, "Physics solver deviation exceeded tolerance!"
    print(" [+] PROOF 2 VERIFIED: ngspice.dll dynamically solved the analytical 1st-order ODE!")

    print("\n" + "=" * 80)
    print(" [PROOF 3] 2ND-ORDER UNDERDAMPED RLC RINGING FREQUENCY PROOF")
    print("=" * 80)

    # Series RLC tank. R is chosen so the damping ratio is zeta ~= 0.25: high
    # enough that the response is genuinely underdamped and rings for several
    # visible cycles, low enough that the ringing is not swamped by the decay.
    # (R = 5 Ohm gives zeta = 0.79, which is nearly critically damped - there is
    # no ringing there to measure, which is exactly what the detector below
    # reports.)
    r_rlc = 1.6
    l_rlc = 100.0e-6     # 100 uH
    c_rlc = 10.0e-6      # 10 uF
    step_v = 5.0

    # Analytical predictions
    w0 = 1.0 / np.sqrt(l_rlc * c_rlc)      # natural angular freq = 31622.8 rad/s
    alpha = r_rlc / (2.0 * l_rlc)          # envelope decay rate      = 8000 Np/s
    zeta = alpha / w0
    wd = np.sqrt(w0**2 - alpha**2)         # damped angular freq = 30595.0 rad/s
    fd_expected = wd / (2.0 * np.pi)       #                          = 4869.2 Hz

    print(f" [*] RLC Tank: R = {r_rlc} Ohm, L = {l_rlc*1e6:.0f} uH, C = {c_rlc*1e6:.0f} uF")
    print(f"     - Damping Ratio (zeta):                    {zeta:.3f} (< 1, underdamped)")
    print(f"     - Undamped Natural Frequency (f0):        {w0/(2*np.pi):.1f} Hz")
    print(f"     - Theoretical Damped Ringing (fd):         {fd_expected:.1f} Hz")
    print(f"     - Theoretical Envelope Decay (alpha):      {alpha:.1f} Np/s")

    rlc_netlist = [
        "* 2nd-Order Underdamped RLC Proof",
        f"Vstep in 0 PWL(0 0 1u {step_v})",
        f"R1 in n1 {r_rlc}",
        f"L1 n1 out {l_rlc*1e6:.1f}u IC=0",
        f"C1 out 0 {c_rlc*1e6:.1f}u IC=0",
        ".tran 0.5u 2m uic",
        ".end"
    ]

    engine.load_circuit(rlc_netlist)
    engine.cmd("run")

    t_rlc = np.array(engine.get_vector_array("time"))
    v_rlc = np.array(engine.get_vector_array("out"))

    # Detect the ringing relative to where the circuit finally settles.
    #
    # An absolute voltage threshold is the trap here: once the tank has settled
    # at 5 V, the solver's last-bit numerical ripple still produces local maxima
    # and minima spaced at the ringing period, so a naive peak detector happily
    # "measures" the frequency of solver noise on a flat line. Requiring each
    # extremum to deviate from the settled value makes that impossible.
    settled = float(np.median(v_rlc[-max(2, len(v_rlc) // 10):]))
    tol = 0.01 * abs(settled)
    diffs = np.diff(v_rlc)
    maxima = np.where((diffs[:-1] > 0) & (diffs[1:] < 0))[0] + 1
    minima = np.where((diffs[:-1] < 0) & (diffs[1:] > 0))[0] + 1
    extrema = sorted(
        [(float(t_rlc[i]), float(v_rlc[i])) for i in maxima if v_rlc[i] > settled + tol]
        + [(float(t_rlc[i]), float(v_rlc[i])) for i in minima if v_rlc[i] < settled - tol]
    )

    if len(extrema) < RLC_MIN_PEAKS:
        raise AssertionError(
            f"Proof 3 could not be evaluated: only {len(extrema)} ringing extrema "
            f"deviating more than {tol:.3f} V from the settled value {settled:.4f} V "
            f"in {len(v_rlc)} samples (need {RLC_MIN_PEAKS}). The ringing was never "
            f"measured, so nothing is proven.")

    t_ex = np.array([e[0] for e in extrema])
    a_ex = np.array([abs(e[1] - settled) for e in extrema])
    half_period = float(np.mean(np.diff(t_ex)))     # consecutive extrema are half a period
    measured_fd = 1.0 / (2.0 * half_period)
    freq_error_pct = abs(measured_fd - fd_expected) / fd_expected * 100.0

    print(f"\n [+] Detected {len(extrema)} ringing extrema in SPICE solver "
          f"(settled value {settled:.4f} V).")
    print(f" [+] Measured Ringing Frequency from Extrema Spacing: {measured_fd:.1f} Hz")
    print(f" [+] Analytical Mathematical Damped Frequency:        {fd_expected:.1f} Hz")
    print(f" [+] Frequency Discrepancy:                           {freq_error_pct:.2f}% "
          f"(Target < {RLC_FREQ_TOLERANCE * 100:.1f}%)")
    assert freq_error_pct < RLC_FREQ_TOLERANCE * 100, \
        "2nd-order RLC frequency deviation too high!"
    print(" [+] PROOF 3a VERIFIED: damped angular frequency matches theory.")

    # The envelope must decay at alpha as well. Without this, a solver could get
    # the oscillation period right while ignoring the damping entirely.
    envelope_alpha = float(np.log(a_ex[0] / a_ex[-1]) / (t_ex[-1] - t_ex[0]))
    envelope_error_pct = abs(envelope_alpha - alpha) / alpha * 100.0
    print(f" [+] Measured Envelope Decay alpha:                   {envelope_alpha:.1f} Np/s")
    print(f" [+] Analytical Envelope Decay alpha:                 {alpha:.1f} Np/s")
    print(f" [+] Envelope Decay Discrepancy:                      {envelope_error_pct:.2f}% "
          f"(Target < {RLC_ENVELOPE_TOLERANCE * 100:.0f}%)")
    assert envelope_error_pct < RLC_ENVELOPE_TOLERANCE * 100, \
        "RLC envelope decay does not match the theoretical damping!"
    print(" [+] PROOF 3 VERIFIED: ngspice.dll solved both the frequency AND the "
          "damping of a 2nd-order system.")

    print("\n" + "=" * 80)
    print(" [SUMMARY] ALL 3 INDEPENDENT PHYSICAL PROOFS PASSED WITH ZERO HARDCODING")
    print("=" * 80)


if __name__ == "__main__":
    prove_ngspice_execution()
