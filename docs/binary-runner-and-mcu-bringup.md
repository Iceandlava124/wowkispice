# Binary Runner & New-MCU Bring-Up — Implementation Plan

**Status:** planned, not implemented. §2 is verified fact; everything after it is
specification, written to be implemented directly.
**Audience:** embedded engineer implementing from this document alone.
**Related records:** `docs/systems-map.md` §7–§9, `tools/qemu-patch/README.md`,
`docs/legacy-module-audit.md`, `docs/pilot-checklist.md`.

## 1. Goal

This repo does **not** use HDL as the controller. The core idea is simpler and
more concrete:

- the **real firmware binary** is the controller;
- the **analog side** is ngspice, and it should eventually be the **PCB**, not
  just the functional buck circuit;
- the two meet through **scripted injection + readback** and then through a
  **sampled-data hardware-in-the-loop** coupling, with ngspice still solving the
  analog network.

Today the closed loop runs **declared** controller behaviour: a pin profile
(`bridge/gpio_model.py`) or a control law parsed from firmware source
(`bridge/control_law.py`). The real firmware binary executes only under QEMU,
disconnected from the solver.

The **binary runner** closes that gap: the real image is the controller — its ADC
input comes from the ngspice solve, and its GPIO decisions drive ngspice
`external` sources.

The second goal is to make adding a new MCU (and testing it beside the others) a
checklist instead of a project. The third goal is to move the analog network from
“schematic buck converter” toward “PCB-level board sim”, so the mixed-signal result
is a board answer, not just a functional one.

## 2. What already works — verified, do not rebuild

| Capability | Evidence |
|---|---|
| Patched QEMU boots the real image through ROM, 2nd-stage bootloader and `app_main()` | 900 000 control-loop samples / 90 s, zero panics — `tools/qemu-patch/README.md` "Status" |
| ADC injection works via a QOM property | `qom-set /machine/peripheral/sens adc1-value N`; firmware prints `Raw ADC: 2012`; gate flips **ON → OFF at 3456** — same README |
| Injection path is stable across boots | device parented under `/machine/peripheral/sens` at creation time |
| GPIO writes are latched, not dropped | `esp32_gpio.c` latches `out`/`enable` with W1TS/W1TC semantics |
| Declared-law closed loop with the solver | `bridge/cosim_runner.py::run_cosim`; 34 tests in `tests/test_cosim_control.py` |
| Firmware image metadata | `bridge/firmware.py` (format, load address, entry point, sections, SHA-256) |
| Boot orchestration + memory probe | `bridge/qemu_orchestrator.py` (`boot_and_watch()`, `probe_memory()`), `bridge/qtest_client.py` |

## 3. The two gaps

1. **Injection is manual.** Feeding `adc1-value` is a human `qom-set` in the
   monitor; nothing in Python does it.
2. **Readback is missing.** Nothing reads the latched gate level out of QEMU
   and into ngspice as the external-source value.

## 4. Trap first — `qtest` does not execute the CPU

`bridge/qtest_client.py`'s docstring describes a lockstep loop ("one ngspice
step → one virtual-time step"). **Do not build the runner on that assumption
with this QEMU.** `probe_memory()` measures the truth: under `accel=qtest`,
`dummy_start_vcpu_thread` means no vCPU thread exists; `clock_step` advances
only the virtual clock and timers (1.078 s elapsed, DRAM unchanged, UART empty,
then QEMU blocks). qtest is a memory-access tool.

So: **run the guest under normal TCG execution** and talk to it over
QMP / HMP / UART. Deterministic instruction-level lockstep is not available
from stock QEMU and must not be promised; §5 M1 defines the honest timing
contract instead.

## 5. Milestones

### M0 — scripted injection + gate readback (the unblocking step)

Deliverable prototype implemented: `bridge/firmware_runner.py`.

- `bridge/firmware_runner.py` provides programmatic ADC injection and gate readback
  for the ESP32 firmware path, with the real QMP path exercised only when
  `WOSP_QEMU` and a QMP socket are configured.
- The same helpers are importable and behave cleanly when `WOSP_QEMU` is absent, so
  the rest of the product keeps working and the real path is clearly marked as
  UNVERIFIED without the environment.
- Tests: `tests/test_firmware_runner.py` (importability, gate-bit semantics, clean
  "not configured" failure paths, and a real-QMP-only class when
  `WOSP_QEMU` is set).

Deliverable: automation (new `bridge/qemu_monitor.py`, or new functions in
`bridge/qemu_orchestrator.py`) that can:

1. launch QEMU under TCG **with a control socket** — the current `-monitor none`
   becomes `-qmp unix:<path>,server=on,wait=off` (QMP); keep UART redirection
   exactly as `_launch()` does today;
