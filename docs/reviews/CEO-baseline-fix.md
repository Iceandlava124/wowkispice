# CEO Review — plan-ceo-review (Phase 1 of /autoplan)

Reviewed input: `docs/PLAN-baseline-fix.md`
sha256 `49801f457dae4c856109e77673f4ee89d117a025a9ba916d5fdb0a40b177c4cf`
Mode: SELECTIVE EXPANSION
Host: claude. Outside provider: codex — **unavailable** (`CODEX_MODE: not_installed`).
Adversarial subagent: **unavailable** (this host exposes only `researcher-web`).
Tag: **[single-model]**. Both outside voices missing, so no consensus cell is CONFIRMED.

## PLAN_REALITY rows

REALITY: premise-table pass four premise challenges named with evidence, PC-1 Critical; docs/reviews/CEO-baseline-fix.md:22
REALITY: already-done pass analog engine, control law, netlist compiler, KiCad export and firmware parsing each mapped to a green suite; docs/reviews/CEO-baseline-fix.md:74
REALITY: surface-check finding the plan proved the verified half and deferred the product's loop - PC-1; docs/reviews/CEO-baseline-fix.md:26
REALITY: binding-decisions pass owner reversed the review's recommendation at the gate (D4) and the plan was restructured to match; docs/PLAN-baseline-fix.md:5
REALITY: numbers pass 166/6/2 measured per file with the 312 discrepancy explained by 3 uncollectable files; docs/PLAN-baseline-fix.md:38
REALITY: deferred-asks pass five deferrals each carry a rationale and a destination; docs/reviews/CEO-baseline-fix.md:66
REALITY: pr-count finding P0 task 1 had no bounded experiment until this review forced three with a stop condition; docs/PLAN-baseline-fix.md:96

---

## Step 0 — premise challenges

The plan's own evidence supports its measurements. Two of its premises do not survive
a CEO reading.

### PC-1 (Critical) — the plan optimises the half of the product that has never been the problem

REALITY: the analog engine is the only part of this system with passing tests. The
co-simulation loop — ngspice voltage into QEMU ADC into gate decision back into the
solver — is the product's entire reason to exist, and `docs/architecture.md` states it
plainly: "This track has zero bi-directional coupling to ngspice today."

The plan puts "make the suite runnable and honest" in P0 and the embedded half in P3,
"owner-gated, cannot be done on this box". Mechanically that is true. Strategically it
means the plan, if executed perfectly, delivers a repo that is honest and green about
everything except the thing the project claims to be. The last eight tasks all ended the
same way.

Cost of proceeding: another green baseline, another deferred Phase 1, and the same
review in a month. The plan must either name the pilot's scope as simulation-only (which
legitimises P3 as a real boundary rather than a parking lot) or move a bounded piece of
the loop into P1/P2.

**Disposition: USER CHALLENGE queued for Phase 4.** Both would change the user's stated
direction, so this is never auto-decided.

### PC-2 (High) — "fix or pin pyqtgraph" is an unbounded investigation disguised as a task

REALITY, measured this session: `PyQt5 5.15.9`, `PyQt5-Qt5 5.15.2`, `pyqtgraph 0.13.3`,
CPython 3.12.10 on Windows. `import PyQt5.QtWidgets` exits 0; `import pyqtgraph` exits
139 inside `graphicsItems/GraphicsWidget.py`, with and without `QT_QPA_PLATFORM=offscreen`,
and with a `QApplication` constructed first. That signature points at a Qt platform or
OpenGL context problem, not at a pyqtgraph logic bug. "Fix or pin" gives no bounded
experiment and no stopping rule.

**Disposition: TASTE DECISION, auto-decided.** P0 task 1 is rewritten as three bounded
experiments with a stated stop condition (see the amended plan).

### PC-3 (Medium) — the plan has no rollback story for the number it is about to change

REALITY: today the honest count is 166 passed / 6 failed / 2 skipped / 3 files
uncollectable. If P0 makes the three crashing files skip instead of crash, the headline
becomes "166 passed, 146 skipped", which reads worse than the number it replaced. The
plan never states the target, so nobody reviewing the fix will accept it.

**Disposition: TASTE DECISION, auto-decided.** P0 gains an explicit target: the three
files must *collect and run*, not skip. A skip is a fallback, not a landing.

### PC-4 (Low) — the sanitiser premise is stale and the plan inherits it

`docs/KNOWN_ISSUES.md` item 8 asserts the sanitiser rejects `.tran`. Measured this
session: `test_ngspice_bridge.py` 1 passed, `test_ngspice_dll_proof.py` 3 passed. The
plan's P2 task 7 already catches this. No further challenge; noted so the next reader
does not re-derive it.

---

## NOT in scope (deferred, with rationale)

| Deferred | Rationale | Where it goes |
|---|---|---|
| Standing up a QEMU binary and a `qemu_flash.bin` | Needs hardware/CI the box does not have; the plan must not pretend otherwise | P3, owner-gated |
| Re-including `tools/qemu-patch/` in git | Owner holds the patch; not derivable from this checkout | P3, owner-gated |
| Raising the firmware build timeout | Only meaningful once a binary can be produced at all | P3, owner-gated |
| CI runners | Separate infrastructure effort; not required to make this baseline honest | TODOS.md |
| Matching real silicon | No test here measures hardware. Nothing may claim it | Never |

