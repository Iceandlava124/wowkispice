# Industry credibility baseline — WOWKISPICE

**Draft for edit.** This is the bounded-evidence statement the project should stand behind before it is presented as an industry-facing engineering tool. It is intentionally narrow: it describes what is verified, what is model-only, what is not validated against hardware on this host, and what the public trust boundary is. It does not assert certification, hardware correlation, or field readiness.

Public label: **hybrid control lab for power-electronics simulation and firmware co-design**.
Merge/publish target for the public-facing docs: `docs/PUBLIC_FACING.md` is the authoritative public-facing README; `README.industry.md` is the public-facing draft for editing; `docs/industry-credibility-baseline.md` is the bounded-evidence statement behind both. This choice is encoded in the public-facing docs so the open items are no longer open questions in them.

## What is actually verified here today

- **ngspice analog engine binding.** The project binds to a real ngspice solver and can load circuits, run analyses, and read results back through the solver interface. (`bridge/ngspice_wrapper.py` + `crates/wowkispice-ffi` / `sharedspice.h`-style C bridge patterns.)
- **Closed-form solver proofs.** Some tests assert solver behavior against closed-form references — for example RC step response and underdamped RLC ringing — with tolerances documented as justified from the solver settings and observed error, not hand-picked to pass. (`docs/validation.md` is the tolerance policy; `tools/prove_physics_engine.py` and related proof tests are the evidence.)
- **Hysteretic buck controller logic parity.** The controller decision logic implemented in the Rust core matches a C firmware mock's hysteresis thresholds (1995 / 2030 raw ADC counts) across sequence, boundary, noise-rejection, and persistence-style checks. The firmware source that anchors those numbers is literally present in this repo (`firmware/esp32_buck_controller/src/main.c` and `firmware/esp32_buck_controller/src/buck_controller_tick.c`), and the same thresholds appear there.
- **Editor compiles clean.** The Qt5-shaped editor (`gui/wowkispice_gui.exe`) builds with strict warnings enabled and the main UI surfaces are exercised by editor-facing tests. This verifies a buildable UI and a working schematic/editor path; it does not, by itself, verify a full interactive desktop launch on every platform.
- **Self-check gate.** `tools/selfcheck.py` / `run_selfcheck.bat` exists as an environment gate and is run before claiming a working install. It is the *prototype* gate, not a substitute for the validation corpus.
- **Known skips/reasons.** Some tests skip with explicit reasons (for example missing emulator/firmware images). Those skips are documented rather than hidden.

**What “verified” does not mean here:** verified against silicon, field conditions, or any external certification body. Verified means *asserted by tests or measured evidence in this repository*.

## What is model-only / simulation-limited

- **Physics-level modeling, not hardware-equivalent prediction.** ngspice is a circuit solver. It is useful for analog behavior, but the accuracy of any result depends on the models and the parasitics and switching behavior fed into it.
- **Device and switching-transient limits.** Semiconductor switching dynamics in SPICE-class tools are model-dependent and can range from useful to misleading depending on the model quality, circuit parasitics, and gate drive details. Precise prediction of switching events should not be assumed from simulation alone.
- **ADC/GPIO path fidelity is documented, not hardware-proven.** The patched QEMU `esp32_sens` path models a subset of the ESP32 ADC/GPIO behavior for co-simulation purposes. `docs/fidelity.md` records what the model does and does not represent. The project explicitly does not claim this model equals real hardware.
- **Controller model vs compiled firmware.** The controller logic the Rust core verifies is a formalized model whose key constants are derived from the firmware source. The shipped co-simulation loop (`crates/wowkispice-ffi/src/cosim_runner.rs` + `mock_controller.rs`) applies that model at each timestep. `firmware_control.dll` exists and exports `buck_controller_tick`, but no Rust, GUI, or Python code path loads it (verified by grep over `crates/`, `gui/`, and `bridge/`). This is not a claim that the simulated controller path equals the behavior of a compiled firmware image on real silicon.

## What is NOT validated against hardware on this host

- **The real binary-in-the-loop path is not closable here.** Evidence that the patched QEMU boots the firmware and can accept host-injected ADC values and show gate behavior exists in the repo's notes, but the full closed loop with the compiled firmware running against the solver is not executable in this environment without the patched QEMU + firmware build on a capable machine. Where this document mentions that path, it is written as a prerequisite / gate, not as a claim that the project currently closes it here.
- **No board correlation exists in this repo.** There is no measurement against a physical ESP32 board, no validated ADC count-vs-voltage curve against silicon, and no evidence that the simulated controller behavior matches a real board. This is stated as a limit, not as a missing footnote.

## Public trust boundary

An engineer should treat WOWKISPICE as a **lab instrument for exploring and comparing power-electronics ideas**, not as a measurement truth machine.

**Reasonably trustworthy from a sim result:**
- Whether a declared circuit topology and control law behave in a way consistent with the solver's physics under the assumptions built into the models.
- Closed-form-style checks: for example, whether an RC or RLC result is consistent with the expected analytic behavior within the project's documented tolerances.
- Controller-decision behavior for the hysteretic logic the project has formalized and tested against its own model/thresholds.

**Not trustworthy from a sim result:**
- Exact switching timing or loss numbers as if they were measured on hardware.
- Any claim that the simulated controller path equals the behavior of a compiled firmware image on real silicon.
- Any claim that a simulated inverter/grid interface behavior satisfies UL 1741 / IEEE 1547 or any hardware immunity standard. The project does not perform those certifications.

