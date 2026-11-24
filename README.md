# WOWKISPICE — mixed-signal virtual lab for power electronics

WOWKISPICE is a Windows-first tool that lets a user draw a power-electronics schematic
(e.g., a buck converter), simulate it with a real ngspice solver, and close the loop
with a controller whose decision constants are derived from real firmware source.
The Rust core, the ngspice FFI layer, and the C++/Qt5 GUI are the shipped path.

## Measured status (2026-11-07)

| Component | Status |
|---|---|
| **Rust core** (`crates/wowkispice-core`) | `cargo test -p wowkispice-core`: **369 passed, 0 failed**; `cargo test -p wowkispice-core --features julia`: **379 passed, 0 failed** (adds 10 Julia-bridge tests; baseline stays zero-dependency, `default = []`) |
| **FFI bridge** (`crates/wowkispice-ffi`) | **27 passed, 0 failed** (26 lib + 1 integration); DLL load uses `LOAD_WITH_ALTERED_SEARCH_PATH`, and `ngGetVSRCData` is optional because this build does not export it |
| **Qt5 GUI** (`gui/`) | Clean rebuild verified 2026-11-07: `cmake --build gui/build --clean-first` exit 0, **0 warnings** (`-Wall -Wextra -Werror -pedantic`), 390,252-byte `wowkispice_gui.exe`. Requires Qt5 Charts |
| **Hysteretic controller** | Rust tests reproduce the firmware thresholds 1995/2030; parity with the Python mock is tested at the logic level |
| **Environment gate** | `run_selfcheck.bat`: **SELF-CHECK: PASS**, all 5 checks (Rust core tests, Julia-feature tests, Julia solver script, deployment guide, Rust↔Julia bridge) |
| **Installer** | `installer/build_installer.ps1` rebuilds the NSIS installer from source (GUI + CLI + ngspice). The installer bundles the full Qt5/MinGW runtime closure (including `libstdc++-6.dll`, `libgcc_s_seh-1.dll`, ICU, and `platforms/qwindows.dll`) so the GUI runs on a Windows machine with no MSYS2/Qt installed. Clean-VM verification pending |
| **Co-simulation path** | Rust `cosim_runner` + ngspice + Rust controller model (`crates/wowkispice-ffi/src/mock_controller.rs`). QEMU is **legacy, not the shipped path** |
| **CLI simulator** (`crates/wosp-cli`) | `cargo run -p wosp-cli -- sim rc --r 2000 --c 1e-6 --vin 5` — simulate RC/RL/RLC/diode with custom values via the Julia backend from any directory; JSON output. `standalone` mode needs no Julia |

## Quick start: simulate a circuit

```bash
# RC low-pass, R=2000 ohm, C=1uF -> final voltage 1.967V at t=1ms
cargo run -p wosp-cli -- sim rc --r 2000 --c 1e-6 --vin 5 --tstop 0.001

# RL series, 12V/50ohm -> 0.24A steady-state
cargo run -p wosp-cli -- sim rl --r 50 --l 0.01 --vin 12 --tstop 0.02

# No Julia needed: built-in dependency-free simulator
cargo run -p wosp-cli -- standalone rc --r 1000 --c 1e-6 --vin 5

# See all options
cargo run -p wosp-cli -- help
```

The `sim` command needs Julia with the pinned project installed once:
`julia --project=bridge/julia -e 'using Pkg; Pkg.instantiate()'`. The `standalone`
command has zero external dependencies.

## Plan status

`ROADMAP.md` is the single source of truth for phase numbers. This table is a
summary; it does not define its own numbering.

| Phase | Status |
|---|---|
| Phase 0 — Foundation | COMPLETE |
| Phase 1 — Reproducible environment | COMPLETE (Windows) |
| Phase 2 — Deterministic & regression-testable | COMPLETE |
| Phase 3 — Professionalize | IN PROGRESS |
| Phase 4 — Validation & sign-off | IN PROGRESS |
| Phase 5 — Product hardening & distribution | NOT STARTED |
| Phase 6 — Optional regulated workflows | NOT STARTED (optional) |

Deferred and unscheduled: PyQt6/Ollama co-pilot, `esp-hal` + `rtic` firmware
migration, AI design assistant.

## Try It Instantly

```bash
# 1. Core tests (369 passed, 0 failed)
cargo test -p wowkispice-core

# 1b. Core tests including the Julia bridge (379 passed, 0 failed)
# Requires the `julia` feature only; baseline stays zero-dependency
cargo test -p wowkispice-core --features julia

# 2. Launch the GUI (4-tab window)
# Qt5 Charts is required: C:/msys64/usr/bin/pacman.exe -S mingw-w64-ucrt-x86_64-qt5-charts
cmake -S gui -B gui\build -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=C:\msys64\ucrt64
cmake --build gui\build
.\gui\build\wowkispice_gui.exe

# 3. Environment gate (uses the project venv automatically)
.\run_selfcheck.bat

# 4. FFI bridge (27 passed, 0 failed)
cargo test -p wowkispice-ffi
```

