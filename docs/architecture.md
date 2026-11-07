# Architecture

One page describing what the system does today and what is automatic versus
legacy. Every path below is traceable to a file in this checkout.

---

## Shipped component map

```
+----------------------------------------------------------------------+
|  C++/Qt5 GUI  (gui/)                                                  |
|   schematic_editor / waveform_viewer / cosim_dashboard / code_workspace|
+----------------------------------------------------------------------+
                     |  C ABI / Rust API
                     v
+----------------------------------------------------------------------+
|  crates/wowkispice-ffi                                                |
|   NgSpiceFfi        : runtime LoadLibraryExA/dlopen + 15 C symbols    |
|   cosim_runner.rs   : per-timestep loop over ngspice callbacks        |
|   mock_controller.rs: hysteretic controller law (1995/2030 counts)   |
|   studio_engine.rs  : waveform/UART helpers                           |
+----------------------------------------------------------------------+
                     |                         ^
                     v                         |
+----------------------------------------------------------------------+  |
|  crates/wowkispice-core  (no external deps)                           |  |
|   control_law, netlist sanitiser, cad_engine, measurements,           |  |
|   analysis_runner, kicad_export, report_generator, firmware parsers   |  |
+----------------------------------------------------------------------+  |
                     |                                                    |
                     v                                                    |
            tools/ngspice_dll/.../ngspice.dll  ----------------------------+
                     (solve; callbacks return the gate voltage)
```

---

## The loop as it actually runs

`crates/wowkispice-ffi/src/cosim_runner.rs` registers ngspice callbacks. On every
`GetVSRCData` callback it:

1. reads the sense net's most recently accepted sample from the live plot;
2. hands that value to the controller law (`ControlLaw` from
   `wowkispice-core::control_law`, or `MockESP32BuckController`);
3. quantises to 12-bit ADC counts and applies the hysteresis thresholds;
4. returns the gate voltage for that instant to the solver.

`mock_controller.rs` states its constants are **derived from**
`firmware/esp32_buck_controller/src/main.c` (ADC_LOW_THRESHOLD 1995,
ADC_HIGH_THRESHOLD 2030), not chosen by hand. The parity is tested at the logic
level in `crates/wowkispice-core/tests/test_buck_controller_hysteresis.rs` and
`test_buck_controller_industry.rs`.

This path is automatic and single-process. There is no QEMU process, no Python
IPC, and no serial console in it.

---

## What is legacy, and what is merely an artifact

| Item | Status | Evidence |
|---|---|---|
| QEMU co-simulation (`bridge/qemu_orchestrator.py`, `bridge/qemu_monitor.py`, `tools/qemu-patch/`) | **Legacy / deprecated.** Not used by the shipped Rust or GUI code. | `grep -rn "qemu" crates gui` matches only `toolchain_resolver.rs` (diagnostic discovery) and `firmware.rs` comments. |
| `tools/qualify_qemu.py`, `bridge/esp32_regs.py` | Legacy tooling retained for historical QEMU work. | Present, but not on the shipped path. |
| `firmware_control.dll` (and the `.so`/`.dylib` build targets) | **Built artifact, not wired.** Exports `buck_controller_tick` / `_ext`; no Rust, GUI, or Python code loads it. | `grep -rn "firmware_control\|buck_controller_tick" crates gui bridge` finds only tests and C sources. |
| `bridge/` (Python) | Parity contract and legacy modules. | The Rust modules mirror these 1:1; `crates/parity` diffs them. |
| `ui/` (PyQt5) | Legacy editor, mined for feature inventory. | Not the shipping GUI. |

The earlier architecture (Python bridge plus patched QEMU driving the firmware)
is documented in `QEMU_REPLACEMENT_STATUS.md` and `docs/STATE.md`. It is history,
not the current co-simulation path.

---

## What is data and what is model

| Item | Kind | Where |
|---|---|---|
| ngspice netlist + `.tran/.dc/.ac` | data | `circuits/`, user files |
| ngspice solver | engine | `tools/ngspice` (DLL 47) or system ngspice |
| `control_law` constants | model (derived from firmware source) | `crates/wowkispice-core/src/control_law.rs` |
| firmware thresholds | model (raw counts) | `firmware/esp32_buck_controller/src/main.c` |
| `mock_controller.rs` law | model (Rust port, constants from main.c) | `crates/wowkispice-ffi/src/mock_controller.rs` |
| `firmware_control.dll` | built artifact (not loaded by shipped code) | `firmware/esp32_buck_controller/src/` |
| golden traces | data | `tests/golden/` |
