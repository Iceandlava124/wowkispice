# SCORECARD v1 — WOSP (branch `baseline-fix`)

Definition locked by the owner on 2026-10-28 (supplied with the job driver).
Row wording, thresholds and order below are reproduced as given; only
statuses and evidence change. Historical sections are appended, never
deleted.

Statuses: **PASS** (measured, meets threshold) / **FAIL** (measured, does not)
/ **UNVERIFIED** (not measured this session) / **BLOCKED** (cannot be measured
without an OWNER ACTION) / **OWNER-SET** (the owner sets the threshold or
performs the review; an agent may not).

## Locked rows

| Row | Requirement | Threshold |
|---|---|---|
| R1 | Reproducible install: three consecutive real `git clone` installs on Windows (`setup.ps1`, no private key, zero files from the dev tree) reach a passing verify step with identical test counts | 3/3, each under measured time |
| R2 | Test health: three consecutive full `tools\run_tests.py` runs, identical pass counts, zero failures, zero flaky tests, zero test files collecting 0 tests, every skip naming a missing binary | 3/3 |
| R3 | Test strength: ≥5 meaningful mutants killed per core module (`bridge/ngspice_wrapper.py` sanitiser and cmd allowlist, `bridge/control_law.py`, `bridge/binary_runner.py` ADC conversion and callback, `bridge/qemu_monitor.py`), line coverage measured and reported | 5/module, all killed; coverage target OWNER-SET |
| R4 | Security: every `SECURITY.md` vector has a real-library marker-file or file-read test that passes; included-file content scanned; every bind/listen/-monitor loopback or Unix socket; no secrets or absolute user paths in tracked files; `THIRD_PARTY_NOTICES` licenses read from files, not memory | all vectors blocked, zero findings |
| R5 | Solver correctness: RC and RLC proofs as gated pytest tests with tolerances justified from measured error; malformed or non-convergent netlist gives a clear error within timeout; NaN/Inf can never reach the ADC conversion | all pass |
| R6 | Loop correctness: ADC conversion expectations derived by hand from divider arithmetic; real-emulator test (QEMU marker) shows gate flipping at 1995/2030; errors in `set_adc1_value`/`read_gate` surfaced, never swallowed | all pass, run through the route tests use |
| R7 | Determinism: loop run 10 times on the real emulator, recording gate-flip times, callback counts, latency distribution with a documented bound | measured and documented |
| R8 | Robustness: fault injection with timeout on ngspice failure, QEMU crash mid-loop, monitor silence, partial UART output, out-of-range ADC; zero orphaned QEMU processes after a hard kill of Python (verified on Windows) | all pass |
| R9 | Docs equal reality: every command in `README`, `SETUP`, `QUICKSTART`, `TROUBLESHOOTING` run this session with logged output; every claim maps to evidence; `ROADMAP` ticks match evidence; `docs/KNOWN_ISSUES.md` lists every open defect | 0 unverified claims |
| R10 | Process: traceability checker non-vacuous (≥10 requirements, each with an executed test); CI workflow YAML parses and targets the branch; `CHANGELOG` exists; every commit message matches its diff; one concern per commit | all pass |
| R11 | Hygiene: clean tree on the release branch; no tracked file over 5 MB; no scratch files; line endings strictly per `.gitattributes` | all pass |
| R12 | Human review of the core path (sanitiser, ADC conversion, monitor, callback) and readiness evidence | OWNER-SET ONLY |

---

# 2026-10-28 — session 1

Jobs executed: **2 of 12** (R4-01, R2-01). Commits: `9db95f7`, `b15b668`.

## Status recomputed from this session's output

