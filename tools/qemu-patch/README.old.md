# QEMU patch: model the ESP32 SAR ADC and GPIO output

`0001-esp32-model-sar-adc-and-gpio-output.patch` against
[espressif/qemu](https://github.com/espressif/qemu) branch `esp-develop`, tag
`esp-develop-9.2.2-20260417` (the version PlatformIO pins for `espressif32`).

## Why

Espressif's QEMU runs our real firmware through ROM, the second-stage
bootloader and `app_main()` — verified, see below. It then dies:

```
Guru Meditation Error: Core  0 panic'ed (Interrupt wdt timeout on CPU0).
Backtrace: 0x400d35c0 0x400d3702 0x400d1699 0x400d116e 0x400d70f9 0x400dd1d1
  adc_oneshot_ll_get_event  adc_ll.h:468
  adc_oneshot_hal_convert   adc_oneshot_hal.c:155   <- while (!get_event()) {;}
  adc_oneshot_read          adc_oneshot.c:241
  app_main                   firmware/esp32_buck_controller/src/main.c:71
```

`info qtree` on a stock `esp32` machine returns 25 devices: 24
`unimplemented-device` stubs and one `open_eth`. `0x3ff48800` (SENS) is one of
the stubs, so `MEAS1_DONE_SAR` reads 0 forever.

A second, less obvious gap: the GPIO device is *not* an unimplemented-device,
but `esp32_gpio_write()` in `hw/gpio/esp32_gpio.c` is an empty function. Writes
to `GPIO_OUT` and `GPIO_ENABLE` are silently dropped, so even with an ADC the
emulated chip would be unsampleable — we could feed it but never read the gate
drive back. `bridge/qemu_orchestrator.py probe_memory()` measures both:

```
region                 address      wrote        read back    retains writes?
dram scratch           0x3FFB0000   0xDEADBEEF   0xDEADBEEF   yes
SENS sar_meas_start1   0x3FF48854   0x00010BAD   0x00000000   NO
GPIO out               0x3FF44004   0x00040000   0x00000000   NO
GPIO enable            0x3FF44020   0x00040000   0x00000000   NO
```

## What it changes

| File | Change |
| --- | --- |
| `include/hw/misc/esp32_sens.h` | New. SENS register map and device state. |
| `hw/misc/esp32_sens.c` | New. RTC SAR ADC oneshot model. |
| `hw/misc/meson.build` | Build the new file under `CONFIG_XTENSA_ESP32`. |
| `hw/xtensa/esp32.c` | Instantiate the device instead of stubbing `DR_REG_SENS_BASE`. |
| `include/hw/gpio/esp32_gpio.h` | Add the output/enable registers and state. |
| `hw/gpio/esp32_gpio.c` | Latch `out`/`enable` with W1TS/W1TC semantics; make them readable. |

431 insertions, 4 deletions.

The ADC models only what `adc_oneshot_read()` needs: `MEAS_STATUS` reads 0 so
`adc_oneshot_ll_start()` leaves its wait loop, a rising edge on `MEAS1_START_SAR`
arms a conversion, and `MEAS1_DONE_SAR` + `MEAS1_DATA_SAR` land 5 µs later in
guest virtual time. Attenuation, calibration and the DMA controller are not
modelled; this is a feedback-voltage source, not an analog model.

## Driving it from the host

The sample returned is whatever the `adc1-value` property holds when the
conversion starts. It is a plain QOM property, so no new protocol and no
firmware change is needed — find the device's QOM path and set it:

```
(qemu) info qtree                        # look for dev: esp32.sens
(qemu) qom-set <path> adc1-value 2012
```

The path **is** pinned down: the patch parents the device at creation time
(`object_property_add_child(container_get(qdev_get_machine(), "/peripheral"),
"sens", …)`), so it is always `/machine/peripheral/sens` — verified identical
across independent boots. (Without that, QEMU files it under
`/machine/unattached/device[N]`, whose index shifts between runs.) Note the
injection properties are declared with `realized_set_allowed = true`; without
that flag QEMU refuses `qom-set` after the SoC realizes the device.

`conversion-ns` defaults to 5000 and is settable the same way.

## Applying and building

```bash
tar xf qemu-esp_develop_9.2.2_20260417-src.tar.xz
cd qemu-esp_develop_9.2.2_20260417
patch -p1 < /path/to/0001-esp32-model-sar-adc-and-gpio-output.patch
./configure --target-list=xtensa-softmmu --disable-docs --disable-gtk \
            --disable-sdl --disable-vnc --disable-spice --enable-slirp
ninja -C build
```

`--enable-slirp` matters: this fork compiles `net/slirp.c` unconditionally and
needs `pkg-config --cflags slirp` on that compile line (`libslirp-dev`
required). The build must be **native** — `qemu-system-xtensa` is an x86-64
program that emulates Xtensa via TCG; the xtensa toolchain is only for
firmware.

## Status

**Compiled, boot-tested, and reproducible from scratch — 2026-10-07.**

- Regenerated from the working tree: the patch now includes the QEMU 9.2
  `QEMUTimer` fixes, the `realized_set_allowed` injection-property fix, and
  the stable `/machine/peripheral/sens` QOM path, none of which the original
  proposal had.
- `patch -p1` applies it cleanly to a pristine export of the pinned commit
  (exit 0, no fuzz, no rejects); configure and a full `ninja -C build` then
  complete with exit 0.
- The resulting `qemu-system-xtensa` boots the real `qemu_flash.bin` through
  ROM, bootloader and `app_main()`, completes **900 000 control-loop samples
  in 90 s with zero panics** (the stock-QEMU `Interrupt wdt timeout` panic is
  gone; residual `task_wdt` warnings are non-fatal), and answers
  `qom-set /machine/peripheral/sens adc1-value N` — the firmware prints
  `Raw ADC: 2012`, then at 3456 flips the gate **ON → OFF**, i.e. its own
  1995/2030 hysteresis reacting to injected input.
- Build prerequisites (all present in WSL Ubuntu 24.04): `ninja`, `pkg-config`,
  `flex`, `bison`, `libglib2.0-dev`, `libpixman-1-dev`, `libslirp-dev`,
  python3 >= 3.10 (`./configure` builds its own meson venv).

Still not wired: `bridge/qemu_orchestrator.py` does not feed `adc1-value`
programmatically — feeding is a manual monitor command, and nothing reads the
gate decision back into ngspice. That is the next session's task; the
implementation plan (milestones, interfaces, acceptance tests) is
`docs/binary-runner-and-mcu-bringup.md`.


## Verification that has already happened

Boot to `app_main`, real firmware, unmodified QEMU binary
(`python -m bridge.qemu_orchestrator --qemu .../qemu-system-xtensa`):

```
ets Jul 29 2019 12:21:46
rst:0x1 (POWERON_RESET),boot:0x12 (SPI_FAST_FLASH_BOOT)
entry 0x4008063c
I (1431) boot: ESP-IDF 6.1.0 2nd stage bootloader
I (5889) boot: Loaded app from partition at offset 0x10000
I (11381) main_task: Calling app_main()
I (11381) BUCK_CTRL: Starting ESP32 Buck Converter Closed-Loop Controller...
I (11381) BUCK_CTRL: Entering high-speed hysteretic control loop...
```

Deterministic over 45 s: 5 ROM boots, 5 `app_main` calls, 4 identical watchdog
panics, 0 control-loop samples.