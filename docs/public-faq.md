# WOWKISPICE Public FAQ

## What is WOWKISPICE?
WOWKISPICE is a hybrid control lab for power-electronics simulation and firmware co-design. It combines a real ngspice engine, closed-form physics proofs, and a hysteretic controller whose key constants (ADC_LOW_THRESHOLD=1995, ADC_HIGH_THRESHOLD=2030) are derived from firmware source files `firmware/esp32_buck_controller/src/main.c` and `firmware/esp32_buck_controller/src/buck_controller_tick.c`.

## What is the public label?
"hybrid control lab for power-electronics simulation and firmware co-design." This label fits the verified slice (real ngspice engine, closed-form proofs, hysteretic controller parity tied to firmware source constants) without overclaiming hardware-validated results.

## What does this project NOT claim?
- NOT a certified inverter or power converter.
- NOT a UL 1741 / UL 1741 SA/SB qualification. Simulation results are not a substitute for certified test procedures.
- NOT an IEEE 1547-2018 compliance tool.
- NOT a replacement for board bring-up, bench validation, or field verification.
- NOT a claim that the simulated controller path equals the behavior of a compiled firmware image on real silicon.
- NOT a claim that a simulated inverter/grid interface satisfies UL 1741 / IEEE 1547 or any hardware immunity standard.

## What is the first-run command path?
The honest minimal first-run (Windows) is:
1. Clone the repo and enter it.
2. Run the Windows bootstrap: `powershell -ExecutionPolicy Bypass -File setup.ps1`
   - `setup.ps1` creates `.venv`, installs `requirements.txt`, downloads the ngspice DLL (checksum-verified), and places it into `tools/ngspice_dll/`. It is documented as idempotent.
3. Run the environment gate: `.\.venv\Scripts\python.exe tools\selfcheck.py` or `.\run_selfcheck.bat`
   - This is the prototype gate: interpreter, dependencies, ngspice load, a known circuit solved against closed-form answers, and the test runner.
   - If the gate is green on a machine, the environment is sane enough to run the suites and the editor. If it is not green, stop and fix that before claiming a working install.

**What is missing from a fully curated public first-run:**
- The exact first-run command path is not yet consolidated into one clean public page free of handoff-style notes.
- A fully documented public install path is only cleanly available as the Windows `setup.ps1` bootstrap right now; a non-Windows first run is not equally curated here.
- The pieces in this repo are not a finished turnkey product. The honest first-run is the bootstrap plus the self-check gate; the deeper suite / editor / emulator paths are separate steps with separate prerequisites.

## Concrete first-run snippets you can actually run today
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
`cargo test -p wowkispice-core` is the strongest Rust-only verification path that does not require the full Python stack.

## What is the project's own license?
The project's license is Apache-2.0 (file `LICENSE`). That is the project's governing license text.

## Redistribution and third-party obligations
This project does not invent additional legal warnings. The underlying audit trail is:

- `LICENSE` → Apache-2.0
- `THIRD_PARTY_NOTICES.md` → real dependency and bundled-tool notes in this repo
- `tools/ngspice_license_snippet.md` → literal ngspice `COPYING` excerpt kept on disk for the present work, read from the repo's existing `tools/ngspice/docs/COPYING`. The ngspice license is the `Modified BSD` license, with some subcomponents under `LGPLv2`, `LGPLv2 or newer`, `GPLv2 or newer`, `MPLv2.0`, unnamed MIT-style, public domain, and the manual under `CC-BY-SA v4.0`.
- PyQt5 metadata in this environment declares `GPL v3`. If a distributed build links PyQt5, that distribution is governed by those terms, not by the project's Apache-2.0 text alone. The repo records this as an owner action, not as a fully resolved public statement.
- QEMU is not redistributed by this repo and is not part of the shipped co-simulation path. Only the two patches under `tools/qemu-patch/` are tracked, and the notes record that QEMU's license travels with the QEMU source the user clones.

If a redistribution note is desired in the public README, it should point at `THIRD_PARTY_NOTICES.md` and `tools/ngspice_license_snippet.md` for the actual evidence, not invent summarized claims.

## Current gate status on this host
Re-measured 2026-11-07 from a clean shell with no virtualenv activated:
- `run_selfcheck.bat` → `SELF-CHECK: PASS`, exit 0, with 547 passed / 4 skipped in 229.43 s.
- `cargo test -p wowkispice-core` → 334 passed, 0 failed, 0 warnings.
- The controller verification passed: `cargo test -p wowkispice-core test_hysteresis` (tests `test_hysteresis_low_then_high` and `test_hysteresis_full_sequence_matches_python_mock`).
- A deliberately removed quick-suite test file made the gate print `SELF-CHECK: FAIL` and exit 1.
- Earlier failures came from running the gate with the system interpreter, which lacks the project dependencies. The gate now resolves the project venv itself (`tools/selfcheck.py` re-executes under it). It is still the prototype gate, not a substitute for the full validation corpus.

## How to read the evidence in this repo
1. Read the bounded-evidence story in `docs/industry-credibility-baseline.md` first.
2. Use the self-check gate as the "is this environment sane" check.
3. Use the closed-form proofs and controller-parity tests as the strongest verified slice.
4. Treat the real binary-in-the-loop path as a documented but not-on-this-host capability until the environment supports it.