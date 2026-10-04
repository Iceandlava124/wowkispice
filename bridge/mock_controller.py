"""
mock_controller.py - Mock MCU firmware running closed-loop hysteretic control
Uses high-performance native ngspice C callbacks (GetVSRCData / GetSyncData)
for zero-overhead mixed-signal co-simulation.
"""

import os
import sys
import ctypes
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, List, Any

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.ngspice_wrapper import (
    NgSpiceEngine, GetVSRCData_t, GetISRCData_t, GetSyncData_t
)


class MockESP32BuckController:
    """
    Simulates ESP32 firmware:
    - Input: Feedback voltage from a 2:1 resistive divider (V_feedback = V_out / 2)
    - ADC: 12-bit (0..4095 counts for 0..3.3V)
    - Target: Calibrated for 3.30V average steady-state output accounting for inductor discharge
    - Output: GPIO 0V / 3.3V
    """
    def __init__(self, target_vout: float = 3.24, hyst_vout: float = 0.02, divider_ratio: float = 0.5, adc_vref: float = 3.30):
        self.target_vout = target_vout
        self.hyst_vout = hyst_vout
        self.divider_ratio = divider_ratio
        self.adc_vref = adc_vref
        
        # Feedback voltage thresholds
        v_fb_target = target_vout * divider_ratio
        v_fb_low = (target_vout - hyst_vout) * divider_ratio
        v_fb_high = (target_vout + hyst_vout) * divider_ratio
        
        # 12-bit ADC threshold counts (0..4095)
        self.adc_low = int((v_fb_low / adc_vref) * 4095.0)
        self.adc_high = int((v_fb_high / adc_vref) * 4095.0)
        
        self.gpio_state = False  # False = 0V (LOW), True = 3.3V (HIGH)
        self.latest_vout = 0.0
        self.latest_fb = 0.0
        self.switch_count = 0
        
        # Telemetry history
        self.history_time = []
        self.history_vout = []
        self.history_vgate = []

    def on_sync(self, actual_time: float, p_delta_t: Any, old_delta_t: float, redostep: int, ident: int, location: int, user_data: Any) -> int:
        """Called by ngspice at every transient calculation step."""
        try:
            if location == 1 and redostep == 0:
                v_ptr = engine.lib.ngGet_Vec_Info(b'vout')
                if v_ptr:
                    v = v_ptr.contents
                    if bool(v.v_realdata) and v.v_length > 0:
                        val = float(v.v_realdata[v.v_length - 1])
                        self.latest_vout = val
                        self.history_time.append(actual_time)
                        self.history_vout.append(val)
                        self.history_vgate.append(3.3 if self.gpio_state else 0.0)
                # Feedback node is the divider output the ADC actually samples.
                # Read it from the solver so the divider's loading on vout, and
                # its own dynamics, are part of the solution rather than a
                # constant multiplied in afterwards.
                fb_ptr = engine.lib.ngGet_Vec_Info(b'fb')
                if fb_ptr:
                    fb = fb_ptr.contents
                    if bool(fb.v_realdata) and fb.v_length > 0:
                        self.latest_fb = float(fb.v_realdata[fb.v_length - 1])
        except Exception:
            pass
        return 0

    def on_vsrc(self, v_ret: Any, actual_time: float, name: str, ident: int, user_data: Any) -> int:
        """
        Called by ngspice whenever it evaluates the external voltage source (Vgate).
        Executes the exact hysteretic decision logic that the compiled C firmware runs.
        """
        try:
            # Feedback comes from the simulated divider node. This is what the
            # ADC pin sees, including the effect of Rfb_top/Rfb_bot loading
            # vout. divider_ratio is no longer applied here.
            v_feedback = self.latest_fb
            
            # 12-bit ADC quantization (0..3.3V -> 0..4095)
            raw_adc = int(np.clip((v_feedback / self.adc_vref) * 4095.0, 0, 4095))
            
            old_state = self.gpio_state
            if raw_adc < self.adc_low:
                self.gpio_state = True   # Turn MOSFET ON (Charge inductor)
            elif raw_adc > self.adc_high:
                self.gpio_state = False  # Turn MOSFET OFF (Freewheel diode)
                
            if self.gpio_state != old_state:
                self.switch_count += 1
                
            v_ret[0] = 3.3 if self.gpio_state else 0.0
        except Exception:
            v_ret[0] = 0.0
        return 0


