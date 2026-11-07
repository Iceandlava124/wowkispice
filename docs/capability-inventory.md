# Capability Inventory — What Works Today, What Is Manual, What Is Planned

A single, current view of every capability in the repo, sorted into three bands.
Each entry names the file, the evidence (tests / measurements / manual run), and the
band it sits in. This page exists so that "can we do X?" is answered by reading one
place instead of asking the repo.

## Band A — Works today (verified, test-harness-backed)

| # | Capability | Files | Evidence (test / measurement) |
|---|---|---|---|
| A1 | Real ngspice DLL C-API bridge + solve | `bridge/ngspice_wrapper.py` | `tests/test_ngspice_dll_proof.py` (3 physics proofs vs closed-form ODEs); tool: `tools/prove_physics_engine.py` |
| A2 | Editor: place/wire/label/rotate/undo/save/zoom/cursors/themes, PDF export | `ui/schematic_editor.py`, `ui/schematic_scene.py`, `ui/schematic_items.py` | `test_editor_workflow.py` (36), `test_ui_polish.py` (76), `test_ui_parity.py` (12) |
| A3 | 15 results tabs + 3 dock tabs (MCU/GPIO, Pin Map, Serial, Waveforms, FFT, Bode, Timing, Step Response, Noise, Distortion, Monte Carlo, Parametric Sweep, I-V Curve Tracer, PV/MPPT, AWG, Console, Netlist, Netlist Editor) | `ui/schematic_editor.py` | `test_schematic_editor.py` (40) — each tab has a handler + an end-to-data test |
| A4 | SPICE netlist export (.cir), KiCad schematic (.kicad_sch), KiCad netlist (.net), BOM CSV | `bridge/cad_engine.py`, `bridge/kicad_export.py` | `test_kicad_export.py` (kicad-cli resolves nets), `test_schematic_editor.py` |
| A5 | BOM report as CSV | `bridge/cad_engine.py`, `bridge/report_generator.py` | `test_sota_suite.py` (7) |
| A6 | HTML/MD/PDF test & report generation | `bridge/report_generator.py` | `test_sota_suite.py` |
| A7 | Closed-loop co-simulation: declared control law vs the actual solver | `bridge/cosim_runner.py`, `bridge/control_law.py` | `test_cosim_control.py` (34) — `GetVSRCData` reads the sense net each timestep; tested loads 5 Ω / 1.5 Ω / 0.5 Ω |
| A8 | Closed-loop with real feedback divider in the netlist (not a Python fudge) | `bridge/cad_engine.py`, `bridge/control_law.py` | `TestDividerSemantics`, `TestThresholdsMatchFirmware` in `test_cosim_control.py` |
| A9 | Component library (passive + sources + generic MCU + Arduino Uno/Nano/Mega, STM32F103, ESP32, ESP32-S3) | `ui/schematic_symbols.py`, `circuits/components/` | `test_components_library.py` (2); KiCad pin-count parity test |
| A10 | Firmware metadata: .hex/.elf format, size, load address, entry, sections, SHA-256 | `bridge/firmware.py` | `test_firmware_gpio.py` |
| A11 | GPIO pin profile system + pin map tab | `bridge/gpio_model.py`, `ui/schematic_editor.py` | `test_firmware_gpio.py`; "MCU/GPIO" tab 400+ lines |
| A12 | Industrial qualification battery (DO-254/ISO 26262/IEC 61508 style) | `bridge/industrial_verification.py` | `test_industrial_verification.py` (5), `test_sota_suite.py` (7) |
| A13 | UART decode from captured trace (8N1 stimuli verified: `0x4F 0x4B 0x0A`) | `bridge/studio_engine.py`, `bridge/serial_console.py`, `ui/schematic_editor.py` | `test_studio_suite.py` (9) + `test_schematic_editor.py` |
| A14 | Waveform analysis: cursors, FFT, Bode + phase/gain margin, waveform stats, noise, distortion, Monte Carlo, step metrics, timing diagram, AWG, I-V Curve Tracer, PV/MPPT | `bridge/measurements.py`, `bridge/analysis_runner.py`, `bridge/studio_engine.py` | `test_measurements.py` (36), `test_ui_parity.py` (12) |
| A15 | ngspice DLL load gate for any fresh machine | `tools/selfcheck.py` + `run_selfcheck.bat` | Measured 2026-11-07: `run_selfcheck.bat` → `SELF-CHECK: PASS`, exit 0; it resolves the project venv interpreter itself |
| A16 | Full test suite | `tools/run_tests.py` | Measured 2026-11-07: 547 passed, 4 skipped, 0 failed in 229.43 s, exit 0 |
| A17 | *(legacy, deprecated)* Firmware boot in patched Espressif QEMU through ROM, bootloader, `app_main()` | `bridge/qemu_orchestrator.py`, `tools/qemu-patch/` | Historical manual runs recorded; **not part of the shipped co-simulation path** |
| A18 | *(legacy, deprecated)* ADC injection gate measurement under patched QEMU | `bridge/esp32_regs.py`, `bridge/qemu_orchestrator.py` | Historical manual `qom-set` runs; **superseded by the Rust `cosim_runner` path** |

