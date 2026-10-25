# Fidelity boundary — what the emulated ADC/GPIO path does and does not model

This document is the honest statement of the `esp32_sens` QEMU patch and
the firmware we actually run. It exists so that nobody builds the "closed
loop" deliverable on a model that looks like the hardware but is not.

Every "does not model" line is backed by the patch or the firmware code, or
marked UNKNOWN. "UNKNOWN" means we did not read the thing we would need to
assert it.

---

## What the emulated ADC/GPIO path *does* model

| Layer | What we verified | Evidence |
|---|---|---|
| **Register map** | `SENS_SAR_MEAS_START1_REG = 0x3FF48854`, `GPIO_OUT_REG = 0x3FF44004`, `GPIO_ENABLE_REG = 0x3FF44020`, the `MEAS1_*` bits (data 16 bits, done 1<<16, start 1<<17, force 1<<18, pad-enable 1<<19..31) | `bridge/esp32_regs.py` and `tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch` |
| **Write path** | `qom-set /machine/peripheral/sens adc1-value N` is reachable through the HMP `qom-set` command; the patch wires `/machine/peripheral/sens` to the `esp32_sens` device | `bridge/qemu_monitor.py` `set_adc1_value`; `tools/qemu-patch/README.md` |
| **Read path** | `xp /1wx 0x3FF44004` returns the latched GPIO18 bit; `bridge/qemu_orchestrator.py` `--qemu` boot check reads it back | Unit tests + the boot test output in `docs/toolchain.md` §6 |
| **Data format** | `sar1_result(raw)` packs a 12-bit value into a 32-bit MEAS_START1 word with the DONE bit set — identical to what the ESP32's RTC SAR ADC controller presents | `bridge/esp32_regs.py::sar1_result` |
| **Peripheral timing** | The model advances with the QEMU virtual clock (`clock_step`); the guest's timer callbacks, including the RTC SAR start, are driven by that clock | `bridge/qtest_client.py::clock_step` |
| **GPIO output latch** | GPIO18 OUT bit is a simple latch; write to `GPIO_OUT_REG` is reflected in `xp` readback; the patched device has *no* input latch (only output) | patch target/function list in `0001-esp32-model-sar-adc-and-gpio-output.patch` |

---

## What the path does NOT model

Every lack of fidelity below is a claim about the patch or the firmware we
actually ran, not about the real ESP32. Where the claim is grounded in code
the location is given; where it is a genuine unknown it is marked **UNKNOWN**.

| Modeled-but-not-real | What it does | Evidence (file/line) |
|---|---|---|
| **No noise** | The ADC returns the exact 12-bit value written; there is no Gaussian, no quantization noise, no kTC noise | patch: SAR conversion result word written verbatim |
| **No non-linearity** | `counts = raw` is a straight line; no 12-bit ENOB curvature, no missing codes | patch: result word copied as-is |
| **No calibration / eFuse** | The firmware reads `adc_oneshot_ll_get_event()` on a model that always returns the injected value; the eFuse calibration bytes and the `adc_cali_raw_to_voltage()` curve are never consulted by the model | `firmware/src/main.c` calibration block (lines: `adc_cali_scheme_line_fitting_check_efuse`, `adc_cali_create_scheme_line_fitting`) — the model never participates in it |
| **No attenuation behaviour** | The model assumes the full 0–3.3 V range with no input attenuation; `ADC_ATTEN_DB_12` (12 dB) is a firmware-side setting that the model ignores | `firmware/src/main.c` `ADC_ATTEN_DB_12` and patch: no attenuator state |
| **No sampling time** | The model has no `td` or aperture; `clock_step` to the next sample happens in one tick, not a slowly settling quantizer | `bridge/qtest_client.py` `clock_step` |
| **No input impedance** | The ADC input is a voltage source with zero impedance; there is no driver resistance, no sample-and-hold capacitance, no divider loading | patch: no impedance state |
| **No PWM / comparator** | The SAR never runs in free-run mode and never competes with a comparator; only the oneshot SW trigger is modelled | patch: `MEAS1_START_FORCE` only |
| **GPIO latency and drive strength** | Out: 0/1 latch, no slew-rate, no drive current, no input trip, no ESD clamp | `bridge/esp32_regs.py` `GPIO_OUT_REG` write |
| **GPIO input** | `GPIO_IN_REG` is not modelled — the device only exposes output; `xp` of the input latch is NOT in the model | patch: no `GPIO_IN_REG` state |
| **Peripheral bus timing** | MMIO access is a single 32-bit word at a time with no AHB/APB behind it | patch: word-addressable register map |
| **ROM/bootloader sequencing** | `qemu_orchestrator.py` `probe_memory()` documents that qtest does not execute the CPU; the boot path (ROM → bootloader → `app_main`) is executed but its internal peripheral sequencing is outside the model | `docs/binary-runner-and-mcu-bringup.md` M0/M1 |

## What is and is not validated against hardware

- **Not validated against hardware** — the whole `esp32_sens` model is a
  patch to QEMU that we built and compiled; we have not measured it against
  a physical ESP32. Report this on the README and in
  `docs/industry-readiness.md` (added as a notice in the next section).
- **What we do have** — the firmware's own `main.c` thresholds (1995/2030
  raw counts), the `_to_counts` mapping in `bridge/control_law.py`, and
  the `sar1_result`/`read_gate` symmetry in `bridge/esp32_regs.py`. Those
  are *definitions*, not measurements against silicon.
- **UNKNOWN** — the SAR aperture time, the sample-and-hold transfer
  function, the noise floor, the eFuse calibration curve for this exact
  chip, the GPIO slew and loading. None of those are prescribed by the
  patch; a future patch would have to add state for them, and a future
  test harness would have to compare against a board.

---

## Notices

* The README and `docs/industry-readiness.md` carry the
  "**Not validated against hardware**" notice (added in §6 of this
  document's required edits).
* Any Phase-1 deliverable that says "measured ADC count" is asserting a
  measurement against a model we have not yet validated. The
  `docs/hardware-validation-protocol.md` protocol exists so that can be
  measured with one ESP32 and a resistor divider.

---

## Where each claim came from

1. `tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch` — the
   full patch that defines the model (register addresses, bit positions,
   result packing, GPIO OUT/ENABLE words).
2. `bridge/esp32_regs.py` — the Python mirror of those registers, and the
   `sar1_result`/`read_gate` implementations.
3. `firmware/esp32_buck_controller/src/main.c` — the calibration and
   threshold code the model never participates in, together with the
   `ADC_ATTEN_DB_12` assumption.
4. `bridge/qemu_monitor.py` and `bridge/qemu_orchestrator.py` — the HMP
   commands that make the model observable, and the acknowledgement in the
   orchestrator that `SENS` is `unimplemented-device` in the unpatched
   build.
5. `README.md` — the project's own statement that the firmware binary
   "runs its control loop and responds to analog values injected from the
   host via a QEMU monitor command", and that what is missing is the
   *automatic* bridge.
