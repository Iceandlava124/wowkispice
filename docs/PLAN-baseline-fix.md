# Plan — baseline-fix: prove the co-simulation loop

Branch: `baseline-fix` (from `9d6c797`)
Measured on: Windows 11, `.venv` CPython 3.12.10, PyQt5 5.15.9, pyqtgraph 0.13.3,
numpy 1.26.4, pytest 8.2.2, pytest-timeout 2.3.1.

**Direction set by the owner at the Phase 4 gate (D4): "All-in on the embedded half."**
This supersedes the review's recommendation. The test-harness work that previously led
this plan is demoted to a single prerequisite, because a runner that exits 0 on a failed
collection cannot be trusted to report an embedded result.

---

## Problem statement

The project claims a real ESP32 firmware, running in patched QEMU, closes a control loop
with a real SPICE solver. Nothing has ever demonstrated that. `docs/architecture.md`
says it outright: the QEMU track has "zero bi-directional coupling to ngspice today".

This plan exists to make that loop run end to end, and to say precisely which link of it
is proven. It does not start from a wish to make numbers go up; it starts from the
observation that the loop has eight tasks of deferral behind it and no measurement.

---

## Measured state of the embedded path

Probed on this box, this session:

```
$ command -v qemu-system-xtensa qemu-system-xtensa.exe
(no output — no binary anywhere)

$ git ls-files tools/qemu-patch
(no output — the patch is not in git)

$ echo "${WOSP_QEMU:-unset}"
unset

$ ls firmware/esp32_buck_controller/.pio/build/esp32dev/*.elf *.bin
bootloader.bin   26176 bytes
bootloader.elf  494980 bytes
partitions.bin    3072 bytes

$ ls firmware/esp32_buck_controller/.pio/build/esp32dev/CMakeFiles/*.dir/*.o
(no output — zero application objects)

$ command -v pio platformio
/c/Users/gudae/.platformio/penv/Scripts/pio
```

Three facts follow, and they set the whole plan's shape:

1. **No QEMU binary exists on this machine.** `tools/build_qemu.sh` would build one from
   `espressif/qemu` at pin tag `esp-develop-9.2.2-20260417`, but it applies
   `tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch`, which is not in
   the repo and not derivable from it. The script cannot run as written.
2. **The firmware never linked.** Only the bootloader and partition table were produced;
   zero application object files. `pio` is installed and working, so this is a build that
   stalled, not a missing toolchain.
3. **`WOSP_QEMU` is unset**, so every QEMU-marked test skips by design.

The loop's dependency chain is therefore: patch → QEMU binary → firmware image → boot →
ADC injection → gate readback → close with ngspice. Nothing below can start until the
link above it exists.

---

## What already works (the half that is proven)

| Capability | Code | Evidence today |
|---|---|---|
| Real SPICE solving | `bridge/ngspice_wrapper.py` | `test_ngspice_bridge.py` 1 passed, `test_ngspice_dll_proof.py` 3 passed, `test_measurements.py` 36 passed, `test_parameter_sweeps.py` 2 passed, `test_closed_loop_buck.py` 3 passed, `test_industrial_verification.py` 5 passed |
| Firmware-truthful control law | `bridge/control_law.py` reads thresholds from `main.c` | `test_cosim_control.py` 34 passed |
| QOM/HMP command contract | `bridge/qemu_monitor.py` `qom-set /machine/peripheral/sens adc1-value N`, `xp /1wx 0x3FF44004` | `test_qemu_monitor_unit.py` (1 stale assertion, P0) |
| Firmware image parsing | `bridge/firmware.py` | `test_firmware_gpio.py` `TestElf` green; `TestRealEsp32Firmware` skips because `firmware.elf` does not exist |
| Real-QEMU contract test | `tests/test_qemu_monitor_qemu.py` | 2 skipped, reason names the missing binary |

The last two rows are the ones this plan turns into passes. They are written, waiting,
and skip only because their binary is absent.

---

## NOT in scope

| Deferred | Rationale |
|---|---|
| pyqtgraph segfault (3 crashing UI test files, ~146 tests) | Orthogonal to the loop. The embedded tests do not import pyqtgraph. Recorded, not fixed — see TODOS.md |
| Test-harness honesty, beyond the one-line runner fix | In blast radius only to the extent that embedded results must be believed |
| CI runners, pilot packaging, docs polish | Not required to demonstrate a closed loop |
| Matching real silicon | No test here measures hardware. Nothing may claim it |

