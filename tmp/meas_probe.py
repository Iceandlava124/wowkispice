import os, sys
sys.path.insert(0, os.path.abspath("."))
from bridge.ngspice_wrapper import NgSpiceEngine
lines = [
    "* rc lp",
    "V1 in 0 DC 0 SIN(0 5 1k)",
    "R1 in out 1k",
    "C1 out 0 1u",
    ".tran 10u 5m",
    ".meas tran vout_max MAX v(out)",
    ".meas tran vout_at_1m FIND v(out) AT=1m",
    ".meas tran vout_pp PP v(out)",
    ".end",
]
ng = NgSpiceEngine(verbose=False)
ng.load_circuit(lines)
ng.cmd("run")
times = ng.get_vector_array("time")
print("points:", len(times) if times else 0)
print("--- output_logs lines mentioning meas/---")
for l in ng.output_logs:
    if "meas" in l.lower() or ":" in l:
        print(repr(l))
