"""
cross_tool_validation.py - Layer 1 external-tool correlation.

Compares the WOWKISPICE Julia solver against an independent SPICE-class solver
(ngspice) on the same RC circuit. Both must agree with each other AND with the
closed-form analytic solution. This is the external-validation evidence that
self-consistency tests cannot provide.

Usage:
  python bridge/julia/cross_tool_validation.py
"""
import json
import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from bridge.ngspice_wrapper import NgSpiceEngine

R = 1000.0
C = 1e-6
VIN = 5.0
TSTOP = 0.001
TAU = R * C
ANALYTIC = VIN * (1 - math.exp(-TSTOP / TAU))
TOL = 5e-3  # 5 mV agreement tolerance between solvers


def run_ngspice():
    netlist = [
        "* RC cross-tool correlation",
        f"Vstep in 0 PWL(0 0 1u {VIN})",
        f"R1 in out {R}",
        f"C1 out 0 {C*1e6:.1f}u IC=0",
        f".tran 1u {TSTOP} uic",
        ".end",
    ]
    engine = NgSpiceEngine(verbose=False)
    engine.load_circuit(netlist)
    engine.cmd("run")
    v = engine.get_vector_array("out")
    if not v:
        raise RuntimeError("ngspice returned no output")
    return float(v[-1])


def run_julia():
    payload = {
        "circuit": {"type": "rc", "resistance": R, "capacitance": C, "input_voltage": VIN},
        "simulation": {"dt": 1e-7, "tstop": TSTOP, "method": "auto", "tolerance": 1e-8},
    }
    proc = subprocess.run(
        ["julia", "--project=bridge/julia", "bridge/julia/solve_julia.jl", json.dumps(payload)],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"julia failed: {proc.stderr}")
    result = json.loads(proc.stdout)
    if result.get("status") != "success":
        raise RuntimeError(f"julia solver error: {result}")
    return float(result["final_vout"])


def main():
    ng = run_ngspice()
    ju = run_julia()
    print(f"analytic = {ANALYTIC:.9f} V")
    print(f"ngspice  = {ng:.9f} V  (err={abs(ng-ANALYTIC):.2e})")
    print(f"julia    = {ju:.9f} V  (err={abs(ju-ANALYTIC):.2e})")
    print(f"inter-tool difference = {abs(ng-ju):.2e} V (tol={TOL})")

    assert abs(ng - ANALYTIC) < TOL, "ngspice disagrees with analytic"
    assert abs(ju - ANALYTIC) < TOL, "julia disagrees with analytic"
    assert abs(ng - ju) < TOL, "julia and ngspice disagree"
    print("CROSS-TOOL VALIDATION PASSED")


if __name__ == "__main__":
    main()
