"""
Simulate Practice Problem 7.12 circuit to verify the textbook answer:
    i(t) = (4 + 2*e^(-10t)) A for t > 0

Reconstructed circuit (from transcription):
  - 6 A DC current source (rightmost vertical branch, pointing up)
  - 10 Ohm resistor (rightmost vertical branch)
  - 1.5 H inductor (top wire)
  - 5 Ohm resistor (left branch) in series with the inductor
  - Switch in parallel with the 10 Ohm resistor, opens at t = 0

After the switch opens, the 6 A source feeds the parallel combination of:
  - 10 ohm (branch 1)
  - 5 ohm + 1.5 H inductor (branch 2)

The inductor sees R_Th = 5 + 10 = 15 Ohm, so tau = L/R = 1.5/15 = 0.1 s,
and the exponent is -t/0.1 = -10t.
i(0) = 6 A (all current through inductor before switch opens)
i(inf) = 4 A (current through 5 ohm + short inductor = 20/5 = 4 A)
"""

import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.ngspice_wrapper import NgSpiceEngine

# Build the netlist for the t > 0 circuit (switch open, i.e. 10 ohm in circuit)
# I1 0 1 DC 6 : current flows from ground (0) to node 1, i.e. 6 A INTO node 1
netlist = [
    "* Practice Problem 7.12 verification",
    "* Current source 6 A injecting INTO node 1 (from ground)",
    "* Parallel branches: 10 ohm (R1) and 5 ohm + 1.5 H inductor (L1, R2)",
    "* Inductor initial current set to 6 A (steady state before switch opens)",
    "I1 0 1 DC 6",
    "R1 1 0 10",
    "R2 2 0 5",
    "L1 1 2 1.5 IC=6",
    ".tran 0.01u 0.5m uic",
    ".end",
]

engine = NgSpiceEngine(verbose=False)
engine.load_circuit(netlist)
engine.cmd("run")

time = np.array(engine.get_vector_array("time"))
print(f"Simulation: {len(time)} points")
print(f"t range: {time[0]:.6f} s to {time[-1]:.6f} s")

# Check node voltages
v1 = np.array(engine.get_vector_array("1"))
v2 = np.array(engine.get_vector_array("2"))
print(f"Node 1 voltage [0]: {v1[0]:.4f} V")
print(f"Node 2 voltage [0]: {v2[0]:.4f} V")

# The inductor current is the same as the current through R2
# i_R2 = (V2 - 0) / 5, so i_L = V2 / 5
iL = v2 / 5.0

# Analytical solution
i_expected = 4.0 + 2.0 * np.exp(-10.0 * time)

print("\nFirst few sample points (t, simulated, expected):")
for i in range(min(5, len(time))):
    print(f"  t={time[i]:.4f}s: sim={iL[i]:.4f} A, expected={i_expected[i]:.4f} A")

# Compare
diff = iL - i_expected
rmse = np.sqrt(np.mean(diff**2))
max_err = np.max(np.abs(diff))

print(f"\nRMSE: {rmse:.6f} A")
print(f"Max error: {max_err:.6f} A")
print(f"Mean abs error: {np.mean(np.abs(diff)):.6f} A")

# Check i(0) and i(infinity)
print(f"\nCheck i(0) = {iL[0]:.4f} A (expected 6 A)")
print(f"Check i(inf) = {iL[-1]:.4f} A (expected 4 A)")

# Time constant check
tau = 0.1  # seconds
idx = np.argmin(np.abs(time - tau))
print(f"At t = tau = {tau} s: sim={iL[idx]:.4f} A, expected={4 + 2*np.exp(-1):.4f} A")

# Verify the exponent coefficient: -R/L = -10
# Take a point where the transient is small
steady_idx = len(time) // 2
print(f"\nExponent check at t = {time[steady_idx]:.4f} s:")
print(f"  Simulated i = {iL[steady_idx]:.4f} A")
print(f"  Expected i = {i_expected[steady_idx]:.4f} A")
print(f"  Ratio over 1ms step = {iL[steady_idx+100]/iL[steady_idx]:.6f}")
print(f"  Expected ratio = {np.exp(-10*0.001):.6f}")

# Verify initial slope: di/dt at t=0 should be -(i(0) - i(inf))/tau = -2/0.1 = -20 A/s
# Check the first few points
print(f"\nInitial slope check:")
for i in range(1, 5):
    if i < len(time):
        dt = time[i] - time[i-1]
        slope = (iL[i] - iL[i-1]) / dt
        print(f"  t={time[i]:.4f}s: di/dt = {slope:.2f} A/s")
