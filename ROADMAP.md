# PROJECT_WOWKISPICE — Canonical Engineering Plan

**This file is the single source of truth for phase numbers.** `README.md`,
`DELIVERABLE_SUMMARY.md`, and `docs/industry-readiness.md` reference these phase
numbers and must not define their own. The mapping table at the end translates
older labels found in the repo's history.

**Status:** Phases 0–2 complete; Phase 3–4 in progress; Phases 5–6 not started.
PyQt6/Ollama and the firmware-framework migration are deferred and unscheduled.

## Evidence legend

- `[x]` **VERIFIED** — a command in this turn or a recorded run produced the stated result.
- `[~]` **PARTIAL** — code or tests exist, but the full claim is not proven.
- `[ ]` **NOT DONE / UNVERIFIED** — no evidence, or not started.

## Measured baseline (2026-11-07)

| Check | Command | Result |
|---|---|---|
| Rust core | `cargo test -p wowkispice-core` | **334 passed, 0 failed, 0 warnings** |
| FFI bridge | `cargo test -p wowkispice-ffi` | **27 passed, 0 failed** — DLL loading fixed via `LOAD_WITH_ALTERED_SEARCH_PATH` flag; reproduced this turn |
| Full environment gate | `run_selfcheck.bat` (clean shell, no venv activated) | **SELF-CHECK: PASS**, exit 0; **547 passed, 4 skipped, 0 failed** in 229.43 s |
| Installer artifact | `installer/wowkispice_installer.exe` | Exists, NSIS PE32, 124,773 bytes; `.nsi` contains `<USERPROFILE>` placeholders; `makensis` absent; clean-machine install **unverified** |
| Co-simulation path | `crates/wowkispice-ffi/src/cosim_runner.rs` + `mock_controller.rs` | Rust + ngspice; QEMU is legacy, not shipped |
| Controller artifact | `firmware/esp32_buck_controller/src/firmware_control.dll` | Exists (24,891 bytes); exports `buck_controller_tick`; **no shipped code path loads it** |

The Python gate's 4 skips are the QEMU contract tests (`WOSP_QEMU` unset), which is
expected because QEMU is legacy.

---

# Phase 0 — Foundation

**Status: `[x]` COMPLETE.**

- [x] Rust core workspace (`crates/wowkispice-core`) with 17 modules mirroring `bridge/` 1:1.
- [x] FFI bridge (`crates/wowkispice-ffi`): hand-written `extern "C"` from `sharedspice.h`, runtime `LoadLibraryExA`/`dlopen`, 15 symbols resolved lazily (14 required; `ngGetVSRCData` optional because the bundled build omits it).
- [x] C++/Qt5 GUI (`gui/`) with four views: schematic editor, waveform viewer, co-sim dashboard, code/text workspace. Clean rebuild verified 2026-11-07 (`--clean-first`, exit 0, 0 warnings); requires Qt5 Charts.
- [x] Controller logic parity: Rust tests reproduce the firmware's 1995/2030 thresholds and match the Python mock (`test_buck_controller_hysteresis.rs`, `test_buck_controller_industry.rs`).
- [x] Parity harnesses (`crates/parity`) diff Rust modules against the Python originals.
- [x] QEMU retired from the shipped path; legacy modules and tests retained for history.
- [x] `firmware_control.dll` built from `buck_controller_tick.c` — an artifact, not a wired dependency.

**Evidence:** core 334/0/0; FFI **27/27** (fixed: load with `LOAD_WITH_ALTERED_SEARCH_PATH`, `ngGetVSRCData` optional);
GUI clean rebuild exit 0 / 0 warnings; `docs/architecture.md` records the
shipped loop and the legacy table.

---

# Phase 1 — Reproducible Environment

**Status: `[x]` COMPLETE for Windows.**

