# PROJECT_WOWKISPICE - Industry Deployment Roadmap

**Goal:** Transform from "impressive research tool" to "legitimately useful engineering platform" ready for industry lab deployment.

**Status:** Reconciled to measured evidence on 2026-10-29. Technology readiness (TRL) labels removed - no measurement in this repository supports a TRL claim.

### Evidence legend

Every item below carries one of three marks:

- `[x]` **VERIFIED** - proven by command output pasted in this session's log.
- `[~]` **PARTIAL** - code exists and/or a test passes, but the full claim is not proven (test uses doubles, real emulator skipped, never run here, or evidence incomplete).
- `[ ]` **UNVERIFIED / NOT DONE** - no evidence produced, or the work has not started.

Suite state measured 2026-10-29: **488 passed, 0 failed, 3 skipped** in 113.09s (`tools/run_tests.py`, log #226). The 3 skips are the three `tests/test_qemu_monitor_qemu.py` contract tests because `WOSP_QEMU` is not set on Windows - each skip names its missing binary. (2026-10-27 measured 406 passed, 4 failed, 3 skipped; the 4 failures were the J4 sanitiser draft.)

---

## Progress Tracking

- [~] Phase 0: Foundation - PARTIAL (code present, several claims unproven; see below)
- [~] Phase 1: P0 - Make it Boringly Reproducible - PARTIAL (tooling wired, clean-clone and Docker never run)
- [ ] Phase 2: P1 - Make it Deterministic & Regression-Testable - NOT DONE (golden traces are stubs, sync unmeasured)
- [ ] Phase 3: P2 - Professionalize for Deployment - NOT STARTED
- [ ] Phase 4: Validation & Sign-off - NOT STARTED

---

## Phase 0: Foundation (PARTIAL - claimed complete, not proven)

Claimed implemented. Status per evidence:

- [x] Hardened ngspice ↔ QEMU synchronization - real-QEMU loop measured: 10 runs, 30/30 gate flips, injection->flip 20.3-20.8 ms (log #207, SCORECARD R7-01); suite green (log #226)
- [x] Binary runner with gate flip testing - `tests/test_binary_runner.py` passes (log #226) and the real-emulator gate-flip test PASSED through `tools/run_emulator_tests.ps1` (3 passed, 0 skips, log #201)
- [~] Adversarial stress tests - pass, but built entirely on `unittest.mock` doubles (`tests/test_adversarial_stress.py:8` imports `Mock, patch, MagicMock`); no real ngspice or QEMU involved
- [~] Load step injection - test passes; engine not confirmed real ngspice in this pass
- [ ] Firmware telemetry enhancements - `main.c` edit is unreviewed, whole-file line-ending rewrite, dead `adaptive_band_shift`; `firmware.elf` may predate the source; no test
- [~] Toolchain resolver - code present; covered by `tests/test_tool_fixes.py::test_find_ngspice_honours_the_same_env_var_as_the_bridge` (log #225); fetch/qualify/cli still untested
- [~] QEMU fetcher - code present, no test
- [~] Environment doctor - no longer crashes on a cp1252 console and discovers ngspice (2 tests, log #225); live run (log #238) prints every section [OK] except `[X] QEMU not found` -> exit 1, expected while the emulator is WSL-only (owner decision 8)
- [~] Improved setup.ps1 - wires cleanup/fetch/doctor (see 1.4); run idempotently 2026-10-29 (exit 0, "Setup complete", log #235); clean-clone run not performed (pending R1)
- [x] third_party/ gitignore + manifest - `.gitignore:105` ignores `third_party/`; `third_party/manifest.json` exists (188 bytes)
- [~] Initial Dockerfile - `Dockerfile` (1410 bytes) and `docker-compose.yml` (1016 bytes) exist but **were never built**: `docker info` reports daemon DOWN/not installed

---

## Phase 1: P0 - Make it Boringly Reproducible (PARTIAL - tooling wired, never run end-to-end)

*Target: 1-2 weeks | Goal: Clone → setup → run tests with zero manual hunting*

### 1.1 Containerize End-to-End
- [~] **Improve Dockerfile** - File present (1410 bytes); contents reviewed, never built (no Docker daemon)
- [~] **Add docker-compose.yml** - File present (1016 bytes); never run
- [ ] **Test container build** - NOT DONE. `docker info` -> `daemon DOWN/not installed`. The prior tick rested on "daemon not running in this env", which is not a test.
- [ ] **Test container runtime** - NOT DONE (follows from build)
- [~] **Document container usage** - README no longer advertises docker commands: the section now states they were never built and are not a reproduction path (revised 2026-10-29; `docker version` reaches only the client 29.8.2, daemon unreachable, log #230)

### 1.2 Tool Qualification for QEMU
- [~] **Create `tools/qualify_qemu.py`** - Code present: sha256, `-machine help` ESP32 probe, `-device help` SENS probe, manifest write, exit code. Never executed against a real binary this session.
- [~] **Integrate with doctor** - `tools/doctor.py:62-64` imports and calls `QemuQualifier.qualify()`; no test
- [~] **Integrate with fetcher** - Not verified in this pass
- [~] **Add to manifest** - `qualify_qemu.py` writes `third_party/manifest.json`; no known-good checksum list exists to compare against
- [~] **Fail fast on bad QEMU** - `bridge/binary_runner.py:108-112` qualifies before launch; no test proving rejection of a stock/unpatched binary

### 1.3 Process Hygiene & Cleanup
- [x] **Create `tools/cleanup_qemu.py`** - run against a real orphaned QEMU: after a hard SIGKILL of python the orphan (pid 489) survived stdin EOF, the reaper then brought the count to zero (logs #210, #212, SCORECARD R8-01)
- [~] **Add atexit handlers** - `bridge/qemu_monitor.py:49` registers `_cleanup_all_monitors`; behaviour MEASURED: a hard kill skips them (orphan survived, log #210) and Windows cannot spawn the ELF at all (log #211); zero-by-construction (prctl PDEATHSIG) remains an open OWNER ACTION in docs/KNOWN_ISSUES.md
- [~] **PID tracking** - Tracked PIDs killed in the atexit path; not exercised by a test
- [~] **Startup cleanup** - `setup.ps1:301` and `setup.sh:84` invoke it
- [~] **Test cleanup** - exercised end-to-end by the R8 orphan check (detect -> reap with tools/cleanup_qemu.py -> verify zero, logs #210/#212); still no dedicated test file

### 1.4 One-Command Setup
- [~] **Make setup.ps1 improved** - Calls cleanup (line 301), fetch (308), doctor (315), writes `.env.local` (320); run as-is 2026-10-29: idempotent, exit 0, "Setup complete" (log #235); clean-clone run pending (R1)
- [~] **Make setup.sh improved** - Calls cleanup (84), fetch (86), doctor (88); `|| true` masks failures, so "loud failure on bad download" is not yet true
- [~] **Auto-generate .env.local** - Wired at `setup.ps1:320`; generation not observed
- [~] **Add post-setup validation** - Doctor invoked; exit status not gated
- [ ] **Test fresh clone simulation** - NOT DONE (belongs to J10, not run)

**Acceptance Criteria for Phase 1:**
- [ ] Fresh clone + `./setup.ps1` (or equivalent) completes with all-green doctor - NOT RUN
- [ ] `docker build && docker run` works without manual intervention - NOT RUN (no daemon)
- [~] No orphaned QEMU processes after test runs - MEASURED 2026-10-29: Windows = zero after a hard kill (log #211); WSL = orphan survives, reaped to zero by tools/cleanup_qemu.py (logs #210/#212); zero-by-construction still open (owner action)
- [ ] All toolchain binaries verified with checksums - PARTIAL (sha256 computed, no known-good list, no binary qualified here)

---

## Phase 2: P1 - Make it Deterministic & Regression-Testable

*Target: 2-3 weeks | Goal: Reproducible results, catch regressions*

### 2.1 Golden Trace Framework
- [~] **Create `tools/golden_trace.py`** - Save/load/compare with tolerances works (tests pass); framework only
- [~] **Define golden cases** - `buck_regulation` name exists, but `tests/golden/buck_regulation.json` is 91 bytes and contains only `{"description", "name"}` - **no trace data, no time axis, no voltages**
- [ ] **Capture reference traces** - NOT DONE for a real run. `tools/capture_golden.py` captures from the Python `cosim_runner` loop (mock controller), never from QEMU, and writes no provenance (no hash, date, command or firmware version)
- [~] **Add comparison logic** - Tolerance comparison exists; tolerances are never justified from measured variance
- [~] **Create `tests/test_golden_traces.py`** - Both tests pass, but they exercise the framework against **dummy data the test itself writes** (`test_dummy`, `test_dummy2`), not a captured reference
- [ ] **Store golden data** - `tests/golden/` holds only the empty buck stub plus two test-created dummies; no checksums, no provenance sidecar

### 2.2 Synchronization Audit & Hardening
- [x] **Instrument timing** - done in the R7 harness: injection/flip times and callback counts recorded for 10 real-emulator runs, 30 flips (log #207)
- [x] **Measure variance** - 10 consecutive runs, flip latency 20.3-20.8 ms, HMP round trip <=10.5 ms; bounds documented in docs/SCORECARD.md R7-01 (log #207)
- [~] **Implement read-until-stable** - the loop containing it ran 10x on the real emulator (log #207), but read-until-stable has no assertion of its own against this contract
- [ ] **Make sync configurable** - NOT VERIFIED
- [ ] **Document sync contract** - NOT DONE (`docs/time-sync.md` does not exist)
- [ ] **Add sync metrics to reports** - NOT VERIFIED

### 2.3 Fault Injection Expansion
- [~] **Ngspice convergence failures** - Adversarial tests pass but are constructed from `unittest.mock` doubles (`tests/test_adversarial_stress.py:8`); no real non-convergent netlist driven through ngspice
- [~] **QEMU monitor hangs** - Timeout paths tested against mocked pipes, not a real hung QEMU
- [~] **Partial UART output** - Mocked only
- [~] **Invalid ADC injections** - Boundary logic tested in doubles
- [~] **Network/pipe failures** - `Broken pipe` OSError mocked
- [~] **Add to test suite** - the five fault families pass 106/106 (log #213, SCORECARD R8-01) and the orphan halves used a real QEMU process (logs #210-#212); the pipe/UART/ADC cases remain doubles-based

### 2.4 Headless CLI
- [~] **Create `tools/cli.py`** - Present, 367 lines; `python tools/cli.py --help` ran successfully this session
- [~] **Add commands** - All five present: `cosim-binary`, `test-gate-flip`, `doctor`, `golden-trace`, `version` (`tools/cli.py:27,60,82,90,122`)
- [x] **Decouple from PyQt** - Verified: `grep -n "PyQt|import ui|schematic_editor" tools/cli.py` matches only the module docstring (line 4)
- [~] **JSON output mode** - `--output` flag exists (`tools/cli.py:56`, `json.dump` at 203); not exercised end-to-end
- [ ] **Add to tools/** - No `console_scripts` entry point confirmed in `pyproject.toml`
- [ ] **Test CLI** - NOT DONE: no `tests/` file for the CLI; only `--help` was run manually

**Acceptance Criteria for Phase 2:**
- [ ] Golden trace tests pass with <2% variance - FAILS ON ITS FACE: no real reference data to compare against
- [x] Gate flip test passes 10/10 times consecutively - PASS: 10/10 clean gate exits through `tools/run_emulator_tests.ps1` (log #208) plus 10 instrumented loop runs, 30/30 flips (log #207)
- [ ] All fault injection tests pass - PARTIAL: they pass, but on doubles
- [ ] CLI works headlessly - PARTIAL: `--help` only
- [x] Sync latency measured and documented - MEASURED: injection->flip 20.3-20.8 ms over 30 flips, HMP round trip <=10.5 ms; bounds (50 ms flip, 20 ms RTT) documented in `docs/SCORECARD.md` job R7-01 (log #207)

---

## Phase 3: P2 - Professionalize for Deployment

*Target: Ongoing | Goal: Team-ready engineering platform*

### 3.1 Enhanced Traceability
- [~] **Extend requirements-matrix** - `docs/requirements-matrix.md` exists with 10 REQ rows; **no file:line references**
- [x] **Create `tools/check_traceability.py`** - false green fixed 2026-10-29: parses 14 requirements and 16 marked tests (`TRACEABILITY OK: 14 requirements, 16 tests`, log #224); zero rows / zero markers remain hard failures (guard suite, log #225)
- [x] **Link tests to requirements** - 16 tests carry `@pytest.mark.req` across 14 requirements, each with an executed test (log #224)
- [ ] **Add to CI** - NOT DONE
- [ ] **Document traceability process** - NOT VERIFIED

### 3.2 CI Pipeline
- [~] **Create `.github/workflows/`** - `cosim-ci.yml` now also triggers on `baseline-fix` (commit 181d885, asserted by `tests/test_ci_workflow.py`, log #225); GitHub CI itself cannot be executed from this machine
- [ ] **Unit tests on every PR** - branch trigger now correct; GitHub CI cannot be executed from this machine (stated, not tested)
- [ ] **Add linting** - NOT DONE
- [ ] **Add type checking** - NOT DONE (parked unless the owner asks)
- [ ] **Test result reporting** - NOT DONE
- [ ] **Status badges** - NOT DONE (parked unless the owner asks)

### 3.3 Structured Logging & Observability
- [ ] **Implement logging framework** - NOT DONE
- [ ] **Add log levels** - NOT DONE
- [ ] **JSON log format** - NOT DONE (the activity log is session tooling, not product logging)
- [ ] **Run correlation IDs** - NOT DONE
- [ ] **Log aggregation** - NOT DONE
- [ ] **Add to doctor** - NOT DONE

### 3.4 Packaging & Distribution
- [ ] **Update pyproject.toml** - NOT VERIFIED for entry points
- [ ] **Create install script** - Partially: setup.ps1/setup.sh exist but are unproven on a clean clone
- [ ] **Version management** - NOT VERIFIED
- [ ] **Release process** - NOT DONE (`docs/RELEASE.md` does not exist)
- [ ] **Consider PyPI** - Parked unless the owner asks

### 3.5 Documentation
- [ ] **Create QUICKSTART.md** - NOT DONE (file does not exist)
- [ ] **Create TROUBLESHOOTING.md** - NOT DONE (file does not exist)
- [x] **Update README.md** - 2026-10-29 pass: status table re-measured (488/3, 3 contract passes, selfcheck PASS in 120.5 s), Docker section replaced by the measured never-built note (log #230), stale gate counts corrected
- [~] **Create CONTRIBUTING.md** - File exists; content not reviewed this session
- [ ] **API documentation** - NOT VERIFIED

**Acceptance Criteria for Phase 3:**
- [ ] CI passing on unit tests - NOT RUN (GitHub CI not executable here; branch trigger now correct)
- [x] Traceability check passes - non-vacuous: 14 requirements / 16 executed tests, exit 0 (log #224)
- [ ] CLI installable via pipx - NOT TESTED
- [ ] Documentation complete and tested - NOT DONE

---

## Phase 4: Validation & Sign-off

*Target: Final validation*

### 4.1 End-to-End Validation
- [ ] **Fresh clone test** - NOT RUN (job J10 not executed)
- [ ] **Docker fresh build test** - NOT RUN (no Docker daemon)
- [x] **All tests pass** - measured 2026-10-29: **488 passed, 0 failed, 3 skipped** in 113.09s, exit 0 (log #226); each skip names its missing binary (WSL-only emulator)
- [ ] **Golden traces pass** - NOT MEANINGFUL: no real reference data exists
- [~] **No orphaned processes** - MEASURED: Windows zero after hard kill (log #211); WSL orphan reaped to zero by tools/cleanup_qemu.py (logs #210/#212); prevention (PDEATHSIG) open as an owner action
- [~] **Doctor all-green** - both recorded defects fixed: no cp1252 crash and ngspice is discovered (2 tests, log #225); live run (log #238) exits 1 with only `[X] QEMU not found`, which is expected while the emulator is WSL-only (owner decision 8)

### 4.2 Documentation Review
- [x] **README accurate** - every README command run 2026-10-29 with logged output: setup.ps1 #235, run_selfcheck.bat #236, run_tests #226, run_editor #237, --require-emulator exit 3 #234, Track B #201, docker client-only #230; Docker section replaced
- [ ] **All docs updated** - NOT VERIFIED
- [x] **Roadmap complete** - This reconciliation pass: every item above now carries VERIFIED / PARTIAL / UNVERIFIED with its evidence
- [x] **Changelog** - reviewed 2026-10-29: Keep-a-Changelog format with Unreleased + 1.0.0 sections; the file exists (R10 clause)

### 4.3 Final Checklist
- [ ] **Reproducibility verified** - NOT DONE (no 3x fresh-run comparison)
- [~] **Determinism verified** - 10 measured runs with documented bounds (flip latency 20.3-20.8 ms, 30/30 flips, log #207); "deterministic" only within those bounds (SCORECARD R7-01)
- [ ] **Error messages helpful** - PARTIAL: sanitiser rejections are specific (`banned directive @line: .include`) but doctor's crash is not
- [x] **Performance acceptable** - Measured: full suite 488 tests in 113.09s (about 0.23s/test, log #226) on this machine
- [ ] **Ready for handoff** - NOT DONE

---

## Success Metrics

*All values measured in this session (2026-10-27) or marked unmeasured. Earlier "~90% deterministic" and "~30-60 min" figures had no source and were removed.*

| Metric | Current (measured) | Target | Status |
|--------|---------|--------|--------|
| Full test suite | 488 passed, 0 failed, 3 skipped (113.09s, log #226) | 0 failed, 0 skipped-without-a-named-binary | PASS |
| Fresh clone to running tests | **unmeasured** (clean-clone run never performed) | <5 min automated | not measured |
| Deterministic gate flip | 10/10 runs, 30/30 flips under WSL (logs #207, #208) | 10/10 consecutive | MEASURED |
| Orphaned processes after tests | Windows zero after hard kill (#211); WSL reaped to zero (#210/#212) | Zero | MEASURED (reaped, not by construction) |
| Doctor on clean environment | runs clean; exit 1 with only `[X] QEMU not found` (WSL-only emulator, log #238) | all-green | PARTIAL |
| Golden reference traces | stub only (91-byte JSON, no trace data) | real-run traces with provenance | FAIL: not captured |
| Traceability check | 14 requirements / 16 executed tests, exit 0 (log #224) | fails when a requirement is untested | PASS |
| Docker build | **not run** - client 29.8.2, daemon unreachable (log #230) | builds unattended | not measured |
| Critical-path test coverage | measured per module with owner-set floors (SCORECARD R3-01/R3-02) | owner-set floors | PASS (R3) |

---

## Notes & Principles

- **Boring over clever** - Reliability trumps fancy features
- **Fail fast with clear errors** - Doctor should tell you exactly how to fix
- **Automate everything automatable** - Manual steps should be eliminated
- **Test the hard parts** - Focus on determinism and reproducibility first
- **Document as you go** - Update docs with each change

**Last Updated:** 2026-10-29 (reconciled to measured evidence; all log numbers refer to logs/activity.jsonl)  
**Status:** Active Development - Phases 0-2 partially built but NOT yet proven; Phases 3-4 not started. Read the evidence legend at the top before trusting any tick.
