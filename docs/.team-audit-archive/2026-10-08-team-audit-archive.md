# Executive findings — `PROJECT_WOWKISPICE` codebase audit

**Date:** 2026-10-08
**Audience span:** product, platform, simulation, embedded, automotive, aviation,
education, regional design-hubs.
**EEC membership ≥ 15 orgs** → find ~15 interested parties (MNCs or large orgs) whose
missions overlap the repo's two core offers: *real per-timestep ngspice analog co-simulation
of a user schematic*, and *parsed (not executed) ESP32/Xtensa MCU firmware + QEMU boot proof*.

---

## 1. MNC / org candidate pool (interest per org, not per file yet)

Map each org to the repo capability it would actually buy or fund. Don't over-claim —
every org is interested in *one* slice, not the whole app.

| # | Organization (role / tier) | Why it suits this codebase (one line) | Repo slice it wants first |
|---|---|---|---|
| 1 | Industry-standard EDA incumbent (Synopsys / Cadence / Mentor-Siemens tier) | Already ships a real SPICE solver; would care whether a Python-in-the-loop closed-loop add-in is architecturally clean enough to adopt rather than re-implement. | Closed-loop `cosim_runner`, ngspice C-API offload design, `.cosim` semantics, graph→netlist determinism, test harness rigour. |
| 2 | Analog IC design house (Texas Instruments analog division tier) | Needs believable combined analog+controller simulation of a *real drawn schematic*, not a fixed parametric tutorial. | `cad_engine` compiler quality, ngspice accuracy, `.noise`/`.disto`/`.ac`/`.tran` coverage, component library realism, noise verified vs √(4kTR). |
| 3 | Automotive Tier-1 supplier (Bosch / Continental tier) | Designs mixed-signal control loops; wants co-sim to replace / augment bench + code-only HIL for a control law before it is flashed. | Co-sim mode semantics (Transient-only vs MCU-only vs Co-sim), control-law import from C, divider-in-netlist honesty, speed presets, Stop/interrupt. |
| 4 | Automotive OEM systems integration (BMW / Tesla-tier powertrain electronics) | OEM would want MCU + analog co-sim inside a larger system-integrator flow, plus qualification/corner reporting traceable to standards. | `industrial_verification`, temperature-corner sweeps, qualification battery HTML/PDF report, traceability of measured constants to source. |
| 5 | Aircraft OEM avionics (Boeing / Airbus-tier embedded systems) | Avionics wants DO-178C / DO-254-flavoured evidence of what was simulated vs executed, and which firmware behaviour is real vs parsed. | Honest firmware-execution status matrix, QEMU boot proof, "parsed not executed" disclosure discipline, report export (PDF), test coverage that disambiguates modes. |
| 6 | Marine / process control OEM (Wärtsilä / ABB Control tier) | Long-duration transient + reliability analysis (Monte Carlo, noise, distortion) matters more than any single UI gesture. | Per-schematic Monte Carlo / yield, noise density, distortion HD2/HD3, step metrics, sweep overlay, document-restore guarantees. |
| 7 | Energy-infrastructure OEM (Siemens Energy tier) | Converts/generators have regulation loops, thermal behavior, and qualification that this "industrial verification" battery touches. | Closed-loop regulation traces, load/line sweeps, industrial verification battery, thermal/qualification reporting. |
| 8 | Power-converter & motor-drive integrator (ABB Drives / Danfoss tier) | Motor drives are PWM + current control + current sensing; the MCU+analog closed loop and PWM source capability matter. | MCU GPIO model, PWM/external sources, co-sim with control law, MCU board symbols, firmware parsing. |
| 9 | Regional design-hub / foundry PDK user (TSMC / GlobalFoundries PDK-adjacent design house) | Wants a solver-backed schematic flow that can export to KiCad and produce real netlists, because the local flow is fragmented across EDA tools. | `kicad_export` fidelity, netlist determinism, BOM, component/glyph pinning correctness, pin-count parity between editor and KiCad. |
| 10 | Test & measurement IC vendor (Analog Devices / ADI tier) | Models of real ICs (op-amp, MOSFET, diode, motor) come from `circuits/components/models.lib`; a T&M vendor would care how faithful those reverse-engineered models are. | Component library realism, model fidelity, CC/CS/linear region coverage, `.dc` sweep behaviour on demo devices. |
| 11 | MCU silicon vendor (Infineon / Espressif tier) | The MCU + firmware story is the differentiator; the vendor would want a flow that can co-sim a *real* Xtensa ESP32 image (boot, bootloader, app_main) and react to analog values. | QEMU boot proof (900k samples/90s), qom-set analog injection, patched SAR ADC + GPIO device model, `tools/qemu-patch` reproducibility. |
| 12 | MCU / MCU IP licensee (STMicro / NXP tier) | MCU board symbols (Uno/Nano/Mega/STM32F103/ESP32/ESP32-S3) and pin-mapped hardware directions are the "hardware truth" layer. | MCU board symbol correctness, pin→hardware inference labelled as such, Pin Map tab, KiCad symbol parity, `.kicad_sch` export of boards. |
| 13 | Automotive Tier-2 firmware vendor (Microchip / NXP firmware-tools tier) | Firmware parsing from `.hex`/`.elf`, control-constant import from `.c`, and GPIO profile authoring are the firmware-facing surface. | `firmware.py` parsing, `control_law.py` import, GPIO profile JSON, pin behaviour strings, "load firmware" UX. |
| 14 | Systems-integrator / lab-automation vendor (Keysight / Rohde tier) | Would want a replayable, exportable, headless, CI-able simulation engine that can export CSV/PNG/PDF and run offscreen in CI. | Headless offscreen execution, progress/stop, export paths, `run_tests.py`CI-ability, docker-compose (even if currently stale), reproducibility. |
| 15 | Open-source-signal-chain / regional-tech nonprofit (RISC-V/ESP32 MOOC hub tier) | Education uses schematic-editor familiarity (LTspice-shaped gestures, bare-letter placement, undo/redo), MCU board familiarity, and real-solver honesty. | Editor UX fidelity, gesture correctness (no silent rotate-vs-place collisions), undo/redo, tutorial/help readiness, licensing (Apache-2.0). |

