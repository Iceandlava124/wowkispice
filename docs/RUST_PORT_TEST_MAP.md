# RUST_PORT_TEST_MAP.md — test-suite porting map (Python → Rust)

**Purpose.** Every file in `tests\*.py` (38 files, 10,557 LOC, 550 collected tests at
baseline 546 passed / 4 skipped) must eventually gate the Rust rewrite. This document
maps each test file — and each separable class group inside mixed-concern files — to
the Rust module that will own it, classifies the porting difficulty, and numbers the
waves so the suite can be ported module-by-module instead of file-by-file.

**Date:** 2026-11-03. **Counts source:** `(Get-Content <file>).Count` for LOC and
`pytest --collect-only -q` per-file for tests (550 collected; `def test_` grep gives
543 because 2 `parametrize` decorators add 4 collected cases in
`test_solver_error_handling.py`, 3 in `test_qemu_monitor_unit.py`, and one
`def test_` in `test_editor_workflow.py` is not collected).

**How to maintain it as modules land:**
- When a Rust module lands with its ported tests, flip that row's classification to
  `ALREADY GATED` and record the Rust/C gate location (like the control_law rows).
- When a parity harness lands, add it under "Parity harness coverage" with the Python
  files it *complements*.
- Wave numbers are dependency estimates: if a wave-1 module turns out to depend on a
  later wave, move the affected rows and say why in the notes.
- Questions in the "Needs a human" section get answered here, not guessed.

---

## 1. Master table

Legend — classification: **PURE-LOGIC** (port + gate with no solver/CLI/hardware),
**BLOCKED-ON-FFI** (needs the ngspice FFI layer, deliberately not ported — see
`native\include\wowkispice\netlist.h` "WHAT IS NOT PORTED"), **EXTERNAL** (spawns
subprocesses/QEMU/network or needs PyQt5), **SKIP-OR-REDESIGN** (no Rust future as-is).
Wave: `1` leaf modules — start now; `2` depends on wave-1 modules only; `3` = blocked
rows (unblock = FFI); `4` = external rows; `—` = not a test / redesign.

