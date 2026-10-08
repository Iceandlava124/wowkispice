import os, sys
sys.path.insert(0, os.path.abspath("."))
from bridge.ngspice_wrapper import NgSpiceEngine
lines = [
    "* rc lp",
    "V1 in 0 PULSE(0 5 1m 1u 1u 2m 10m)",
    "R1 in out 1k",
    "C1 out 0 1u",
    ".tran 20u 8m",
    ".meas tran vout_max MAX v(out)",
    ".meas tran vout_at_3m FIND v(out) AT=3m",
    ".end",
]
ng = NgSpiceEngine(verbose=False)
ng.load_circuit(lines)
ng.cmd("run")
times = ng.get_vector_array("time")
print("points:", len(times) if times else 0)
for l in ng.output_logs:
    print(repr(l))
print("--- after explicit meas cmd ---")
ng.cmd(".meas tran vout_min MIN v(out)")
for l in ng.output_logs[-6:]:
    print(repr(l))
