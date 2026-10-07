# WOSP Systems Map

**Date:** 2026-10-04 · **Scope:** the repository as it exists at commit `60b308c`.
**Purpose:** a map for understanding, not a task list. Read the flags literally.

## How to read this

Every item carries exactly one of four states. They are not interchangeable and
the distinctions are the whole point of this document.

| Flag | Means |
|---|---|
| **CONFIRMED WORKING** | A test in `tools/run_tests.py` exercises it and passes, or a measurement in this repo's history demonstrates it. Evidence cited. |
| **CONFIRMED BROKEN** | A test fails, or a measurement demonstrates the failure. Evidence cited. |
| **UNVERIFIED** | No test, no measurement. Plausible, but nobody has shown it. Stated as UNVERIFIED even when it is probably fine. |
| **LATENT RISK** | Works today. Fragile: coupled to global state, silently degrades, or fails in a way that produces no obvious symptom. |

A claim of "probably fine" is UNVERIFIED, not CONFIRMED WORKING.

Baseline: `python tools/run_tests.py` -> **257 tests, 15 suites, exit 0**
(verified repeatedly this session). Any claim below about test coverage refers
to that run.

## Third-party material

WOSP is **Apache-2.0** (`LICENSE`). Two other projects were consulted, and the
difference between them is a licence-compatibility fact, not a judgement call.

| Project | Licence | How it may be used here |
|---|---|---|
| Qucs-S (installed at `C:\Program Files\Qucs-S`) | `GPL-2.0-or-later` (declared in its own `share/metainfo/io.github.ra3xdh.qucs_s.metainfo.xml`) | **Read and study freely.** Architectures, file-format handling, and UI grammar may be imitated. **Code may not be copied into this repo** — GPL-2.0-or-later code cannot live in an Apache-2.0 work; combining them would force this repo to GPL-2.0-or-later. |
| LTspice (installed at `C:\Program Files\ADI\LTspice`) | proprietary EULA, no reverse-engineering clause for the binary | **No code may be read, decompiled, or copied.** Screenshots are not its code, but they are ADI's copyrighted images, so `docs/ltspice-reference/` is a **local, gitignored** reference only and must never be committed or redistributed. |

What is and is not protected here is worth stating precisely, because the
distinction decides what this project may keep doing:

- **Not copyrightable, and fair to imitate:** interaction patterns. Pane layout,
  where the palette sits, letter-key shortcuts, click-to-rotate, right-click to
  edit a value, schematic-plus-waveform-plus-console. These are functional
  grammar, shared by KiCad, Eagle, Altium and every SPICE tool, and that sharing
  predates LTspice by decades. The two law conflicts found this session (the `A`
  and `N` hotkeys) are collisions of exactly this kind, and resolving them
  toward LTspice's meanings is not a copying problem.
- **Copyrightable, and therefore avoided:** the icon artwork. Every symbol is
  drawn as a `QPainterPath` at runtime from our own geometry in
  `ui/schematic_symbols.py`; no third-party image or SVG was imported.

**Enforcement in the repo, not just intent.** `.gitignore` excludes
`docs/ltspice-reference/` and `docs/qucs-reference/`, so the vendor screenshots
cannot be committed by accident even during a broad `git add`. The one test that
consumes them, `TestLtspiceControl` in `tests/test_ui_parity.py`, skips with an
explicit reason when they are absent — verified by moving the directory aside
(11 pass, 1 skip, exit 0). That test is therefore a **local-only calibration**:
it pins why `tools/ui_parity.py` is not an LTspice-similarity score, and it will
skip in CI. The repository retains no third-party images.

---

# LAYER 1 — SUBSYSTEMS IN ISOLATION

## 1. ngspice engine — `bridge/ngspice_wrapper.py` (406 LOC)

**What it does.** `ctypes` binding to `libngspice`. Resolves the library in a
fixed order: explicit argument, `$WOSP_NGSPICE_LIB`, the bundled Windows
`tools/ngspice_dll/`, then `ctypes.util.find_library`. Wraps the C callbacks
`GetVSRCData` (external-source evaluation), `GetSyncData` (timestep) and
`SendData` (telemetry), plus `request_stop()`, vector reads, and complex-vector
access.

**How verified.** `tests/test_ngspice_bridge.py` (1 test) is a live
ctypes sanity check. `tests/test_components_library.py` (2),
`test_measurements.py` (29), `test_parameter_sweeps.py` (2),
`test_firmware_gpio.py` (28) and `test_editor_workflow.py` (36) all drive
simulations through it. **CONFIRMED WORKING.**

**Failure points.**
- **LATENT RISK — `sharedspice` is a process-wide singleton.**
  `cosim_runner.run_cosim` deliberately never calls `quit`, with the comment
  *"sharedspice is a process-wide singleton and quitting it breaks every later
  NgSpiceEngine in this process."* Any future `quit` call is a cross-module
  landmine. `tools/run_tests.py` already runs each suite in its own process,
  partly for this reason; that isolation hides the problem inside a suite that
  creates several engines.
- **LATENT RISK — `request_stop()` works by injecting a debugger breakpoint**
  (`_issue()` at line 298) and flagging `_stop_requested`. It is a control-flow
  hack into the solver, not an API.
- **UNVERIFIED** — behaviour when the resolved library is a different ngspice
  build than the one the struct definitions were written against. The struct
  layouts in `sharedspice.h` are transcribed by hand.

