# PROJECT_WOWKISPICE ⚡

> **High-Performance Mixed-Signal Hardware-Software Co-Simulator**  
> Closed-loop co-simulation of a real analog circuit (`libngspice`) against a
> control law imported from real microcontroller firmware source.
>
> **Read this first:** the compiled firmware binary is *parsed, not executed*.
> What runs is the decision logic and its constants, lifted from the firmware's
> own `#define`s — see [the limitation, stated plainly](#firmware-execution-status).
> The Renode path exists as a script but has never been run.

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

### 1. Setup — from a fresh clone

PROJECT_WOWKISPICE needs two things that are not in the repository: a Python
environment, and the `libngspice` shared library (the analytic solver is the
whole point — nothing here is faked).

**Windows**
```powershell
git clone <this-repo>
cd PROJECT_WOWKISPICE
powershell -ExecutionPolicy Bypass -File setup.ps1
```

**Linux / macOS**
```bash
git clone <this-repo>
cd PROJECT_WOWKISPICE
./setup.sh
```

The scripts are idempotent — re-run them any time.

| Platform | What setup does |
|---|---|
| Windows | Creates `.venv`, installs `requirements.txt`, downloads the official `ngspice-47_dll_64.7z` (4.4 MB) from SourceForge, verifies its SHA-256, extracts it to `tools/ngspice_dll/`, and confirms the loader can actually bind it. |
| Linux / macOS | Creates `.venv`, installs `requirements.txt`, then requires a **system** ngspice, which ngspice does not publish prebuilt binaries for. `setup.sh` prints the exact `apt` / `dnf` / `pacman` / `brew` command. |

#### Why isn't ngspice committed?
It is 12.9 MB of vendor binary, and `tools/ngspice_dll/` is gitignored. The
setup scripts fetch it instead, so the repository stays small and the
dependency is explicit.

#### If you already have libngspice
```bash
export WOSP_NGSPICE_LIB=/full/path/to/libngspice.so   # Linux / macOS
```
The resolver checks, in order: an explicit `NgSpiceEngine(dll_path=...)`
argument, then `$WOSP_NGSPICE_LIB`, then the bundled Windows DLL, then
`ctypes.util.find_library("ngspice")`. It raises only if all four fail, and the
error lists every path it tried.

### 2. Verify the install
```powershell
.\run_tests.bat          # Windows
python tools/run_tests.py   # Linux / macOS
```
All 13 suites (176 tests) run against the real solver.

### 3. Launch the Schematic Editor (flagship PyQt5 app)
```powershell
python ui/schematic_editor.py
```

The editor is LTspice-shaped: component palette on the left, schematic canvas
in the middle, waveform viewer on the right, console + generated SPICE netlist
at the bottom.

| Gesture | Action |
|---|---|
| Place a part | Click it in the palette, then click the canvas |
| Wire | Click pin &rarr; click pin (Esc cancels) |
| Move / rotate | Drag a part (snaps to grid) / press <kbd>R</kbd> |
| Edit value | Right-click &rarr; *Edit Value* (or press <kbd>E</kbd>) |
| Label net | Right-click a wire &rarr; *Label Net* (or press <kbd>L</kbd>) |
| Simulate | <kbd>F2</kbd> — compiles the schematic to SPICE and solves it in the real `ngspice.dll` |
| Export | File menu: SPICE netlist (`.cir`), **KiCad schematic** (`.kicad_sch`), KiCad netlist (`.net`), BOM (`.csv`) |
| Undo / redo | <kbd>Ctrl+Z</kbd> / <kbd>Ctrl+Shift+Z</kbd> |
| Zoom / pan | Mouse wheel / drag |

The schematic is the single source of truth: `bridge/cad_engine.py` resolves the
component graph into nets (union-find over wires, alias-aware pins, ground
detection) and emits a real netlist, so what you draw is what gets simulated.

**KiCad export is real, not a stub.** `bridge/kicad_export.py` writes a genuine
KiCad 9/10 schematic (embedded `lib_symbols`, symbol instances at true pin
coordinates, wires, junctions and net labels) plus a KiCad netlist. It is
verified against a real install by `tests/test_kicad_export.py`, which runs
`kicad-cli sch export netlist` on the generated file and asserts KiCad resolves
the intended nets (skipped automatically when KiCad is not installed).

### MCU co-simulation (what is real, and what isn't)

Place an **MCU** symbol from the palette, wire its pins, then right-click it:

- **Load Firmware (.hex / .elf)** parses the image and reports facts read from
  the file: format, byte size, load address, entry point, section names, SHA-256.
- **Set GPIO Pin Profile (JSON)** declares what each pin does *open loop*:
  `{"GPIO18": {"mode": "square", "freq_hz": 1000, "duty": 0.5}}` (or
  `{"mode": "static", "level": 1}`).
- **F2** then drives each wired pin as a real SPICE source, so the analog solver
  sees genuine switching voltages. The **MCU / GPIO** tab reports what the solver
  produced: logic levels, V min/max, duty cycle, edge count and measured
  frequency — measured from the waveform, not copied from the declaration.

#### MCU boards, gestures, and simulation control

**Board symbols.** The palette carries Arduino Uno / Nano / Mega 2560, STM32F103
(blue pill), ESP32 and ESP32-S3 with their real header pin names — an Uno has
`D0`–`D13` and `A0`–`A5`, an F103 has `PB0`–`PB15` — so a GPIO profile written
against a sketch means the same thing here. Each board also gets its own KiCad
symbol; a test asserts the editor and KiCad pin counts agree, because a symbol
whose pins disagree with its exported twin silently produces a wrong schematic.

**Gestures.** Ctrl+click adds/removes from the selection, double-click rotates
one part in place (single-click still drags), `R` rotates the selection,
`Ctrl+Y` and `Ctrl+Shift+Z` both redo.

**Netlist editor.** The bottom dock has an editable SPICE pane next to the
read-only generated one. *Run this netlist* simulates your edits; *Import as
components* builds a schematic from them; *Reset to schematic* throws them away.
The reverse direction is deliberately not offered — a hand-written netlist line
has no pin coordinates, so there is nothing to draw.

**Simulation control.** Mode dropdown (Transient only / MCU only /
Co-simulation), accuracy presets (Accurate/Balanced/Fast) that scale timestep
and duration, a live progress bar, and **Stop** / `Ctrl+C` that interrupts a
running solve. The solver runs on a worker thread so the window stays responsive
and Stop is actually reachable. *Transient only* leaves MCU pins undriven and
says so in the netlist; *MCU only* shows firmware behaviour with no analog solve
and says that too.

**Pin Map** tab lists every wired pin with its net, hardware direction, role and
what drives it. The hardware column is inferred from the pin name and labelled
as such — only the datasheet is definitive.

**Serial** tab shows captured UART/print output with a live filter and a
truncation count, so a long capture never quietly lies about what it dropped.

#### Waveform analysis

The results pane has three tabs, all driven by the same solver output:

- **Waveforms** — left-click the plot to drop a cursor, again for a second one.
  The readout under the plot gives the LTspice ruler (Δt, ΔV, 1/Δt, slope) plus
  min/max/RMS/peak-to-peak for that trace. `Ctrl+K` clears cursors.
- **FFT** (`Ctrl+F`) — magnitude spectrum of the selected net in dB, with the
  dominant frequency, the bin width, the noise floor, and THD. THD is computed
  by summing the first 20 harmonic lobes; the pure-tone floor is ~0.06%, which
  matters because the naive "sum bins at integer multiples" approach reports a
  pure sine as 0.4% distorted.
- **Bode** (`Ctrl+B`) — runs its own `.ac` sweep, drawing gain and unwrapped
  phase, and reports the unity-gain crossover, phase margin and gain margin.
  If there is no crossover in range it says so instead of printing a margin
  that does not exist.

**Results menu** exports the solved data as CSV, any plot as PNG, and a
multi-page PDF report (one page per net, with statistics) via matplotlib — a
vector PDF rather than a screenshot in a wrapper.

#### Closed-loop control (the pin reacts to the circuit)

A declared profile is open loop: the pin plays a waveform regardless of what the
analog side is doing, so a regulator built that way cannot regulate. A
**control law** is different.

- **Import Control Law from Firmware (.c)** reads the real decision logic out of
  a firmware source — it picks up `#define ADC_LOW_THRESHOLD`,
  `#define ADC_HIGH_THRESHOLD` and `#define GATE_PIN` and builds a law that
  compares ADC counts at exactly those boundaries.
- **Set Control Law (JSON)** writes one by hand:
  `{"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
    "target_v": 3.3, "hysteresis_v": 0.05, "divider": 0.5}`
  (`"kind": "pwm"` with `carrier_hz`/`duty_gain` is also available).

The pin is then compiled as an `external` source, so ngspice calls back into
Python on every timestep: the law reads the **simulated** feedback net, quantises
it to a 12-bit ADC, decides, and returns the pin voltage for that instant. The
analog solver therefore sees a pin that reacts to the circuit.

Measured on the buck built in `tests/test_cosim_control.py` (law imported from
`firmware/esp32_buck_controller/src/main.c`, which targets 2048 counts ≈ 1.65 V
through a 1× divider):

| Load | Steady-state Vout | Pin duty | Switch events |
|------|-------------------|----------|---------------|
| 5 Ω  | 1.608 V           | 16 %     | 1500          |
| 1.5 Ω| 1.608 V           | 10 %     | 854           |
| 0.5 Ω| 1.610 V           | 2 %      | 52            |

Output holds target across a 10× load sweep while the pin's duty cycle visibly
responds — which it can only do if it is reading the circuit. Retuning the
thresholds moves the operating point (1024 counts → 0.825 V, 3072 counts →
2.481 V).

> **Limitation, stated plainly:** the firmware *binary* is still parsed, not
> executed. What executes is the decision logic and its constants, lifted from
> the firmware's own source. Running the compiled .elf needs an instruction-set
> emulator (Renode/QEMU) or a transpiler. The netlist says which mode a pin is in,
> and the editor never shows a behaviour the solver did not produce.

#### Firmware execution status

What each "firmware" capability actually does today:

| Capability | Status |
|---|---|
| Parse `.hex` / `.elf` (size, load address, entry point, sections, SHA-256) | **Works.** `bridge/firmware.py` |
| Import control constants from firmware **source** (`#define` regex) | **Works.** `bridge/control_law.py` |
| Declared GPIO pin profiles (authored JSON) | **Works.** `bridge/gpio_model.py` |
| Close the loop against a real ngspice solve | **Works.** `bridge/cosim_runner.py` |
| Execute compiled machine instructions | **Does not exist.** No decoder, no emulator, no transpiler. |
| Renode lockstep co-simulation | **Incomplete.** `bridge/renode_orchestrator.py --mode renode` shells out to `tools/renode/renode.exe`, which is gitignored and has never been run. |

There is no code path from a `.bin`/`.elf` to GPIO or ADC behaviour. Loading an
image gives you metadata; behaviour comes from separately importing the `.c`
source or hand-writing a law. See the architecture audit for details.

### 4. Launch Interactive LTspice-Style Workbench
```powershell
python ui/ltspice_workbench.py
```

### 5. Run Automated Co-Simulation Tests
```powershell
# Run baseline ctypes bridge test
python tests/test_ngspice_bridge.py

# Run closed-loop buck converter regulation test
python tests/test_closed_loop_buck.py

# Run line & load regulation parameter sweeps
python tests/test_parameter_sweeps.py

# Run reverse-engineered component library test
python tests/test_components_library.py

# Run schematic editor tests (headless, offscreen Qt)
python tests/test_schematic_editor.py

# Run KiCad export tests (uses kicad-cli if KiCad is installed)
python tests/test_kicad_export.py

# Run firmware loading + GPIO co-simulation tests
python tests/test_firmware_gpio.py

# Run closed-loop control-law co-simulation tests
python tests/test_cosim_control.py

# Run waveform analysis tests (cursors, FFT, Bode, metrics)
python tests/test_measurements.py

# Run editor workflow tests (MCU boards, gestures, netlist editor, sim control)
python tests/test_editor_workflow.py
```

---

## 📁 Repository Structure

* `bridge/` — Low-level `ngspice.dll` C-API ctypes bridge, the schematic→SPICE
  compiler (`cad_engine.py`), firmware parsers (`firmware.py`), GPIO models
  (`gpio_model.py`), closed-loop control laws (`control_law.py`), the
  co-simulation runner (`cosim_runner.py`), waveform analysis
  (`measurements.py`) and the FFT/Bode runner (`analysis_runner.py`),
  KiCad export and Renode MMIO peripherals.
* `circuits/` — SPICE netlists (Buck, Boost, RC Filter) & reverse-engineered component models (`circuits/components/models.lib`).
* `firmware/` — PlatformIO bare-metal C firmware project for ESP32.
* `ui/` — Flagship PyQt5 schematic editor (`schematic_editor.py`, `schematic_scene.py`,
  `schematic_items.py`, `schematic_symbols.py`), plus the older tkinter workbench
  (`ltspice_workbench.py`) and parameter dashboard.
* `tools/` — `prove_physics_engine.py` (solver proof harness), `run_tests.py`,
  `screenshot_editor.py` and `overnight_ollama.py` (local LLM batch runner).
  `tools/ngspice_dll/` and `tools/renode/` are gitignored vendor binaries;
  `setup.ps1` / `setup.sh` fetch ngspice on demand.
* `tests/` — Automated verification test suites and benchmark runners.
* `.github/workflows/` — Automated GitHub Actions CI/CD co-simulation workflow.
* `setup.ps1` / `setup.sh` — one-shot bootstrap (venv + deps + libngspice).
* `Dockerfile` & `docker-compose.yml` — Containerized headless execution setup.
  **Known broken:** they install a system `libngspice0` but predate the
  `find_library` fallback, and they copy neither `ui/` nor `tools/`.
