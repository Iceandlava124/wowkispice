# Current status — generated 2026-11-01

`docs/SCORECARD.md` rows are **frozen** (owner decision): no further stacked
tables are appended there. This file is the live view. Every number below
names the activity-log entry it came from; `logs/activity.jsonl` is the
record, `tools/agentlog_verify.ps1` reports its integrity (exit 1 while the
two known problems from the seq-254 fork remain, on purpose — owner decision
Q5(a)).

## Row status

| Row | Status now | What changed / evidence |
| --- | --- | --- |
| R1 | **PASS** (re-scored 3/3 this session) | Three consecutive fresh `git clone --no-hardlinks` installs at HEAD `6628a89` - zero dev-tree files, clone tree proven empty by `CLONE_TREE_DIRTY=[]` - each ran `setup.ps1` then the full gate then `run_selfcheck.bat` and exited 0: **VERDICT PASS x3 with identical test counts 514 passed / 9 skipped / 58 subtests / 0 failed** (#557, #559, #560; wall 527 s / 784 s / 956 s; both ngspice downloads the same SHA-256 every run). The 9 clone skips are the artifact-dependent tests absent from a clone by design (4 firmware.elf, 4 WOSP_QEMU, 1 gitignored LTspice screenshot); the worktree's 519/4 (#532) differs from the clone's 514/9 only by those 5 artifact tests that pass where the artifacts exist. Scorecard row met with evidence: three consecutive installs reaching a passing verify with identical test counts - full table in the section below. |
| R2 | **PASS** (owner-measured 2026-10-31, #439-#441; recheck 1/3 this session) | Full gate at HEAD: **519 passed, 4 skipped, 33 warnings, exit 0, 178.20 s** (#532, HEAD `3454fbe`), reconfirmed 519/4 at HEAD `c4c16e4` (#570, 218.26 s); prior green 517 passed, 4 skipped, 130.10 s (#489). All 4 skips name the missing `qemu-system-xtensa`/firmware image. Test-count movement 512/3 -> 517/4 -> 519/4 reconciled below (owner decision 6). Open owner action Q7 (editor-crash root cause) unchanged - the crash did not recur. |
| R3 | **PASS** | Unchanged basis (19/19 mutants, coverage floors); this session's gate and the R6 suite run re-ran those modules green (#489, #492). |
| R4 | **PASS** | Unchanged (licence text quoted from files, hygiene vectors green); gate green (#489). |
| R5 | **PASS** | Unchanged (RC/RLC proofs with measured tolerances, NaN/Inf guard); gate green (#489). |
| R6 | **PASS** (PARTIAL lifted, re-scored this session) | Owner's R6* clause proven end-to-end: emulator route **4 contract tests passed, 0 skipped, `[GATE] all contract tests ran and passed`, exit 0** (#490), including `test_gate_follows_the_output_voltage_through_the_divider PASSED` - 3.21 V -> 1992 counts -> gate ON, 3.28 V -> 2035 counts -> gate OFF, back ON (`[True, False, True]`), derived by `binary_runner._adc_counts_from_voltage` (the `v_pin = sense * divider` law) before injection. Hand-derived conversion + error-surfacing suites: **58 passed** (#492). |
| R7 | **PASS** (re-measured this session, #534) | Threshold (SCORECARD: loop 10 times on the real emulator, recording gate-flip times, callback counts, latency distribution with a documented bound) measured through the tracked harness `tools/loop_repeat.py` (commits `afe2669` -> `fdd80c9` -> `3454fbe`): **10/10 runs error-free, 30/30 expected flips matched, flips_missed 0, panics 0, qemu alive at end 10/10**. Gate-flip times n=30: min 0.0203 s, mean 0.0217 s, p50 0.0205 s, p95 0.0218 s, max 0.051 s. Callbacks per run: gate_reads 60-65 (mean 61.7), adc_writes 4. Latency: read_gate n=617 mean 33.7 ms p50 40.3 p95 50.5 max 71.2; set_adc n=40 mean 14.7 ms p50 10.4 p95 31.2 max 40.4. run_s 3.29-4.31 (owner start state was 29.4 s), readiness_s 2.49-2.94, boot 0.56-1.15 s. Observed bound: flip latency <= 0.051 s. |
| R8 | **PASS** | Unchanged basis; orphan check after this session's full gate + emulator route: **zero** qemu/fake_hmp processes on Windows, none in WSL (the single `pgrep` hit was its own shell) (#491). |
| R9 | **PASS** | Unchanged. |
| R10 | **PASS** | Unchanged (traceability, guard suite, one-concern-per-commit). |
| R11 | **FAIL** (2 dirty files remain, both owner-forbidden) | The one committable dirty file is done: `bridge/qemu_orchestrator.py`'s 68-line duplicate-QemuMonitor copy was committed as `c4c16e4` (the names re-export from committed `bridge/qemu_monitor.py`; no code or test imports them from the orchestrator; 42 focused tests green; full gate **519 passed, 4 skipped, 0 failed** at the new HEAD, #570). Remaining dirty: `firmware/esp32_buck_controller/src/main.c` (owner restore) and `ui/schematic_editor.py` (owner decision 3: stays uncommitted) - both untouchable per the driver - plus 6 untracked paths (`.cloud-attachments/`, `.coverage`, `docs/ARCHITECTURE_LOOP.md`, `docs/WINDOWS_QEMU_BUILD.md`, `tools/cli.py`, `uv.lock`) that need an owner commit-or-skip decision. `ui/schematic_items.py`, `bridge/cosim_runner.py`, `bridge/qemu_orchestrator.py` left the dirty set via `e26e6d7` / `d69d98a` / `c4c16e4`. Owner start state also carries 34 line-ending violations and `tests/CHANGES.md` stored as binary. |
| R12 | **OWNER-SET** | Unchanged: `docs/REVIEW_BRIEF.md` delivered (`7f1251e`), owner schedules it. |

## Commits made this session (branch `baseline-fix`)

| Commit | Concern |
| --- | --- |
| `aa97db2` | agentlog: seq allocated after the command, under a mutex; verify exits non-zero (owner decision Q5a) |
| `10c42d0` | requirements.txt: PyYAML==6.0.3 pinned (owner decision Q2a) |
| `c7dc286` | run_tests.py writes the full pytest output under `logs\` |
| `6d57d47` | QemuMonitor.stop() tears down the whole process tree (red test first) |
| `d783da0` | Q4: divider-law tests pin 2048 counts and the 1995/2030 round trip |
| `4883f65` | setup.ps1: Get-NgspiceArchive returns the path alone (found by R1 run 1) |
| `f70f789` | tools/verify_clone.ps1: one R1 clone install, five steps, one verdict |
| `a43bfeb` | setup.ps1: bounded 3-attempt retry for HTML answers (owner action 1) |
| `6090ed9` | verify_clone keeps the clone's pytest output after the clone is gone |
| `79c9c46` | test: test_missing_qemu is hermetic about the firmware image (R1 finding) |
| `250dbf6` | test: the LTspice calibration test guards the images it actually reads (R1 finding) |
| `e26e6d7` | Q6: `ui/schematic_items.py` committed with its datasheet-symbol tests (proof-before-commit) |
| `d69d98a` | Q6: `bridge/cosim_runner.py` load_stepper kwarg with `test_load_step_injection` (proof-before-commit) |
| `fdd80c9` | R7: harness drops firmware-log-text dependence (text-free readiness probe; green 4/4, mutants M1-M4 killed, gate 518/4) |
| `3454fbe` | owner decision 4: R7_FLASH override, dummy flash in tmp_path, skip reason names `qemu_flash.bin` (M5/M6 killed, gate 519/4) |
| `6628a89` | docs: R7 re-scored PASS with the 10-run evidence; test-count reconciliation 512/3 -> 517/4 -> 519/4 (owner decision 6) |
| `8cec5c7` | docs: R1 re-scored PASS - three clone installs 3/3 at `6628a89` with identical 514/9 counts (#557, #559, #560) |
| `c4c16e4` | bridge: drop `qemu_orchestrator.py`'s duplicate QemuMonitor copy (68 dead lines; 42 focused tests green; gate 519/4 #570) |

Full gate after each group: 507 passed (#375) → 510 (#380) → 512 (#398) →
**512 passed, 3 skipped, 0 failed** after the last two commits (#414) →
517 passed, 4 skipped (#489) → 518 passed, 4 skipped (#518) →
**519 passed, 4 skipped, 0 failed** at HEAD `3454fbe` (#532), reconfirmed
**519 passed, 4 skipped, 0 failed** at HEAD `c4c16e4` (#570).
Clone installs: three scored runs at `6090ed9` (#403, #405, #406) plus one
confirmation run at `250dbf6` (#415).

## R1 as scored — three clone installs (`tools/verify_clone.ps1`)

Each run: `git clone --no-hardlinks -b baseline-fix` into `%TEMP%` (git
objects only — no venv, no logs, no uncommitted work), then `setup.ps1`,
the gate (`tools/run_tests.py`), the verify step (`run_selfcheck.bat`), then
a verdict of PASS only when all four exit 0. Network is only what
`setup.ps1` itself uses (ngspice URL, pypi.org — owner decision 5); every
archive is recorded with size and SHA-256. The clone is never edited.

| Run | Clone | Setup | Gate | Verify | Verdict | Wall time | Log entry |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 (2.5 s) | 0 (83 s) | 1 (127 s) — 491 passed, **5 failed**, 7 skipped | 1 (145 s) — SELF-CHECK: FAIL (1 of 5, test runner) | **FAIL** | 359 s | R1-RUN1G (#403), HEAD `6090ed9` |
| 2 | 0 (2.5 s) | 0 (84.0 s) | 1 (134.8 s) — 491 passed, **5 failed**, 7 skipped | 1 (135.5 s) | **FAIL** | 357 s | R1-RUN2 (#405), HEAD `6090ed9` |
| 3 | 0 (2.3 s) | 0 (79.8 s) | 1 (137.7 s) — 491 passed, **5 failed**, 7 skipped | 1 (132.5 s) | **FAIL** | 353 s | R1-RUN3 (#406), HEAD `6090ed9` |
| 4 (confirmation after the two test jobs) | 0 (1.5 s) | 0 (84.5 s) | 1 (136.8 s) — 492 passed, **3 failed**, 8 skipped | 1 (162.3 s) | **FAIL** | 385 s | R1-RUN4-CONFIRM (#415), HEAD `250dbf6` |
| 5 (re-score) | 0 (11.2 s) | 0 (125.3 s) | 0 (199.0 s) - **514 passed, 9 skipped**, 58 subtests | 0 (181.5 s) - SELF-CHECK: PASS | **PASS** | 527 s | R1-VERIFY-RUN5 (#557), HEAD `6628a89` |
| 6 (re-score) | 0 (3.5 s) | 0 (177.1 s) | 0 (280.3 s) - **514 passed, 9 skipped**, 58 subtests | 0 (306.2 s) - SELF-CHECK: PASS | **PASS** | 784 s | R1-VERIFY-RUN6 (#559), HEAD `6628a89` |
| 7 (re-score) | 0 (6.6 s) | 0 (353.6 s) | 0 (282.5 s) - **514 passed, 9 skipped**, 58 subtests | 0 (297.2 s) - SELF-CHECK: PASS | **PASS** | 956 s | R1-VERIFY-RUN7 (#560), HEAD `6628a89` |

Earlier, superseded attempts against older HEADs are kept in
`logs/r1-verify.txt` (they are what found the boolean leak and the missing
retry). Runs 1-4 are the superseded FAIL set - identical within each set
(same HEAD, same downloads, same five failing tests, same verdict).
**Runs 5-7 are the scored set**: same HEAD `6628a89`, same downloads (both
ngspice archives, same SHA-256), identical counts 514 passed / 9 skipped /
58 subtests, three PASS verdicts - meets the scorecard row (three
consecutive real clone installs reaching a passing verify step with
identical test counts) with evidence #557, #559, #560.

### The five gate failures, and what became of each

| Test | Cause | Disposition |
| --- | --- | --- |
| `TestBinaryRunner.test_missing_qemu` | clone has no `qemu_flash.bin` (gitignored); the firmware check runs before the `WOSP_QEMU` check | **fixed as a job** (`79c9c46`) - red in a clone (#407), green (#408), mutant killed (#409) |
| `TestCalibration.test_control_sits_in_the_same_band` | guarded on `docs/editor-*.png` but reads `docs/ltspice-reference/*.png`, which is gitignored on purpose | **fixed as a job** (`250dbf6`) - same red/green/mutation evidence |
| `test_doctor_runs_on_an_ascii_console` | `tools/doctor.py` is untracked | **Q6 owner decision** - it is in the commit list below |
| `test_doctor_source_is_pure_ascii` | `tools/doctor.py` is untracked | **Q6 owner decision** |
| `test_find_ngspice_honours_the_same_env_var_as_the_bridge` | `bridge/toolchain_resolver.py` is untracked | **Q6 owner decision** |

The self-check step (`run_selfcheck.bat`) reports `FAIL (1 of 5: test
runner)` in every run - the other four checks (interpreter, dependencies,
ngspice bind, known circuit) are green, and the bat now exits 1 as it must.

Run 4 is the confirmation after the two test jobs were committed: the two
fixed tests left the list (492 passed, 8 skipped - the calibration test now
skips with its stated reason), and **the only failures left are the three
untracked-file failures**. Nothing else separates a clone from a passing
gate at this HEAD - which is exactly what Q6 decides. Q6 committed those
three files in the 10-31 batch, and the re-score proves it: runs 5-7 all
exit 0 with identical counts.


## Q6 — untracked inventory, proposed disposition

Facts from job Q6-REASONS2 (#352), Q6-IMPORTS, Q6-IMPORTLINES, Q6-DOCTORREFS.

**Commit — a clone is broken without these, because tracked files use them:**

| Path | Reason |
| --- | --- |
| `bridge/toolchain_resolver.py` | `tests/test_tool_fixes.py:65` imports it and `setup.ps1:379` imports it — both tracked. |
| `tools/doctor.py` | `tests/test_tool_fixes.py` runs and reads it (lines 18–58); `setup.ps1:372` runs it. |
| `tools/cleanup_qemu.py` | `setup.ps1:358` runs it. |
| `tools/fetch_qemu.py` | `setup.ps1:365` runs it. |
| `tools/qualify_qemu.py` | `bridge/binary_runner.py:118` (tracked, clean) imports it; `tools/doctor.py:75` does too. |

These four are the reason R1's setup step cannot be clean today; they are the
"doctor / toolchain" work owner decision 2 already listed as finished (J7/J9).
`fetch_qemu.py` and `cleanup_qemu.py` are also named in `ROADMAP.md:66,73` as
done-with-annotations.

**Commit — self-contained test + module + fixture groups (atomic, all three
or none, otherwise collection breaks):**

| Path | Reason |
| --- | --- |
| `bridge/load_stepper.py` + `tests/test_load_step_injection.py` | test imports the module; `bridge/cosim_runner.py` (tracked) already calls it. |
| `tools/golden_trace.py` + `tools/capture_golden.py` + `tests/test_golden_traces.py` + `tests/golden/` (6 files, 1176 B) | test imports the module and reads the fixtures. |
| `tools/extract_datasheet_img.py` + `tests/test_datasheet_symbols.py` + `datasheets/` (1 file, 1166 B) | test imports the module and reads the fixture; `ui/schematic_items.py` (tracked) references it. |
| `tools/cli.py` | referenced by 9 tracked files incl. `bridge/cad_engine.py` and `tests/test_kicad_export.py`. |
| `docs/ARCHITECTURE_LOOP.md`, `docs/WINDOWS_QEMU_BUILD.md` | docs only, no dependency. |

Caveat for the last group: owner decision 2 says roadmap-added tools wait for
their own job to be DONE. `tools/doctor.py` is explicitly released; the other
four are forced by tracked callers — either they are committed, or a new job
amends `setup.ps1` / `tests/test_tool_fixes.py` to guard for their absence.

**Ignore:**

| Path | Reason |
| --- | --- |
| `.coverage` (53 KB) | coverage run artefact; `.gitignore:88` already declares coverage never-commit but has no pattern. Needs a one-line `.gitignore` addition (owner-approved like `.gitattributes`). |

**Delete (owner's call, no code depends on it):**

| Path | Reason |
| --- | --- |
| `uv.lock` (406 KB) | job Q6-REASONS2 found **no** `uv` reference in `setup.ps1`, `pyproject.toml` or `SETUP.md` — a stray lock from a tool the project does not use. |

**Owner keeps:** `firmware/esp32_buck_controller/src/main.c` is modified in the
worktree; owner decision Q6(a) says the owner restores it himself
(`git checkout -- firmware/esp32_buck_controller/src/main.c`). After all Q6
decisions, renormalise EOLs per `.gitattributes` (owner step, measured at 32
offenders in #240).

## Q7 — the memory-debugger question, facts only (no install, no editor fix)

The repo's own notes name three candidates (`docs/KNOWN_ISSUES.md:467`,
`docs/SCORECARD.md:538`). The practical one for a Windows access violation in
PyQt5/Qt DLLs is:

* **What it is:** Dr. Memory, a dynamic memory checker (uninitialised reads,
  use-after-free, invalid frees) for Windows/Linux binaries — same idea as
  valgrind, no recompilation needed.
* **Source:** `github.com/DynamoRIO/drmemory`. Latest release
  `cronbuild-2.6.20434` (published 2025-12-13).
* **Portable package (the one I propose):**
  `https://github.com/DynamoRIO/drmemory/releases/download/cronbuild-2.6.20434/DrMemory-Windows-2.6.20434.zip`
  — **111,924,507 bytes**, sha256
  `ed9c0e3f1bdb7f8db1adc13531493fb1c451e15f375638592c01d8837825a73a`.
* **Installer alternative (not proposed):** same release's `.msi`, 103,441,457
  bytes, sha256 `bd6e6eb2bfe466f839b1641e8ca8822aac1fdbf9e4a835abd34041a86cd7d531`
  — that one writes to Program Files (system-wide).
* **Footprint:** the zip is extracted into a local folder; nothing is installed
  system-wide, no service, no registry keys, no PATH change; delete the folder
  to remove it.
* **Command I would run** (after extracting to `tools\drmemory\`, outside the
  repo's tracked files):

  ```
  tools\drmemory\bin\drmemory.exe -logdir logs\drmemory -- .venv\Scripts\python.exe -m pytest tests -q
  ```

  scoped first to the reproducing pair if the full suite is too slow under
  instrumentation:
  `... -- .venv\Scripts\python.exe -m pytest tests/test_editor_workflow.py tests/test_ui_polish.py -q`.
* **Risk to state honestly:** Dr. Memory's Windows injection has reported
  failures on recent Windows builds, so this may return no report; the
  fallback is Application Verifier (part of the Windows SDK — installs
  system-wide) or the MSVC address sanitizer (needs a toolchain we do not
  have). Network host `github.com/DynamoRIO` is **not** in owner decision 5's
  approved list, so downloading it needs an explicit approval.

Crash as recorded (`docs/KNOWN_ISSUES.md:404-478`): Windows fatal exception —
access violation, `ui/schematic_editor.py:686 _run_in_worker` from
`run_simulation`, entered from `tests/test_editor_workflow.py:284` or
`tests/test_ui_polish.py:573`; full suite 4/4 crashes, `tools/run_tests.py`
2/2 (#134, #138), each file alone 0 crashes.

## R2 re-score (2026-10-31) - PASS

Command each time: `.venv\Scripts\python.exe tools\run_tests.py` through
`tools/agentlog.ps1`, transcripts in `logs/r2-run<N>-pytest.txt`.

| Run | Entry | Result | Duration | Exit |
|---|---|---|---|---|
| 1 | #439 | 512 passed, 3 skipped, 33 warnings | 238.96 s | 0 |
| 2 | #440 | 512 passed, 3 skipped, 33 warnings | 205.84 s | 0 |
| 3 | #441 | 512 passed, 3 skipped, 33 warnings | 210.34 s | 0 |

Clause by clause:

* **three consecutive runs, identical counts, zero failures** - 512/512/512
  passed, 3/3/3 skipped, 33/33/33 warnings (#439-#441).
* **zero flaky tests** - no test changed status across the three runs; the
  same three skips each time.
* **zero test files collecting 0 tests** - 515 collected, 34 test files on
  disk, 34 of them collecting >= 1 test, 0 empty (#442). `run_tests.py` only
  detects the *global* empty case, which is why this is measured separately.
* **every skip naming a missing binary** - all three read: `WOSP_QEMU not set
  and no qemu-system-xtensa in PATH or the working directory (Track B:
  tools/run_emulator_tests.ps1, see SETUP.md)`.

Honest caveats: (1) the three runs exercised this worktree, which still
carries the pre-existing uncommitted modifications (`main.c`,
`ui/schematic_editor.py`, `ui/schematic_items.py`, `bridge/cosim_runner.py`,
`bridge/qemu_orchestrator.py`) - what a *clone* runs is R1's question;
(2) the 2026-10-28/29 editor crash that made this row FAIL then has not
recurred in these runs, but its root cause is still open under Q7, so the
row is PASS **on its stated threshold**, not a claim that the defect is
understood.

## Test-count reconciliation 512/3 -> 517/4 -> 519/4 (owner decision 6)

The naive reading "+18 test defs landed between `f2fc456` and `55c44f1` but
only +5 passed" is reconciled by counting collected *items* rather than defs,
and by what was on disk when the baseline ran. Evidence: #538 (test-touching
diffs), #539 (per-commit defs via `git show`, no checkout), #540
(collect-only at HEAD), #541 (the arithmetic below, all MATCH), plus
agentlog `??` status tails (#1, #64, #304, #305, #327) and the 12-test
collect at #275.

1. **Defs per commit** (#539): `f2fc456` = 496, `55c44f1` = 514,
   `fdd80c9` = 515, `3454fbe` = 516.
2. **Constant item gap of 7.** The two parametrize-bearing files
   (`tests/test_qemu_monitor_unit.py`, `tests/test_solver_error_handling.py`)
   are byte-identical `f2fc456..HEAD` (#541), so the gap is the same now as
   at the baseline: collect-only at HEAD is 523 items vs 516 defs (#540) ->
   gap 7. `tests/` is also byte-identical `250dbf6..f2fc456` (#541), so the
   #414 tracked state equals `f2fc456`'s.
3. **The baseline run counted 12 uncommitted defs.** 512 passed + 3 skipped
   = 515 items, minus 496 tracked defs, minus the 7-item gap = 12 - exactly
   `test_datasheet_symbols.py` (8) + `test_golden_traces.py` (2) +
   `test_load_step_injection.py` (2). Those three files sat **untracked on
   disk** during #414/#439-#441 (agentlog `??` tails from #1 through #327;
   they collect 12 tests at #275) and were only committed in the 10-31 10:24
   Q6 batch (`cec64b7`, `8c63fe8`, `080dea9`).
4. **Committed evolution** (#541): 496 + 18 = 514 defs -> 514 + 7 = 521
   items = 517 passed + 4 skipped (#489). Of the +18 defs, 12 were already
   counted in the baseline as untracked files, so the genuinely new items
   are 6: two gate-flip voltage tests and the R7 divider qemu test
   (`c731125`) plus three harness tests (`afe2669`). The divider qemu test
   skips without the firmware image, so skips go 3 -> 4 and passed goes
   512 -> 517. `fdd80c9` adds the no-log-text harness test -> 518/4 (#518).
   `3454fbe` adds the skip-reason naming test -> **519/4 = 523 items =
   516 defs + 7** (#532, #540). All three equalities MATCH.

## R6 re-score (2026-10-31) - PASS

Route: the command the tests document, through `tools/run_emulator_tests.ps1`
(#419, exit 0):

```
locator: WSL filesystem probe -> <wsl-home>/repro/src/build/qemu-system-xtensa
python3 -m pytest tests/test_qemu_monitor_qemu.py -v   (inside WSL)
3 passed, 0 skipped  /  [GATE] all contract tests ran and passed (0 skips)
```

Threshold measurement on the real firmware (#420, `logs/cmd/r6_probe.py`
driving `binary_runner.test_gate_flip`), against `main.c`'s
`raw < 1995 -> ON`, `raw > 2030 -> OFF`, else hold:

| injected counts | expected (main.c) | measured gate |
|---|---|---|
| 1994 | ON (below 1995) | True |
| 2031 | OFF (above 2030) | False |
| 1994 | ON again | True |
| 1995 / 2030 / 1995 | hold (inside the band) | True / True / True |

Both cases PASS with `errors=[]`. Case A flips while case B holds, which is
what rules out a stale read: the reading follows the injected counts.

Clause 3 of the row (errors surfaced, never swallowed): the raising paths are
`qemu_monitor.py:138,152,210,260,278,299,304`; the assertions live in
`tests/test_qemu_monitor_unit.py` (lines 115-127, 184-185, 206-207, 224,
233-239, 246-251, 403-410) and were all green inside the 512-passed gate
(#414). 41 tests collect across the four R6 files (#425).

R7's harness is now tracked at HEAD (`afe2669` -> `fdd80c9` -> `3454fbe`)
and its 10-run determinism measurement is re-done through it (#534); R6's
own evidence path is tracked and clean.

## R11 clause measurements (2026-10-31)

| Clause | Result | Evidence |
|---|---|---|
| no tracked file > 5 MB | PASS | 176 tracked files, none over 5 MB (#421) |
| no scratch files | PASS | name matches were `bug_report.yml` (matched `temp` inside `ISSUE_TEMPLATE`) and `tests/hidpi_probe.py`, used by `tests/test_ui_polish.py:824,844` and `ui/schematic_editor.py:4329` (#421, #423) |
| line endings per `.gitattributes` | FAIL | 34 violations (#424): 25 files with `eol=lf` but CRLF on disk, 9 with `eol=crlf` but LF on disk (`setup.ps1`, `run_*.bat`, `tools/*.ps1`, `verify_clone.ps1`); plus `tests/CHANGES.md` stored `i/-text` (#426-#429). `.gitignore` is CRLF but no rule covers an extensionless file, so it is not a violation |
| clean tree | FAIL | Q6 untracked set, `.coverage`, `main.c` owner restore |

Method note, recorded honestly: the first pass (#421) used a regex that only
matched lines *starting* with `i/crlf` and undercounted (reported 1); #424
parses both tokens and is the number above. Two logged jobs (#422, #427)
failed with exit -196608 because I invoked a script before it finished
writing - a harness race of mine, kept in the log rather than hidden; the
reruns (#423, #428) succeeded.

## Open owner actions

1. **Q6 decisions** — approve/dispose each row of the inventory above, then
   renormalise EOLs (owner step).
2. **Q7 decision** — approve (or refuse) the Dr. Memory run above, including
   the extra download host; approve or refuse the hunk-staged
   `ui/schematic_editor.py` fix.
3. **main.c restore** — owner runs
   `git checkout -- firmware/esp32_buck_controller/src/main.c` (J2, Q6a).
4. ~~R7 harness~~ - **done**: `tools/loop_repeat.py` +
   `tests/test_loop_repeat.py` are tracked (`afe2669`, `fdd80c9`,
   `3454fbe`); the 10-run measurement through the tracked harness is #534.
5. **R12** — schedule the human review (`docs/REVIEW_BRIEF.md`).
6. ~~Logger commit~~ - **done**: `aa97db2` carries the Q5(a) fix; both files
   are tracked and clean.
7. **EOL renormalise (owner step) - two caveats measured today**: (a) 9 files
   carry `eol=crlf` but are LF on disk (`setup.ps1`, `run_*.bat`,
   `tools/*.ps1`), so the step must restore CRLF, not only strip it;
   (b) `git add --renormalize .` will **not** fix `tests/CHANGES.md` - git
   classifies it `-text`, so its bytes are stored as-is (51 CRLF lines + 5
   lone CR bytes inside the blob, #426-#429). That file needs a content
   rewrite to LF.