## 2. Schematic editor / UI — `ui/` (~4,471 LOC)

`ui/schematic_editor.py` (2,927) is the main window: palette, canvas, menus,
part hotkeys, control-law import, the run button. `ui/schematic_scene.py` (490)
holds the graphics scene and edit operations. `ui/schematic_items.py` (397)
draws symbols. `ui/schematic_symbols.py` (211) is a pure-data symbol library
with no Qt import, so it can be validated headlessly. `ui/theme.py` (447) and
`ui/icons.py` (345) are presentation.

**How verified.** `test_ui_polish.py` (47), `test_editor_workflow.py` (36),
`test_schematic_editor.py` (28), `test_ui_parity.py` (12). **CONFIRMED
WORKING.**

**Failure points.**
- **FIXED THIS SESSION — the canvas used to measure 97 px wide.** It was a real
  layout fault, not an offscreen artifact. `win.view.width()` returned 97 inside
  a 1,329 px splitter pane. Cause: the Bode tab's controls sat in one
  unshrinkable `QHBoxLayout` (1227 px minimum, mostly two `QDoubleSpinBox`
  hints that size to their range text); `QTabWidget` passes the widest page's
  `minimumSizeHint` to the `QSplitter`, and a splitter honours the minimum over
  its stretch factors, so `setStretchFactor(0, 3)` did nothing. Fixed by moving
  the controls into a `QScrollArea` on a page with
  `QLayout.SetNoConstraint`, plus `view.setMinimumWidth(420)`. Canvas is now
  681 px of a 1,329 px pane (51%, tracking the 3:2 stretch) and scales with the
  window. Pinned by `TestCanvasShare` (5 tests) in `test_ui_polish.py`, each of
  which fails against the original code (canvas 71 px = 4%).
- **KNOWN CONSEQUENCE — the reference screenshots now exercise a real canvas.**
  `docs/editor-*.png` were regenerated, which invalidated a parity calibration
  that had been taken against an almost-chrome-only window. `tools/ui_parity.py`
  cut at the 1st luminance percentile, which sat inside the light theme's dark
  ink tail and inverted its range (221) against the dark theme's (35). The cut
  is now the 5th percentile; measured sweep in the module docstring, unrelated
  control unchanged at 8.8.
- **LATENT RISK — the editor is the only place that wires the closed loop.**
  `ui/schematic_editor.py:2765` calls `cosim_runner.run_cosim`. Nothing else
  does. If `cosim_runner` changes signature, the UI is the only signal.
- **UNVERIFIED** — the whole-window screenshots in `docs/` are not regenerated
  by any test. They can silently go stale. This is exactly how the parity
  mismatch above was caught only by hand.

## 3. ELF / firmware image parsing — `bridge/firmware.py` (278 LOC)

**What it does.** Parses `.hex` (Intel HEX) and `.elf` (real Xtensa section
headers): payload, load address, entry point, section names, machine, SHA-256,
and a declared pin profile. Defensive by design — malformed input raises
`FirmwareParseError` with a human-readable reason.

**How verified.** `tests/test_firmware_gpio.py` (28 tests) calls
`parse_intel_hex`, `parse_elf` and `parse_pin_profile`, including a truncated
ELF and a real compiled image when present.
`tools/verify_elf_sections.py` cross-checks sections against Xtensa readelf.
**CONFIRMED WORKING** (parsing only).

**Failure points.**
- **CONFIRMED: it does not execute the firmware.** This is documented and
  intended, not a defect. Its docstring now says so explicitly.
- **UNVERIFIED** — anything downstream of parsing. Nothing consumes the parsed
  section data in a control path.

## 4. Firmware — `firmware/esp32_buck_controller/src/main.c`

**What it does.** ESP-IDF application built by PlatformIO
(`platform = espressif32`, `framework = espidf`, board `esp32dev`). Real
hysteretic buck controller. Constants that matter:

```c
#define GATE_PIN            GPIO_NUM_18
#define ADC_CHANNEL         ADC_CHANNEL_0   // GPIO 36 / ADC1_CH0
#define ADC_OVERSAMPLE_N    16
#define ADC_LOW_THRESHOLD   1995
#define ADC_HIGH_THRESHOLD  2030
```

It configures `adc_oneshot`, sets up **ADC calibration**
(`adc_cali_scheme_line_fitting`), reads with oversampling, averages
`sum / samples_ok`, and drives the gate on the 1995/2030 comparison.

**Build artifacts present** at `.pio/build/esp32dev/`: `firmware.elf` (3.1 MB),
`firmware.bin`, `bootloader.bin`, `partitions.bin`, and a merged
`qemu_flash.bin` (4 MB).

**How verified.**
- Compiles and links: **CONFIRMED WORKING** (artifacts on disk).
- Boots in QEMU to `app_main()`: **CONFIRMED WORKING** — the two
  `BOOT_MARKERS` (`BUCK_CTRL: Starting ESP32 Buck Converter Closed-Loop
  Controller`, `...Entering high-speed hysteretic control loop`) reach the UART;
  5 ROM boots, 5 `app_main()` entries.
- Past `app_main()` under **stock** QEMU: was **CONFIRMED BROKEN.** `SENS` is
  one of ~24 `unimplemented-device` stubs that decode MMIO and discard writes,
  so the firmware spun at `while (!adc_oneshot_ll_get_event(...))` in
  `adc_oneshot_hal.c:155` and the interrupt watchdog tripped. Measured then:
  4 watchdog panics / 45 s, **0 control-loop samples**.