---

## 2. How 15 orgs would *prefer to implement* this codebase

"Prefer to implement" here means: given this codebase as a starting point, what layer
does each org want to own / extend, and what implementation posture would it insist on?
This is forward posture, not a judgment of current correctness of every line.

### 2.1 Industry-standard EDA incumbent
- Prefer a **solver SDK spine**, not a monolithic PyQt app: keep `bridge/ngspice_wrapper.py`
  as the ctypes boundary, but want the closed-loop ".cosim" callback interface documented as
  a public contract and versioned, with the Python callback avoiding per-timestep full-vector
  copies (`bridge/cosim_runner.py:163` already flags `get_vector_array()` copy cost).
- Want the graph→netlist compiler (`cad_engine.py`) to be a reusable, testable library callable
  from any UI, not private to `schematic_editor.py`. They'd prefer the component graph, pin
  resolution (union-find over wires), ground detection, and netlist emission to be isolated and
  covered by solver-backed tests.
- Accept Python as the "glue" but would push the per-timestep gate decision out of Python if it
  matters at speed — likely a compiled extension or a native callback, not another interpreter hop.
- Would insist on a **formal netlist identity** test: the same graph must emit byte-identical or
  canonical netlists across runs, because EDA back-ends compare netlists, not screenshots.

### 2.2 Analog IC design house
- Prefer **physics-verifiable components**: they want the component library and the solver to be
  judged by numbers, not by plots. Concretely: R noise = √(4kTR), diode I-V knee, MOSFET Vth,
  op-amp rail behaviour, motor model losses.
- Want the analysis coverage to be first-class and wired: `.tran`, `.ac`/Bode, `.dc`, `.noise`,
  `.disto`, FFT, step metrics — each with a real-solver test, not a stub. The noise-vs-thermal
  test and distortion HD2/HD3 test are exactly the kind of evidence they'd look for.
- Would push on `.dc` of the *user's own schematic*: they want to sweep a drawn netlist, not a
  fixed demo device, so the I-V tracer scope gap is real to them.
- Prefer the editor UI to be a consumer of an analysis library, so new analyses (Monte Carlo,
  step, timing, noise, distortion) are wired through a consistent runner pattern (`analysis_runner`)
  rather than one-off engine call sites.

### 2.3 Automotive Tier-1 supplier
- Prefer **control-law-first co-sim**: the thing they care about is importing the real decision
  logic from firmware source and closing the loop against a real solve. They'd want
  `control_law.py` + `cosim_runner.py` to be the spine, with the MCU pin model as a consumer.
- Want explicit mode semantics and a guarantee that "Co-simulation" is distinguishable from
  "MCU only" and "Transient only" in the *netlist and the behaviour*, not just a dropdown label.
- Want test evidence that retuning the thresholds moves the operating point (already present:
  1024→0.825 V, 3072→2.481 V) and that load sweeps show duty responding — they read that as
  "the pin reacts to the circuit".
- Would push for a **repeatable, parameter-sweepable, exportable** loop: line/load regulation,
  corner sweeps, CSV/PDF export — already partially present.

