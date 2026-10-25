# Eng Review — plan-eng-review (Phase 3 of /autoplan)

Reviewed input: `docs/PLAN-baseline-fix.md` (amended after the Phase 4 gate decision D4)
Mode: HOLD-SCOPE on the harness half, SCOPE EXPANSION on the loop
Host: claude. Outside provider: codex — **unavailable** (`CODEX_MODE: not_installed`).
Adversarial subagent: **unavailable** (host exposes only `researcher-web`).
Tag: **[single-model]**. Every consensus cell below is N/A, none CONFIRMED.

## PLAN_REALITY rows

REALITY: premise-table pass the loop's dependency chain (patch -> QEMU -> image -> boot -> inject -> readback -> close) is stated and each link maps to a file; docs/PLAN-baseline-fix.md:70
REALITY: already-done pass six proven capabilities mapped to passing suites, incl test_cosim_control.py 34 and test_measurements.py 36; docs/reviews/ENG-baseline-fix.md:96
REALITY: surface-check finding the plan never names the duplicate-monitor surface; E-1 found it instead - two QemuMonitor classes and two cycle_adc_and_gate signatures; bridge/qemu_monitor.py:34 vs bridge/qemu_orchestrator.py:49
REALITY: binding-decisions pass the owner's D4 reversal is recorded and the canonical module is now named so links 6/7 cannot pick wrong; docs/PLAN-baseline-fix.md:118
REALITY: numbers pass 166 passed / 6 failed / 2 skipped / 3 files uncollectable, each traced to a named cause; docs/PLAN-baseline-fix.md:22
REALITY: deferred-asks pass the owner-gated patch is listed in TODOS.md as the single hard blocker; TODOS.md:38
REALITY: pr-count finding L0-L7 are all unwritten - zero of the eight new tests exist yet, which the plan states rather than implies; docs/reviews/ENG-baseline-fix.md:150

Prior-phase input carried forward:
- **CEO:** 4 premise challenges, 1 Critical (PC-1). Owner rejected the review's
  recommendation at the gate and directed all-in on the embedded half.
- **Design:** skipped, no UI scope detected.
- **DX:** skipped by owner instruction at D5 (run Eng directly).

---

## Step 0 — Scope challenge, grounded in code

The plan names `bridge/qemu_orchestrator.py` once, in link 5. Reading the code shows
that is where most of the loop actually lives, and that it has a duplicate.

### Finding E-1 (Critical) — two `QemuMonitor` classes with incompatible `cycle_adc_and_gate`

```
bridge/esp32_regs.py:75        def read_gate(client, pin)
bridge/qemu_monitor.py:24      class QemuMonitorError
bridge/qemu_monitor.py:34      class QemuMonitor
bridge/qemu_monitor.py:147     def cycle_adc_and_gate(qmp=None, adc_value=2012, qemu=None)
bridge/qemu_monitor.py:188     def sweep_report(qmp, adc_values)
bridge/qemu_orchestrator.py:49 class QemuMonitor
bridge/qemu_orchestrator.py:90 def cycle_adc_and_gate(session, adc_value=2012)
bridge/qemu_orchestrator.py:103 def sweep_report(session, adc_values)
```

Three gate readers and two monitor classes over the same QOM/HMP surface, with different
contracts:

| | `qemu_monitor.py` | `qemu_orchestrator.py` |
|---|---|---|
| Constructor | `QemuMonitor(qemu_path)` spawns via `subprocess.Popen` | `QemuMonitor(session)` wraps a session it does not own |
| Process field | `self._proc` | `session.client` |
| Cycle signature | `cycle_adc_and_gate(qmp=..., qemu=...)` keyword | `cycle_adc_and_gate(session, ...)` positional |
| Owns boot/UART | No | Yes (`boot_and_watch`, `probe_memory`, `-serial file:`) |

`qemu_orchestrator.py:116` re-imports the other module's names into its own namespace,
so both are reachable and neither is canonical.

This is not a cosmetic DRY hit. It is the direct cause of the three stale
`TestQemuGateBridge` failures: those tests were written against the orchestrator's
`session` design while importing from `qemu_monitor`. **The plan's links 6 and 7 will
repeat exactly that mistake** unless the plan names which module is canonical.

**Disposition: TASTE DECISION, auto-decided (P5 explicit over clever).** Plan link 6 is
amended to name `bridge/qemu_orchestrator.py` as canonical for anything that boots a
guest, and to forbid a new monitor class. Deletion of the duplicate is deferred to
TODOS.md — it is outside the loop's critical path and re-landing it here would re-scope
the plan the owner just set.

### Finding E-2 (High) — `probe_memory()` is a second, undocumented read path

