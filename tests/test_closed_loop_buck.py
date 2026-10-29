"""
test_closed_loop_buck.py - Automated unit test for Closed-loop buck converter regulation.
"""

import sys
import os
import unittest
import ctypes
import io
import re

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bridge.mock_controller import run_closed_loop_simulation, MockESP32BuckController
from bridge.ngspice_wrapper import GetSyncData_t


class TestThresholdsMatchFirmware(unittest.TestCase):
    """mock_controller and control_law must agree on the decision boundary.

    Both model the same firmware, so both must cross at the same counts. The
    firmware declares ADC_LOW_THRESHOLD 1995 / ADC_HIGH_THRESHOLD 2030; these
    are derived from the controller's defaults rather than restated, so they
    cannot drift apart silently again.
    """

    def test_counts_match_the_firmware_constants(self):
        c = MockESP32BuckController()
        self.assertEqual(c.adc_low, 1995)
        self.assertEqual(c.adc_high, 2030)

    def test_divider_is_not_applied_twice(self):
        """It reads the real `fb` node, so the divider belongs in thresholds only."""
        c = MockESP32BuckController()
        self.assertEqual(c.divider_ratio, 0.5)
        # 1997 would mean the divider had also been applied to the reading.
        self.assertNotEqual(c.adc_low, 997)


class TestClosedLoopBuck(unittest.TestCase):
    @pytest.mark.req("CO-11")
    def test_buck_regulation(self):
        res = run_closed_loop_simulation(
            total_time_ms=5.0,
            tstep_us=0.5,
            save_plot=False
        )
        
        avg_vout = res["avg_vout"]
        ripple = res["ripple_p2p"]
        switch_count = res["switch_count"]
        
        # 1. Check regulation target (3.3V +- 0.10V)
        self.assertTrue(3.20 <= avg_vout <= 3.40, f"Regulation failed: Avg Vout was {avg_vout:.4f}V")

        # 2. Check ripple is within expected hysteretic bounds (< 300mV)
        self.assertLess(ripple, 0.300, f"Ripple too high: {ripple*1000:.1f}mV")

        # 3. Check continuous gate toggling occurred
        self.assertGreater(switch_count, 50, f"Expected > 50 switch events, got {switch_count}")


