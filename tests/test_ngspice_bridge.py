"""
test_ngspice_bridge.py - Test script to verify ngspice ctypes wrapper with a simple RC circuit.
"""

import sys
import os
import unittest

# Add root directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.ngspice_wrapper import NgSpiceEngine


class TestNgSpiceBridge(unittest.TestCase):
    def test_rc_circuit(self):
        engine = NgSpiceEngine(verbose=False)
        self.assertIsNotNone(engine.lib)

        # RC Low-pass filter netlist
        netlist = [
            "* RC Filter Test Circuit",
            "Vgpio in 0 0.0",
            "R1 in out 1k",
            "C1 out 0 1u IC=0",
            ".tran 10u 5m uic",
            ".end"
        ]

        engine.load_circuit(netlist)
        engine.cmd("run")
        v_out_init = engine.get_node_voltage("out")
        self.assertAlmostEqual(v_out_init, 0.0, delta=0.01)

        # Simulating GPIO Pin Toggle (0V -> 3.3V)
        engine.alter_source_voltage("Vgpio", 3.3)
        engine.cmd("tran 10u 5m uic")
        
        v_out_final = engine.get_node_voltage("out")
        time_vec = engine.get_vector_array("time")
        out_vec = engine.get_vector_array("out")

        self.assertGreater(len(time_vec), 0)
        self.assertGreater(v_out_final, 3.0)


if __name__ == "__main__":
    unittest.main()