### 2.4 Automotive OEM systems integration
- Prefer a **qualification/traceability layer** that ties simulation evidence to standards-flavoured
  categories (corner, fault injection, capability CpK-style). The `industrial_verification_engine`
  is exactly the layer they'd want to own or extend, with reports traceable to which netlist and
  which mode produced them.
- Want the PCB-export story clarified: KiCad *schematic + netlist* exist, but Gerber/.kicad_pcb do
  not. An OEM integrating this into a board-design flow would treat Gerber as a gap until it is filled
  or explicitly deferred.
- Would be sensitive to the firmware behavior honesty: "parsed, not executed" in the loop must stay
  clearly disclosed, because an OEM can't certify behaviour it thinks is real when it is a parsed
  model.

### 2.5 Aircraft OEM avionics
- Prefer **certification-evidence discipline** over solver novelty. They care about: which firmware
  behaviour is real (QEMU boot + real control loop + analog injection), which is parsed/model, and
  which netlist produced which result. The "firmware execution status" matrix is the artifact they'd
  want to keep rigorous and machine-verifiable where possible.
- Want deterministic, reproducible, headless runs with a clean settings isolation model (`WOSP_SETTINGS_DIR`
  per suite) so an avionics audit can re-run a scenario and get the same evidence.
- Would ask for a **netlist identity + mode identity** test: the saved scenario must reconstruct the
  exact netlist and exact mode, because avionics traceability is scenario-level.
- Would push on report generation: PDF reports with per-net statistics are good; they'd want the
  report to also name the mode, the source/image, and the analysis type, not just the numbers.

### 2.6 Marine / process control OEM
- Prefer **reliability + distribution analysis**: Monte Carlo per schematic, noise density, distortion,
  step metrics, worst-case corner sweeps. They'd want these as first-class, well-tested analyses with
  histogram/report output.
- Want long-duration, robust transient control: the accuracy presets (Accurate/Balanced/Fast) and
  Stop/interrupt are the operational surface they'd care about. They'd test that a stopped run leaves
  the document coherent and doesn't leak solver state.
- Would push for **document-restore guarantees**: a Monte Carlo or sweep must leave the schematic
  exactly as it was. That guarantee is already asserted in tests — they'd want it as an explicit
  contract and tested under failure paths too.
- Care about the step-response viewer being real, not a UI wrapper around a stub: `measurements.step_metrics`
  with delay/rise/overshoot/settling/slew, ±2% band, and 50% crossing is the kind of evidence they'd want.

### 2.7 Energy-infrastructure OEM
- Prefer a **closed-loop regulation evidence package**: buck/boost regulation traces, load/line sweeps,
  efficiency, thermal/qualification reporting. The existing buck co-sim and parameter sweeps are the
  core they'd extend.
- Want the industrial-verification battery to be extensible to their own qualification scenarios, with
  reports tied to netlist + mode + parameters.
- Would push on the firmware→analog automatic bridge gap: the QEMU proof is real, but the automatic
  coupling is missing. An energy OEM would fund that bridge as the difference between "proof-of-concept"
  and "usable flow".

### 2.8 Power-converter & motor-drive integrator
- Prefer **motor + PWM + current-control modelling**: motor model in `circuits/components/models.lib`,
  PWM/external source capability, MCU GPIO model with PWM/square profiles, and co-sim with a control law.
- Want the MCU board symbols to carry real hardware directions (Arduino header naming, STM32 PB0–PB15)
  and the Pin Map tab to be a trustworthy hardware-truth layer.
- Would push on the firmware-execution story for Xtensa/ESP32: the boot proof and the analog-injection
  proof are the assets; the missing automatic bridge is the gap they'd fund.

### 2.9 Regional design-hub / foundry PDK user
- Prefer a **netlist-aware, KiCad-exporting, BOM-producing schematic flow** that can drop into a fragmented
  local EDA environment. The `kicad_export` tests (KiCad CLI resolves intended nets) are the kind of
  evidence they'd want to trust the export.
- Want component/glyph pinning correctness and pin-count parity between the editor and KiCad — a mismatch
  silently produces wrong schematics.
- Would push for deterministic netlist emission and a canonical-form test, because PDK users compare
  netlists across tools.
- Care about the "hand-written netlist has no pin coordinates, so Import as components is not offered"
  design decision: it's the right honesty call, but they'd want the reverse import to be explicit and
  bounded.

### 2.10 Test & measurement IC vendor
- Prefer **verifiable device models**: op-amp, MOSFET, diode, motor, and any other IC in
  `circuits/components/models.lib` should be judged by swept I-V and AC behaviour, not just by existing.
