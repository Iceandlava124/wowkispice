# PROJECT_WOWKISPICE - Industry Deployment Roadmap

**Goal:** Transform from "impressive research tool" to "legitimately useful engineering platform" ready for industry lab deployment.

**Status:** Reconciled to measured evidence on 2026-10-27. Technology readiness (TRL) labels removed - no measurement in this repository supports a TRL claim.

### Evidence legend

Every item below carries one of three marks:

- `[x]` **VERIFIED** - proven by command output pasted in this session's log.
- `[~]` **PARTIAL** - code exists and/or a test passes, but the full claim is not proven (test uses doubles, real emulator skipped, never run here, or evidence incomplete).
- `[ ]` **UNVERIFIED / NOT DONE** - no evidence produced, or the work has not started.

Suite state measured 2026-10-27: **406 passed, 4 failed, 3 skipped** in 152.98s (`pytest tests/ -q --timeout=60`).
The 4 failures are the J4 sanitiser draft rejecting `.include` and `.meas` (those tests pass at HEAD); the 3 skips are `tests/test_qemu_monitor_qemu.py` because `WOSP_QEMU` is not set.

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

- [~] Hardened ngspice ↔ QEMU synchronization - suite reaches its end (was hanging); real-QEMU sync not exercised this session (`WOSP_QEMU` unset)
- [~] Binary runner with gate flip testing - `tests/test_binary_runner.py` passes as part of the 16-test block; the real-emulator gate-flip test is **skipped** (no QEMU binary)
- [~] Adversarial stress tests - pass, but built entirely on `unittest.mock` doubles (`tests/test_adversarial_stress.py:8` imports `Mock, patch, MagicMock`); no real ngspice or QEMU involved
- [~] Load step injection - test passes; engine not confirmed real ngspice in this pass
- [ ] Firmware telemetry enhancements - `main.c` edit is unreviewed, whole-file line-ending rewrite, dead `adaptive_band_shift`; `firmware.elf` may predate the source; no test
- [~] Toolchain resolver - code present, no test (`ls tests/` finds no resolver/doctor/fetch/qualify/cleanup/cli test file)
- [~] QEMU fetcher - code present, no test
- [~] Environment doctor - `tools/doctor.py:62-64` calls `QemuQualifier`; no test
- [~] Improved setup.ps1 - wires cleanup/fetch/doctor (see 1.4); clean-clone run not performed this session
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
- [~] **Document container usage** - README.md lines 47-62 document `docker build`/`docker run`/`docker-compose`; instructions untested here

### 1.2 Tool Qualification for QEMU
- [~] **Create `tools/qualify_qemu.py`** - Code present: sha256, `-machine help` ESP32 probe, `-device help` SENS probe, manifest write, exit code. Never executed against a real binary this session.
- [~] **Integrate with doctor** - `tools/doctor.py:62-64` imports and calls `QemuQualifier.qualify()`; no test
- [~] **Integrate with fetcher** - Not verified in this pass
- [~] **Add to manifest** - `qualify_qemu.py` writes `third_party/manifest.json`; no known-good checksum list exists to compare against
- [~] **Fail fast on bad QEMU** - `bridge/binary_runner.py:108-112` qualifies before launch; no test proving rejection of a stock/unpatched binary

### 1.3 Process Hygiene & Cleanup
- [~] **Create `tools/cleanup_qemu.py`** - Code present (50 lines); never run against a deliberately orphaned process
- [~] **Add atexit handlers** - `bridge/qemu_monitor.py:49` `atexit.register(_cleanup_all_monitors)` with taskkill/os.kill at lines 36-43; behaviour when Python is hard-killed unproven
- [~] **PID tracking** - Tracked PIDs killed in the atexit path; not exercised by a test
- [~] **Startup cleanup** - `setup.ps1:301` and `setup.sh:84` invoke it
- [ ] **Test cleanup** - NOT DONE. No test file for cleanup exists.

### 1.4 One-Command Setup
- [~] **Make setup.ps1 improved** - Calls cleanup (line 301), fetch (308), doctor (315), writes `.env.local` (320); not run this session
- [~] **Make setup.sh improved** - Calls cleanup (84), fetch (86), doctor (88); `|| true` masks failures, so "loud failure on bad download" is not yet true
- [~] **Auto-generate .env.local** - Wired at `setup.ps1:320`; generation not observed
- [~] **Add post-setup validation** - Doctor invoked; exit status not gated
- [ ] **Test fresh clone simulation** - NOT DONE (belongs to J10, not run)

