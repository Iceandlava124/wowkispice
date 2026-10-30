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
'

### test_sweep_report_one_row_per_value_over_a_single_monitor � STRENGTHENED (JOB 3c)
- What it tested: sweep_report() over a single running monitor with three ADC values (1900, 2012, 3456), asserting every row ok=True, gate_high is a bool, the fake recorded exactly three qom-set ADC value commands in order, exactly one Popen launch for the entire sweep, and the monitor still running afterwards (poll() is None).
- Change: added assertions (b) and (c) about cycle_adc_and_gate stop behavior (stop=False leaves monitor running, stop=True stops it), and assertion (d) about sweep with pipe drops where fake drops pipe after second command yielding rows ok=True, ok=False, ok=False. Also moved monitor lifecycle management to after assertions to verify monitor was NOT stopped by the bug where cycle_adc_and_gate stops after every cycle.
- Justification: the original test only asserted "first cycle ok=True" and did not verify the monitor lifecycle; the strengthened test now provably validates the stop=False/stop=True contract added in JOB 3b.
- Related: JOB 3b added  parameter to ; JOB 3c strengthens the tests to provably validate the fix.


### test_sweep_report_one_row_per_value_over_a_single_monitor — STRENGTHENED (JOB 3c)
- What it tested: sweep_report() over a single running monitor with three ADC values (1900, 2012, 3456), asserting every row ok=True, gate_high is a bool, the fake recorded exactly three qom-set ADC value commands in order, exactly one Popen launch for the entire sweep, and the monitor still running afterwards (poll() is None).
- Change: added assertions (b) and (c) about cycle_adc_and_gate stop behavior (stop=False leaves monitor running, stop=True stops it), and assertion (d) about sweep with pipe drops where fake drops pipe after second command yielding rows ok=True, ok=False, ok=False. Also moved monitor lifecycle management to after assertions to verify monitor was NOT stopped by the bug where cycle_adc_and_gate stops after every cycle.
- Justification: the original test only asserted "first cycle ok=True" and did not verify the monitor lifecycle; the strengthened test now provably validates the stop=False/stop=True contract added in JOB 3b.
- Related: JOB 3b added `stop` parameter to `cycle_adc_and_gate`; JOB 3c strengthens the tests to provably validate the fix.


### tests/test_ngspice_sanitiser.py - NEW - sanitiser validation
- What it tests: 17 tests validating the ngspice input sanitiser.
- Why changed: New test file for JOB 4 ngspice sanitiser.
- New assertions: .control and .endc banned, run/alter/bg_run/destroy allowed,
  .tran/.ac/.dc/.op/.model/.measure allowed, unknown directives pass through.

### tests/test_closed_loop_buck.py - NEW class TestGetSyncDataArityMatchesHeader (JOB 1: hang regression)

- What it tests: that `GetSyncData_t` in bridge/ngspice_wrapper.py matches the C
  typedef shipped in `tools/ngspice_dll/Spice64_dll/include/ngspice/sharedspice.h:319`
  (`typedef int (GetSyncData)(double, double*, double, int, int, int, void*);`) -
  the return type, all seven parameter types, and an actual call with all seven
  arguments.
- Why added: the JOB 1 hang was a CFUNCTYPE declaration missing one parameter, so
  ctypes read the wrong stack frame inside ngspice and `ngSpice_Command("run")`
  never returned. Nothing guarded that declaration. Reintroducing the defect in a
  scratch copy reproduces the hang 3/3 times at the reported stack
  (`mock_controller.py:156` -> `ngspice_wrapper.py:328`).
- New assertions (all `@pytest.mark.timeout(30)`):
  (a) `len(GetSyncData_t._argtypes_) == 7` and `GetSyncData_t._restype_ is ctypes.c_int`;
  (b) each `_argtypes_` entry equals the ctypes type for the header's C type at that
      position (double, double*, double, int, int, int, void*);
  (c) invoking the callback with all seven arguments reaches the Python handler and
      returns 0.
- Two assumptions in the FIRST draft were wrong and are corrected here, both after
  measuring rather than guessing:
  * old assertion: `len(_argtypes_) == len(header params) + 1`, treating the return
    type as `_argtypes_[0]` - WHY WRONG: `ctypes.CFUNCTYPE` stores the return type in
    `_restype_`, not `_argtypes_` (measured: `logs/cmd/probe_cfuntyp.py` printed
    `_argtypes_ len = 7` and `_restype_ = c_long` for a declaration built from the
    header signature). NEW assertion: `len(_argtypes_) == len(header params)` plus a
    separate `_restype_ is ctypes.c_int` check.
  * old assertion: `declared[0] is ctypes.c_int` as the return type - WHY WRONG:
    `declared[0]` is the first parameter, not the return type, so it compared
    `c_double` against `c_int` and also sliced `[1:]` off a list that never contained
    a return type. NEW assertion: no slice; compare all seven entries positionally.
  * also measured: on this Windows build `ctypes.c_int is ctypes.c_long` (identical
    ids), so the header's `int` maps to the object printed as `ctypes.c_long`. The
    mapping in the test therefore uses `ctypes.c_int`, which is the same object.
- Not weakened: no existing assertion in this file was changed or removed; the
  original `TestThresholdsMatchFirmware` and `TestClosedLoopBuck` tests are untouched
  and still pass.