- Want the `.dc` sweep path to be real and wired for demo devices (it is: MOSFET Vth = 3.0 V, Schottky knee),
  and want the user-schematic `.dc` gap acknowledged as a real gap, not a stub.
- Would push on the `.noise`/`.disto`/`.ac` coverage being real-solver-wired and tested — already largely done,
  with the new Noise and Distortion tabs and their tests.

### 2.11 MCU silicon vendor (Espressif tier)
- Prefer the **Xtensa/ESP32 execution story** to be the crown jewel, because that is the repo's real
  differentiation against an EDA incumbent. The patched QEMU boot proof (900k samples / 90 s, zero panics),
  the SAR ADC + GPIO device-model patch, and the analog-injection proof are the assets.
- Want the `tools/qemu-patch` patch to be reproducible end-to-end from a fresh source export + patch — already
  claimed and re-verified, but they'd want the claim backed by a reproducer script and pinned source version.
- Would push hard on the **missing automatic ngspice↔QEMU bridge**: the manual `qom-set` proof is real, but the
  gap is the difference between "works in a script" and "is a supported flow".
- Would be cautious about the "parsed, not executed" disclosure inside the simulation loop — they'd want it clear
  that the in-loop controller is a *model of the firmware's logic*, not the firmware executing.

### 2.12 MCU / MCU IP licensee (STMicro / NXP tier)
- Prefer the **MCU hardware-truth layer**: board symbols, pin→hardware inference (labelled as inference, not fact),
  Pin Map tab, KiCad board symbols, and the firmware-parsing surface.
- Want the MCU board symbol correctness and pin-count parity tested (already asserted) and kept green as boards
  are added.
- Would push for real hardware-directional accuracy on the "hardware" column of the Pin Map, because it is labelled
  as inferred from pin name — they'd want the inference rules explicit and reviewable, not implicit.

### 2.13 Automotive Tier-2 firmware vendor
- Prefer the **firmware-facing surface**: `.hex`/`.elf` parsing, control-constant import from `.c`, GPIO profile
  JSON authoring, pin behaviour strings, and the "load firmware" UX.
- Want the parser to be honest about what it can and cannot extract (format, size, load address, entry point,
  sections, SHA-256) and to reject garbage cleanly.
- Would push for the control-law import from C to be robust and versioned, because that is the bridge between a
  firmware team's source and the simulation.
- Care about the "behaviour comes from separately importing the .c source or hand-writing a law" contract being
  explicit in the UX, so a firmware team doesn't expect a loaded `.elf` to drive GPIO automatically in the loop.

### 2.14 Systems-integrator / lab-automation vendor
- Prefer a **headless, CI-able, reproducible, exportable** engine: offscreen Qt, `run_tests.py`, per-suite isolated
  settings, deterministic netlist, CSV/PNG/PDF export, progress/stop.
- Want the docker-compose + CI story to be either fixed or explicitly marked stale, because a systems integrator
  integrating this into a larger automation flow needs to know whether the container story is real.
- Would push on the CI workflow having actually executed at least once — the README says `.github/workflows/cosim-ci.yml`
  "has never executed in CI history". That is a concrete honesty/progress gap for an integrator.
- Care about the known-broken Dockerfile/docker-compose (predates `find_library` fallback, copies neither `ui/` nor
  `tools/`) being either fixed or clearly marked broken, not silently half-working.

### 2.15 Open-source-signal-chain / regional-tech nonprofit
- Prefer an **education-friendly, honest, licenced** tool: LTspice-shaped gestures, bare-letter placement, undo/redo,
  real solver honesty, Apache-2.0 licensing, and clear "what is real vs model" disclosure.
- Want the gesture correctness (no silent rotate-vs-place collisions), undo/redo, and the recent-file / settings
  discipline to be solid, because education users notice UX regressions fast.
- Would push for a **clear limitation page** aimed at students/teachers: what is simulated, what is modelled, what is
  parsed, what boots in QEMU, and what is not yet wired.
- Care about licensing and third-party material being explicit (Apache-2.0; Qucs-S-based studio materials noted).

---

## 3. Per-org audit team report (org → focus × implementation posture)

Each org below is treated as if it fielded its own audit team that read the repo's actual artifacts
(tests, bridge, editor, docs) and wrote a section for its own interests + preferred implementation posture.
These are synthesized auditor voices, not your own earlier summaries.

### 3.1 Industry-standard EDA incumbent — audit team report
**Interest:** Is this a credible *closed-loop add-in* to a real SPICE workflow, or a one-off PyQt demo?
**Read of the codebase:**
- The analog spine is a genuine ngspice C-API ctypes bridge; the compiler turns a schematic graph into a real
  netlist; the closed-loop co-sim calls back into Python per timestep. That is the right shape for an add-in.
