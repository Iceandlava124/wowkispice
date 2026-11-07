# WOWKISPICE — hybrid control lab for power-electronics simulation and firmware co-design

WOWKISPICE is a hybrid control laboratory for power-electronics simulation and
firmware co-design: you can draw or ingest a circuit, simulate it with a real
SPICE-class solver (a genuine ngspice engine), and keep the resulting controller
decision logic tied to firmware source constants, then inspect waveform-level
consequences before committing to hardware. The honest public posture is not
“it predicts measured hardware,” but “it is a substantiated lab tool whose engine,
closed-form truths, and controlled-cycle controller logic are verified here today,
with the deeper electrical prediction and hardware correlation bounded and documented.”

Public label: **hybrid control lab for power-electronics simulation and firmware co-design**.
This is the label used for this project's public-facing docs. It is chosen because it
matches what is verified here today without overstating it.

What the public docs are:
- **Authoritative public-facing README:** `docs/PUBLIC_FACING.md`.
- **Public-facing draft for editing:** this file, `README.industry.md`.
- **Bounded-evidence statement behind both:** `docs/industry-credibility-baseline.md`.

These docs describe the same public story from different angles, and they are
intentionally kept consistent. If one is edited, the others that reference the same
thing should be reconciled.

## What this tool is

- A **hybrid control lab for power-electronics simulation and firmware co-design**, with
  the simulation backend indexed to a real ngspice flow rather than a surface-only GUI story.
- A tool where the hysteretic controller thresholds are not merely sketched but explicitly
  pinned to firmware source constants (1995 / 2030 raw ADC counts) and verified against that
  formalization.
- A credible engineering lab environment whose strongest verified slice is the closed-form
  proofs plus the controlled hysteresis behavior, presented honestly against what simulation
  can and cannot say.

## What this tool is not

- Not a certified inverter, converter, or grid-interconnection product.
- Not a UL 1741 / IEEE 1547 / related DER certification tool.
- Not a measurement instrument and not a substitute for bench or board validation.
- Not a “simulated product” in the sense of passing field-grade claims from model-only evidence.

If the goal is to use WOWKISPICE to reason about a circuit or a controller pathway before
hardware, it is honest and useful for that. If the goal is to claim certified hardware behavior
from simulation results alone, that is outside the project's bounds and should not be presented
that way.

## What the verifier says it can do, honestly

Verified here today, on this repo, as asserted by tests or measured evidence in this checkout:

- **Real ngspice analog engine.** The project binds to a real ngspice solver and can load circuits,
  run analyses, and read results back through the solver interface. This is not a toy fill-in.
- **Closed-form sanity checks.** Some tests assert solver behavior against closed-form references —
  for example RC step response and underdamped RLC ringing — with tolerances documented as justified
  from the solver settings and observed error, not hand-picked to pass.
- **Hysteretic buck controller logic parity.** The controller decision logic implemented in the Rust
  core matches a C firmware mock's hysteresis thresholds (1995 / 2030 raw ADC counts) across sequence,
  boundary, noise-rejection, and persistence-style checks. The firmware source that anchors those numbers
  is literally present in this repo (`firmware/esp32_buck_controller/src/main.c` and
  `firmware/esp32_buck_controller/src/buck_controller_tick.c`), and the same thresholds appear there.
- **Editor compiles clean.** The Qt5-shaped editor builds with strict warnings enabled in the repo's
  build settings, and the main UI surfaces are exercised by editor-facing tests. This verifies a
  buildable UI path; it does not by itself guarantee a fully interactive desktop launch on every platform.
- **Environment gate exists.** `tools/selfcheck.py` / `run_selfcheck.bat` is the prototype environment
  gate. Running it is the first honest “is this environment sane” check before claiming a working install.

What verified does **not** mean here: verified against silicon, field conditions, or any external
certification body. Verified means *asserted by tests or measured evidence in this repository*.

## Simulation limits and the hardware gap, stated plainly

- The analog engine is physics-level modeling, not hardware-equivalent prediction. The accuracy of any
  result depends on the models and the parasitics and switching behavior fed into it.
- Semiconductor switching dynamics in SPICE-class tools are model-dependent and can range from useful to
  misleading depending on model quality, circuit parasitics, and gate drive details. Precise prediction of
  switching events should not be assumed from simulation alone.
- The ADC/GPIO path fidelity is documented, not hardware-proven. The repo's fidelity notes record what the
  model does and does not represent; the project does not claim the model equals real hardware.
- The controller logic the Rust core verifies is a formalized model whose key constants are derived from the
  firmware source. Some closed-loop results on this host run `firmware_control.dll` inside the solver loop, so
  the present build does close a DLL-driven controller loop here — but that is still a DLL path, not a claim that
  this proves the behavior of a compiled firmware image on real silicon.
- The closer-to-hardware path is bounded. Evidence that the patched QEMU can boot the firmware and accept
  host-injected ADC values and show gate behavior exists in the repo's notes, but the full binary-in-the-loop
  path is not closable on this host without the patched QEMU plus a firmware build on a capable machine. Where
  these docs mention that path, they describe it as a prerequisite / gate, not as a claim that the project
  currently closes it here. There is no board correlation in this repo.

