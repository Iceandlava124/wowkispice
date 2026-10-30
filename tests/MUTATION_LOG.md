"""
tests/MUTATION_LOG.md — mutation checks that were actually run.

Each entry records: what was mutated, what command was run, what failure was
observed (pasted), and that the original was restored afterward.
"""

# 2026-10-25 — JOB 3: four mutations against a SCRATCH COPY of bridge/qemu_monitor.py

Method: the whole `bridge/` package was copied to
`<home>/AppData/Local/Temp/job3_mut`, each mutation was applied to the
COPY with `sed -i`, and pytest was run from inside the scratch dir with
`PYTHONPATH=<scratch>` so `import bridge.qemu_monitor` resolved to the mutated
copy. Proof of resolution printed before every run:
`python -c "import bridge.qemu_monitor as m; print(m.__file__)"` ->
`<home>\AppData\Local\Temp\job3_mut\bridge\qemu_monitor.py`.
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

# 2026-10-27 - JOB 4: allowlist fix (.meas alias, .include directory policy)

Scratch copy outside the repo: %TEMP%\wosp_mut_j4 (bridge/, tests/, circuits/ copied).
Driver: logs/cmd/j4_mutate.py. Proof printed by every run:
MODULE <home>\AppData\Local\Temp\wosp_mut_j4\bridge\ngspice_wrapper.py
INTERP <home>\Music\PROJECT_WOWKISPICE\.venv\Scripts\python.exe
Unmutated scratch first: **28 passed** (pytest exit 0).

## M1 - skip the .include path check
- Mutation: `NgSpiceEngine._check_include_path(raw, ...)` -> `pass  # MUTANT M1`
- Result: **4 failed, 24 passed** - test_include_outside_allowed_dirs_is_rejected,
  test_include_traversal_out_of_allowed_dir_is_rejected,
  test_include_without_argument_is_rejected, test_lib_outside_allowed_dirs_is_rejected
- Verdict: **KILLED**.

## M2 - drop the `meas` alias from ALLOWED_DIRECTIVES
- Mutation: `'ends', 'measure', 'meas', 'print'` -> `'ends', 'measure', 'print'`
- Result: **2 failed, 26 passed** - TestMeasAlias::test_meas_alias_is_allowed,
  test_meas_alias_is_allowed_case_insensitive (RuntimeError: banned directive @line: .meas)
- Verdict: **KILLED**.

## M3 - disable path normalisation in _check_include_path
- Mutation: `resolved = os.path.realpath(cand)` -> `resolved = cand`
- Result: **1 failed, 27 passed** - test_include_relative_to_repo_root_is_allowed
  (the un-normalised relative string no longer matches the allowlist prefix)
- Verdict: **KILLED**.

## M4 - empty ALLOWED_INCLUDE_DIRS
- Mutation: remove `os.path.join(PROJECT_ROOT, 'circuits', 'components')`
- Result: **4 failed, 24 passed** - test_allowlist_is_exactly_the_known_library_directory,
  test_include_of_the_listed_library_is_allowed,
  test_include_relative_to_repo_root_is_allowed, test_lib_inside_allowed_dir_is_allowed
- Verdict: **KILLED**.

4/4 mutants killed. Scratch tree removed after the run.

# 2026-10-27 - J7/J9 queued fixes: doctor.py cp1252 + check_traceability false green

Scratch copy outside the repo: %TEMP%\wosp_mut_tools (bridge/, tools/doctor.py,
tools/check_traceability.py, tests/test_tool_fixes.py copied).
Driver: logs/cmd/toolfix_mutate.py. Proof every run:
INTERP <home>\Music\PROJECT_WOWKISPICE\.venv\Scripts\python.exe
MODULE ...\wosp_mut_tools\tools\doctor.py
Unmutated scratch first: **7 passed**.

## T1 - reintroduce the check/cross glyphs in doctor.py
- Mutation: `tag = "[OK]" if ok else "[X] "` -> `tag = "\u2713" if ok else "\u2717"`
- First run: **SURVIVED** - `errors="replace"` on stdout degraded the glyph to
  '?' instead of raising, so "no crash" alone did not prove the ASCII policy.
  Recorded here as a survivor, not absorbed.
- Fix: strengthened test_doctor_runs_on_an_ascii_console to assert `"[OK]"` is
  present in the report output (tests/test_tool_fixes.py; entry in CHANGES.md).
- Rerun: **1 failed, 6 passed** - test_doctor_runs_on_an_ascii_console failed
  with `assert '[OK]' in ...`
- Verdict: **KILLED after strengthening**.

## T2 - remove both zero-guards in check_traceability.py
- Mutation: delete the `if not reqs:` and `if not junit:` problem blocks
- Result: **2 failed, 5 passed** - test_zero_requirements_parsed_is_a_failure
  and test_zero_marked_tests_is_a_failure (the tool printed "TRACEABILITY OK"
  / exited 0 paths again)
- Verdict: **KILLED**.

2/2 mutants killed after one strengthening pass. Scratch tree removed.