- The closed loop is real and tested: retuning thresholds moves the operating point (1024→0.825 V, 3072→2.481 V),
  and load sweeps show the pin duty reacting — which can only happen if the pin reads the circuit.
- The netlist compiler resolves pins (union-find over wires, alias-aware pins, ground detection) and emits real
  SPICE; KiCad export is real (KiCad CLI resolves intended nets in a test).
**Preferred implementation:**
- Own the solver SDK spine (`ngspice_wrapper` ctypes boundary + `.cosim` semantics) as a versioned contract.
- Isolate `cad_engine` as a reusable netlist library, not private to the editor; add a canonical-netlist identity test.
- Push the per-timestep gate decision toward a native/compiled callback if speed matters; today it is a Python callback
  (the in-loop "firmware" is a parsed model, not executed code — keep that honest).
- Add netlist-identity, mode-identity, and deterministic-export tests so the back-end is comparable across runs.

### 3.2 Analog IC design house — audit team report
**Interest:** Are the components and analyses believable and solver-wired?
**Read of the codebase:**
- Component library lives in `circuits/components/models.lib`; analyses are wired through `analysis_runner`
  (`.tran`, `.ac`/Bode, FFT, `.dc` demo devices, `.noise`, `.disto`, step metrics, Monte Carlo, sweep) plus the
  editor tabs.
- Noise density is verified against √(4kTR) (4.07 nV/√Hz @ 27 °C for 1 kΩ) with correct 1-pole rolloff; `.disto`
  HD2/HD3 are finite, non-negative, with a biased diode producing real second-harmonic content.
- The GUI exposes the new analysis tabs (Noise, Distortion, Monte Carlo, Step Response, Timing) with real-solver
  backends and editor tests.
**Preferred implementation:**
- Treat physics-verifiable numbers as the acceptance criterion for components and analyses, not plots.
- Wire `.dc` for the user's own schematic as the next analysis gap (the I-V tracer sweeps fixed demo devices today).
- Keep the analysis-runner pattern consistent so each analysis is a library function with a real-solver test, not a
  one-off call site.
- Expand component fidelity coverage (CC/CS/linear region, motor losses, op-amp rail behaviour) under swept I-V/AC.

### 3.3 Automotive Tier-1 supplier — audit team report
**Interest:** Can we import a real control law from firmware and co-sim it against a drawn schematic?
**Read of the codebase:**
- Yes, in principle: `control_law.py` imports constants from firmware source (`ADC_LOW_THRESHOLD`, `ADC_HIGH_THRESHOLD`,
  `GATE_PIN`), `cosim_runner` closes the loop against a real ngspice solve, and the editor offers mode semantics and
  control-law authoring.
- The closed loop is real: thresholds move the operating point; load sweeps show duty responding.
- Mode semantics exist (Transient-only / MCU-only / Co-simulation) and are reflected in the netlist.
**Preferred implementation:**
- Own `control_law.py` + `cosim_runner.py` as the spine; treat the MCU pin model as a consumer.
- Make the three modes distinguishable in netlist *and* behaviour, not just dropdown labels.
- Build parameter-sweepable, exportable loop scenarios (line/load, corner) with CSV/PDF evidence — partially present.
- Keep the "parsed, not executed" disclosure rigorous; an automotive team must not mistake a parsed model for executed
  firmware in a safety-adjacent flow.

### 3.4 Automotive OEM systems integration — audit team report
**Interest:** Does this give traceable, standards-flavoured qualification evidence?
**Read of the codebase:**
- There is an `industrial_verification_engine` + Tools ▸ Qualification battery that produces qualification-flavoured
  reports; temperature-corner sweeps and fault-injection scenarios exist in tests.
- Report export (PDF, CSV, PNG) exists; KiCad schematic + netlist exist; Gerber/.kicad_pcb do not.
- Firmware behaviour honesty is explicitly maintained ("parsed, not executed" in the loop; QEMU boot proof separate).
**Preferred implementation:**
- Own/extend the qualification layer so reports are traceable to netlist + mode + parameters, not just numbers.
- Treat Gerber/.kicad_pcb as a gap until filled or explicitly deferred.
- Keep "parsed vs executed" disciplined; an OEM cannot certify behaviour it thinks is real when it is a model.
- Add a saved-scenario identity test (reconstruct exact netlist + mode) for traceability.