---

## The work

Each step names whether it is **verifiable on this box** or **owner-gated**. No step
counts as done on a skip.

### P0 — unblock the two hard prerequisites

1. **Recover the QEMU patch.** `tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch`
   is owner-held. Either commit it or add a documented fetch step to
   `docs/toolchain.md` §1. **Owner-gated.** Everything below waits on this.
   Verification: `git ls-files tools/qemu-patch` is non-empty, or the documented fetch
   produces a byte-identical file whose sha256 is recorded.

2. **Make `tools/run_tests.py` tell the truth.** It currently invokes bare `python`
   (MSYS2 CPython 3.14, no PyQt5) and exits 0 on a failed collection because it greps
   summary lines instead of reading pytest's exit code. Run `.venv`, gate on the exit
   code, exit non-zero on collection errors. **Verifiable here.**
   Verification: force a collection error, confirm non-zero exit and an accurate printed
   count. This is the one harness item kept, because an embedded result reported by a
   lying runner is not a result.

### P1 — build the two binaries

3. **Build QEMU.** Run `tools/build_qemu.sh` once the patch exists. Its own tail
   verification must pass: `--version` prints, and `-machine help` lists `esp32_sens`.
   Then `export WOSP_QEMU=$(pwd)/tools/build/qemu-system-xtensa`. **Verifiable here**
   once step 1 lands, though a full Espressif QEMU build is long-running and should be
   detached rather than run in a foreground turn.

4. **Make the firmware link.** `pio` is installed; the build produced a bootloader and
   partitions but zero application objects. Raise or parameterise the gate timeout that
   `docs/toolchain.md` §6 documents, rebuild, and confirm `firmware.elf` and
   `app.bin` appear. **Verifiable here.**
   Verification: `test_firmware_gpio.py::TestRealEsp32Firmware` stops skipping. That
   test already asserts Xtensa machine, a plausible entry point inside `.iram0.text`,
   and section addresses that are memory addresses rather than file offsets.

### P2 — the loop, one link at a time

Each link gets its own test and its own pass condition. No link inherits confidence
from the one before it.

5. **Boot.** Firmware boots under patched QEMU to `app_main`. Assert on the UART boot
   markers `bridge/qemu_orchestrator.py` already reads. **Verifiable here** once P1 lands.
6. **ADC injection changes firmware state.** `qom-set ... adc1-value N` moves the
   firmware's Raw ADC output. Assert the output for at least three distinct N.
   **Use `bridge/qemu_orchestrator.py` as the canonical monitor for anything that boots
   a guest** (Eng finding E-1): `bridge/qemu_monitor.py` holds a second, incompatible
   `QemuMonitor` and `cycle_adc_and_gate(qmp=...)` whose positional/keyword mismatch is
   the direct cause of the three stale `TestQemuGateBridge` failures. Do not write a
   third monitor class; do not import from `qemu_monitor` here.
7. **Gate flips at the firmware's real thresholds.** Sweep across 1995 and 2030 and
   assert the transitions. The firmware source is the contract — quote the branch order
   beside the assertion, do not widen it to make a test pass.
8. **Close the loop.** ngspice voltage → `control_law` counts → `qom-set` → gate readback
   → ngspice source, with no manual step. This is the first time the project's headline
   claim would be true. Print the first 20 rows of the trace and assert self-consistency,
   not just absence of exceptions.

### P3 — make it repeatable

9. **Time-sync.** `docs/time-sync.md` documents a golden-trace mechanism that is not
   implemented in any versioned format. Implement it, then run the same injection
   sequence five times and report the observed variation rather than asserting
   determinism. **Measure the two acceleration modes separately** (Eng finding E-2):
   `probe_memory()` runs under `accel=qtest` and `boot_and_watch()` under TCG, so their
   timings are not comparable and must never be mixed into one number.

---

## Failure modes this plan must not introduce

| Risk | Mitigation |
|---|---|
| QEMU builds but `esp32_sens` is absent because the patch silently failed to apply | The build script's own tail verification fails the build; assert it, do not trust the exit code alone |
| A skip is reported as a pass anywhere in P2 | Every link's test names its missing prerequisite in the skip reason; `git status` of the binary is checked before the count |
| The gate threshold test is "fixed" by loosening it | Firmware `main.c` branch order is quoted beside the assertion; the assertion moves to match the code, never the other way |
| The loop appears to close because a double stands in for QEMU | `tests/test_qemu_monitor_qemu.py` is the only test allowed to claim a pass on the loop; doubles cover error shapes only |
| The long QEMU build dies with the foreground turn | Detach it, log to a file, poll for the binary |