`qemu_orchestrator.py:15` states `probe_memory()` runs the guest under `accel=qtest`
purely to read memory, while `boot_and_watch()` runs under normal TCG. Two acceleration
modes means two timing behaviours. Plan link 9 (time-sync, five repeats) must state which
acceleration it measures, or the variation number is meaningless.

**Disposition: TASTE DECISION, auto-decided.** Link 9 amended to name `accel=qtest` for
the repeatability measurement and TCG for the boot/link-8 loop, and to report the two
separately.

### Finding E-3 (Medium) — the monitor binds TCP

`qemu_orchestrator.py:204` launches `-monitor tcp:127.0.0.1:%d,server=on,wait=off`. The
bind is loopback-only, which is correct. Worth recording because a future edit that
widens it to `0.0.0.0` would expose an unauthenticated guest control surface.

**Disposition: no change; recorded in the failure-modes registry below.**

### Complexity check

The plan adds no new module, class or abstraction. Every link is a test against code
that already exists (`qemu_orchestrator.py`, `qemu_monitor.py`, `control_law.py`). No
link requires more than one file of new logic. Complexity is acceptable.

---

## NOT in scope

| Deferred | Rationale |
|---|---|
| Deleting the duplicate `QemuMonitor`/`cycle_adc_and_gate` | Real debt (E-1), but outside the loop's critical path; re-landing it re-scopes the plan the owner just set |
| pyqtgraph segfault, 146 uncollectable UI tests | Orthogonal; embedded tests do not import pyqtgraph |
| Widening the runner fix beyond the exit-code gate | In blast radius only as far as embedded results must be believed |
| CI, pilot packaging | Not required to demonstrate a closed loop |

## What already exists

| Loop link | Existing code | Test standing by |
|---|---|---|
| Boot + UART sentinel | `qemu_orchestrator.py::boot_and_watch`, `BOOT_SENTINEL` lines from `main.c` | none — link 5 writes it |
| Memory probe | `qemu_orchestrator.py::probe_memory` (`accel=qtest`) | none |
| ADC injection | `qemu_monitor.py::set_adc1_value` / `qemu_orchestrator.py::QemuMonitor.set_adc1_value` | `test_qemu_monitor_qemu.py` (2 skipped) |
| Gate readback | `read_gate()` at `xp /1wx 0x3FF44004`; third impl in `esp32_regs.py:75` | `test_qemu_monitor_qemu.py` (2 skipped) |
| Counts mapping | `bridge/control_law.py::_to_counts`, thresholds read from `main.c` | `test_cosim_control.py` (34 passed) |
| Solver source driving | `bridge/ngspice_wrapper.py` `set_vsrc_callback` for `external` sources | `test_ngspice_bridge.py` (passed) |

---

## Section 1 — Architecture (new vs existing)

```
                       EXISTING (proven today)
  +-------------------------------------------------------------+
  | bridge/ngspice_wrapper.py   real libngspice, GetVSRCData     |
  | bridge/control_law.py       counts <-> volts, firmware pins  |
  | bridge/firmware.py          ELF/HEX parse, SHA-256           |
  +-------------------------------------------------------------+
                               |
                               | set_vsrc_callback (link 8 only)
                               v
                       NEW FOR THIS PLAN (tests + one env var)
  +-------------------------------------------------------------+
  | tools/run_tests.py  [P0] gate on pytest exit code            |
  | WOSP_QEMU           [P1] env var, set by build_qemu.sh       |
  +-------------------------------------------------------------+
                               |
              +----------------+------------------+
              v                                   v
  +-------------------------------+   +-------------------------------+
  | qemu_orchestrator.py  CANONICAL|   | qemu_monitor.py   DUPLICATE   |
  |  boot_and_watch (TCG)          |   |  QemuMonitor(qemu_path)       |
  |  probe_memory (qtest)          |   |  cycle_adc_and_gate(qmp=...)  |
  |  QemuMonitor(session)          |   |  sweep_report(qmp, ...)       |
  |  cycle_adc_and_gate(session,..)|   +-------------------------------+
  |  sweep_report(session, ...)    |            ^ link 6/7 MUST NOT use
  +-------------------------------+
              |
              |  -serial file:uart.log   -monitor tcp:127.0.0.1:<free>
              v
  +-------------------------------------------------------------+
  | qemu-system-xtensa (patched esp32_sens)  [MISSING — owner]    |
  | firmware.elf / app.bin                  [MISSING — build]    |
  +-------------------------------------------------------------+
```

Coupling: the plan adds zero coupling. It points existing call sites at the canonical
module and writes tests. Security: the only new attack surface is the QEMU monitor TCP
socket, already loopback-bound (E-3). Scaling: irrelevant, this is a single-guest harness.

## Section 2 — Code quality

