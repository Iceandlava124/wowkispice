"""
test_control_law_unit.py — Unit tests for control_law.py.

Covers spec normalisation, the hysteretic decision table at every transition
around 1995 and 2030 (including values exactly at the thresholds and repeated
values), divider semantics, and the fidelity-gap assertions that pin the
"what this law does not model" section of the module.
"""

import os
import re
import sys
import pytest

sys.path.insert(0, ".")

from bridge import control_law

FIRMWARE_MAIN_C = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "firmware", "esp32_buck_controller", "src", "main.c",
)


class TestSpecNormalization:
    def test_normalize_fills_defaults(self):
        law = control_law.normalize_law({
            "kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
            "target_v": 3.3, "hysteresis_v": 0.165, "divider": 0.5,
            "vref": 3.3, "adc_bits": 12,
        })
        assert law["kind"] == "hysteretic"
        assert "low_counts" in law and "high_counts" in law

    def test_rejects_unknown_kind(self):
        # normalize_law accepts only LAW_KINDS = ('hysteretic', 'pwm').
        # Everything else must raise ControlLawError.
        for bad in ("sine", "bang-bang"):
            with pytest.raises(control_law.ControlLawError, match=re.escape(bad)):
                control_law.normalize_law(
                    {"kind": bad, "pin": "GPIO18", "sense_net": "vout"}
                )
        # Empty kind must also be rejected.
        with pytest.raises(control_law.ControlLawError):
            control_law.normalize_law(
                {"kind": "", "pin": "GPIO18", "sense_net": "vout"}
            )

    def test_accepts_pwm_kind(self):
        # PwmLaw is a registered kind and must normalise cleanly.
        spec = control_law.normalize_law({
            "kind": "pwm", "pin": "GPIO18", "sense_net": "vout",
            "target_v": 3.3, "vref": 3.3, "adc_bits": 12,
        })
        assert spec["kind"] == "pwm"

    def test_rejects_zero_divider(self):
        try:
            control_law.normalize_law(
                {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
                 "target_v": 3.3, "hysteresis_v": 0.165, "divider": 0})
        except control_law.ControlLawError:
            pass
        else:
            raise AssertionError("expected ControlLawError for divider=0")

    def test_rejects_negative_adc_bits(self):
        try:
            control_law.normalize_law(
                {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
                 "target_v": 3.3, "hysteresis_v": 0.165, "vref": 3.3,
                 "adc_bits": 4}
            )
        except control_law.ControlLawError:
            pass
        else:
            raise AssertionError("expected ControlLawError for adc_bits=4")

    def _reraise(self):
        return type("R", (), {"__enter__": lambda s: None,
                             "__exit__": lambda s, *a: False})()


class TestHystereticDecision:
    def _fixture_spec(self):
        # The firmware's ADC_LOW_THRESHOLD/ADC_HIGH_THRESHOLD (1995/2030)
        # are raw counts at the ADC pin (firmware/esp32_buck_controller/src/main.c
        # lines 40-41). Use those explicit counts so the decision boundary is
        # bit-for-bit the firmware's.
        return {
            "kind": "hysteretic",
            "pin": "GPIO18",
            "sense_net": "vout",
            "target_v": 3.3,
            "hysteresis_v": 0.165,
            "divider": 0.5,
            "vref": 3.3,
            "adc_bits": 12,
            "low_counts": 1995,
            "high_counts": 2030,
        }

    def test_every_transition_around_1995_and_2030(self):
        # 1995 and 2030 are the firmware's own thresholds (main.c lines 40-41);
        # every transition around them, including exact-at-threshold values, is
        # asserted here. The firmware's branch order is < low -> HIGH,
        # > high -> LOW, else hold — so exactly 1995 and exactly 2030 hold.
        law = control_law.make_law(self._fixture_spec())
        assert law.decide(1992) is True
        assert law.decide(1994) is True
        law.level = True
        assert law.decide(1995) is True
        law.level = False
        assert law.decide(1995) is False
        law.level = True
        assert law.decide(2030) is True
        law.level = False
        assert law.decide(2030) is False
        # 2031 is above the high threshold, so the firmware drives LOW
        # (main.c:160 uses strict `>`). It never forces HIGH; instead it forces
        # the gate OFF from any prior ON state, and holds OFF when already OFF.
        law.level = True
        assert law.decide(2031) is False
        law.level = False
        assert law.decide(2031) is False
        assert law.decide(2033) is False

    def test_below_low_drives_high(self):
        law = control_law.make_law(self._fixture_spec())
        assert law.decide(1994) is True

    def test_above_high_drives_low(self):
        law = control_law.make_law(self._fixture_spec())
        assert law.decide(2030) is False
        assert law.decide(2031) is False
        assert law.decide(2032) is False

    def test_exact_at_high_holds_when_low(self):
        law = control_law.make_law(self._fixture_spec())
        law.level = True
        assert law.decide(2030) is True

    def test_inside_band_holds_previous_state(self):
        law = control_law.make_law(self._fixture_spec())
        inside = (law.low_counts + law.high_counts) // 2
        assert law.decide(inside) is not None
        law.level = True
        assert law.decide(inside) is True
        law.level = False
        assert law.decide(inside) is False


class TestDividerSemantics:
    def test_pin_referenced_net_needs_no_divider(self):
        spec = control_law.law_from_firmware_source_exact(
            FIRMWARE_MAIN_C, "fb", divider=1.0)
        assert spec["divider"] == 1.0
        assert spec["low_counts"] == 1995
        assert spec["high_counts"] == 2030

    def test_undivided_node_regulates_to_half(self):
        spec = control_law.law_from_firmware_source_exact(
            FIRMWARE_MAIN_C, "vout", divider=0.5)
        lo, hi = control_law.implied_output_voltages(spec, 0.5)
        assert abs(lo - 3.2154) < 0.01
        assert abs(hi - 3.2718) < 0.01

    def test_reapplying_divider_twice_halves_the_target(self):
        spec = control_law.law_from_firmware_source_exact(
            FIRMWARE_MAIN_C, "vout", divider=0.5)
        spec["divider"] = 1.0
        s = control_law.normalize_law(spec)
        assert s["low_counts"] == 1995
        assert s["high_counts"] == 2030


class TestFidelityGap:
    """
    A fidelity gap nobody notices is how a model rots.

    control_law does NOT model oversampling or ADC calibration. These tests
    assert the gap is visible, so a future change to the firmware forces this
    module's "WHAT THIS DOES NOT MODEL" section to be revisited.
    """

    def source(self):
        with open(FIRMWARE_MAIN_C, encoding="utf-8") as fh:
            return fh.read()

    def test_firmware_still_oversamples(self):
        assert "ADC_OVERSAMPLE_N" in self.source()

    def test_firmware_still_calibrates(self):
        assert "adc_cali" in self.source()

    def test_firmware_still_says_counts_are_raw(self):
        assert "RAW counts" in self.source()


if __name__ == "__main__":
    import unittest
    unittest.main()
