# Architecture

One page (plus diagrams). The intent is to describe what the system *does*
today and what is automatic versus manual, not to describe a dream state.

---

## Component map

```
+----------------------------------------------------------------------+
|  controller (what runs the loop)                                      |
|  - bridge/control_law.py      : hysteretic thresholds, ADC counts    |
|  - bridge/ngspice_wrapper.py  : ngspice.dll / libngspice bindings    |
|  - bridge/qemu_monitor.py     : HMP qom-set xp reads/writes          |
|  - bridge/qemu_orchestrator.py: boot, console log, monitor session   |
|  - bridge/firmware.py         : parse .elf/.hex, SHA-256, metadata   |
+----------------------------------------------------------------------+
        |          |          |              |
        v          v          v              v
   ngspice   QEMU (esp32_sens)  ESP32    serial console
   netlist   patched: esp32_sens (executed binary, boot test)
   solver    SAR ADC + GPIO OUT ( modelled )  ( ROM->bootloader->app_main)
        |          |          |              |
        +----------+----------+              |
                   |  ADC count (12-bit)      |
                   |  <- qom-set adc1-value   |
                   |  -> xp GPIO_OUT (18)     |
                   |      gate decision       |
                   +----------> closed loop <+
```

The loop, as it actually is today, is two independent tracks that share the
same numbers:

1. **`bridge/ngspice_wrapper.py` → `bridge/control_law.py` (automatic).** A
   netlist that lives in the repo or a user file is handed to ngspice, the
   solver runs, and the Python bridge converts the results into counts with
   the same mapping the firmware uses (`bridge/control_law._to_counts`).
   Nothing here touches QEMU. This is the *analog engine* and it is real.

2. **`bridge/qemu_orchestrator.py` + `bridge/qemu_monitor.py` (manual).** The
   firmware binary boots under the *patched* QEMU, `app_main()` runs, and
   the host pushes an ADC sample with `qom-set
   /machine/peripheral/sens adc1-value N` and reads the latched GPIO18 gate
   decision back with `xp /1wx 0x3FF44004`. **This track has zero
   bi-directional coupling to ngspice today** — `cosim_runner.py` and the
   `probe_memory()` helpers document the gap. It is a *verification* of the
   firmware, not the co-simulation loop.

The coupling is now automatic via `bridge/binary_runner.py`:

* ngspice solver results drive ADC injection into the firmware running in QEMU via `QemuMonitor`;
* firmware gate state (read from GPIO registers) drives the ngspice external voltage source each timestep;
* the loop runs in lockstep with the solver callbacks.

---

## Data flow (as it is today)

```
ngspice netlist ──> ngspice (solve) ──> bridge/ngspice_wrapper.py
                                                       │
                                                       ▼
                                              control_law.py  (_to_counts)
                                                       │
                                                       ▼
                                              (controller model output)

ESP32 firmware ──> QEMU (esp32_sens patched) ──> host ADC injection
     |                                        (manual, qom-set)
     └──> console UART (boot markers) ◀──────────┘
```

Legend:

* **Automatic** – the path from netlist to numbers that needs no human in
  the loop once the files are in place.
* **Manual** – a human (or an operator script) acts at that point; the
  robot never does it on its own.

---

## What is data and what is model

| Item | Kind | Where |
|---|---|---|
| ngspice netlist + `.tran/.dc/.ac` directives | data | repo `circuits/`, user files |
| ngspice solver | engine | `tools/ngspice` (Windows DLL 47), system ngspice |
| `control_law.py` constants | model (calibrated, real counts) | `bridge/control_law.py` |
| firmware `main.c` thresholds | model (raw counts, uncalibrated) | `firmware/src/main.c` |
| `esp32_sens` model | EML (patched QEMU) | `tools/qemu-patch/` |
| `bridge/esp32_regs.py` addresses | data (transcribed from ESP-IDF 6.1.0 `soc` headers) | `bridge/esp32_regs.py` |
| golden traces | data (to be versioned) | documented in `docs/time-sync.md` |
| `firmware_control.dll` / `.so` / `.dylib` | FFI bridge (cross-platform) | `firmware/esp32_buck_controller/src/buck_controller_tick.c` |
| `buck_controller_tick_ext()` | calibrated/oversample path | Added in industrial hardening Phase 3 |
