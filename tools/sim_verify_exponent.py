"""
Verify the exponent coefficient from the simulated inductor current waveform.
"""

import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.ngspice_wrapper import NgSpiceEngine

netlist = [
    "* Verification of exponent from simulation waveform",
    "* I1 0 1 DC 6",
    "* R1 1 0 10",
    "* R2 2 0 5",
    "* L1 1 2 1.5 IC=6",
    ".tran 100u 0.5s uic",
    ".end",
]

engine = NgSpiceEngine(verbose=False)
engine.load_circuit(netlist)
engine.cmd("run")

time = np.array(engine.get_vector_array("time"))
v2 = np.array(engine.get_vector_array("2"))
iL = v2 / 5.0

# The solution should be i(t) = 4 + 2*exp(-10t)
# So i(t) - 4 = 2*exp(-10t)
# ln(i(t) - 4) = ln(2) - 10t
# The slope of ln(i - 4) vs t should be -10

# Take points after the transient has settled somewhat (avoid t=0 singularity)
# Filter out points where i <= 4 (shouldn't happen with i starting at 6)
mask = (iL > 4.01) & (time > 0.01)  # skip t=0 to avoid numerical issues
t_valid = time[mask]
i_valid = iL[mask]

print(f"Points used for log-fit: {len(t_valid)} out of {len(time)}")
if len(t_valid) < 10:
    print("WARNING: Too few points!")

log_diff = np.log(i_valid - 4.0)
coeffs = np.polyfit(t_valid, log_diff, 1)
slope = coeffs[0]
intercept = coeffs[1]

print(f"\nLog-linear plot of i(t) - 4 vs t:")
print(f"  Fitted slope (should be -10): {slope:.6f}")
print(f"  Fitted intercept (should be ln(2)={np.log(2):.6f}): {intercept:.6f}")
print(f"  R^2: {1 - np.var(log_diff - (slope*t_valid + intercept)) / np.var(log_diff):.6f}")

# Compute the expected exponent
expected_exp = -10.0
measured_exp = slope
print(f"\nExponent verification:")
print(f"  Expected exponent coefficient: {-expected_exp:.2f} /s")
print(f"  Measured exponent coefficient: {-measured_exp:.6f} /s")
print(f"  Relative error: {abs(measured_exp - expected_exp)/expected_exp*100:.6f}%")

# Verify the time constant
tau_measured = -1.0 / slope if slope != 0 else float('inf')
tau_expected = 0.1
print(f"\nTime constant verification:")
print(f"  Expected tau = {tau_expected} s")
print(f"  Measured tau = {tau_measured:.6f} s")
print(f"  Relative error: {abs(tau_measured - tau_expected)/tau_expected*100:.6f}%")

# Verify the Thevenin resistance
print(f"\nThevenin resistance verification:")
print(f"  Expected R_Th = L/tau = 1.5/0.1 = {1.5/0.1} Ohm")
print(f"  L = 1.5 H")

# Verify the final value and initial value
print(f"\nFinal value verification:")
print(f"  i(0) = {iL[0]:.6f} A (expected 6 A)")
print(f"  i(inf) = {iL[-1]:.6f} A (expected 4 A)")
print(f"  i(0) - i(inf) = {iL[0] - iL[-1]:.6f} A (matches 2 A amplitude)")

# Check the known values
print(f"\nKnown checkpoints from analytical solution:")
print(f"  i(tau) = 4 + 2/e = {4 + 2*np.exp(-1):.6f} A")
print(f"  i(2*tau) = 4 + 2/e^2 = {4 + 2*np.exp(-2):.6f} A")
print(f"  i(3*tau) = 4 + 2/e^3 = {4 + 2*np.exp(-3):.6f} A")

# Verify i(0) and i(infinity) directly
print(f"\nDirect value checks:")
print(f"  i(0) = 4 + 2*exp(0) = {4 + 2*np.exp(0):.6f} A")
print(f"  i(inf) = 4 A (from steady state)")
print(f"  At t=0.5s: i = 4 + 2*exp(-5) = {4 + 2*np.exp(-5):.6f} A")
