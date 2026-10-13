# Analysis-Mode Audit — Active PyQt5 Editor

**Scope.** This audits the *active* editor, `ui/schematic_editor.py`, only. The
legacy surfaces (`ui/ltspice_workbench.py`, `ui/dashboard.py`, bare
`bridge/studio_engine.py` call sites) are a separate path per
`docs/legacy-module-audit.md` and are mentioned only as *engine capability*.

**Method.** Every claim below comes from grepping the live UI (menu actions,
toolbar, tabs, buttons) and the engine call graph, not from marketing docs.

---

## 1. Analysis types the editor's UI actually exposes right now

| Analysis | UI surface | Entry points | Backed by |
|---|---|---|---|
| Transient `.tran` | **Waveforms** tab | Run button / toolbar / `F2` | `bridge/cad_engine.py` compiler (always emits `.tran … uic`) → `ngspice_wrapper` |
| AC / Bode `.ac` | **Bode** tab | "Run Simulate ▸ Run Bode / AC Sweep", `Ctrl+B`, in-tab "Run AC Sweep" button | `analysis_runner.run_bode`; compiler emits `.ac dec …` |
| FFT (of last transient) | **FFT** tab | Simulate ▸ Run FFT of selected net, `Ctrl+F` | `analysis_runner.run_fft` |
| DC curve tracer `.dc` | **I-V Curve Tracer** tab (wired this pass) | Simulate ▸ Run I-V Curve Tracer, `Ctrl+Shift+D`, in-tab "Run I-V sweep" | `studio_engine.trace_mosfet_iv` / `trace_diode_iv` — real `.dc` sweeps of **built-in demo device models**, not the drawn schematic |
| Free-form netlist execution | **Netlist Editor** tab | "Run this netlist" | raw escape hatch: a user can type `.op`, `.dc`, `.noise`, … and run it; no dedicated widget |
| Co-simulation *modes* (not analysis types) | toolbar combo | Transient only / MCU only / Co-simulation | selects which path `F2` takes |
| Parametric sweep | **Parametric Sweep** tab | Simulate ▸ Run Parametric Sweep, `Ctrl+Shift+S`, in-tab Run | `analysis_runner`-style re-run loop over compile + solve (document restored after) |
| Noise `.noise` | **Noise** tab | Simulate ▸ Run Noise Analysis, `Ctrl+Shift+N`, in-tab Run | `analysis_runner.run_noise` → `.noise V(out) src dec …`, spectra located by plot description |
| Distortion `.disto` | **Distortion** tab | Simulate ▸ Run Distortion Analysis (.disto), `Ctrl+Shift+T`, in-tab Run | `analysis_runner.run_disto` (AC reference + HD2/HD3 = harmonic/fundamental, plotted in dBc) |
| Monte Carlo / yield | **Monte Carlo** tab | Simulate ▸ Run Monte Carlo / Yield, `Ctrl+Shift+M` | `analysis_runner.run_monte_carlo` — **per-schematic**: every sample is a real solve of the drawn circuit |
| Step-response metrics | **Step Response** tab | Simulate ▸ Step Response Metrics, `Ctrl+Shift+E` | `measurements.step_metrics` (delay, 10-90% rise, overshoot, settling, slew) |
| Digital timing diagram | **Timing** tab | Simulate ▸ Show Timing Diagram, `Ctrl+Shift+G` | `gpio_model.analyze_pin` / `measured_frequency` — stacked thresholded lanes per trace |
| Readouts (not analyses) | **MCU / GPIO**, **Pin Map**, **Serial** tabs | duty / edge-count / frequency; raw UART log import | `gpio_model`, `serial_console` |

Tooling extras: speed preset combo (Accurate / Balanced / Fast), qualification
battery under Tools, Results ▸ CSV/PNG/PDF export.

**Not exposed as any button/tab:** `.op` (only via the netlist escape hatch),
a `.dc` sweep *of the user's own schematic* (the I-V tracer sweeps fixed demo
device models).

---

## 2. Engine capability that exists but is not reachable from the editor

| Capability | Engine location (tested?) | Editor status | Cost to expose |
|---|---|---|---|
| UART packet decode | `studio_engine.decode_uart_packets` (`test_studio_suite`, `test_sota_suite`) | **Wired this pass**: Serial tab net+baud+Decode TX (demo fallback filtered) | done |
| Solar PV / MPPT trace | `studio_engine.trace_solar_pv` (`test_sota_suite`) | **Wired this pass**: PV / MPPT tab (I-V + P-V plots, MPP marker, info line) | done |
| AWG waveform generator | `studio_engine.generate_awg_signal` (`test_studio_suite`) | **Wired this pass**: AWG tab (type/freq/amp/offset/duty/phase/duration → plot + stats) | done |
| Parametric sweep (Vin/Rload vs Vout) | re-run per point | **Wired this pass**: Parametric Sweep tab (`Ctrl+Shift+S`), document restored after the sweep | done |
| Operating point `.op` | computed internally by studio engine; editor's compiler only emits `tran`/`ac`/`noise`/`disto` | no button (only the raw netlist escape hatch) | **Small–medium**: compiler card + runner + readout |
| Monte Carlo / yield | `studio_engine.run_monte_carlo` is a fixed-buck parametric model; **`analysis_runner.run_monte_carlo` is per-schematic and tested** (`test_measurements.TestNoiseAndYield`) | **Wired this pass**: Monte Carlo tab (`Ctrl+Shift+M`) → per-schematic solves, yield vs spec, histogram | done |
| Second AC path `run_real_spice_bode` | studio engine | editor already ships its own working AC/Bode path | **No action** — duplicate (see `docs/legacy-module-audit.md`) |