- Past `app_main()` under the **patched** QEMU (built 2026-10-07, §8):
  **CONFIRMED WORKING.** A 90 s run prints **900 000 control-loop samples**
  (`BUCK_CTRL: Loop: … | Raw ADC: … | Gate: …`) with **zero panics** — the
  fatal `Interrupt wdt timeout` never occurs. Residual `task_wdt` warnings
  are non-fatal (IDLE0 starved by the busy loop; the guest keeps running).
- Responds to host-injected analog values: **CONFIRMED WORKING, by
  measurement.** With `-monitor tcp:127.0.0.1:4444`,
  `qom-set /machine/peripheral/sens adc1-value 2012` changes the printed
  `Raw ADC` from 0 to 2012 on the following loop lines (25 observed), and
  raising it to **3456 flips the gate `ON → OFF`** (16 lines) — the
  firmware's own 1995/2030 hysteresis reacting to injected input.

**Failure points.**
- **CONFIRMED BROKEN under stock QEMU** — the ADC read never returns there.
  The patched build is now the one to run; the stock binary still exhibits it.
- **LATENT RISK** — feeding `adc1-value` is a manual monitor command;
  nothing in this repository drives it (orchestrator wiring is a deliberately
  separate, not-yet-started task).
- **UNVERIFIED** — the 1995/2030 thresholds are uncalibrated against real
  hardware. No ESP32 board has been involved. `ADC_OVERSAMPLE_N 16` and the
  line-fitting calibration scheme have never run on silicon.

## 5. Control law / closed loop — `bridge/control_law.py` (447) + `bridge/cosim_runner.py` (306)

**This is the real closed loop, and it is a different implementation from
`mock_controller.py`.** See item 6.

**What it does.** `control_law.py` normalises a law spec, quantises a sense
node into ADC counts (`to_counts`, clipped), and decides: hysteretic
(bang-bang with a hold band) or PWM. `cosim_runner.py` compiles the netlist
from a CAD model, builds the laws, installs a `GetVSRCData` callback that
reads the sense net straight out of ngspice's C buffer, and runs.

Key design: `sense()` calls `ngGet_Vec_Info` and reads
`info.v_realdata[length-1]` rather than `get_vector_array()`, because the
latter copies the whole vector on each of tens of thousands of callbacks,
making the loop O(n^2).

It also scrapes constants out of the real C source
(`read_firmware_constants`) using a `#define` regex over the aliases
`ADC_LOW_THRESHOLD`, `ADC_HIGH_THRESHOLD`, `GATE_PIN`.

**How verified.** `tests/test_cosim_control.py` (23 tests) covers spec
normalisation, rejection of bad specs, count conversion, firmware-constant
extraction (asserting `low_counts == 1995`, `high_counts == 2030`), round-trip
save/load, and real `run_cosim` executions including the failure paths.
`tests/test_schematic_editor.py` covers the UI path that calls it.
**CONFIRMED WORKING.**

**Failure points.**
- **LATENT RISK — the firmware scrape is partial and can silently drift.**
  `read_firmware_constants` reads three `#define`s. It does **not** read
  `ADC_OVERSAMPLE_N` (16) or the ADC calibration scheme. The real firmware
  averages 16 samples and applies line-fitting calibration before comparing;
  `control_law` compares a single instantaneous count against `vref`. The
  modelled controller is therefore *not* the firmware's controller. Nothing
  detects this: both read the same file and neither cross-checks. See Layer 2.5.
- **LATENT RISK — `run_cosim` swallows exceptions.** The main body is wrapped in
  `try/except Exception` that appends `"closed-loop run failed: ..."` to
  `run.warnings`. A caller that ignores `run.warnings` sees a tidy empty
  result instead of a failure.
- **UNVERIFIED** — behaviour with multiple MCUs driving one run. The pin
  back-mapping (`_pin_for_source`) is written for it and is not exercised by a
  multi-MCU test.

## 6. Mock controller — `bridge/mock_controller.py` (211 lines)

**A second, independent closed-loop implementation.** It runs
`circuits/buck_converter.cir` directly through `ngSpice_Init_Sync`, with its
own `on_vsrc` / `on_sync` callbacks and a `MockESP32BuckController`. It reads
the `fb` node from the solver, applies a 12-bit quantisation, and switches the
gate.

**This is not the loop the editor uses.** `docs/legacy-module-audit.md` and the
import graph agree: `cosim_runner` is wired into the UI; `mock_controller` is
only reachable from `renode_orchestrator.py` (misleading name), CI, and
`docker-compose.yml`.

**How verified.** `tests/test_closed_loop_buck.py` — **3 tests**
(`TestThresholdsMatchFirmware` x2, `TestClosedLoopBuck` x1).
**CONFIRMED WORKING**, but thinly covered.

**Failure points.**
- **LATENT RISK — module-global `engine`.** `run_closed_loop_simulation` does
  `global engine`, and both callbacks dereference that global
  (`engine.lib.ngGet_Vec_Info`). A second concurrent run, or any reentrancy,
  corrupts state silently. This is the defect the audit flagged and it is still
  unfixed.