def run_closed_loop_simulation(
    total_time_ms: float = 5.0,
    tstep_us: float = 0.5,
    save_plot: bool = True,
    plot_path: str = "tests/buck_converter_response.png"
) -> Dict[str, Any]:
    """
    Run high-speed closed-loop co-simulation between Mock ESP32 and ngspice Buck Converter.
    """
    global engine
    cir_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "circuits", "buck_converter.cir")
    
    print(f"=== Starting High-Speed Closed-Loop Co-Simulation ===")
    print(f"Circuit: {cir_path}")
    print(f"Total time: {total_time_ms} ms, Resolution: {tstep_us} us")
    
    controller = MockESP32BuckController(target_vout=3.24, hyst_vout=0.02, divider_ratio=0.5)
    
    c_vsrc = GetVSRCData_t(controller.on_vsrc)
    c_isrc = GetISRCData_t(lambda v, t, n, i, u: 0)
    c_sync = GetSyncData_t(controller.on_sync)
    
    engine = NgSpiceEngine(verbose=False)
    ident = ctypes.c_int(0)
    engine.lib.ngSpice_Init_Sync(c_vsrc, c_isrc, c_sync, ctypes.byref(ident), None)
    
    engine.load_circuit_file(cir_path)
    
    # Run transient analysis
    tran_cmd = f"tran {tstep_us}u {total_time_ms}m uic"
    engine.cmd(tran_cmd)
    
    time_arr = np.array(controller.history_time) * 1000.0  # ms
    vout_arr = np.array(controller.history_vout)
    vgate_arr = np.array(controller.history_vgate)
    
    if len(time_arr) == 0:
        raise RuntimeError("Simulation did not produce any data points.")
    
    # Steady-state metrics (last 60% of timeline)
    steady_mask = time_arr >= (total_time_ms * 0.4)
    steady_vout = vout_arr[steady_mask]
    avg_vout = float(np.mean(steady_vout))
    ripple_p2p = float(np.max(steady_vout) - np.min(steady_vout))

    print(f"\n=== Simulation Results ===")
    print(f"Total synchronized steps:   {len(time_arr)}")
    print(f"Total switch transitions:   {controller.switch_count}")
    print(f"Average Steady-State Vout:  {avg_vout:.4f} V (Target: 3.3000 V)")
    print(f"Peak-to-Peak Output Ripple: {ripple_p2p*1000:.1f} mV")

    if save_plot:
        os.makedirs(os.path.dirname(os.path.abspath(plot_path)), exist_ok=True)
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
        
        ax1.plot(time_arr, vout_arr, 'b-', label='V(out) [Simulated]', linewidth=1.5)
        ax1.axhline(3.30, color='r', linestyle='--', label='Target Output (3.30V)')
        ax1.set_ylabel('Output Voltage (V)')
        ax1.set_title('Closed-Loop Co-Simulation: ESP32 Hysteretic Buck Converter (12V -> 3.3V)')
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='upper right')
        
        ax2.plot(time_arr, vgate_arr, 'g-', label='V(gate) [ESP32 GPIO]', linewidth=1.2)
        ax2.set_ylabel('Gate Logic (V)')
        ax2.set_xlabel('Time (ms)')
        ax2.set_ylim(-0.5, 4.0)
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper right')
        
        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()
        print(f"Waveform plot saved to: {plot_path}")

    return {
        "time": time_arr,
        "vout": vout_arr,
        "vgate": vgate_arr,
        "avg_vout": avg_vout,
        "ripple_p2p": ripple_p2p,
        "switch_count": controller.switch_count
    }


if __name__ == "__main__":
    run_closed_loop_simulation()