| test file (class / group) | Py LOC | tests | project imports | Rust owner module | classification | wave | notes |
|---|---:|---:|---|---|---|---|---|
| `conftest.py` | 18 | 0 | — | test harness infra | SKIP-OR-REDESIGN | — | Registers `qemu` + `req("ID")` markers. Rust runner needs an equivalent requirement-tag scheme or traceability moves to the build. **[Q1]** |
| `hidpi_probe.py` | 163 | 0 | `ui.theme`, `ui.schematic_editor`, `ui.schematic_scene` | — | SKIP-OR-REDESIGN | — | Not collected (no `test_` prefix): manual HiDPI probe script. Fold into Qt5 GUI redesign or drop. **[Q2]** |
| `test_control_law_unit.py` (all 5 classes) | 232 | 18 | `bridge.control_law` | `wowkispice-core::control_law` | **ALREADY GATED** | 1 (done) | Green gate: `native\tests\test_control_law.c` (all 18). Rust crate must carry the same gate; `parity_control_law` complements. |
| `test_adc_conversion.py` (all 2 classes) | 136 | 12 | `bridge.control_law` | `wowkispice-core::control_law` | **ALREADY GATED** | 1 (done) | Green gate: `native\tests\test_control_law.c` (all 12). |
| `test_cosim_control.py` — control-law classes: `TestControlLawSpec`, `TestHystereticDecision`, `TestFirmwareImport`, `TestPwmLaw`, `TestDividerSemantics`, `TestFidelityGap` | 257 | 25 | `bridge.control_law`, `bridge.cad_engine`, firmware `main.c` fixture | `wowkispice-core::control_law` | **ALREADY GATED** | 1 (done) | C gate ports the 6 classes; 3 of the 4 cosim `TestFidelityGap` tests are folded into the unit-file fidelity trio (dedup, noted at the C function), the 4th transcribed. |
| `test_cosim_control.py` — `TestNetlistEmission` | 43 | 4 | `bridge.control_law`, `bridge.cad_engine` | `cosim_runner` (+`cad_engine`) | PURE-LOGIC | 2 | Pure `compile_netlist()` text assertions (`external` source, save/reload, warnings). ⚠ The `test_control_law.c` header lumps it with solver tests — inspection shows no solver call. **[Q3]** |
| `test_cosim_control.py` — `TestCosimEndToEnd` (+ shared fixtures, ~64 LOC) | 163 | 5 | `bridge.cosim_runner`, `bridge.cad_engine` | `cosim_runner` | BLOCKED-ON-FFI | 3 | Closed-loop regulation runs through `run_cosim()` → ngspice. |
| `test_esp32_regs.py` | 86 | 16 | `bridge.esp32_regs` | `wowkispice-core::esp32_regs` | PURE-LOGIC | 1 | Module already ported (`esp32_regs.rs`); gate can be transcribed now. |
| `test_ngspice_sanitiser.py` (all 5 classes) | 383 | 36 | `bridge.ngspice_wrapper` (static methods) | `wowkispice-core::netlist` | **ALREADY GATED** | 1 (done) | Rust: `crates\wowkispice-core\tests\test_netlist.rs` — 48 tests (36 from this file incl. the foreign-cwd subprocess test re-pointed at the venv Python, + the 4 security-vector validate_cmd rows + 4 RUST-ONLY deck tests + pure halves of the security rows). `parity_netlist` complements. The DLL-only `test_engine_load_rejects_it...` stays in Python; its domestic-phase and marker observable transcribed (documented in place). |
| `test_security_vectors.py` — `_MarkerCase` + `TestNetlistVectors` + `TestCommandVectors` (+ header ~73 LOC) | 278 | 11 | `bridge.ngspice_wrapper` (validate_cmd, sanitise, shadowed DLL entry points) | `wowkispice-core::netlist` | **ALREADY GATED (pure halves)** | 1 | The validate_cmd rejections (`TestCommandVectors` 2/3/5/6/7/separators) and the legitimate-command row are in `test_netlist.rs` with the `calls == []` engine-Ffi half left in Python. Vectors 1/4/8/9 mechanically overlap the sanitiser tests above (marker/calls API is the Python-only evidence — unchanged in pytest). |
| `test_security_vectors.py` — `TestLocalSocketBinding`, `TestTrackedFileHygiene` | 145 | 6 | `git ls-files`, source-text scans | repo hygiene (no module) | SKIP-OR-REDESIGN | — | Scans *Python* sources / tracked files. Does it rescan Rust sources, stay Python during transition, or move to CI? **[Q4]** |
| `test_solver_error_handling.py` — `TestFailureReportClassifier`, `TestNonFiniteNeverBecomesACount` | 102 | 14 | `bridge.ngspice_wrapper._failure_report`, `bridge.control_law`, `bridge.binary_runner` | `netlist` + `control_law` (+`binary_runner::_adc_counts_from_voltage`) | PURE-LOGIC | 1 | Classifier is the netlist gate's stated target (see `netlist.h`); 14 = 10 `def test_` + 4 parametrized. |
| `test_solver_error_handling.py` — `TestMalformedNetlistRaises`, `TestNonConvergentAnalysisRaises`, `TestHealthyDeckStillRuns`, `TestCompletedTransientIsNotAFailure` (+ deck fixtures ~130 LOC) | 270 | 10 | `bridge.ngspice_wrapper.NgSpiceEngine` | `ngspice_wrapper` FFI layer | BLOCKED-ON-FFI | 3 | R5: bad decks must error from the captured output stream, not rc. Unblocked only when the FFI layer exists. |
| `test_measurements.py` — `TestCursors`, `TestTraceStats`, `TestFft`, `TestBodeMaths`, `TestPowerMetrics`, `TestStepMetrics` | 233 | 27 | `bridge.measurements` | `wowkispice-core::measurements` | PURE-LOGIC | 1 | Landed: `measurements.rs` ported (27 tests), `parity_measurements` harness green (PARITY OK — 27 values). Solver-driven classes (`TestAgainstRealSolver`, `TestNoiseAndYield`, `TestDistortion`) stay Python-gated (wave 3). |
| `test_measurements.py` — `TestAgainstRealSolver`, `TestNoiseAndYield`, `TestDistortion` (+ shared rc fixture ~52 LOC) | 205 | 9 | `bridge.analysis_runner`, `bridge.ngspice_wrapper` | `analysis_runner` + FFI | BLOCKED-ON-FFI | 3 | Noise/FFT/Bode/distortion through a real ngspice run. |
| `test_firmware_gpio.py` — `TestIntelHex`, `TestElf`, `TestGpioProfile`, `TestLogicAnalysis` | 179 | 20 | `bridge.firmware`, `bridge.gpio_model` | `wowkispice-core::firmware`, `gpio_model` | PURE-LOGIC | 1 | HEX/ELF parsing, SPICE-card emission, logic analysis on synthetic pins. `firmware.rs` landed (SHA-256 fix + parity OK, 27/27); `gpio_model.rs` landed (ported with unit tests). |
| `test_firmware_gpio.py` — `TestGpioCosimEndToEnd` | 48 | 4 | `bridge.cad_engine`, `bridge.ngspice_wrapper` | `cosim_runner` + FFI | BLOCKED-ON-FFI | 3 | GPIO pin drives real solver physics. |
| `test_firmware_gpio.py` — `TestRealEsp32Firmware` (+ `REAL_ELF`/repo fixtures ~103 LOC) | 155 | 4 | firmware build artifact (`.pio/build/.../firmware.elf`, not committed) | `wowkispice-core::firmware` | EXTERNAL | 4 | Skips when the 3 MB ELF hasn't built. Keep skip semantics, or gate on a committed tiny fixture. **[Q5]** |
| `test_firmware_gpio.py` — `QemuMonitorDouble` + `TestQemuGateBridge` | 112 | 4 | `bridge.qemu_monitor` (cycle_adc_and_gate, sweep_report) | `wowkispice-core::qemu_monitor` (candidate) | PURE-LOGIC | 1 | In-process double, "no process, no socket, no real QEMU" — wiring/order assertions only. |
| `test_closed_loop_buck.py` — `TestThresholdsMatchFirmware` (+ header ~20 LOC) | 42 | 2 | `bridge.mock_controller` constants, `bridge.control_law` | `mock_controller` + `control_law` | PURE-LOGIC | 1 | Boundary agreement between mock controller and control law; constants only. |
| `test_closed_loop_buck.py` — `TestClosedLoopBuck` | 23 | 1 | `bridge.mock_controller.run_closed_loop_simulation` | `mock_controller` | BLOCKED-ON-FFI | 3 | `run_closed_loop_simulation` builds `NgSpiceEngine`. |
| `test_closed_loop_buck.py` — `TestGetSyncDataArityMatchesHeader` | 158 | 3 | ctypes `CFUNCTYPE` vs firmware header text | — (ctypes-specific) | SKIP-OR-REDESIGN | — | Rust has no ctypes: becomes a compile-time signature check or a `RUST-ONLY ADDITION`. **[Q6]** |
| `test_load_step_injection.py` — `test_load_stepper_creation` (+ header) | 22 | 1 | `bridge.load_stepper` | `wowkispice-core::load_stepper` | PURE-LOGIC | 1 | Module already ported (`load_stepper.rs`). |
| `test_load_step_injection.py` — `test_load_step_injection_in_cosim` | 42 | 1 | `bridge.cosim_runner`, `bridge.cad_engine` | `cosim_runner` + FFI | BLOCKED-ON-FFI | 3 | Calls `run_cosim()` end-to-end. |
| `test_kicad_export.py` — `TestSchematicStructure`, `TestPinMapping`, `TestNetlistExport` (+ header ~79 LOC) | 163 | 13 | `bridge.cad_engine`, `bridge.kicad_export` | `cad_engine`, `kicad_export` | PURE-LOGIC | 1 | Balanced s-expressions, canonical pin → KiCad pin numbers, netlist export. |
| `test_kicad_export.py` — `TestRealKiCadRoundTrip` | 24 | 1 | `kicad-cli` subprocess | `kicad_export` | EXTERNAL | 4 | Skips when kicad-cli absent. |
| `test_cad_engine.py` (Rust-only gate) | — | 36 | `bridge.cad_engine` | `cad_engine` | **ALREADY GATED** | 1 | Rust-only gate (no Python equivalent): `crates/wowkispice-core/tests/test_cad_engine.rs` — SchematicComponent defaults/to_dict/from_dict, is_mcu(), add/remove component/add_wire/clear, generate_bom()/generate_bom_for(), compile_netlist() (empty→legacy buck, V/I/D/MOSFET/SWITCH/MCU emission, warnings, panic on unknown analysis/mcu_pins), to_dict()/load_dict() round-trip, generate_spice_netlist(), export_kicad_schematic() stub error. |
| `test_binary_runner.py` — `TestBinaryRunner`, `TestReadUntilStable` (+ header ~15 LOC) | 106 | 5 | `bridge.binary_runner` (helpers), `bridge.cad_engine` | `binary_runner` (leaf helpers) | PURE-LOGIC | 1 | Missing-image/missing-qemu early-exit paths + settling logic on a scripted gate. |
| `test_binary_runner.py` — `TestLaunchPath`, `TestDividerSemantics`, `TestGateFlipVoltagePath`, `TestProgressAndLoadStepping`, `TestSyncModes`, `TestAbortState` (+ `_RecordingMonitor`/`_RecordingStepper` doubles) | 306 | 14 | `bridge.binary_runner.run_binary_cosim` (patched monitor seam) | `binary_runner` + FFI | BLOCKED-ON-FFI | 3 | Full runs: `run_binary_cosim` creates `NgSpiceEngine`; monitor faked at Python's import-site seam — Rust needs an injectable monitor trait. Note `TestDividerSemantics::test_firmware_threshold_counts_round_trip...` is pure (test it with wave 1 if split). |
| `test_adversarial_stress.py` (`TestAdversarialQemuMonitor`) | 156 | 10 | `bridge.qemu_monitor` (mocked `_proc`), `bridge.binary_runner` | `qemu_monitor`, `binary_runner` | PURE-LOGIC | 2 | 9/10 tests are mocked-protocol/ADC-clamp assertions; `test_binary_runner_handles_qemu_crash_mid_run` reaches `run_binary_cosim` early-exit — verify it never constructs the engine, else move it to wave 3. |
| `test_firmware_runner` / `test_fault_injection.py` (`TestFaultInjection`) | 64 | 3 | `bridge.firmware_runner` | `firmware_runner` | PURE-LOGIC | 1 | qmp=None failure shapes return `ok=False`, no spawn. |
| `test_industrial_verification.py` | 79 | 5 | `bridge.industrial_verification` | `industrial_verification` | PURE-LOGIC | 1 | No solver import; math + HTML report. |
| `test_golden_traces.py` | 44 | 2 | `tools.golden_trace` | `tools::golden_trace` | PURE-LOGIC | 1 | File-I/O framework test. |
| `test_sota_suite.py` — `test_01`..`test_03`, `test_05`..`test_07` (+ header) | 189 | 6 | `bridge.cad_engine`, `bridge.kicad_export`, `bridge.report_generator`, `bridge.studio_engine` (analytic fns) | `cad_engine`, `kicad_export`, `report_generator`, `studio_engine` | PURE-LOGIC | 1 | CAD graph, KiCad export, BOM, Monte-Carlo (analytic), solar PV (analytic), bus decoder. |
| `test_sota_suite.py` — `test_04_lab_report_generation` | 10 | 1 | `studio_engine.run_simulation` | `studio_engine` + FFI | BLOCKED-ON-FFI | 3 | Report built on metrics from a real run. |
| `test_studio_suite.py` — `test_05` AWG, `test_06` curve tracer, `test_08` UART, `test_09` project JSON | 121 | 4 | `bridge.studio_engine` (analytic fns) | `studio_engine` | PURE-LOGIC | 1 | Verified: `generate_awg_signal`, `trace_mosfet_iv`/`trace_diode_iv`, `decode_uart_packets`, project JSON do not touch the solver. |
| `test_studio_suite.py` — `test_01`–`test_04`, `test_07` (+ setUp) | 161 | 5 | `studio_engine.run_simulation`, `run_real_spice_bode` | `studio_engine` + FFI | BLOCKED-ON-FFI | 3 | Closed-loop, DMM, FFT, Bode, power/thermal all run the solver. |
| `test_ui_parity.py` (all 4 classes) | 223 | 12 | `tools\ui_parity.py` (loaded via importlib), `docs\*.png` fixtures | `tools::ui_parity` | PURE-LOGIC | 1 | Image-metric calibration; no solver/Qt/network. Owner's Rust future is a decision. **[Q7]** |
| `test_cli.py` (all 5 classes) | 251 | 14 | `tools.cli`, `tools.golden_trace`, `bridge.cad_engine`, `bridge.cosim_runner` | `tools::cli` | PURE-LOGIC | 2 | Dispatch + golden commands in-process; QEMU/solver commands mocked at import sites — Rust needs the same seams (traits). Depends on wave-1 `cad_engine`/`golden_trace` + `binary_runner`/`cosim_runner` surfaces. |
| `test_ngspice_bridge.py` | 82 | 1 | `bridge.ngspice_wrapper.NgSpiceEngine` | FFI layer | BLOCKED-ON-FFI | 3 | Point-by-point analytics vs real transient. |
| `test_components_library.py` | 57 | 2 | `bridge.ngspice_wrapper` | FFI layer | BLOCKED-ON-FFI | 3 | Real `.include` of `circuits/components/models.lib` + `.tran`. |
| `test_parameter_sweeps.py` | 107 | 2 | `bridge.ngspice_wrapper` (VSRC/ISRC/SYNC callbacks) | FFI layer | BLOCKED-ON-FFI | 3 | Line/load regulation matrix; ctypes callbacks. |
| `test_ngspice_dll_proof.py` | 199 | 3 | `bridge.ngspice_wrapper`, `tools.prove_physics_engine` | FFI layer (+`tools::prove_physics_engine`) | BLOCKED-ON-FFI | 3 | Gate for the physics proof; unblocked by FFI — also decide the proof script's Rust future. **[Q8]** |
| `test_qemu_monitor_unit.py` | 517 | 18 | `bridge.qemu_monitor`, spawns `tests\fakes\fake_hmp_qemu.py` | `qemu_monitor` | EXTERNAL | 4 | Hermetic but subprocess-based: real `QemuMonitor.start()` launched against the Python HMP fake. Candidate to become wave-2 PURE-LOGIC if Rust grows an in-process HMP double. **[Q9]** |
| `test_qemu_monitor_qemu.py` | 217 | 5 | `bridge.qemu_monitor`, real `qemu-system-xtensa` | `qemu_monitor` | EXTERNAL | 4 | `@pytest.mark.qemu`, skips with stated reason when binary/flash absent. Keep marker + skip contract. |
| `test_loop_repeat.py` | 132 | 4 | spawns `tools\loop_repeat.py` + `tests\fakes\fake_hmp_qemu.py` | `tools::loop_repeat` | EXTERNAL | 4 | R7 harness end-to-end against the fake double (subprocess, JSON contract `R7_JSON:`). Does the R7 harness have a Rust future? **[Q10]** |
| `test_selfcheck.py` | 81 | 3 | spawns `tools\selfcheck.py`, `run_selfcheck.bat` | `selfcheck` | **ALREADY GATED** | 1 | Landed: `selfcheck.rs` ported (loader/package/linter checks). Python spawn replaced by Rust CLI + exit-code contract. Rust gate: `crates/wowkispice-core/tests/test_selfcheck.rs` (5 tests). |

