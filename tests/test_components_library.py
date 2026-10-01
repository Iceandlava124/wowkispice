"""
test_components_library.py - Verification suite for reverse-engineered component models
"""

import os
import sys
import unittest
import numpy as np

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.ngspice_wrapper import NgSpiceEngine


class TestComponentsLibrary(unittest.TestCase):
    def test_dc_motor_model(self):
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
        self.assertGreater(final_speed, 150.0, f"Motor did not accelerate (speed: {final_speed})")

    def test_opamp_model(self):
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
        self.assertTrue(2.90 <= final_vout <= 3.10, f"OpAmp gain unexpected (got {final_vout:.4f}V)")


if __name__ == "__main__":
    unittest.main()