### 3.5 Aircraft OEM avionics — audit team report
**Interest:** Does this give certification-evidence discipline — real vs modelled vs parsed, reproducible, scenario-traceable?
**Read of the codebase:**
- Firmware behaviour honesty is maintained: "parsed, not executed" in the loop; QEMU boot proof is separate and real
  (900k samples / 90 s, zero panics); analog injection is real via `qom-set`.
- Headless execution, per-suite isolated settings, deterministic netlist, CSV/PNG/PDF export exist.
- PDF reports include per-net statistics.
**Preferred implementation:**
- Own the certification-evidence discipline: real/executed, modelled, parsed must be unambiguously labelled per result.
- Keep deterministic, reproducible, headless runs with clean settings isolation.
- Add a netlist + mode identity test for scenario traceability.
- Make PDF reports name the mode, source/image, and analysis type, not just the numbers.
- Treat "CI has never executed" as a readiness gap, not a feature.

### 3.6 Marine / process control OEM — audit team report
**Interest:** Long-duration reliability + distribution analysis (Monte Carlo, noise, distortion, step, corners).
**Read of the codebase:**
- Per-schematic Monte Carlo, noise density, distortion HD2/HD3, step metrics, sweep overlay, and corner/qualification
  scenarios exist and are tested.
- Document-restore is asserted in tests (Monte Carlo and sweep leave the schematic unchanged).
- Accuracy presets and Stop/interrupt exist.
**Preferred implementation:**
- Own reliability + distribution analysis as first-class, well-tested analyses with histogram/report output.
- Test document-restore under failure paths, not only success.
- Test that a stopped run leaves the document and solver state coherent.
- Push the automatic QEMU↔ngspice bridge as the difference between "proof" and "usable reliability flow".

### 3.7 Energy-infrastructure OEM — audit team report
**Interest:** Closed-loop regulation evidence package (buck/boost, load/line, efficiency, qualification).
**Read of the codebase:**
- Buck co-sim and line/load regulation parameter sweeps exist; efficiency and qualification reporting exist.
- Closed-loop regulation traces exist and are tested.
**Preferred implementation:**
- Own the regulation evidence package: buck/boost, load/line, efficiency, qualification reports tied to netlist + mode + params.
- Extend the industrial-verification battery to OEM scenarios with traceable reports.
- Fund the automatic firmware→analog bridge as the gap between proof-of-concept and a usable regulation flow.

### 3.8 Power-converter & motor-drive integrator — audit team report
**Interest:** Motor + PWM + current control modelling, MCU hardware truth.
**Read of the codebase:**
- Motor model in `circuits/components/models.lib`; PWM/external source capability; MCU GPIO model (PWM/square/static
  profiles); MCU board symbols (Arduino, STM32F103, ESP32, ESP32-S3); Pin Map tab with hardware direction inferred from
  pin name and labelled as such.
**Preferred implementation:**
- Own motor + PWM + current-control modelling; treat the MCU GPIO model and board symbols as the hardware-truth layer.
- Keep MCU board symbol correctness + pin-count parity tested as boards are added.
- Make Pin Map "hardware" inference rules explicit and reviewable.
- Push the Xtensa/ESP32 execution story and the missing automatic bridge as the differentiator to fund.

### 3.9 Regional design-hub / foundry PDK user — audit team report
**Interest:** A KiCad-exporting, BOM-producing, netlist-aware schematic flow for a fragmented local EDA environment.
**Read of the codebase:**
- `kicad_export` is real (KiCad CLI resolves intended nets in a test); BOM export exists; component/glyph pinning exists;
  pin-count parity between editor and KiCad is asserted.
- Hand-written netlists have no pin coordinates, so "Import as components" is deliberately not offered — honest.
**Preferred implementation:**
- Own the KiCad-exporting, BOM-producing, netlist-aware flow; keep `kicad_export` fidelity tests green.
- Add a canonical-netlist identity test so PDK users can compare netlists across tools.
- Keep the reverse-import decision bounded and explicit.
- Treat pin-count parity and glyph correctness as gating tests for any new board symbol.

### 3.10 Test & measurement IC vendor — audit team report
**Interest:** Verifiable device models and analysis coverage.
**Read of the codebase:**
- Device models in `circuits/components/models.lib`; `.dc` demo-device sweep real (MOSFET Vth = 3.0 V, Schottky knee);
  analysis coverage wired and tested (.tran, .ac/Bode, FFT, .dc demo, .noise, .disto, step, Monte Carlo, sweep).
**Preferred implementation:**
- Judge device models by swept I-V/AC behaviour, not by existence.
- Wire `.dc` for the user's own schematic as the next gap.
- Keep analysis coverage real-solver-wired and tested; treat the new Noise/Distortion tabs and their tests as the model.

