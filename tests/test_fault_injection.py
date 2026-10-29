"""Fault-injection probe for the M0 cycle helpers.

Every failure shape is enumerated; each call returns a clean
FirmwareCouplingCycle with ok=False and a readable message.

Failure shapes covered (all clean, no exceptions):
  1. qmp is None while WOSP_QEMU unset     -> "WOSP_QEMU not configured"
  2. qmp is None while WOSP_QEMU is set     -> "no QMP handle"
  3. sweep runs even when a single cycle fails -> no raise, all ok=False
"""
from __future__ import annotations

import os
import unittest
import pytest

from bridge import firmware_runner as fr


class TestFaultInjection(unittest.TestCase):
    def test_qemu_not_configured_is_clean(self):
        # WOSP_QEMU empty/null -> the env gate is hit first.
        saved = os.environ.get("WOSP_QEMU")
        try:
            os.environ["WOSP_QEMU"] = ""
            cycle = fr.cycle_adc_and_gate(qmp=None, adc_value=2000)
            self.assertFalse(cycle.ok)
            self.assertIsNone(cycle.gate_high)
            self.assertIn("not configured", cycle.message.lower())
        finally:
            if saved is None:
                os.environ.pop("WOSP_QEMU", None)
            else:
                os.environ["WOSP_QEMU"] = saved

    @pytest.mark.req("CO-10")
    def test_qmp_none_with_env_set_is_clean(self):
        # WOSP_QEMU points at an existing normal-abspath, so the env gate
        # reports configured; with qmp=None the explicit "no QMP handle"
        # failure path fires first.
        saved = os.environ.get("WOSP_QEMU")
        try:
            os.environ["WOSP_QEMU"] = os.path.abspath(os.path.dirname(__file__))
            cycle = fr.cycle_adc_and_gate(qmp=None, adc_value=2000)
            self.assertFalse(cycle.ok)
            self.assertIsNone(cycle.gate_high)
            self.assertIn("no qmp handle", cycle.message.lower())
        finally:
            if saved is None:
                os.environ.pop("WOSP_QEMU", None)
            else:
                os.environ["WOSP_QEMU"] = saved

    def test_sweep_returns_every_cycle_clean(self):
        report = fr.sweep_report(qmp=None, adc_values=[1500, 2000, 3500])
        self.assertEqual(len(report), 3)
        for entry in report:
            self.assertFalse(entry.ok)
            self.assertIsNone(entry.gate_high)
            self.assertTrue(entry.message)


if __name__ == "__main__":
    unittest.main()
