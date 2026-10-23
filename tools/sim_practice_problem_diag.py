"""
Quick diagnostic: list available vectors in the ngspice plot.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.ngspice_wrapper import NgSpiceEngine

netlist = [
    "* Practice Problem 7.12 verification",
    "* Current source 6 A, parallel: 10 ohm, 5 ohm + 1.5 H inductor",
    "* The switch opens at t = 0, putting the 10 ohm back into the circuit.",
    "I1 1 0 DC 6",
    "R1 1 0 10",
    "R2 2 0 5",
    "L1 1 2 1.5",
    ".tran 10u 0.3m uic",
    ".end",
]

engine = NgSpiceEngine(verbose=False)
engine.load_circuit(netlist)
engine.cmd("run")

# List all vectors available via ngGet_Vec_Info
import ctypes

ptr = engine.lib.ngGet_Vec_Info(b"time")
if ptr:
    vec = ptr.contents
    print(f"time: type={vec.v_type}, length={vec.v_length}")
    if vec.v_realdata:
        print(f"  first 5 real values: {list(vec.v_realdata[:5])}")
else:
    print("time: NOT FOUND")

# Try some common node names
for name in [b"out", b"1", b"2", b"iL1", b"iL", b"n1", b"n2"]:
    ptr = engine.lib.ngGet_Vec_Info(name)
    if ptr:
        vec = ptr.contents
        print(f"{name.decode()}: type={vec.v_type}, length={vec.v_length}")
        if vec.v_realdata:
            print(f"  first 5 real values: {list(vec.v_realdata[:5])}")
    else:
        print(f"{name.decode()}: NOT FOUND")

# Check running
print(f"Running: {engine.lib.ngSpice_running()}")
print(f"Output logs ({len(engine.output_logs)} entries):")
for log in engine.output_logs[-20:]:
    print(f"  {log}")
