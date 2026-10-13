# Product Vision: WOSP (The Co-Simulation EDA Platform)

## 1. Executive Summary

WOSP is an open-source, desktop-native circuit design and co-simulation platform tailored for embedded systems engineers. It bridges the gap between raw analog hardware and microcontroller firmware by combining an LTspice-compatible user experience, an industrial-grade analog solver (ngspice), real-time MCU emulation, and an AI-driven design assistant.

## 2. Core Value Proposition

- Analog Fidelity: Powered by ngspice for true transistor-level physics.
- MCU Co-Simulation: Load .hex or .elf firmware files and co-simulate GPIO interactions alongside analog circuitry.
- Familiar EDA UX: Replicates LTspice schematic capture gestures, hotkeys, and menu layouts.
- AI Design Assistant: Integrates context-aware agents to suggest component values and optimize efficiency.

## 3. High-Level Architecture

- ui/: PyQt5 schematic editor and PyQtGraph waveform viewer.
- circuits/: ngspice wrappers, netlist generators, and solvers.
- bridge/: Co-simulation synchronization loop coupling analog time steps with MCU instructions.
- firmware/: MCU binary parsing and peripheral loading.
- tests/: Pytest unit test suite.

## 4. Status Tracker (2026-10-09)

| Vision slice | Status | Evidence |
|---|---|---|
| Real SPICE solver on `libngspice` | **ACHIEVED** | `tools/prove_physics_engine.py` + `tests/test_ngspice_dll_proof.py` (RC step, RLC ringing). |
| Per-timestep closed loop (declared law) | **ACHIEVED** | `bridge/cosim_runner.py` + `bridge/control_law.py`; 34 tests in `test_cosim_control.py`. Fidelity caveat: controller is a Python model with constants scraped from C source. |
| Firmware as the closed-loop controller (binary runner) | **PLANNED** | `docs/binary-runner-and-mcu-bringup.md` M0/M1. Patched QEMU boots the `.elf` and runs a full loop (900 000 samples / 90 s, zero panics) but is not yet coupled to the solver. |
| LTspice-familiar schematic editor | **ACHIEVED** | `ui/schematic_editor.py`; `test_ui_polish.py` 76. |
| AI design assistant | **NOT ACHIEVED** | Design notes only (`overnight/04-ai-assistant-design.md`). |
| Export and integration (.cir/.kicad_sch/.net/BOM/PDF) | **ACHIEVED** | `bridge/kicad_export.py` verified against `kicad-cli`. |

## 5. Industry Readiness

**Verdict (2026-10-09): YES as a pilot/prototyping/teaching tool; NO as a production engineering tool.**

Living documentation: [docs/industry-readiness.md](docs/industry-readiness.md) — the verdict, the
evidence-backed blockers, and the phased plan with acceptance criteria per phase:

| Phase | Goal |
|---|---|
| **0 — Honest & installable** | Kill the silent substitutions (BOM, legacy fallback); packaging + versioning for a fresh clone |
| **1 — Engineering credibility** | Validation corpus, CI, fidelity boundary |
| **2 — Product hardening** | Binary runner M0/M1, save-format migration, quality-report artifacts, installer |
| **3 — Regulated workflows** | Optional; external certification scope |

## 6. Automated guards in the tree

- `tools/selfcheck.py` / `run_selfcheck.bat` — environment gate (interpreter, dependencies, ngspice load, known circuit, suites): 17 suites, 309 tests, exit 0
- `docs/analysis-mode-audit.md`, `docs/deliverables-verification.md`, `docs/legacy-module-audit.md` — per-capability evidence sheets
- `docs/systems-map.md` — every artifact flag CONFIRMED WORKING / CONFIRMED BROKEN / UNVERIFIED / LATENT RISK
