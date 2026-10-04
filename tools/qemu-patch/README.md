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

409 insertions, 4 deletions.

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

The exact path is not pinned down here. The device is created with `qdev_new()`
on the SoC's `esp32-periph-bus`, so it will land somewhere under
`/machine/soc/esp32-periph-bus/` with an auto-generated instance suffix rather
than the tidy `/machine/soc/sens` one might expect. If a stable, hand-writable
path matters, give it an explicit id at creation time
(`device_set_id(sens, "sens")`) — that is a one-line change.

`conversion-ns` defaults to 5000 and is settable the same way.

## Applying and building

```bash
tar xf qemu-esp_develop_9.2.2_20260417-src.tar.xz
cd qemu-esp_develop_9.2.2_20260417
git apply /path/to/0001-esp32-model-sar-adc-and-gpio-output.patch
./configure --target-list=xtensa-softmmu --enable-trace-backends=nop
ninja -j4
```

## Status

**Not compiled.** The patch is verified to apply cleanly to the pinned source
and to reproduce the intended tree byte for byte, but it has never been through
a compiler, and no test has confirmed the firmware's control loop completes an
iteration. Treat the register semantics as a proposal to review, not as working
code.

Build prerequisites it assumes, none of which are currently in the WSL
environment: `ninja`, `meson`, `pkg-config`, `flex`, `bison`,
`libglib2.0-dev`, `libpixman-1-dev`. Ubuntu 24.04 ships meson 1.3.2 and QEMU
9.2 wants >= 1.5, so a newer meson will probably have to come from a venv —
WSL has no `pip` either, so `python3-venv` first.

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