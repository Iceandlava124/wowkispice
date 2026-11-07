# WOWKISPICE Quickstart

## Get Up and Running in 5 Minutes

### 1. Prerequisites

- Windows 10/11
- [MSYS2 UCRT64](https://www.msys2.org/) (includes MinGW, CMake, Ninja)
- Git
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (optional, for container workflows)

### 2. Clone and Install

```bash
git clone <repo-url>
cd wosp

# Run the improved setup script
.\setup.ps1
# Or on Linux/macOS: . setup.sh

# Verify installation
cargo test -p wowkispice-core  # should be 328/328 pass
```

### 3. Launch the GUI

```bash
cmake -S gui . -B gui\build -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=C:\msys64\ucrt64
cmake --build gui\build
.\gui\build\wowkispice_gui.exe
```

You should see a 4-tab window:
- **Schematic Editor** — draw power-electronics circuits
- **Waveform Viewer** — plot simulation results (FFT, Bode, noise, Monte Carlo)
- **Co-Sim Dashboard** — hysteretic controller dashboard with GPIO state
- **Code/Text Workspace** — run simulations, stop, clear

### 4. Run the Test Suite

```bash
# Rust core tests (328 pass, zero warnings)
cargo test -p wowkispice-core

# FFI bridge tests (27/27 pass)
cargo test -p wowkispice-ffi

# Parity harnesses (Rust vs Python comparison)
cargo run -p parity --bin parity_analysis_runner
cargo run -p parity --bin parity_mock_controller
cargo run -p parity --bin parity_studio_engine
# Should print: PARITY OK — N values identical
```

### 5. Docker (optional)

```bash
docker info  # Verify Docker Desktop is running
docker build -t wosp .  # Build the Docker image
```

### 6. Next Steps

- Check the **FFI Consolidation Report** for bridge details
- Review the **Hysteresis Controller** tests (`test_buck_controller_hysteresis.rs`)
- Read the **Roadmap** for upcoming features
- Contribute via `CONTRIBUTING.md`

---

## Need Help?

- `cargo run -p parity --bin parity_analysis_runner` — see Rust vs Python comparison
- `python bridge/analysis_runner.py spice_value 1k` — test SPICE value parser
- `docker info` — verify Docker environment
- `python tools/cli.py --help` — CLI command reference