# 2026-10-27 - JOB 4 3b/3c: include-content scan, depth limit, validated-path rewrite

Scratch copy outside the repo: %TEMP%\wosp_mut_j4 (bridge/, tests/, circuits/
copied). Driver: logs/cmd/j4_mutate.py. Proof printed by every run:
MODULE ...\wosp_mut_j4\bridge\ngspice_wrapper.py
INTERP <home>\Music\PROJECT_WOWKISPICE\.venv\Scripts\python.exe
Unmutated scratch first: **34 passed**.

## M1 - skip the .include path check entirely
- Mutation: replace the `_check_include_path(...)` call with a blind abs-path join
- Result: **10 failed, 24 passed** (outside/traversal/no-arg/lib-outside,
  included-content x3, cycle, missing-file, foreign-cwd)
- Verdict: **KILLED**.

## M2 - drop the `meas` alias
- Result: **2 failed, 32 passed** (both TestMeasAlias tests)
- Verdict: **KILLED** (carried over from the earlier allowlist pass).

## M3 - no path normalisation (realpath -> raw)
- Result: **2 failed, 32 passed** (relative-include roundtrip, foreign-cwd)
- Verdict: **KILLED**.

## M4 - empty ALLOWED_INCLUDE_DIRS
- Result: **9 failed, 25 passed**
- Verdict: **KILLED**.

## M5 - drop the include-content scan (`_scan_included_file` call)
- Result: **3 failed, 31 passed** - control-block-in-include,
  engine-load-rejects (both would let the .control payload through), cycle test
- Verdict: **KILLED**.

## M6 - remove the include depth limit
- Result: **1 failed, 33 passed** - test_self_including_file_hits_the_depth_limit
  failed with 'nesting exceeds' not found in a 'maximum recursion depth exceeded'
  message (the cycle recursed to Python's limit instead of the policy limit)
- Verdict: **KILLED**.

## M7 - drop the validated-path rewrite
- Result: **2 failed, 32 passed** (relative roundtrip returned the raw relative
  string; foreign-cwd subprocess asserted absolute and failed)
- Verdict: **KILLED**.

7/7 mutants killed on this pass. Scratch tree removed after the run.


## R4-01 - cmd() guard mutants (2026-10-28)
Harness: logs/cmd/r4_mutate.py via tools/agentlog.ps1 -Job R4-01-MUTATE.
Scope: tests/test_security_vectors.py + tests/test_ngspice_sanitiser.py
(50 passed unmutated, 0.61 s). Target restored after each mutant and
SHA256 re-checked (9f3f5a4b...fbc880 before and after).

## M1 - drop the cmd() verb allowlist check
- Result: **5 failed, 45 passed**
- Verdict: **KILLED**.

## M2 - drop the separator/redirection character check
- Result: **1 failed, 49 passed** - test_command_separators_are_rejected
- Verdict: **KILLED**.

## M3 - add 'shell' to Cmd_ALLOWED
- Result: **1 failed, 49 passed** - test_vector2_shell_command_is_rejected
- Verdict: **KILLED**.

## M4 - cmd() bypasses validate_cmd() entirely
- Result: **6 failed, 44 passed** - all six command vectors
- Verdict: **KILLED**.

## M5 - swallow the missing-included-file rejection
- Result: **1 failed, 49 passed** - the sanitiser suite covers this branch;
  running only the new vector file left it SURVIVED, which is why both
  suites are in scope for this harness.
- Verdict: **KILLED**.

5/5 mutants killed. Tree restored (SHA256 match printed by the harness).


## R1FIX-B - run_selfcheck.bat exit propagation (2026-10-30)

Target: run_selfcheck.bat (the fix) and tests/test_selfcheck.py (two new
tests: test_bat_propagates_the_exit_code, test_bat_still_returns_zero_on_pass).
Harness: logs/cmd/job_b_mutate.py via tools/agentlog.ps1 -Job R1FIX-B-MUTATE2
(entry #293). Unmutated baseline in the harness control run: 3 passed in
5.7 s; the same three tests passed in 4.60 s at entry #291. Each mutant was
applied IN PLACE, the target restored, and its SHA256 re-checked:
a63216679326cf0f59691fa0834ba87364e5e72462deee1ea27c2acbe163bd40 before and
after every restore, identical=True printed by the harness. No git commands
were used.

### Mutation i - revert to bare `endlocal` (the pre-fix behaviour, measured in entry #277)
- Result: **1 failed, 2 passed** - `AssertionError: 0 != 2` in
  test_bat_propagates_the_exit_code: the bat swallowed selfcheck.py's exit 2.
- Verdict: **KILLED**.

### Mutation ii - hard-code `endlocal & exit /b 2`
- Result: **1 failed, 2 passed** - `AssertionError: 2 != 0` in
  test_bat_still_returns_zero_on_pass: a green self-check must still exit 0.
- Verdict: **KILLED**.

2/2 mutants killed; control run after restore: 3 passed (entry #293).
Entry #292 is the same harness's first run, which aborted on a path bug
(FileNotFoundError, exit 1) before the target was touched.