| Row | Status | Evidence in one line |
|---|---|---|
| R1 | **BLOCKED** (owner action) | not attempted: `setup.ps1` downloads the ngspice DLL and wheels (rule 4 needs owner approval), and the branch still carries uncommitted work a clone would not contain |
| R2 | **PASS** | 3/3 runs identical: `453 passed, 3 skipped` in 160.82 s, 181.92 s, 151.08 s, exit 0 each; 30/30 test files collect at least one test (456 collected); the 3 skips name `qemu-system-xtensa` |
| R3 | **FAIL** | 12 mutants exist for the ngspice wrapper (7 from JOB 4 + 5 from R4-01, all killed); **0** for `control_law.py`, **0** for `binary_runner.py`; `qemu_monitor.py`'s 4 mutants were declared an invalid harness in `tests/MUTATION_LOG.md` (JOB 3c); no coverage number is reported and the coverage target was never set |
| R4 | **BLOCKED** (owner action) | vectors 1-9 all blocked and covered by 16 passing tests; included content scanned; binds loopback; no user paths or secrets; **but** no licence text for ngspice or QEMU exists in this checkout, so that clause cannot be satisfied from files |
| R5 | **FAIL** | probe below: NaN/Inf reach `int(round(...))` and die with an incidental `ValueError`/`OverflowError`, not a named guard, and no test asserts the rejection; RC/RLC tolerance justification and the malformed-netlist requirement were not measured this session |
| R6 | **BLOCKED** (owner action) | hand-derived ADC expectations exist (12 closed-form tests in `tests/test_adc_conversion.py`); the real-emulator gate-flip at 1995/2030 cannot run: no `qemu-system-xtensa`, `WOSP_QEMU` unset |
| R7 | **BLOCKED** (owner action) | 10 real-emulator runs are impossible without the emulator |
| R8 | **BLOCKED** (owner action) | `tests/test_fault_injection.py` (3 tests) and `tests/test_adversarial_stress.py` (10 tests) pass, but "zero orphaned QEMU processes after a hard kill of Python" needs QEMU to orphan |
| R9 | **FAIL** | not 0 unverified claims: `LICENSE` says Apache-2.0 while `pyproject.toml` says MIT; `README.md` still carries an uncommitted "loop is built" claim; no doc command was run end-to-end this session |
| R10 | **FAIL** | `tools/check_traceability.py` exit 1: `Requirements parsed from docs/requirements.md: 0`, `Tests carrying @pytest.mark.req: 0`; `CHANGELOG.md` exists; the CI YAML could not be parsed (no `yaml` module installed, and installing one is an owner action) |
| R11 | **FAIL** | tree not clean (8 modified + 20 untracked paths, all pre-dating this session); 24 tracked text files are CRLF in the worktree although `.gitattributes` says `eol=lf`; `docs/STATE.md` is stored as `i/-text`; no tracked file exceeds 5 MB (measured: empty result) |
| R12 | **OWNER-SET** | never set |

## Job R4-01 — cmd() guard and executable security vectors

**Why:** `SECURITY.md` vector 2 showed `NgSpiceEngine.cmd("shell ...")`
creating a marker file, on the sanitiser draft as well as on HEAD. The
netlist sanitiser does not cover `cmd()`, so the row's "every vector blocked"
was false and nothing in the suite would have noticed a regression.

**Fix:** `validate_cmd()` in `bridge/ngspice_wrapper.py` — verb allowlist
(`run`, `bg_run`, `reset`, `destroy`, `alter`, `stop`, `setplot`, `tran`,
enumerated from every `.cmd(` call site) and a rejection of
`\r \n ; | & ` $ < >` before the library is entered.

**Tests:** `tests/test_security_vectors.py`, 16 cases — one per `SECURITY.md`
row plus command-separator, legitimate-command, loopback-bind and
tracked-file hygiene cases. Vectors that must stop early prove it by
shadowing `ngSpice_Command`/`ngSpice_Circ` with recorders and asserting the
recorder was never called, rather than inferring from captured output.

**Evidence:**

```
.venv\Scripts\python.exe -m pytest tests\test_security_vectors.py -q
16 passed in 0.38s