- **LATENT RISK — bare `except Exception: pass` in `on_sync`,** and
  `except Exception: v_ret[0] = 0.0` in `on_vsrc`. A solver error becomes a
  silently wrong control decision rather than a failure.
- **RESOLVED 2026-10-04 — the two loops now agree exactly.** Both cross at the
  firmware's 1995/2030 counts. `mock_controller`'s defaults were derived from
  those constants rather than picked by hand (`target_vout=3.2436`,
  `hyst_vout=0.0282`), and `TestThresholdsMatchFirmware` asserts both counts so
  they cannot drift apart again.
- **LATENT RISK — aligning the band made the mock's ripple marginal.**
  Widening hysteresis from +/-12 to the firmware's true +/-17.5 counts raised
  peak-to-peak ripple to **293.3 mV against the test's 300 mV ceiling**: 2.2%
  margin. The assertion was tuned against the previous, incorrect narrower
  band. The test still passes; the limit was deliberately not widened, because
  whether 300 mV is the right ceiling is a judgement about the LC, not a
  consequence of this fix. **This is the one place the more accurate model made
  a margin worse.**
- **Verdict 2026-10-04: RETIRE the CI/compose entry point; KEEP the module and
  its tests.** See "Retire or reconcile?" below for the evidence.

## 6b. Retire or reconcile? — `mock_controller` and the CI path

**The question.** `mock_controller` duplicates what `control_law` +
`cosim_runner` already do. Should it be deleted, or kept and made consistent?

**Answer: retire the CI/compose *entry point*, keep the module and its tests.**
The two halves of the module and the entry point that reaches it have opposite
answers, and the divider work is what made the split obvious.

### The entry point is pure duplication

`cosim-ci.yml:58` runs
`python bridge/renode_orchestrator.py --mode benchmark`, and
`renode_orchestrator.py:50-57` shows that `mock` and `benchmark` both call
`run_closed_loop_simulation()` — the *same function*
`tests/test_closed_loop_buck.py:40` calls. And `tools/run_tests.py:61`
auto-discovers `test_*.py`, so the file that covers it is **already** run by
the CI step at line 44.

Measured, both paths, this session:

| Path | Ripple | Steps | Switches |
|---|---|---|---|
| CI command (line 58, 10 ms) | 293.2 mV | — | — |
| Test (line 40, 5 ms) | 293.3 mV | 10143 | 112 |

So CI line 58 re-runs a test the same workflow already ran, in the same job,
to produce a PNG. That is a 0.7 s solver run whose entire unique output is
`tests/ci_waveform.png`, uploaded by line 60-65 with a 7-day retention and
consumed by nothing in the repo. It is not "real coverage of that module" —
the coverage is line 44, which is unconditional and runs on the same trigger.

Two further reasons it is safe to drop rather than repair:
- `renode_orchestrator.py` is already self-declared deprecated: the `--mode renode`
  branch has never run this firmware (Renode cannot decode the Xtensa `entry`
  instruction). Retiring the CI step removes the *last* consumer of a file whose
  remaining modes are its only working ones.
- `studio_engine.py` does **not** use `mock_controller`, despite
  `overnight/05-gap-review.md:111` claiming it does. It drives its own
  `GetVSRCData_t` loop (L151). The overnight doc overstates the blast radius;
  verified against the source, not taken from the doc.

### Why the module stays

Deleting `mock_controller` is the one-way move, and the evidence says not to:
- Its 3 tests include `TestThresholdsMatchFirmware`, an **independent
  re-derivation** of the firmware's counts from `main.c` constants. That is a
  canary for precisely the class of bug this session hunted — a control law that
  is self-consistent and silently off by the divider ratio. Deleting the second
  implementation deletes the only thing that can notice the first one drifting.
- `cosim_runner` has **34** tests to its 3, but that asymmetry is the argument
  for *not spending new engineering on the loser*, not for deleting the
  cross-check.
- It costs nothing: it is 211 lines, already written, already green.

**What retiring does and does not mean.** It means deleting the step at
`cosim-ci.yml:56-58` and the `cosim-runner` service in `docker-compose.yml:4-17`.
It does not mean deleting `bridge/mock_controller.py`,
`tests/test_closed_loop_buck.py`, or the `--mode mock` branch.

**The honest cost.** Retiring drops a waveform artifact a human may have been
downloading from CI runs, and removes the only end-to-end "run the whole thing
from a shell" entry point that needs no Qt. The real path has no CLI
(`run_cosim` has no `__main__` and no plot output; its only callers are
`ui/schematic_editor.py:2811` and `tests/test_cosim_control.py`), so if a
headless artifact is wanted, the fix is a *new* small CLI over `cosim_runner`,
not a repoint of the existing one. That is new scope, not a repair.

**Not yet done.** This is a recommendation, not an applied change: the CI and
compose edits are one-way and affect a workflow that has never actually run, so
they wait on an explicit go-ahead.

## 7. QEMU orchestrator — `bridge/qemu_orchestrator.py` (252) + `bridge/qtest_client.py` (198) + `bridge/esp32_regs.py` (76)

**What it does.** `boot_and_watch()` runs the guest under TCG and reads the
console UART until the boot markers appear. `probe_memory()` runs under
`accel=qtest` to read/write guest memory.

