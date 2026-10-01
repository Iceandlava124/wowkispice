"""
test_components_library.py - Verification suite for reverse-engineered component models
Tests:
1. DC Brushed Motor transient spin-up and Back-EMF generation
2. LM358 Op-Amp non-inverting amplifier closed-loop gain
"""

import os
import sys
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.ngspice_wrapper import NgSpiceEngine


def test_dc_motor_model():
    print("\n=======================================================")
    print(" [TEST] DC Brushed Motor & Back-EMF Subcircuit Model   ")
    print("=======================================================")
    
    lib_path = os.path.abspath("circuits/components/models.lib")
    
    netlist = [
        "* DC Motor Step-Response Test",
        f".include \"{lib_path}\"",
        "Vmotor in 0 DC 12.0",
        "X1 in 0 speed_node DC_MOTOR_MODEL",
        ".tran 200u 100m uic",
        ".end"
    ]
    
    engine = NgSpiceEngine(verbose=False)
    engine.load_circuit(netlist)
    engine.cmd("run")
    
    speed_arr = engine.get_vector_array("speed_node")
    final_speed = speed_arr[-1]
    
    print(f"  Rotor Speed at 100ms: {final_speed:.2f} rad/s (Expected ~190-240 rad/s)")
    assert final_speed > 150.0, f"Motor did not accelerate (speed: {final_speed})"
    print("  [PASS] Motor mechanical acceleration & Back-EMF verified!")


def test_opamp_model():
    print("\n=======================================================")
    print(" [TEST] LM358 Op-Amp Closed-Loop Gain Model            ")
    print("=======================================================")
    
    lib_path = os.path.abspath("circuits/components/models.lib")
    
    # Non-inverting op-amp with Gain = 1 + (R2 / R1) = 1 + (10k / 10k) = 2.0
    netlist = [
        "* Op-Amp Non-Inverting Gain Test",
        f".include \"{lib_path}\"",
        "Vin in 0 DC 1.50",
        "Vcc vcc 0 DC 5.0",
        "X1 in fb vcc 0 vout OPAMP_LM358",
        "R1 fb 0 10k",
        "R2 vout fb 10k",
        ".tran 10u 1m uic",
        ".end"
    ]
    
    engine = NgSpiceEngine(verbose=False)
    engine.load_circuit(netlist)
    engine.cmd("run")
    
    vout_arr = engine.get_vector_array("vout")
    final_vout = vout_arr[-1]
    
    print(f"  Input: 1.50V | Gain Target: 2.0x | Output: {final_vout:.4f}V")
    assert 2.90 <= final_vout <= 3.10, f"OpAmp gain unexpected (got {final_vout:.4f}V)"
    print("  [PASS] LM358 Op-Amp linear closed-loop gain verified!")


if __name__ == "__main__":
    test_dc_motor_model()
    test_opamp_model()
    print("\n>>> ALL REVERSE-ENGINEERED COMPONENT TESTS PASSED! <<<\n")
