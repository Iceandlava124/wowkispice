"""
Debug available vectors for the 0.5s simulation.
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

# List all vectors
import ctypes

print("Available vectors:")
ptr = engine.lib.ngGet_Vec_Info(b"time")
if ptr:
    vec = ptr.contents
    print(f"  time: type={vec.v_type}, length={vec.v_length}")

# Try some common names
for name in [b"1", b"2", b"time", b"out", b"n1", b"n2", b"iL1", b"iL", b"iL(t)"]:
    ptr = engine.lib.ngGet_Vec_Info(name)
    if ptr:
        vec = ptr.contents
        print(f"  {name.decode()}: type={vec.v_type}, length={vec.v_length}")
    else:
        print(f"  {name.decode()}: NOT FOUND")

v1 = np.array(engine.get_vector_array("1"))
print(f"\nnode 1: shape={v1.shape}, first 3 = {v1[:3]}, last 3 = {v1[-3:]}")

# For the inductor current, compute from node voltage
# iL = (V1 - V2)/L for the inductor branch... wait, the inductor is from node 1 to node 2
# And R2 is from node 2 to ground
# So V2 is the voltage at node 2, and iL = i_R2 = V2/5
# But we need V2!
# Alternative: iL is also the current through the inductor
# vL = V1 - V2, iL = vL / (L * s) ... but that's frequency domain

# Let me try: the current through the inductor is the same as the current through R2
# i_R2 = V2/R2, but we don't have V2.
# However, we can compute V2 = V1 - L*di/dt, but that's complex.

# Actually, let's check if there are other vectors in the plot
# The default ngspice plot might only have "time" and "1" and "2"
# But maybe "2" isn't being plotted because we didn't specify it

# Let's try .print or .plot
# Actually, let's check by probing node voltages manually
# The inductor current = current through R2 = (V2 - 0)/5 = V2/5
# We should add .print 2 to the netlist

print("\nTreating the issue:")
print("We need to add .print 2 or similar to capture node 2 voltage.")
print("Let's use a .print statement in the netlist.")