The module is unusually honest about a distinction that is easy to get wrong:
**qtest does not execute the CPU.** QEMU wires the qtest accelerator to
`dummy_start_vcpu_thread`, so no vCPU thread exists; `clock_step` only advances
the virtual clock. Measured: 1.078 s of virtual time elapses, UART stays empty,
DRAM never changes, QEMU then blocks. `probe_memory()` is a memory poke tool,
and nothing in the module uses it to drive the guest.

**How verified.**
- `boot_and_watch()` reaching `app_main()`: **CONFIRMED WORKING** (markers on
  UART, 5 boots).
- `probe_memory()` showing which registers are observable: **CONFIRMED
  WORKING** as a probe; its own output is the evidence that `SENS` and GPIO
  writes do not round-trip — measured against **stock** QEMU; not re-run
  against the patched binary (**UNVERIFIED** for it).
- **Test coverage: zero.** `qemu_orchestrator.py`, `qtest_client.py` and
  `esp32_regs.py` are imported by no test file. Verification is manual and
  requires an external `qemu-system-xtensa` binary via `--qemu` / `$WOSP_QEMU`.
  **UNVERIFIED** as a module boundary.

**Failure points.**
- **UNVERIFIED** — `request_stop`/cleanup paths, qtest socket failure handling,
  and the `FileNotFoundError` branches are untested.
- **LATENT RISK** — logs go to `tempfile.gettempdir()` on purpose (drvfs refuses
  reads of a file another process holds open). That is a Windows-under-WSL
  workaround, not an abstraction, and will silently apply anywhere drvfs is
  mounted.

## 8. The QEMU ADC/GPIO patch — `tools/qemu-patch/` (528-line patch, 431 insertions / 4 deletions, 6 files)

**What it is.** A patch against `espressif/qemu` branch `esp-develop`, tag
`esp-develop-9.2.2-20260417` (the version PlatformIO pins). Six files: a new
`esp32_sens.h` / `esp32_sens.c` SAR ADC model, a `meson.build` entry,
instantiation in `hw/xtensa/esp32.c`, and W1TS/W1TC-latching output/enable
registers in the ESP32 GPIO model. Regenerated 2026-10-07 from the working
tree, so it also carries four fixes the original proposal lacked: the QEMU 9.2
`QEMUTimer` API (`timer_init` / `timer_mod(&…)`), `realized_set_allowed` on
the three injection properties (without it `qom-set` refuses writes after
realize), and a fixed QOM path
(`object_property_add_child(…, "/peripheral", "sens")`) so the device is
always addressable at `/machine/peripheral/sens` instead of a per-run
`/machine/unattached/device[N]` index.

**How verified.**
- Applies cleanly to a pristine export of the pinned commit: **CONFIRMED
  WORKING** (`patch -p1 --batch`, all six files, exit 0, no fuzz, no rejects).
- Compiles: **CONFIRMED WORKING** — native `./configure
  --target-list=xtensa-softmmu --disable-docs --disable-gtk --disable-sdl
  --disable-vnc --disable-spice --enable-slirp && ninja -C build` → exit 0,
  `build/qemu-system-xtensa` (QEMU 9.2.2, TCG).
- Boots and completes the control loop: **CONFIRMED WORKING** — 900 000
  samples / 90 s, zero panics (§4).
- Accepts host-injected ADC values at a stable path: **CONFIRMED WORKING** —
  `/machine/peripheral/sens` identical across two independent boots;
  end-to-end `qom-set` verified (Gate ON→OFF at 3456, §4).
- Reproducible from scratch: **CONFIRMED WORKING** — 2026-10-07, a fresh
  `git archive` export of the pinned commit + this patch + the documented
  configure line produced a clean configure and a clean full build (2493
  targets, exit 0), and that binary then booted the firmware, accepted
  `qom-set` at `/machine/peripheral/sens` (2012 → 3456), printed
  `Raw ADC: 2012` (30 lines) then `Raw ADC: 3456 | Gate: OFF` (16 lines),
  reached `app_main`, and logged **0 panics**.

**Not covered by anything automated.** No test in `tools/run_tests.py`
touches the QEMU build; verification is manual and needs the external binary.
`bridge/qemu_orchestrator.py` does not yet feed `adc1-value` — the automatic
ngspice ↔ QEMU bridge remains the unwritten step (Layer 2, §4).

## 9. Renode path — **abandoned**, 4 files

`bridge/renode_orchestrator.py` (86), `bridge/renode_adc_peripheral.py` (36),
`bridge/run_cosim.resc` (12), `bridge/esp32_buck.repl` (18).

**Why precisely, not vaguely.** Renode cannot decode the Xtensa `entry`
instruction, which occurs 393 times in an ordinary ESP-IDF build. It therefore
executed **zero instructions** of this firmware. The `--mode renode` branch
shells out to `tools/renode/renode.exe`, which is gitignored and has never been
run. **CONFIRMED BROKEN** by measurement, not inspection.

Two traps worth naming:
- `renode_orchestrator.py --mode benchmark` **never touches Renode**. It
  branches to `bridge/mock_controller.run_closed_loop_simulation`, a pure
  Python loop. The filename implies emulator coverage the mode never provided.
  Both CI and `docker-compose.yml` invoke only that mode.
- `renode_adc_peripheral.py` is not importable at all: it raises
  `NameError: name 'request' is not defined`, because `request` is injected by
  Renode's peripheral loader. It is a paste-in desktop-script fragment.

**CONFIRMED BROKEN / abandoned.** Retained deliberately as a record.