## What It Does

- **Schematic Editor** — draw circuits (buck converters, etc.)
- **Waveform Viewer** — FFT, Bode, noise, Monte Carlo, measurements
- **Co-Sim Dashboard** — controller loop with GPIO/gate state
- **Code/Text Workspace** — run simulations, export netlists/BOM/PDF

The Rust co-simulation harness drives ngspice in lockstep with a controller law
whose ADC thresholds are derived from `firmware/esp32_buck_controller/src/main.c`.
The `firmware_control.dll` artifact exists and exports `buck_controller_tick`, but
**no shipped code path loads it**; the Rust hysteresis tests re-implement the same
logic and compare it against the Python mock. QEMU is retained only for historical
reference and legacy Python modules.

## Julia backend (optional)

The Rust core has an opt-in `julia` feature that links a pure-Rust JSON bridge to a
Julia-based circuit solver (`bridge/julia/solve_julia.jl`). The baseline build uses
**zero external dependencies**; the bridge is only compiled with `--features julia`.

```bash
# 1. Baseline — 369 passed, 0 failed (unchanged), no Julia dependency
cargo test -p wowkispice-core

# 2. With the Julia bridge — 379 passed, 0 failed (adds 10 bridge tests:
#    JSON serialization round-trip, whitespace/reordered/missing-field handling,
#    convergence-failure parsing, error-status detection)
cargo test -p wowkispice-core --features julia
```

The solver itself requires Julia ≥ 1.9 with `OrdinaryDiffEq.jl` and `JSON.jl` — locked in `bridge/julia/Project.toml` + `Manifest.toml`. Run `julia --project=bridge/julia -e "using Pkg; Pkg.instantiate()"` to install the exact pinned versions (see `JULIA_DEPLOYMENT_GUIDE.md`). CI uses the same lockfile with `actions/cache` for the Julia depot so repeat runs are instantaneous.
(see `JULIA_DEPLOYMENT_GUIDE.md` for the package install and `julia-ci.yml` for the
exact CI invocation, including the `"times"`/`"status"` output validation step).
The Julia solver is **not** bundled: it is a user-installed runtime dependency.

## Honest Boundaries

- **Core functionality** is verified and test-backed (369 Rust core tests, FFI bridge,
  Qt5 GUI, controller parity).
- **Distribution**: source+build plus a reproducible NSIS installer that bundles
  all Qt5/MinGW runtime DLLs. Installation on a machine with no developer
  toolchains is pending final verification. No PyPI, no pipx.
- **Platform**: Windows + MSYS2/MinGW; POSIX shell scripts exist but are not the
  verified primary path.
- **Emulator**: QEMU is deprecated and not part of the shipped co-simulation path.
  The shipped path is single-process ngspice + Rust controller.
- **Not a calibrated instrument**: this is an engineering laboratory tool, not a
  measurement-grade product.
- **Ongoing work**: parameter-sweep automation, clean-VM installer sign-off, and
  firmware migration to `esp-hal` + `rtic`.

## Reports

- [`BASELINE_REPORT.md`](BASELINE_REPORT.md) — test outputs, GUI verification, baseline
- [`FFI_CONSOLIDATION_REPORT.md`](FFI_CONSOLIDATION_REPORT.md) — frozen FFI API, diff matrix
- [`QEMU_REPLACEMENT_STATUS.md`](QEMU_REPLACEMENT_STATUS.md) — how the QEMU path was retired

## Install — Windows (MSYS2)

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1   # venv, deps, ngspice DLL, Qt5 Charts
cargo test -p wowkispice-core                        # verify: 369 passed
.\run_selfcheck.bat                                  # environment gate: SELF-CHECK: PASS
.\gui\build\wowkispice_gui.exe                       # launch GUI
```

`setup.ps1` now checks for Qt5 Charts headers and installs
`mingw-w64-ucrt-x86_64-qt5-charts` via pacman (falling back to a direct
`repo.msys2.org` download if mirrors fail) before the GUI build step. On POSIX
systems, install the equivalent package (`qt5-charts` or `qt5-qtcharts`) before
running `setup.sh`.

`run_selfcheck.bat` invokes `.venv\Scripts\python.exe` directly, so it works from a
clean shell with no virtualenv activated. `tools/selfcheck.py` re-executes itself
under the project interpreter when started with another `python`.

## Key Modules

- `crates/wowkispice-core` — Rust dependency-free core (334 tests)
- `crates/wowkispice-ffi` — hand-written `extern "C"` bridge to ngspice.dll
- `crates/parity/` — Rust vs Python parity harnesses per module
- `gui/` — C++/Qt5 GUI, 4-tab QTabWidget, CMake/Ninja build
- `firmware/esp32_buck_controller/` — C firmware + `firmware_control.dll` artifact
- `bridge/` — Python ngspice wrapper, control law, legacy QEMU orchestrator
- `tools/` — setup scripts, CLI, self-check, cleanup, qualification

## License

Apache-2.0. See [LICENSE](LICENSE). Third-party obligations: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
