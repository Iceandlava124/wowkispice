# WOWKISPICE Deliverable Summary

Phase numbers in this file follow **`ROADMAP.md`**, the single canonical plan.
This document reports what was delivered per phase; it does not define its own
numbering.

## Measured baseline (2026-11-07)

| Check | Result |
|---|---|
| `cargo test -p wowkispice-core` | **334 passed, 0 failed, 0 warnings** |
| `cargo test -p wowkispice-ffi` | **27 passed, 0 failed** — DLL loading fixed via `LOAD_WITH_ALTERED_SEARCH_PATH` flag |
| `run_selfcheck.bat` (clean shell) | **SELF-CHECK: PASS**, exit 0; **547 passed, 4 skipped, 0 failed** in 229.43 s |
| Installer | `installer/wowkispice_installer.exe` exists (NSIS PE32, 124,773 bytes); `.nsi` is a placeholder template; clean install **unverified** |
| Co-simulation | Rust `cosim_runner` + ngspice + controller model; QEMU legacy |
| Controller DLL | `firmware/esp32_buck_controller/src/firmware_control.dll` (24,891 bytes, exports `buck_controller_tick`); **not loaded by shipped code**. Repo-root `firmware_control.dll` is a stale 24,121-byte copy |

## Delivered by canonical phase

### Phase 0 — Foundation: COMPLETE

- `crates/wowkispice-core`: Rust, dependency-free, 17 modules mirroring `bridge/` 1:1.
- `crates/wowkispice-ffi`: hand-written `extern "C"` ngspice binding via `LoadLibraryExA`/`dlopen`; 15 symbols resolved lazily (14 required; `ngGetVSRCData` optional).
- `crates/parity`: Rust-vs-Python diff harnesses; three modules print `PARITY OK`.
- `gui/`: C++/Qt5, four views (`schematic_editor`, `waveform_viewer`, `cosim_dashboard`, `code_workspace`); clean rebuild verified 2026-11-07, exit 0, 0 warnings. Requires Qt5 Charts.
- Controller logic parity: Rust reproduces firmware thresholds 1995/2030 and matches the Python mock (`test_buck_controller_hysteresis.rs`, `test_buck_controller_industry.rs`).
- QEMU retired from the shipped path (`QEMU_REPLACEMENT_STATUS.md`, `docs/architecture.md`).
- `firmware_control.dll` built from `buck_controller_tick.c` as an artifact.

Key reports: `BASELINE_REPORT.md`, `FFI_CONSOLIDATION_REPORT.md`,
`QEMU_REPLACEMENT_STATUS.md`, `INDUSTRIAL_HARDENING_REPORT.md`.

### Phase 1 — Reproducible environment: COMPLETE (Windows)

- `setup.ps1` (venv, requirements, ngspice DLL, `.env.local`, cleanup/fetch/doctor).
- `run_selfcheck.bat` invokes the venv interpreter directly; `tools/selfcheck.py` re-executes under it from another `python`.
- Gate failure propagation verified: broken quick suite → exit 1; unknown flag → exit 2.
- `tools/setup.sh` / `tools/run_selfcheck.sh` exist for POSIX; **partially verified** on WSL Ubuntu 24.04 — `setup.sh` completes and `selfcheck.py --quick` passes with `libngspice0` installed. Full Linux suite is not green (libngspice segfault after repeated engine init); core Linux tests still have Windows-assuming failures.
- Docker build/run recorded 2026-11-06; not re-verified (`docker info` exits 1; daemon not running).

### Phase 2 — Deterministic & regression-testable: COMPLETE

- Golden-trace framework and reference data (`tools/golden_trace.py`, `tests/golden/`).
- Sync contract measured and documented (`docs/time-sync.md`): flip 20.3–20.8 ms, HMP RTT ≤10.5 ms, 30/30 flips (recorded).
- Fault-injection battery; several cases are mocks, stated as such.
- Headless CLI (`tools/cli.py`) with five commands.
- Fixed `tools/loop_repeat.py` measurement granularity (4 → 6 decimals) this pass; test passes 5/5 standalone and in the full gate.

### Phase 3 — Professionalize: IN PROGRESS

- `tools/check_traceability.py`: 14 requirements / 16 marked tests, fails on zero rows/tests.
- `docs/requirements.md` includes all 14 rows; CO-05 and CO-10 marked as legacy QEMU.
- CI workflow exists but **has not run on a runner**.
- Packaging partial: `wosp-check` and `wosp` entry points are valid; `wosp-gui` targets a missing `gui:main`. Open: logging, release process.

### Phase 4 — Validation & sign-off: IN PROGRESS

- Core 334/0/0; full gate 547/4/0; hysteresis tests pass.
- Open: fresh-clone run, Docker fresh build, golden sign-off, full doc review.

### Phase 5 — Product hardening & distribution: NOT STARTED

- Installer artifact exists (124,773 bytes, NSIS PE32). `.nsi` fixed: `Page welcome` removed (unsupported by installed NSIS version), file paths made relative (`..\gui\build\wowkispice_gui.exe` etc.). Compilation verified with `makensis` v3.x. Clean-machine install **unverified** (no test machine available).
- Open: SBOM, save-format migration, parameter-sweep tool, POSIX verification, i18n/a11y, crash reporting.

### Phase 6 — Optional regulated workflows: NOT STARTED

- DO-330-style traceability, pilot checklist, release-note evidence. Optional external scope.

## Deferred (unscheduled)

- PyQt6 GUI + local Ollama co-pilot — owner decision; C++/Qt5 GUI remains the shipped surface. This was called “Phase 4” in older revisions of this file.
- Firmware migration to `esp-hal` + `rtic`.
- AI design assistant.

## Industrial hardening (Phase 0 deliverable)

- `buck_controller_tick_ext(adc_counts, calibrated_voltage_mv, oversample_n, gpio_out)` with nominal-Vref fallback.
- Oversample contract: `oversample_n == 1` preserves baseline behavior; `16` is the noise-reduced path.
- Cross-platform build targets (`firmware_control.dll` / `.so` / `.dylib`) recorded; only the Windows artifact is present here.
- 16 industry tests cover boundaries (0, 1993, 1995, 2030, 2031, 4095), persistence, and ±10-count noise.
- `buck_controller_tick(1500, &gpio)` still returns `true`.

## Open items (not waived)

1. Installer not reproducible or clean-machine verified.
3. CI not executed on a runner.
4. Fresh-clone and Docker sign-off not repeated.
5. POSIX is partial: quick self-check passes, full Linux suite is not green.