### 3.11 MCU silicon vendor (Espressif tier) — audit team report
**Interest:** The Xtensa/ESP32 execution story as the differentiator.
**Read of the codebase:**
- Patched QEMU boots the compiled `.elf` through ROM, bootloader, `app_main()` and a full control loop: 900k samples / 90 s,
  zero panics; the SAR ADC + GPIO device-model patch is in `tools/qemu-patch`; analog injection is real via `qom-set`
  (gate flips ON→OFF at 3456).
- Inside the simulation loop, firmware is *parsed, not executed*; behaviour comes from separately importing the .c source
  or hand-writing a law.
**Preferred implementation:**
- Own the Xtensa/ESP32 execution story; make `tools/qemu-patch` reproducible end-to-end from a fresh source export + patch
  with a pinned source version and a reproducer script.
- Fund the missing automatic ngspice↔QEMU bridge; the manual `qom-set` proof is real but not yet a supported flow.
- Keep "parsed, not executed" inside the loop rigorously disclosed.

### 3.12 MCU / MCU IP licensee (STMicro / NXP tier) — audit team report
**Interest:** MCU hardware-truth layer and firmware-facing surface.
**Read of the codebase:**
- MCU board symbols, Pin Map tab, KiCad board symbols, firmware parsing, control-constant import, GPIO profile JSON, pin
  behaviour strings, and "load firmware" UX all exist.
- Pin→hardware inference is labelled as inferred from pin name, not as fact.
**Preferred implementation:**
- Own the MCU hardware-truth layer; keep board-symbol correctness + pin-count parity tested as boards are added.
- Make Pin Map hardware-inference rules explicit and reviewable.
- Treat the firmware-facing surface (parsing, control-law import, GPIO profiles) as versioned and honest about extraction
  limits.

### 3.13 Automotive Tier-2 firmware vendor — audit team report
**Interest:** Firmware-facing surface: parse, import constants from C, author GPIO profiles, load firmware UX.
**Read of the codebase:**
- `firmware.py` parses `.hex`/`.elf` (format, size, load address, entry point, sections, SHA-256); `control_law.py`
  imports constants from firmware source; GPIO profile JSON authoring exists; "load firmware" UX exists.
**Preferred implementation:**
- Own the firmware-facing surface; keep parsing honest about extraction limits and garbage rejection.
- Keep control-law import from C robust and versioned.
- Make explicit in the UX that loading an image gives metadata, and that behaviour comes from separately importing the .c
  source or hand-writing a law — so a firmware team does not expect a loaded `.elf` to drive GPIO automatically in the loop.

### 3.14 Systems-integrator / lab-automation vendor — audit team report
**Interest:** Headless, CI-able, reproducible, exportable engine.
**Read of the codebase:**
- Headless offscreen Qt, `run_tests.py`, per-suite isolated settings, deterministic netlist, CSV/PNG/PDF export, progress/stop
  exist.
- `.github/workflows/cosim-ci.yml` exists but README says it has never executed in CI history.
- Dockerfile/docker-compose are known broken (predate `find_library` fallback, copy neither `ui/` nor `tools/`).
**Preferred implementation:**
- Own the headless/CI/reproducibility/exports story; make CI actually run at least once (close the "never executed" gap).
- Either fix docker-compose/Dockerfile or mark it explicitly broken, not silently half-working.
- Keep per-suite settings isolation and deterministic netlist as gating for any automation integration.

### 3.15 Open-source-signal-chain / regional-tech nonprofit — audit team report
**Interest:** Education-friendly, honest, licenced tool with clear real-vs-modelled disclosure.
**Read of the codebase:**
- LTspice-shaped gestures, bare-letter placement, undo/redo, real solver honesty, Apache-2.0 licensing, and explicit
  "what is real vs model vs parsed" disclosure exist.
**Preferred implementation:**
- Own the education UX correctness (no silent rotate-vs-place collisions, undo/redo, gesture discipline) and the limitation
  page for students/teachers.
- Keep licensing + third-party material explicit.
- Treat "parsed vs executed vs modelled" disclosure as student-facing, not just developer-facing.

---

## 4. Cross-org synthesis — what every team would ask the codebase to prove next

These are the recurring, org-independent follow-ups that 15 teams would converge on, derived from the slice each
wants first.

1. **Real vs modelled vs parsed is labelled per artifact, not just per page.** Avionics/energy/automotive teams want
   every result page, report, and saved scenario to state which firmware behaviour is executed (QEMU), which is modelled
   (in-loop parsed controller), and which is purely simulated (analog). Today the disclosure exists but should be per-result.