One DRY violation with a reliability cost (E-1, above). Naming is otherwise consistent.
`bridge/qemu_orchestrator.py:116` importing `qemu_monitor`'s names into its own namespace
is the specific smell that makes both reachable; flagging, not fixing, since deletion is
deferred. No catch-alls found in the loop path; `sweep_report` at
`qemu_monitor.py:188` does use a bare `except Exception`, but it converts to a clean
failure row by contract, and that contract is asserted.

## Section 3 — Test diagram (codepath → coverage)

| # | New codepath / flow | Type of test needed | Exists today? | Gap |
|---|---|---|---|---|
| L0 | Runner exits non-zero on failed collection | Unit, forces a collection error | **No** | P0 must write it |
| L1 | `build_qemu.sh` applies patch, binary passes its own tail check | Build gate, asserts `-machine help` lists `esp32_sens` | **No** | P1 |
| L2 | Firmware links to `firmware.elf` | `TestRealEsp32Firmware` (4 tests) | Written, **skips** | Unblocks when the image exists |
| L3 | Boot to `app_main`, UART sentinel matches `BOOT_SENTINEL` | Contract test | **No** | Link 5 |
| L4 | `qom-set adc1-value N` changes firmware Raw ADC | Contract test, ≥3 distinct N | **No** | Link 6 |
| L5 | Gate flips at 1995 / 2030 with firmware branch order quoted | Contract test, sweep | **No** | Link 7 |
| L6 | Full loop closes, no manual step, trace self-consistent | End-to-end, prints first 20 rows | **No** | Link 8 |
| L7 | Same sequence 5× reports variation | Repeatability, `accel=qtest` | **No** | Link 9 |
| L8 | Error shapes (no binary, dead process, drop) | Unit, doubles allowed | `test_qemu_monitor_unit.py` | 1 stale assertion, P0 |
| L9 | Sanitiser rejects marker-file netlist | Contract, real libngspice | `test_ngspice_dll_proof.py` (3 passed) | None |

**Test-gap auto-decisions (P1, all relevant suites):** every gap L0–L7 is written as
part of the plan rather than deferred, because a loop claim with no test is exactly the
failure mode this project has repeated. Doubles are permitted only for L8; L3–L7 must run
against the real binary or report skip with the missing prerequisite named.

Test plan artifact:
`~/.gstack/projects/Iceandlava124-WOSP/user-baseline-fix-eng-review-test-plan-<datetime>.md`

## Section 4 — Performance

No N+1, no caching, no hot path. Two measurements are required and neither exists:
the QEMU build wall-clock time (P1 should detach it and log, since an Espressif QEMU
build exceeds a foreground turn) and the repeatability spread (link 9). `probe_memory`
under `accel=qtest` is deliberately slower than TCG and must not be reported as a
loop timing.

## Failure Modes Registry

| # | Failure mode | Sev | Flag | Plan's answer |
|---|---|---|---|---|
| G1 | Link 6/7 written against the wrong `QemuMonitor` | **Critical** | **GAP** | E-1 names the canonical module |
| G2 | Patch applies but `esp32_sens` absent; build still exits 0 | High | — | Assert the build's own `-machine help` check, not the exit code |
| G3 | `probe_memory` (qtest) timing reported as loop timing | High | — | E-2: report the two acceleration modes separately |
| G4 | Skip counted as pass anywhere in L3–L7 | High | — | Skip reason names the missing binary; binary presence checked first |
| G5 | Gate threshold test widened to pass | High | — | Quote `main.c` branch order beside the assertion |
| G6 | QEMU monitor TCP widened off loopback | Medium | — | E-3 recorded; assert the bind stays `127.0.0.1` |
| G7 | Long QEMU build dies with the foreground turn | Medium | — | Detach, log to file, poll for the binary |

## Completion Summary

| Area | Status |
|---|---|
| Architecture sound | Yes, once E-1 is answered; the plan as written would have picked the wrong module |
| Test coverage sufficient | Not yet — L0–L7 are all unwritten; the plan correctly treats them as the work |
| Performance risks addressed | Partially; both required measurements are new |
| Security threats covered | Yes; one loopback TCP surface, recorded |
| Error paths handled | Yes for existing code; L3–L7 have no error paths yet |
| Deployment risk | The loop cannot deploy; its binary does not exist |

## ENG DUAL VOICES — CONSENSUS TABLE

```
  Dimension                            Claude  Codex  Consensus
  1. Architecture sound?               —       N/A    N/A
  2. Test coverage sufficient?         —       N/A    N/A
  3. Performance risks addressed?      —       N/A    N/A
  4. Security threats covered?         —       N/A    N/A
  5. Error paths handled?              —       N/A    N/A
  6. Deployment risk manageable?       —       N/A    N/A
```

`outside_status: unavailable`. Single-reviewer mode. Single-voice critical to watch:
**E-1** — the canonical-module ambiguity is the finding most likely to cost a real cycle.
