# WOWKISPICE — mixed-signal virtual lab for power electronics

WOWKISPICE is a Windows-first tool that lets a user draw a power-electronics schematic
(e.g., a buck converter), simulate it with a real ngspice solver, and close the loop
with embedded controller firmware. The goal: a single-process Rust solver that loads
firmware at each timestep, eliminating Python IPC and QEMU dependencies.

## Quick Literal

| Component | Status |
|---|---|
| **Rust core** (`crates/wowkispice-core`) | 328 tests pass, zero `cargo test -D warnings` |
| **FFI bridge** (`crates/wowkispice-ffi`) | 24/26 pass; 2 pre-existing DLL-load env failures (documented) |
| **Qt5 GUI** (`gui/`) | `wowkispice_gui.exe` compiles with `-Wall -Wextra -Werror`; 4 tabs |
| **Hysteretic controller** | DLL-driven logic matches Python mock exactly (3 verified tests) |
| **Docker** | Desktop 4.98.0 verified; `docker info` works |
| **Parity harnesses** | 3 modules print `PARITY OK — N values identical` |

## Try It Instantly

```bash
# 1. Core tests (328/328, 0 warnings)
cargo test -p wowkispice-core

# 2. Launch the GUI (4-tab window)
cmake -S gui . -B gui\build -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=C:\msys64\ucrt64
cmake --build gui\build
.\gui\build\wowkispice_gui.exe

# 3. FFI bridge (24/26 pass)
cargo test -p wowkispice-ffi

# 4. Docker info
docker info
```

## What It Does

- **Schematic Editor** — draw circuits (buck converters, etc.)
- **Waveform Viewer** — FFT, Bode, noise, Monte Carlo, measurements
- **Co-Sim Dashboard** — hysteretic controller with GPIO state
- **Code/Text Workspace** — run simulations, export netlists/BOM/PDF

The Rust core calls `buck_controller_tick` from `firmware_control.dll` at each
timestep, passing the ngspice-sampled ADC value, and captures the GPIO state —
a single-process co-simulation loop with no QEMU dependency.

## Try It

```bash
cargo test -p wowkispice-core    # 328 pass, 0 warnings
cmake -S gui . -B gui\build && cmake --build gui\build
.\gui\build\wowkispice_gui.exe   # 4-tab window
cargo test -p wowkispice-ffi    # 24/26 pass
docker info                      # Docker verified
```

## Honest Boundaries

- **Core functionality** is verified and test-backed (328 Rust tests, FFI bridge,
  Qt5 GUI, hysteretic controller DLL).
- **Distribution**: source+build only; no Windows installer, no PyPI, no pipx.
- **Platform**: Windows + MSYS2/MinGW; not Linux/macOS out of the box.
- **Emulator**: QEMU replaced by native `firmware_control.dll`; QEMU is deprecated
  but still available for historical reference.
- **Not a calibrated instrument**: this is an engineering laboratory tool, not a
  measurement-grade product.
- **Ongoing work**: PyQt6 upgrade, parameter-sweep automation, Windows installer,
  firmware migration to `esp-hal` + `rtic` (roadmap Phases 3–6).

## Quick Literal

| Check | Result |
|---|---|
| `cargo test -p wowkispice-core` | 328 passed, 0 failed, 0 warnings |
| `cargo test -p wowkispice-ffi` | 24/26 pass (2 DLL-load env failures) |
| `wowkispice_gui.exe` | 4 tabs, zero compiler warnings |
| `docker info` | Docker Desktop 4.98.0, WSL2 backend |
| `cargo test -p wowkispice-core test_hysteresis` | 3/3 tests pass |

## Reports

- [`BASELINE_REPORT.md`](BASELINE_REPORT.md) — full test outputs, GUI verification, baseline
- [`FFI_CONSOLIDATION_REPORT.md`](FFI_CONSOLIDATION_REPORT.md) — frozen FFI API, diff matrix
- [`QEMU_REPLACEMENT_STATUS.md`](QEMU_REPLACEMENT_STATUS.md) — DLL path won; legacy QEMU

## Install — Windows (MSYS2)

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1   # venv, deps, DLL
cargo test -p wowkispice-core    # verify
.\gui\build\wowkispice_gui.exe   # launch GUI
```

## Supported Emulator

The firmware runs via `firmware_control.dll` — a native DLL compiled from
`buck_controller_tick.c`. QEMU is deprecated; the DLL is the standard co-simulation
path. WSL2+patched QEMU is available for historical reference only.

## Key Modules

- `crates/wowkispice-core` — Rust dependency-free core (328 tests)
- `crates/wowkispice-ffi` — hand-written `extern "C"` bridge to ngspice.dll
- `crates/parity/` — Rust vs Python parity harnesses per module
- `gui/` — C++/Qt5 GUI, 4-tab QTabWidget, CMake/Ninja build
- `firmware/esp32_buck_controller/` — C firmware + `firmware_control.dll`
- `bridge/` — Python ngspice wrapper, control law, hysteretic logic, QEMU orchestrator (deprecated)
- `tools/` — setup scripts, CLI, cleanup, qualification

## License

Apache-2.0. See [LICENSE](LICENSE).

## Contact

This repository is active under the roadmap: Phases 0–2 complete; Phases 3–6
(PyQt6, parameter-sweep, installer, firmware migration) planned.