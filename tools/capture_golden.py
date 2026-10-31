"""
capture_golden.py - Capture golden reference traces
"""
import os
import sys
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.cad_engine import SchematicNetlistEngine, SchematicComponent
from bridge import cosim_runner
from bridge import control_law
from tools.golden_trace import GoldenTrace


def capture_buck_regulation():
    """Capture golden trace for buck regulation"""
    print("Capturing buck regulation golden trace...")
    
    g = SchematicNetlistEngine()
    g.add_component(SchematicComponent("V1", "V", "V1", "12", -160, 0))
    g.add_component(SchematicComponent("S1", "SWITCH", "S1", "", 0, 0))
    g.add_component(SchematicComponent("D1", "D", "D1", "", 60, 60))
    g.add_component(SchematicComponent("L1", "L", "L1", "47u", 120, 0))
    g.add_component(SchematicComponent("C1", "C", "C1", "100u", 200, 0))
    g.add_component(SchematicComponent("R1", "R", "R1", "10", 260, 0))
    g.add_component(SchematicComponent("GND1", "GND", "GND", "", 0, 160))
    g.add_component(SchematicComponent("U1", "MCU", "U1", "ESP32", -260, 0))
    g.add_wire("V1:+", "S1:1", "in")
    g.add_wire("V1:-", "GND1:1", "gnd")
    g.add_wire("S1:2", "L1:1", "sw_node")
    g.add_wire("L1:2", "C1:1", "vout")
    g.add_wire("C1:2", "R1:1", "NET_LOAD")
    g.add_wire("R1:2", "GND1:1", "gnd")
    g.add_wire("D1:A", "GND1:1", "gnd")
    g.add_wire("D1:K", "S1:2", "sw_node")
    g.add_wire("U1:GPIO18", "S1:CTRL", "gate")
    
    laws = {"GPIO18": {
        "kind": "hysteretic",
        "sense_net": "vout",
        "low_v": 3.24 - 0.02,
        "high_v": 3.24 + 0.02,
        "vref": 3.3,
        "divider": 0.5,
    }}
    
    run = cosim_runner.run_cosim(g, laws, vin=12.0, tstep_us=0.5, duration_ms=5.0)
    
    traces = {k: v for k, v in run.traces.items()}
    # Add pin traces
    for pin, law in run.laws.items():
        if law.history_pin:
            traces[f"{pin}_pin"] = law.history_pin
    
    gt = GoldenTrace("buck_regulation")
    gt.save(run.time, traces, {"description": "Buck converter hysteretic regulation"})
    print(f"✓ Captured {len(run.time)} points")


if __name__ == "__main__":
    capture_buck_regulation()