class TestGetSyncDataArityMatchesHeader(unittest.TestCase):
    """Regression guard for the JOB 1 hang.

    bridge/ngspice_wrapper.py declares GetSyncData_t with ctypes.CFUNCTYPE and
    hands it to ngSpice_Init_Sync. ctypes builds the call from that
    declaration alone. If one parameter type is missing, ctypes reads the C
    stack wrongly inside the callback, the callback fails inside ngspice's C
    frame, and the ngSpice_Command("run") that follows never returns - the
    hang triaged in this job.

    Independent expected source, not the module under test:

        tools/ngspice_dll/Spice64_dll/include/ngspice/sharedspice.h:319
            typedef int (GetSyncData)(double, double*, double, int, int, int, void*);

    Read from disk in this session: 7 parameter types plus the int return
    type = 7 parameters plus an int return, checked via _argtypes_/_restype_.
    When the header is present it is parsed and
    must still match that quote. tools/ngspice_dll is gitignored, so a clean
    clone has no copy; then the quoted typedef is used and the source string
    says so instead of skipping the test.
    """

    HEADER_REL = os.path.join(
        "tools", "ngspice_dll", "Spice64_dll", "include", "ngspice", "sharedspice.h"
    )
    HEADER_TYPEDEF_RE = (
        r"typedef\s+int\s*\(\s*GetSyncData\s*\)\s*\(([^)]*)\)\s*;"
    )
    HEADER_TYPEDEF_QUOTED = (
        "typedef int (GetSyncData)(double, double*, double, int, int, int, void*);"
    )

    # C type as spelled in the header -> ctypes type used in the declaration.
    CTYPES_FOR_C = {
        "double": ctypes.c_double,
        "double*": ctypes.POINTER(ctypes.c_double),
        "int": ctypes.c_int,
        "void*": ctypes.c_void_p,
    }

    @classmethod
    def _header_param_types(cls):
        """Return (list of C type strings, description of where they came from)."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        header = os.path.join(repo_root, cls.HEADER_REL)

        if not os.path.isfile(header):
            match = re.search(cls.HEADER_TYPEDEF_RE, cls.HEADER_TYPEDEF_QUOTED)
            assert match, "quoted header typedef must parse"
            return (
                [p.strip() for p in match.group(1).split(",")],
                "quoted typedef, header absent from this clone: " + cls.HEADER_REL,
            )

        with io.open(header, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()

        for idx, line in enumerate(lines, start=1):
            match = re.search(cls.HEADER_TYPEDEF_RE, line)
            if match:
                quoted = line.strip()
                assert quoted == cls.HEADER_TYPEDEF_QUOTED, (
                    "sharedspice.h:%d no longer matches this job's expectation:\n"
                    "  on disk: %s\n  quoted:  %s"
                    % (idx, quoted, cls.HEADER_TYPEDEF_QUOTED)
                )
                return ([p.strip() for p in match.group(1).split(",")],
                        "%s:%d" % (cls.HEADER_REL, idx))

        raise AssertionError("GetSyncData typedef not found in " + header)

    @pytest.mark.timeout(30)
    def test_cfunctype_arity_matches_the_header(self):
        """ctypes.CFUNCTYPE keeps the return type in _restype_, not _argtypes_.

        Measured on this platform (logs/cmd/probe_cfuntyp.py): a declaration
        built directly from the header signature gives _argtypes_ of length 7
        and _restype_ = c_int.  So the expected arity of _argtypes_ is exactly
        the number of header parameters, and the return type is checked
        against _restype_.
        """
        params, source = self._header_param_types()
        self.assertEqual(
            len(params), 7,
            "header gave %r from %s" % (params, source),
        )

        declared = list(GetSyncData_t._argtypes_)
        self.assertEqual(
            len(declared), len(params),
            "CFUNCTYPE declares %d parameters for %d header params (%s)"
            % (len(declared), len(params), source),
        )
        self.assertIs(
            GetSyncData_t._restype_, ctypes.c_int,
            "return type from %s" % source,
        )

    @pytest.mark.timeout(30)
    def test_cfunctype_types_match_the_header_parameter_by_parameter(self):
        params, source = self._header_param_types()
        # _argtypes_ starts at parameter 1; there is no return type in it.
        declared = list(GetSyncData_t._argtypes_)

        for position, (c_type, ctypes_type) in enumerate(zip(params, declared), start=1):
            expected = self.CTYPES_FOR_C.get(c_type)
            self.assertIsNotNone(
                expected,
                "no ctypes mapping for header type %r at position %d (%s)"
                % (c_type, position, source),
            )
            self.assertIs(
                ctypes_type, expected,
                "parameter %d of GetSyncData: header says %s, CFUNCTYPE says %r (%s)"
                % (position, c_type, ctypes_type, source),
            )

    @pytest.mark.timeout(30)
    def test_callback_accepts_the_seven_header_arguments(self):
        """ngspice calls the handler with all seven parameters; a 6-parameter
        declaration rejects that call.

        Building a CFUNCTYPE object does not check its arity, so this test
        actually invokes it with (double, double*, double, int, int, int,
        void*) exactly as the typedef at sharedspice.h:319 specifies. A
        declaration missing a parameter raises TypeError instead of returning
        the 0 that tells ngspice to continue.
        """
        params, source = self._header_param_types()
        self.assertEqual(len(params), 7, source)

        seen = {}

        def _fake_callback(time, vector, size, redostep, ident, location, userdata):
            seen["args"] = (time, size, redostep, ident, location, userdata)
            return 0

        callback = GetSyncData_t(_fake_callback)
        vector = (ctypes.c_double * 1)(0.0)

        returned = callback(1.5, vector, 2.0, 0, 0, 0, None)

        # Check the handler was entered before anything else: a declaration
        # missing a parameter raises inside ctypes, which swallows the
        # exception as unraisable and hands back garbage, so "seen" stays
        # empty. That is the precise symptom of the JOB 1 defect.
        self.assertIn(
            "args", seen,
            "handler was never invoked with the seven declared arguments; "
            "ctypes swallowed an arity mismatch (%s)" % source,
        )
        self.assertEqual(returned, 0, "handler must return 0 to let ngspice continue")
        self.assertEqual(len(seen["args"]), 6, "time plus the other five scalars/pointer")
        self.assertEqual(seen["args"][0], 1.5, "first parameter is the double from %s" % source)

if __name__ == "__main__":
    unittest.main()