2. inject without a human:
   - QMP: `{"execute":"qom-set","arguments":{"path":"/machine/peripheral/sens",
     "property":"adc1-value","value":N}}`;
   - fallback, works on any build: QMP `human-monitor-command` → HMP
     `qom-set /machine/peripheral/sens adc1-value N`;
3. read the gate level:
   - **no patch change:** HMP `xp /1wx 0x3FF44004` (physical read of the
     latched `GPIO_OUT`; mask with `bridge/esp32_regs.py::gate_bit(pin)`);
   - **preferred:** add a read-only QOM property for `out`/`enable` to the
     patched `esp32_gpio` device (mirror the `adc1-value` pattern in
     `tools/qemu-patch/`), so the interface is a named property, not a hex dump;
4. drain the UART log (`QemuSession.uart_text()`) for `Raw ADC:`/gate lines.

**Acceptance test** — new `tests/test_qemu_binary_runner.py`, guarded with
`unittest.skipUnless(os.environ.get("WOSP_QEMU"), ...)`:
- boots the image and waits for `BOOT_MARKERS` from `qemu_orchestrator.py`;
- sweeps injected counts 1500 → 3500 over two runs and asserts the gate flips
  at the firmware's own boundary (measured 3456 under manual injection);
- fails if a watchdog panic appears within the window.
This test is also the regression guard for the QEMU patch itself.

### M1 — the binary runner (closed loop with ngspice)

**Timing contract — wall-clock sampled-data hardware-in-the-loop.** State it in
the UI and results; do not call it lockstep:
- ngspice solves with its own step; on accepted steps (`run_cosim`'s
  `progress_callback`) the host pushes the latest divider-node voltage into
  `adc1-value` and polls the gate at a bounded rate (every K steps or
  ≥ ~100 µs wall time);
- a gate change updates the pin's `external` source exactly like `control_law`
  does today in `bridge/cosim_runner.py`;
- the firmware's own loop decides — no Python law is involved.

Interface sketch — new `bridge/binary_runner.py`:

```python
run_binary_cosim(model, pin_specs, *, firmware_image, qemu, machine="esp32",
                 tstep_us=0.5, duration_ms=5.0,
                 poll_interval_steps=...,
                 progress_callback=None,
                 stop_flag=None) -> CosimRun
```

- reuse `run_cosim`'s external-source wiring and the `CosimRun` result type, so
  results remain comparable with declared-law runs (`CosimRun.regulation()`);
- reuse `esp32_regs.read_gate` / `gate_bit` for pin mapping and the net naming
  from `gpio_model.py`;
- record the actual coupling interval in `run.warnings` rather than implying
  exactness.

**Acceptance:**
- same buck circuit with firmware in the loop: report regulation error with
  `CosimRun.regulation()` and compare against the declared-law run and
  `mock_controller` (same circuit, same targets);
- assert non-trivial gate activity (switches > 0, duty in a plausible band);
- skipped without `WOSP_QEMU`, so CI stays green where QEMU is absent.

### M2 — PCB-level analog network (the mixed-signal target)

The functional buck netlist is a start, but the real target is **pcb sim** with
the firmware in the loop. The current plan therefore adds a board network layer:

1. **Start from the functional circuit** — the M0/M1 buck topology is the
   control loop the firmware expects. Do not replace that until the runner works.
2. **Add board parasitics and routing** — trace resistance, via/plane impedance,
   connector impedance, and any sensed-vs-loaded node separation, so the ADC
   sense net is a real board node and not an ideal point.
3. **Keep the firmware as the controller** — the PCB sim does not get a new
   HDL controller; the gate still comes from the real firmware image under QEMU
   once the runner is wired.
4. **Compare board vs functional** — the PCB run is the same firmware, same
   buck topology intent, richer analog network. Differences are a board answer
   (parasitics, layout sensitivity, sense-node movement), not “a different
   controller”.

**Acceptance:**
- the PCB netlist compiles and runs through ngspice;
- the runner can still couple the firmware ADC input and gate output into it;
- the result differs from the functional buck by board effects you can name
  (trace resistance, sense-node shift, ground bounce, connector parasitics),
  and those effects are reported rather than hidden.

### M3 — UI wiring (optional)

Add a "Run on firmware binary" mode beside the declared-law cosim (F2), reusing
the existing `progress_callback` / `stop_flag` plumbing. Keep declared-law mode
as the fast default.

## 6. Adding & testing a new MCU — checklist