| `test_serial_console.py` | 0 | 0 | `bridge.serial_console` | `serial_console` | PURE-LOGIC | 1 | Landed: `serial_console.rs` ported (18 tests). UART line capture, bounded buffer, case-insensitive grep. `parity_serial_console` green (15 values). |
| `test_qtest_client.py` | 0 | 0 | `bridge.qtest_client` | `qtest_client` | **ALREADY GATED** | 1 | Landed: `qtest_client.rs` ported (TCP client, `Result`-based errors, `Drop` close). Rust gate: `crates/wowkispice-core/tests/test_qtest_client.rs` (16 tests). `parity_qtest_client` future. |
| `test_report_generator.py` | 0 | 0 | `bridge.report_generator` | `report_generator` | **ALREADY GATED** | 1 | Landed: `report_generator.rs` ported (HTML lab report with `{token}` placeholders). Rust gate: `crates/wowkispice-core/tests/test_report_generator.rs` (19 tests). |

| `test_setup_download.py` | 336 | 10 | extracts fn body from `setup.ps1`, child PowerShell, scripted network | installer script | EXTERNAL | 4 | Needs PowerShell + network-shaped fakes. Does the installer survive the rewrite? **[Q11]** |
| `test_tool_fixes.py` | 186 | 7 | spawns `tools\doctor.py`, `tools\check_traceability.py`; `bridge.toolchain_resolver`, `resolve_ngspice_library` | `tools::doctor`, `tools::check_traceability`, `toolchain_resolver` | EXTERNAL | 4 | `toolchain_resolver.rs` landed (env-var qemu/ngspice discovery + status shape + write_env_local); doctor/check_traceability subprocess suites remain Python-side pending their Rust futures. Do they? **[Q12]** |
| `test_schematic_editor.py` | 995 | 40 | `ui.schematic_editor/scene/symbols`, `bridge.cad_engine`, `bridge.analysis_runner` | Qt5 GUI (redesign) | EXTERNAL | 4 (redesign) | Headless PyQt5. `TestSymbolTable` (3) and `TestBomFromGraph` (1) are logic-vs-UI consistency checks; `TestAnalysisPanels` alone is 678 LOC / 21 tests; `TestClosedLoopEditorPath` needs FFI. Whole file belongs to the Qt5 GUI redesign, not a transcription. **[Q13]** |
| `test_editor_workflow.py` | 580 | 40 | `ui.schematic_editor/scene/symbols`, `bridge.*` (binary_runner, kicad_export, cad_engine, cosim_runner, gpio_model, serial_console, ngspice_wrapper) | Qt5 GUI (redesign) | EXTERNAL | 4 (redesign) | 41 `def test_`, 40 collected. 41 `def test_`, 40 collected. Board symbols, gestures, netlist pane, sim controls, pin-map/serial panels, binary-cosim branch — all construct `SchematicEditor`. **[Q13]** |
| `test_ui_polish.py` | 1444 | 76 | `ui.*` (icons, theme, schematic_*), `bridge.measurements`, `bridge.ngspice_wrapper` | Qt5 GUI (redesign) | EXTERNAL | 4 (redesign) | Largest file; `TestHiDpiConsistency` additionally spawns a subprocess probe. **[Q13]** |
| `test_datasheet_symbols.py` | 187 | 8 | `ui.schematic_items/symbols`, `tools.extract_datasheet_img`, PIL/QImage | Qt5 GUI + `tools::extract_datasheet_img` | EXTERNAL | 4 (redesign) | Symbol body precedence (datasheet PNG → square-with-pins → "?") is drawn via Qt; PDF extraction part is a `tools` candidate. **[Q13]** |
| `test_ci_workflow.py` | 45 | 3 | `.github\workflows\cosim-ci.yml` (PyYAML) | — (repo CI config) | SKIP-OR-REDESIGN | — | Tests the CI YAML itself, not product code. Keep as a repo-level check in whatever runner replaces pytest. **[Q14]** |

