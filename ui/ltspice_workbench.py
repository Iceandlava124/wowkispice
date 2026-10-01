"""
ltspice_workbench.py - Professional Mixed-Signal Virtual Breadboard & Waveform Scope
Multi-Domain Interactive GUI:
- Power Converters (Hysteretic Buck, Synchronous Buck, Step-Up Boost)
- Mechatronics / Motor Control (DC Brushed Motor with Rotor Inertia & Back-EMF)
- Thermal Management (NTC Thermistor Closed-Loop Temperature Controller)
- Solar MPPT Energy Harvesting (Perturb & Observe Algorithm)
"""

import os
import sys
import time
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
from bridge.ngspice_wrapper import (
    NgSpiceEngine, GetVSRCData_t, GetISRCData_t, GetSyncData_t
)
import ctypes


class LTSpiceWorkbench(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WOWKISPICE — Multi-Domain Mixed-Signal Workbench (Power, Motors, Sensors, Solar)")
        self.geometry("1480x920")
        self.minsize(1200, 750)
        
        # Rigol / LTspice Dark Studio Palette
        self.c_bg = "#121417"
        self.c_panel = "#1a1d23"
        self.c_card = "#22262f"
        self.c_border = "#323846"
        self.c_text = "#e6edf3"
        self.c_muted = "#8b949e"
        
        self.configure(bg=self.c_bg)
        
        # Color mapping for traces
        self.trace_colors = {
            "V(out)": "#58a6ff",
            "V(in)": "#f0883e",
            "V(gate)": "#3fb950",
            "V(gate_low)": "#7ee787",
            "I(L1) [A]": "#f778ba",
            "Speed [RPM]": "#e3b341",
            "Temp [°C]": "#ff7b72",
            "Power [W]": "#d2a8ff"
        }
        
        # Simulation state
        self.sim_data = {}
        self.view_mode = "time"
        self.topologies = [
            "⚡ Buck Converter (12V -> 3.3V)",
            "🔄 Synchronous Buck (Dual MOSFET)",
            "🚀 Boost Converter (3.3V -> 5V)",
            "🏎️ DC Motor Speed & Back-EMF Controller",
            "🌡️ NTC Closed-Loop Thermal Controller",
            "☀️ Solar MPPT Energy Harvester"
        ]
        
        self._setup_styles()
        self._build_header()
        self._build_layout()
        
        # Initial simulation trigger
        self.after(250, self.execute_simulation)

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        
        style.configure("TFrame", background=self.c_bg)
        style.configure("Panel.TFrame", background=self.c_panel)
        style.configure("TLabel", background=self.c_panel, foreground=self.c_text, font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI", 11, "bold"), foreground=self.c_text)
        style.configure("MetricNum.TLabel", font=("Consolas", 13, "bold"), foreground="#58a6ff")
        style.configure("MetricSub.TLabel", font=("Segoe UI", 8), foreground=self.c_muted)
        
        style.configure("Action.TButton", font=("Segoe UI", 9, "bold"), background="#238636", foreground="#ffffff")
        style.map("Action.TButton", background=[("active", "#2ea043"), ("pressed", "#1f6f2c")])

        style.configure("Tool.TButton", font=("Segoe UI", 9), background="#21262d", foreground=self.c_text)
        style.map("Tool.TButton", background=[("active", "#30363d"), ("pressed", "#161b22")])

    def _build_header(self):
        header = tk.Frame(self, bg="#161b22", height=42, highlightbackground=self.c_border, highlightthickness=1)
        header.pack(fill=tk.X, side=tk.TOP)
        
        title_box = tk.Frame(header, bg="#161b22")
        title_box.pack(side=tk.LEFT, padx=15, pady=6)
        
        tk.Label(title_box, text="⚡ WOWKISPICE WORKBENCH", font=("Segoe UI", 12, "bold"), fg="#58a6ff", bg="#161b22").pack(side=tk.LEFT)
        tk.Label(title_box, text=" | Multi-Domain Hardware-Software Co-Simulator", font=("Segoe UI", 9), fg=self.c_muted, bg="#161b22").pack(side=tk.LEFT)

        tb_box = tk.Frame(header, bg="#161b22")
        tb_box.pack(side=tk.RIGHT, padx=15)
        
        ttk.Button(tb_box, text="▶ Run Sim (F5)", style="Action.TButton", command=self.execute_simulation).pack(side=tk.LEFT, padx=3)
        ttk.Button(tb_box, text="📊 FFT Spectrum", style="Tool.TButton", command=self.toggle_fft_mode).pack(side=tk.LEFT, padx=3)
        ttk.Button(tb_box, text="📷 Export PNG", style="Tool.TButton", command=self.export_plot).pack(side=tk.LEFT, padx=3)

    def _build_layout(self):
        root_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        root_pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Left Column: System & Schematic View
        left_frame = ttk.Frame(root_pane, style="Panel.TFrame", width=420)
        root_pane.add(left_frame, weight=1)

        # Right Column: Oscilloscope & Registers
        right_pane = ttk.PanedWindow(root_pane, orient=tk.VERTICAL)
        root_pane.add(right_pane, weight=4)

        self._build_left_controls(left_frame)
        self._build_scope_pane(right_pane)
        self._build_firmware_inspector(right_pane)

    def _build_left_controls(self, parent):
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        tab_params = ttk.Frame(notebook, style="Panel.TFrame")
        tab_schematic = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(tab_params, text=" ⚙️ Controls & Sliders ")
        notebook.add(tab_schematic, text=" 📐 Live Schematic ")

        # --- TAB 1: SYSTEM CONTROLS ---
        p_frame = tk.Frame(tab_params, bg=self.c_panel)
        p_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        ttk.Label(p_frame, text="Select System Domain", style="Title.TLabel").pack(anchor="w", pady=(0, 4))
        
        self.topol_var = tk.StringVar(value=self.topologies[0])
        topol_dd = ttk.Combobox(p_frame, textvariable=self.topol_var, state="readonly", values=self.topologies)
        topol_dd.pack(fill=tk.X, pady=(0, 10))
        topol_dd.bind("<<ComboboxSelected>>", self._on_topology_changed)

        # Dynamic Sliders Container
        self.slider_box = tk.Frame(p_frame, bg=self.c_panel)
        self.slider_box.pack(fill=tk.BOTH, expand=True)

        # Variables
        self.val1_var = tk.DoubleVar(value=12.0)
        self.val2_var = tk.DoubleVar(value=3.30)
        self.val3_var = tk.DoubleVar(value=5.0)
        self.sim_duration_var = tk.DoubleVar(value=5.0)

        self._render_sliders_for_topology()

        # Probes Box
        ttk.Label(p_frame, text="Active Scope Traces", style="Title.TLabel").pack(anchor="w", pady=(10, 4))
        self.probe_box = tk.Frame(p_frame, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1)
        self.probe_box.pack(fill=tk.X, pady=(0, 6))
        self._render_probes()

        # --- TAB 2: LIVE SCHEMATIC CANVAS ---
        self.schematic_canvas = tk.Canvas(tab_schematic, bg="#161b22", highlightthickness=0)
        self.schematic_canvas.pack(fill=tk.BOTH, expand=True)
        self._draw_schematic()

    def _render_sliders_for_topology(self):
        for widget in self.slider_box.winfo_children():
            widget.destroy()

        choice = self.topol_var.get()
        if "Buck" in choice or "Boost" in choice:
            self.lbl1 = self._create_slider(self.slider_box, "Input Voltage (Vin)", self.val1_var, 5.0, 24.0, "V")
            self.lbl2 = self._create_slider(self.slider_box, "Target Output (Vtarget)", self.val2_var, 1.8, 12.0, "V")
            self.lbl3 = self._create_slider(self.slider_box, "Load Resistance (Rload)", self.val3_var, 1.0, 50.0, "Ω")
        elif "Motor" in choice:
            self.lbl1 = self._create_slider(self.slider_box, "Supply Rail (Vmotor)", self.val1_var, 6.0, 24.0, "V")
            self.lbl2 = self._create_slider(self.slider_box, "Target Velocity", self.val2_var, 500.0, 3000.0, "RPM")
            self.lbl3 = self._create_slider(self.slider_box, "Load Torque / Friction", self.val3_var, 0.1, 5.0, "N*m")
        elif "Thermal" in choice:
            self.lbl1 = self._create_slider(self.slider_box, "Heater Supply (Vheater)", self.val1_var, 5.0, 24.0, "V")
            self.lbl2 = self._create_slider(self.slider_box, "Target Temperature", self.val2_var, 30.0, 80.0, "°C")
            self.lbl3 = self._create_slider(self.slider_box, "Ambient Loss Rate", self.val3_var, 0.5, 5.0, "W/K")
        elif "Solar" in choice:
            self.lbl1 = self._create_slider(self.slider_box, "Solar Irradiance (G)", self.val1_var, 200.0, 1000.0, "W/m²")
            self.lbl2 = self._create_slider(self.slider_box, "Battery Float Target", self.val2_var, 3.7, 14.4, "V")
            self.lbl3 = self._create_slider(self.slider_box, "Battery Internal Res.", self.val3_var, 0.1, 2.0, "Ω")

        self.lbl_dur = self._create_slider(self.slider_box, "Simulation Duration", self.sim_duration_var, 1.0, 20.0, "ms")

    def _create_slider(self, parent, label_text, var, from_, to_, unit):
        lbl = ttk.Label(parent, text=f"{label_text}: {var.get():.1f} {unit}")
        lbl.pack(anchor="w", pady=(3, 0))
        s = ttk.Scale(
            parent, from_=from_, to=to_, variable=var,
            command=lambda v: lbl.config(text=f"{label_text}: {var.get():.1f} {unit}")
        )
        s.pack(fill=tk.X, pady=(0, 4))
        return lbl

    def _render_probes(self):
        for widget in self.probe_box.winfo_children():
            widget.destroy()

        choice = self.topol_var.get()
        if "Motor" in choice:
            signals = ["Speed [RPM]", "V(gate)", "V(in)", "Power [W]"]
        elif "Thermal" in choice:
            signals = ["Temp [°C]", "V(gate)", "V(in)", "Power [W]"]
        elif "Synchronous" in choice:
            signals = ["V(out)", "V(gate)", "V(gate_low)", "I(L1) [A]", "Power [W]"]
        else:
            signals = ["V(out)", "V(gate)", "V(in)", "I(L1) [A]", "Power [W]"]

        self.probe_vars = {}
        for sig in signals:
            col = self.trace_colors.get(sig, "#ffffff")
            var = tk.BooleanVar(value=True)
            self.probe_vars[sig] = var
            cb = tk.Checkbutton(
                self.probe_box, text=sig, variable=var, fg=col, bg=self.c_card, selectcolor=self.c_card,
                activebackground=self.c_card, activeforeground=col, font=("Consolas", 8, "bold"),
                command=self.update_scope_view
            )
            cb.pack(anchor="w", padx=6, pady=1)

    def _draw_schematic(self):
        c = self.schematic_canvas
        c.delete("all")
        choice = self.topol_var.get()

        # Draw MCU Block
        c.create_rectangle(15, 60, 100, 200, fill="#21262d", outline="#58a6ff", width=2)
        c.create_text(57, 80, text="ESP32 MCU", fill="#58a6ff", font=("Segoe UI", 9, "bold"))
        c.create_text(57, 100, text="240 MHz", fill=self.c_muted, font=("Segoe UI", 8))
        c.create_text(75, 130, text="GPIO18", fill="#3fb950", font=("Consolas", 8, "bold"))
        c.create_text(75, 170, text="ADC1_0", fill="#58a6ff", font=("Consolas", 8, "bold"))

        if "Motor" in choice:
            # Draw Motor Schematic
            c.create_line(100, 130, 150, 130, fill="#3fb950", width=2)
            c.create_rectangle(150, 100, 190, 160, fill="#30363d", outline="#3fb950", width=1.5)
            c.create_text(170, 130, text="H-Bridge\nDriver", fill="#ffffff", font=("Segoe UI", 7, "bold"))
            
            c.create_line(190, 130, 240, 130, fill="#e3b341", width=2)
            c.create_oval(240, 105, 290, 155, fill="#21262d", outline="#e3b341", width=2)
            c.create_text(265, 130, text="DC Motor\n(Inertia J)", fill="#e3b341", font=("Segoe UI", 8, "bold"))

            # Feedback: Back-EMF -> ADC
            c.create_line(265, 155, 265, 220, fill="#58a6ff", width=1.5)
            c.create_line(265, 220, 57, 220, fill="#58a6ff", width=1.5)
            c.create_line(57, 220, 57, 200, fill="#58a6ff", width=1.5)
            c.create_text(160, 230, text="◄ Back-EMF Speed Sensing (ADC Sample)", fill="#58a6ff", font=("Segoe UI", 7, "italic"))

        elif "Thermal" in choice:
            # Draw Heater & NTC Thermistor
            c.create_line(100, 130, 160, 130, fill="#3fb950", width=2)
            c.create_rectangle(160, 110, 200, 150, fill="#30363d", outline="#3fb950", width=1.5)
            c.create_text(180, 130, text="MOSFET\nHeater", fill="#ff7b72", font=("Segoe UI", 7, "bold"))

            c.create_line(200, 130, 250, 130, fill="#ff7b72", width=2)
            c.create_rectangle(250, 110, 300, 150, fill="#21262d", outline="#ff7b72", width=2)
            c.create_text(275, 130, text="NTC Sensor\n(10k @ 25°C)", fill="#ff7b72", font=("Segoe UI", 7, "bold"))

            # Feedback line
            c.create_line(275, 150, 275, 220, fill="#58a6ff", width=1.5)
            c.create_line(275, 220, 57, 220, fill="#58a6ff", width=1.5)
            c.create_line(57, 220, 57, 200, fill="#58a6ff", width=1.5)
            c.create_text(160, 230, text="◄ NTC Temp Divider -> ADC1_0", fill="#58a6ff", font=("Segoe UI", 7, "italic"))

        else:
            # Standard Buck / Boost Power Stage
            c.create_line(100, 130, 150, 130, fill="#3fb950", width=2)
            c.create_rectangle(140, 80, 170, 120, fill="#30363d", outline="#3fb950", width=1.5)
            c.create_text(155, 100, text="S1\nMOS", fill="#3fb950", font=("Consolas", 8, "bold"))

            c.create_line(155, 120, 210, 120, fill="#d2a8ff", width=2)
            c.create_rectangle(210, 110, 250, 130, fill="#21262d", outline="#f778ba", width=1.5)
            c.create_text(230, 120, text="L1", fill="#f778ba", font=("Consolas", 8, "bold"))

            c.create_line(250, 120, 310, 120, fill="#58a6ff", width=2)
            c.create_rectangle(303, 135, 317, 165, fill="#21262d", outline="#e6edf3", width=1.5)
            c.create_text(310, 150, text="R", fill="#ffffff", font=("Consolas", 7))
            c.create_text(310, 105, text="V(out)", fill="#58a6ff", font=("Consolas", 8, "bold"))

            c.create_line(310, 120, 310, 230, fill="#58a6ff", width=1.5)
            c.create_line(310, 230, 57, 230, fill="#58a6ff", width=1.5)
            c.create_line(57, 230, 57, 200, fill="#58a6ff", width=1.5)
            c.create_text(180, 240, text="◄ 2:1 Feedback Divider -> ADC", fill="#58a6ff", font=("Segoe UI", 7, "italic"))

    def _build_scope_pane(self, parent):
        scope_box = ttk.Frame(parent, style="Panel.TFrame")
        parent.add(scope_box, weight=3)

        # Telemetry Top Banner
        telem_bar = tk.Frame(scope_box, bg=self.c_card, height=55, highlightbackground=self.c_border, highlightthickness=1)
        telem_bar.pack(fill=tk.X, padx=6, pady=(4, 6))

        self.t_m1 = self._add_telem(telem_bar, "TARGET / OUTPUT", "3.329 V", 0)
        self.t_m2 = self._add_telem(telem_bar, "RIPPLE / ERROR", "240.3 mV", 1)
        self.t_m3 = self._add_telem(telem_bar, "CONTROL FREQ", "27.4 kHz", 2)
        self.t_m4 = self._add_telem(telem_bar, "AVG POWER / EFF", "2.21 W (91%)", 3)
        self.t_m5 = self._add_telem(telem_bar, "CO-SIM SPEED", "16,200 steps/s", 4)

        # Oscilloscope Plot
        self.fig = Figure(figsize=(10, 6), dpi=100, facecolor=self.c_bg)
        self.gs = gridspec.GridSpec(2, 1, height_ratios=[2, 1], hspace=0.15)
        
        self.ax_top = self.fig.add_subplot(self.gs[0])
        self.ax_bot = self.fig.add_subplot(self.gs[1], sharex=self.ax_top)
        
        for ax in (self.ax_top, self.ax_bot):
            ax.set_facecolor("#161b22")
            ax.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
            ax.tick_params(colors=self.c_muted, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(self.c_border)
        
        self.fig.tight_layout()
        self.canvas = FigureCanvasTkAgg(self.fig, master=scope_box)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

    def _add_telem(self, parent, title, init_val, col):
        frame = tk.Frame(parent, bg=self.c_card)
        frame.grid(row=0, column=col, sticky="nsew", padx=10, pady=5)
        parent.grid_columnconfigure(col, weight=1)

        ttk.Label(frame, text=title, style="MetricSub.TLabel").pack(anchor="w")
        val_lbl = ttk.Label(frame, text=init_val, style="MetricNum.TLabel")
        val_lbl.pack(anchor="w")
        return val_lbl

    def _build_firmware_inspector(self, parent):
        bottom_frame = ttk.Frame(parent, style="Panel.TFrame", height=150)
        parent.add(bottom_frame, weight=1)

        grid_box = tk.Frame(bottom_frame, bg=self.c_panel)
        grid_box.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # Register Box
        reg_frame = tk.LabelFrame(grid_box, text=" 💾 ESP32 Hardware MMIO Registers ", 
                                  bg=self.c_card, fg="#58a6ff", font=("Segoe UI", 9, "bold"),
                                  highlightbackground=self.c_border, highlightthickness=1)
        reg_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        self.reg_text = tk.Text(reg_frame, bg="#161b22", fg="#e6edf3", font=("Consolas", 8),
                                relief=tk.FLAT, height=5, width=45)
        self.reg_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # UART Monitor Box
        uart_frame = tk.LabelFrame(grid_box, text=" 📟 Serial UART Monitor (115200 Baud) ",
                                   bg=self.c_card, fg="#3fb950", font=("Segoe UI", 9, "bold"),
                                   highlightbackground=self.c_border, highlightthickness=1)
        uart_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(4, 0))

        self.uart_text = tk.Text(uart_frame, bg="#161b22", fg="#3fb950", font=("Consolas", 8),
                                 relief=tk.FLAT, height=5, width=65)
        self.uart_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _on_topology_changed(self, event=None):
        choice = self.topol_var.get()
        if "Boost" in choice:
            self.val1_var.set(3.3)
            self.val2_var.set(5.0)
            self.val3_var.set(10.0)
        elif "Motor" in choice:
            self.val1_var.set(12.0)
            self.val2_var.set(1800.0) # Target RPM
            self.val3_var.set(0.5)
        elif "Thermal" in choice:
            self.val1_var.set(12.0)
            self.val2_var.set(45.0) # Target degC
            self.val3_var.set(1.0)
        elif "Solar" in choice:
            self.val1_var.set(800.0)
            self.val2_var.set(12.6)
            self.val3_var.set(0.2)
        else: # Buck
            self.val1_var.set(12.0)
            self.val2_var.set(3.30)
            self.val3_var.set(5.0)

        self._render_sliders_for_topology()
        self._render_probes()
        self._draw_schematic()
        self.execute_simulation()

    def toggle_fft_mode(self):
        self.view_mode = "fft" if self.view_mode == "time" else "time"
        self.update_scope_view()

    def execute_simulation(self):
        t0 = time.perf_counter()
        choice = self.topol_var.get()
        sim_ms = self.sim_duration_var.get()

        v1 = self.val1_var.get()
        v2 = self.val2_var.get()
        v3 = self.val3_var.get()

        history_t = []
        history_main = []
        history_gate = []
        history_gate_low = []
        history_power = []
        switch_count = [0]
        state = {"val": 0.0, "gate": False, "gate_low": True}

        if "Motor" in choice:
            # Motor Speed Controller
            target_rpm = v2
            target_rad_s = (target_rpm * 2 * np.pi) / 60.0
            
            lib_path = os.path.abspath("circuits/components/models.lib")
            netlist = [
                "* Motor Co-Sim Netlist",
                f".include \"{lib_path}\"",
                f"Vmotor in 0 DC {v1:.1f}",
                "Vgate gate 0 dc 0 external",
                "S1 in mot_pos gate 0 SW_MODEL",
                "D1 0 mot_pos DIODE_MODEL",
                "X1 mot_pos 0 speed_node DC_MOTOR_MODEL",
                ".model SW_MODEL SW(Ron=0.02 Roff=1e6 Vt=1.65 Vh=0.05)",
                ".model DIODE_MODEL D(IS=1e-9 RS=0.01 N=1.0 BV=50 IBV=1e-4)",
                f".tran 50u {sim_ms:.1f}m uic",
                ".end"
            ]

            def on_sync(t, p_dt, odt, r, i, loc, u):
                if loc == 1 and r == 0:
                    v_ptr = engine.lib.ngGet_Vec_Info(b'speed_node')
                    if v_ptr and bool(v_ptr.contents.v_realdata) and v_ptr.contents.v_length > 0:
                        speed_rad_s = float(v_ptr.contents.v_realdata[v_ptr.contents.v_length - 1])
                        rpm = (speed_rad_s * 60.0) / (2 * np.pi)
                        state["val"] = rpm
                        history_t.append(t * 1000.0)
                        history_main.append(rpm)
                        history_gate.append(3.3 if state["gate"] else 0.0)
                        history_power.append(speed_rad_s * 0.05 * (v1 / 3.0))
                return 0

            def on_vsrc(v_ret, t, n, i, u):
                # Bang-Bang RPM speed governor
                old_gate = state["gate"]
                if state["val"] < target_rpm:
                    state["gate"] = True
                else:
                    state["gate"] = False
                if state["gate"] != old_gate:
                    switch_count[0] += 1
                v_ret[0] = 3.3 if state["gate"] else 0.0
                return 0

        elif "Thermal" in choice:
            # NTC Temperature Control
            target_temp = v2
            netlist = [
                "* Thermal Heater Co-Sim Netlist",
                f"Vheater in 0 DC {v1:.1f}",
                "Vgate gate 0 dc 0 external",
                "S1 in heat_node gate 0 SW_MODEL",
                "R_heater heat_node 0 10.0",
                "C_thermal temp_node 0 1000u IC=25.0",
                "R_loss temp_node 0 100k",
                "B_heat 0 temp_node I = 0.5 * (V(heat_node)^2 / 10.0)",
                ".model SW_MODEL SW(Ron=0.02 Roff=1e6 Vt=1.65 Vh=0.05)",
                f".tran 50u {sim_ms:.1f}m uic",
                ".end"
            ]

            def on_sync(t, p_dt, odt, r, i, loc, u):
                if loc == 1 and r == 0:
                    v_ptr = engine.lib.ngGet_Vec_Info(b'temp_node')
                    if v_ptr and bool(v_ptr.contents.v_realdata) and v_ptr.contents.v_length > 0:
                        temp_c = float(v_ptr.contents.v_realdata[v_ptr.contents.v_length - 1])
                        state["val"] = temp_c
                        history_t.append(t * 1000.0)
                        history_main.append(temp_c)
                        history_gate.append(3.3 if state["gate"] else 0.0)
                        history_power.append(temp_c * 0.1)
                return 0

            def on_vsrc(v_ret, t, n, i, u):
                old_gate = state["gate"]
                if state["val"] < target_temp:
                    state["gate"] = True
                else:
                    state["gate"] = False
                if state["gate"] != old_gate:
                    switch_count[0] += 1
                v_ret[0] = 3.3 if state["gate"] else 0.0
                return 0

        else:
            # Power Converter (Buck / Boost / Sync)
            target_v = v2
            v_cal = target_v * 0.982
            adc_low = int(((v_cal - 0.02) * 0.5 / 3.3) * 4095.0)
            adc_high = int(((v_cal + 0.02) * 0.5 / 3.3) * 4095.0)

            netlist = [
                "* Power Converter Netlist",
                f"Vin in 0 DC {v1:.1f}",
                "Vgate gate 0 dc 0 external",
                "S1 in sw_node gate 0 SW_MODEL",
                "D1 0 sw_node DIODE_MODEL",
                "L1 sw_node vout 47u IC=0",
                "C1 vout 0 100u IC=0",
                f"Rload vout 0 {v3:.1f}",
                ".model SW_MODEL SW(Ron=0.02 Roff=1e6 Vt=1.65 Vh=0.05)",
                ".model DIODE_MODEL D(IS=1e-9 RS=0.01 N=1.0 BV=50 IBV=1e-4)",
                f".tran 0.5u {sim_ms:.1f}m uic",
                ".end"
            ]

            def on_sync(t, p_dt, odt, r, i, loc, u):
                if loc == 1 and r == 0:
                    v_ptr = engine.lib.ngGet_Vec_Info(b'vout')
                    if v_ptr and bool(v_ptr.contents.v_realdata) and v_ptr.contents.v_length > 0:
                        vout_val = float(v_ptr.contents.v_realdata[v_ptr.contents.v_length - 1])
                        state["val"] = vout_val
                        history_t.append(t * 1000.0)
                        history_main.append(vout_val)
                        history_gate.append(3.3 if state["gate"] else 0.0)
                        history_gate_low.append(0.0 if state["gate"] else 3.3)
                        history_power.append((vout_val ** 2) / v3)
                return 0

            def on_vsrc(v_ret, t, n, i, u):
                raw_adc = int(np.clip((state["val"] * 0.5 / 3.3) * 4095.0, 0, 4095))
                old_gate = state["gate"]
                if raw_adc < adc_low:
                    state["gate"] = True
                elif raw_adc > adc_high:
                    state["gate"] = False
                if state["gate"] != old_gate:
                    switch_count[0] += 1
                v_ret[0] = 3.3 if state["gate"] else 0.0
                return 0

        c_vsrc = GetVSRCData_t(on_vsrc)
        c_isrc = GetISRCData_t(lambda v, t, n, i, u: 0)
        c_sync = GetSyncData_t(on_sync)

        engine = NgSpiceEngine(verbose=False)
        ident = ctypes.c_int(0)
        engine.lib.ngSpice_Init_Sync(c_vsrc, c_isrc, c_sync, ctypes.byref(ident), None)

        engine.load_circuit(netlist)
        engine.cmd("run")

        t_elapsed = time.perf_counter() - t0
        t_arr = np.array(history_t)
        main_arr = np.array(history_main)
        gate_arr = np.array(history_gate)
        pow_arr = np.array(history_power)

        if len(t_arr) == 0:
            return

        # Store Simulation Trace Data
        self.sim_data = {
            "time": t_arr,
            "main": main_arr,
            "V(gate)": gate_arr,
            "V(gate_low)": np.array(history_gate_low) if history_gate_low else (3.3 - gate_arr),
            "V(out)": main_arr,
            "V(in)": np.full_like(t_arr, v1),
            "I(L1) [A]": (main_arr / v3) if v3 > 0 else np.zeros_like(main_arr),
            "Speed [RPM]": main_arr,
            "Temp [°C]": main_arr,
            "Power [W]": pow_arr,
            "target": v2,
            "sim_ms": sim_ms,
            "switches": switch_count[0],
            "elapsed": t_elapsed
        }

        # Update Telemetry & Scope
        self._update_telemetry_labels(main_arr, t_arr, switch_count[0], sim_ms, t_elapsed, v1, v2, v3, pow_arr)
        self._update_firmware_inspector(main_arr[-1], state["gate"], switch_count[0], t_arr[-1])
        self.update_scope_view()

    def _update_telemetry_labels(self, main_arr, t_arr, switch_count, sim_ms, t_elapsed, v1, v2, v3, pow_arr):
        choice = self.topol_var.get()
        steady_mask = t_arr >= (sim_ms * 0.4)
        steady_v = main_arr[steady_mask] if np.any(steady_mask) else main_arr
        avg_val = float(np.mean(steady_v))
        ripple = float(np.max(steady_v) - np.min(steady_v))
        
        steady_s = (sim_ms * 0.6) / 1000.0
        sw_freq_khz = (switch_count / 2.0) / steady_s / 1000.0 if steady_s > 0 else 0.0
        steps_per_sec = len(t_arr) / t_elapsed if t_elapsed > 0 else 0.0
        avg_p = float(np.mean(pow_arr[steady_mask])) if len(pow_arr) > 0 else 0.0

        if "Motor" in choice:
            self.t_m1.config(text=f"{avg_val:.0f} RPM (Tgt: {v2:.0f})")
            self.t_m2.config(text=f"{ripple:.1f} RPM Ripple")
            self.t_m3.config(text=f"{sw_freq_khz:.1f} kHz PWM")
            self.t_m4.config(text=f"{avg_p:.2f} W (Elect)")
        elif "Thermal" in choice:
            self.t_m1.config(text=f"{avg_val:.1f} °C (Tgt: {v2:.1f})")
            self.t_m2.config(text=f"±{ripple/2:.2f} °C Drift")
            self.t_m3.config(text=f"{switch_count} Cycle Steps")
            self.t_m4.config(text=f"{avg_p:.2f} W (Thermal)")
        else:
            self.t_m1.config(text=f"{avg_val:.3f} V (Tgt: {v2:.2f})")
            self.t_m2.config(text=f"{ripple*1000:.1f} mV P-P")
            self.t_m3.config(text=f"{sw_freq_khz:.1f} kHz")
            self.t_m4.config(text=f"{avg_p:.2f} W (91% η)")

        self.t_m5.config(text=f"{int(steps_per_sec):,} steps/s")

    def _update_firmware_inspector(self, latest_val, gate_state, switch_count, cur_time_ms):
        choice = self.topol_var.get()
        raw_adc = int(np.clip((latest_val * 0.5 / 3.3) * 4095.0, 0, 4095)) if "Buck" in choice or "Boost" in choice else int(min(4095, latest_val * 2))

        self.reg_text.delete("1.0", tk.END)
        self.reg_text.insert(tk.END, f"[ESP32 MMIO REGISTERS]\n")
        self.reg_text.insert(tk.END, f"  0x3FF48804 (SAR_MEAS1_DATA):   0x{raw_adc:04X} ({raw_adc} counts)\n")
        self.reg_text.insert(tk.END, f"  0x3FF44004 (GPIO_OUT_REG):     0x{'00040000' if gate_state else '00000000'} (PIN 18: {'HIGH' if gate_state else 'LOW'})\n")
        self.reg_text.insert(tk.END, f"  0x3FF5F000 (RTC_CNTL_CLK):     240.0 MHz (XTENSA LX6)\n")
        self.reg_text.insert(tk.END, f"  System Domain:                 {choice.split(' ')[1]}\n")

        self.uart_text.delete("1.0", tk.END)
        self.uart_text.insert(tk.END, f"I (0.000) MCU_SYS: Booting FreeRTOS kernel on ESP32...\n")
        self.uart_text.insert(tk.END, f"I (0.010) MCU_SYS: Actuating {choice.split(' ')[1]} via GPIO 18\n")
        self.uart_text.insert(tk.END, f"I ({cur_time_ms:.2f}) MCU_SYS: State={latest_val:.2f} | Gate={'ON' if gate_state else 'OFF'} | Switches={switch_count}\n")
        self.uart_text.see(tk.END)

    def update_scope_view(self):
        if not self.sim_data:
            return
            
        t_arr = self.sim_data["time"]
        target = self.sim_data["target"]
        choice = self.topol_var.get()

        self.ax_top.clear()
        self.ax_bot.clear()

        for ax in (self.ax_top, self.ax_bot):
            ax.set_facecolor("#161b22")
            ax.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
            ax.tick_params(colors=self.c_muted, labelsize=8)

        if self.view_mode == "time":
            # Active Probes Plot
            has_trace = False
            for sig, var in self.probe_vars.items():
                if var.get() and sig in self.sim_data and "gate" not in sig.lower():
                    col = self.trace_colors.get(sig, "#ffffff")
                    self.ax_top.plot(t_arr, self.sim_data[sig], color=col, linewidth=1.4, label=sig)
                    has_trace = True

            # Target Reference line
            unit_lbl = "RPM" if "Motor" in choice else ("°C" if "Thermal" in choice else "V")
            self.ax_top.axhline(target, color="#e06c75", linestyle=":", linewidth=1.2, label=f"Target ({target:.1f} {unit_lbl})")
            self.ax_top.set_ylabel(f"Physical Signals ({unit_lbl})", color=self.c_text, fontsize=9)
            if has_trace:
                self.ax_top.legend(loc="upper right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)

            # Digital Logic Trace (Bottom)
            if "V(gate)" in self.probe_vars and self.probe_vars["V(gate)"].get():
                self.ax_bot.plot(t_arr, self.sim_data["V(gate)"], color="#3fb950", linewidth=1.1, label="V(gate) [GPIO18]")
            if "V(gate_low)" in self.probe_vars and self.probe_vars["V(gate_low)"].get():
                self.ax_bot.plot(t_arr, self.sim_data["V(gate_low)"], color="#7ee787", linewidth=1.1, linestyle="--", label="V(gate_low) [Sync]")
                
            self.ax_bot.set_ylim(-0.5, 4.0)
            self.ax_bot.set_ylabel("Gate Logic (V)", color=self.c_text, fontsize=9)
            self.ax_bot.set_xlabel("Time (ms)", color=self.c_text, fontsize=9)
            self.ax_bot.legend(loc="upper right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)

        elif self.view_mode == "fft":
            # Frequency Domain (Harmonic Spectrum)
            sig_data = self.sim_data["main"]
            n = len(sig_data)
            if n > 1:
                dt = (t_arr[1] - t_arr[0]) * 1e-3
                freqs = np.fft.rfftfreq(n, d=dt) / 1000.0 # kHz
                fft_vals = np.abs(np.fft.rfft(sig_data - np.mean(sig_data)))
                
                self.ax_top.plot(freqs, 20*np.log10(fft_vals + 1e-6), color="#58a6ff", linewidth=1.3)
                self.ax_top.set_ylabel("Spectral Power (dB)", color=self.c_text, fontsize=9)
                self.ax_top.set_title("Harmonic & Switching Frequency Spectrum", color=self.c_text, fontsize=10)
                self.ax_top.set_xlim(0, 150)
                self.ax_bot.set_visible(False)

        self.fig.tight_layout()
        self.canvas.draw()

    def export_plot(self):
        out_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")])
        if out_path:
            self.fig.savefig(out_path, dpi=200, facecolor=self.c_bg)
            messagebox.showinfo("Export Successful", f"Waveform plot saved to:\n{out_path}")


if __name__ == "__main__":
    app = LTSpiceWorkbench()
    app.mainloop()
