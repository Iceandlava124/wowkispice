# PROJECT_STATUS.md — current state of WOWKISPICE

This is the honest map of the repo as it exists now. Read it as a product shape, not as a task list.

## In one line

A Windows-first power-electronics tool that combines a real `libngspice` solver, a Qt5-shaped schematic editor, and a controller workflow whose decision logic comes from real firmware source. The compiled firmware now runs inside the simulation loop through an `extern "C"` DLL, eliminating the QEMU dependency.

## The strongest slice today

If you want the part that is most credible right now, it is this:

- draw a schematic in the editor
- simulate it in the real solver
- attach a control law imported from firmware source or declared by hand
- let the controller read the simulated circuit and drive the gate each timestep
- inspect the result in the waveform and measurement tabs
- export the design to KiCad or as a netlist/BOM/PDF

That slice is coherent and test-backed. The rest of the repo is either supporting material, planned material, or material that is useful but only manual.

## Credible status in plain language

### Works and is test-backed

- The ngspice C-API bridge (`wowkispice-ffi`): 24/26 tests pass; 2 pre-existing DLL-load environment issues documented (VC++ runtime, not code bugs).
- The Qt5 C++ GUI: `wowkispice_gui.exe` compiles with `-Wall -Wextra -Werror`; 4 tabs (Schematic Editor, Waveform Viewer, Co-Sim Dashboard, Code/Text Workspace) — zero warnings.
- Closed-loop co-simulation: Rust core drives the hysteretic controller DLL at each timestep; gate flip thresholds (1995/2030) match the Python mock exactly.
- Firmware image parsing and control-constant import from source (Intel HEX/ELF parsers in `crates/wowkispice-core`).
- The automatic co-simulation loop: the Rust solver calls `buck_controller_tick` from `firmware_control.dll` at each timestep, passing the ngspice-sampled ADC value, and captures the GPIO state.
- GPIO pin profiles and the pin map view.
- A self-check gate and a large test suite: 328/328 Rust tests pass, zero warnings.
- Parity harnesses: 3 modules with Rust+Python drivers printing `PARITY OK — N values identical`.

### Works, but only manual (no longer the only path)

- The old QEMU+Python co-simulation loop is now superseded by the single-process Rust+DLL path.
- Running the compiled firmware under patched Espressif QEMU and watching it boot and control a buck — **deprecated**: the DLL path is the standard.
- Injecting analog values into that firmware by hand through a QEMU monitor command — **deprecated**.
- Reading the gate state back by hand — **deprecated**.

### Not yet done, or only planned

- PyQt6 upgrade and local Ollama co-pilot (Phase 4 of roadmap).
- Parameter-sweep automation via `rayon` (Phase 5).
- Polished Windows installer with "honest boundaries" credibility badge (Phase 6).
- Firmware migration to `esp-hal` + `rtic` Rust embedded framework (continuous improvement).

### Intentionally not claimed

- This is not a calibrated measurement instrument.
- This is not a vendor-validated component library.
- This is not a certified or production release yet.
- The hysteresis controller DLL is the new standard; QEMU is deprecated but still available for historical reference.

## Why those boundaries matter

Industry-facing tools win by being clear about their limits. The interesting part of this repo is real; the risk is presenting it as more finished than it is. The boundaries above are the difference between a useful engineering tool and something that quietly over-promises.

## The most important opens

1. PyQt6 upgrade + local Ollama co-pilot (Phase 4).
2. Parameter-sweep automation via `rayon` (Phase 5).
3. Windows installer ("honest boundaries") (Phase 6).
4. Firmware migration to `esp-hal` + `rtic` (continuous improvement).

## Where the internal notes live

The repo still carries planning and positioning notes. Some of those are useful scaffolding. They are not the public product story, and they should not be the first thing a new reader sees.

- Virtual-lab feature map: `docs/virtual-lab-features.md`
- Embedded start page: `docs/embedded-engineer-start.md`
- Embedded workspace layout: `docs/embedded-workspace-layout.md`
- Capability inventory: `docs/capability-inventory.md`
- Systems map: `docs/systems-map.md`
- Industry-readiness verdict and phased plan: `docs/industry-readiness.md`
- Binary runner and MCU bring-up spec: `docs/binary-runner-and-mcu-bringup.md`

## The next move

For an industry-ready path, the next move is not another analysis feature. It is to choose the public surface, harden the parts a user would blame on the tool, and make the credibility boundaries explicit. That usually means:

1. Decide what this is for.
2. Make the first-use path reproducible and honest.
3. Pick one strongest demo and make it the front door.
4. Fix the failure and round-trip paths before expanding the feature set.

If you want, the next concrete draft can be one of these:

- a tighter industry-facing README plus a one-page product story
- a first-use and support-scope page that says what a user can and cannot trust
- a short credibility baseline: the reference circuits and results the tool should match before it is presented as dependable