## What this is not

- **Not a certified inverter or power converter.**
- **Not a UL 1741 / UL 1741 SA / SB qualification.** The project does not certify inverter safety or grid-support behavior, and simulation results are not a substitute for the certified test procedures those standards define.
- **Not an IEEE 1547-2018 compliance tool.** Interconnection standards are about real DER behavior and certified testing; this project may help explore behavior but does not establish compliance.
- **Not a replacement for board bring-up, bench validation, or field verification.** Simulation is a design and learning aid; hardware validation is a separate activity and is not represented here as complete.

## First-run command path

This project's first run is not a single one-line bootstrap that is fully curated for public consumption yet, and this baseline does not pretend otherwise. What exists is a Windows bootstrap and a self-check gate, plus a Rust-only verification path that does not require the full Python stack. The honest minimal first-run is:

**Today's honest minimal first-run (Windows):**
1. Clone the repo and enter it.
2. Run the project's Windows bootstrap:
   `powershell -ExecutionPolicy Bypass -File setup.ps1`
3. Run the environment gate:
   `.\.venv\Scripts\python.exe tools\selfcheck.py`
   or `.\\run_selfcheck.bat` on Windows.

If that gate is green on a machine, the environment is sane enough to run the suites and the editor. If it is not green, stop and fix that before claiming a working install.

**What is missing from a fully curated public first-run:**
- The exact first-run command path is not yet consolidated into one clean public page free of handoff-style notes.
- The Windows `setup.ps1` bootstrap is the verified path. `tools/setup.sh` and `tools/run_selfcheck.sh` exist for POSIX shells, but they are not verified on Linux/macOS in this pass.
- The pieces in this repo are not a finished turnkey product. The honest first-run is the bootstrap plus the self-check gate; the deeper suite / editor paths are separate steps with separate prerequisites.

## Redistribution and third-party obligations

This project's own license is Apache-2.0.

The repository already records the real third-party story in `THIRD_PARTY_NOTICES.md`, and this baseline points there for the full evidence trail. A literal excerpt of the ngspice license file is also kept on disk for this work at `tools/ngspice_license_snippet.md`, which is read from the repo's existing `tools/ngspice/docs/COPYING`.

The obligations worth surfacing explicitly are:
- **PyQt5.** The installed PyQt5 metadata in this environment declares `GPL v3`. If a distributed build links PyQt5, that distribution is governed by those terms, not by the project's Apache-2.0 text alone. The repo records this as an owner action, not as a fully resolved public statement.
- **ngspice.** The project downloads the ngspice shared library as a binary, and the license text in this checkout is the `tools/ngspice/docs/COPYING` file, which states the ngspice license is the `Modified BSD` license with some subcomponents under `LGPLv2`, `LGPLv2 or newer`, `GPLv2 or newer`, `MPLv2.0`, unnamed MIT-style, public domain, and the manual under CC-BY-SA v4.0. The DLL archive itself does not ship a license file.
- **QEMU.** Not redistributed by this repo. Only the two patches under `tools/qemu-patch/` are tracked, and the notes record that QEMU's license travels with the QEMU source the user clones.

## Current gate status on this host

Re-measured 2026-11-07 from a clean shell with no virtualenv activated:

- `run_selfcheck.bat` → **`SELF-CHECK: PASS`**, exit 0. It invokes
  `.venv\Scripts\python.exe` directly and reported 547 passed / 4 skipped in
  229.43 s (full suite).
- `tools/selfcheck.py` started with the system `python` re-executes under the
  project venv automatically, so the result does not depend on `PATH`.
- `cargo test -p wowkispice-core` → 334 passed, 0 failed, 0 warnings.
- The controller verification passed: `cargo test -p wowkispice-core test_hysteresis`
  (tests `test_hysteresis_low_then_high`,
  `test_hysteresis_full_sequence_matches_python_mock`).
- Deliberately removing a quick-suite test file made the gate print
  `SELF-CHECK: FAIL` and exit 1, confirming the exit status is real.

Earlier runs of the same gate failed because they used the system interpreter,
which does not have the project dependencies. That was an invocation problem,
not a code failure; the gate now resolves the interpreter itself. The gate is
still the prototype gate and is not a substitute for the full validation corpus.

## How to read the evidence in this repo

If you are evaluating this project, start from the bounded-evidence story, not from the feature list:

1. Read this credibility baseline first.
2. Use the self-check gate as the “is this environment sane” check.
3. Use the closed-form proofs and controller-parity tests as the strongest verified slice.
4. Treat the real binary-in-the-loop path as a documented but not-on-this-host capability until the environment supports it.

## Open user decisions

- [TODO: user decision] Whether the public README should carry a short redistribution note inline, or just point at `THIRD_PARTY_NOTICES.md` and `tools/ngspice_license_snippet.md` for the actual evidence.
- [TODO: user decision] Whether to verify the POSIX `tools/setup.sh` / `tools/run_selfcheck.sh` path on Linux/macOS. Windows is the verified path as of 2026-11-07.
- [TODO: user decision] Whether the editor path should be presented as “buildable in the repo's build settings” rather than as a guaranteed one-click desktop launch on every platform.
