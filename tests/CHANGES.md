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

## 2026-10-25 — JOB 3: QEMU monitor tests audited and rebuilt against a fake HMP emulator

Method note: the audit compared `git --no-pager log -p -1 -- <file>` (the two
files are committed in `7371a29`, so there was no working-tree diff) against
the parent version from `git show 7371a29^:<file>`. New coverage comes from
`tests/fakes/fake_hmp_qemu.py`, a TEST DOUBLE launched through the REAL
`QemuMonitor.start()`; it verifies protocol handling only and says nothing
about real firmware. Real-emulator behaviour stays in
`tests/test_qemu_monitor_qemu.py` (@pytest.mark.qemu), which was NOT edited.

### test_qemu_monitor_unit.py::test_monitor_client_sends_qom_set_and_gets_reply — REWRITTEN
- Old assertion: the test built `expected_set` itself, matched a regex
  against that same literal (`set_cmd_pat.match(expected_set)`), then asserted
  `expected_set == "qom-set /machine/peripheral/sens adc1-value 2012"` — a
  tautology against its own string. Client code was touched only for the
  "no live process" error shape. Verdict: DECORATIVE for the command format.
- Why wrong: no assertion tied bridge/qemu_monitor.py to the command that
  reaches the wire; renaming the QOM property in the client would not have
  failed this test.
- New assertion: the fake emulator RECORDS every command it receives
  (FAKE_HMP_RECORD), and the test asserts
  `recorded_commands(record) == ["qom-set /machine/peripheral/sens adc1-value 2012"]`
  after driving `mon.set_adc1_value(2012)` through a started monitor. The
  `QemuMonitorError` shape without a live process is kept unchanged.

### test_qemu_monitor_unit.py::test_monitor_socket_server_double — DELETED
- Old: a `pass` body under a docstring explaining the earlier defective
  server (`srv.accept()` with no client, no bridge import). Verdict:
  DECORATIVE — a test that always passes and exercises nothing.
- Why removed: its stated replacements now exist as real tests; keeping a
  `pass` stub inflates the count and hides that nothing is covered. History
  remains in git (`7371a29^:tests/test_qemu_monitor_unit.py`).

### test_qemu_monitor_unit.py::test_cycle_adc_and_gate_error_shapes — KEPT, docstring narrowed
- Old docstring claimed "Every failure shape" (implying protocol failures).
- New docstring scopes it honestly to environment-gate shapes (no env, bad
  path, host:port string that never dials, handle that dies mid-cycle) and
  points protocol failures at the fake-emulator tests. No assertion changed.

### test_qemu_monitor_unit.py — NEW tests (added, none replaced or weakened)
Each carries `@pytest.mark.timeout(30)` (or 60) so none can hang:
- `test_set_adc1_value_accepts_int_coercion` — wire carries a bare integer.
- `test_read_gate_is_true_when_bit_18_set` (xp values 0x00040000, 0x00040004).
- `test_read_gate_is_false_when_bit_18_clear` (0x00000000, 0x00000004).
- `test_error_reply_raises_qemu_monitor_error_with_reply_text` — Error: reply
  must raise and must quote the reply text.
- `test_dropped_pipe_raises_qemu_monitor_error` — fake exits after the banner;
  must raise, not hang, not AttributeError.
- `test_silent_emulator_times_out_within_documented_timeout` — times the 10 s
  prompt wait and asserts `< 13 s`.
- `test_garbage_xp_output_raises_qemu_monitor_error` — unparsable xp output.
- `test_non_executable_binary_raises_cannot_execute` — an existing but
  non-runnable file fails start() with "cannot execute".
- `test_cycle_adc_and_gate_returns_ok_false_for_each_failure[error|drop|garbage]`
  and `..._clean_failure_for_a_monitor_never_started` — cycle never raises.
- `test_sweep_report_one_row_per_value_over_a_single_monitor` — Popen spy
  asserts exactly ONE launch for the whole sweep; one row per value.

### test_firmware_gpio.py — double narrowed to WIRING, order asserted
- `QemuMonitorDouble`: added a `calls` log (append in set_adc1_value,
  read_gate, stop) and a SCOPE docstring: it checks call ORDER only and must
  not be counted as emulator coverage. No behaviour it returned changed.
- `TestQemuGateBridge`: class docstring now states all four tests are wiring
  tests against the double, not emulator coverage.
- `test_cycle_adc_and_gate_flow`: added
  `assertEqual(mon.calls, ["set_adc1_value", "read_gate", "stop"])` — the
  order the old test never checked (it only asserted `injected` and
  `stopped`, which both hold even if read_gate ran first).
- `test_cycle_adc_and_gate_returns_a_clean_cycle`: added
  `assertEqual(mon.calls, ["set_adc1_value", "stop"])` — a failed injection
  must not read the gate.
- `test_sweep_report_returns_a_row_per_value`: added the full order ×3 and
  `assertEqual(mon.injected, [1900, 2012, 3456])`, so a sweep that silently
  dropped values now fails.
- No test was skipped, deleted or loosened in this file.

Result: `pytest tests/test_qemu_monitor_unit.py tests/test_firmware_gpio.py`
-> 49 passed. Mutation evidence for the new tests: tests/MUTATION_LOG.md
(4/4 mutations killed). Bridge bugs found while testing are recorded in
docs/KNOWN_ISSUES.md, NOT fixed here (bridge/ is out of this job's allowlist).
