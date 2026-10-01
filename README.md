# PROJECT_WOWKISPICE ⚡

> **High-Performance Mixed-Signal Hardware-Software Co-Simulator**  
> Run real compiled microcontroller firmware (ESP32 via Renode/QEMU) in lockstep with true analog circuit physics (`libngspice`) on your desktop or CI/CD pipelines.

---

## 🏛️ Architecture Overview

```
┌────────────────────────────────────────────────────────┐
│                   DIGITAL FIRMWARE                     │
│  • Bare-metal ESP32 C code built with PlatformIO       │
│  • Emulated in Renode with virtual clock ticks         │
│  • Reads simulated ADC register, outputs GPIO states   │
└───────────────────────────┬────────────────────────────┘
                            │
              LOCKSTEP SYNCHRONIZATION BRIDGE
       • Advances digital MCU by quantum dt
       • Extracts GPIO logic state (0 or 1)
       • Solves analog equations in ngspice for dt
       • Samples feedback node voltage & writes to Renode ADC
                            │
┌───────────────────────────┴────────────────────────────┐
│                    ANALOG CIRCUIT                      │
│  • Buck / Boost / Power Stages & Motor Subcircuits     │
│  • ngspice solving non-linear DAEs & RLC matrices      │
└────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart Guide

### 1. Environment Setup (Windows / Linux)
```powershell
# Create Python virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Launch Interactive LTspice-Style Workbench
```powershell
python ui/ltspice_workbench.py
```

### 3. Run Automated Co-Simulation Tests
```powershell
# Run baseline ctypes bridge test
python tests/test_ngspice_bridge.py

# Run closed-loop buck converter regulation test
python tests/test_closed_loop_buck.py

# Run line & load regulation parameter sweeps
python tests/test_parameter_sweeps.py

# Run reverse-engineered component library test
python tests/test_components_library.py
```

---

## 📁 Repository Structure

* `bridge/` — Low-level `ngspice.dll` C-API ctypes bridge & Renode MMIO peripherals.
* `circuits/` — SPICE netlists (Buck, Boost, RC Filter) & reverse-engineered component models (`circuits/components/models.lib`).
* `firmware/` — PlatformIO bare-metal C firmware project for ESP32.
* `ui/` — Desktop Workbench GUI (`ltspice_workbench.py`) and parameter dashboard.
* `tests/` — Automated verification test suites and benchmark runners.
* `.github/workflows/` — Automated GitHub Actions CI/CD co-simulation workflow.
* `Dockerfile` & `docker-compose.yml` — Containerized headless execution setup.
