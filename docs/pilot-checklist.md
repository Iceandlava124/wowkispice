# Pilot Checklist — Editor → Buck Circuit → F2 Run

Short acceptance checklist for the PyQt5 schematic editor, the 12 V → 3.3 V hysteretic buck demo, and one transient run. This is a *runbook*, not a plan: do it in order, compare each step against the expected result, and stop when a step does not match.

**Scope.**
- Transient analysis from the editor (`F2` → Waveforms tab).
- Declared-law closed-loop cosimulation, if the buck controller is wired into the schematic — not the real firmware binary (that is a separate checklist, in `docs/binary-runner-and-mcu-bringup.md`).

**How to tell this doc from marketing:** every expected result here is a number or a test name, and anything not verified is labelled `UNVERIFIED`. If a step has no measurable limit, say so.

---

## 0. Start from a known-good state

1. Run the environment gate first.
   - Command: `run_selfcheck.bat` (Windows) or the equivalent from `SETUP.md`.
   - Expected: `SELF-CHECK: PASS (quick mode - full suite not run)` and exit 0.
   - If it fails, stop. Do not open the editor; fix the environment first.
     - `tests/test_selfcheck.py::TestSelfcheck::test_quick_selfcheck_reports_pass` is the automated guard for this step.

2. This checklist assumes the editor launches headless in its current test form and that the automated suites are green.
   - Status: `tests/test_sota_suite.py` (7 tests) + `tests/test_selfcheck.py` (1 test) are green in this repo branch.
   - Remaining status of a graphical launch on a real desktop: `UNVERIFIED` in this checklist.

---

## 1. Launch the editor

**Step.**
- Start the schematic editor from the project root.
  - In headless/test contexts this is what `tests/test_schematic_editor.py` exercises through `SchematicEditor()` with `QT_QPA_PLATFORM=offscreen`.

**Expected.**
- A main window opens with:
  - a schematic canvas,
  - a component palette/sidebar,
  - a netlist pane or equivalent, and
  - analysis tabs including **Waveforms**.
- No uncaught exception on startup.
- Status of each specific UI element listed here: `CONFIRMED WORKING` for the analysis-mode surfaces in `docs/analysis-mode-audit.md` §1; the exact dock/tab layout is not re-verified by this checklist.

**Stop condition.**
- If the window does not open, or the Waveforms tab is missing, stop and log the failure. Do not continue to circuit construction.

---

## 2. Build the buck circuit (12 V → 3.3 V hysteretic)

**Goal.**
- A schematic that compiles to a solvable buck with an MCU control pin on the switch gate.

**Step-by-step.**

1. Place and wire the power path.
   - `V1` (12 V source) → `S1` (switch, gate driven) → `L1` (47 µH) → `vout` → `C1` (100 µF) → `Rload`.
   - `D1` freewheels from 0 → sw_node.
   - Ground the negative of `V1` and one side of `C1`/`Rload`.

2. Place and wire the control side.
   - Place one MCU (ESP32 for the firmware-derived law, or any MCU for a declared profile).
   - Wire the MCU GPIO to `S1:CTRL` on the net `gate`.

3. If you want the **firmware-derived closed loop**, attach the control law from firmware source.
   - Use `bridge/control_law.py::law_from_firmware_source[_exact]` against `firmware/esp32_buck_controller/src/main.c`.
   - Attach it to the MCU in the engine as a control law so the gate pin becomes an `external` source (`bridge/cosim_runner.py` drives it from inside the solver).

4. If you only want the **declared-law demo**, give the MCU pin a profile instead of a law.
   - Example: a static or hysteretic profile on the gate pin, enough to drive the switch.

5. Verify the netlist compiles cleanly.
   - Engine path: `bridge/cad_engine.py::compile_netlist`.
   - Expected: a `.tran` card, the switch/diode/inductor/capacitor/load, and the gate source.

**Expected waveforms (steady-state target).**
- The firmware-derived loop targets the divider node at about 2048 counts of 3.3 V over a 1× divider → about **1.62 V** at the sense node.
- Across a load sweep (e.g. 5 Ω → 1.5 Ω → 0.5 Ω), the tail mean should stay near that target.
  - Verified tolerance in the existing cosim tests: `assertAlmostEqual(mean, 1.62, delta=0.10)`.
  - This is the published acceptance band for the declared-law closed loop.