## What already exists (sub-problem → code)

| Sub-problem | Existing code | Verified how |
|---|---|---|
| Real SPICE solving | `bridge/ngspice_wrapper.py` | `test_ngspice_bridge.py`, `test_ngspice_dll_proof.py`, `test_measurements.py` (36), `test_parameter_sweeps.py`, `test_closed_loop_buck.py`, `test_industrial_verification.py` — all green today |
| Firmware-truthful control law | `bridge/control_law.py` reads thresholds out of `main.c` | `test_cosim_control.py` (34 green) |
| Schematic → netlist | `bridge/cad_engine.py` union-find net resolution | `test_kicad_export.py` (14 green) |
| Export validated against its consumer | `bridge/kicad_export.py` against a real KiCad 10 install | `test_kicad_export.py` |
| Firmware parsing | `bridge/firmware.py`, addresses deliberately far from file offsets | `test_firmware_gpio.py` `TestElf` (green) |
| Honest test runner | `tools/run_tests.py` — currently the opposite | Measured: exits 0 on a failed collection |

The reuse ladder holds: nothing in P0 asks for a new dependency, a new framework or a
new abstraction. Every P0/P1 item edits an existing file.

---

## Section 2 — Error & Rescue Registry

| # | Error class | Trigger | Handler today | Rescue | Test |
|---|---|---|---|---|---|
| E1 | `ImportError` | PyQt5 absent from the interpreter the runner picked | pytest collection error | Runner must fail, not pass | None; today the runner exits 0 |
| E2 | Native access violation (0xC0000005) | `import pyqtgraph` | Process dies; pytest cannot report it | Guard at collection with a named skip; never let it kill the interpreter | None |
| E3 | `RuntimeError` from `load_circuit` | Banned netlist directive | Raised and asserted | Keep | `test_ngspice_dll_proof.py` |
| E4 | `QemuMonitorError` | No live QEMU process | Returned as a clean cycle | Keep | `test_qemu_monitor_unit.py` |
| E5 | Stale assertion | Interface changed under a test | Test fails loudly | Update the test, log in `tests/CHANGES.md` | The six failures |

E2 is the only one with no handler at all, and it is the one that silently removes 146
tests from the suite. Catch-all risk: guarding E2 with a bare `except Exception` would
convert a crash into a silent pass, which is worse than the crash. The guard must be a
`pytest.skip` at collection with the exit code in the reason.

## Section 4 — Failure Modes Registry

| # | Failure mode | Likelihood | Impact | Plan's answer |
|---|---|---|---|---|
| F1 | Runner goes honest, count gets worse, the fix is reverted | High | High | P0 names the target: collect and run, not skip |
| F2 | pyqtgraph guard hides a real UI regression | Medium | High | Skip reason names the exit code and platform; no `except ImportError` pass |
| F3 | `decide(2031)` "fixed" by loosening the assertion | Medium | High | Firmware source is the contract; assertion is corrected to match quoted branch order |
| F4 | QEMU tests count as passing because they skip | High | Critical | Skips stay skips; no executed test, no pass |
| F5 | Plan is executed, green baseline ships, Phase 1 still absent | High | Critical | PC-1, queued as a User Challenge |

## Dream state delta

Twelve months out, this system is a mixed-signal co-simulator where a drawn schematic,
a real ESP32 firmware image and a real SPICE solver close a loop with no human in it.
Today the analog half is real and the loop half is two independent tracks that share
numbers. This plan, executed fully, moves the repo from "honestly broken" to "honestly
runnable" — it does not move the loop. That is a legitimate milestone and a dangerous
one if it is mistaken for progress on the product.

## Completion Summary

| Area | Status |
|---|---|
| Premises valid | 2 of 4 challenged; 1 queued as User Challenge |
| Right problem | Partial — right for the baseline, silent about the product |
| Scope calibration | Correct for P0/P1; P3 is a parking lot, not a plan |
| Alternatives explored | Adequate; the pyqtgraph investigation lacks bounded experiments |
| Risks covered | F5 is named but unowned |
| 6-month trajectory | Sound only if PC-1 is resolved |

## CEO DUAL VOICES — CONSENSUS TABLE

```
  Dimension                            Claude  Codex  Consensus
  1. Premises valid?                   —       N/A    N/A
  2. Right problem to solve?           —       N/A    N/A
  3. Scope calibration correct?        —       N/A    N/A
  4. Alternatives sufficiently explored?—      N/A    N/A
  5. Competitive/market risks covered? —       N/A    N/A
  6. 6-month trajectory sound?         —       N/A    N/A
```

`outside_status: unavailable` (codex not installed; no adversarial subagent on this
host). Per the degradation matrix this is **single-reviewer mode**. Every cell is N/A,
never CONFIRMED. Single-voice criticals to watch: PC-1.

## PLAN_REALITY

`PLAN_REALITY: plan=docs/PLAN-baseline-fix.md phase=ceo checks=5 passed=5 verdict=complete`