*(Totals: 10,557 LOC / 550 collected tests across 38 files, including the two
non-test files `conftest.py` and `hidpi_probe.py`. Row LOC for split files sums to
the file's LOC; shared scaffolding/fixtures are assigned to the row that uses them,
noted where it matters.)*

---

## 2. Per-wave summary

| wave | files touched* | Py LOC | can start now? |
|---|---:|---:|---|
| **Already gated** (control_law; 3 entries) | 3 | 625 | **Done** — `native\tests\test_control_law.c` green (56 tests) |
| **Wave 1** — PURE-LOGIC, leaf modules (no unported-module deps) | 17 (+3 gated above) | 2,582 | **Yes** — 191 tests / 2,582 LOC can be transcribed the day their leaf module is ported |
| **Wave 2** — PURE-LOGIC, depends on wave-1 modules only | 2 (`test_cli.py`, cosim `TestNetlistEmission`) | 294 | After wave-1 modules land (18 tests) |
| **Wave 3** — BLOCKED-ON-FFI (ngspice FFI layer) | 13 | 1,673 | **No** — unblocked by: a Rust ngspice FFI crate (the `native\...\netlist.h` "NOT PORTED" list: `NgSpiceEngine`, init/command wiring, vector accessors, `ngSpice_Circ` deck handoff) + `cosim_runner`/`analysis_runner`/`studio_engine` running on it |
| **Wave 4** — EXTERNAL (subprocess / QEMU / network / PyQt5) | 12 | 4,854 | **No** — needs: fake-HMP/real-QEMU binaries, PowerShell+network, kicad-cli, and (for 4 files, 3,206 LOC) the redesigned Qt5 GUI |
| **SKIP-OR-REDESIGN** | 3 (+2 partial) | 529 | Blocked on the 6 human questions below |

