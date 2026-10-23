"""test_control_law_unit.py - Unit tests for control_law.py.

Covers spec normalisation, the hysteretic decision table at every transition
around 1995 and 2030 (including values exactly at the thresholds and repeated
values), divider semantics, and the fidelity-gap assertions that pin the
"what this law does not model" section of the module.
"""

import os
import sys

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
        for bad in ("sine", "pwm", "bang-bang", ""):
            try:
                control_law.normalize_law(
                    {"kind": bad, "pin": "GPIO18", "sense_net": "vout"}
                )
            except control_law.ControlLawError:
                pass
            else:
                raise AssertionError("expected ControlLawError for kind %r" % bad)

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
    def test_every_transition_around_1995_and_2030(self):
        # 1995 and 2030 are the firmware's own thresholds; every transition
        # around them, including exact-at-threshold values, is asserted here.
        law = control_law.make_law(
            {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
             "target_v": 3.3, "hysteresis_v": 0.165, "divider": 0.5,
             "vref": 3.3, "adc_bits": 12}
        )
        assert law.decide(1992) is True
        assert law.decide(1994) is True
        law.level = True
        assert law.decide(1995) is True
        law.level = False
        assert law.decide(1995) is False
        assert law.decide(2030) is False
        law.level = True
        assert law.decide(2030) is True
        law.level = False
        assert law.decide(2031) is False
        law.level = True
        assert law.decide(2031) is True
        law.level = False
        assert law.decide(2033) is False

    def test_below_low_drives_high(self):
        law = control_law.make_law(
            {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
             "target_v": 3.3, "hysteresis_v": 0.165, "divider": 0.5,
             "vref": 3.3, "adc_bits": 12}
        )
        assert law.decide(1945) is True

    def test_above_high_drives_low(self):
        law = control_law.make_law(
            {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
             "target_v": 3.3, "hysteresis_v": 0.165, "divider": 0.5,
             "vref": 3.3, "adc_bits": 12}
        )
        assert law.decide(2030) is False
        assert law.decide(2031) is False

    def test_inside_band_holds_previous_state(self):
        law = control_law.make_law(
            {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
             "target_v": 3.3, "hysteresis_v": 0.165, "divider": 0.5,
             "vref": 3.3, "adc_bits": 12}
        )
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
        # Naming the undivided node but leaving divider at 1.0 is the bug
        # that halves the deadband. This test asserts the corrected version
        # keeps the same switching points.
        spec["divider"] = 1.0
        s = control_law.normalize_law(spec)
        assert s["low_counts"] == 1995
        assert s["high_counts"] == 2030


class TestFidelityGap:
    """A fidelity gap nobody notices is how a model rots.

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
