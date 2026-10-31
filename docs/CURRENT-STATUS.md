# Current status — generated 2026-10-31

`docs/SCORECARD.md` rows are **frozen** (owner decision): no further stacked
tables are appended there. This file is the live view. Every number below
names the activity-log entry it came from; `logs/activity.jsonl` is the
record, `tools/agentlog_verify.ps1` reports its integrity (exit 1 while the
two known problems from the seq-254 fork remain, on purpose — owner decision
Q5(a)).

## Row status

| Row | Status now | What changed / evidence |
| --- | --- | --- |
| R1 | **RE-RUNNING (3 installs in progress)** | The three recorded causes of the last FAIL are fixed and committed: setup.ps1 rejects a non-archive download (`994ca91`), `run_selfcheck.bat` propagates the real exit code (`4786bb2`), PyYAML is pinned in `requirements.txt` so a clone can collect (owner decision Q2a, `10c42d0`). This session added two more fixes found by the first clone install: `Get-NgspiceArchive` no longer leaks the validator's boolean (`4883f65`, entry #374), and a bounded 3-attempt retry covers SourceForge's HTML answers (`a43bfeb`, entry #393). Results in the table below. |
| R2 | **BLOCKED (owner)** | Unchanged. Two owner questions open: (Q7) approve a memory-debugger run — facts gathered, see below; approve a hunk-staged fix to `ui/schematic_editor.py`. No source change made (owner: "do not apply the editor fix"). |
| R3 | **PASS** | Unchanged. 19/19 mutants, coverage floors met, `pytest-cov` + `PyYAML==6.0.3` pinned. |
| R4 | **PASS** | Unchanged (licence text quoted from files, hygiene vectors green). |
| R5 | **PASS** | Unchanged (RC/RLC proofs with measured tolerances, NaN/Inf guard). |
| R6 | **PASS** (re-scored 2026-10-31) | Route run through `tools/run_emulator_tests.ps1`: WSL locator found `/home/user/repro/src/build/qemu-system-xtensa`, **3 contract tests passed, 0 skipped, `[GATE] all contract tests ran and passed`, exit 0** (#419). Threshold probe on the real firmware (#420): `1994 -> ON`, `2031 -> OFF`, `1994 -> ON` flips across the band, and `1995/2030/1995` all hold - exactly `main.c`'s `raw < 1995` / `raw > 2030` rule. Hand-derived conversion expectations: 12 closed-form tests in `tests/test_adc_conversion.py` plus `TestDividerSemantics` (`d783da0`, #360/#361). Errors surfaced: `qemu_monitor.py:138,152,210,260,278,299,304` asserted in `tests/test_qemu_monitor_unit.py` (#414 gate, 41 tests collect across the four R6 files, #425). |
| R7 | **FAIL (reproducibility)** | Unchanged blocker: the harness `logs/cmd/r7_loop10.py` is covered by `.gitignore:58 logs/` (job Q1-CommittedStatus), so a clone cannot reproduce #207. Needs a job that moves the harness out of `logs/` (owner approval — it also changes `.gitignore`). |
| R8 | **PASS** | Unchanged, plus this session's teardown leak: red test first (#310, leaked pid 22836), fix, green (#314, #316), mutation 1/1 killed with byte-identical restore (#317). |
| R9 | **PASS** | Unchanged. |
| R10 | **PASS** | Unchanged (traceability, guard suite, one-concern-per-commit). |
| R11 | **FAIL** (all four clauses now measured) | clean tree: FAIL (Q6 untracked set, `.coverage` still unignored, `main.c` owner restore). No tracked file > 5 MB: **PASS** - 176 tracked files, none over 5 MB (#421). No scratch files: **PASS** - the only name matches were `bug_report.yml` (matched `temp` inside `ISSUE_TEMPLATE`) and `tests/hidpi_probe.py`, which `tests/test_ui_polish.py:824,844` and `ui/schematic_editor.py:4329` use (#421, #423). Line endings per `.gitattributes`: **FAIL** - 34 violations (#424): 25 files with `eol=lf` but CRLF on disk, 9 with `eol=crlf` but LF on disk; plus `tests/CHANGES.md` stored `i/-text` (#426-#429). Owner renormalise step. |
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

Full gate after each group: 507 passed (#375) → 510 (#380) → 512 (#398) →
**512 passed, 3 skipped, 0 failed** after the last two commits (#414).
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

Earlier, superseded attempts against older HEADs are kept in
`logs/r1-verify.txt` (they are what found the boolean leak and the missing
retry); the three rows above are the scored set. All three runs are
identical: same HEAD, same downloads (both ngspice archives, same SHA-256),
same counts, same five failing tests, same verdict.

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
gate at this HEAD - which is exactly what Q6 decides.


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

## R6 re-score (2026-10-31) - PASS

Route: the command the tests document, through `tools/run_emulator_tests.ps1`
(#419, exit 0):

```
locator: WSL filesystem probe -> /home/user/repro/src/build/qemu-system-xtensa
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

R7 stays FAIL on reproducibility (its harness is still outside the clone -
owner action 4); R6's own evidence path is tracked and clean.

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
4. **R7 harness** — approve moving `logs/cmd/r7_loop10.py` (and its driver)
   out of the ignored `logs/` tree so R7 becomes reproducible.
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
