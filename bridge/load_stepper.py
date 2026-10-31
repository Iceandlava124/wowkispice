"""
load_stepper.py - Configurable load-step injection for mid-simulation testing
"""
import time
from typing import Dict, List, Callable, Optional


class LoadStepper:
    """Dynamically step load resistor values during simulation"""
    
    def __init__(self, engine, load_component: str, steps: List[Dict]):
        """
        Args:
            engine: NgSpice engine instance
            load_component: Component name (e.g., 'Rload' or 'RL')
            steps: List of {'time_s': float, 'value': float, 'unit': 'ohm'}
        """
        self.engine = engine
        self.load_component = load_component
        self.steps = sorted(steps, key=lambda x: x['time_s'])
        self.applied = set()
        
    def check_and_apply(self, current_time_s: float):
        """Check if any load steps should be applied at current time"""
        for i, step in enumerate(self.steps):
            if i in self.applied:
                continue
            if current_time_s >= step['time_s']:
                try:
                    value = step['value']
                    unit = step.get('unit', 'ohm')
                    # Use alter command to change component value
                    cmd = f"alter {self.load_component} {value}{unit[0] if unit != 'ohm' else ''}"
                    if unit == 'ohm' and not str(value).endswith(('k', 'K', 'M', 'm')):
                        # ngspice accepts values like 5 or 5k
                        pass
                    self.engine.cmd(cmd)
                    self.applied.add(i)
                    return True
                except Exception as e:
                    print(f"Load step failed: {e}")
                    return False
        return False


def create_load_step_profile(base_load_ohm: float, step_times_s: List[float], 
                             step_multipliers: List[float]) -> List[Dict]:
    """Create a load step profile"""
    steps = []
    for t, mult in zip(step_times_s, step_multipliers):
        steps.append({
            'time_s': t,
            'value': base_load_ohm * mult,
            'unit': 'ohm'
        })
    return steps
