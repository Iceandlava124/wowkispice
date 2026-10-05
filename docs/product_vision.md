# Product Vision: WOSP (The Co-Simulation EDA Platform)

## 1. Executive Summary
WOSP is an open-source, desktop-native circuit design and co-simulation platform tailored for embedded systems engineers. It bridges the gap between raw analog hardware and microcontroller firmware by combining an LTspice-compatible user experience, an industrial-grade analog solver (ngspice), real-time MCU emulation, and an AI-driven design assistant.

## 2. Core Value Proposition
- Analog Fidelity: Powered by ngspice for true transistor-level physics.
- MCU Co-Simulation: Load .hex or .elf firmware files and co-simulate GPIO interactions alongside analog circuitry.
- Familiar EDA UX: Replicates LTspice schematic capture gestures, hotkeys, and menu layouts.
- AI Design Assistant: Integrates context-aware agents to suggest component values and optimize efficiency.

## 3. High-Level Architecture
- ui/: PyQt5 schematic editor and PyQtGraph waveform viewer.
- circuits/: ngspice wrappers, netlist generators, and solvers.
- bridge/: Co-simulation synchronization loop coupling analog time steps with MCU instructions.
- firmware/: MCU binary parsing and peripheral loading.
- tests/: Pytest unit test suite.