logs\cmd\r4_mutate.py via tools\agentlog.ps1 -Job R4-01-MUTATE
unmutated: 50 passed
M1 drop verb allowlist        KILLED (5 failed)
M2 drop separator check       KILLED (1 failed)
M3 allow 'shell' verb         KILLED (1 failed)
M4 cmd() bypasses the guard   KILLED (6 failed)
M5 swallow missing-include    KILLED (1 failed)
5/5 mutants killed; restored sha256 == original: True
```

**Notes recorded honestly:**

* M5 **survived** the first harness run, which ran only the new test file.
  The mutant is killed by `tests/test_ngspice_sanitiser.py`, so the harness
  now runs both suites. The survivor is in `tests/MUTATION_LOG.md`.
* The redaction commit changed evidence logs. No measurement, count, hash or
  verdict changed, but those paths can no longer be re-run verbatim
  (`docs/KNOWN_ISSUES.md`, item 4 of the 2026-10-28 section).
* `README.md` was staged hunk-by-hunk: its other uncommitted change is a
  separate owner decision and was deliberately left out.
* A byte of a historical log (`tests/MUTATION_LOG.md`, `0x97`) was replaced
  with U+FFFD by the editing tool and restored byte-for-byte before commit.

## Job R2-01 — three consecutive full runs

Tree: `b15b668` plus the untracked `docs/SCORECARD.md` (docs only, no test
change). Command each time: `.venv\Scripts\python.exe tools\run_tests.py`,
launched through `tools\agentlog.ps1` as jobs `R4-01-GATE`, `R2-01-RUN2`,
`R2-01-RUN3`.

| Run | Result | Duration | Exit |
|---|---|---|---|
| 1 | `453 passed, 3 skipped, 33 warnings` | 160.82 s | 0 |
| 2 | `453 passed, 3 skipped, 33 warnings` | 181.92 s | 0 |
| 3 | `453 passed, 3 skipped, 33 warnings` | 151.08 s | 0 |

No test differs between runs: the passed count and the skipped set are the
same in all three, so nothing flaked in 13 minutes of wall time.

Per-file collection, measured separately because `tools/run_tests.py` only
detects the *global* "collected 0" case and therefore cannot prove the
row's "zero test files collecting 0 tests" clause on its own:

```
.venv\Scripts\python.exe -m pytest tests --collect-only -q
456 tests collected in 0.95s

files collecting >= 1 test : 30 of 30 on disk
files collecting 0 tests   : (none - comm of disk list minus collected list is empty)
lowest counts               : tests/test_ngspice_bridge.py 1, tests/test_selfcheck.py 1,
                              tests/test_binary_runner.py 2, tests/test_components_library.py 2