- [x] `setup.ps1` creates the venv, installs requirements, prepares the ngspice DLL, writes `.env.local`, runs cleanup/fetch/doctor.
- [x] `tools/setup.sh` and `tools/run_selfcheck.sh` exist for POSIX shells; **not verified on Linux/macOS**.
- [x] `run_selfcheck.bat` resolves `.venv\Scripts\python.exe` directly; `tools/selfcheck.py` re-executes under the project venv when started with another `python`.
- [x] Gate exits non-zero on a failed check (verified by removing a quick-suite file: exit 1; bad flag: exit 2).
- [x] Regression test starts the gate with the base (non-venv) interpreter and asserts it re-execs into `.venv`: `tests/test_selfcheck.py::test_non_venv_python_reexecutes_into_the_project_venv`.
- [x] Dockerfile / docker-compose recorded as building and running (2026-11-06). **Not re-verified:** `docker info` exits 1 on this host (daemon not running).
- [x] QEMU orphan cleanup tooling (`tools/cleanup_qemu.py`) recorded against a real orphan.

**Acceptance:** fresh clone + `setup.ps1` completes; `run_selfcheck.bat` prints
`SELF-CHECK: PASS` and exits 0 — **met on this host on 2026-11-07**.

---

# Phase 2 — Deterministic & Regression-Testable

**Status: `[x]` COMPLETE (framework and metrics in place).**

- [x] Golden-trace save/load/compare (`tools/golden_trace.py`), reference data under `tests/golden/`.
- [x] Sync timing measured on the QEMU path (recorded: flip 20.3–20.8 ms, HMP round trip ≤10.5 ms, 30/30 flips) and documented in `docs/time-sync.md`.
- [x] Fault-injection/adversarial tests (106/106 recorded) — several are `unittest.mock` doubles, stated as such.
- [x] Headless CLI (`tools/cli.py`) runs without PyQt; five commands present.
- [x] Fixed a real measurement flake this pass: `tools/loop_repeat.py` rounded `flip_s` to 4 decimals, so a first-poll flip could record `0.0`; now 6 decimals, test passes 5/5 standalone and in the full gate.

**Acceptance:** deterministic gate flip 10/10; golden traces within documented
tolerance; CLI headless — **met as recorded**.

---

# Phase 3 — Professionalize

**Status: `[~]` IN PROGRESS.**

- [x] Traceability tooling: `tools/check_traceability.py` parses 14 requirements and 16 marked tests and fails on zero rows/tests. Verified with its required input: `python -m pytest tests --junit-xml=tests/junit.xml -q` then `python tools/check_traceability.py tests/junit.xml` → exit 0, `TRACEABILITY OK: 14 requirements, 16 tests`.
- [x] `docs/requirements.md` carries the 14 requirement rows, including CO-05 marked as the legacy QEMU path.
- [~] CI workflow exists (`.github/workflows/cosim-ci.yml`) and is asserted by `tests/test_ci_workflow.py`, but **CI has not been executed on a runner**; only local `cargo test` is verified.
- [ ] Structured logging / log levels / correlation IDs.
- [~] Packaging entry points partly present: `pyproject.toml` declares `wosp-check` and `wosp` (both import and expose `main`), but `wosp-gui` targets `gui:main`, which does not exist. Release process absent (`docs/RELEASE.md`).
- [x] README/plan reconciled to measured evidence (this pass).

**Acceptance:** traceability non-vacuous; CI executed green on a fresh clone;
packaging and release process documented; no doc claim contradicted by a command.

---

# Phase 4 — Validation & Sign-off

**Status: `[~]` IN PROGRESS.**

- [x] Core suite green: 334/0/0.
- [x] Full Python gate green: 547 passed / 4 skipped / 0 failed, exit 0.
- [x] Controller verification: `cargo test -p wowkispice-core test_hysteresis` passes.
- [x] FFI suite: 27/27; DLL loading fixed via `LOAD_WITH_ALTERED_SEARCH_PATH` flag; all tests pass
- [ ] Fresh-clone end-to-end run on a separate directory.
- [ ] Docker fresh build/run sign-off.
- [ ] Golden-trace sign-off against reference data.
- [ ] Full documentation review beyond the four reconciled files.

**Acceptance:** fresh clone → setup → gate → suite all green; Docker fresh build
green; golden traces signed off; every doc claim traceable to a command or file.

---

# Phase 5 — Product Hardening & Distribution

**Status: `[ ]` NOT STARTED (one artifact exists, unverified).**