## 10. Additional subsystems you did not name

| Subsystem | LOC | Role | State |
|---|---|---|---|
| `bridge/cad_engine.py` | 712 | **The largest bridge module.** Component/pin graph, SPICE netlist compiler, MCU pin routing, KiCad/LTspice export, BOM. Emits `external` sources for law-bearing pins. | CONFIRMED WORKING (`test_cosim_control`, `test_schematic_editor`, `test_kicad_export`, `test_ui_polish`) |
| `bridge/measurements.py` | 559 | Waveform analysis, FFT, Bode. Pure array computation, no Qt, no solver dependency. | CONFIRMED WORKING (29 tests) |
| `bridge/kicad_export.py` | 616 | KiCad netlist + `.kicad_sch`, driven from the real graph. | CONFIRMED WORKING (14 tests) |
| `bridge/studio_engine.py` | 653 | Multi-instrument engine: transient, AC, DC sweep, op-point, Monte Carlo. Owns its own FFT path. | CONFIRMED WORKING (9 + 7 tests) |
| `bridge/industrial_verification.py` | 440 | DO-254 / ISO 26262 / IEC 61508 qualification battery. Reachable from the UI under **Tools ▸ Qualification**. | CONFIRMED WORKING (5 tests) |
| `bridge/report_generator.py` | 178 | HTML / Markdown / PDF test reports. | CONFIRMED WORKING (via `test_sota_suite`) |
| `bridge/analysis_runner.py` | 134 | Post-simulation FFT and Bode replays that need their own run. | CONFIRMED WORKING (via `test_measurements.py` and `test_schematic_editor.py`, including the `AnalysisError` path) |
| `bridge/gpio_model.py` | 218 | Open-loop declared pin profiles (the *pre*-control-law path). | CONFIRMED WORKING (28 tests) |
| `bridge/serial_console.py` | 89 | UART / `print()` capture panel. | CONFIRMED WORKING (via `test_editor_workflow`) |
| `bridge/circuit_stepper.py` | 82 | **Dead.** No importer, no test, no launcher. | CONFIRMED BROKEN (dead by construction) |
| `tools/ui_parity.py` | 444 | Theme-robust layout parity. Wraps the vendored `imgdiff`. | CONFIRMED WORKING (11 tests) |
| `tools/imgdiff.py` | 493 | Vendored MIT, upstream body byte-identical. Upstream's own `layout` mode. | **CONFIRMED BROKEN** for cross-theme comparison: it scores our two themes of one window at 8.1/100, because it thresholds absolute luminance and compares per-cell edge density. Do not use it directly; `ui_parity` wraps it. |

---

# LAYER 2 — INTEGRATION POINTS

## 1. ngspice <-> schematic editor

**Connection:** the UI holds a `cad_engine.SchematicNetlistEngine`; F2 calls
`cosim_runner.run_cosim(model, laws)`, which calls `model.compile_netlist()`
and feeds the lines to `NgSpiceEngine.load_circuit`.

**State: CONFIRMED WORKING.** `test_schematic_editor.py` includes
`test_f2_runs_the_control_law_and_populates_the_table` and
`test_clear_control_law_reverts_to_the_open_loop_path`, which assert the loop
runs and that results land in the UI table. `test_editor_workflow.py` (36)
covers netlist generation end to end.

**Failure points.**
- **LATENT RISK** — a pin carrying a control law must be wired, or the netlist
  emits no `external` source and the law silently never fires.
  `_check_laws_against_netlist` catches this and puts it in `run.warnings`
  rather than failing. The warning is only as good as the caller's attention.
- **UNVERIFIED** — behaviour when the UI netlist is large enough to slow the
  callback loop, or when a user-built netlist is syntactically invalid.

## 2. ngspice <-> control_law (the working closed loop)

**Connection:** `GetVSRCData` callback per timestep; the law reads its sense
net from ngspice's C buffer and returns the pin voltage.

**State: CONFIRMED WORKING.** 23 tests in `test_cosim_control.py`, including
real executions and the diagnostic paths.

**Failure points.**
- **LATENT RISK** — bare `except Exception` in `run_cosim` converts crashes into
  warnings. A run can "succeed" with zero samples.
- **LATENT RISK** — the `sense()` fast path trusts `ngGet_Vec_Info` results
  with no validation beyond a null check.

## 3. firmware.elf <-> QEMU

**Connection:** `qemu_orchestrator.FLASH_IMAGE` is
`firmware/.../qemu_flash.bin` (present, 4 MB), loaded with
`-drive file=...,if=mtd,format=raw`. QEMU runs ROM -> second-stage bootloader
-> `app_main()`; the host reads the console UART and waits for two markers.

**State: CONFIRMED WORKING end to end against the patched binary (built
2026-10-07).** With `tools/qemu-patch/0001-*.patch` applied, the ADC read
completes: 900 000 control-loop samples / 90 s, zero panics, and
`qom-set /machine/peripheral/sens adc1-value N` changes what the firmware
prints (Gate ON→OFF at 3456). Against *stock* QEMU the old measurement still
stands: 4 watchdog panics / 45 s, 0 control-loop samples.

**Failure points.**
- **CONFIRMED BROKEN in stock QEMU** — no analog handoff at all there; the
  patch replaces it. Against the patched binary a **manual** handoff exists
  (monitor `qom-set`); the automatic one does not — see §4 below.