**Stop condition.**
- If `compile_netlist` emits an empty list or the netlist is obviously missing the switch/inductor/output node, stop. Do not run F2 on an empty deck.

---

## 3. Run F2 (transient)

**Step.**
- From the editor, run the transient simulation.
  - UI path: **Waveforms** tab / run action / `F2`.
  - Under the hood this is `bridge/cad_engine.py` → ngspice transient → waveform readback.

**Expected.**
- A transient trace set appears in the Waveforms tab.
- For the buck circuit in §2, the primary trace to look at is the output node (`vout`) and the switch control (`gate`).
- Status:
  - Transient tab and F2 path are `CONFIRMED WORKING` in `docs/analysis-mode-audit.md` §1.
  - The exact plotted traces and zoom range are not re-certified by this checklist; this step checks that a run produces *some* plot and the right key traces exist.

**If the firmware law is attached**, the gate should switch repeatedly during the run and the output should sit near the target band above.

**If only a declared profile is attached**, the switch is driven by that profile; the output may or may not regulate — that depends on the profile you chose, not on the F2 button itself.

**Stop condition.**
- If F2 produces no trace, or the run aborts with a solver error, stop and inspect the netlist warnings from `compile_netlist` before retrying.

---

## 4. Inspect waveforms and limits

**What to look at.**

1. Output voltage (`vout`).
   - Expected steady band for the firmware-derived loop: **1.62 V ±0.10 V** in the tail, per the existing cosim acceptance.
   - If a load step was applied, the band should hold across the step.

2. Switch gate / control signal.
   - Expected: repeated switching during the run when a closed loop is active.
   - When no law/profile is attached, the gate may be flat — that is not a bug in the UI, it is a missing control input.

3. Algebra of the circuit.
   - Freewheeling diode, inductor, output cap, and load must all be present for a sensible transient.
   - If any of those is missing, the plot may look reasonable while the circuit is actually wrong — so check the parts list, not just the trace shape.

**Hard limits for this checklist.**
- Primary acceptance number: output tail mean within ±0.10 V of 1.62 V **when the firmware-derived closed loop is wired and the run finishes**.
- This is not a claim that the editor itself guarantees regulation; it is the existing test assertion for the cosim path.

**Negative checks.**
- If the gate is flat and you expected switching, check whether a control law/profile is actually attached to the MCU.
- If the output is near zero, check for a missing source, missing ground, or a miswired switch.

---

## 5. Record the result

**Step.**
- Save the result however the editor supports it, or record the trace/key values by hand for this pilot.
- If the run matched the band above, mark the pilot step **PASS**.
- If not, record:
  - the schematic steps,
  - the netlist warnings,
  - the expected vs actual output level,
  - whether a control law or profile was attached.

**Expected.**
- A written result: which step matched, which did not, and the numbers.

---

## Verification status of this checklist

| Step | Status | Evidence |
|---|---|---|
| Environment gate | CONFIRMED | `run_selfcheck.bat`, `tests/test_selfcheck.py::test_quick_selfcheck_reports_pass` |
| Netlist + declared-law cosim | CONFIRMED | `tests/test_sota_suite.py`, `tests/test_cosim_control.py` |
| Editor transient (F2 path) | CONFIRMED (analysis-mode surface) | `docs/analysis-mode-audit.md` §1 |
| Exact GUI launch on a real desktop | UNVERIFIED | not covered by this checklist |
| Firmware binary closed loop from F2 | UNVERIFIED / planned | see `docs/binary-runner-and-mcu-bringup.md` |

---

## Companion docs

- `docs/analysis-mode-audit.md` — what the editor actually exposes now.
- `docs/binary-runner-and-mcu-bringup.md` — the real-firmware closed-loop path, if that is the mixed-signal step you are aiming at.
- `docs/industry-readiness.md` — the honest readiness verdict and phases.
- `bridge/cosim_runner.py`, `bridge/control_law.py`, `bridge/cad_engine.py` — the engine paths behind F2 for this circuit.
