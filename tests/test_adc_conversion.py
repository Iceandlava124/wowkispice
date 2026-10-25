"""test_adc_conversion.py - Unit: ADC conversion, no external tools.

Verifies the same pin-referenced counts mapping the firmware (and
control_law.to_counts) uses, with the clamp and rounding behaviour asserted
from closed-form values, not from the function under test.
"""

import sys

sys.path.insert(0, ".")

from bridge.control_law import _to_counts, ControlLaw, HystereticLaw


class TestToCountsClampAndRounding:
    """ADC conversion must clamp and round exactly at the converter boundaries.

    Values come from the closed-form ADC mapping
    `counts = round(v / vref * (2^bits - 1))`, not from the function under test.
    """

    def test_negative_maps_to_zero(self):
        # -0.001 V must be clamped to 0 counts, not wrapped.
        out = _to_counts(-0.001, 3.3, 12)
        assert out == 0

    def test_exact_half_lsb_rounds_down(self):
        # A voltage exactly half an LSB above 0 must round to 0 counts.
        # LSB = vref/full = 3.3/4095, so half LSB = 3.3/8190. The spec
        # expression 3.3/4095.0/2.0 is float-associative: (3.3/4095)/2.0
        # round-trips to 0.00040293040293040293, and the closed-form value is
        # exactly 3.3/8190 = 0.00040293040293040293 as well, so this is not
        # the float fragility the old comment claimed. It is simply the
        # halfway point of the 12-bit range in volts.
        out = _to_counts(3.3 / 8190, 3.3, 12)
        assert out == 0
        # One ulp above the half-LSB boundary must round up to 1.
        out = _to_counts(3.3 / 8190 + 1e-9, 3.3, 12)
        assert out == 1

    def test_exact_full_scale_clips_to_max(self):
        # 3.3 V is exactly full scale and must map to 4095, never 4096.
        out = _to_counts(3.3, 3.3, 12)
        assert out == 4095

    def test_just_below_full_scale(self):
        # One ulp below full scale is a real count, not clipped.
        out = _to_counts(3.3 - 1e-9, 3.3, 12)
        assert out == 4095

    def test_above_vref_clips(self):
        out = _to_counts(3.31, 3.3, 12)
        assert out == 4095

    def test_clamp_behaviour_without_float(self):
        # The clamp must hold even for a voltage that is clearly above Vref
        # but tiny enough that exact half-lsb rounding would otherwise matter.
        out = _to_counts(3.30000001, 3.3, 12)
        assert out == 4095


class TestLawCountsAtThresholds:
    """Every HystereticLaw threshold is checked for exactly-at-value behaviour,
    using the firmware's own ADC_LOW_THRESHOLD/ADC_HIGH_THRESHOLD (1995/2030)
    from firmware/esp32_buck_controller/src/main.c.
    """

    def _fixture_spec(self):
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

    def test_decide_below_low_drives_high(self):
        law = HystereticLaw(self._fixture_spec())
        # firmware branch: raw_adc < ADC_LOW_THRESHOLD -> drive HIGH
        assert law.decide(1994) is True
        assert law.decide(1993) is True

    def test_decide_at_low_drives_high_hold(self):
        law = HystereticLaw(self._fixture_spec())
        # Exactly at ADC_LOW_THRESHOLD holds the previous state, because the
        # firmware's hold region is the inclusive band [1995, 2030].
        law.level = True
        assert law.decide(1995) is True
        law.level = False
        assert law.decide(1995) is False
        # Just below still drives HIGH.
        assert law.decide(1994) is True

    def test_decide_inside_band_holds(self):
        law = HystereticLaw(self._fixture_spec())
        inside = (law.low_counts + law.high_counts) // 2
        law.level = True
        assert law.decide(inside) is True
        law.level = False
        assert law.decide(inside) is False
        law.level = True
        assert law.decide(inside + 1) is True
        law.level = False
        assert law.decide(inside + 1) is False

    def test_decide_at_high_drives_low_hold(self):
        law = HystereticLaw(self._fixture_spec())
        # Exactly at ADC_HIGH_THRESHOLD holds the previous state.
        law.level = True
        assert law.decide(2030) is True
        law.level = False
        assert law.decide(2030) is False
        # Just above still drives LOW.
        assert law.decide(2031) is False

    def test_decide_above_high_drives_low(self):
        law = HystereticLaw(self._fixture_spec())
        assert law.decide(2031) is False
        assert law.decide(2032) is False

    def test_update_counts_switches_only_on_change(self):
        # With the firmware's real thresholds (1995/2030), two readings inside
        # the hysteresis band must not change the level or switch_count.
        # A sense voltage of 3.25 V through a 2:1 divider is 1.625 V at the
        # ADC pin = 2023 counts, which is inside (1995, 2030).
        law = HystereticLaw(self._fixture_spec())
        law.update(3.25, 0.0)
        first = law.history_counts[-1]
        law.update(3.25, 1e-6)
        assert law.history_counts[-1] == first
        assert law.switch_count == 0