Public trust boundary: treat WOWKISPICE as a lab instrument for exploring and comparing power-electronics
ideas, not as a measurement truth machine. Reasonably trustworthy from a sim result: whether a declared circuit
topology and control law behave in a way consistent with the solver's physics under the assumptions built into the
models; closed-form-style checks that land inside the project's documented tolerances; controller-decision behavior
for the hysteretic logic the project has formalized and tested against its own model/thresholds. Not trustworthy
from a sim result: exact switching timing or loss numbers as if they were measured on hardware; any claim that the
simulated controller path equals the behavior of a compiled firmware image on real silicon; any claim that a simulated
inverter/grid interface behavior satisfies UL 1741 / IEEE 1547 or any hardware immunity standard.

## First-run command path

This project's first run is not a single one-line bootstrap that is fully curated for public consumption yet, and
this draft does not pretend otherwise. What exists is a Windows bootstrap and a self-check gate, plus a Rust-only
verification path that does not require the full Python stack. The honest minimal first-run is:

**Today's honest minimal first-run (Windows):**

1. Clone the repo and enter it.
2. Run the project's Windows bootstrap:
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```
   `setup.ps1` creates `.venv`, installs `requirements.txt`, downloads the ngspice DLL (checksum-verified),
   and places it into `tools/ngspice_dll/`. It is documented as idempotent.
3. Run the environment gate:
   ```powershell
   .\.venv\Scripts\python.exe tools\selfcheck.py
   ```
   or, on Windows, run `.\\run_selfcheck.bat`, which does the same thing through the repo's `.venv` interpreter.
   This is the prototype gate: interpreter, dependencies, ngspice load, a known circuit solved against closed-form
   answers, and the test runner.

If that gate is green on a machine, the environment is sane enough to run the suites and the editor. If it is not
green, stop and fix that before claiming a working install.

**What is missing from a fully curated public first-run:**
- The exact first-run command path is not yet consolidated into one clean public page free of handoff-style notes.
- A fully documented public install path is only cleanly available as the Windows `setup.ps1` bootstrap right now;
  a non-Windows first run is not equally curated here.
- The pieces in this repo are not a finished turnkey product. The honest first-run is the bootstrap plus the
  self-check gate; the deeper suite / editor / emulator paths are separate steps with separate prerequisites.

## Concrete first-run snippets you can actually run today

From the repo's existing docs and scripts, the commands that exist on disk and mean something are:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

```powershell
.\run_selfcheck.bat
```

```powershell
.\.venv\Scripts\python.exe tools\run_tests.py
```

```powershell
cargo test -p wowkispice-core
```

`cargo test -p wowkispice-core` is the strongest Rust-only verification path that does not require the full Python
stack. On this host it runs inside the crate and is independent of the Windows dependency gate. It does not, by itself,
start the editor or close the emulator path. Use it as a verification target, not as a complete product smoke test.

## Redistribution and third-party obligations

This project's own license is Apache-2.0. That is the project's license text in `LICENSE`.

When these docs say they are not inventing additional legal warnings, the underlying audit trail is:
- `THIRD_PARTY_NOTICES.md` is the real dependency and bundled-tool notes in this repo.
- `tools/ngspice_license_snippet.md` is the literal ngspice `COPYING` excerpt kept on disk for the present work,
  read from the repo's existing `tools/ngspice/docs/COPYING`.

Those files show the following shape of obligations:

- **PyQt5.** The installed PyQt5 metadata in this environment declares `GPL v3`. If a distributed build links PyQt5,
  that distribution is governed by those terms, not by the project's Apache-2.0 text alone. The repo records this as
  an owner action, not as a fully resolved public statement. Whether and how the project wants to carry that into the
  public README is still a real decision, but these docs do not leave it vague or pretend it does not exist.
- **ngspice.** The project downloads the ngspice shared library as a binary, and the license text in this checkout is
  the `tools/ngspice/docs/COPYING` file, which states the ngspice license is the `Modified BSD` license with some
  subcomponents under `LGPLv2`, `LGPLv2 or newer`, `GPLv2 or newer`, `MPLv2.0`, unnamed MIT-style, public domain, and
  the manual under CC-BY-SA v4.0. The DLL archive itself does not ship a license file, which `THIRD_PARTY_NOTICES.md`
  records explicitly.
- **QEMU.** Not redistributed by this repo. Only the two patches under `tools/qemu-patch/` are tracked, and the notes
  record that the QEMU license travels with the QEMU source the user clones.

In short: if you are choosing what to publish, the public README should not bury the PyQt5 point, and it should point at
`THIRD_PARTY_NOTICES.md` and `tools/ngspice_license_snippet.md` for the actual evidence rather than invented summaries.
Whether the repo wants a short redistribution note in the public README itself is still a real decision, but it is no
longer an open question about whether there are obligations to consider — there are.

## Open topics that are real, but are now owner decisions, not open questions about whether the public docs have a
 stance

- Whether the public README should carry a short redistribution note inline, or just point at
  `THIRD_PARTY_NOTICES.md` and `tools/ngspice_license_snippet.md` for the actual evidence.
- Whether the repo wants a non-Windows first-run path curated, and how strongly to state the current gate
  status versus the historical green runs recorded in the repo's own notes.
- Whether the editor path should be presented as “buildable in the repo's build settings” rather than as a
  guaranteed one-click desktop launch on every platform.