**Acceptance Criteria for Phase 1:**
- [ ] Fresh clone + `./setup.ps1` (or equivalent) completes with all-green doctor - NOT RUN
- [ ] `docker build && docker run` works without manual intervention - NOT RUN (no daemon)
- [ ] No orphaned QEMU processes after test runs - NOT MEASURED (no test, no WOSP_QEMU)
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
- [ ] **Instrument timing** - NOT DONE: no capture of injection/read times or firmware loop counts
- [ ] **Measure variance** - NOT MEASURED: no repeated gate-flip run recorded
- [~] **Implement read-until-stable** - Reported in `bridge/binary_runner.py`; not reviewed against this roadmap's contract, and unproven without a real emulator run
- [ ] **Make sync configurable** - NOT VERIFIED
- [ ] **Document sync contract** - NOT DONE (`docs/time-sync.md` does not exist)
- [ ] **Add sync metrics to reports** - NOT VERIFIED

### 2.3 Fault Injection Expansion
- [~] **Ngspice convergence failures** - Adversarial tests pass but are constructed from `unittest.mock` doubles (`tests/test_adversarial_stress.py:8`); no real non-convergent netlist driven through ngspice
- [~] **QEMU monitor hangs** - Timeout paths tested against mocked pipes, not a real hung QEMU
- [~] **Partial UART output** - Mocked only
- [~] **Invalid ADC injections** - Boundary logic tested in doubles
- [~] **Network/pipe failures** - `Broken pipe` OSError mocked
- [~] **Add to test suite** - 16/16 pass in the `test_adversarial_stress + load_step + binary_runner + golden_traces` block (measured 0.38s); **none counts as emulator coverage**

