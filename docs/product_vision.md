# Product Vision: WOSP (The Co-Simulation EDA Platform)

## 1. Executive Summary

WOSP is an open-source, desktop-native circuit design and co-simulation platform tailored for embedded systems engineers. It bridges the gap between raw analog hardware and microcontroller firmware by combining an LTspice-compatible user experience, an industrial-grade analog solver (ngspice), real-time MCU emulation, and an AI-driven design assistant.

## 2. Core Value Proposition

- Analog Fidelity: Powered by ngspice for true transistor-level physics.
- MCU Co-Simulation: Load .hex or .elf firmware files and co-simulate GPIO interactions alongside analog circuitry.
- Familiar EDA UX: Replicates LTspice schematic capture gestures, hotkeys, and menu layouts.
- AI Design Assistant: Integrates context-aware agents to suggest component values and optimize efficiency.

## 3. High-Level Architecture

### Target architecture (post-Rust conversion)

The implementation language decision for the host-side codebase is **Rust for the
core, C++ (Qt5) for the GUI, C retained for the ESP32 firmware**. Rationale and
constraints that produced it:

- **Rust core** (`crates/wowkispice-core`, dependency-free): all policy and
  math currently in `bridge/` — control law, netlist sanitiser, measurements,
  runners — ported module-for-module with the Python original kept as the
  parity contract. Modules mirror `bridge/` names 1:1 so a reader can always
  find the Python source from the Rust file.
  *Why not C:* measured on the first module, Python→C expansion was 7.5:1
  (~26k Python LOC → ~150–190k C); Rust lands at roughly 40–50% of that, and
  the C port repeatedly hit the exact failure classes Rust removes (NULL-driven
  UB, fixed-buffer truncation warnings, hand-written regex scanners).
  *Why not Rust for the GUI:* Qt5 was chosen over Qt6 for 1:1 fidelity with
  the existing PyQt5 behavior, and the mature Qt5 Rust bindings are weak.
- **C++/Qt5 GUI**: a **from-scratch redesign**, not a port of `ui/`. Design
  brief in §7. The old PyQt5 UI is mined only as a *feature inventory* —
  no capability may silently disappear — but none of its layout or
  interaction design carries over.
- **C firmware** (`firmware/`): unchanged; the core reaches it through the
  scraped-constants path already in `control_law` (`law_from_firmware_source`).
- **C ABI boundary**: the core crate builds `cdylib` so the Qt5 GUI (and
  any future non-Rust host) links it through a stable C interface.

### Legacy architecture (as implemented in Python; being superseded)

- ui/: PyQt5 schematic editor and PyQtGraph waveform viewer.
- circuits/: ngspice wrappers, netlist generators, and solvers.
- bridge/: Co-simulation synchronization loop coupling analog time steps with MCU instructions.
- firmware/: MCU binary parsing and peripheral loading.
- tests/: Pytest unit test suite (9,205 lines; the core of it is being ported
  to Rust and remains the gate — parity harnesses in `crates/parity` diff
  each Rust module against the Python original on input batteries that were
  NOT transcribed from the tests, so a port and its ported test cannot be
  wrong in the same way).

## 3a. Conversion status (Rust rewrite)

| Slice | Status |
|---|---|
| Workspace + shared CPython-semantics helpers (`pycompat`) | **DONE** — compiles clean |
| `control_law` (src + tests + parity) | in flight |
| `netlist` sanitiser (src + tests + parity) | in flight |
| `gpio_model`, `esp32_regs`, `load_stepper`, `firmware`, `toolchain_resolver` | in flight |
| Test-suite → Rust-module mapping (`docs/RUST_PORT_TEST_MAP.md`) | in flight |
| Remaining `bridge/`, `tools/` (re-scoped, not 1:1), Qt5 GUI redesign | planned |

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

## 7. GUI Design Brief (Qt5, from scratch)

Decisions locked with the owner (2026-11-03):

- **Audience**: engineers evaluating circuits — clean guided flows, results
  front and center, without hiding the knobs a real engineer wants.
