# PROJECT_STATUS.md — current state of WOSP

This is the honest map of the repo as it exists now. Read it as a product shape,
not as a task list.

## In one line

A Windows-first power-electronics tool that combines a real `libngspice` solver,
an LTspice-shaped schematic editor, and a controller workflow whose decision logic
comes from real firmware source. The compiled firmware does not yet run inside the
simulation loop.

## The strongest slice today

If you want the part that is most credible right now, it is this:

- draw a schematic in the editor
- simulate it in the real solver
- attach a control law imported from firmware source or declared by hand
- let the controller read the simulated circuit and drive the gate each timestep
- inspect the result in the waveform and measurement tabs
- export the design to KiCad or as a netlist/BOM/PDF

That slice is coherent and test-backed. The rest of the repo is either
supporting material, planned material, or material that is useful but only manual.

## Credible status in plain language

### Works and is test-backed

- The ngspice C-API bridge.
- The schematic editor and its workflows.
- Closed-loop co-simulation against a declared or firmware-imported law.
- A real feedback divider in the netlist, not a Python fudge.
- Waveform analysis: cursors, FFT, Bode, timing, step metrics, noise, distortion,
  Monte Carlo, parametric sweep, I-V curve tracer, PV/MPPT.
- Export to SPICE netlist, KiCad schematic/netlist, BOM, CSV/PDF/PNG.
- Firmware image parsing and control-constant import from source.
- GPIO pin profiles and the pin map view.
- A self-check gate and a large test suite.

### Works, but only manual

- Running the compiled firmware under patched Espressif QEMU and watching it boot
  and control a buck.
- Injecting analog values into that firmware by hand through a QEMU monitor command.
- Reading the gate state back by hand.

### Not yet done, or only planned

- An automatic bridge between the solver and the compiled firmware.
- Packaging, versioning, and a fully polished first-use story.
- A small, defensible reference-set validation corpus.
- Cross-platform install paths and onboarding that do not depend on knowing the repo.

## What is intentionally not claimed

- This is not a calibrated measurement instrument.
- This is not a vendor-validated component library.
- This is not a certified or production release yet.
- This does not yet execute the real firmware binary as the controller inside the
  simulation loop.

## Why those boundaries matter

Industry-facing tools win by being clear about their limits. The interesting part
of this repo is real; the risk is presenting it as more finished than it is. The
boundaries above are the difference between a useful engineering tool and
something that quietly over-promises.

## The most important opens

1. Close the loop with the compiled firmware automatically, not only manually.
2. Make save/open and export paths trustworthy end to end.
3. Define a small reference corpus the tool can be checked against.
4. Make the public story, setup, and onboarding feel like a product, not a repo.


## Where the internal notes live

The repo still carries planning and positioning notes. Some of those are useful
scaffolding. They are not the public product story, and they should not be the
first thing a new reader sees.

- Virtual-lab feature map: [docs/virtual-lab-features.md](docs/virtual-lab-features.md)
- Embedded start page: [docs/embedded-engineer-start.md](docs/embedded-engineer-start.md)
- Embedded workspace layout: [docs/embedded-workspace-layout.md](docs/embedded-workspace-layout.md)
- Capability inventory: [docs/capability-inventory.md](docs/capability-inventory.md)
- Systems map: [docs/systems-map.md](docs/systems-map.md)
- Industry-readiness verdict and phased plan: [docs/industry-readiness.md](docs/industry-readiness.md)
- Binary runner and MCU bring-up spec: [docs/binary-runner-and-mcu-bringup.md](docs/binary-runner-and-mcu-bringup.md)

## The next move

For an industry-ready path, the next move is not another analysis feature. It is
to choose the public surface, harden the parts a user would blame on the tool, and
make the credibility boundaries explicit. That usually means:

1. Decide what this is for.
2. Make the first-use path reproducible and honest.
3. Pick one strongest demo and make it the front door.
4. Fix the failure and round-trip paths before expanding the feature set.

If you want, the next concrete draft can be one of these:

- a tighter industry-facing README plus a one-page product story
- a first-use and support-scope page that says what a user can and cannot trust
- a short credibility baseline: the reference circuits and results the tool should
  match before it is presented as dependable
