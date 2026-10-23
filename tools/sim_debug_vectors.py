"""
Debug vector shapes for the 0.5s simulation.
"""

import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.ngspice_wrapper import NgSpiceEngine

netlist = [
    "* Verification of exponent from simulation waveform",
    "* I1 0 1 DC 6",
    "* R1 1 0 10",
    "* R2 2 0 5",
    "* L1 1 2 1.5 IC=6",
    ".tran 100u 0.5s uic",
    ".end",
]

engine = NgSpiceEngine(verbose=False)
engine.load_circuit(netlist)
engine.cmd("run")

time = np.array(engine.get_vector_array("time"))
print(f"time: shape={time.shape}")

v2 = np.array(engine.get_vector_array("2"))
print(f"v2 (node 2): shape={v2.shape}, min={np.min(v2) if v2.size else None}, max={np.max(v2) if v2.size else None}")
print(f"v2 first 5: {v2[:5] if v2.size else 'empty'}")

# If v2 is empty, try to find the inductor current 
# The inductor current can be computed from V2/R2
if v2.size == 0:
    print("Node 2 vector is empty!")
    # Try alternative: use the current through R2
    # Or check other node names
    for name in ["n1", "n2", "out", "iL1"]:
        vec = engine.get_vector_array(name)
        print(f"  {name}: shape={vec.shape}")
else:
    iL = v2 / 5.0
    print(f"iL: shape={iL.shape}")
