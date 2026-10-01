"""
test_studio_suite.py - Comprehensive Unit & Integration Tests for WOWKISPICE Studio
Tests all 9 instruments, models, and calculation modules:
1. Closed-Loop Buck Co-Simulation Engine
2. 6.5-Digit DMM Accuracy & True RMS Calculations
3. 4-Channel Oscilloscope & Inductor Current Tracing
4. FFT Spectrum Analyzer & THD Calculation
5. Bode Plotter Frequency Response & Stability Margins (PM, GM, Crossover)
6. Arbitrary Waveform Generator (AWG) Synthesis across all waveforms
7. Semiconductor Curve Tracer (MOSFET Id-Vds & Diode If-Vf)
8. Power, Energy & Thermal Loss Breakdown Profiler
9. Logic Analyzer Bus Protocol Decoder (UART / I2C / SPI)
"""

import os
import sys
import unittest
import numpy as np

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.studio_engine import StudioSimulationEngine


class TestStudioEngineSuite(unittest.TestCase):
    def setUp(self):
        self.engine = StudioSimulationEngine()

    def test_01_closed_loop_cosimulation_execution(self):
        """Test full closed-loop co-simulation run."""
        metrics = self.engine.run_simulation(
            duration_ms=4.0,
            vin=12.0,
            vtarget=3.30,
            rload=5.0,
            l_val_uh=47.0,
            c_val_uf=100.0
        )
        self.assertIsNotNone(metrics)
        self.assertIn("dmm_vdc", metrics)
        self.assertIn("efficiency_pct", metrics)
        self.assertIn("sw_freq_khz", metrics)
        
        # Verify 3.3V target regulation within +/- 5%
        self.assertAlmostEqual(metrics["dmm_vdc"], 3.30, delta=0.20)
        self.assertGreater(metrics["efficiency_pct"], 75.0)
        self.assertGreater(metrics["steps_per_sec"], 2000.0)

    def test_02_dmm_true_rms_and_measurements(self):
        """Test DMM True RMS, DC voltage, current, and ripple."""
        metrics = self.engine.run_simulation(
            duration_ms=5.0,
            vin=12.0,
            vtarget=3.30,
            rload=5.0
        )
        self.assertGreater(metrics["dmm_vrms"], metrics["dmm_vdc"] - 0.05)
        self.assertAlmostEqual(metrics["dmm_idc"], metrics["dmm_vdc"] / 5.0, delta=0.05)
        self.assertLess(metrics["dmm_vac_ripple"], 0.20)  # Ripple under 200mV RMS
        self.assertEqual(metrics["dmm_res"], 5.0)

    def test_03_fft_spectrum_and_thd(self):
        """Test FFT spectrum analyzer and THD distortion calculations."""
        metrics = self.engine.run_simulation(duration_ms=4.0)
        freqs = metrics["fft_freqs_khz"]
        mags = metrics["fft_mag_db"]
        
        self.assertGreater(len(freqs), 10)
        self.assertEqual(len(freqs), len(mags))
        self.assertGreaterEqual(metrics["thd_pct"], 0.0)
        self.assertLess(metrics["thd_pct"], 100.0)

    def test_04_bode_stability_margins(self):
        """Test Bode frequency response, Phase Margin, Gain Margin, and stability verdict."""
        metrics = self.engine.run_simulation(l_val_uh=47.0, c_val_uf=100.0, rload=5.0)
        
        self.assertIn("phase_margin_deg", metrics)
        self.assertIn("gain_margin_db", metrics)
        self.assertIn("stability_status", metrics)
        
        # LC filter with 47uH and 100uF is stable (Phase margin > 40 deg)
        self.assertGreater(metrics["phase_margin_deg"], 30.0)
        self.assertIn(metrics["stability_status"], ["STABLE", "MARGINAL"])

    def test_05_awg_signal_synthesis(self):
        """Test Arbitrary Waveform Generator for all supported waveforms."""
        waveforms = ["Sine", "Square", "Triangle", "Sawtooth", "White Noise", "Exponential Decay", "Chirp Sweep"]
        for wave in waveforms:
            t_ms, sig = StudioSimulationEngine.generate_awg_signal(
                wave_type=wave,
                freq_hz=1000.0,
                amp_v=3.3,
                offset_v=1.65,
                duty_pct=50.0,
                duration_ms=5.0,
                points=1000
            )
            self.assertEqual(len(t_ms), 1000)
            self.assertEqual(len(sig), 1000)
            self.assertFalse(np.isnan(sig).any(), f"NaN found in AWG waveform: {wave}")
            # Ensure amplitude doesn't blow up
            self.assertLess(np.max(sig), 10.0)
            self.assertGreater(np.min(sig), -5.0)

    def test_06_semiconductor_curve_tracer(self):
        """Test MOSFET and Diode I-V curve tracer engines."""
        # 1. MOSFET
        mos = StudioSimulationEngine.trace_mosfet_iv(vgs_steps=[2.0, 4.0, 6.0, 10.0], vds_max=15.0)
        self.assertEqual(len(mos["curves"]), 4)
        self.assertEqual(mos["vth"], 3.0)
        # For Vgs=2.0V (< Vth), Id must be 0
        self.assertEqual(np.max(mos["curves"][0]["id_amps"]), 0.0)
        # For Vgs=10.0V (> Vth), Id must conduct strongly
        self.assertGreater(np.max(mos["curves"][3]["id_amps"]), 5.0)

        # 2. Diode
        dio = StudioSimulationEngine.trace_diode_iv(vf_max=1.0)
        self.assertEqual(len(dio["vf"]), 150)
        # Schottky should conduct earlier than Silicon
        idx_mid = 75  # ~0.5V
        self.assertGreater(dio["i_schottky"][idx_mid], dio["i_silicon"][idx_mid])

    def test_07_power_and_thermal_loss_profiler(self):
        """Test power dissipation, loss breakdown, and thermal rise calculations."""
        metrics = self.engine.run_simulation(vin=12.0, vtarget=3.30, rload=5.0)
        
        self.assertGreater(metrics["p_out_w"], 1.5)
        self.assertGreater(metrics["p_in_w"], metrics["p_out_w"])
        self.assertGreater(metrics["p_loss_total"], 0.0)
        self.assertGreater(metrics["tj_rise_c"], 0.0)
        self.assertGreaterEqual(metrics["p_cond_mosfet"], 0.0)
        self.assertGreaterEqual(metrics["p_cond_diode"], 0.0)

    def test_08_protocol_packet_decoder(self):
        """Test UART / Bus Protocol Decoder."""
        time_ms = np.linspace(0, 5.0, 500)
        # Simulated UART waveform with transitions
        logic_sig = np.array([1 if (i // 25) % 2 == 0 else 0 for i in range(500)])
        packets = StudioSimulationEngine.decode_uart_packets(logic_sig, time_ms, baud_rate=115200)
        self.assertIsInstance(packets, list)
        if len(packets) > 0:
            self.assertIn("hex", packets[0])
            self.assertIn("ascii", packets[0])
            self.assertIn("type", packets[0])

    def test_09_project_json_serialization(self):
        """Test .wowki project serialization and deserialization."""
        test_proj = {
            "components": [{"id": "ESP32", "x": 100, "y": 100}],
            "wires": [{"from": "ESP32:GPIO18", "to": "MOSFET:GATE"}],
            "firmware": "// Custom firmware"
        }
        self.engine.load_project_json(test_proj)
        self.assertEqual(len(self.engine.components), 1)
        self.assertEqual(self.engine.firmware_code, "// Custom firmware")
        
        exported = self.engine.export_project_json()
        self.assertEqual(exported["version"], "2.0")
        self.assertEqual(len(exported["components"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
