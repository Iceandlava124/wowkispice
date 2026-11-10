# Industry-Readiness Assessment

This page states the verdict and the acceptance gates. **Phase numbers are defined
in `ROADMAP.md`**; this page uses those numbers and does not define its own.

## Verdict (measured 2026-11-07)

- **YES as a pilot / prototyping / teaching tool.** A real ngspice solver, a
  buildable Qt5 GUI, firmware-derived controller logic, and a working test hub
  are all present and verifiable in one checkout.
- **YES as a production-facing controller layer.** The hysteretic controller
  logic is hardened and exhaustively tested at the logic level. It is **not** a
  claim about compiled firmware on real silicon.
- **NO as a certified or regulated product.** No UL/IEC/DO qualification, no
  hardware correlation, no calibrated-instrument claim.

Measured evidence:

| Check | Result |
|---|---|
| `cargo test -p wowkispice-core` | 334 passed, 0 failed, 0 warnings |
| `cargo test -p wowkispice-ffi` | 27 passed, 0 failed (DLL loading fixed via `LOAD_WITH_ALTERED_SEARCH_PATH`) |
| `run_selfcheck.bat` (clean shell) | `SELF-CHECK: PASS`, exit 0; 547 passed, 4 skipped in 229.43 s |
| Controller hysteresis | `cargo test -p wowkispice-core test_hysteresis` passes |
| Installer | Artifact exists (124,773 bytes); NSIS script fixed (`RequestConfirmation` removed, file paths made relative); compiled with `makensis` v3.x; clean-machine install **unverified** |

The gate resolves the project interpreter itself: `run_selfcheck.bat` calls
`.venv\Scripts\python.exe`, and `tools/selfcheck.py` re-executes under the repo
venv when started with another `python`. Earlier failures came from running the
gate with the system interpreter, which lacks the project dependencies.

## Blockers and dispositions

| Blocker | Disposition | Evidence |
|---|---|---|
| Silent BOM substitutions | Fixed — BOM is drawing-derived | `cad_engine.generate_bom()` |
| Controller model vs firmware | Addressed at the **logic** level; no shipped code loads `firmware_control.dll` | grep over `crates/`, `gui/`, `bridge/`; hysteresis tests |
| No external validation corpus | Extended — closed-form proofs + 16 industry tests | `test_buck_controller_industry.rs` |
| No packaging/versioning | Partial — entry points exist but `wosp-gui` is broken; installer unverified | `pyproject.toml`; installer artifact |
| Coverage asymmetry | Extended — 334 core tests include industry tests; FFI 27/27 | measured this turn |
| Compliance implied, not established | Bounded in `docs/industry-credibility-baseline.md` | public docs |
| Windows-centric | POSIX **partially verified**: quick self-check passes on WSL Ubuntu 24.04; full Linux suite not green (libngspice segfault after repeated init) | `tools/setup.sh`, `tools/run_selfcheck.sh` |
| No installer/i18n/crash reporting | Open — Phase 5 | `.nsi` placeholders |

## Canonical phase plan

Acceptance criteria are checkable gates. `ROADMAP.md` carries the detailed
task lists and the mapping from older labels.

| Phase | Goal | Status | Acceptance gate |
|---|---|---|---|
| **0 — Foundation** | Solver, FFI, GUI, controller parity, parity harnesses | COMPLETE | core 334/0/0; FFI 27/27; GUI clean rebuild exit 0 / 0 warnings; logic parity tests pass |
| **1 — Reproducible environment** | One-command setup and an honest gate | COMPLETE (Windows) | `run_selfcheck.bat` → PASS, exit 0 from a clean shell; setup idempotent |
| **2 — Deterministic & regression-testable** | Golden traces, sync bounds, fault injection, headless CLI | COMPLETE | gate flips 10/10; golden traces within tolerance; CLI headless |
| **3 — Professionalize** | Traceability, CI execution, logging, packaging, release | IN PROGRESS | traceability non-vacuous; CI green on a runner; packaging/release documented |
| **4 — Validation & sign-off** | Fresh-clone proof and documentation review | IN PROGRESS | fresh clone → setup → gate → suite green; Docker fresh build; golden sign-off |
| **5 — Product hardening & distribution** | Reproducible installer, SBOM, sweep tool, POSIX verification | NOT STARTED | installer builds from tracked script and installs cleanly; SBOM published |
| **6 — Optional regulated workflows** | DO-330-style traceability and pilot evidence | NOT STARTED (optional) | traceability matrix + SBOM toolchain; pilot checklist recorded |

### Deferred (unscheduled)

- PyQt6 GUI + local Ollama co-pilot — owner decision; the C++/Qt5 GUI is the
  shipped surface. This was labelled “Phase 4” in older revisions of this file.
- Firmware migration to `esp-hal` + `rtic`.
- AI design assistant.

## Where the work sits relative to existing artifacts

- **Phase 0** is delivered: `crates/`, `gui/`, parity harnesses, hardening report.
- **Phase 1** is delivered on Windows: `setup.ps1`, `run_selfcheck.bat`, `tools/setup.sh`.
- **Phase 2** is delivered: `tools/golden_trace.py`, `docs/time-sync.md`, fault-injection tests, `tools/cli.py`.
- **Phase 3** is the current engineering-credibility job: run CI for real, add logging, finish packaging (`wosp-gui` entry point is broken) and the release process.
- **Phase 4** is the sign-off pass: fresh clone, Docker, golden traces, documentation review.
- **Phase 5** is distribution: installer, SBOM, sweep automation, POSIX checks.
- **Phase 6** is optional regulated scope and needs external qualification.

## Automated guards

- `tools/selfcheck.py` / `run_selfcheck.bat` — five checks; exit 0 only when all pass.
- `tools/run_tests.py` — full suite, measured 547 passed / 4 skipped.
- `tools/check_traceability.py` — fails on zero requirements or zero marked tests.
- `docs/architecture.md` — shipped-vs-legacy component map.
- `docs/industry-credibility-baseline.md` — the public trust boundary.