## Band B — Works today but only manual, not automated

| # | Capability | Files | How it currently works | Why it is manual | What would automate it |
|---|---|---|---|---|---|
| B1 | *(legacy, deprecated)* Inject analog values into the emulated firmware's ADC | `tools/qemu-patch/`, `bridge/qemu_orchestrator.py` | Historical manual `qom-set` through the QEMU monitor | QEMU is no longer the shipped path; the Rust loop reads the sense net directly | Not applicable unless QEMU work is revived |
| B2 | *(legacy, deprecated)* Read the latched gate level out of QEMU into ngspice | `bridge/esp32_regs.py` | Historical manual `xp /1wx 0x3FF44004` | Superseded by `cosim_runner.rs` callbacks | Not applicable |
| B3 | *(legacy, deprecated)* Run the real firmware as the closed-loop controller | `bridge/binary_runner.py`, `bridge/cosim_runner.py` | Historical QEMU coupling; shipped loop uses a Rust controller model instead | No shipped code loads `firmware_control.dll` | Wire the DLL if firmware-in-the-loop is required |
| B4 | Add a new MCU and test it beside the others | `bridge/gpio_model.py`, `bridge/control_law.py` | One-off manual port | No checklist + no per-MCU test row | Bring-up checklist + profile table |

## Band C — Planned / not started (no code path to execution)

| # | Capability | Files | Contract / source |
|---|---|---|---|
| C1 | *(legacy, deprecated)* QEMU binary runner closed loop — firmware drives the solver | `bridge/binary_runner.py` | Historical implementation; not on the shipped path and not loaded by Rust/GUI code |
| C2 | GUI integration of B1/B2/B3 (auto-bridge, real HIL) | `ui/schematic_editor.py` handlers (`run_simulation`, `run_closed_loop`, …) | M2 wiring in binary-runner doc; currently only declared-law F2 exists |
| C3 | *(legacy, deprecated)* New-MCU QEMU bring-up harness | `bridge/gpio_model.py`, `bridge/control_law.py`, `tools/qemu-patch/`, `docs/binary-runner-and-mcu-bringup.md` §6 | Historical contract; not on the shipped path |
| C4 | Auto-sync netlist with schematic (live, not Reset/Import buttons) | `ui/schematic_editor.py` (Netlist dock) | Named open; current sync is manual Reset/Import |
| C5 | Net↔trace highlight (click a net, see its trace) | `ui/schematic_editor.py`, `bridge/measurements.py` | Named open |
| C6 | Editable design templates / unified Preferences | `ui/schematic_editor.py` | Named open |
| C7 | Gerber/.kicad_pcb export | `bridge/kicad_export.py` | Named open |
| C8 | Packaging: `pyproject.toml`, version, lockfile, release tags | repo root | Named open (industry-readiness.md Phase 0) |
| C9 | CI verification on a fresh clone (workflow executed, not merely YAML-parsed) | `.github/workflows/cosim-ci.yml` | Named open (industry-readiness.md Phase 0) |
| C10 | Crash reporting, i18n/a11y baseline, installer | `ui/schematic_editor.py`, `ui/theme.py` | Named open (industry-readiness.md Phase 0‑2) |
| C11 | Regulated-workflow traceability (DO-330, TCL, SBOM, disclaimers) | `bridge/industrial_verification.py`, `bridge/report_generator.py` | Named open (industry-readiness.md Phase 3) |

## How to read the bands

- **Band A** is what a user can point, click, simulate, and export today, and what a
  test proves about it. Nothing here needs a human or a terminal.
- **Band B** entries are legacy QEMU work that required a human in the loop. They are
  retained for history and are not on the shipped Rust/ngspice path.
- **Band C** is just names: nothing exists to execute. Anything in Band C is at
  `UNVERIFIED` in `docs/systems-map.md`, never `CONFIRMED WORKING`.

## Related evidence sheets

- `docs/systems-map.md` — CONFIRMED WORKING / CONFIRMED BROKEN / UNVERIFIED / LATENT RISK per artifact
- `docs/analysis-mode-audit.md` — engine-exists vs editor-wired status
- `docs/deliverables-verification.md` — vision-doc claims vs tree
- `docs/industry-readiness.md` — verdict + phased plan with acceptance criteria
- `docs/binary-runner-and-mcu-bringup.md` — M0/M1 + per-MCU bring-up contract
