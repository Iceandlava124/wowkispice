"""Smoke test for process-isolated co-sim: verifies a worker crash is contained."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge import cosim_runner

# A minimal model shim that emits a valid-looking netlist. On systems where
# libngspice crashes, the worker child dies but the PARENT must survive with
# a structured warning (this is the whole point of isolation).
class Model:
    def compile_netlist(self, **kwargs):
        return (["* smoke", "V1 in 0 DC 5", "R1 in 0 1000", ".end"],
                ["in"], [])

os.environ["WOSP_COSIM_ISOLATED"] = "1"
# 15s so the parent returns promptly even if the worker hangs
import bridge.cosim_runner as cr
_orig = cr.run_cosim_isolated
run = _orig(Model(), {"GPIO18": {"kind": "hysteretic", "target_v": 1.65}}, timeout_s=15)
print("PARENT SURVIVED")
print("warnings:", run.warnings)
print("callback_hits:", run.callback_hits)