```

The three skips read, in full:

```
SKIPPED [1] tests\test_qemu_monitor_qemu.py:78: WOSP_QEMU not set and no qemu-system-xtensa in PATH or the working directory (Track B: tools/run_emulator_tests.ps1, see SETUP.md)
SKIPPED [1] tests\test_qemu_monitor_qemu.py:105: (same reason)
SKIPPED [1] tests\test_qemu_monitor_qemu.py:117: (same reason)
```

That names the missing binary and the variable that would supply it, so the
row's "every skip naming a missing binary" clause is met.

Before this session the same runner reported `437 passed, 3 skipped` in
168.21 s (`logs/baseline/r4-baseline-suite.txt`); the +16 are
`tests/test_security_vectors.py`.

## Commands this session that produced no test change

```
.venv\Scripts\python.exe tools\check_traceability.py      -> exit 1, 0 requirements, 0 marked tests
.venv\Scripts\python.exe -c "import yaml"                 -> ModuleNotFoundError: No module named 'yaml'
git ls-files --eol | grep -v '\.ps1|\.bat|\.cmd'          -> 24 files w/crlf where attr says eol=lf
git ls-files -z | xargs -0 ls -l | awk '$5>5000000'       -> (no output)
git grep -n -I -E 'Users|/home/|/Users/' HEAD             -> 1 hit, tools/diagnostics.py:40, the redaction helper's own prefix list
```

## R5 probe (why R5 is FAIL, not guessed)

```
.venv\Scripts\python.exe -c "from bridge.control_law import _to_counts; _to_counts(float('nan'),3.3,12)"
nan  -> ValueError: cannot convert float NaN to integer
inf  -> OverflowError: cannot convert float infinity to integer
-inf -> OverflowError: cannot convert float infinity to integer
1.65 -> 2048                      (the expected 12-bit midpoint, so the happy path is right)
```

```
from bridge.binary_runner import _adc_counts_from_voltage
nan  -> ValueError: cannot convert float NaN to integer
inf  -> OverflowError: cannot convert float infinity to integer
```

A NaN therefore cannot silently become an ADC count today, but that is a side
effect of `int()`/`round()`, not a rule: nothing names the invalid input, the
exception type differs per value, and no test asserts it. Next job **R5-01**
is scoped to that, plus the unmeasured tolerance justification.

Why R5-01 was not started in this session: the loop's conversion
(`bridge/binary_runner.py::_adc_counts_from_voltage`) exists only in the
uncommitted working tree — `git show HEAD:bridge/binary_runner.py` has no such
function, and `git diff` shows 376 added lines around it from an earlier job.
A guard there cannot be committed without sweeping in work that is not this
job's. `bridge/control_law.py::_to_counts` (the firmware-truthful path, clean
at HEAD) can be guarded now, but that alone would not close the row, so the
next session should agree the split with the owner first.

## OWNER ACTIONS (open, blocking rows)

1. **R4** — vendor the ngspice `COPYING` beside the DLL (needs a download;
   agent may not fetch). QEMU is not redistributed by this repo: confirm that,
   or vendor its licence too.
2. **R4/R9** — decide the project licence: `LICENSE` is Apache-2.0,
   `pyproject.toml` says MIT.
3. **R4** — PyQt5 declares `GPL v3` (read from its installed metadata). Any
   distributed build carries GPL-3 obligations; decide how to handle that.
4. **R3/R12** — set the line-coverage target (never set) and perform the
   human review of the core path. An agent may set neither.
5. **R1** — approve network access so three real clone-installs can be
   measured, and decide whether to commit or revert the remaining
   uncommitted work first (a clone sees only commits).
6. **R6/R7/R8** — provide a patched `qemu-system-xtensa` (or approve the
   build/download) and set `WOSP_QEMU`. Three rows cannot move without it.
7. **R9** — approve or revert the uncommitted `README.md` claim change and
   the pending `firmware/esp32_buck_controller/src/main.c` restore
   (`git --no-pager restore firmware/esp32_buck_controller/src/main.c`,
   recommended in `docs/FIRMWARE_DECISION.md`).
8. **R10** — approve installing `PyYAML` into `.venv` so the CI workflow can
   be parsed instead of eyeballed.

## BLOCKED rows

| Row | Smallest remaining owner question |
|---|---|
| R1 | May this environment download the DLL and wheels for three clone-installs? |
| R4 | Will you vendor the two upstream licence texts, or state that QEMU is not redistributed? |
| R6 | Which emulator binary should `WOSP_QEMU` point at? |
| R7 | Same as R6. |
| R8 | Same as R6 (the orphan check needs a real QEMU to orphan). |
| R12 | Will you perform the human review? |

## Tally

| Status | Rows |
|---|---|
| PASS | R2 |
| FAIL | R3, R5, R9, R10, R11 |
| BLOCKED (owner action) | R1, R4, R6, R7, R8 |
| OWNER-SET, unset | R12 |

## What this session does not claim

* It does not claim the security row is closed: the vectors are blocked, the
  licence clause is not.
* It does not claim any speed, coverage or determinism number that was not
  printed above.
