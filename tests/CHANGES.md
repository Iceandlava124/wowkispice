# tests/CHANGES.md — honest log of test status decisions
#
# Rule: any test that is edited, skipped, or reinterpreted is documented here
# with (a) what it tested, (b) why the change is justified, and (c) what
# replaces it or how it is now guarded. No test is weakened silently.

## 2026-10-24 — baseline-fix branch

### test_qemu_monitor_unit.py::test_monitor_socket_server_double — REPLACED
- What it tested: a listening socket server that never accepted a real client
  and never imported bridge.qemu_monitor. The test asserted its own local
  variable `ok` after sending a string to a socket it created, so it proved
  nothing about the repo and could never pass because no client was ever
  connected to srv.accept().
- Why: defective test, not a flaky one. It was, at best, a half-written fake
  monitor that was left unwired.
- Replacement: test_monitor_client_sends_qom_set_and_gets_reply, which runs
  the double in a daemon thread and calls the real QemuMonitor._hmp send/recv
  path against it. The assertion checks what the server actually received and
  what the client returned. The server is now named explicitly as a double in
  the docstring and used only for error-handling shapes.
- Related: the real-QEMU contract test is still expected to live under a
  @pytest.mark.qemu marker; this machine does not have qemu-system-xtensa, so
  that contract test is UNEXECUTED, not skipped by choice.

### test_cycle_adc_and_gate_error_shapes — KEPT, guarded
- Kept as-is. It exercises real bridge.qemu_monitor code paths (the
  no-qmp / no-QEMU / bad-handle return values) and is not a socket-only stub.
- Guard added in Step 3: every connection-using path in the file now has
  socket settimeouts so the suite cannot hang.

### test_control_law_unit.py::test_rejects_unknown_kind — NO LONGER FAILING
- Current behavior: normalize_law rejects anything not in LAW_KINDS
  ("hysteretic", "pwm"). The test now asserts that "sine", "bang-bang", ""
  raise ControlLawError, and that "pwm" is accepted. This matches the module.
- No edit required; the failure was from a stale test in a prior tree, not the
  committed 9d6c797 behavior.

### test_adc_conversion.py / test_control_law_unit.py — GATE ON FIRMWARE
- The 1995/2030 thresholds come from firmware/esp32_buck_controller/src/main.c
  lines 40-41. The firmware's branch order is:
    raw_adc < ADC_LOW_THRESHOLD  ->  drive HIGH
    raw_adc > ADC_HIGH_THRESHOLD ->  drive LOW
    otherwise                    ->  hold
  So the thresholds are inclusive for the hold region: exactly 1995 holds, and
  exactly 2030 holds. This matches bridge/control_law.py HystereticLaw.decide()
  today (counts < low -> HIGH, counts > high -> LOW, else hold).
- The 6 failing tests were STALE, not real bugs: they asserted voltage-derived
  counts (1945/2150), exact thresholds that differ from the firmware, and
  float-point behavior that does not match the committed control_law. They are
  fixed to use the firmware's real counts and to assert the firmware's actual
  branch semantics.

### test_exact_half_lsb_rounds_down — FLOATING POINT NOTE (kept, passing)
- 3.3/8190 in IEEE-754 double does not land above the 0.5 rounding boundary of
  int(round( ... * 4095)). The closed-form half-LSB value is exactly
  3.3/8190 V; _to_counts maps it to 0 because round(v/vref*4095) with
  v = 3.3/8190 gives round(0.5) under Python's banker's rounding only if the
  product is bitwise >= 0.5 — it is not. This test is correct and stays.
- Computed: (3.3/4095/2) * 4095/3.3 is not above 0.5 in this runtime; the test
  is not fragile in the way the old comment feared. Reported here for the record.

## 2026-10-24 — skip reasons sharpened + emulator gate added (second pass)

### tests/test_qemu_monitor_qemu.py — SKIP REASONS SHARPENED (not weakened)
- What changed: both `@pytest.mark.qemu` tests previously skipped with one
  generic reason ("qemu-system-xtensa (or WOSP_QEMU binary) not found on this
  machine"). The reason is now produced by `_skip_reason()`, which names the
  EXACT missing item in one of three shapes:
  1. `WOSP_QEMU set but binary not found at <path>`
  2. `WOSP_QEMU not set and no qemu-system-xtensa in PATH or the working
     directory (Track B: tools/run_emulator_tests.ps1, see SETUP.md)`
  3. `not running under Linux: <path> is a Linux ELF that Windows cannot
     execute (Track B: tools/run_emulator_tests.ps1 runs these tests inside WSL)`
- No assertion, no test body, no marker was changed or removed. When the
  binary exists and the OS can execute it, both tests RUN (proven: 2 passed
  inside WSL against the built patched qemu-system-xtensa 9.2.2).
- Guard added so a skip can never be silently absorbed:
  `tools/run_tests.py --require-emulator` re-runs only `-m qemu` and exits 3
  on any skip, failure, or empty collection; `tools/run_emulator_tests.ps1`
  (Track B) exits non-zero if WSL/binary is missing or any test is skipped or
  fails, and never prints success for a skip.