---

## 3. Explicit check — DC sweep (`.dc`)

- **Engine path: YES, working.** `trace_mosfet_iv` and `trace_diode_iv` build
  real `.dc` netlists and run them through ngspice; `tests/test_studio_suite.py`
  extracts MOSFET Vth = 3.0 V and the Schottky knee voltage from the results.
- **Reachable from the editor: YES as of this pass** — the **I-V Curve Tracer**
  tab + Simulate ▸ Run I-V Curve Tracer (`Ctrl+Shift+D`), with an
  ends-in-data test in `tests/test_schematic_editor.py`.
- **Caveat:** the tracer sweeps *fixed demo device models*. A `.dc` sweep of
  the user's own schematic has **no button** — it is reachable only by typing
  the card into the Netlist Editor.

## 4. Explicit check — timing / logic diagram view

- **Built this pass.** The **Timing** tab (Simulate ▸ Show Timing Diagram,
  `Ctrl+Shift+G`) stacks one digital lane per trace of the last run, each
  thresholded at its own mid-swing and drawn as an ideal 0/1 staircase, with
  edge count / duty / measured frequency per lane. Flat traces are drawn as
  honest constant lanes (0 edges), never as invented activity.
- Engine path: `gpio_model.analyze_pin` + `measured_frequency` (pre-existing,
  tested in `test_firmware_gpio`); test in `test_schematic_editor.py`
  (`test_timing_tab_draws_digital_lanes_from_the_last_run`).

---

## 5. The three buckets

### ALREADY WORKING IN THE EDITOR
- Transient (F2) with cursors, readouts and `.meas` surfacing
- AC / Bode (`Ctrl+B`)
- FFT (`Ctrl+F`)
- DC I-V curve tracer (`Ctrl+Shift+D`) — wired this pass
- UART packet decode on the Serial tab (net + baud + Decode TX) — wired this pass
- Solar PV / MPPT trace (PV / MPPT tab, `Ctrl+Shift+V`) — wired this pass
- AWG waveform generator (AWG tab, `Ctrl+Shift+A`) — wired this pass
- Parametric sweep (Parametric Sweep tab, `Ctrl+Shift+S`) — wired this pass
- Noise `.noise` (Noise tab, `Ctrl+Shift+N`) — **wired this batch**: compiler
  card + `analysis_runner.run_noise` + UI, DC density verified against √(4kTR)
- Distortion `.disto` (Distortion tab, `Ctrl+Shift+T`) — **wired this batch**:
  compiler cards (`.ac` + `.disto` + `distof1`) + `analysis_runner.run_disto`
  (HD2/HD3 = harmonic/fundamental per the ngspice manual) + UI in dBc
- Monte Carlo / yield, **per-schematic** (Monte Carlo tab, `Ctrl+Shift+M`) —
  **wired this batch**: `analysis_runner.run_monte_carlo` re-solves the drawn
  circuit per sample, reports sigma/yield, restores the document
- Step-response metrics (Step Response tab, `Ctrl+Shift+E`) — **wired this
  batch**: `measurements.step_metrics` (delay, rise, overshoot, settling,
  slew) with the ±2% band and 50% crossing drawn on the waveform
- Digital timing diagram (Timing tab, `Ctrl+Shift+G`) — **wired this batch**
- Free-form netlist execution (escape hatch for any analysis card)
- GPIO duty / edge / frequency readouts, raw UART log import

### ENGINE EXISTS BUT NOT WIRED TO UI
- `.op` operating point — small–medium (compiler + UI)
- A `.dc` sweep *of the user's own schematic* (the tracer's `.dc` path sweeps
  fixed demo device models only)

### GENUINELY NOT BUILT YET
- (nothing left in this bucket from the original audit — noise, `.disto`,
  Monte Carlo, timing view and the step-response viewer all landed this pass;
  see `docs/deliverables-verification.md` for the remaining vision scope:
  Phase 4 AI assistant, net↔waveform highlight, templates, Preferences,
  Gerber/PCB export, packaging)

---

## Verification status at time of writing

