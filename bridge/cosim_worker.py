"""
cosim_worker.py - process-isolated ngspice co-simulation worker.

Layer 3: ngspice is a process-global C library that can abort the interpreter
(Fatal Python error: Segmentation fault) on some systems during a transient
with `external` sources. A C-level abort cannot be caught by Python try/except.
This worker runs ONE simulation in a child process so a crash is contained:
the parent sees a non-zero exit and returns a structured error instead of
losing the whole test/CI process.

The parent writes the netlist, law specs, and options to a JSON file; the
child writes a complete CosimRun-shaped JSON result (including law histories)
to an output file so the parent can reconstruct a faithful result object.

Usage:
  python bridge/cosim_worker.py <input.json> <output.json>
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bridge import cosim_runner
from bridge.control_law import make_law


def main(in_path, out_path):
    with open(in_path, encoding="utf-8") as fh:
        payload = json.load(fh)

    # Lightweight model shim: the parent already compiled the netlist, so we
    # inject those lines directly and avoid recompiling.
    class NetlistModel:
        def __init__(self, lines, nets):
            self._lines, self._nets = lines, nets

        def compile_netlist(self, **kwargs):
            return list(self._lines), list(self._nets), []

    model = NetlistModel(payload["netlist"], payload["nets"])
    run = cosim_runner.run_cosim(
        model, payload["laws"],
        vin=payload.get("vin", 12.0),
        tstep_us=payload.get("tstep_us", 0.5),
        duration_ms=payload.get("duration_ms", 5.0),
        probe_nets=payload.get("probe_nets"),
    )
    laws = {}
    for pin, law in run.laws.items():
        laws[pin] = {
            "spec": law.spec,
            "pin": law.pin,
            "sense_net": law.sense_net,
            "level": law.level,
            "switch_count": law.switch_count,
            "history_time": law.history_time,
            "history_pin": law.history_pin,
            "history_counts": law.history_counts,
        }
    result = {
        "warnings": run.warnings,
        "callback_hits": run.callback_hits,
        "aborted": run.aborted,
        "time": run.time,
        "traces": run.traces,
        "netlist": run.netlist,
        "nets": run.nets,
        "laws": laws,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