2. **A saved scenario reconstructs its exact netlist + mode.** Avionics/automotive/energy teams want scenario-level
   traceability. A saved scenario should reconstruct the exact netlist and exact mode (Transient-only / MCU-only / Co-sim).

3. **Netlist identity is canonical and comparable.** PDK users, EDA incumbents, and systems integrators want the same graph
   to emit byte-identical/canonical netlists across runs, so the back-end is comparable across tools and runs.

4. **The QEMU↔ngspice automatic bridge is either built or explicitly broken.** MCU silicon vendor, MCU IP licensee,
   motor-drive integrator, energy OEM, and avionics teams all converge on the same gap: the manual `qom-set` proof is real,
   but the automatic coupling is missing. Any of them would fund that bridge; none would accept it as a supported flow today.

5. **CI and container story are real or explicitly marked stale.** Systems integrator and lab-automation vendor want
   `cosim-ci.yml` to have executed at least once, and the known-broken Dockerfile/docker-compose to be fixed or explicitly
   marked broken.

6. **`cad_engine` is a reusable, testable netlist library, not private to the editor.** EDA incumbent, PDK user, analog IC
   house, and systems integrator all want the compiler isolated and covered by solver-backed tests plus a canonical-identity
   test.

7. **Per-timestep callback cost is a real design issue, not a footnote.** The EDA incumbent and motor-drive integrator read
   `cosim_runner.py:163` ("get_vector_array() would copy the entire vector on every …") as a design signal: if speed matters,
   the per-timestep gate decision should move toward a native/compiled callback, and the current Python-in-the-loop controller
   is a model, not executed firmware.

8. **Document-restore is a contract, tested under failure paths.** Marine/process OEM and Monte Carlo users want the "sweep and
   Monte Carlo leave the schematic unchanged" guarantee tested under failure paths, not only success.

9. **Gerber/.kicad_pcb is either built or explicitly deferred.** Automotive OEM and any board-flow integrator want the gap closed
   or explicitly deferred; today it is an honest gap but not yet a decision.

10. **The `.dc` of the user's own schematic is wired or explicitly deferred.** Analog IC house, T&M vendor, and EDA incumbent
    want the user-schematic `.dc` gap closed (the I-V tracer sweeps fixed demo devices today).

11. **Component fidelity is verified under swept I-V/AC, not assumed.** T&M vendor and analog IC house want device models judged
    by swept behaviour; motor losses, op-amp rail behaviour, diode knee, MOSFET Vth are the kind of evidence they'd demand.

12. **Pin-count parity + glyph correctness are gating tests for new board symbols.** MCU IP licensee, PDK user, and nonprofit
    education team all want new board symbols gated by editor↔KiCad pin-count parity and glyph drawing tests.

---

## 5. Honest caveats carried from the repo's own documentation

These are not invented here; they are the repo's own stated limitations, restated for the audit record.

- The in-loop "firmware" is parsed, not executed: the controller logic and constants are lifted from firmware source, not the
  compiled image running inside the simulation loop. The compiled image boots and runs its real control loop in patched QEMU
  (900k samples / 90 s, zero panics), and responds to manually injected analog values, but the automatic ngspice↔QEMU bridge is
  not yet built.
- KiCad *schematic + netlist* export exist; PCB-layout formats (Gerber, .kicad_pcb) do not.
- `.dc` sweep is wired for built-in demo device models (MOSFET Vth = 3.0 V, Schottky knee); a `.dc` of the user's own schematic
  is reachable only via the raw netlist editor.
- `.github/workflows/cosim-ci.yml` exists but has never executed in CI history (per README/verification).
- `Dockerfile`/docker-compose are known broken (predate `find_library` fallback; copy neither `ui/` nor `tools/`).
- The test suite covers the Python controller matching three scraped constants in a C file; it does not mean the compiled image's
  behaviour is proven end-to-end by those tests.
- Renode co-simulation is abandoned (Xtensa `entry` instruction decode failure); the Renode path is kept for reference only.
- `circuits/components/models.lib` and the demo device models are reverse-engineered; fidelity is verified under swept I-V/AC in
  tests but is not equivalent to a foundry PDK.

---

## 6. How to use this audit

- Each org's section is a *preferred implementation posture*, not a verdict of current correctness. Where the codebase already
  meets an org's interest, that is stated as a read of the artifacts; where it does not, that is stated as a gap or a deferral.
- The cross-org synthesis (§4) is the list of follow-ups that 15 teams would converge on; treat those as the roadmap candidates
  that survive org-by-org filtering.
- The honest caveats (§5) are the repo's own stated limitations; any roadmap item that touches them should carry the same
  disclosure in its own docs, not weaken it.