- The I-V curve tracer wiring, its test, and the README wiring-status
  checklist are in the working tree (see `README.md` → "Analysis-mode wiring
  status (per the analysis-mode audit)").
- **Full suite green: 309 tests, 17 suites** — after fixing the real cause of
  the long-hanging `.meas` tests: `load_circuit()` never gave ngspice a title
  line, and ngspice treats the first line of every deck as the title, so a
  hand-typed netlist lost its first device line (floating nodes → singular DC
  op → `run` wedged forever). `bridge/ngspice_wrapper.py` now guarantees a
  title; two stale test assertions (a FIND `at=` format ngspice-47 never
  printed, a `.3g` readout expectation that never matched `%g`) were corrected.
- Landed this pass: UART decode (Serial tab), PV/MPPT tab, AWG tab,
  Parametric Sweep tab, then (parallel batch) Noise tab, Distortion tab,
  Monte Carlo / yield tab, Step Response tab and Timing tab — each with an
  end-to-data test in `tests/test_schematic_editor.py`; the noise/disto/MC/
  step engines have their own solver-backed tests in
  `tests/test_measurements.py` (36 tests; see also
  `docs/deliverables-verification.md` for the full vision-doc check).
- Noise verified against physics: DC output density of an RC low-pass equals
  √(4kTR) at 27 °C within 5% (4.07 nV/√Hz for 1 kΩ), with the 1-pole rolloff
  above the corner; `.disto` HD2/HD3 come out finite and non-negative, with a
  biased diode producing real second-harmonic content.

- Reconciliation record (2026-10-08, this session): two audits conflicted on
  whether noise, distortion, per-schematic Monte Carlo, step response and timing
  were built. Resolution method was **code first, then test**: each was checked
  for a reachable editor handler in `ui/schematic_editor.py`, an implementing
  function in `bridge/`, and a test in `tests/`; the exact analysis tests were
  then run and are green in this session's rerun.

  Reconciliation table (all CONFIRMED unless noted):
  - Noise `.noise`: reachable (`ui/schematic_editor.py:run_noise_analysis`,
    menu "Run &Noise Analysis" `Ctrl+Shift+N`); implements
    `bridge/analysis_runner.py:run_noise` with the `.noise` card in
    `bridge/cad_engine.py:compile_netlist`; covered by
    `tests/test_measurements.py:TestNoiseAndYield.test_noise_matches_resistor_
    thermal_noise` and `tests/test_schematic_editor.py:TestAnalysisPanels.test_
    noise_tab_measures_resistor_thermal_noise`. Status: **CONFIRMED**.
  - Distortion `.disto`: reachable (`ui/schematic_editor.py:run_distortion_analysis`,
    menu "Run &Distortion Analysis (.disto)" `Ctrl+Shift+T`); implements
    `bridge/analysis_runner.py:run_disto` with the `.ac`+`.disto`+`distof1` cards
    in `bridge/cad_engine.py:compile_netlist`; covered by
    `tests/test_measurements.py:TestDistortion.test_distortion_reports_hd2_hd3`
    and `tests/test_schematic_editor.py:TestAnalysisPanels.test_distortion_tab_
    reports_harmonics_in_dbc`. Status: **CONFIRMED**.
  - Per-schematic Monte Carlo / yield: reachable (`ui/schematic_editor.py:run_yield_study`,
    menu "Run Monte Carlo / &Yield" `Ctrl+Shift+M`); implements
    `bridge/analysis_runner.py:run_monte_carlo`; covered by
    `tests/test_measurements.py:TestNoiseAndYield.test_monte_carlo_perturbs_the_
    schematic_and_restores_it` and `tests/test_schematic_editor.py:TestAnalysisPanels.test_
    monte_carlo_tab_solves_real_samples_and_restores_the_doc`. Status: **CONFIRMED**.
  - Step response / propagation delay: reachable (`ui/schematic_editor.py:analyze_step_response`,
    menu "&Step Response Metrics" `Ctrl+Shift+E`); implements
    `bridge/measurements.py:step_metrics` plus the editor handler; covered by
    `tests/test_measurements.py:TestStepMetrics` (3 tests) and
    `tests/test_schematic_editor.py:TestAnalysisPanels.test_step_response_tab_
    measures_delay_rise_and_settling`. Status: **CONFIRMED**.
  - Timing / logic diagram: reachable (`ui/schematic_editor.py:draw_timing_diagram`,
    menu "Show &Timing Diagram" `Ctrl+Shift+G`); implements
    `bridge/gpio_model.py:analyze_pin` + `measured_frequency` plus the editor
    handler; covered by `tests/test_schematic_editor.py:TestAnalysisPanels.test_
    timing_tab_draws_digital_lanes_from_the_last_run`. Status: **CONFIRMED**.

  Compiler claim also corrected by code: `bridge/cad_engine.py:compile_netlist`
  already accepts `analysis in ("tran", "ac", "noise", "disto")` (line 229), so
  the older audit's "only tran/ac" wording is wrong. Status: **CONFIRMED**.

  Genuinely still open (not resolved by this reconciliation):
  - `.op` button — absent; only raw-netlist escape hatch.
  - `.dc` sweep of the user's own schematic — tracer sweeps fixed demo device
    models only; not a UI button.
  - Automatic ngspice↔QEMU bridge — QEMU boot + manual `qom-set` injection are
    real; the automatic orchestrator is not yet wired. Status: **CONFIRMED OPEN**.

  Count verified in this session's rerun: 309 tests, 17 suites, all green.
