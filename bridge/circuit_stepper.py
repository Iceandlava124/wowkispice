"""
circuit_stepper.py - Stateful transient circuit stepper for ngspice
Manages continuous stepping of circuit physics and injection of digital control signals.
"""

import os
import sys
from typing import Dict, List, Tuple, Optional
from bridge.ngspice_wrapper import NgSpiceEngine


class CircuitStepper:
    def __init__(self, netlist_path: str, dt_step: float = 10e-6, verbose: bool = False):
        """
        :param netlist_path: Path to .cir netlist file
        :param dt_step: Time step size per simulation tick (seconds, e.g. 10 microseconds)
        """
        self.netlist_path = os.path.abspath(netlist_path)
        self.dt_step = dt_step
        self.current_time = 0.0
        self.current_gate_voltage = 0.0
        self.verbose = verbose
        
        self.engine = NgSpiceEngine(verbose=verbose)
        self._load_and_init()

    def _load_and_init(self):
        """Load netlist into ngspice engine."""
        self.engine.load_circuit_file(self.netlist_path)
        # Suppress interactive prompts/plots
        self.engine.cmd("set noaskquit")
        self.engine.cmd("set nomoremode")

    def set_gate_signal(self, logic_high: bool):
        """Set gate voltage (3.3V for HIGH, 0.0V for LOW)."""
        voltage = 3.3 if logic_high else 0.0
        if voltage != self.current_gate_voltage:
            self.current_gate_voltage = voltage
            self.engine.alter_source_voltage("Vgate", voltage)

    def step(self, num_steps: int = 1) -> Dict[str, float]:
        """
        Advance circuit simulation forward by (num_steps * dt_step) seconds.
        Returns latest measurements: {"time": t, "vout": vout, "vgate": vgate, "isw": isw, ...}
        """
        target_time = self.current_time + (num_steps * self.dt_step)
        
        # Step transient from current_time to target_time
        # In ngspice: tran <tstep> <tstop> [<tstart> [<tmax>]] [uic]
        # Using tstep = dt_step / 10 for fine numerical resolution
        tstep = self.dt_step / 10.0
        cmd_str = f"tran {tstep:e} {target_time:e} {self.current_time:e} uic"
        self.engine.cmd(cmd_str)
        
        self.current_time = target_time
        
        # Query node voltages
        vout = self.engine.get_node_voltage("vout")
        vgate = self.engine.get_node_voltage("gate")
        
        try:
            v_sw = self.engine.get_node_voltage("sw_node")
        except Exception:
            v_sw = 0.0
            
        return {
            "time": self.current_time,
            "vout": vout,
            "vgate": vgate,
            "sw_node": v_sw
        }

    def get_history(self) -> Dict[str, List[float]]:
        """Extract full vector arrays across entire simulation run."""
        time_vec = self.engine.get_vector_array("time")
        vout_vec = self.engine.get_vector_array("vout")
        gate_vec = self.engine.get_vector_array("gate")
        return {
            "time": time_vec,
            "vout": vout,
            "gate": gate_vec
        }
