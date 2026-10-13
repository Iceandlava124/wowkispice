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
| A15 | ngspice DLL load gate for any fresh machine | `tools/selfcheck.py` + `run_selfcheck.bat` | `python tools/selfcheck.py` → `SELF-CHECK: PASS`, exit 0 |
| A16 | Full test suite (17 suites, 309 tests) | `tools/run_tests.py` | `python tools/run_tests.py` → 309 passed, exit 0 |
| A17 | Firmware boots in patched Espressif QEMU through ROM, bootloader, `app_main()` | `bridge/qemu_orchestrator.py`, `tools/qemu-patch/` | Manual boot runs: 900 000 samples / 90 s, zero panics |
| A18 | GET/ADC injection gate measurement under patched QEMU | `bridge/esp32_regs.py`, `bridge/qemu_orchestrator.py` | Manual `qom-set /machine/peripheral/sens adc1-value N` → gate ON → OFF at 3456 |

## Band B — Works today but only manual, not automated

| # | Capability | Files | How it currently works | Why it is manual | What would automate it |
|---|---|---|---|---|---|
| B1 | Inject analog values into the emulated firmware's ADC | `tools/qemu-patch/`, `bridge/qemu_orchestrator.py` | Human opens the QEMU monitor and runs `qom-set /machine/peripheral/sens adc1-value N` | No host-side automation exists; the patch exposes a QOM property but nobody reads/writes it from Python | New `bridge/qemu_monitor.py` (QMP/HMP): scripted injection + gate readback (this is M0 of `docs/binary-runner-and-mcu-bringup.md`) |
| B2 | Read the latched gate level out of QEMU into ngspice | `bridge/esp32_regs.py` | Physical read `xp /1wx 0x3FF44004` via HMP console | No QEMU harness reads it back | Add a read-only QOM property (preferred path in M0) |
| B3 | Run the real firmware as the closed-loop controller | `bridge/binary_runner.py` (planned), `bridge/cosim_runner.py` | Declared-law runs only; firmware runs isolated | Binary runner not implemented | M1: wall-clock sampled-data HIL contract, `external` sources from the firmware's own decisions |
| B4 | Add a new MCU and test it beside the others | `bridge/gpio_model.py`, `bridge/control_law.py`, `tools/qemu-patch/` | One-off manual port | No checklist + no per-MCU test row | M2 bring-up checklist + profile table (binary-runner doc §6) |

## Band C — Planned / not started (no code path to execution)

| # | Capability | Files | Contract / source |
|---|---|---|---|
| C1 | Binary runner closed loop (M1) — firmware drives the solver | `bridge/binary_runner.py` (planned), `docs/binary-runner-and-mcu-bringup.md` | `run_binary_cosim(model, pin_specs, *, firmware_image, qemu, machine="esp32", tstep_us=0.5, duration_ms=5.0, progress_callback=None, stop_flag=None)` |
| C2 | GUI integration of B1/B2/B3 (auto-bridge, real HIL) | `ui/schematic_editor.py` handlers (`run_simulation`, `run_closed_loop`, …) | M2 wiring in binary-runner doc; currently only declared-law F2 exists |
| C3 | New-MCU bring-up harness (one checklist row + one test row) | `bridge/gpio_model.py`, `bridge/control_law.py`, `tools/qemu-patch/`, `docs/binary-runner-and-mcu-bringup.md` §6 | Register map → regs module → QEMU device patch → firmware project → pin/law wiring → tests |
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
- **Band B** works, but every use of it touches a human inside the loop (a QEMU monitor
  command) or a human-written controller. Those are the highest-value automation
  targets; M0 (B1/B2) is the minimum step to make the firmware "responsive to the
  circuit" end to end.
- **Band C** is just names: nothing exists to execute. Anything in Band C is at
  `UNVERIFIED` in `docs/systems-map.md`, never `CONFIRMED WORKING`.

## Related evidence sheets

- `docs/systems-map.md` — CONFIRMED WORKING / CONFIRMED BROKEN / UNVERIFIED / LATENT RISK per artifact
- `docs/analysis-mode-audit.md` — engine-exists vs editor-wired status
- `docs/deliverables-verification.md` — vision-doc claims vs tree
- `docs/industry-readiness.md` — verdict + phased plan with acceptance criteria
- `docs/binary-runner-and-mcu-bringup.md` — M0/M1 + per-MCU bring-up contract
