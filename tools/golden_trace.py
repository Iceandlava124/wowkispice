"""
golden_trace.py - Golden trace regression testing
"""
import os
import json
import numpy as np
from pathlib import Path
from typing import Dict, Any


GOLDEN_DIR = Path(__file__).parent.parent / "tests" / "golden"


class GoldenTrace:
    def __init__(self, name: str):
        self.name = name
        self.golden_path = GOLDEN_DIR / f"{name}.npz"
        self.meta_path = GOLDEN_DIR / f"{name}.json"
        
    def save(self, time, traces: Dict[str, list], metadata: Dict[str, Any] = None):
        """Save golden trace"""
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(self.golden_path, time=np.array(time), **{k: np.array(v) for k,v in traces.items()})
        meta = metadata or {}
        meta['name'] = self.name
        with open(self.meta_path, 'w') as f:
            json.dump(meta, f, indent=2)
        print(f"Saved golden trace to {self.golden_path}")
        
    def load(self):
        """Load golden trace"""
        if not self.golden_path.exists():
            return None, None
        data = np.load(self.golden_path)
        time = data['time'].tolist()
        traces = {k: data[k].tolist() for k in data.keys() if k != 'time'}
        meta = {}
        if self.meta_path.exists():
            with open(self.meta_path) as f:
                meta = json.load(f)
        return time, traces, meta
        
    def compare(self, time, traces, tolerances=None):
        """Compare traces against golden"""
        tolerances = tolerances or {'voltage': 0.02, 'time': 0.01}
        golden_time, golden_traces, meta = self.load()
        if golden_time is None:
            return False, ["No golden trace found"]
        
        errors = []
        # Check time points
        if abs(len(time) - len(golden_time)) > max(1, len(golden_time) * 0.1):
            errors.append(f"Time point count differs: {len(time)} vs {len(golden_time)}")
        
        # Check traces
        for name in golden_traces:
            if name not in traces:
                errors.append(f"Missing trace: {name}")
                continue
            g = np.array(golden_traces[name])
            t = np.array(traces[name][:len(g)])
            if len(t) != len(g):
                errors.append(f"Trace length differs for {name}")
                continue
            rel_err = np.max(np.abs((t - g) / (np.abs(g) + 1e-9)))
            if rel_err > tolerances['voltage']:
                errors.append(f"Trace {name} exceeds tolerance: {rel_err:.4f}")
        
        return len(errors) == 0, errors