---

## Completion criteria

- `tools/qemu-patch/` is in git, or a documented fetch reproduces it byte-identically.
- `qemu-system-xtensa` runs, and `-machine help` lists `esp32_sens`.
- `firmware.elf` exists and `TestRealEsp32Firmware` passes instead of skipping.
- Every P2 link has a test that executed against the real binary.
- Link 8 closes with no manual step, and its trace is printed.
- `tools/run_tests.py` exits non-zero when anything is actually wrong.
- The pyqtgraph segfault stays recorded as UNVERIFIED, not quietly forgotten.

---

## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| 1 | ceo | Rewrite P0 task 1 as three bounded experiments with a stop condition | Taste | P5 explicit over clever | "Fix or pin" is an open investigation with no stopping rule | Unbounded bisect-first approach |
| 2 | ceo | Fix the P0 target as collect-and-run, not skip | Taste | P1 completeness | Trading 146 crashes for 146 skips makes the number worse and invites reverting the fix | Accepting skips as a landing |
| 3 | ceo | Keep QEMU work explicitly gated on the missing binary rather than pretending it can run | Mechanical | P6 pragmatic | No `qemu-system-xtensa` exists on this box | Scheduling work that cannot execute |
| 4 | gate | **Owner rejected the review's recommendation and chose "All-in on the embedded half"** | User Challenge, accepted | — | Owner's call; the loop is the product | Simulation-only pilot (review's recommendation, 6/10 completeness) |
| 5 | plan | Demote the pyqtgraph/harness work to one prerequisite instead of cutting it entirely | Mechanical | P2 blast radius | A runner that exits 0 on a failed collection cannot be trusted to report an embedded result | Cutting P0 entirely |
| 6 | eng | Name `bridge/qemu_orchestrator.py` canonical for loop links 6 and 7 | Taste | P5 explicit over clever | Two `QemuMonitor` classes with incompatible `cycle_adc_and_gate` signatures; the mismatch already produced three stale tests | Deleting the duplicate now (deferred to TODOS.md, outside the critical path) |
| 7 | eng | Report qtest and TCG timings separately in link 9 | Taste | P5 explicit over clever | `probe_memory` and `boot_and_watch` use different acceleration; one number would be meaningless | A single blended timing figure |
| 8 | eng | Write L0–L7 as part of the plan rather than deferring any | Mechanical | P1 completeness | A loop claim with no test is the exact failure mode this project has repeated | Deferring test gaps |

---

## GSTACK REVIEW REPORT

**Phase 3 (Eng) — complete, single-model.** Outside provider unavailable
(`CODEX_MODE: not_installed`); no adversarial subagent on this host. All six consensus
cells N/A, none CONFIRMED. Review record:
[docs/reviews/ENG-baseline-fix.md](reviews/ENG-baseline-fix.md).
Test plan artifact:
`~/.gstack/projects/Iceandlava124-WOSP/user-baseline-fix-eng-review-test-plan-20261024-192500.md`
Deferred scope ledger: [TODOS.md](../TODOS.md).

One Critical engineering finding: **E-1**, two `QemuMonitor` classes and two
`cycle_adc_and_gate` functions with incompatible signatures across
`bridge/qemu_monitor.py` and `bridge/qemu_orchestrator.py`, with a third gate reader at
`bridge/esp32_regs.py:75`. That divergence is why the three `TestQemuGateBridge` tests
went stale, and it would have made links 6 and 7 pick the wrong module. Auto-decided by
naming the canonical module in the plan; the deletion is deferred.

Two High findings folded into the plan: E-2 (qtest and TCG timings must be reported
separately), and the build gate must assert `-machine help` lists `esp32_sens` rather
than trusting the build's exit code.

Auto-decisions across all phases: 5. Taste decisions: 4. User Challenges: 1 (PC-1,
raised at the gate, owner rejected the review's recommendation).

**Phases run: 1 (CEO), 3 (Eng). Phases skipped: 2 (Design, no UI scope detected),
2.5 (DX, skipped by owner at D5).**