**Already MCU-agnostic — reuse as is:** `bridge/gpio_model.py` (pin profiles →
SPICE cards), `bridge/control_law.py` (`law_from_firmware_source[_exact]` parses
`#define`s), `bridge/measurements.py`, `bridge/analysis_runner.py`, and the UI.

| # | Step | Imitate | Produce |
|---|---|---|---|
| 1 | Register map | `bridge/esp32_regs.py` | `bridge/<mcu>_regs.py` — addresses transcribed from the SoC headers (not re-derived), data + fetch aliases, packers (`sar1_result` pattern), pin masks |
| 2 | Execution | `tools/qemu-patch/` + `bridge/qemu_orchestrator.py` | Either a stock-QEMU machine (then just set `machine=`) or a device patch that: exposes injection as a QOM property usable after realize, parents the device for a stable QOM path, latches GPIO writes (W1TS/W1TC) and makes them readable, finishes conversions in bounded virtual time |
| 3 | Firmware project | `firmware/esp32_buck_controller/` | New PlatformIO project, pinned platform; flash image at flash offsets (bootloader + partition table + app) via esptool `merge_bin`; `BOOT_MARKERS` are strings the firmware really prints |
| 4 | Wiring & laws | `bridge/gpio_model.py`, `bridge/control_law.py` | Pin profile JSON for the board; parse thresholds/targets from firmware source where possible — the cross-check pattern is `tests/test_closed_loop_buck.py::TestThresholdsMatchFirmware` |
| 5 | Tests | `tests/test_firmware_gpio.py` + runner tests | Unit (regs/packers/ranges) without QEMU; integration (boot markers, injection boundary, loop parity) behind `WOSP_QEMU`; keep declared-law doubles for CI without QEMU |
| 6 | Done | — | Boots reproducibly; injection flips the gate at the expected counts; binary runner closes the loop; tests added; README / `systems-map.md` updated |

**Side-by-side MCUs:** `machine`, `image`, `markers` and the regs module are
already parameters (`boot_and_watch(qemu, image=…, machine=…, markers=…)`).
Give each board a small profile table (name → machine / image / markers / regs
module) and let the integration tests iterate it, so a new MCU is one row plus
its checklist items.

## 7. Build & run commands (copy-paste)

```bash
# 1. Patched QEMU (native build; --enable-slirp matters) — see tools/qemu-patch/README.md
patch -p1 < 0001-esp32-model-sar-adc-and-gpio-output.patch && ninja -C build

# 2. Firmware image (PlatformIO + esptool merge_bin at flash offsets)
#    expected at: firmware/esp32_buck_controller/.pio/build/esp32dev/qemu_flash.bin

# 3. Boot check (no output of interest = missing markers; exit 0 = booted)
WOSP_QEMU=/path/to/qemu-system-xtensa python -m bridge.qemu_orchestrator

# 4. Runner tests (skipped automatically when WOSP_QEMU is unset)
WOSP_QEMU=/path/to/qemu-system-xtensa python -m pytest tests/test_qemu_binary_runner.py -q
```

## 8. Risks and traps (each measured or read from the code)

- **qtest never executes the guest** — §4; the only working control channel is
  QMP/HMP plus the UART.
- **QOM paths shift** unless the device is parented at creation time
  (`/machine/unattached/device[N]` indices are not stable).
- **Injection properties need `realized_set_allowed`**, or `qom-set` refuses
  once the SoC has realized the device.
- **Console logs must live on a local filesystem** (temp dir): drvfs refuses
  reads of a file QEMU still holds open; `_log_path()` already does this.
- **TCG is not real-time**; report the coupling interval instead of implied
  cycle accuracy.
- **Stock QEMU does not work**: GPIO writes are dropped and the ADC read spins
  into an interrupt-watchdog panic. Only the patched build runs the loop.
- **The in-repo `.venv` may be stale**; run tests with a Python 3.12 that has
  `requirements.txt` installed (see README Quickstart).
- **PCB parasitics are easy to overclaim** — a pretty trace model is not a
  validated board answer. Name the parasitics you include and which ones you
  are ignoring, and report the result as a board estimate until proven otherwise.

## 9. References

- `tools/qemu-patch/README.md` — patch contents, build steps, manual-injection
  evidence, and the "still not wired" statement this plan resolves.
- `docs/systems-map.md` §6–§9 — layer-by-layer verification state.
- `bridge/qemu_orchestrator.py`, `bridge/qtest_client.py`, `bridge/esp32_regs.py`.
- `bridge/cosim_runner.py` + `bridge/control_law.py` — the external-source
  contract the runner reuses.
- `tests/test_closed_loop_buck.py` — firmware-constants cross-check pattern.
- `docs/pilot-checklist.md` — the editor-side runbook for the functional buck + F2.