### 2.4 Headless CLI
- [~] **Create `tools/cli.py`** - Present, 367 lines; `python tools/cli.py --help` ran successfully this session
- [~] **Add commands** - All five present: `cosim-binary`, `test-gate-flip`, `doctor`, `golden-trace`, `version` (`tools/cli.py:27,60,82,90,122`)
- [x] **Decouple from PyQt** - Verified: `grep -n "PyQt|import ui|schematic_editor" tools/cli.py` matches only the module docstring (line 4)
- [~] **JSON output mode** - `--output` flag exists (`tools/cli.py:56`, `json.dump` at 203); not exercised end-to-end
- [ ] **Add to tools/** - No `console_scripts` entry point confirmed in `pyproject.toml`
- [ ] **Test CLI** - NOT DONE: no `tests/` file for the CLI; only `--help` was run manually

**Acceptance Criteria for Phase 2:**
- [ ] Golden trace tests pass with <2% variance - FAILS ON ITS FACE: no real reference data to compare against
- [ ] Gate flip test passes 10/10 times consecutively - NOT RUN (3 gate-flip tests skip: `WOSP_QEMU` unset)
- [ ] All fault injection tests pass - PARTIAL: they pass, but on doubles
- [ ] CLI works headlessly - PARTIAL: `--help` only
- [ ] Sync latency measured and documented - NOT DONE

---

## Phase 3: P2 - Professionalize for Deployment

*Target: Ongoing | Goal: Team-ready engineering platform*

### 3.1 Enhanced Traceability
- [~] **Extend requirements-matrix** - `docs/requirements-matrix.md` exists with 10 REQ rows; **no file:line references**
- [~] **Create `tools/check_traceability.py`** - Exists, but returns a **false green**: run this session printed `Requirements parsed from docs/requirements.md: 0`, `Tests carrying @pytest.mark.req: 0`, then `TRACEABILITY OK: 0 requirements, 0 tests` (exit 0). It must fail on zero coverage.
- [ ] **Link tests to requirements** - NOT DONE: 0 tests carry the `req` marker
- [ ] **Add to CI** - NOT DONE
- [ ] **Document traceability process** - NOT VERIFIED

### 3.2 CI Pipeline
- [~] **Create `.github/workflows/`** - `cosim-ci.yml` exists (installs ngspice, Python 3.12, ubuntu-latest) but triggers only on `main`, `master`, `dev` (line 4-8) - **this repo's branch is `baseline-fix`, so it never fires**
- [ ] **Unit tests on every PR** - Blocked by the branch trigger above; GitHub CI cannot be executed from this machine (stated, not tested)
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
- [~] **Update README.md** - Exists and documents Docker (lines 47-62); Docker section describes commands never run here
- [~] **Create CONTRIBUTING.md** - File exists; content not reviewed this session
- [ ] **API documentation** - NOT VERIFIED

**Acceptance Criteria for Phase 3:**
- [ ] CI passing on unit tests - NOT RUN (GitHub CI not executable here; branch trigger wrong)
- [ ] Traceability check passes - FAILS IN SPIRIT: passes vacuously with 0 requirements and 0 tests
- [ ] CLI installable via pipx - NOT TESTED
- [ ] Documentation complete and tested - NOT DONE

---

## Phase 4: Validation & Sign-off

*Target: Final validation*

### 4.1 End-to-End Validation
- [ ] **Fresh clone test** - NOT RUN (job J10 not executed)
- [ ] **Docker fresh build test** - NOT RUN (no Docker daemon)
- [ ] **All tests pass** - FAIL: measured 2026-10-27 = **4 failed, 406 passed, 3 skipped** in 152.98s. The 4 failures are the J4 sanitiser draft rejecting `.include` and `.meas` (both pass at HEAD)
- [ ] **Golden traces pass** - NOT MEANINGFUL: no real reference data exists
- [ ] **No orphaned processes** - NOT MEASURED
- [ ] **Doctor all-green** - FAIL, two ways: (1) `tools/doctor.py` crashes with `UnicodeEncodeError: 'charmap' codec can't encode character '\u2713'` on a cp1252 console, **exit 1**, before printing its first line; (2) under `PYTHONIOENCODING=utf-8` it completes but still exits 1 with `ngspice not found` and `WOSP_QEMU` unset

### 4.2 Documentation Review
- [ ] **README accurate** - NOT VERIFIED; its Docker section (lines 47-62) documents commands never run here
- [ ] **All docs updated** - NOT VERIFIED
- [x] **Roadmap complete** - This reconciliation pass: every item above now carries VERIFIED / PARTIAL / UNVERIFIED with its evidence
- [~] **Changelog** - `CHANGELOG.md` exists; contents not reviewed this session

### 4.3 Final Checklist
- [ ] **Reproducibility verified** - NOT DONE (no 3x fresh-run comparison)
- [ ] **Determinism verified** - NOT DONE (gate-flip tests skip: `WOSP_QEMU` unset)
- [ ] **Error messages helpful** - PARTIAL: sanitiser rejections are specific (`banned directive @line: .include`) but doctor's crash is not
- [x] **Performance acceptable** - Measured: full suite runs 406 tests in 152.98s (about 0.38s/test average) on this machine
- [ ] **Ready for handoff** - NOT DONE

---

## Success Metrics

*All values measured in this session (2026-10-27) or marked unmeasured. Earlier "~90% deterministic" and "~30-60 min" figures had no source and were removed.*

| Metric | Current (measured) | Target | Status |
|--------|---------|--------|--------|
| Full test suite | 406 passed, 4 failed, 3 skipped (152.98s) | 0 failed, 0 skipped-without-a-named-binary | FAIL: 4 failing |
| Fresh clone to running tests | **unmeasured** (clean-clone run never performed) | <5 min automated | not measured |
| Deterministic gate flip | **unmeasured** (3 gate-flip tests skip: WOSP_QEMU unset) | 10/10 consecutive | not measured |
| Orphaned processes after tests | **unmeasured** | Zero | not measured |
| Doctor on clean environment | **fails**: exit 1 (cp1252 crash on the check mark; also ngspice/QEMU missing) | all-green | FAILING |
| Golden reference traces | stub only (91-byte JSON, no trace data) | real-run traces with provenance | FAIL: not captured |
| Traceability check | vacuous pass: 0 requirements, 0 tests, exit 0 | fails when a requirement is untested | FAIL: false green |
| Docker build | **not run** (daemon down) | builds unattended | not measured |
| Critical-path test coverage | Good (unquantified) | Excellent (measured %) | unquantified |

---

## Notes & Principles

- **Boring over clever** - Reliability trumps fancy features
- **Fail fast with clear errors** - Doctor should tell you exactly how to fix
- **Automate everything automatable** - Manual steps should be eliminated
- **Test the hard parts** - Focus on determinism and reproducibility first
- **Document as you go** - Update docs with each change

**Last Updated:** 2026-10-27 (reconciled to measured evidence)  
**Status:** Active Development - Phases 0-2 partially built but NOT yet proven; Phases 3-4 not started. Read the evidence legend at the top before trusting any tick.
