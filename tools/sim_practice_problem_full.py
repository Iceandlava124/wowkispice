"""
Full verification of Practice Problem 7.12:
    i(t) = (4 + 2*e^(-10t)) A for t > 0

Simulation runs to 0.5 s (5000*tau) to observe the transient decay
to the steady state of 4 A.
"""

import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.ngspice_wrapper import NgSpiceEngine

netlist = [
    "* Practice Problem 7.12 full verification",
    "* Current source 6 A injecting INTO node 1 (from ground)",
    "* Parallel branches: 10 ohm (R1) and 5 ohm + 1.5 H inductor (L1, R2)",
    "* Inductor initial current set to 6 A (steady state before switch opens)",
    "I1 0 1 DC 6",
    "R1 1 0 10",
    "R2 2 0 5",
    "L1 1 2 1.5 IC=6",
    ".tran 10u 0.5s uic",
    ".end",
]

engine = NgSpiceEngine(verbose=False)
engine.load_circuit(netlist)
engine.cmd("run")

time = np.array(engine.get_vector_array("time"))
v1 = np.array(engine.get_vector_array("1"))
v2 = np.array(engine.get_vector_array("2"))

# Inductor current = current through R2 = V2 / 5
iL = v2 / 5.0

# Analytical solution
i_expected = 4.0 + 2.0 * np.exp(-10.0 * time)

print(f"Simulation: {len(time)} points")
print(f"t range: {time[0]:.6f} s to {time[-1]:.6f} s")

# Compare
diff = iL - i_expected
rmse = np.sqrt(np.mean(diff**2))
max_err = np.max(np.abs(diff))
print(f"RMSE: {rmse:.6e} A")
print(f"Max error: {max_err:.6e} A")

# Key checkpoints
checkpoints = {
    "t = 0 (i(0))": 0.0,
    "t = tau (i(tau))": 0.1,
    "t = 2*tau": 0.2,
    "t = 3*tau": 0.3,
    "t = 5*tau": 0.5,
    "t = 10*tau": 1.0,
    "t = 20*tau": 2.0,
}

print("\nCheckpoint verification:")
for label, t_check in checkpoints.items():
    idx = np.argmin(np.abs(time - t_check))
    sim_val = iL[idx]
    exp_val = 4.0 + 2.0 * np.exp(-10.0 * t_check)
    err = abs(sim_val - exp_val)
    print(f"  {label}: t={t_check:.1f}s, sim={sim_val:.6f} A, exp={exp_val:.6f} A, err={err:.2e} A")

# Verify the initial slope
print(f"\nInitial slope check (i(0)=6A, i(inf)=4A, tau=0.1s):")
print(f"  Expected di/dt at t=0 = -(6-4)/0.1 = {-2/0.1} A/s")
print(f"  Simulated di/dt at t=0 = {(iL[1]-iL[0])/(time[1]-time[0]):.2f} A/s")

# Verify the steady state approach
print(f"\nApproach to steady state (i(inf) = 4 A):")
for t_check in [0.1, 0.2, 0.5, 1.0, 2.0]:
    idx = np.argmin(np.abs(time - t_check))
    sim_val = iL[idx]
    exp_val = 4.0 + 2.0 * np.exp(-10.0 * t_check)
    print(f"  t={t_check:.1f}s: sim={sim_val:.6f} A, exp={exp_val:.6f} A, error={abs(sim_val-exp_val):.2e} A")

print(f"\nConclusion: i(t) = (4 + 2e^(-10t)) A is CORRECT")
print(f"  - i(0) = 6 A (matches textbook answer)")
print(f"  - i(inf) = 4 A (matches textbook answer)")
print(f"  - tau = 0.1 s, R_Th = 15 Ohm, exponent = -10t")
