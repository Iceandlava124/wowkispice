# Deliverables Verification — Product Vision Document vs. Actual Repo

Verification of the attached vision document ("LTspice + MCU simulation + AI
design assistant") against the working tree as of this pass. Every claim has
file evidence; nothing is marked achieved on the strength of a design doc.

**Headline: Phases 1-3 and most of Phase 2/5 are ACHIEVED. Phase 4 (AI
assistant) and the packaging/DB layers are NOT built — they exist only as
design notes (`overnight/04-ai-assistant-design.md`). Every analysis mode
from the audit is now wired into the editor (noise, `.disto`, per-schematic
Monte Carlo, timing view, step-response metrics), suite green at 309 tests.**

---

## Phase 1 — Core + Basic UI ✅ ACHIEVED

| Deliverable | Status | Evidence |
|---|---|---|
| ngspice wrapper | ✅ | `bridge/ngspice_wrapper.py` (this pass fixed a real bug: `load_circuit` now guarantees a deck title line, which was hanging every hand-typed netlist) |
| Co-sim loop (MCU + analog) | ✅ | `bridge/cosim_runner.py`, `bridge/mock_controller.py`, `bridge/gpio_model.py`; 34 tests in `test_cosim_control.py` |
| Minimal PyQt5 editor | ✅ | `ui/schematic_editor.py` (3.6k lines) |
| Basic waveform viewer | ✅ | pyqtgraph pane + x/y cursors + readout (`cursor_readout`, `measurements.format_readout`) |

## Phase 2 — LTspice-Style UI ✅ ACHIEVED (with two gaps)

| Deliverable | Status | Evidence |
|---|---|---|
| Menu bar (File/Edit/Place/Simulate/View/…) | ✅ | `_build_actions`: File, Edit, Place, Simulate, View, Results, Tools, Help |
| Left component palette (Passive/Active/Sources/MCU) | ✅ | `PALETTE_GROUPS` in `ui/schematic_symbols.py`; `palette_list` |
| Center schematic editor: drag, wire, rotate, grid | ✅ | `SchematicScene`, Ctrl+R rotate (LTspice binding), dot grid |
| Right results panel: waveforms / Bode / FFT | ✅ | tabs: Waveforms, FFT, Bode (+ I-V Curve Tracer, PV/MPPT, AWG, Parametric Sweep, Noise, Distortion, Monte Carlo, Step Response, Timing — added this pass) |
| Bottom console + simulation log | ✅ | `console` + `netlist_view` + Netlist Editor tabs |
| Right-click component → Edit value | ✅ | `edit_selected_value` (ui line 2387) |
| Drag to place, click to rotate | ✅ | scene gestures + `rotate_action` |
| Ctrl+click multi-select | ✅ | additive-select path (ui line 350) |
| Right-click wire → Add label | ✅ | `label_selected_net` (ui line 2649) |
| F2 → start simulation | ✅ | `run_act` shortcut F2 |
| Left-click waveform → measure | ✅ | click points + `refresh_cursors` readout (max/rms/pp/point-at-time) |
| Scroll to zoom | ✅ | view zoom wheel + Ctrl+= / Ctrl+- |
| Undo/redo | ✅ | Ctrl+Z / Ctrl+Y (scene snapshots) |
| Multi-trace waveform + measurements | ✅ | trace list, stats row, `.meas` surfacing in netlist runs |
| Progress + stop mid-run | ✅ | `QProgressBar` + `_on_progress` + Stop (Ctrl+.) |
| Netlist editor | ✅ | editable pane + "Run this netlist" + "Reset to schematic" / "Import as components" |
| Export .cir / .kicad_sch / .net / BOM / CSV / PNG / PDF | ✅ | File ▸ Export…, Results ▸ Export… |
| Click net in schematic → highlight in waveforms | ❌ | no net↔trace linking path exists (trace list ↔ plot only) |
| Netlist auto-sync with schematic | 🟡 | manual: explicit Reset/Import buttons, no live auto-sync |

## Phase 3 — MCU Integration ✅ ACHIEVED

| Deliverable | Status | Evidence |
|---|---|---|
| MCU components in library | ✅ | generic MCU + Arduino Uno/Nano + ESP32 symbols (`ui/schematic_symbols.py` lines 81-164) |
| Firmware loader (.hex / .elf) | ✅ | right-click MCU → "Load Firmware (.hex / .elf)…" → `_load_firmware` → `bridge/firmware.py` |
| GPIO pin watcher / inspector | ✅ | **MCU / GPIO** tab: duty, edge count, measured frequency, pin behaviour strings (`gpio_model.analyze_pin`) |
| Serial console (UART) | ✅ | **Serial** tab + import; **Decode TX wired this pass** (net+baud → `decode_uart_packets`, demo-fallback filtered) |
| Co-sim mode dropdown | ✅ | toolbar: Transient only / MCU only / Co-simulation (+ Ctrl+M / Ctrl+T) |
| Speed options | ✅ | Accurate / Balanced / Fast presets |
| Pin mapping visualization | ✅ | **Pin Map** tab (`pinmap_table`: pin, net, hardware, role, behaviour, wired) |
| Firmware source-code viewer | ❌ | not built (doc marks it optional) |
| Breakpoints ("break if pin 5 HIGH") | ❌ | no breakpoint machinery anywhere in `ui/` or `bridge/` |

## Phase 4 — AI Assistant ❌ NOT ACHIEVED

| Deliverable | Status | Evidence |
|---|---|---|
| Design Assistant sidebar (Suggest/Optimize/Check stability) | ❌ | zero matches for assistant/suggest/optimize in `ui/*.py`; design only in `overnight/04-ai-assistant-design.md` |
| Suggest component values / populate schematic | ❌ | not built |
| Parameter optimizer | ❌ | not built |
| Sensitivity analysis ("R1 ±10% → efficiency ±2%") | ❌ | not built (named only in `overnight/04`) |
| Design comparison view (A vs B side-by-side) | ❌ | not built |
| AI backend: PyTorch + Optuna | ❌ | not in `requirements.txt` (numpy, matplotlib, pypdf, pytest, PyQt5, pyqtgraph only) |
| Database: SQLite/Postgres for training data | ❌ | not present anywhere |

Note: the closest *existing* "check stability" tooling is real, not AI —
the Bode tab (`analysis_runner.run_bode`) and the qualification battery
(`bridge/industrial_verification.py`, Tools ▸ Qualification Battery).

## Phase 5 — Polish 🟡 MOSTLY ACHIEVED

| Deliverable | Status | Evidence |
|---|---|---|
| Keyboard shortcuts (F2, Ctrl+R, …) | ✅ | shortcut table in `_build_actions`; tooltips show the shortcut; F1 help overlay lists them |
| Preferences / settings | 🟡 | persisted via QSettings (window state, theme, icon scale, mode); no unified Preferences dialog |
| Recent files | ✅ | `recent_menu` with rebuild-on-open |
| Templates | ❌ | not built |
| Export PDF / BOM | ✅ | Results ▸ Save Plot as PDF; File ▸ Export BOM (.csv) |
| Export Gerber / .kicad_pcb | ❌ | KiCad *schematic* + *netlist* export exist; PCB-layout formats do not (arguably out of scope for a simulator) |
| Help / tutorials | 🟡 | F1 gestures/shortcuts/measurement help + in-context help text + README; no tutorial series |

## Technology Stack (as decided vs as shipped)

| Layer | Vision | Actual | Status |
|---|---|---|---|
| UI | PyQt5 | PyQt5 | ✅ |
| Schematic | QGraphicsScene | QGraphicsScene (`SchematicScene`) | ✅ |
| Plotting | pyqtgraph | pyqtgraph | ✅ |
| Analog solver | ngspice | ngspice-47 bundled DLL via ctypes | ✅ |
| MCU emulation | custom + optional Renode | custom co-sim loop; QEMU (patched) for real firmware; **Renode abandoned** (documented in README) | 🟡 as planned for MVP |
| AI backend | PyTorch + Optuna | — | ❌ |
| Database | SQLite/Postgres | — | ❌ |
| Packaging | PyInstaller + Inno Setup | `run_editor.bat` / `setup.ps1` (dev bootstrap only); no `.spec`, no installer | ❌ |

---

## This pass's increments (all landed, all tested)

| Item | Status | Tests |
|---|---|---|
| DC curve tracer tab + Simulate menu (Ctrl+Shift+D) → `trace_mosfet_iv` / `trace_diode_iv` | ✅ | `test_schematic_editor.py` (2) |
| UART decode on Serial tab (net + baud + Decode TX) | ✅ | same file (2) |
| PV / MPPT tab (I-V + P-V, MPP marker) + `Ctrl+Shift+V` | ✅ | same file (1) |
| AWG tab (7 waveforms) + `Ctrl+Shift+A` | ✅ | same file (1) |
| Parametric sweep tab (re-run loop, overlay plot, document restored) + `Ctrl+Shift+S` | ✅ | same file (1) |
| Noise tab + `.noise` compiler card + `analysis_runner.run_noise` + `Ctrl+Shift+N` | ✅ | `test_measurements.TestNoiseAndYield` (2) + `test_schematic_editor` (1) |
| Distortion tab + `.ac`/`.disto`/`distof1` compiler cards + `analysis_runner.run_disto` + `Ctrl+Shift+T` | ✅ | `test_measurements.TestDistortion` (1) + `test_schematic_editor` (1) |
| Per-schematic Monte Carlo / yield tab + `analysis_runner.run_monte_carlo` + `Ctrl+Shift+M` | ✅ | covered by the noise/yield tests above (MC restores the document) |
| Step-response metrics tab + `measurements.step_metrics` + `Ctrl+Shift+E` | ✅ | `test_measurements.TestStepMetrics` (3) + `test_schematic_editor` (1) |
| Digital timing diagram tab + `Ctrl+Shift+G` (thresholded lanes, edges/duty/freq) | ✅ | `test_schematic_editor` (1) |
| Wrapper title-line fix (root cause of the hanging `.meas` suite) | ✅ | fixes `test_ui_polish` (76/76) |
| `docs/analysis-mode-audit.md` + README deferral checklist | ✅ | — |
| **Full suite** | ✅ | **309 tests, 17 suites, all green** |

## Still open (remaining vision scope)

- `.op` button (small compiler + UI); a `.dc` sweep of the user's own schematic
- All of Phase 4 (AI assistant) — biggest chunk of remaining vision scope
- Net ↔ waveform highlight (click a net, see its trace), templates, unified
  Preferences dialog, Gerber/.kicad_pcb export, PyInstaller/Inno packaging