- **LATENT RISK** — `qemu_flash.bin` is a build artifact under `.pio/`. It is
  4 MB of stale binary unless rebuilt; the orchestrator will happily boot an
  out-of-date image.

## 4. QEMU <-> ngspice

**Connection: half exists — host → chip manually; chip → solver not at all.**

What exists as of 2026-10-07: the patched SENS device accepts values *from the
host* through QOM at the fixed path `/machine/peripheral/sens`
(`qom-set … adc1-value N`), verified to change firmware behaviour (Gate
ON→OFF at 3456). What does not exist: `qemu_orchestrator.py` still has no
import of, and no reference to, ngspice — nothing in this repository calls
`qom-set` programmatically, and nothing maps a gate transition back into an
ngspice source. The chip's decisions never reach the analog solver.

**State: host → chip MANUAL and CONFIRMED WORKING; automatic orchestrator
bridge NOT IMPLEMENTED (deliberately deferred to a separate session);
chip → ngspice NOT IMPLEMENTED.** To finish it, in order: orchestrator code
that discovers the QOM path and calls `qom-set` each iteration; a host-side
reader for the SAR result or the GPIO output state; a bridge converting that
into an ngspice `external` source or an `alter_source_voltage` call; and a run
where the chip's gate decision changes the simulated `vout`.

## 5. control_law firmware-scraping <-> actual firmware behaviour

**Are they guaranteed to stay in sync? No, and they already have not.**

`read_firmware_constants()` scrapes exactly three names:
`ADC_LOW_THRESHOLD` (1995), `ADC_HIGH_THRESHOLD` (2030), `GATE_PIN`
(`GPIO_NUM_18` -> `GPIO18`). Those three *are* tracked — a test asserts them.

Everything else the firmware does is invisible to the scraper:

| Firmware behaviour | Modelled by `control_law`? |
|---|---|
| `ADC_OVERSAMPLE_N 16`, averages `sum / samples_ok` | **No** — one instantaneous sample |
| `adc_cali` line-fitting calibration, `adc_cali_raw_to_voltage` | **No** — counts compared directly against `vref` |
| ADC attenuation setting on the channel | **No** |
| `ESP_ERROR_CHECK` guards on init failure | **No** |
| Feedback divider | **Resolved, and a second bug fixed here too** — see below. |

**State: CONFIRMED BROKEN as a fidelity claim; CONFIRMED WORKING as a
constant-sync mechanism.**

**The divider question, resolved 2026-10-04.** Neither path was wrong. The
firmware's thresholds are *raw counts at the ADC pin* — its own comment says so
— and the 100k/100k divider is therefore already reflected in them:

    mid count 2012.5 / 4095 x 3.3 V = 1.6218 V at the pin
    1.6218 V x 2                    = 3.2436 V at vout   (main.c says 3.24 V)

So `control_law`'s `divider=1.0` is correct **when `sense_net` is the divider
output**, and `mock_controller`'s `x0.5`-in-the-thresholds plus reading `fb` is
also correct; they differ only in what they call the sense node. The genuine
defect was the *interface*: `control_law.divider` was undocumented, and the UI
let the user pick any net, so choosing the undivided `vout` regulated to
1.62 V instead of 3.24 V — exactly the divider ratio, silently.

Fixed by: documenting the semantics in `control_law`'s module docstring with the
arithmetic; adding `implied_pin_voltages()` / `implied_output_voltages()`; making
the UI's net-picker state that the net must be what the ADC pin sees and log the
implied switching voltages; and deriving `mock_controller`'s defaults from the
firmware constants. `TestDividerSemantics` and `TestThresholdsMatchFirmware`
pin all of it.

**A second, real bug in the same area, found while re-verifying the above.**
`law_from_firmware_source()` (the non-`_exact` variant) divided its recovered
`target_v` by `divider` but left `hysteresis_v` in pin volts. `normalize_law()`
then multiplies *both* by `divider` again, so the target survived while the
deadband came out **halved**. Naming the undivided net — `sense_net="vout"`,
`divider=0.5` — therefore produced **2004/2021 instead of 1995/2030**: a 35%
narrower hysteresis band, silently, from what is nominally the same firmware.

Latent, not live: every production caller uses `law_from_firmware_source_exact()`
(`cosim_runner.py:303`, `ui/schematic_editor.py:1871`), which pins
`low_counts`/`high_counts` verbatim from the source and bypasses the
recomputation. But the broken variant is the documented, obvious entry point,
so the fix is to scale both terms together. Pinned by two new tests in
`TestDividerSemantics`, both verified to fail against the old code with exactly
`(2004, 2021)`.

**All three paths now reproduce the firmware's numbers exactly:**

| Path | Counts |
|---|---|
| `main.c` | 1995 / 2030 |
| `control_law` (`fb`, `divider=1.0`) | 1995 / 2030 |
| `control_law` (`vout`, `divider=0.5`) | 1995 / 2030 |
| `mock_controller` (reads `fb`) | 1995 / 2030 |

**The fidelity gap is now loud and self-policing.** `TestFidelityGap` asserts
that `main.c` *still* declares `ADC_OVERSAMPLE_N`, *still* calls `adc_cali`, and
*still* says "RAW counts". Remove any of those from the firmware and the tests
fail, forcing the "WHAT THIS DOES NOT MODEL" section in `control_law.py` to be
revisited. A gap nobody can notice is how a model rots.