### tests/test_ngspice_sanitiser.py - NEW TESTS (JOB 4)
- Why: the sanitiser draft rejected `.meas` (ngspice's alias of `.measure`) and
  blanket-banned `.include`, which broke 4 real tests:
  tests/test_components_library.py::test_dc_motor_model,
  tests/test_components_library.py::test_opamp_model (both use
  `.include "<abs path>/circuits/components/models.lib"`), and
  tests/test_ui_polish.py::TestMeasEquivalentDiscoverability::test_meas_results_include_the_value_and_the_time
  and ::test_run_edited_netlist_executes_meas_and_prints_results
  (netlist uses `.meas tran ...` at tests/test_ui_polish.py:1346-1350).
  Exact failure before the fix: `RuntimeError: ngSpice_Circ rejected the
  untrusted netlist: banned directive @line: .include` / `... @line: .meas`.
- Old assertion: none existed - these are new tests; the old suite had no
  coverage for the .meas alias or the .include directory policy.
- New assertions: .meas/.MEAS pass through unchanged; .include/.lib are
  accepted only for the allowlisted circuits/components directory (relative
  and absolute forms); an outside path, a `..` traversal, and a bare
  `.include` with no argument each raise RuntimeError naming the reason;
  ALLOWED_INCLUDE_DIRS contains exactly one directory and the listed library
  file really exists on disk.
- Every new test carries @pytest.mark.timeout(30). No existing test was
  weakened, skipped or deleted.
- Mutation evidence: tests/MUTATION_LOG.md (2026-10-27 JOB 4, 4/4 killed).

### tests/test_tool_fixes.py - NEW TESTS (J7 + J9 queued fixes)
- Why: tools/doctor.py crashed on a cp1252 console (non-ASCII glyphs) and
  discovered ngspice through a dead glob list instead of the bridge's
  resolve_ngspice_library(); tools/check_traceability.py exited 0 while
  parsing 0 requirements and 0 marked tests (false green, recorded in J11).
- Old assertion: none existed - these are new tests; no existing test changed.
- New assertions: doctor runs under PYTHONIOENCODING=ascii with no
  UnicodeEncodeError and prints the ASCII "[OK]" tag; doctor.py source is
  pure ASCII; ToolchainResolver().find_ngspice() equals
  resolve_ngspice_library() under WOSP_NGSPICE_LIB and flows into get_status();
  check_traceability exits non-zero with "parsed 0 requirements" on an empty
  table, non-zero with "cannot read" on a missing file, non-zero with
  "0 tests carrying" when no marked test ran, and still exits 0 for a complete
  mapping (control).
- Mutation evidence: tests/MUTATION_LOG.md (2026-10-27 J7/J9, 2/2 killed after
  strengthening the doctor test, survivor recorded honestly).

### tests/test_ngspice_sanitiser.py - TEST CHANGED + NEW TESTS (JOB 4 3b/3c)
- Changed: `test_include_relative_to_repo_root_is_allowed` (this job's own
  test from the allowlist pass). Old assertion: `_sanitise_line` returns the
  line unchanged. Why wrong: leaving the relative string intact lets ngspice
  resolve the same text against ITS own working directory instead of the file
  that was validated. New assertion: the line is rewritten to
  `.include <absolute realpath of circuits/components/models.lib>`, i.e. the
  validated path.
- New tests (all @pytest.mark.timeout(30)/timeout(60)):
  TestIncludedFileContent - a .control block inside an allowed included file
  is rejected by _sanitise_line AND by the full engine.load_circuit path, with
  the offending file named in the error, and the marker payload never runs;
  a nested include inside the allowlist is allowed; a self-including file
  fails with the 'nesting exceeds' depth message; a missing file inside the
  allowed directory is rejected as 'not found'. Temp libs are written under
  circuits/components with a __tmp_s3b_scan_ prefix and removed in tearDown,
  which also fails if any prefix-matching file survives.
  TestIncludeCwdIndependence - a subprocess started in a foreign temp cwd runs
  the same accept/rewrite/reject checks and prints cwd/root proofs.
- Evidence for WHY: logs/job S3B-INCLUDE - before the fix, the temp library's
  .control block EXECUTED on both HEAD and the draft (marker file created,
  `PWNED` printed); temp lib cleaned up: True.
- Mutation evidence: tests/MUTATION_LOG.md (2026-10-27 3b/3c, 7/7 killed).

## 2026-10-31 — divider convention pinned through run_binary_cosim (Q4)

### test_solver_error_handling.py::test_a_finite_value_still_converts — EXPECTATION UPDATED
- What it tested: after the non-finite rejection tests, the working path
  asserted `_adc_counts_from_voltage(0.825) == 2048`, i.e. it pinned
  binary_runner's INVERTED divider arithmetic (`v_adc = v_sense /
  divider`), with a comment claiming the half-scale pre-divider input is
  0.825 V.
- Why: owner decision Q4(a), after the derivation from the board
  netlist and firmware: circuits/buck_converter.cir wires a 100k/100k
  pair so fb = vout/2, and main.c's thresholds 1995/2030 are raw counts
  at the ADC pin (3.3 V reference, 12-bit). The documented law in
  bridge/control_law.py is `v_pin = sense_net * divider`, which
  binary_runner contradicted. Half scale at the PIN is 1.65 V, so the
  half-scale value on the PRE-divider node (vout) is 3.3 V, not 0.825 V.
- Replacement: the assertion is now
  `_adc_counts_from_voltage(3.3) == 2048`. The rounding/clamp
  behaviour under test is unchanged; only the node convention moved.
  The new end-to-end pin is tests/test_binary_runner.py
  ::TestDividerSemantics, which forces vout = 3.3 V and asserts the
  injected count is 2048 (it failed with 4095 under the old divide,
  job JOBB-RED). Companion derivation evidence: job Q4-DERIVE.
- Guarded by: TestDividerSemantics (mon injection) + the unchanged
  control_law-side tests (test_adc_conversion, test_control_law_unit).
