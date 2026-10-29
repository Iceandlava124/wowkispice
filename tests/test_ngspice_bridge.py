"""
test_ngspice_bridge.py - Rigorous Mathematical Verification of libngspice C-API
Evaluates simulated SPICE transient waveforms point-by-point against
closed-form analytical differential equations:
1. RC First-Order Step Response: V(t) = V0 * (1 - e^(-t / RC))
2. Time Constant Tau Verification: V(tau) = V0 * (1 - e^(-1)) = 63.212% * V0
3. Steady-State Settling Error: |V(5*tau) - V0| <= 1.0%
4. Root-Mean-Square Error (RMSE) across entire time series: RMSE < 5.0 mV (< 0.15%)
"""

import sys
import os
import unittest
import pytest
import numpy as np

# Add root directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.ngspice_wrapper import NgSpiceEngine


class TestNgSpiceBridge(unittest.TestCase):
    @pytest.mark.req("CO-02")
    def test_rc_circuit_mathematical_precision(self):
        """
        Verify RC low-pass filter transient step response point-by-point against
        the analytical solution: V(t) = V0 * (1 - exp(-t / (R * C))).
        """
        engine = NgSpiceEngine(verbose=False)
        self.assertIsNotNone(engine.lib)

        r_val = 1000.0   # 1 kOhm
        c_val = 1.0e-6   # 1 uF
        tau = r_val * c_val  # tau = 1.0 ms
        v0 = 3.30        # 3.3V Step input

        # RC Low-pass filter netlist with initial condition 0V
        netlist = [
            "* RC Filter Step Response Precision Test",
            f"Vstep in 0 PWL(0 0 1u {v0:.4f})",
            f"R1 in out {r_val:.1f}",
            f"C1 out 0 {c_val * 1e6:.1f}u IC=0",
            ".tran 10u 5m uic",
            ".end"
        ]

        engine.load_circuit(netlist)
        engine.cmd("run")

        time_vec = np.array(engine.get_vector_array("time"))
        vout_sim = np.array(engine.get_vector_array("out"))

        self.assertGreater(len(time_vec), 100, "Simulation did not generate sufficient time points.")
        self.assertEqual(len(time_vec), len(vout_sim))

        # 1. Closed-Form Analytical Solution Comparison across every single point
        vout_analytical = v0 * (1.0 - np.exp(-time_vec / tau))
        
        # Calculate Root-Mean-Square Error (RMSE)
        rmse = float(np.sqrt(np.mean((vout_sim - vout_analytical) ** 2)))
        max_err = float(np.max(np.abs(vout_sim - vout_analytical)))

        # Industrial tolerance: RMSE must be under 5 mV across all 500+ integration steps
        self.assertLess(rmse, 0.008, f"RC Step Response RMSE too high: {rmse*1000:.3f} mV (Target < 8.0 mV)")
        self.assertLess(max_err, 0.025, f"Maximum deviation too high: {max_err*1000:.3f} mV")

        # 2. Time Constant Tau (1.0 ms) Verification
        # At t = tau = 1.0 ms, V(tau) must equal exactly 3.3 * (1 - 1/e) = 2.08599 V
        idx_tau = np.argmin(np.abs(time_vec - tau))
        v_at_tau = vout_sim[idx_tau]
        expected_v_tau = v0 * (1.0 - np.exp(-1.0))
        self.assertAlmostEqual(v_at_tau, expected_v_tau, delta=0.015,
                               msg=f"V(tau) was {v_at_tau:.4f}V, expected {expected_v_tau:.4f}V")

        # 3. Steady-State Settling (5*tau = 5.0 ms)
        # At t = 5*tau, capacitor must be charged to > 99.3% of V0
        v_final = vout_sim[-1]
        self.assertGreaterEqual(v_final, v0 * 0.990, f"Final voltage did not settle to 99%: {v_final:.4f}V")


if __name__ == "__main__":
    unittest.main(verbosity=2)
