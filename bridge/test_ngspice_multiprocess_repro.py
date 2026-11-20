"""Reproduce the ngspice C-abort: multiple engines in one process."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.ngspice_wrapper import NgSpiceEngine

LIB = os.environ.get("WOSP_NGSPICE_LIB")

def run_one(load):
    netlist = [
        f"* load {load}",
        "Vstep in 0 PWL(0 0 1u 5)",
        "R1 in out 1000",
        f"C1 out 0 {load}u IC=0",
        ".tran 1u 1m uic",
        ".end",
    ]
    e = NgSpiceEngine()
    e.load_circuit(netlist)
    e.cmd("run")
    v = e.get_vector_array("out")
    print(f"  load={load}: {len(v)} points, final={v[-1] if v else None}")
    del e

print("Creating multiple engines in ONE process (like the load-sweep test)...")
for load in (1, 2, 3):
    run_one(load)
print("MULTI-ENGINE OK")
