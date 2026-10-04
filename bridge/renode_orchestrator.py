"""
renode_orchestrator.py - High-Level Mixed-Signal Co-Simulation Orchestrator

DEPRECATED / NOT AN EMULATOR DRIVER. The `--mode renode` branch below has
never executed this firmware: Renode cannot decode the Xtensa `entry`
instruction, which appears 393 times in an ordinary ESP-IDF build, and the
binary it would launch is gitignored. The emulator target is Espressif QEMU
now - see bridge/qemu_orchestrator.py.

Note that `--mode mock` and `--mode benchmark` (the only two modes CI and
docker-compose use) branch straight to bridge/mock_controller, a pure-Python
closed loop. Despite this file's name, neither mode touches Renode.

See docs/legacy-module-audit.md for the full record.
"""

import os
import sys
import time
import argparse
import subprocess
import numpy as np
import matplotlib.pyplot as plt

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.mock_controller import run_closed_loop_simulation


def main():
    parser = argparse.ArgumentParser(description="PROJECT_WOWKISPICE: Mixed-Signal Co-Simulation Platform")
    parser.add_argument("--mode", choices=["mock", "renode", "benchmark"], default="mock",
                        help="Simulation mode: 'mock' (fast python firmware), 'renode' (emulator), 'benchmark'")
    parser.add_argument("--time", type=float, default=5.0, help="Simulation duration in milliseconds (default: 5.0ms)")
    parser.add_argument("--tstep", type=float, default=0.5, help="Simulation time step in microseconds (default: 0.5us)")
    parser.add_argument("--plot", type=str, default="tests/buck_converter_response.png", help="Path to output plot image")
    args = parser.parse_args()

    print("======================================================================")
    print("      PROJECT_WOWKISPICE: Mixed-Signal Co-Simulator Engine            ")
    print("======================================================================")
    print(f" Mode:              {args.mode.upper()}")
    print(f" Duration:          {args.time} ms")
    print(f" Time Resolution:   {args.tstep} us")
    print(f" Circuit:           circuits/buck_converter.cir (12V -> 3.3V)")
    print("----------------------------------------------------------------------\n")

    t_start = time.perf_counter()

    if args.mode in ("mock", "benchmark"):
        results = run_closed_loop_simulation(
            total_time_ms=args.time,
            tstep_us=args.tstep,
            save_plot=True,
            plot_path=args.plot
        )
        
        t_elapsed = time.perf_counter() - t_start
        sim_time_s = args.time / 1000.0
        speed_ratio = sim_time_s / t_elapsed if t_elapsed > 0 else 0.0

        print("\n======================================================================")
        print("                       BENCHMARK & SUMMARY                            ")
        print("======================================================================")
        print(f" Real Wall-Clock Time:       {t_elapsed:.3f} seconds")
        print(f" Simulated Circuit Time:     {sim_time_s*1000:.1f} ms")
        print(f" Co-Simulation Speed Ratio:  {speed_ratio:.4f}x real-time")
        print(f" Output Waveform Saved:      {args.plot}")
        print("======================================================================\n")

    elif args.mode == "renode":
        print("Launching Renode co-simulation environment...")
        renode_exe = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools", "renode", "renode.exe")
        resc_script = os.path.join(os.path.dirname(__file__), "run_cosim.resc")
        
        if not os.path.exists(renode_exe):
            print(f"[ERROR] Renode binary not found at: {renode_exe}")
            return
        
        cmd = [renode_exe, "--plain", "-e", f"include @{resc_script}"]
        print(f"Executing: {' '.join(cmd)}")
        subprocess.run(cmd)


if __name__ == "__main__":
    main()
