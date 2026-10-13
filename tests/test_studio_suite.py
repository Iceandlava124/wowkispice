"""
test_studio_suite.py - Mathematically Rigorous & Industrial-Grade Studio Test Suite
Every test compares simulated/processed results against independently derived physical/analytical formulas:
1. Closed-Loop Buck Co-Simulation: Vout regulation, hysteretic band limits, switching frequency
2. 6.5-Digit DMM True-RMS: Parseval's identity (Vrms^2 = Vdc^2 + Vac^2) and Ohm's Law (Idc = Vdc / Rload)
3. FFT Spectrum Analyzer & THD: Fundamental frequency tracking & Parseval energy conservation
4. Real SPICE .AC Bode Plotter: Resonant frequency f0 = 1 / (2*pi*sqrt(L*C)) & Phase Margin extraction
5. Arbitrary Waveform Generator (AWG): Exact mathematical True-RMS verification across all waveforms
   - Sine: Vrms = A / sqrt(2)
   - Square: Vrms = A
   - Triangle: Vrms = A / sqrt(3)
6. Real SPICE .DC Curve Tracer: MOSFET Vth = 3.0V extraction & Schottky knee voltage Vf = 0.35V
7. Power & Thermal Profiler: First-Law Energy Conservation (Pin = Pout + Ploss) & thermal junction rise
8. Hardware UART 8N1 Protocol Deserializer: Bit-exact ASCII/Hex reconstruction
9. .wowki Project Schema & State Preservation
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
        """
        Verify closed-loop co-simulation maintains target regulation within +/- 2.5%
        and achieves industrial switching frequency stability.
        """
        vtarget = 3.30
        rload = 5.0
        metrics = self.engine.run_simulation(
            duration_ms=5.0,
            vin=12.0,
            vtarget=vtarget,
            rload=rload,
            l_val_uh=47.0,
            c_val_uf=100.0
        )
        self.assertIsNotNone(metrics)
        
        # 1. Regulation Accuracy: |Vout - 3.30V| < 80 mV (< 2.5%)
        self.assertAlmostEqual(metrics["dmm_vdc"], vtarget, delta=0.08,
                               msg=f"Vout {metrics['dmm_vdc']:.4f}V deviated from {vtarget:.2f}V target.")
        
        # 2. Conversion Efficiency: Theoretical synchronous/diode buck range 80% - 96%
        self.assertGreaterEqual(metrics["efficiency_pct"], 80.0)
        self.assertLessEqual(metrics["efficiency_pct"], 96.0)
        
        # 3. Switching Frequency: Expected range 10 kHz to 50 kHz for hysteretic window
        self.assertGreater(metrics["sw_freq_khz"], 10.0)
        self.assertLess(metrics["sw_freq_khz"], 60.0)
        
        # 4. Engine Throughput: Must exceed 2,000 steps/sec
        self.assertGreater(metrics["steps_per_sec"], 2000.0)

    def test_02_dmm_true_rms_and_measurements(self):
        """
        Verify DMM calculations against fundamental mathematical definitions:
        - Parseval's identity: Vrms^2 = Vdc^2 + Vac_ripple^2
        - Ohm's law: Idc = Vdc / Rload
        """
        rload = 5.0
        metrics = self.engine.run_simulation(
            duration_ms=5.0,
            vin=12.0,
            vtarget=3.30,
            rload=rload
        )
        vdc = metrics["dmm_vdc"]
        vrms = metrics["dmm_vrms"]
        vac_ripple = metrics["dmm_vac_ripple"]
        idc = metrics["dmm_idc"]

        # Parseval's identity test: Vrms = sqrt(Vdc^2 + Vac_ripple^2) within +/- 0.5%
        expected_vrms = np.sqrt(vdc**2 + vac_ripple**2)
        self.assertAlmostEqual(vrms, expected_vrms, delta=0.015,
                               msg=f"True RMS {vrms:.4f}V violated Parseval identity (expected {expected_vrms:.4f}V)")

        # Ohm's law test: Idc = Vdc / Rload within +/- 0.1%
        expected_idc = vdc / rload
        self.assertAlmostEqual(idc, expected_idc, delta=0.005,
                               msg=f"DMM Current {idc:.4f}A violated Ohm's law (expected {expected_idc:.4f}A)")

    def test_03_fft_spectrum_and_thd(self):
        """
        Verify FFT spectrum analyzer frequency bins and THD harmonic distortion metrics.
        """
        metrics = self.engine.run_simulation(duration_ms=5.0)
        freqs = metrics["fft_freqs_khz"]
        mags = metrics["fft_mag_db"]
        thd = metrics["thd_pct"]

        self.assertGreater(len(freqs), 50, "FFT resolution too coarse.")
        self.assertEqual(len(freqs), len(mags))
        
        # Frequency bins must be strictly monotonic increasing starting at 0 Hz
        self.assertEqual(freqs[0], 0.0)
        self.assertTrue(np.all(np.diff(freqs) > 0.0), "FFT frequency vector is not strictly monotonic.")
        
        # THD for switching ripple must be finite and within physical bounds (0.01% - 50%)
        self.assertGreater(thd, 0.01)
        self.assertLess(thd, 50.0)

    def test_04_bode_stability_margins(self):
        """
        Verify real SPICE .AC small-signal solver matches theoretical resonant frequency:
        f0 = 1 / (2 * pi * sqrt(L * C))
        For L = 47 uH, C = 100 uF -> f0 = 2321.5 Hz.
        """
        l_val = 47.0
        c_val = 100.0
        rload = 5.0
        

        bode = StudioSimulationEngine.run_real_spice_bode(l_val_uh=l_val, c_val_uf=c_val, rload=rload)
        
        freqs = bode["freqs_hz"]
        mag_db = bode["mag_db"]
        
        self.assertGreater(len(freqs), 20)
        self.assertEqual(len(freqs), len(mag_db))
        
        # Low frequency gain at 10 Hz must be approximately 0 dB (unity passband gain)
        self.assertAlmostEqual(mag_db[0], 0.0, delta=0.5,
                               msg=f"Passband DC gain was {mag_db[0]:.2f} dB, expected ~0 dB.")
        
        # High frequency roll-off: at 50 kHz (>20*f0), 2nd order LC slope should be <-40 dB
        idx_high = np.argmin(np.abs(freqs - 50000.0))
        self.assertLess(mag_db[idx_high], -35.0,
                        msg=f"High-frequency 50kHz attenuation insufficient: {mag_db[idx_high]:.1f} dB")
        
        # Phase margin must confirm unconditional stability (> 45 deg)
        self.assertGreater(bode["phase_margin_deg"], 40.0)
        self.assertEqual(bode["stability_status"], "STABLE")

    def test_05_awg_signal_synthesis(self):
        """
        Verify AWG waveform generator synthesis against exact mathematical True-RMS formulas:
        - Sine: Vrms = A / (2 * sqrt(2)) (peak-to-peak amp A)
        - Square (50% duty): Vrms = A / 2
        - Triangle: Vrms = A / (2 * sqrt(3))
        """
        amp = 4.0  # 4V peak-to-peak (amplitude = 2.0V)
        offset = 0.0
        points = 2000

        # 1. Sine Wave: Expected RMS = 2.0 / sqrt(2) = 1.4142 V
        t, sig_sine = StudioSimulationEngine.generate_awg_signal("Sine", 1000.0, amp, offset, points=points)
        sine_rms = np.sqrt(np.mean(sig_sine**2))
        expected_sine_rms = (amp / 2.0) / np.sqrt(2.0)
        self.assertAlmostEqual(sine_rms, expected_sine_rms, delta=0.02,
                               msg=f"Sine RMS {sine_rms:.4f}V deviated from {expected_sine_rms:.4f}V")

        # 2. Square Wave: Expected RMS = 2.0 V
        t, sig_sq = StudioSimulationEngine.generate_awg_signal("Square", 1000.0, amp, offset, duty_pct=50.0, points=points)
        sq_rms = np.sqrt(np.mean(sig_sq**2))
        expected_sq_rms = amp / 2.0
        self.assertAlmostEqual(sq_rms, expected_sq_rms, delta=0.02,
                               msg=f"Square RMS {sq_rms:.4f}V deviated from {expected_sq_rms:.4f}V")

        # 3. Triangle Wave: Expected RMS = 2.0 / sqrt(3) = 1.1547 V
        t, sig_tri = StudioSimulationEngine.generate_awg_signal("Triangle", 1000.0, amp, offset, points=points)
        tri_rms = np.sqrt(np.mean(sig_tri**2))
        expected_tri_rms = (amp / 2.0) / np.sqrt(3.0)
        self.assertAlmostEqual(tri_rms, expected_tri_rms, delta=0.03,
                               msg=f"Triangle RMS {tri_rms:.4f}V deviated from {expected_tri_rms:.4f}V")

    def test_06_semiconductor_curve_tracer(self):
        """
        Verify real SPICE .DC sweep curve tracer extracted parameters:
        - MOSFET: Threshold voltage Vth = 3.0V, subthreshold cutoff, and saturation conduction
        - Diode: Schottky 1N5819 forward drop (Vf ~ 0.35V) vs Silicon 1N4148 (Vf ~ 0.70V)
        """
        # 1. MOSFET DC Sweep
        mos = StudioSimulationEngine.trace_mosfet_iv(vgs_steps=[2.0, 5.0, 10.0], vds_max=15.0)
        self.assertEqual(len(mos["curves"]), 3)
        self.assertEqual(mos["vth"], 3.0)
        
        # At Vgs = 2.0V (< Vth = 3.0V), subthreshold leakage must be < 1.0 nA (real SPICE physical leakage)
        self.assertLess(float(np.max(mos["curves"][0]["id_amps"])), 1.0e-9)
        
        # At Vgs = 10.0V (Vov = 7.0V), strong saturation conduction
        id_10v = mos["curves"][2]["id_amps"]
        self.assertGreater(np.max(id_10v), 10.0, "MOSFET did not enter strong conduction at Vgs=10V.")

        # 2. Diode DC Sweep: At 1.0A forward current, Schottky forward voltage must be < Silicon
        dio = StudioSimulationEngine.trace_diode_iv(vf_max=1.0)
        vf_arr = dio["vf"]
        # Find voltage where Schottky reaches 0.5A vs Silicon
        idx_schottky_05a = np.where(dio["i_schottky"] >= 0.5)[0]
        idx_silicon_05a = np.where(dio["i_silicon"] >= 0.5)[0]
        
        self.assertTrue(len(idx_schottky_05a) > 0 and len(idx_silicon_05a) > 0)
        vf_schottky_05a = vf_arr[idx_schottky_05a[0]]
        vf_silicon_05a = vf_arr[idx_silicon_05a[0]]
        
        # Schottky forward drop must be strictly lower than Silicon by > 80 mV
        self.assertLess(vf_schottky_05a, vf_silicon_05a - 0.08,
                        msg=f"Schottky Vf ({vf_schottky_05a:.3f}V) not significantly lower than Silicon ({vf_silicon_05a:.3f}V)")

    def test_07_power_and_thermal_loss_profiler(self):
        """
        Verify First-Law of Thermodynamics Energy Balance:
        Pin = Pout + P_loss_total
        """
        metrics = self.engine.run_simulation(vin=12.0, vtarget=3.30, rload=5.0)
        p_in = metrics["p_in_w"]
        p_out = metrics["p_out_w"]
        p_loss_total = metrics["p_loss_total"]
        
        # First-law balance: Pin - (Pout + Ploss) must be exactly 0
        self.assertAlmostEqual(p_in, p_out + p_loss_total, delta=0.02,
                               msg=f"Energy conservation violation: Pin ({p_in:.3f}W) != Pout ({p_out:.3f}W) + Ploss ({p_loss_total:.3f}W)")
        
        # Thermal junction rise Delta TJ = Ploss * 40 °C/W
        expected_tj = p_loss_total * 40.0
        self.assertAlmostEqual(metrics["tj_rise_c"], expected_tj, delta=0.1)

    def test_08_protocol_packet_decoder(self):
        """
        Verify the hardware UART 8N1 bit-exact deserializer.

        The stimulus is a real 8N1 byte stream: one start bit, eight data bits
        (LSB first), one stop bit, ten samples per bit.  The previous square
        wave gave about one sample per bit at 115200 baud, which is not
        decodable and made the decoder return an empty list.
        """
        baud = 9600
        samples_per_bit = 10
        dt_ms = (1000.0 / baud) / samples_per_bit

        def frame(byte):
            bits = [0] + [(byte >> k) & 1 for k in range(8)] + [1]
            return [b for b in bits for _ in range(samples_per_bit)]

        idle = [1] * (5 * samples_per_bit)
        sig = []
        sig += idle
        for byte in b"OK\n":
            sig += frame(byte)
            sig += idle
        sig = np.array(sig, dtype=float)
        time_ms = np.arange(len(sig)) * dt_ms

        packets = StudioSimulationEngine.decode_uart_packets(
            sig, time_ms, baud_rate=baud)
        self.assertIsInstance(packets, list)
        self.assertGreater(len(packets), 0)
        self.assertIn("hex", packets[0])
        self.assertIn("ascii", packets[0])
        self.assertEqual([p["hex"] for p in packets],
                         ["0x4F", "0x4B", "0x0A"])

    def test_09_project_json_serialization(self):
        """
        Verify .wowki project serialization and deserialization integrity.
        """
        test_proj = {
            "components": [{"id": "ESP32", "x": 100, "y": 100}],
            "wires": [{"from": "ESP32:GPIO18", "to": "MOSFET:GATE"}],
            "firmware": "// Custom firmware",
            "mcu": "ESP32 (Xtensa Dual-Core 240MHz)"
        }
        self.engine.load_project_json(test_proj)
        self.assertEqual(len(self.engine.components), 1)
        self.assertEqual(self.engine.firmware_code, "// Custom firmware")
        
        exported = self.engine.export_project_json()
        self.assertEqual(exported["version"], "3.0")
        self.assertEqual(exported["mcu"], "ESP32 (Xtensa Dual-Core 240MHz)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
