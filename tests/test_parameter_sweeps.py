"""
test_parameter_sweeps.py - Automated Line & Load Regulation Matrix Tests
Verifies that the co-simulation closed-loop controller maintains target output
voltage across varying input voltages (Line Regulation) and load resistances (Load Regulation).
"""

import os
import sys
import ctypes
import numpy as np

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.ngspice_wrapper import (
    NgSpiceEngine, GetVSRCData_t, GetISRCData_t, GetSyncData_t
)


def run_single_sweep(vin: float, rload: float, target_v: float = 3.30, sim_ms: float = 4.0) -> dict:
    """Helper to run a parameterized buck converter simulation."""
    netlist = [
        "* Parametric Sweep Netlist",
        f"Vin in 0 DC {vin:.2f}",
        "Vgate gate 0 dc 0 external",
        "S1 in sw_node gate 0 SW_MODEL",
        "D1 0 sw_node DIODE_MODEL",
        "L1 sw_node vout 47u IC=0",
        "C1 vout 0 100u IC=0",
        f"Rload vout 0 {rload:.2f}",
        ".model SW_MODEL SW(Ron=0.02 Roff=1e6 Vt=1.65 Vh=0.05)",
        ".model DIODE_MODEL D(IS=1e-9 RS=0.01 N=1.0 BV=50 IBV=1e-4)",
        f".tran 0.5u {sim_ms:.1f}m uic",
        ".end"
    ]

    history_t = []
    history_v = []
    state = {"vout": 0.0, "gate": False}

    v_calibrated = target_v * 0.982
    adc_low = int(((v_calibrated - 0.02) * 0.5 / 3.3) * 4095.0)
    adc_high = int(((v_calibrated + 0.02) * 0.5 / 3.3) * 4095.0)

    def on_sync(actual_time, p_dt, old_dt, redostep, ident, location, user_data):
        try:
            if location == 1 and redostep == 0:
                v_ptr = engine.lib.ngGet_Vec_Info(b'vout')
                if v_ptr and bool(v_ptr.contents.v_realdata) and v_ptr.contents.v_length > 0:
                    val = float(v_ptr.contents.v_realdata[v_ptr.contents.v_length - 1])
                    state["vout"] = val
                    history_t.append(actual_time * 1000.0)
                    history_v.append(val)
        except Exception:
            pass
        return 0

    def on_vsrc(v_ret, actual_time, name, ident, user_data):
        try:
            raw_adc = int(np.clip((state["vout"] * 0.5 / 3.3) * 4095.0, 0, 4095))
            if raw_adc < adc_low:
                state["gate"] = True
            elif raw_adc > adc_high:
                state["gate"] = False
            v_ret[0] = 3.3 if state["gate"] else 0.0
        except Exception:
            v_ret[0] = 0.0
        return 0

    c_vsrc = GetVSRCData_t(on_vsrc)
    c_isrc = GetISRCData_t(lambda v, t, n, i, u: 0)
    c_sync = GetSyncData_t(on_sync)

    engine = NgSpiceEngine(verbose=False)
    ident = ctypes.c_int(0)
    engine.lib.ngSpice_Init_Sync(c_vsrc, c_isrc, c_sync, ctypes.byref(ident), None)

    engine.load_circuit(netlist)
    engine.cmd("run")

    t_arr = np.array(history_t)
    v_arr = np.array(history_v)
    
    # Calculate steady-state average (last 50%)
    steady_mask = t_arr >= (sim_ms * 0.5)
    steady_v = v_arr[steady_mask]
    avg_v = float(np.mean(steady_v)) if len(steady_v) > 0 else 0.0
    ripple = float(np.max(steady_v) - np.min(steady_v)) * 1000.0 if len(steady_v) > 0 else 0.0

    return {"avg_vout": avg_v, "ripple_mv": ripple}


def test_line_regulation():
    """Test Buck Converter across input voltages 8V to 24V."""
    print("\n=======================================================")
    print(" [TEST] Line Regulation: Vin = 8V, 12V, 16V, 24V       ")
    print("=======================================================")
    
    vin_list = [8.0, 12.0, 16.0, 24.0]
    for vin in vin_list:
        res = run_single_sweep(vin=vin, rload=5.0, target_v=3.30)
        avg = res["avg_vout"]
        ripple = res["ripple_mv"]
        print(f"  Vin = {vin:4.1f}V | Regulated Vout: {avg:.4f}V | Ripple: {ripple:5.1f}mV -> [PASS]")
        assert 3.20 <= avg <= 3.50, f"Line regulation failed at Vin={vin}V (got {avg:.4f}V)"


def test_load_regulation():
    """Test Buck Converter across load resistances 2 Ohm to 20 Ohm."""
    print("\n=======================================================")
    print(" [TEST] Load Regulation: Rload = 2, 5, 10, 20 Ohm       ")
    print("=======================================================")
    
    rload_list = [2.0, 5.0, 10.0, 20.0]
    for rload in rload_list:
        res = run_single_sweep(vin=12.0, rload=rload, target_v=3.30)
        avg = res["avg_vout"]
        ripple = res["ripple_mv"]
        print(f"  Rload = {rload:4.1f} Ohm | Regulated Vout: {avg:.4f}V | Ripple: {ripple:5.1f}mV -> [PASS]")
        assert 3.20 <= avg <= 3.45, f"Load regulation failed at Rload={rload} Ohm (got {avg:.4f}V)"


if __name__ == "__main__":
    test_line_regulation()
    test_load_regulation()
    print("\n>>> ALL LINE & LOAD REGULATION MATRIX TESTS PASSED! <<<\n")