\* Files that split across waves are counted in each wave they contribute to. Of the
38 distinct files: 7 are fully wave-1, 11 split across waves, 4 fully wave-3, 1 fully
wave-2, 10 fully wave-4, 3 skip-only, 2 fully already-gated (`cosim_control` spans
gated + wave 2 + wave 3 and is counted among the 11 split).

**Wave 1 in one line:** 18 pure entries (2,582 LOC, 191 tests) + the 3 already-gated
control-law entries (625 LOC, 55 tests) = **3,207 LOC across 20 files can start
immediately**; the only work is porting the leaf module and transcribing its tests.

---

## 3. ALREADY GATED entries

**control_law — GREEN, 56 tests.** Gate: `native\tests\test_control_law.c`
(C harness `native\tests\wosp_test.h`; lib `native\src\control_law.c`;
`native\build\test_control_law.exe`).

- Transcribed from: `tests\test_control_law_unit.py` (all 18),
  `tests\test_adc_conversion.py` (all 12),
  `tests\test_cosim_control.py` control-law classes (25 of 34;
  3 cosim `TestFidelityGap` tests folded as exact duplicates of the unit-file trio —
  deliberate, commented at the C function).
- 56 RUN() = 52 ports + **4 C-ONLY ADDITIONS** (not ports, marked in a loud block
  comment): `test_stats_reports_a_run`, `test_describe_names_the_law`,
  `test_regulation_error_skips_startup`, `test_regulation_error_empty_and_single_sample`
  — covering `stats()` on empty/run, `describe()` on a constructed law, and
  `regulation_error()` which Python never tests. If Python grows equivalents, fold
  them into the ported set and delete the note.