**Failure points.**
- **LATENT RISK — silent drift is the defining risk.** Change the firmware's
  oversampling or calibration and every co-simulation result stays plausible,
  stays green, and is quietly wrong. Nothing compares the model to the binary.
- **LATENT RISK — the regex is a `#define` scan.** Move a threshold into a
  header, a `static const`, or a Kconfig default and the scrape fails loudly
  (`ControlLawError`), which is the *good* case; but rename it and change its
  meaning and the scrape succeeds with the wrong number, which is the bad case.
- **UNVERIFIED** — the two thresholds have never been checked against silicon.

## 6. Other integration points

- **cad_engine <-> schematic_symbols — CONFIRMED WORKING.**
  `test_schematic_editor.py` asserts every palette symbol's pin order matches
  the netlister's canonical order. This is the contract that stops a drawing
  from compiling to a wrong netlist.
- **editor <-> measurements / kicad_export / report_generator — CONFIRMED
  WORKING** for the modules with tests; the report and KiCad paths are reached
  through `test_sota_suite.py` and `test_kicad_export.py`.
- **industrial_verification <-> studio_engine — CONFIRMED WORKING** (the
  qualification battery runs real engine simulations).
- **CI <-> repository — UNVERIFIED.** `.github/workflows/cosim-ci.yml` has never
  executed in CI history (no Docker in this environment). It is YAML-parsed and
  step-order-checked only. Its last simulation step is covered under **Retire or
  reconcile** below.

---

# LAYER 3 — THE FULL SYSTEM

## The path a user can actually run today

```
run_editor.bat  (or: python run_editor.py)
   |
   +-- Qt5 editor: place parts, wires, an ESP32 symbol; edit values
   |     ui/schematic_editor.py + schematic_scene.py + schematic_symbols.py
   |
   +-- MCU -> right-click -> "Import Control Law..." -> pick
   |   firmware/esp32_buck_controller/src/main.c
   |     control_law.law_from_firmware_source_exact()
   |       reads #define ADC_LOW_THRESHOLD 1995, ADC_HIGH_THRESHOLD 2030, GATE_PIN 18
   |
   +-- F2 -> cosim_runner.run_cosim(model, laws)
   |     cad_engine.compile_netlist()   -> SPICE text, MCU pins as `external`
   |     NgSpiceEngine.load_circuit()
   |     GetVSRCData callback per timestep:
   |         law reads the sense net from ngspice's buffer
   |         quantises to 12-bit counts, compares 1995 / 2030
   |         returns 0 V or 3.3 V for that instant
   |     transient run completes; traces land in the UI table
   |
   +-- post: measurements (FFT/Bode), KiCad export, qualification battery,
           HTML/Markdown reports
```

**This is the whole working product.** It is a genuine closed-loop
mixed-signal simulator: the digital decision is made inside the analog
timestep and the analog circuit's feedback is what drives the decision.

**What is NOT in that path:** the compiled firmware is never executed. The
`.elf` is parsed for facts and otherwise ignored. The "MCU" is a Python
implementation of a controller whose three constants were read out of the C
file.

## The intended path, once everything is finished

```
   UI -> netlist -> ngspice solves analog
             ^                        |
             |  gate voltage          | vout / divider
             |                        v
   QEMU (patched esp32_sens + esp32_gpio)
             ^
             |  merged qemu_flash.bin (real .elf)
   firmware app_main() oversamples ADC, decides on 1995/2030, drives GPIO18
```

The chip runs real compiled code; its ADC reads the analog world; its gate pin
drives the switch; the loop closes through silicon-equivalent hardware.

## The exact gap

**One link: the analog world is not visible to the chip, and the chip is not
visible to the analog solver.**

Concretely, four things stand between here and there, in dependency order:

1. ~~**The QEMU patch must compile.**~~ **DONE 2026-10-07** — builds clean
   from a fresh source export + the regenerated patch; **CONFIRMED WORKING**.
2. ~~**`esp32_sens` must model the conversion the firmware waits on.**~~
   **DONE 2026-10-07** — the firmware completes its ADC read and runs the
   control loop (900 000 samples / 90 s, zero panics); **CONFIRMED WORKING**.
3. **A host-side channel must exist to carry the reading out and the pin in.**
   **Half done.** Host → chip exists as a *manual* monitor command at the
   stable path `/machine/peripheral/sens` (**CONFIRMED WORKING** by
   measurement). Programmatic use by the orchestrator, and chip → ngspice,
   remain unwritten — the only genuinely new *design* work left in the gap.
4. **The control law must stop being a Python stand-in.** Once real firmware
   executes, `control_law`'s three scraped `#define`s stop being the model, and
   its divergences (no oversampling, no calibration, `divider=1.0`) become
   misleading rather than merely approximate.

Step 3 is the remaining new code: an orchestrator loop that feeds
`adc1-value` from the solver and reads the gate decision back. The repository
still has no prototype of that loop.

## What a reader should not conclude

- The 1995/2030 thresholds are **not** calibrated. No ESP32 board has ever run
  this firmware in the loop.
- The green suite does **not** mean the firmware works. It means the Python
  controller matches three constants in a C file.
- Both closed-loop paths now agree on the divider and on the counts. What they
  still share is every unmodelled behaviour listed in Layer 2.5.