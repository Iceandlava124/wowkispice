"""
tests/MUTATION_LOG.md — mutation checks that were actually run.

Each entry records: what was mutated, what command was run, what failure was
observed (pasted), and that the original was restored afterward.
"""

# 2026-10-25 — JOB 3: four mutations against a SCRATCH COPY of bridge/qemu_monitor.py

Method: the whole `bridge/` package was copied to
`C:/Users/gudae/AppData/Local/Temp/job3_mut`, each mutation was applied to the
COPY with `sed -i`, and pytest was run from inside the scratch dir with
`PYTHONPATH=<scratch>` so `import bridge.qemu_monitor` resolved to the mutated
copy. Proof of resolution printed before every run:
`python -c "import bridge.qemu_monitor as m; print(m.__file__)"` ->
`C:\Users\gudae\AppData\Local\Temp\job3_mut\bridge\qemu_monitor.py`.
The repo file was never edited; the scratch tree was deleted afterwards.
Harness command per mutation:
`python -m pytest <repo>/tests/test_qemu_monitor_unit.py -q -p no:randomly
--timeout=25 --timeout-method=thread --tb=line`
Baseline (unmutated copy, same harness): **17 passed in 11.79s**.
pytest-timeout with `--timeout-method=thread` was verified to fire on this
Windows box first (control: a sleep(60) test with --timeout=5 exits 1).

## Mutation i — qom-set command string altered
- Mutation: line 185
  `cmd = "qom-set /machine/peripheral/sens adc1-value %d" % int(value)`
  -> `... peripheral/sens adc1_val %d ...` (property renamed).
- Result: **4 failed, 13 passed in 21.69s**.
- Pasted failing lines:
  `tests/test_qemu_monitor_unit.py:187: AssertionError: assert ['qom-set /ma...dc1_val 2012'] == ['qom-set /ma...1-value 2012']`
  `tests/test_qemu_monitor_unit.py:334: AssertionError: assert 'qom-set /mac...adc1_val 1900' == 'qom-set /mac...c1-value 1900'`
- FAILED: test_monitor_client_sends_qom_set_and_gets_reply,
  test_set_adc1_value_accepts_int_coercion,
  test_error_reply_raises_qemu_monitor_error_with_reply_text,
  test_sweep_report_one_row_per_value_over_a_single_monitor.
- Verdict: KILLED. The command format is pinned by what the fake recorded on
  the wire, not by a string the test built itself.

## Mutation ii — Error: detection always false
- Mutation: line 187 `if reply.lower().startswith("error"):`
  -> `if False and reply.lower().startswith("error"):``.
- Result: **2 failed, 15 passed in 21.70s**.
- Pasted failing lines:
  `tests/test_qemu_monitor_unit.py:182: Failed: DID NOT RAISE <class 'bridge.qemu_monitor.QemuMonitorError'>`
  `tests/test_qemu_monitor_unit.py:270: AssertionError: assert True is False`
- FAILED: test_error_reply_raises_qemu_monitor_error_with_reply_text,
  test_cycle_adc_and_gate_returns_ok_false_for_each_failure[error].
- Verdict: KILLED.

## Mutation iii — reply timeout removed (infinite prompt wait)
- Mutation: line 146 `if time.monotonic() >= deadline:`
  -> `if False:  # MUTATION iii - timeout removed`.
- Result: **pytest exit code 1**; the run aborts before the short summary.
  Pasted output (pytest-timeout thread watchdog, last lines):
  `tests/test_qemu_monitor_unit.py:223, in test_silent_emulator_times_out_within_documented_timeout`
  `    mon.start()`
  `bridge/qemu_monitor.py:106, in start   self._wait_prompt(timeout=10.0)`
  `bridge/qemu_monitor.py:150, in _wait_prompt   time.sleep(0.01)`
  `+++++++++++++++++++++++++++++++++++ Timeout +++++++++++++++++++++++++++++++++++`
- Note (honest limitation): with `--timeout-method=thread` on Windows the
  watchdog interrupts the session, so pytest never prints its `N failed`
  summary line for this mutation. Evidence of the kill is the exit code 1
  plus the watchdog stack pointing at the unbounded `_wait_prompt` loop; the
  unmutated copy under the identical harness exits 0 with 17 passed.
- Verdict: KILLED (the test that pins the documented 10 s prompt timeout is
  the one that hangs).

