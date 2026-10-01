"""
Test script to verify ngspice ctypes wrapper with a simple RC circuit.
Demonstrates:
1. Loading netlist
2. Stepping transient simulation
3. Altering input voltage (simulating GPIO toggle: 0V -> 3.3V)
4. Reading back capacitor voltage (simulating ADC feedback)
"""

import sys
import os

# Add root directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.ngspice_wrapper import NgSpiceEngine


def test_rc_circuit():
    print("=== Testing ngspice ctypes wrapper on RC Circuit ===")
    
    engine = NgSpiceEngine(verbose=False)
    print("[OK] ngspice.dll initialized successfully!")

    # RC Low-pass filter netlist
    # Vgpio is our controlled input (simulating ESP32 GPIO pin)
    # R1 = 1k, C1 = 1uF (tau = 1ms)
    netlist = [
        "* RC Filter Test Circuit",
        "Vgpio in 0 0.0",
        "R1 in out 1k",
        "C1 out 0 1u IC=0",
        ".tran 10u 5m uic",
        ".end"
    ]

    print("\n[1] Loading netlist into ngspice...")
    engine.load_circuit(netlist)

    print("[2] Running initial transient simulation (Vgpio = 0V)...")
    engine.cmd("run")
    v_out_init = engine.get_node_voltage("out")
    print(f"    Initial V(out) = {v_out_init:.4f} V")

    print("\n[3] Simulating GPIO Pin Toggle (0V -> 3.3V) and re-running...")
    engine.alter_source_voltage("Vgpio", 3.3)
    engine.cmd("tran 10u 5m uic")
    
    v_out_final = engine.get_node_voltage("out")
    print(f"    Charged V(out) at 5ms = {v_out_final:.4f} V (Expected ~3.3V)")

    time_vec = engine.get_vector_array("time")
    out_vec = engine.get_vector_array("out")
    print(f"    Total simulation points collected: {len(time_vec)}")
    
    assert len(time_vec) > 0, "No time points recorded"
    assert v_out_final > 3.0, f"Expected V(out) > 3.0V, got {v_out_final}"
    
    print("\n>>> ALL CHECKS PASSED! ngspice ctypes bridge is fully functional. <<<\n")


if __name__ == "__main__":
    test_rc_circuit()