- The Rust `wowkispice-core::control_law` gate must reproduce this contract (same
  test names, greppable both ways per the C header's instruction) — and be labelled
  `RUST-ONLY ADDITION` for anything extra.

**netlist — GREEN, 48 tests.** Gate: `crates\wowkispice-core\tests\test_netlist.rs`
(Rust module `wowkispice-core::netlist`; green run: 48 tests, 0 failed, zero warnings —
36 from `tests\test_ngspice_sanitiser.py` incl. the foreign-cwd subprocess test re-pointed
at the venv Python, + 4 `TestCommandVectors` validate_cmd rows + legitimate-command row
from `tests\test_security_vectors.py`, + 4 RUST-ONLY deck tests covering the domestic
header/end + tstop phases that no engine-free Python test reaches directly).

- Python files the netlist gate now covers:
  - `tests\test_ngspice_sanitiser.py` (whole file, 36 tests),
  - `tests\test_security_vectors.py` validate_cmd pure halves (`TestCommandVectors` +
    the `.control`/include vectors in `TestNetlistVectors`; the `calls == []`
    engine-FFI half stays in Python as decided).
- Follow-up in this module's group (split out of the netlist gate, not faked):
  `tests\test_solver_error_handling.py::TestFailureReportClassifier` (pure half).
- Known unportable-by-construction: Python's `validate_cmd()` TypeError branch
  (a C/Rust `const char *` cannot be "not a string") — documented in the Rust gate,
  not faked.

---

## 4. Parity harness coverage (complement, never duplicate)

Pattern: `native\tools\parity_control_law.py` (+`.c`) — one fixed battery computed
twice (Python vs port), **neither test suite was transcribed from it**, so it catches a
port and its ported test being wrong together. `crates\parity\src\bin\parity_<module>.rs`
holds one Rust binary per module (`parity_control_law`, `parity_netlist`, ...); the
Python driver lives in `crates\parity\python\parity_<module>.py` and feeds fixture
manifests for file-touching batteries.

| harness | status | complements (Python tests — do NOT duplicate) | complements (gate) |
|---|---|---|---|
| `parity_control_law` | **exists** (`native\tools\parity_control_law.py` + `.c`) | `test_control_law_unit.py`, `test_adc_conversion.py`, control-law classes of `test_cosim_control.py` | `native\tests\test_control_law.c`, future `crates\parity` bin |
| `parity_netlist` | **exists** (`crates\parity\src\bin\parity_netlist.rs` + `crates\parity\python\parity_netlist.py`; green run: `PARITY OK — 112 values identical`) | `test_ngspice_sanitiser.py`, `test_solver_error_handling.py::TestFailureReportClassifier`, `test_security_vectors.py` validate_cmd vectors | `native\src\netlist.c`, future Rust `netlist` gate |
| `parity_cad_engine` | future | `test_kicad_export.py` structure/pin rows, `test_schematic_editor.py::TestSymbolTable`/`TestBomFromGraph`, `test_cli.py::TestModelLoading` | `cad_engine` gate |
| `parity_measurements` | exists (`crates/parity/src/bin/parity_measurements.rs` + `crates/parity/python/parity_measurements.py`; `PARITY OK — 27 values identical`) | `test_measurements.py` pure classes (27 tests) | `measurements` gate |
| `parity_studio_engine` | future | `test_studio_suite.py` analytic rows, `test_sota_suite.py` analytic rows | `studio_engine` gate |
| `parity_firmware` | exists (`crates/parity/src/bin/parity_firmware.rs` + `crates/parity/python/parity_firmware.py`; `PARITY OK — 27 values identical`) | `test_firmware_gpio.py` HEX/ELF/profile/logic classes | `firmware` gate |
| `parity_gpio_model` | future | `test_firmware_gpio.py` GPIO classes (`TestGpioProfile`, `TestLogicAnalysis`) | `gpio_model` gate |
| `parity_serial_console` | exists (`crates/parity/src/bin/parity_serial_console.rs` + `crates/parity/python/parity_serial_console.py`; `PARITY OK — 15 values identical`) | `test_serial_console.py` (18 tests) | `serial_console` gate |
| `parity_qtest_client` | future | `test_qtest_client.py` (planned) | `qtest_client` gate |
| `parity_selfcheck` | future | `test_selfcheck.py` (3 tests) | `selfcheck` gate |
| `parity_report_generator` | future | `test_report_generator.py` (planned) | `report_generator` gate |
| `parity_gpio_model` | future | `test_firmware_gpio.py` GPIO classes (`TestGpioProfile`, `TestLogicAnalysis`) | `gpio_model` gate |
| `parity_qemu_monitor` | future | `test_qemu_monitor_unit.py` protocol facts (if the file becomes pure) | `qemu_monitor` gate |
| `parity_toolchain_resolver` | future | `test_tool_fixes.py::test_find_ngspice_honours_the_same_env_var...` | `toolchain_resolver` gate (module already ported) |
| `parity_mock_controller` | future | `test_closed_loop_buck.py::TestThresholdsMatchFirmware` | `mock_controller` gate |
| `parity_binary_runner` | future | `test_binary_runner.py` divider/ADC-count rows | `binary_runner` gate |
| `parity_report_generator`, `parity_industrial_verification`, `parity_load_stepper`, `parity_esp32_regs` | future (as modules land) | their files above | their gates |

Rule of thumb for new harnesses: if a module has both a ported Python test file and a
Rust port, it gets a parity battery that neither side saw.

---

## 5. Fidelity rules (already established — do not renegotiate per file)

1. **Transcribe, never re-invent.** Tests are ported line-for-line from Python:
   same names (greppable both directions), same assertions, same fixtures. Never
   weaken, "simplify", or re-derive expected values during the port.
2. **Split back mixed assertions.** A Python file that mixed concerns was already
   split into its real tests — when a Rust gate groups them differently, the split
   must still be visible (class-per-test, comments pointing at the Python origin).
3. **Delete invented tests.** Tests that were invented and contradicted Python were
   deleted, not reconciled. If a Rust test has no Python counterpart, it is not a port.
4. **Label C/Rust-only extras.** Anything not ported from Python is marked loudly
   (`C-ONLY ADDITION` today, `RUST-ONLY ADDITION` in Rust) in a block comment with the
   reason, exactly like the four in the control_law gate.
5. **Parity over trust.** Transcribed tests cannot catch a port and its ported test
   being wrong together; each module gets a parity harness (section 4) whose battery
   neither suite was transcribed from.
6. **Known-unportable paths are documented, not faked** (e.g. the `validate_cmd`
   TypeError branch; ctypes-arity checks).

---

## 6. UNMAPPABLE / ambiguous — questions for a human

- **[Q1] `conftest.py` + `req("ID")` traceability:** `tools\check_traceability.py`
  parses Python markers. What replaces requirement tags in the Rust suite — Cargo
  attributes, doc comments, a build-time index? (Affects every row with `@pytest.mark.req`.)
- **[Q2] `hidpi_probe.py`:** manual probe, not collected. Fold into the Qt5 GUI
  redesign's test plan, port as a tool, or delete?
- **[Q3] `test_cosim_control.py::TestNetlistEmission`:** `native\tests\test_control_law.c`
  header says it "calls the ngspice solver", but the code only asserts `compile_netlist()`
  text. Confirm it is wave-2 PURE-LOGIC (as mapped) — and correct the C header if so.
- **[Q4] `test_security_vectors.py::TestLocalSocketBinding` + `TestTrackedFileHygiene`:**
  repo-hygiene scans over Python sources and `git ls-files`. Re-point at Rust sources,
  keep scanning both during transition, or move to CI?
- **[Q5] `test_firmware_gpio.py::TestRealEsp32Firmware`:** depends on a gitignored
  3 MB firmware ELF with skip-if-absent. Keep the skip contract, or commit a small
  fixture image?
- **[Q6] `test_closed_loop_buck.py::TestGetSyncDataArityMatchesHeader` (158 LOC):**
  ctypes-vs-header arity checks have no Rust equivalent. Compile-time signature
  assertion? `RUST-ONLY ADDITION`? Or drop?
- **[Q7] `test_ui_parity.py`:** does `tools\ui_parity.py` (image-metric calibration
  over `docs\*.png` references) get a Rust future, especially after the GUI redesign
  invalidates the reference screenshots?
- **[Q8] `tools\prove_physics_engine.py`:** `test_ngspice_dll_proof.py` gates it.
  Does the proof script survive as a Rust tool once the FFI layer exists?
- **[Q9] `test_qemu_monitor_unit.py`:** keep spawning the Python fake
  `tests\fakes\fake_hmp_qemu.py` from Rust tests, or build an in-process HMP double
  (making the file wave-2 pure)? Same question for `tests\fakes\` generally.
- **[Q10] `tools\loop_repeat.py` (R7 harness):** does the harness itself get ported,
  and do its 4 tests stay as an end-to-end subprocess contract?
- **[Q11] `setup.ps1`:** does the installer stay PowerShell (tests stay EXTERNAL as
  mapped), or is it replaced — and by what?
- **[Q12] `tools\doctor.py` / `tools\check_traceability.py`:** Rust futures? If yes,
  `test_tool_fixes.py` splits into 1 wave-1 pure test + external tool tests; if no,
  the whole file is SKIP-OR-REDESIGN.
- **[Q13] Qt5 GUI redesign (4 files, 3,206 LOC — 31% of the suite):**
  `test_schematic_editor.py`, `test_editor_workflow.py`, `test_ui_polish.py`,
  `test_datasheet_symbols.py`. There is no Python equivalent to port against. Which
  behaviours are re-specified in the new Qt5 GUI test plan (e.g. `TestAnalysisPanels`
  678 LOC, `TestHiDpiConsistency`), which are dropped, and who owns that redesign list?
- **[Q14] `test_ci_workflow.py`:** stays as a repo-level YAML check in the new
  runner, or is it superseded by the workflow rewrite itself?

---

*Maintenance log: created 2026-11-03 by the test-map agent (analysis only, no code
touched). Update the ALREADY GATED rows and the parity table as each module lands.*
*2026-11-04: netlist group landed — sanitiser gate GREEN (48 tests, 48/48 + zero
warnings; `netlist` module + `pycompat` repr fix), `parity_netlist` harness green
(PARITY OK — 112 values). Firmware group landed — `firmware.rs` SHA-256 fix (all four
FIPS-180-4 vectors), `parity_firmware` harness green (PARITY OK — 27 values).
Toolchain resolver landed — `toolchain_resolver.rs` ported with 3 unit tests.
Measurements group landed — `measurements.rs` ported (27 tests), `parity_measurements`
harness green (PARITY OK — 27 values).
Full core gate green: 196 tests, `*RUSTFLAGS="-D warnings"*`, zero warnings.
Sections 3, 4, maintenance log flipped; `gpio_model` row now landed.*
*2026-11-05: gpio_model group landed — `gpio_model.rs` ported with unit tests. 196 tests total, `*RUSTFLAGS="-D warnings"*`, zero warnings.*
*2026-11-05: serial_console group landed — `serial_console.rs` ported (18 tests), `parity_serial_console` harness green (PARITY OK — 15 values). qtest_client, selfcheck, report_generator modules landed (zero warnings each). Full core gate green: 204 tests, `*RUSTFLAGS="-D warnings"*`, zero warnings. `cad_engine` subagent port produced non-compiling Rust (26 errors — Python syntax in Rust source); module removed, will be re-delegated properly.*
*2026-11-05: cad_engine landed (re-delegated properly) — `cad_engine.rs` compiles zero-warnings. `kicad_export.rs` ported (617 LOC Python → ~1430 LOC Rust) with 13 tests. `qtest_client.rs` +16 tests, `selfcheck.rs` +5 tests, `report_generator.rs` +19 tests, `cad_engine.rs` +36 tests (Rust-only gate, no Python equivalent). `test_solver_error_handling.py::TestFailureReportClassifier` pure half +9 tests. Full core gate green: 303 tests, 0 failed, `*RUSTFLAGS="-D warnings"*`, zero warnings. All 4 parity harnesses green: firmware 27, measurements 27, gpio_model 17, serial_console 15.*