- [~] Windows installer: `installer/wowkispice_installer.exe` exists (124,773 bytes, NSIS PE32), but `installer/wowkispice_installer.nsi` contains literal `<USERPROFILE>` placeholder paths, has no `OutFile`/pages, and `makensis` is not installed. It is not reproducible from the checkout and has not been installed on a clean machine.
- [ ] SBOM generation (`cyclonedx-py` or `pip-audit`).
- [ ] Save-format migration/versioning on load.
- [ ] Parameter-sweep automation: 16 industry tests exist; no `tools/run_sweep.py`.
- [ ] Cross-platform verification of `setup.sh` / `run_selfcheck.sh` / GUI on Linux/macOS.
- [ ] i18n/a11y baseline and crash reporting.

**Acceptance:** installer builds from a tracked script and installs/runs on a
clean Windows machine; SBOM published; sweep tool produces golden comparisons;
POSIX path verified.

---

# Phase 6 — Optional Regulated Workflows

**Status: `[ ]` NOT STARTED (optional; external scope).**

- [ ] DO-330-style traceability matrix plus SBOM toolchain.
- [ ] Pilot checklist executed with recorded evidence artifacts.
- [ ] Release notes quoting the gate verdict and open defects per tag.

Requires an external certification/qualification scope; not a prerequisite for
the engineering tool.

---

# Deferred (unscheduled, not a phase)

- **PyQt6 GUI + local Ollama co-pilot.** Owner decision: skipped while the C++/Qt5 GUI is the shipped surface. Old label: “Phase 4” in `DELIVERABLE_SUMMARY.md` and `docs/industry-readiness.md`.
- **Firmware migration to `esp-hal` + `rtic`.** Continuous-improvement item, no schedule.
- **AI design assistant.** Deferred; no implementation.

---

# Success metrics (measured)

| Metric | Measured | Target | Status |
|---|---|---|---|
| Rust core suite | 334 passed, 0 failed, 0 warnings | 0 failed | PASS |
| Python environment gate | 547 passed, 4 skipped, exit 0, 229.43 s | 0 failed | PASS |
| FFI suite | 27 passed, 0 failed | 0 failed | PASS |
| Deterministic gate flip | 10/10 runs, 30/30 flips (recorded) | 10/10 | RECORDED |
| Orphaned processes | Zero after hard kill (recorded) | Zero | RECORDED |
| Installer | Artifact exists; build/install unverified | Reproducible + clean install | NOT MET |
| Traceability | 14 requirements / 16 executed tests | non-vacuous | PASS |

---

# Phase-label mapping (for older documents and notes)

| Old label | Appears in | Canonical phase |
|---|---|---|
| Phase 0 Foundation | ROADMAP (old) | 0 |
| Phase 1 P0 Reproducible | ROADMAP (old) | 1 |
| Phase 2 P1 Deterministic | ROADMAP (old) | 2 |
| Phase 3 P2 Professionalize | ROADMAP (old) | 3 |
| Phase 4 Validation | ROADMAP (old) | 4 |
| Phase 0 Honest & installable | `docs/industry-readiness.md` (old) | 3 |
| Phase 1 Engineering credibility | `docs/industry-readiness.md` (old) | 3 + 4 |
| Phase 2 Product hardening | `docs/industry-readiness.md` (old) | 5 |
| Phase 3 Regulated workflows | `docs/industry-readiness.md` (old) | 6 |
| Phase 4 PyQt6 + Ollama | `docs/industry-readiness.md` (old) | Deferred |
| Phase 5 parameter sweep | `docs/industry-readiness.md` (old) | 5 |
| Phase 6 installer + badge | `docs/industry-readiness.md` (old) | 5 |
| Phase 0 baseline | `DELIVERABLE_SUMMARY.md` (old) | 0 |
| Phase 1 FFI consolidation | `DELIVERABLE_SUMMARY.md` (old) | 0 |
| Phase 2 QEMU replacement | `DELIVERABLE_SUMMARY.md` (old) | 0 |
| Phase 3+ Industrial hardening | `DELIVERABLE_SUMMARY.md` (old) | 0 + 5 |
| Phase 4 PyQt6 | `DELIVERABLE_SUMMARY.md` (old) | Deferred |
| Phase 5 sweep | `DELIVERABLE_SUMMARY.md` (old) | 5 |
| Phase 6 installer | `DELIVERABLE_SUMMARY.md` (old) | 5 |

**Last measured:** 2026-11-07.
**Next gate:** Phase 3 (CI execution, packaging) → Phase 4 (fresh-clone sign-off) → Phase 5 (reproducible installer).
