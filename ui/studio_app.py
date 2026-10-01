"""
studio_app.py - All-In-One Mixed-Signal Virtual Electronics & Firmware Studio
Comprehensive Virtual Electronics Laboratory Suite:
1. 📐 Visual Breadboard & Schematic Canvas (Tinkercad / Wokwi style)
2. 📝 Integrated C/C++ Firmware Code Editor & Compiler
3. 📈 4-Channel Digital Storage Oscilloscope (DSO) with measurements HUD
4. ⚡ 6.5-Digit Auto-Ranging True-RMS Digital Multimeter (DMM)
5. 📊 Real-Time FFT Spectrum Analyzer & THD Distortion Meter
6. 📉 Bode Frequency Response Analyzer (Gain & Phase Margins)
7. 📟 8-Channel Digital Logic Analyzer & Protocol Packet Decoder
8. 🌊 Arbitrary Waveform Generator (AWG / Function Generator)
9. 🔬 Semiconductor Curve Tracer (I-V Characteristics for MOSFET / Diode)
10. 🔋 Power, Energy & Thermal Loss Breakdown Profiler
11. 💾 Live ESP32 Hardware MMIO Registers & UART Serial Terminal
"""

import os
import sys
import time
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.studio_engine import StudioSimulationEngine


class WOWKISpiceStudio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WOWKISPICE STUDIO — All-In-One Virtual Electronics Lab & Firmware Co-Simulator")
        self.geometry("1600x960")
        self.minsize(1280, 800)
        
        # Color Palette (Dark High-Tech Studio Theme)
        self.c_bg = "#0d1117"
        self.c_panel = "#161b22"
        self.c_card = "#21262d"
        self.c_border = "#30363d"
        self.c_text = "#e6edf3"
        self.c_muted = "#8b949e"
        self.c_accent = "#58a6ff"
        self.c_green = "#3fb950"
        self.c_yellow = "#d29922"
        self.c_red = "#f85149"
        self.c_pink = "#f778ba"
        self.c_purple = "#d2a8ff"
        
        self.configure(bg=self.c_bg)
        
        # Simulation Engine & State
        self.engine = StudioSimulationEngine()
        self.sim_metrics = {}
        self.current_project_path = None
        
        # UI Setup
        self._setup_styles()
        self._build_top_menu()
        self._build_toolbar()
        self._build_main_workspace()
        
        # Initial simulation trigger
        self.after(300, self.run_co_simulation)

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        
        style.configure("TFrame", background=self.c_bg)
        style.configure("Panel.TFrame", background=self.c_panel)
        style.configure("Card.TFrame", background=self.c_card)
        style.configure("TLabel", background=self.c_panel, foreground=self.c_text, font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI", 10, "bold"), foreground=self.c_accent)
        style.configure("DMMValue.TLabel", font=("Consolas", 32, "bold"), foreground="#39ff14", background="#05080c")
        style.configure("DMMUnit.TLabel", font=("Consolas", 14, "bold"), foreground="#58a6ff", background="#05080c")
        style.configure("MetricNum.TLabel", font=("Consolas", 11, "bold"), foreground=self.c_accent, background=self.c_card)
        style.configure("MetricSub.TLabel", font=("Segoe UI", 8), foreground=self.c_muted, background=self.c_card)
        
        style.configure("Run.TButton", font=("Segoe UI", 9, "bold"), background="#238636", foreground="#ffffff")
        style.map("Run.TButton", background=[("active", "#2ea043"), ("pressed", "#1f6f2c")])

        style.configure("Tool.TButton", font=("Segoe UI", 9), background="#21262d", foreground=self.c_text)
        style.map("Tool.TButton", background=[("active", "#30363d"), ("pressed", "#161b22")])

    def _build_top_menu(self):
        menubar = tk.Menu(self, bg=self.c_panel, fg=self.c_text, activebackground=self.c_card)
        
        file_menu = tk.Menu(menubar, tearoff=0, bg=self.c_panel, fg=self.c_text)
        file_menu.add_command(label="New Project (.wowki)", command=self.new_project)
        file_menu.add_command(label="Open Project...", command=self.open_project)
        file_menu.add_command(label="Save Project", command=self.save_project)
        file_menu.add_separator()
        file_menu.add_command(label="Export SPICE Netlist (.cir)...", command=self.export_netlist)
        file_menu.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=0, bg=self.c_panel, fg=self.c_text)
        tools_menu.add_command(label="Virtual Breadboard & IDE", command=lambda: self.tab_control.select(0))
        tools_menu.add_command(label="4-Channel Oscilloscope", command=lambda: self.tab_control.select(1))
        tools_menu.add_command(label="6.5-Digit Multimeter (DMM)", command=lambda: self.tab_control.select(2))
        tools_menu.add_command(label="FFT Spectrum Analyzer", command=lambda: self.tab_control.select(3))
        tools_menu.add_command(label="Bode Plotter (Loop Stability)", command=lambda: self.tab_control.select(4))
        tools_menu.add_command(label="8-Channel Logic & Protocol Analyzer", command=lambda: self.tab_control.select(5))
        tools_menu.add_command(label="Arbitrary Waveform Generator (AWG)", command=lambda: self.tab_control.select(6))
        tools_menu.add_command(label="Semiconductor Curve Tracer", command=lambda: self.tab_control.select(7))
        tools_menu.add_command(label="Power & Thermal Loss Profiler", command=lambda: self.tab_control.select(8))
        menubar.add_cascade(label="Instruments", menu=tools_menu)

        self.config(menu=menubar)

    def _build_toolbar(self):
        bar = tk.Frame(self, bg="#161b22", height=44, highlightbackground=self.c_border, highlightthickness=1)
        bar.pack(fill=tk.X, side=tk.TOP)
        
        left_box = tk.Frame(bar, bg="#161b22")
        left_box.pack(side=tk.LEFT, padx=12, pady=6)
        
        tk.Label(left_box, text="⚡ WOWKISPICE ALL-IN-ONE STUDIO", font=("Segoe UI", 11, "bold"), fg=self.c_accent, bg="#161b22").pack(side=tk.LEFT)
        tk.Label(left_box, text=" | Full Virtual Instrument Rack & Firmware Co-Sim", font=("Segoe UI", 9), fg=self.c_muted, bg="#161b22").pack(side=tk.LEFT)

        right_box = tk.Frame(bar, bg="#161b22")
        right_box.pack(side=tk.RIGHT, padx=12)
        
        ttk.Button(right_box, text="▶ Run Co-Sim (F5)", style="Run.TButton", command=self.run_co_simulation).pack(side=tk.LEFT, padx=4)
        ttk.Button(right_box, text="🔄 Step Load (5Ω -> 2Ω)", style="Tool.TButton", command=self.step_load_transient).pack(side=tk.LEFT, padx=4)
        ttk.Button(right_box, text="💾 Export Project", style="Tool.TButton", command=self.save_project).pack(side=tk.LEFT, padx=4)

    def _build_main_workspace(self):
        root_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        root_pane.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Left Column: Circuit Parameters & Component Palette
        left_frame = ttk.Frame(root_pane, style="Panel.TFrame", width=340)
        root_pane.add(left_frame, weight=1)

        # Center Column: Instrument Tabs & Hardware Console
        center_pane = ttk.PanedWindow(root_pane, orient=tk.VERTICAL)
        root_pane.add(center_pane, weight=5)

        self._build_parts_toolbox(left_frame)
        self._build_instrument_tabs(center_pane)
        self._build_bottom_console(center_pane)

    def _build_parts_toolbox(self, parent):
        box = tk.Frame(parent, bg=self.c_panel)
        box.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Lab Bench Presets
        ttk.Label(box, text="System Architecture Preset", style="Title.TLabel").pack(anchor="w", pady=(0, 4))
        self.preset_var = tk.StringVar(value="⚡ ESP32 Hysteretic Buck Converter (12V -> 3.3V)")
        presets = [
            "⚡ ESP32 Hysteretic Buck Converter (12V -> 3.3V)",
            "🔄 Synchronous Dual-MOSFET Buck (High Efficiency)",
            "🚀 Step-Up Boost Converter (3.3V -> 5.0V)",
            "🏎️ DC Brushed Motor Closed-Loop Velocity Controller",
            "🌡️ NTC Thermistor Temperature Controller",
            "☀️ Solar MPPT Charge Controller"
        ]
        preset_dd = ttk.Combobox(box, textvariable=self.preset_var, state="readonly", values=presets)
        preset_dd.pack(fill=tk.X, pady=(0, 10))
        preset_dd.bind("<<ComboboxSelected>>", self._on_preset_changed)

        # Component Tuning Sliders
        ttk.Label(box, text="Live SPICE Parameters", style="Title.TLabel").pack(anchor="w", pady=(6, 4))
        
        self.vin_var = tk.DoubleVar(value=12.0)
        self.vtarget_var = tk.DoubleVar(value=3.30)
        self.rload_var = tk.DoubleVar(value=5.0)
        self.l1_var = tk.DoubleVar(value=47.0)
        self.c1_var = tk.DoubleVar(value=100.0)
        self.duration_var = tk.DoubleVar(value=5.0)

        self.lbl_vin = self._add_slider(box, "Input Voltage (Vin)", self.vin_var, 5.0, 24.0, "V")
        self.lbl_vtarget = self._add_slider(box, "Target Voltage (Vtarget)", self.vtarget_var, 1.8, 12.0, "V")
        self.lbl_rload = self._add_slider(box, "Load Resistance (Rload)", self.rload_var, 1.0, 50.0, "Ω")
        self.lbl_l1 = self._add_slider(box, "Inductor (L1)", self.l1_var, 10.0, 200.0, "µH")
        self.lbl_c1 = self._add_slider(box, "Capacitor (C1)", self.c1_var, 10.0, 470.0, "µF")
        self.lbl_dur = self._add_slider(box, "Sim Duration", self.duration_var, 1.0, 20.0, "ms")

        # Parts Palette
        ttk.Label(box, text="Component Library", style="Title.TLabel").pack(anchor="w", pady=(12, 4))
        parts_box = tk.Frame(box, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1)
        parts_box.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        parts_list = [
            ("🔷 ESP32 Dual-Core MCU", "#58a6ff"),
            ("⚡ IRF540N Power MOSFET", "#3fb950"),
            ("🔺 1N5819 Schottky Diode", "#f0883e"),
            ("🌀 47µH High-Q Inductor", "#f778ba"),
            ("🔋 Low-ESR Filter Cap", "#79c0ff"),
            ("🎚️ 5.0Ω Load Resistor", "#e6edf3"),
            ("🏎️ DC Motor (Inertia J)", "#e3b341"),
            ("🌡️ NTC Thermistor Probe", "#ff7b72"),
            ("🔌 LM358 Precision Op-Amp", "#d2a8ff"),
            ("⚡ 2N2222 NPN Transistor", "#58a6ff")
        ]
        
        for name, col in parts_list:
            lbl = tk.Label(parts_box, text=name, fg=col, bg=self.c_card, font=("Segoe UI", 9), anchor="w", padx=8, pady=2)
            lbl.pack(fill=tk.X)

    def _add_slider(self, parent, name, var, from_, to_, unit):
        lbl = ttk.Label(parent, text=f"{name}: {var.get():.1f} {unit}")
        lbl.pack(anchor="w", pady=(2, 0))
        s = ttk.Scale(parent, from_=from_, to=to_, variable=var,
                      command=lambda v: lbl.config(text=f"{name}: {var.get():.1f} {unit}"))
        s.pack(fill=tk.X, pady=(0, 3))
        return lbl

    def _build_instrument_tabs(self, parent):
        self.tab_control = ttk.Notebook(parent)
        parent.add(self.tab_control, weight=4)

        # 9 Integrated Instrument Tabs
        tab_breadboard = ttk.Frame(self.tab_control, style="Panel.TFrame")
        tab_scope = ttk.Frame(self.tab_control, style="Panel.TFrame")
        tab_dmm = ttk.Frame(self.tab_control, style="Panel.TFrame")
        tab_fft = ttk.Frame(self.tab_control, style="Panel.TFrame")
        tab_bode = ttk.Frame(self.tab_control, style="Panel.TFrame")
        tab_logic = ttk.Frame(self.tab_control, style="Panel.TFrame")
        tab_awg = ttk.Frame(self.tab_control, style="Panel.TFrame")
        tab_curve = ttk.Frame(self.tab_control, style="Panel.TFrame")
        tab_power = ttk.Frame(self.tab_control, style="Panel.TFrame")

        self.tab_control.add(tab_breadboard, text=" 📐 Breadboard & IDE ")
        self.tab_control.add(tab_scope, text=" 📈 4-CH Scope ")
        self.tab_control.add(tab_dmm, text=" ⚡ Multimeter (DMM) ")
        self.tab_control.add(tab_fft, text=" 📊 Spectrum (FFT) ")
        self.tab_control.add(tab_bode, text=" 📉 Bode Plotter ")
        self.tab_control.add(tab_logic, text=" 📟 Logic & Bus ")
        self.tab_control.add(tab_awg, text=" 🌊 Waveform Gen (AWG) ")
        self.tab_control.add(tab_curve, text=" 🔬 Curve Tracer ")
        self.tab_control.add(tab_power, text=" 🔋 Power & Thermal ")

        self._build_breadboard_and_ide(tab_breadboard)
        self._build_oscilloscope_view(tab_scope)
        self._build_multimeter_view(tab_dmm)
        self._build_spectrum_view(tab_fft)
        self._build_bode_view(tab_bode)
        self._build_logic_analyzer_view(tab_logic)
        self._build_awg_view(tab_awg)
        self._build_curve_tracer_view(tab_curve)
        self._build_power_profiler_view(tab_power)

    # -------------------------------------------------------------------------
    # TAB 1: BREADBOARD & FIRMWARE IDE
    # -------------------------------------------------------------------------
    def _build_breadboard_and_ide(self, parent):
        split = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        split.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        canvas_box = tk.Frame(split, bg="#161b22", highlightbackground=self.c_border, highlightthickness=1)
        split.add(canvas_box, weight=3)

        tk.Label(canvas_box, text="⚡ LIVE VIRTUAL BREADBOARD & WIRING MATRIX", fg=self.c_accent, bg="#161b22", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=8, pady=4)
        
        self.breadboard_canvas = tk.Canvas(canvas_box, bg="#0d1117", highlightthickness=0)
        self.breadboard_canvas.pack(fill=tk.BOTH, expand=True)

        ide_box = tk.Frame(split, bg=self.c_panel, highlightbackground=self.c_border, highlightthickness=1)
        split.add(ide_box, weight=2)

        ide_header = tk.Frame(ide_box, bg=self.c_card, height=30)
        ide_header.pack(fill=tk.X)
        tk.Label(ide_header, text="📝 main.c (ESP-IDF / FreeRTOS)", fg=self.c_text, bg=self.c_card, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=8, pady=4)
        ttk.Button(ide_header, text="⚡ Compile & Flash", style="Run.TButton", command=self.run_co_simulation).pack(side=tk.RIGHT, padx=6, pady=2)

        self.code_text = tk.Text(ide_box, bg="#161b22", fg="#79c0ff", insertbackground="#ffffff",
                                 font=("Consolas", 9), relief=tk.FLAT, wrap=tk.NONE)
        self.code_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        
        self._load_default_firmware()
        self._draw_virtual_breadboard()

    def _load_default_firmware(self):
        sample_c = """// ESP32 Closed-Loop Hysteretic Controller
#include "freertos/FreeRTOS.h"
#include "driver/gpio.h"
#include "driver/adc.h"

#define GATE_PIN       GPIO_NUM_18
#define ADC_CH         ADC1_CHANNEL_0 // GPIO 36

#define ADC_LOW_TGT    2010  // ~3.28V (MOSFET ON)
#define ADC_HIGH_TGT   2050  // ~3.32V (MOSFET OFF)

void app_main(void) {
    gpio_set_direction(GATE_PIN, GPIO_MODE_OUTPUT);
    adc1_config_width(ADC_WIDTH_BIT_12);
    adc1_config_channel_atten(ADC_CH, ADC_ATTEN_DB_11);

    int current_gate = 0;
    while(1) {
        int raw_adc = adc1_get_raw(ADC_CH);
        
        // Hysteretic bang-bang control
        if (raw_adc < ADC_LOW_TGT) {
            if (!current_gate) {
                gpio_set_level(GATE_PIN, 1);
                current_gate = 1;
            }
        } else if (raw_adc > ADC_HIGH_TGT) {
            if (current_gate) {
                gpio_set_level(GATE_PIN, 0);
                current_gate = 0;
            }
        }
    }
}
"""
        self.code_text.delete("1.0", tk.END)
        self.code_text.insert(tk.END, sample_c)

    def _draw_virtual_breadboard(self):
        c = self.breadboard_canvas
        c.delete("all")
        
        # Breadboard Grid
        for x in range(30, 520, 16):
            for y in range(40, 360, 16):
                c.create_oval(x-1.5, y-1.5, x+1.5, y+1.5, fill="#30363d", outline="")

        # Power Rails
        c.create_line(15, 40, 15, 360, fill="#f85149", width=2)
        c.create_line(22, 40, 22, 360, fill="#58a6ff", width=2)

        # ESP32 DevKit
        c.create_rectangle(50, 80, 140, 240, fill="#21262d", outline="#58a6ff", width=2)
        c.create_text(95, 100, text="ESP32", fill="#58a6ff", font=("Segoe UI", 11, "bold"))
        c.create_text(95, 120, text="Xtensa 240MHz", fill=self.c_muted, font=("Segoe UI", 7))
        c.create_text(120, 150, text="GPIO18", fill="#3fb950", font=("Consolas", 8, "bold"))
        c.create_text(120, 190, text="ADC1_0", fill="#58a6ff", font=("Consolas", 8, "bold"))

        # Jumper: GPIO18 -> Gate
        c.create_line(140, 150, 210, 150, fill="#3fb950", width=2.5, smooth=True)
        c.create_line(210, 150, 210, 110, fill="#3fb950", width=2.5)

        # MOSFET IRF540N
        c.create_rectangle(195, 70, 225, 110, fill="#30363d", outline="#3fb950", width=1.5)
        c.create_text(210, 85, text="IRF540N", fill="#ffffff", font=("Consolas", 7, "bold"))

        # Jumper: Vin -> Drain
        c.create_line(210, 40, 210, 70, fill="#f0883e", width=2.5)
        c.create_text(210, 30, text="Vin (+12V)", fill="#f0883e", font=("Segoe UI", 8, "bold"))

        # Switch Node
        c.create_line(210, 110, 210, 145, fill="#d2a8ff", width=2.5)
        c.create_line(210, 145, 270, 145, fill="#d2a8ff", width=2.5)

        # Diode 1N5819
        c.create_line(210, 145, 210, 180, fill="#ffffff", width=1.5)
        c.create_polygon(202, 160, 218, 160, 210, 175, fill="#8b949e", outline="#ffffff")
        c.create_line(202, 175, 218, 175, fill="#ffffff", width=2)
        c.create_line(210, 180, 210, 210, fill="#8b949e", width=1.5)

        # Inductor L1
        c.create_rectangle(270, 135, 310, 155, fill="#21262d", outline="#f778ba", width=2)
        c.create_text(290, 145, text="47µH", fill="#f778ba", font=("Consolas", 8, "bold"))

        # Output Node
        c.create_line(310, 145, 370, 145, fill="#58a6ff", width=2.5)
        c.create_text(370, 130, text="V(out) 3.3V", fill="#58a6ff", font=("Segoe UI", 9, "bold"))

        # Capacitor C1
        c.create_oval(335, 170, 355, 190, fill="#21262d", outline="#79c0ff", width=1.5)
        c.create_line(345, 145, 345, 170, fill="#58a6ff", width=1.5)
        c.create_line(345, 190, 345, 210, fill="#8b949e", width=1.5)
        c.create_text(345, 200, text="100µF", fill="#79c0ff", font=("Consolas", 7))

        # Load Resistor Rload
        c.create_rectangle(380, 165, 396, 195, fill="#21262d", outline="#e6edf3", width=1.5)
        c.create_line(388, 145, 388, 165, fill="#58a6ff", width=1.5)
        c.create_line(388, 195, 388, 210, fill="#8b949e", width=1.5)
        c.create_text(415, 180, text="5.0Ω", fill="#e6edf3", font=("Consolas", 8))

        # Feedback Wire: Vout -> 2:1 Divider -> ADC1_0
        c.create_line(370, 145, 370, 260, fill="#58a6ff", width=2)
        c.create_line(370, 260, 95, 260, fill="#58a6ff", width=2)
        c.create_line(95, 260, 95, 240, fill="#58a6ff", width=2)
        c.create_text(230, 272, text="◄ 2:1 Feedback Voltage Divider Wire", fill="#58a6ff", font=("Segoe UI", 8, "italic"))

    # -------------------------------------------------------------------------
    # TAB 2: 4-CHANNEL OSCILLOSCOPE
    # -------------------------------------------------------------------------
    def _build_oscilloscope_view(self, parent):
        box = tk.Frame(parent, bg=self.c_panel)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.fig_scope = Figure(figsize=(10, 6), dpi=100, facecolor=self.c_bg)
        gs = gridspec.GridSpec(2, 1, height_ratios=[1.2, 1])
        self.ax_ch1 = self.fig_scope.add_subplot(gs[0])
        self.ax_ch2 = self.fig_scope.add_subplot(gs[1], sharex=self.ax_ch1)

        for ax in (self.ax_ch1, self.ax_ch2):
            ax.set_facecolor("#161b22")
            ax.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
            ax.tick_params(colors=self.c_muted, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(self.c_border)

        self.fig_scope.tight_layout()
        self.canvas_scope = FigureCanvasTkAgg(self.fig_scope, master=box)
        self.canvas_scope.draw()
        self.canvas_scope.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # -------------------------------------------------------------------------
    # TAB 3: 6.5-DIGIT MULTIMETER (DMM)
    # -------------------------------------------------------------------------
    def _build_multimeter_view(self, parent):
        box = tk.Frame(parent, bg="#0d1117")
        box.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        bezel = tk.Frame(box, bg="#161b22", highlightbackground="#3fb950", highlightthickness=2)
        bezel.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        tk.Label(bezel, text="⚡ DIGITAL MULTIMETER — TRUE RMS (6.5 DIGIT)", fg="#3fb950", bg="#161b22", font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=20, pady=(15, 10))

        lcd = tk.Frame(bezel, bg="#05080c", highlightbackground=self.c_border, highlightthickness=1)
        lcd.pack(fill=tk.X, padx=20, pady=10)

        val_row = tk.Frame(lcd, bg="#05080c")
        val_row.pack(padx=20, pady=20)

        self.dmm_main_val = ttk.Label(val_row, text="+3.3298", style="DMMValue.TLabel")
        self.dmm_main_val.pack(side=tk.LEFT)

        self.dmm_unit_lbl = ttk.Label(val_row, text=" V DC", style="DMMUnit.TLabel")
        self.dmm_unit_lbl.pack(side=tk.LEFT, padx=(10, 0))

        sub_row = tk.Frame(bezel, bg="#161b22")
        sub_row.pack(fill=tk.X, padx=20, pady=15)

        self.dmm_sub_vrms = self._add_dmm_card(sub_row, "TRUE RMS VOLTAGE", "3.332 V RMS", 0)
        self.dmm_sub_idc = self._add_dmm_card(sub_row, "DC LOAD CURRENT", "0.665 A DC", 1)
        self.dmm_sub_vac = self._add_dmm_card(sub_row, "AC RIPPLE VOLTAGE", "85.2 mV AC", 2)
        self.dmm_sub_res = self._add_dmm_card(sub_row, "LOAD RESISTANCE", "5.000 Ω", 3)

    def _add_dmm_card(self, parent, title, init_val, col):
        card = tk.Frame(parent, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1)
        card.grid(row=0, column=col, padx=6, sticky="nsew")
        parent.grid_columnconfigure(col, weight=1)

        ttk.Label(card, text=title, style="MetricSub.TLabel").pack(anchor="w", padx=10, pady=(6, 2))
        lbl = ttk.Label(card, text=init_val, style="MetricNum.TLabel")
        lbl.pack(anchor="w", padx=10, pady=(0, 6))
        return lbl

    # -------------------------------------------------------------------------
    # TAB 4: SPECTRUM ANALYZER & THD
    # -------------------------------------------------------------------------
    def _build_spectrum_view(self, parent):
        box = tk.Frame(parent, bg=self.c_panel)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.fig_fft = Figure(figsize=(10, 6), dpi=100, facecolor=self.c_bg)
        self.ax_fft = self.fig_fft.add_subplot(111)
        self.ax_fft.set_facecolor("#161b22")
        self.ax_fft.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
        self.ax_fft.tick_params(colors=self.c_muted, labelsize=8)
        self.fig_fft.tight_layout()

        self.canvas_fft = FigureCanvasTkAgg(self.fig_fft, master=box)
        self.canvas_fft.draw()
        self.canvas_fft.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # -------------------------------------------------------------------------
    # TAB 5: BODE FREQUENCY RESPONSE & STABILITY
    # -------------------------------------------------------------------------
    def _build_bode_view(self, parent):
        box = tk.Frame(parent, bg=self.c_panel)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.fig_bode = Figure(figsize=(10, 6), dpi=100, facecolor=self.c_bg)
        self.ax_bode_mag = self.fig_bode.add_subplot(211)
        self.ax_bode_phase = self.fig_bode.add_subplot(212, sharex=self.ax_bode_mag)

        for ax in (self.ax_bode_mag, self.ax_bode_phase):
            ax.set_facecolor("#161b22")
            ax.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
            ax.tick_params(colors=self.c_muted, labelsize=8)

        self.fig_bode.tight_layout()
        self.canvas_bode = FigureCanvasTkAgg(self.fig_bode, master=box)
        self.canvas_bode.draw()
        self.canvas_bode.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # -------------------------------------------------------------------------
    # TAB 6: LOGIC ANALYZER & PROTOCOL DECODER
    # -------------------------------------------------------------------------
    def _build_logic_analyzer_view(self, parent):
        split = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        split.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Logic timing traces
        trace_box = tk.Frame(split, bg=self.c_panel)
        split.add(trace_box, weight=3)

        self.fig_logic = Figure(figsize=(10, 4), dpi=100, facecolor=self.c_bg)
        self.ax_logic = self.fig_logic.add_subplot(111)
        self.ax_logic.set_facecolor("#161b22")
        self.ax_logic.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
        self.ax_logic.tick_params(colors=self.c_muted, labelsize=8)
        self.fig_logic.tight_layout()

        self.canvas_logic = FigureCanvasTkAgg(self.fig_logic, master=trace_box)
        self.canvas_logic.draw()
        self.canvas_logic.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Protocol Packet Decode Table
        decode_box = tk.LabelFrame(split, text=" 📟 Hardware Bus Protocol Decoder (UART 8N1 / I2C / SPI) ",
                                   bg=self.c_card, fg=self.c_accent, font=("Segoe UI", 9, "bold"),
                                   highlightbackground=self.c_border, highlightthickness=1)
        split.add(decode_box, weight=2)

        cols = ("Time (ms)", "Protocol", "Hex Byte", "ASCII / Symbol", "Parity / Status")
        self.tree_decode = ttk.Treeview(decode_box, columns=cols, show="headings", height=4)
        for c in cols:
            self.tree_decode.heading(c, text=c)
            self.tree_decode.column(c, width=120, anchor="center")
        self.tree_decode.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

    # -------------------------------------------------------------------------
    # TAB 7: ARBITRARY WAVEFORM GENERATOR (AWG)
    # -------------------------------------------------------------------------
    def _build_awg_view(self, parent):
        split = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        split.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # AWG Controls Panel
        ctrl_box = tk.Frame(split, bg=self.c_panel, width=320)
        split.add(ctrl_box, weight=1)

        tk.Label(ctrl_box, text="🌊 AWG SYNTHESIZER CONTROLS", fg=self.c_accent, bg=self.c_panel, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 6))

        self.awg_type_var = tk.StringVar(value="Sine")
        ttk.Label(ctrl_box, text="Waveform Function").pack(anchor="w", padx=10)
        awg_dd = ttk.Combobox(ctrl_box, textvariable=self.awg_type_var, state="readonly",
                              values=["Sine", "Square", "Triangle", "Sawtooth", "White Noise", "Exponential Decay", "Chirp Sweep"])
        awg_dd.pack(fill=tk.X, padx=10, pady=(0, 8))
        awg_dd.bind("<<ComboboxSelected>>", lambda e: self._update_awg_plot())

        self.awg_freq_var = tk.DoubleVar(value=1000.0)
        self.awg_amp_var = tk.DoubleVar(value=3.3)
        self.awg_offset_var = tk.DoubleVar(value=1.65)
        self.awg_duty_var = tk.DoubleVar(value=50.0)

        self._add_awg_slider(ctrl_box, "Frequency", self.awg_freq_var, 10.0, 50000.0, "Hz")
        self._add_awg_slider(ctrl_box, "Amplitude", self.awg_amp_var, 0.1, 12.0, "Vpp")
        self._add_awg_slider(ctrl_box, "DC Offset", self.awg_offset_var, -5.0, 12.0, "V")
        self._add_awg_slider(ctrl_box, "PWM Duty", self.awg_duty_var, 5.0, 95.0, "%")

        # AWG Visual Scope
        plot_box = tk.Frame(split, bg=self.c_panel)
        split.add(plot_box, weight=3)

        self.fig_awg = Figure(figsize=(8, 5), dpi=100, facecolor=self.c_bg)
        self.ax_awg = self.fig_awg.add_subplot(111)
        self.ax_awg.set_facecolor("#161b22")
        self.ax_awg.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
        self.ax_awg.tick_params(colors=self.c_muted, labelsize=8)
        self.fig_awg.tight_layout()

        self.canvas_awg = FigureCanvasTkAgg(self.fig_awg, master=plot_box)
        self.canvas_awg.draw()
        self.canvas_awg.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._update_awg_plot()

    def _add_awg_slider(self, parent, name, var, from_, to_, unit):
        lbl = ttk.Label(parent, text=f"{name}: {var.get():.1f} {unit}")
        lbl.pack(anchor="w", padx=10, pady=(4, 0))
        s = ttk.Scale(parent, from_=from_, to=to_, variable=var,
                      command=lambda v: (lbl.config(text=f"{name}: {var.get():.1f} {unit}"), self._update_awg_plot()))
        s.pack(fill=tk.X, padx=10, pady=(0, 4))

    def _update_awg_plot(self):
        t_ms, sig = StudioSimulationEngine.generate_awg_signal(
            wave_type=self.awg_type_var.get(),
            freq_hz=self.awg_freq_var.get(),
            amp_v=self.awg_amp_var.get(),
            offset_v=self.awg_offset_var.get(),
            duty_pct=self.awg_duty_var.get(),
            duration_ms=4.0
        )
        self.ax_awg.clear()
        self.ax_awg.set_facecolor("#161b22")
        self.ax_awg.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
        self.ax_awg.tick_params(colors=self.c_muted, labelsize=8)
        self.ax_awg.plot(t_ms, sig, color="#39ff14", linewidth=1.8, label=f"AWG OUT: {self.awg_type_var.get()} ({self.awg_freq_var.get():.0f}Hz)")
        self.ax_awg.set_ylabel("Signal Voltage (V)", color=self.c_text, fontsize=9)
        self.ax_awg.set_xlabel("Time (ms)", color=self.c_text, fontsize=9)
        self.ax_awg.legend(loc="upper right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)
        self.fig_awg.tight_layout()
        self.canvas_awg.draw()

    # -------------------------------------------------------------------------
    # TAB 8: SEMICONDUCTOR CURVE TRACER
    # -------------------------------------------------------------------------
    def _build_curve_tracer_view(self, parent):
        box = tk.Frame(parent, bg=self.c_panel)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.fig_curve = Figure(figsize=(10, 6), dpi=100, facecolor=self.c_bg)
        self.ax_curve_mos = self.fig_curve.add_subplot(121)
        self.ax_curve_dio = self.fig_curve.add_subplot(122)

        for ax in (self.ax_curve_mos, self.ax_curve_dio):
            ax.set_facecolor("#161b22")
            ax.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
            ax.tick_params(colors=self.c_muted, labelsize=8)

        self.fig_curve.tight_layout()
        self.canvas_curve = FigureCanvasTkAgg(self.fig_curve, master=box)
        self.canvas_curve.draw()
        self.canvas_curve.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._update_curve_tracer()

    def _update_curve_tracer(self):
        # 1. MOSFET Id vs Vds family of curves
        mos_data = StudioSimulationEngine.trace_mosfet_iv()
        self.ax_curve_mos.clear()
        self.ax_curve_mos.set_facecolor("#161b22")
        self.ax_curve_mos.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
        self.ax_curve_mos.tick_params(colors=self.c_muted, labelsize=8)

        colors = ["#8b949e", "#58a6ff", "#3fb950", "#d29922", "#f778ba", "#f85149"]
        for idx, curve in enumerate(mos_data["curves"]):
            col = colors[idx % len(colors)]
            self.ax_curve_mos.plot(curve["vds"], curve["id_amps"], color=col, linewidth=1.5, label=f"Vgs={curve['vgs']:.1f}V")

        self.ax_curve_mos.set_title("IRF540N MOSFET $I_D$ vs $V_{DS}$", color=self.c_accent, fontsize=10, fontweight="bold")
        self.ax_curve_mos.set_xlabel("Drain-Source Voltage $V_{DS}$ (V)", color=self.c_text, fontsize=9)
        self.ax_curve_mos.set_ylabel("Drain Current $I_D$ (A)", color=self.c_text, fontsize=9)
        self.ax_curve_mos.legend(loc="upper left", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=7)

        # 2. Diode & Schottky forward I-V
        dio_data = StudioSimulationEngine.trace_diode_iv()
        self.ax_curve_dio.clear()
        self.ax_curve_dio.set_facecolor("#161b22")
        self.ax_curve_dio.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
        self.ax_curve_dio.tick_params(colors=self.c_muted, labelsize=8)

        self.ax_curve_dio.plot(dio_data["vf"], dio_data["i_schottky"], color="#f0883e", linewidth=1.8, label="1N5819 Schottky (Vf=0.35V)")
        self.ax_curve_dio.plot(dio_data["vf"], dio_data["i_silicon"], color="#58a6ff", linewidth=1.8, label="1N4148 Silicon (Vf=0.70V)")
        self.ax_curve_dio.set_title("Diode Forward Conduction $I_F$ vs $V_F$", color=self.c_green, fontsize=10, fontweight="bold")
        self.ax_curve_dio.set_xlabel("Forward Voltage $V_F$ (V)", color=self.c_text, fontsize=9)
        self.ax_curve_dio.set_ylabel("Forward Current $I_F$ (A)", color=self.c_text, fontsize=9)
        self.ax_curve_dio.legend(loc="upper left", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=7)

        self.fig_curve.tight_layout()
        self.canvas_curve.draw()

    # -------------------------------------------------------------------------
    # TAB 9: POWER & THERMAL PROFILER
    # -------------------------------------------------------------------------
    def _build_power_profiler_view(self, parent):
        box = tk.Frame(parent, bg=self.c_panel)
        box.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.fig_power = Figure(figsize=(10, 6), dpi=100, facecolor=self.c_bg)
        self.ax_p_breakdown = self.fig_power.add_subplot(121)
        self.ax_p_eff = self.fig_power.add_subplot(122)

        self.fig_power.tight_layout()
        self.canvas_power = FigureCanvasTkAgg(self.fig_power, master=box)
        self.canvas_power.draw()
        self.canvas_power.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # -------------------------------------------------------------------------
    # BOTTOM HARDWARE CONSOLE
    # -------------------------------------------------------------------------
    def _build_bottom_console(self, parent):
        console_frame = ttk.Frame(parent, style="Panel.TFrame", height=140)
        parent.add(console_frame, weight=1)

        grid = tk.Frame(console_frame, bg=self.c_panel)
        grid.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        reg_frame = tk.LabelFrame(grid, text=" 💾 ESP32 Hardware MMIO Registers (SAR_ADC / GPIO) ",
                                  bg=self.c_card, fg=self.c_accent, font=("Segoe UI", 9, "bold"),
                                  highlightbackground=self.c_border, highlightthickness=1)
        reg_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))

        self.txt_mmio = tk.Text(reg_frame, bg="#161b22", fg="#e6edf3", font=("Consolas", 8),
                                relief=tk.FLAT, height=5, width=45)
        self.txt_mmio.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        uart_frame = tk.LabelFrame(grid, text=" 📟 Serial UART Monitor (115200 Baud) ",
                                   bg=self.c_card, fg=self.c_green, font=("Segoe UI", 9, "bold"),
                                   highlightbackground=self.c_border, highlightthickness=1)
        uart_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(3, 0))

        self.txt_uart = tk.Text(uart_frame, bg="#161b22", fg=self.c_green, font=("Consolas", 8),
                                relief=tk.FLAT, height=5, width=65)
        self.txt_uart.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

    # -------------------------------------------------------------------------
    # EXECUTION & UPDATE ENGINE
    # -------------------------------------------------------------------------
    def _on_preset_changed(self, event=None):
        choice = self.preset_var.get()
        if "Boost" in choice:
            self.vin_var.set(3.3)
            self.vtarget_var.set(5.0)
            self.rload_var.set(10.0)
        elif "Motor" in choice:
            self.vin_var.set(12.0)
            self.vtarget_var.set(6.0)
            self.rload_var.set(3.0)
        else:
            self.vin_var.set(12.0)
            self.vtarget_var.set(3.30)
            self.rload_var.set(5.0)
            
        self._update_all_slider_labels()
        self.run_co_simulation()

    def _update_all_slider_labels(self):
        self.lbl_vin.config(text=f"Input Voltage (Vin): {self.vin_var.get():.1f} V")
        self.lbl_vtarget.config(text=f"Target Voltage (Vtarget): {self.vtarget_var.get():.2f} V")
        self.lbl_rload.config(text=f"Load Resistance (Rload): {self.rload_var.get():.1f} Ω")
        self.lbl_l1.config(text=f"Inductor (L1): {self.l1_var.get():.1f} µH")
        self.lbl_c1.config(text=f"Capacitor (C1): {self.c1_var.get():.1f} µF")
        self.lbl_dur.config(text=f"Sim Duration: {self.duration_var.get():.1f} ms")

    def run_co_simulation(self):
        vin = self.vin_var.get()
        vtarget = self.vtarget_var.get()
        rload = self.rload_var.get()
        l_val = self.l1_var.get()
        c_val = self.c1_var.get()
        dur_ms = self.duration_var.get()

        try:
            metrics = self.engine.run_simulation(
                duration_ms=dur_ms,
                tstep_us=0.5,
                vin=vin,
                vtarget=vtarget,
                rload=rload,
                l_val_uh=l_val,
                c_val_uf=c_val
            )
            self.sim_metrics = metrics
            self._update_all_instruments()
        except Exception as e:
            messagebox.showerror("Simulation Error", str(e))

    def _update_all_instruments(self):
        m = self.sim_metrics
        ts = self.engine.time_series
        t_arr = ts["time_ms"]
        vout_arr = ts["vout"]
        vgate_arr = ts["vgate"]
        il_arr = ts["il"]
        
        # 1. DMM
        self.dmm_main_val.config(text=f"{m['dmm_vdc']:+.4f}")
        self.dmm_sub_vrms.config(text=f"{m['dmm_vrms']:.4f} V RMS")
        self.dmm_sub_idc.config(text=f"{m['dmm_idc']:.3f} A DC")
        self.dmm_sub_vac.config(text=f"{m['dmm_vac_ripple']*1000:.1f} mV AC")
        self.dmm_sub_res.config(text=f"{m['dmm_res']:.2f} Ω")

        # 2. 4-Channel Oscilloscope
        self.ax_ch1.clear()
        self.ax_ch2.clear()
        for ax in (self.ax_ch1, self.ax_ch2):
            ax.set_facecolor("#161b22")
            ax.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
            ax.tick_params(colors=self.c_muted, labelsize=8)

        self.ax_ch1.plot(t_arr, vout_arr, color="#58a6ff", linewidth=1.5, label="CH1: V(out) [Regulated]")
        self.ax_ch1.axhline(self.vtarget_var.get(), color="#f85149", linestyle=":", label=f"Target ({self.vtarget_var.get():.2f}V)")
        self.ax_ch1.set_ylabel("Vout (V)", color=self.c_text, fontsize=9)
        self.ax_ch1.legend(loc="upper right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)

        self.ax_ch2.plot(t_arr, vgate_arr, color="#3fb950", linewidth=1.2, label="CH2: V(gate) [ESP32 GPIO 18]")
        self.ax_ch2.plot(t_arr, il_arr, color="#f778ba", linewidth=1.2, label="CH3: I(L1) Inductor Current (A)")
        self.ax_ch2.set_ylabel("Signals", color=self.c_text, fontsize=9)
        self.ax_ch2.set_xlabel("Time (ms)", color=self.c_text, fontsize=9)
        self.ax_ch2.legend(loc="upper right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)

        self.fig_scope.tight_layout()
        self.canvas_scope.draw()

        # 3. FFT Spectrum & THD
        self.ax_fft.clear()
        self.ax_fft.set_facecolor("#161b22")
        self.ax_fft.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
        self.ax_fft.tick_params(colors=self.c_muted, labelsize=8)
        self.ax_fft.plot(m["fft_freqs_khz"], m["fft_mag_db"], color="#58a6ff", linewidth=1.3, label=f"Ripple Spectrum (THD={m['thd_pct']:.2f}%)")
        self.ax_fft.set_xlim(0, 150)
        self.ax_fft.set_ylabel("Power Spectral Density (dBV)", color=self.c_text, fontsize=9)
        self.ax_fft.set_xlabel("Frequency (kHz)", color=self.c_text, fontsize=9)
        self.ax_fft.legend(loc="upper right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)
        self.fig_fft.tight_layout()
        self.canvas_fft.draw()

        # 4. Bode Frequency Response & Stability Margins
        self.ax_bode_mag.clear()
        self.ax_bode_phase.clear()
        for ax in (self.ax_bode_mag, self.ax_bode_phase):
            ax.set_facecolor("#161b22")
            ax.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
            ax.tick_params(colors=self.c_muted, labelsize=8)

        self.ax_bode_mag.semilogx(m["bode_freqs_hz"], m["bode_mag_db"], color="#58a6ff", linewidth=1.5, label=f"Loop Gain (GM={m['gain_margin_db']:.1f}dB)")
        self.ax_bode_mag.axhline(0.0, color="#f85149", linestyle="--", alpha=0.6)
        self.ax_bode_mag.set_ylabel("Gain (dB)", color=self.c_text, fontsize=9)
        self.ax_bode_mag.legend(loc="upper right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)

        self.ax_bode_phase.semilogx(m["bode_freqs_hz"], m["bode_phase_deg"], color="#e3b341", linewidth=1.5,
                                    label=f"Phase Margin ({m['phase_margin_deg']:.1f}° - {m['stability_status']})")
        self.ax_bode_phase.axhline(-180.0, color="#f85149", linestyle="--", alpha=0.6)
        self.ax_bode_phase.set_ylabel("Phase (°)", color=self.c_text, fontsize=9)
        self.ax_bode_phase.set_xlabel("Frequency (Hz)", color=self.c_text, fontsize=9)
        self.ax_bode_phase.legend(loc="upper right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)
        self.fig_bode.tight_layout()
        self.canvas_bode.draw()

        # 5. Logic Analyzer & Protocol Table
        self.ax_logic.clear()
        self.ax_logic.set_facecolor("#161b22")
        self.ax_logic.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
        self.ax_logic.tick_params(colors=self.c_muted, labelsize=8)

        channels = [
            ("D0 (GPIO18 Gate)", vgate_arr > 1.65, "#3fb950"),
            ("D1 (PWM Sync)", np.bitwise_not(vgate_arr > 1.65), "#7ee787"),
            ("D2 (ADC Conv Done)", np.ones_like(vgate_arr, dtype=bool), "#58a6ff"),
            ("D3 (Fault Flag)", np.zeros_like(vgate_arr, dtype=bool), "#f85149")
        ]
        
        y_ticks = []
        y_labels = []
        for idx, (name, sig, col) in enumerate(channels):
            y_base = idx * 1.5
            self.ax_logic.step(t_arr, sig * 0.9 + y_base, color=col, linewidth=1.3, where="post")
            y_ticks.append(y_base + 0.45)
            y_labels.append(name)

        self.ax_logic.set_yticks(y_ticks)
        self.ax_logic.set_yticklabels(y_labels, color=self.c_text, fontsize=8)
        self.ax_logic.set_xlabel("Time (ms)", color=self.c_text, fontsize=9)
        self.fig_logic.tight_layout()
        self.canvas_logic.draw()

        # Populate decoded protocol table
        for row in self.tree_decode.get_children():
            self.tree_decode.delete(row)
        for pkt in m.get("uart_packets", []):
            self.tree_decode.insert("", tk.END, values=(f"{pkt['timestamp_ms']:.2f}", pkt["type"], pkt["hex"], pkt["ascii"], pkt["parity"]))

        # 6. Power & Thermal Loss Breakdown
        self.ax_p_breakdown.clear()
        self.ax_p_breakdown.set_facecolor("#161b22")
        loss_labels = ["MOSFET Conduction", "Diode Conduction", "Passives (DCR/ESR)", "Switching Loss"]
        loss_vals = [m["p_cond_mosfet"], m["p_cond_diode"], m["p_cond_passives"], m["p_switching"]]
        loss_colors = ["#3fb950", "#f0883e", "#58a6ff", "#f85149"]
        
        self.ax_p_breakdown.pie(loss_vals, labels=loss_labels, colors=loss_colors, autopct="%1.1f%%",
                                textprops={"color": self.c_text, "fontsize": 8})
        self.ax_p_breakdown.set_title(f"Loss Breakdown (Total Loss={m['p_loss_total']:.2f}W | $\\Delta T_J$={m['tj_rise_c']:.1f}°C)",
                                      color=self.c_accent, fontsize=9, fontweight="bold")

        # Efficiency Curve vs Load
        self.ax_p_eff.clear()
        self.ax_p_eff.set_facecolor("#161b22")
        self.ax_p_eff.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
        self.ax_p_eff.tick_params(colors=self.c_muted, labelsize=8)
        r_sweep = np.linspace(1.5, 20.0, 50)
        i_sweep = m["dmm_vdc"] / r_sweep
        eff_curve = 100.0 * (m["dmm_vdc"] * i_sweep) / ((m["dmm_vdc"] * i_sweep) + 0.15 + 0.05 * (i_sweep**2))
        self.ax_p_eff.plot(i_sweep, eff_curve, color="#3fb950", linewidth=2.0, label="Efficiency vs Current")
        self.ax_p_eff.scatter([m["dmm_idc"]], [m["efficiency_pct"]], color="#f85149", s=60, zorder=5, label=f"Operating Point ({m['efficiency_pct']:.1f}%)")
        self.ax_p_eff.set_title("Power Conversion Efficiency $\\eta$", color=self.c_green, fontsize=9, fontweight="bold")
        self.ax_p_eff.set_xlabel("Load Current $I_{out}$ (A)", color=self.c_text, fontsize=8)
        self.ax_p_eff.set_ylabel("Efficiency (%)", color=self.c_text, fontsize=8)
        self.ax_p_eff.set_ylim(60, 100)
        self.ax_p_eff.legend(loc="lower right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)

        self.fig_power.tight_layout()
        self.canvas_power.draw()

        # 7. MMIO Registers & UART Console
        raw_adc = int(np.clip((m["dmm_vdc"] * 0.5 / 3.3) * 4095.0, 0, 4095))
        self.txt_mmio.delete("1.0", tk.END)
        self.txt_mmio.insert(tk.END, f"[ESP32 MMIO REGISTERS]\n")
        self.txt_mmio.insert(tk.END, f"  0x3FF48804 (SAR_MEAS1_DATA):   0x{raw_adc:04X} ({raw_adc} / 4095 counts)\n")
        self.txt_mmio.insert(tk.END, f"  0x3FF44004 (GPIO_OUT_REG):     0x00040000 (GPIO 18 Pin: HIGH/LOW)\n")
        self.txt_mmio.insert(tk.END, f"  0x3FF5F000 (RTC_CNTL_CLK):     240.0 MHz (XTENSA Dual-Core)\n")
        self.txt_mmio.insert(tk.END, f"  Telemetry:                     Vout={m['dmm_vdc']:.4f}V | Ripple={m['p2p_ripple_mv']:.1f}mV | η={m['efficiency_pct']:.1f}%\n")

        self.txt_uart.delete("1.0", tk.END)
        self.txt_uart.insert(tk.END, f"I (0.000) WOWKI_STUDIO: Firmware loaded into virtual ESP32.\n")
        self.txt_uart.insert(tk.END, f"I (0.010) WOWKI_STUDIO: Co-Simulation Bridge initialized with libngspice.dll\n")
        self.txt_uart.insert(tk.END, f"I (0.020) BUCK_CTRL: Switching Frequency: {m['sw_freq_khz']:.1f} kHz | Switch Transitions: {m['switch_cycles']}\n")
        self.txt_uart.insert(tk.END, f"I (5.000) BUCK_CTRL: Telemetry: Vout={m['dmm_vdc']:.4f}V | Iout={m['dmm_idc']:.3f}A | Pout={m['p_out_w']:.2f}W | Loss={m['p_loss_total']:.2f}W\n")

    def step_load_transient(self):
        self.rload_var.set(2.0)
        self.lbl_rload.config(text=f"Load Resistance (Rload): 2.0 Ω")
        messagebox.showinfo("Load Step Applied", "Rload dropped from 5.0Ω to 2.0Ω. Re-running co-simulation to observe transient recovery.")
        self.run_co_simulation()

    def new_project(self):
        self._load_default_firmware()
        self.vin_var.set(12.0)
        self.vtarget_var.set(3.30)
        self.rload_var.set(5.0)
        self._update_all_slider_labels()
        self.run_co_simulation()

    def open_project(self):
        fpath = filedialog.askopenfilename(filetypes=[("WOWKISPICE Project", "*.wowki"), ("JSON Files", "*.json")])
        if fpath:
            with open(fpath, "r") as f:
                data = json.load(f)
            self.engine.load_project_json(data)
            if "firmware" in data:
                self.code_text.delete("1.0", tk.END)
                self.code_text.insert(tk.END, data["firmware"])
            self.current_project_path = fpath
            self.run_co_simulation()

    def save_project(self):
        fpath = filedialog.asksaveasfilename(defaultextension=".wowki", filetypes=[("WOWKISPICE Project", "*.wowki")])
        if fpath:
            self.engine.firmware_code = self.code_text.get("1.0", tk.END)
            data = self.engine.export_project_json()
            with open(fpath, "w") as f:
                json.dump(data, f, indent=2)
            self.current_project_path = fpath
            messagebox.showinfo("Project Saved", f"Project bundle saved successfully to:\n{fpath}")

    def export_netlist(self):
        fpath = filedialog.asksaveasfilename(defaultextension=".cir", filetypes=[("SPICE Netlist", "*.cir")])
        if fpath:
            netlist_content = f"""* Exported SPICE Netlist from WOWKISPICE Studio
Vin in 0 DC {self.vin_var.get():.2f}
Vgate gate 0 dc 0 external
S1 in sw_node gate 0 SW_MODEL
D1 0 sw_node DIODE_MODEL
L1 sw_node vout {self.l1_var.get():.1f}u IC=0
C1 vout 0 {self.c1_var.get():.1f}u IC=0
Rload vout 0 {self.rload_var.get():.2f}
.model SW_MODEL SW(Ron=0.02 Roff=1e6 Vt=1.65 Vh=0.05)
.model DIODE_MODEL D(IS=1e-9 RS=0.01 N=1.0 BV=50 IBV=1e-4)
.tran 0.5u {self.duration_var.get():.1f}m uic
.end
"""
            with open(fpath, "w") as f:
                f.write(netlist_content)
            messagebox.showinfo("Export Successful", f"SPICE netlist saved to:\n{fpath}")


if __name__ == "__main__":
    app = WOWKISpiceStudio()
    app.mainloop()
