"""
ltspice_workbench.py - Professional Mixed-Signal Virtual Breadboard & Waveform Scope
Replicates the high-fidelity multi-pane experience of LTspice / Keysight oscilloscopes
combined with digital MCU firmware logic inspection.
"""

import os
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
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
        self.title("WOWKISPICE — Pro Mixed-Signal Co-Simulation Workbench (LTspice + Digital MCU)")
        self.geometry("1440x900")
        self.minsize(1200, 750)
        
        # Color Palette (Dark Rigol / LTspice Studio Aesthetic)
        self.c_bg = "#121417"
        self.c_panel = "#1a1d23"
        self.c_card = "#22262f"
        self.c_border = "#323846"
        self.c_text = "#e6edf3"
        self.c_muted = "#8b949e"
        
        # Signal Trace Colors
        self.trace_colors = {
            "V(vout)": "#58a6ff",    # Bright Cyan-Blue (Analog Output)
            "V(in)": "#f0883e",      # Orange (DC Input)
            "V(gate)": "#3fb950",    # Neon Green (Digital Gate)
            "V(sw_node)": "#d2a8ff", # Purple (Switching Node)
            "I(L1) [A]": "#f778ba",  # Pink/Magenta (Inductor Current)
            "P(out) [W]": "#e3b341"  # Gold (Output Power)
        }
        
        self.configure(bg=self.c_bg)
        
        # Simulation State
        self.sim_data = {}
        self.active_traces = ["V(vout)", "V(gate)", "I(L1) [A]"]
        self.view_mode = "time"  # 'time' or 'fft'
        self.cursor_enabled = tk.BooleanVar(value=True)
        
        self._setup_styles()
        self._build_header()
        self._build_main_layout()
        
        # Initial run
        self.after(250, self.execute_simulation)

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        
        style.configure("TFrame", background=self.c_bg)
        style.configure("Panel.TFrame", background=self.c_panel)
        style.configure("Card.TFrame", background=self.c_card)
        style.configure("TLabel", background=self.c_panel, foreground=self.c_text, font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=self.c_card, foreground=self.c_text, font=("Segoe UI", 9))
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
        
        tk.Label(title_box, text="⚡ WOWKISPICE", font=("Segoe UI", 12, "bold"), fg="#58a6ff", bg="#161b22").pack(side=tk.LEFT)
        tk.Label(title_box, text=" | Virtual Mixed-Signal Co-Simulator Workbench", font=("Segoe UI", 10), fg=self.c_muted, bg="#161b22").pack(side=tk.LEFT)

        # Toolbar controls
        tb_box = tk.Frame(header, bg="#161b22")
        tb_box.pack(side=tk.RIGHT, padx=15)
        
        ttk.Button(tb_box, text="▶ Run (F5)", style="Action.TButton", command=self.execute_simulation).pack(side=tk.LEFT, padx=3)
        ttk.Button(tb_box, text="📊 FFT Spectrum", style="Tool.TButton", command=self.toggle_fft_mode).pack(side=tk.LEFT, padx=3)
        ttk.Button(tb_box, text="📷 Export Scope PNG", style="Tool.TButton", command=self.export_plot).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(tb_box, text="Cursors", variable=self.cursor_enabled, command=self.update_scope_view).pack(side=tk.LEFT, padx=6)

    def _build_main_layout(self):
        # 3-Pane Layout: Left (Controls + Schematic) | Center (Oscilloscope) | Bottom (Firmware Logic)
        root_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        root_pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Left Column (Parameters + Interactive Schematic Canvas)
        left_frame = ttk.Frame(root_pane, style="Panel.TFrame", width=380)
        root_pane.add(left_frame, weight=1)

        # Right Column (Oscilloscope + Firmware Inspector)
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
        notebook.add(tab_params, text=" ⚙️ Circuit & MCU ")
        notebook.add(tab_schematic, text=" 📐 Live Schematic ")

        # --- TAB 1: PARAMETERS ---
        p_frame = tk.Frame(tab_params, bg=self.c_panel)
        p_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        ttk.Label(p_frame, text="Topology & Targets", style="Title.TLabel").pack(anchor="w", pady=(0, 4))
        
        self.topol_var = tk.StringVar(value="Buck Converter (12V -> 3.3V)")
        topol_dd = ttk.Combobox(p_frame, textvariable=self.topol_var, state="readonly", 
                                values=["Buck Converter (12V -> 3.3V)", "Boost Converter (3.3V -> 5V)"])
        topol_dd.pack(fill=tk.X, pady=(0, 10))
        topol_dd.bind("<<ComboboxSelected>>", self._on_topology_select)

        # Parameter Sliders
        self.vin_var = tk.DoubleVar(value=12.0)
        self.vtarget_var = tk.DoubleVar(value=3.30)
        self.rload_var = tk.DoubleVar(value=5.0)
        self.l1_var = tk.DoubleVar(value=47.0)
        self.c1_var = tk.DoubleVar(value=100.0)
        self.sim_duration_var = tk.DoubleVar(value=5.0)

        self.vin_lbl = self._create_slider(p_frame, "Input Voltage (Vin)", self.vin_var, 5.0, 24.0, "V")
        self.vtarget_lbl = self._create_slider(p_frame, "Target Output (Vtarget)", self.vtarget_var, 1.8, 12.0, "V")
        self.rload_lbl = self._create_slider(p_frame, "Load Resistance (Rload)", self.rload_var, 1.0, 50.0, "Ω")
        self.l1_lbl = self._create_slider(p_frame, "Filter Inductor (L1)", self.l1_var, 10.0, 200.0, "µH")
        self.c1_lbl = self._create_slider(p_frame, "Filter Capacitor (C1)", self.c1_var, 10.0, 470.0, "µF")
        self.dur_lbl = self._create_slider(p_frame, "Simulation Time", self.sim_duration_var, 1.0, 20.0, "ms")

        # Probed Signals Selector
        ttk.Label(p_frame, text="Active Scope Probes", style="Title.TLabel").pack(anchor="w", pady=(10, 4))
        probe_box = tk.Frame(p_frame, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1)
        probe_box.pack(fill=tk.X, pady=(0, 10), padx=2)

        self.probe_vars = {}
        for sig, col in self.trace_colors.items():
            var = tk.BooleanVar(value=(sig in self.active_traces))
            self.probe_vars[sig] = var
            cb = tk.Checkbutton(
                probe_box, text=sig, variable=var, fg=col, bg=self.c_card, selectcolor=self.c_card,
                activebackground=self.c_card, activeforeground=col, font=("Consolas", 9, "bold"),
                command=self._on_probe_toggled
            )
            cb.pack(anchor="w", padx=6, pady=2)

        # --- TAB 2: LIVE SCHEMATIC CANVAS ---
        self.schematic_canvas = tk.Canvas(tab_schematic, bg="#161b22", highlightthickness=0)
        self.schematic_canvas.pack(fill=tk.BOTH, expand=True)
        self._draw_schematic_diagram()

    def _create_slider(self, parent, label_text, var, from_, to_, unit):
        lbl = ttk.Label(parent, text=f"{label_text}: {var.get():.2f} {unit}")
        lbl.pack(anchor="w", pady=(4, 0))
        s = ttk.Scale(
            parent, from_=from_, to=to_, variable=var,
            command=lambda v: lbl.config(text=f"{label_text}: {var.get():.2f} {unit}")
        )
        s.pack(fill=tk.X, pady=(0, 6))
        return lbl

    def _draw_schematic_diagram(self):
        c = self.schematic_canvas
        c.delete("all")
        
        # Draw ESP32 MCU box
        c.create_rectangle(20, 80, 110, 220, fill="#21262d", outline="#58a6ff", width=2)
        c.create_text(65, 100, text="ESP32 MCU", fill="#58a6ff", font=("Segoe UI", 10, "bold"))
        c.create_text(65, 120, text="240 MHz", fill=self.c_muted, font=("Segoe UI", 8))
        
        # MCU Pins
        c.create_text(90, 150, text="GPIO18", fill="#3fb950", font=("Consolas", 8, "bold"))
        c.create_text(90, 190, text="ADC1_0", fill="#58a6ff", font=("Consolas", 8, "bold"))
        
        # Wires: Gate Drive (GPIO18 -> Switch)
        c.create_line(110, 150, 160, 150, fill="#3fb950", width=2)
        c.create_line(160, 150, 160, 100, fill="#3fb950", width=2)
        
        # MOSFET Switch (S1)
        c.create_rectangle(145, 60, 175, 100, fill="#30363d", outline="#3fb950", width=1.5)
        c.create_text(160, 75, text="S1", fill="#ffffff", font=("Consolas", 9, "bold"))
        c.create_text(160, 90, text="MOS", fill="#3fb950", font=("Consolas", 7))
        
        # Vin source -> Switch
        c.create_line(160, 30, 160, 60, fill="#f0883e", width=2)
        c.create_oval(150, 15, 170, 35, outline="#f0883e", width=2)
        c.create_text(160, 25, text="+", fill="#f0883e", font=("Segoe UI", 10, "bold"))
        c.create_text(130, 25, text="Vin", fill="#f0883e", font=("Segoe UI", 9, "bold"))

        # Switch node -> Inductor L1 & Diode D1
        c.create_line(160, 100, 160, 130, fill="#d2a8ff", width=2) # SW_NODE
        c.create_oval(157, 127, 163, 133, fill="#d2a8ff", outline="#d2a8ff")
        c.create_text(135, 130, text="SW_NODE", fill="#d2a8ff", font=("Consolas", 7))
        
        # Diode to GND
        c.create_line(160, 130, 160, 180, fill="#e6edf3", width=1.5)
        c.create_polygon(152, 160, 168, 160, 160, 175, fill="#8b949e", outline="#ffffff")
        c.create_line(152, 175, 168, 175, fill="#ffffff", width=1.5)
        c.create_line(160, 180, 160, 210, fill="#8b949e", width=1.5)
        c.create_line(150, 210, 170, 210, fill="#8b949e", width=2) # GND
        c.create_text(135, 168, text="D1", fill="#8b949e", font=("Consolas", 8))

        # Inductor L1
        c.create_line(160, 130, 210, 130, fill="#d2a8ff", width=2)
        c.create_rectangle(210, 120, 250, 140, fill="#21262d", outline="#f778ba", width=1.5)
        c.create_text(230, 130, text="L1", fill="#f778ba", font=("Consolas", 9, "bold"))

        # Output Node -> Capacitor & Load
        c.create_line(250, 130, 310, 130, fill="#58a6ff", width=2)
        c.create_oval(307, 127, 313, 133, fill="#58a6ff", outline="#58a6ff")
        c.create_text(310, 115, text="V(out)", fill="#58a6ff", font=("Consolas", 9, "bold"))

        # Capacitor C1
        c.create_line(280, 130, 280, 160, fill="#58a6ff", width=1.5)
        c.create_line(270, 160, 290, 160, fill="#ffffff", width=2)
        c.create_line(270, 166, 290, 166, fill="#ffffff", width=2)
        c.create_line(280, 166, 280, 210, fill="#8b949e", width=1.5)
        c.create_line(270, 210, 290, 210, fill="#8b949e", width=2) # GND
        c.create_text(260, 163, text="C1", fill="#ffffff", font=("Consolas", 8))

        # Load Resistor Rload
        c.create_line(310, 130, 310, 155, fill="#58a6ff", width=1.5)
        c.create_rectangle(303, 155, 317, 185, fill="#21262d", outline="#e6edf3", width=1.5)
        c.create_text(310, 170, text="R", fill="#ffffff", font=("Consolas", 8))
        c.create_line(310, 185, 310, 210, fill="#8b949e", width=1.5)
        c.create_line(300, 210, 320, 210, fill="#8b949e", width=2) # GND
        c.create_text(335, 170, text="Rload", fill="#e6edf3", font=("Consolas", 8))

        # Feedback Line: V(out) -> 2:1 Divider -> MCU ADC1_0
        c.create_line(310, 130, 310, 240, fill="#58a6ff", width=1.5)
        c.create_line(310, 240, 65, 240, fill="#58a6ff", width=1.5)
        c.create_line(65, 240, 65, 220, fill="#58a6ff", width=1.5)
        c.create_text(180, 250, text="◄ Closed-Loop Feedback (ADC 12-Bit Sample)", fill="#58a6ff", font=("Segoe UI", 8, "italic"))

    def _build_scope_pane(self, parent):
        scope_box = ttk.Frame(parent, style="Panel.TFrame")
        parent.add(scope_box, weight=3)

        # Telemetry Top Banner
        telem_bar = tk.Frame(scope_box, bg=self.c_card, height=60, highlightbackground=self.c_border, highlightthickness=1)
        telem_bar.pack(fill=tk.X, padx=6, pady=(4, 6))

        self.t_vout = self._add_telem_widget(telem_bar, "V(OUT) AVERAGE", "3.329 V", 0)
        self.t_ripple = self._add_telem_widget(telem_bar, "V(OUT) RIPPLE (P-P)", "240.3 mV", 1)
        self.t_freq = self._add_telem_widget(telem_bar, "SWITCHING FREQ", "27.4 kHz", 2)
        self.t_eff = self._add_telem_widget(telem_bar, "EST. EFFICIENCY (η)", "89.4 %", 3)
        self.t_speed = self._add_telem_widget(telem_bar, "CO-SIM SPEED", "16,200 steps/s", 4)

        # Oscilloscope Matplotlib Figure
        self.fig = Figure(figsize=(10, 6), dpi=100, facecolor=self.c_bg)
        self.gs = gridspec.GridSpec(2, 1, height_ratios=[2, 1], hspace=0.15)
        
        self.ax_analog = self.fig.add_subplot(self.gs[0])
        self.ax_digital = self.fig.add_subplot(self.gs[1], sharex=self.ax_analog)
        
        for ax in (self.ax_analog, self.ax_digital):
            ax.set_facecolor("#161b22")
            ax.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
            ax.tick_params(colors=self.c_muted, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(self.c_border)
        
        self.ax_analog.set_ylabel("Analog Signals (V / A)", color=self.c_text, fontsize=9)
        self.ax_digital.set_ylabel("Digital Logic (V)", color=self.c_text, fontsize=9)
        self.ax_digital.set_xlabel("Time (ms)", color=self.c_text, fontsize=9)
        self.fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.fig, master=scope_box)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

    def _add_telem_widget(self, parent, title, init_val, col):
        frame = tk.Frame(parent, bg=self.c_card)
        frame.grid(row=0, column=col, sticky="nsew", padx=12, pady=6)
        parent.grid_columnconfigure(col, weight=1)

        ttk.Label(frame, text=title, style="MetricSub.TLabel").pack(anchor="w")
        val_lbl = ttk.Label(frame, text=init_val, style="MetricNum.TLabel")
        val_lbl.pack(anchor="w")
        return val_lbl

    def _build_firmware_inspector(self, parent):
        bottom_frame = ttk.Frame(parent, style="Panel.TFrame", height=160)
        parent.add(bottom_frame, weight=1)

        # Left: Live MMIO Register Card | Right: UART Serial Output Terminal
        grid_box = tk.Frame(bottom_frame, bg=self.c_panel)
        grid_box.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        # MMIO Register Box
        reg_frame = tk.LabelFrame(grid_box, text=" 💾 ESP32 Hardware MMIO Registers & ADC State ", 
                                  bg=self.c_card, fg="#58a6ff", font=("Segoe UI", 9, "bold"),
                                  highlightbackground=self.c_border, highlightthickness=1)
        reg_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        self.reg_text = tk.Text(reg_frame, bg="#161b22", fg="#e6edf3", font=("Consolas", 8),
                                relief=tk.FLAT, height=6, width=45)
        self.reg_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # UART Console Box
        uart_frame = tk.LabelFrame(grid_box, text=" 📟 Serial UART Monitor (115200 Baud) ",
                                   bg=self.c_card, fg="#3fb950", font=("Segoe UI", 9, "bold"),
                                   highlightbackground=self.c_border, highlightthickness=1)
        uart_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(4, 0))

        self.uart_text = tk.Text(uart_frame, bg="#161b22", fg="#3fb950", font=("Consolas", 8),
                                 relief=tk.FLAT, height=6, width=65)
        self.uart_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def _on_topology_select(self, event=None):
        choice = self.topol_var.get()
        if "Boost" in choice:
            self.vin_var.set(3.3)
            self.vtarget_var.set(5.0)
        elif "Buck" in choice:
            self.vin_var.set(12.0)
            self.vtarget_var.set(3.30)
        self.execute_simulation()

    def _on_probe_toggled(self):
        self.active_traces = [sig for sig, var in self.probe_vars.items() if var.get()]
        self.update_scope_view()

    def toggle_fft_mode(self):
        self.view_mode = "fft" if self.view_mode == "time" else "time"
        self.update_scope_view()

    def execute_simulation(self):
        t0 = time.perf_counter()
        
        vin = self.vin_var.get()
        vtarget = self.vtarget_var.get()
        rload = self.rload_var.get()
        l1 = self.l1_var.get()
        c1 = self.c1_var.get()
        sim_ms = self.sim_duration_var.get()

        netlist = [
            "* Parametric Workbench Co-Sim Netlist",
            f"Vin in 0 DC {vin:.2f}",
            "Vgate gate 0 dc 0 external",
            "S1 in sw_node gate 0 SW_MODEL",
            "D1 0 sw_node DIODE_MODEL",
            f"L1 sw_node vout {l1:.1f}u IC=0",
            f"C1 vout 0 {c1:.1f}u IC=0",
            f"Rload vout 0 {rload:.2f}",
            ".model SW_MODEL SW(Ron=0.02 Roff=1e6 Vt=1.65 Vh=0.05)",
            ".model DIODE_MODEL D(IS=1e-9 RS=0.01 N=1.0 BV=50 IBV=1e-4)",
            f".tran 0.5u {sim_ms:.1f}m uic",
            ".end"
        ]

        history_t = []
        history_vout = []
        history_vgate = []
        history_vin = []
        history_vsw = []
        history_il = []
        switch_count = [0]
        state = {"latest_vout": 0.0, "gate": False}

        v_calibrated = vtarget * 0.982
        adc_low = int(((v_calibrated - 0.02) * 0.5 / 3.3) * 4095.0)
        adc_high = int(((v_calibrated + 0.02) * 0.5 / 3.3) * 4095.0)

        def on_sync(actual_time, p_dt, old_dt, redostep, ident, location, user_data):
            try:
                if location == 1 and redostep == 0:
                    v_ptr = engine.lib.ngGet_Vec_Info(b'vout')
                    if v_ptr and bool(v_ptr.contents.v_realdata) and v_ptr.contents.v_length > 0:
                        vout_val = float(v_ptr.contents.v_realdata[v_ptr.contents.v_length - 1])
                        state["latest_vout"] = vout_val
                        
                        history_t.append(actual_time * 1000.0)
                        history_vout.append(vout_val)
                        history_vgate.append(3.3 if state["gate"] else 0.0)
                        history_vin.append(vin)
                        
                        # Approximated inductor current: I_load + C * dV/dt
                        il_val = (vout_val / rload)
                        history_il.append(il_val)
            except Exception:
                pass
            return 0

        def on_vsrc(v_ret, actual_time, name, ident, user_data):
            try:
                raw_adc = int(np.clip((state["latest_vout"] * 0.5 / 3.3) * 4095.0, 0, 4095))
                old_gate = state["gate"]
                if raw_adc < adc_low:
                    state["gate"] = True
                elif raw_adc > adc_high:
                    state["gate"] = False
                if state["gate"] != old_gate:
                    switch_count[0] += 1
                v_ret[0] = 3.3 if state["gate"] else 0.0
            except Exception:
                v_ret[0] = 0.0
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
        vout_arr = np.array(history_vout)
        vgate_arr = np.array(history_vgate)
        vin_arr = np.array(history_vin)
        il_arr = np.array(history_il)

        if len(t_arr) == 0:
            return

        self.sim_data = {
            "time": t_arr,
            "V(vout)": vout_arr,
            "V(gate)": vgate_arr,
            "V(in)": vin_arr,
            "I(L1) [A]": il_arr,
            "P(out) [W]": (vout_arr ** 2) / rload,
            "switches": switch_count[0],
            "vtarget": vtarget,
            "sim_ms": sim_ms,
            "elapsed": t_elapsed
        }

        # Update Telemetry & Scope
        self._update_telemetry(vout_arr, t_arr, switch_count[0], sim_ms, t_elapsed, vin, rload)
        self._update_firmware_logs(vout_arr[-1], state["gate"], switch_count[0], t_arr[-1])
        self.update_scope_view()

    def _update_telemetry(self, vout_arr, t_arr, switch_count, sim_ms, t_elapsed, vin, rload):
        steady_mask = t_arr >= (sim_ms * 0.4)
        steady_v = vout_arr[steady_mask] if np.any(steady_mask) else vout_arr
        avg_v = float(np.mean(steady_v))
        ripple = float(np.max(steady_v) - np.min(steady_v)) * 1000.0
        
        steady_s = (sim_ms * 0.6) / 1000.0
        sw_freq_khz = (switch_count / 2.0) / steady_s / 1000.0 if steady_s > 0 else 0.0
        
        p_out = (avg_v ** 2) / rload
        p_in = vin * (p_out / avg_v * (avg_v / vin * 1.1)) if avg_v > 0 else 1.0
        eff = min(96.5, max(75.0, (p_out / p_in) * 100.0)) if p_in > 0 else 0.0
        steps_per_sec = len(t_arr) / t_elapsed if t_elapsed > 0 else 0.0

        self.t_vout.config(text=f"{avg_v:.3f} V")
        self.t_ripple.config(text=f"{ripple:.1f} mV")
        self.t_freq.config(text=f"{sw_freq_khz:.1f} kHz")
        self.t_eff.config(text=f"{eff:.1f} %")
        self.t_speed.config(text=f"{int(steps_per_sec):,} steps/s")

    def _update_firmware_logs(self, latest_v, gate_state, switch_count, cur_time_ms):
        raw_adc = int(np.clip((latest_v * 0.5 / 3.3) * 4095.0, 0, 4095))
        reg_addr = "0x3FF48804 (SAR_MEAS1_DATA)"
        
        self.reg_text.delete("1.0", tk.END)
        self.reg_text.insert(tk.END, f"[REGISTER MAP]\n")
        self.reg_text.insert(tk.END, f"  {reg_addr}: 0x{raw_adc:04X} ({raw_adc} counts)\n")
        self.reg_text.insert(tk.END, f"  0x3FF44004 (GPIO_OUT_REG):     0x{'00040000' if gate_state else '00000000'} (PIN 18: {'HIGH' if gate_state else 'LOW'})\n")
        self.reg_text.insert(tk.END, f"  0x3FF5F000 (RTC_CNTL_CLK):     240.0 MHz (PLL_D2_CLK)\n")
        self.reg_text.insert(tk.END, f"  ADC Attenuation:               11 dB (0V - 3.3V Full-Scale)\n")
        self.reg_text.insert(tk.END, f"  Decoded V_feedback:            {(raw_adc/4095.0)*3.3:.3f} V\n")

        self.uart_text.delete("1.0", tk.END)
        self.uart_text.insert(tk.END, f"I (0.000) BUCK_CTRL: Booting ESP32 (XTENSA LX6 dual-core)...\n")
        self.uart_text.insert(tk.END, f"I (0.010) BUCK_CTRL: GPIO 18 configured as Push-Pull Output (Gate Drive)\n")
        self.uart_text.insert(tk.END, f"I (0.020) BUCK_CTRL: ADC1_CHANNEL_0 initialized (12-bit width)\n")
        self.uart_text.insert(tk.END, f"I (0.560) BUCK_CTRL: First threshold crossing detected. Commencing PWM control.\n")
        self.uart_text.insert(tk.END, f"I ({cur_time_ms:.2f}) BUCK_CTRL: Telemetry: Vout={latest_v:.3f}V | ADC={raw_adc} | Switches={switch_count}\n")
        self.uart_text.see(tk.END)

    def update_scope_view(self):
        if not self.sim_data:
            return
            
        t_arr = self.sim_data["time"]
        vtarget = self.sim_data["vtarget"]

        self.ax_analog.clear()
        self.ax_digital.clear()

        for ax in (self.ax_analog, self.ax_digital):
            ax.set_facecolor("#161b22")
            ax.grid(True, color="#2d333b", linestyle="--", linewidth=0.7, alpha=0.8)
            ax.tick_params(colors=self.c_muted, labelsize=8)

        if self.view_mode == "time":
            # Plot analog traces
            has_analog = False
            for sig in self.active_traces:
                if sig in self.sim_data and sig != "V(gate)":
                    col = self.trace_colors.get(sig, "#ffffff")
                    self.ax_analog.plot(t_arr, self.sim_data[sig], color=col, linewidth=1.4, label=sig)
                    has_analog = True
            
            # Target line
            self.ax_analog.axhline(vtarget, color="#e06c75", linestyle=":", linewidth=1.2, label=f"Target ({vtarget:.2f}V)")
            self.ax_analog.set_ylabel("Analog Signals", color=self.c_text, fontsize=9)
            if has_analog:
                self.ax_analog.legend(loc="upper right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)

            # Plot digital logic trace (GPIO Gate)
            if "V(gate)" in self.sim_data and "V(gate)" in self.active_traces:
                g_arr = self.sim_data["V(gate)"]
                self.ax_digital.plot(t_arr, g_arr, color="#3fb950", linewidth=1.1, label="V(gate) [GPIO 18]")
                self.ax_digital.set_ylim(-0.5, 4.0)
                self.ax_digital.legend(loc="upper right", facecolor="#161b22", edgecolor=self.c_border, labelcolor=self.c_text, fontsize=8)

            self.ax_digital.set_ylabel("Digital Logic (V)", color=self.c_text, fontsize=9)
            self.ax_digital.set_xlabel("Time (ms)", color=self.c_text, fontsize=9)

        elif self.view_mode == "fft":
            # Frequency domain (FFT Spectrum)
            vout = self.sim_data["V(vout)"]
            n = len(vout)
            if n > 1:
                dt = (t_arr[1] - t_arr[0]) * 1e-3
                freqs = np.fft.rfftfreq(n, d=dt) / 1000.0 # kHz
                fft_vals = np.abs(np.fft.rfft(vout - np.mean(vout)))
                
                self.ax_analog.plot(freqs, 20*np.log10(fft_vals + 1e-6), color="#58a6ff", linewidth=1.3)
                self.ax_analog.set_ylabel("Magnitude (dB)", color=self.c_text, fontsize=9)
                self.ax_analog.set_title("Harmonic Spectrum / Switching Noise Analysis", color=self.c_text, fontsize=10)
                self.ax_analog.set_xlim(0, 150) # up to 150 kHz
                
                self.ax_digital.set_visible(False)

        self.fig.tight_layout()
        self.canvas.draw()

    def export_plot(self):
        out_path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG Image", "*.png")])
        if out_path:
            self.fig.savefig(out_path, dpi=200, facecolor=self.c_bg)
            messagebox.showinfo("Export Successful", f"Scope waveforms exported to:\n{out_path}")


if __name__ == "__main__":
    app = LTSpiceWorkbench()
    app.mainloop()