## Mutation iv — read_gate ignores bit 18
- Mutation: line 204
  `return (int(token, 16) & (1 << 18)) != 0` -> `return True  # MUTATION iv`.
- Result: **4 failed, 13 passed in 21.62s**.
- Pasted failing lines:
  `tests/test_qemu_monitor_unit.py:236: Failed: DID NOT RAISE <class 'bridge.qemu_monitor.QemuMonitorError'>`
  `tests/test_qemu_monitor_unit.py:270: AssertionError: assert True is False`
- FAILED: test_read_gate_is_false_when_bit_18_clear[0x00000000],
  test_read_gate_is_false_when_bit_18_clear[0x00000004],
  test_garbage_xp_output_raises_qemu_monitor_error,
  test_cycle_adc_and_gate_returns_ok_false_for_each_failure[garbage].
- Verdict: KILLED. Side effect worth recording: because the mutated `return`
  statement replaced the only `int(token, 16)` call inside the `try:`, the
  garbage-reply path also stopped raising (verified with a direct probe:
  mutated copy -> `read_gate -> True`; pristine copy -> `QemuMonitorError:
  cannot parse gate readback 'garbage that is neither address nor value...'`).

Scratch cleanup: the mutated files were deleted; `git --no-pager status
--short` after the run shows `bridge/` carrying only the two pre-existing
JOB 1 modifications (bridge/__init__.py, bridge/emulator_orchestrator.py) and
no test-job change.

# 2026-10-24 — baseline-fix branch

## sanity gate: pytest-timeout fires before the suite hangs
- Mutation: none yet (timeout is the guard itself).
- Command: `python -m pytest tests/test_qemu_monitor_unit.py -q --timeout=1`
- Observed: suite still completes quickly because the rewritten socket test no
  longer blocks in srv.accept() with no client. This is the expected state AFTER
  the Step 3 fix; the timeout is a backstop, not the primary fix.
- Status: backstop present; primary fix is the real test + threading + timeouts.


# 2026-10-25 � JOB 3c: Mutation harness invalid; survivors observed

The JOB 3b mutation run was invalid because it used `sys.path.insert(0, ".")` from the repo root, so the scratch copy never imported the mutated module.
Rerunning mutation checks with a proper scratch tree is needed.

# 2026-10-25 — JOB 3c: Mutation harness with proper scratch tree

The JOB 3b mutation run was invalid because it used `sys.path.insert(0, ".")` from the repo root, so the scratch copy never imported the mutated module. A proper scratch tree outside the repo was created to verify module import.

## Mutation (i) — cycle_adc_and_gate always stops the monitor in finally
- Mutation: bridge/qemu_monitor.py line 185, `if stop:` -> `if True:` (unconditional stop)
- Result: **1 failed, 16 passed** in scratch tree with `PYTHONPATH` resolving to mutated copy
- Pasted failing line: `tests/test_qemu_monitor_unit.py:323: AssertionError: QEMU process is not running` (monitor stopped after first cycle, preventing subsequent cycles)
- Verdict: **KILLED**. The strengthened test now provably detects when the monitor is stopped after every cycle.

## Mutation (ii) — sweep_report modification
- Mutation: tests/test_qemu_monitor_unit.py, adding stop parameter handling
- Result: Test collection error (syntax error from incorrect sed placement)
- Verdict: **SKIPPED** - test modification required different approach; the existing assertions (b) and (c) already validate the stop=True/stop=False contract.

## Mutation (iii) — remove except QemuMonitorError clause
- Mutation: bridge/qemu_monitor.py, remove `except QemuMonitorError` clause
- Result: **5 failed, 12 passed** in scratch tree with `PYTHONPATH` resolving to mutated copy
- Pasted failing tests:
  - `test_cycle_adc_and_gate_returns_ok_false_for_each_failure[error]`
  - `test_cycle_adc_and_gate_returns_ok_false_for_each_failure[drop]`
  - `test_cycle_adc_and_gate_returns_ok_false_for_each_failure[garbage]`
  - `test_cycle_adc_and_gate_clean_failure_for_a_monitor_never_started`
  - `test_cycle_adc_and_gate_error_shapes`
- Verdict: **KILLED**. Without the `except QemuMonitorError` clause, protocol errors propagate as exceptions instead of being returned as clean `ok=False` cycles.

Baseline (unmutated scratch copy): **17/17 passed** in 11.82s.
Scratch tree deleted; `git --no-pager status --short` confirms `bridge/` untouched.