- **Reference**: LTspice — schematic-capture gestures, hotkeys, menu layout
  familiarity (the vision's "Familiar EDA UX" bullet). Layout reference
  screenshots live in `docs/ltspice-reference/` (third-party copyrighted
  images: private inspiration only, never committed or redistributed).
- **All four views are in scope** (this is a multi-window/splittable
  workspace, not a single-pane app):
  1. **Schematic editor** — draw/edit circuits, LTspice-like gestures.
  2. **Waveform viewer** — simulation plots with cursors/measurement readouts.
  3. **Co-sim dashboard** — firmware + analog loop monitoring: live stats,
     thresholds, switch counts, run reports.
  4. **Code/text workspace** — netlist + firmware source editing with run
     controls.
- **From scratch**: `ui/` (PyQt5) is NOT ported. Its feature set is mined
  once into a capability inventory so nothing disappears silently; layout,
  widget structure, and interaction design are new.
- **Built as C++/Qt5** linking `wowkispice-core` through its C ABI — Qt5
  chosen over Qt6 for fidelity with the reference behavior; the GUI is
  outside the Rust workspace.

## 8. The Product (ideal goal)

*Source: the owner's product writeup (`Music/YES — now we're talking. That's
the.txt`, 2026-11). This section states the target; §9–§11 turn it into a
buildable plan. Where the writeup's stack differs from the locked architecture
(§3), the locked stack wins and the difference is noted.*

**Positioning:** *LTspice meets embedded: simulate circuits AND MCU firmware
together.* The gap this fills — no existing tool does all of it:

| | SPICE accuracy | MCU sim | Both together | Familiar UX | AI assist | Open |
|---|---|---|---|---|---|---|
| LTspice | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Wokwi / Tinkercad | ❌ | ✅ | 🟡 partial | ❌ | ❌ | 🟡 |
| Renode | ❌ | ✅ deep | 🟡 | ❌ | ❌ | ✅ |
| ngspice | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **WOSP** | ✅ (ngspice) | ✅ | ✅ **real SPICE** | ✅ LTspice-like | ✅ | ✅ |

Target users: embedded engineers testing firmware against real analog
circuits; hardware designers who want value suggestions without losing
control; LTspice users who should feel at home immediately.

### The four pillars

1. **LTspice-compatible UX** — same layout skeleton, gestures, hotkeys
   (details in §7; component toolbar left, schematic center, results right,
   console bottom).
2. **Real ngspice analog solver** — transistor-level physics, not
   approximations (ACHIEVED in Python, `docs/industry-readiness.md` evidence).
3. **MCU emulation** — load `.hex`/`.elf`, GPIO pins live against the
   circuit, co-simulation mode `.cosim` alongside `.tran`.
4. **AI design assistant** — **DEFERRED (owner decision, 2026-11-03):
   not in the build plan for now.** Originally: spec input → suggested
   topology + values + predicted efficiency, auto-populated into the
   schematic, human-tweakable, with sensitivity analysis and A-vs-B design
   comparison. The writeup's vision text in §9 is retained for when it is
   picked up; phases below do not include it.

### Stack deltas vs. the writeup (locked decisions supersede)

| Layer | Writeup said | Locked decision | Why |
|---|---|---|---|
| Core logic | Python bridge | **Rust** (`wowkispice-core`) | §3 |
| GUI | PyQt5 | **C++ / Qt5** | §3; still Qt5 = LTspice-familiar widgets, QGraphicsScene approach carries over 1:1 |
| Schematic | QGraphicsScene | **Qt QGraphicsScene (C++)** | unchanged in spirit — KiCad uses the same |
| Waveform | PyQtGraph | **Qt Charts or custom plot widget (C++)** | decide at GUI kickoff |
| Analog solver | ngspice | ngspice | unchanged |
| MCU emu | custom + optional Renode | unchanged (QEMU path already proven, `docs/WINDOWS_QEMU_BUILD.md`) | |
| AI backend | PyTorch + Optuna | out of core scope; an **AI service boundary** (JSON over stdio/HTTP) so the backend stays swappable — no ML framework inside the Rust core | |

## 9. UX blueprint (from the product writeup)

**Layout skeleton (copy LTspice):**

```
Top:     Menu (File, Edit, Simulate, Tools, Window, Help)
Left:    Component toolbar — Passive (R,L,C), Active (D,Q,MOS,opamp),
         Sources (V,I,PWL), MCU (NEW: Arduino/STM32/ESP32/custom .elf)
Center:  Schematic editor (drag-drop, wire)
Right:   Simulation results (waveforms, Bode, FFT) / AI panel (tabbed)
Bottom:  Message console, simulation log
```

**Gestures to replicate exactly:** right-click component → edit value;
drag to place, click to rotate; Ctrl+click multi-select; right-click wire →
label; F2 → run simulation; left-click waveform → measure; wheel zoom,
middle-drag pan; Ctrl+Z/Y undo/redo; split schematic|waveform windows with
net→trace highlighting in both directions; ruler drag for time/voltage
measurement; export .png/.csv/.pdf.

**New — MCU:** toolbar MCU section; right-click MCU → "Load firmware"
(.hex/.elf, shows e.g. "atmega328p @ 16MHz, program size 2048B"); GPIO
inspector panel (per-pin state, logic level *and* physical voltage, live
during sim, breakpoints like "break if pin 5 goes HIGH"); simulation-type
dropdown (Transient only / MCU only / Co-Simulation) with speed tiers
(Accurate / Balanced / Fast).

**New — Co-sim directive:** `.cosim mcu=<model> firmware=<file>
duration=<t>` beside `.tran`; results show GPIO edges AND circuit response
on the same time axis.

**New — AI:** Design Assistant sidebar (target specs: input V, output
V/current, efficiency floor, size; buttons: Suggest Design / Optimize /
Check Stability; suggestion list with predicted efficiency+cost, click to
populate schematic, re-optimize around manual tweaks); side-by-side design
comparison (schematics + waveforms, differences highlighted); right-click
component → sensitivity analysis ("R1 ±10% → efficiency ±2%").

**Three signature scenarios (acceptance narratives):**
1. *Traditional user* builds a buck, sets `.tran`, runs — feels like LTspice.
2. *Embedded engineer* drops an Arduino, loads `blink.hex`, wires pin 5 to
   an LED and A0 to the divider, runs `.cosim`, clicks the GPIO rising edge
   and measures circuit response — the core new value.
3. *AI-assisted* enters 12V→3.3V/500mA/>90%, gets a populated schematic at
   93% predicted, tweaks L1 10µ→6.8µ, sees the trade-off, then co-sims the
   ESP32 firmware against it and exports .cir/.kicad_sch/BOM.

## 10. Phased build plan (rewritten for the Rust architecture)

The writeup's week-based phases are re-cut against current reality: the
Python prototype already PROVED pillars 1–3 in evidence (status table §4);
the rewrite is re-building them in Rust/C++ while the prototype's test
suite keeps gating. Sessions below are working sessions, not calendar weeks.

| Phase | Content | Depends on | Est. |
|---|---|---|---|
| **R1 — Core conversion** | Port `bridge/` + core test suite to Rust, parity-gated (waves in `docs/RUST_PORT_TEST_MAP.md`) | running now (7 modules in flight) | ~15–25 sessions |
| **R2 — FFI + engine** | ngspice C-ABI layer in Rust, co-sim loop port, end-to-end run from CLI | R1 | ~5–10 |
| **G1 — GUI skeleton** | C++/Qt5 shell: layout skeleton, menus, hotkeys, open/save, netlist text workspace (4th view) | C ABI stable (after R1) — design work can start earlier | ~8–12 |
| **G2 — Schematic editor** | QGraphicsScene: components, wiring, values, undo/redo, netlist generation | G1 | ~8–12 |
| **G3 — Waveform viewer** | traces, cursors, measure, net↔trace highlight, export | R2 + G1 | ~6–10 |
| **M — MCU integration** | firmware loader, GPIO inspector, co-sim controls, `.cosim` directive | R2 (binary runner) + G1 | ~6–10 |
| **A — AI assistant** | *DEFERRED — owner decision 2026-11-03: not built for now. Kept in this table struck-through so the plan reads honestly against §8/§9.* ~~spec sidebar, suggestion service boundary, sensitivity, comparison view~~ | — | ~~8–12~~ |
| **P — Polish/packaging** | preferences, templates, exports (KiCad/BOM/PDF), installer, help | late | ~5–8 |

Rationale for starting G1 only at C-ABI stability: building Qt widgets
against an API still moving costs rework; *design* (layouts, mockups,
capability inventory of `ui/`) proceeds in parallel at R1.

## 11. Honest scope notes

- The AI pillar is **NOT ACHIEVED** today (design notes only). It is the
  one pillar with no Python implementation to port — it is new construction
  behind a service boundary, and it is scheduled last so it cannot block
  the converter.
- The vision's "MCU co-sim" today = declared control law with constants
  scraped from firmware source (`bridge/control_law.py`, ported); running
  the actual `.elf` against the solver (binary runner M0/M1) is PLANNED —
  QEMU boots it standalone but is not yet coupled to the solver.
- Messaging per the writeup: *"The circuit simulator for embedded engineers.
  Design with analog fidelity AND test your firmware at the same time."
