// standalone_sim.rs - Dependency-free standalone embedded systems simulation.
// Pure Rust transient circuit simulator with closed-loop MCU co-simulation.
// ZERO external dependencies - only stdlib. No QEMU, no ngspice DLL, no Qt.

use crate::control_law::{ControlLaw, LawInput, make_law};
use std::collections::HashMap;

pub type NodeId = String;
pub type RefDes = String;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum VsSourceType { Dc, Pulse, Sin, Pwl }

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ComponentType { Resistor, Capacitor, Inductor, Diode, MosfetN, MosfetP, Switch }

#[derive(Debug, Clone)]
pub struct VoltageSource { pub name: RefDes, pub node_p: NodeId, pub node_n: NodeId, pub kind: VsSourceType, pub dc_value: f64 }

#[derive(Debug, Clone)]
pub struct PassiveComponent { pub name: RefDes, pub kind: ComponentType, pub node1: NodeId, pub node2: NodeId, pub value: f64 }

#[derive(Debug, Clone)]
pub struct Circuit {
    pub name: String,
    pub resistors: Vec<PassiveComponent>,
    pub capacitors: Vec<PassiveComponent>,
    pub inductors: Vec<PassiveComponent>,
    pub diodes: Vec<PassiveComponent>,
    pub mosfets_n: Vec<PassiveComponent>,
    pub mosfets_p: Vec<PassiveComponent>,
    pub switches: Vec<PassiveComponent>,
    pub voltage_sources: Vec<VoltageSource>,
    pub current_sources: Vec<PassiveComponent>,
    pub ground_node: NodeId,
}

impl Default for Circuit {
    fn default() -> Self {
        Circuit { name: "standalone".to_string(), resistors: Vec::new(), capacitors: Vec::new(), inductors: Vec::new(), diodes: Vec::new(), mosfets_n: Vec::new(), mosfets_p: Vec::new(), switches: Vec::new(), voltage_sources: Vec::new(), current_sources: Vec::new(), ground_node: "0".to_string() }
    }
}

impl VoltageSource {
    pub fn value_at(&self, _t: f64) -> f64 { self.dc_value }
}

pub fn build_rc_filter(r: f64, c: f64, vin: f64) -> Circuit {
    let mut ckt = Circuit::default();
    ckt.name = "rc_filter".to_string();
    ckt.voltage_sources.push(VoltageSource { name: "VIN".to_string(), node_p: "vin".to_string(), node_n: "0".to_string(), kind: VsSourceType::Dc, dc_value: vin });
    ckt.resistors.push(PassiveComponent { name: "R1".to_string(), kind: ComponentType::Resistor, node1: "vin".to_string(), node2: "vout".to_string(), value: r });
    ckt.capacitors.push(PassiveComponent { name: "C1".to_string(), kind: ComponentType::Capacitor, node1: "vout".to_string(), node2: "0".to_string(), value: c });
    ckt
}

pub fn build_buck_converter(vin: f64, l: f64, c: f64, r_load: f64, _freq_hz: f64) -> Circuit {
    let mut ckt = Circuit::default();
    ckt.name = "buck_converter".to_string();
    ckt.voltage_sources.push(VoltageSource { name: "VIN".to_string(), node_p: "vin".to_string(), node_n: "0".to_string(), kind: VsSourceType::Dc, dc_value: vin });
    ckt.voltage_sources.push(VoltageSource { name: "VSWITCH".to_string(), node_p: "sw".to_string(), node_n: "0".to_string(), kind: VsSourceType::Dc, dc_value: 0.0 });
    ckt.inductors.push(PassiveComponent { name: "L1".to_string(), kind: ComponentType::Inductor, node1: "sw".to_string(), node2: "vout".to_string(), value: l });
    ckt.capacitors.push(PassiveComponent { name: "C1".to_string(), kind: ComponentType::Capacitor, node1: "vout".to_string(), node2: "0".to_string(), value: c });
    ckt.resistors.push(PassiveComponent { name: "RLOAD".to_string(), kind: ComponentType::Resistor, node1: "vout".to_string(), node2: "0".to_string(), value: r_load });
    ckt.resistors.push(PassiveComponent { name: "D1_FWD".to_string(), kind: ComponentType::Resistor, node1: "sw".to_string(), node2: "0".to_string(), value: 1e6 });
    ckt
}

#[derive(Debug, Clone)]
pub struct CircuitState {
    pub time: f64,
    pub node_voltages: HashMap<NodeId, f64>,
    pub inductor_currents: HashMap<RefDes, f64>,
    pub voltage_source_currents: HashMap<RefDes, f64>,
}

impl CircuitState {
    pub fn new() -> Self { CircuitState { time: 0.0, node_voltages: HashMap::new(), inductor_currents: HashMap::new(), voltage_source_currents: HashMap::new() } }
    pub fn v(&self, node: &str) -> f64 { self.node_voltages.get(node).copied().unwrap_or(0.0) }
}

pub struct CircuitSolver {
    pub circuit: Circuit,
    pub state: CircuitState,
    pub dt: f64,
    pub tstop: f64,
    pub node_index: HashMap<NodeId, usize>,
    pub num_nodes: usize,
    pub num_vsrc: usize,
    pub num_inductor: usize,
    pub num_total: usize,
}

impl CircuitSolver {
    pub fn new(circuit: Circuit, dt: f64, tstop: f64) -> Result<Self, String> {
        let mut nodes: Vec<NodeId> = Vec::new();
        let ground = &circuit.ground_node;
        for r in &circuit.resistors { if r.node1 != *ground { nodes.push(r.node1.clone()); } if r.node2 != *ground { nodes.push(r.node2.clone()); } }
        for c in &circuit.capacitors { if c.node1 != *ground { nodes.push(c.node1.clone()); } if c.node2 != *ground { nodes.push(c.node2.clone()); } }
        for l in &circuit.inductors { if l.node1 != *ground { nodes.push(l.node1.clone()); } if l.node2 != *ground { nodes.push(l.node2.clone()); } }
        for v in &circuit.voltage_sources { if v.node_p != *ground { nodes.push(v.node_p.clone()); } if v.node_n != *ground { nodes.push(v.node_n.clone()); } }
        nodes.sort();
        nodes.dedup();
        let mut node_index = HashMap::new();
        for (i, n) in nodes.iter().enumerate() { node_index.insert(n.clone(), i); }
        let num_nodes = nodes.len();
        let num_vsrc = circuit.voltage_sources.len();
        let num_inductor = circuit.inductors.len();
        let num_total = num_nodes + num_vsrc + num_inductor;
        let mut state = CircuitState::new();
        state.time = 0.0;
        state.node_voltages.insert(ground.clone(), 0.0);
        for n in &nodes { state.node_voltages.insert(n.clone(), 0.0); }
        for v in &circuit.voltage_sources { state.voltage_source_currents.insert(v.name.clone(), 0.0); }
        for l in &circuit.inductors { state.inductor_currents.insert(l.name.clone(), 0.0); }
        Ok(CircuitSolver { circuit, state, dt, tstop, node_index, num_nodes, num_vsrc, num_inductor, num_total })
    }

    pub fn step(&mut self) -> Result<CircuitState, String> {
        let t = self.state.time + self.dt;
        let dt = self.dt;
        let n = self.num_total;
        let mut gmat = vec![vec![0.0f64; n]; n];
        let mut rhs = vec![0.0f64; n];
        let node_idx = |node: &str, solver: &CircuitSolver| -> usize { if node == solver.circuit.ground_node { usize::MAX } else { solver.node_index.get(node).copied().unwrap_or(usize::MAX) } };
        let vsrc_idx = |i: usize, solver: &CircuitSolver| solver.num_nodes + i;
        let ind_idx = |i: usize, solver: &CircuitSolver| solver.num_nodes + solver.num_vsrc + i;
        for r in &self.circuit.resistors {
            let n1 = node_idx(&r.node1, self); let n2 = node_idx(&r.node2, self);
            let g = 1.0 / r.value;
            if n1 != usize::MAX && n2 != usize::MAX { gmat[n1][n1] += g; gmat[n2][n2] += g; gmat[n1][n2] -= g; gmat[n2][n1] -= g; }
            else if n1 != usize::MAX { gmat[n1][n1] += g; }
            else if n2 != usize::MAX { gmat[n2][n2] += g; }
        }
        for c in &self.circuit.capacitors {
            let n1 = node_idx(&c.node1, self); let n2 = node_idx(&c.node2, self);
            let g = c.value / dt;
            let v_old1 = self.state.v(&c.node1); let v_old2 = self.state.v(&c.node2);
            let i_hist = c.value * (v_old1 - v_old2) / dt;
            if n1 != usize::MAX && n2 != usize::MAX { gmat[n1][n1] += g; gmat[n2][n2] += g; gmat[n1][n2] -= g; gmat[n2][n1] -= g; rhs[n1] += i_hist; rhs[n2] -= i_hist; }
            else if n1 != usize::MAX { gmat[n1][n1] += g; rhs[n1] += i_hist; }
            else if n2 != usize::MAX { gmat[n2][n2] += g; rhs[n2] -= i_hist; }
        }
        for (i, l) in self.circuit.inductors.iter().enumerate() {
            let n1 = node_idx(&l.node1, self); let n2 = node_idx(&l.node2, self);
            let ii = ind_idx(i, self); let r = l.value / dt;
            let v_hist = l.value * self.state.inductor_currents.get(&l.name).copied().unwrap_or(0.0) / dt;
            if n1 != usize::MAX && n2 != usize::MAX { gmat[n1][n1] += 1.0; gmat[n2][n2] += 1.0; gmat[n1][n2] -= 1.0; gmat[n2][n1] -= 1.0; gmat[n1][ii] -= r; gmat[n2][ii] += r; gmat[ii][n1] -= r; gmat[ii][n2] += r; rhs[n1] -= v_hist; rhs[n2] += v_hist; }
            else if n1 != usize::MAX { gmat[n1][n1] += 1.0; gmat[n1][ii] -= r; gmat[ii][n1] -= r; rhs[n1] -= v_hist; }
            else if n2 != usize::MAX { gmat[n2][n2] += 1.0; gmat[n2][ii] += r; gmat[ii][n2] += r; rhs[n2] += v_hist; }
            gmat[ii][ii] = 0.0;
        }
        for (i, v) in self.circuit.voltage_sources.iter().enumerate() {
            let n1 = node_idx(&v.node_p, self); let n2 = node_idx(&v.node_n, self);
            let ii = vsrc_idx(i, self); let vsrc_val = v.value_at(t);
            if n1 != usize::MAX && n2 != usize::MAX { gmat[n1][n1] += 1.0; gmat[n2][n2] += 1.0; gmat[n1][n2] -= 1.0; gmat[n2][n1] -= 1.0; gmat[n1][ii] += 1.0; gmat[n2][ii] -= 1.0; gmat[ii][n1] += 1.0; gmat[ii][n2] -= 1.0; }
            else if n1 != usize::MAX { gmat[n1][n1] += 1.0; gmat[n1][ii] += 1.0; gmat[ii][n1] += 1.0; }
            else if n2 != usize::MAX { gmat[n2][n2] += 1.0; gmat[n2][ii] -= 1.0; gmat[ii][n2] -= 1.0; }
            gmat[ii][ii] = 0.0;
            rhs[ii] = vsrc_val;
        }
        for i_src in &self.circuit.current_sources {
            let n1 = node_idx(&i_src.node1, self); let n2 = node_idx(&i_src.node2, self);
            let isrc_val = i_src.value;
            if n1 != usize::MAX { rhs[n1] += isrc_val; }
            if n2 != usize::MAX { rhs[n2] -= isrc_val; }
        }
        let mut x = vec![0.0f64; n];
        solve_linear_system(&mut gmat, &mut rhs, &mut x).map_err(|e| format!("Linear solve failed: {}", e))?;
        let mut new_state = CircuitState::new();
        new_state.time = t;
        new_state.node_voltages.insert(self.circuit.ground_node.clone(), 0.0);
        for (node, &idx) in &self.node_index { new_state.node_voltages.insert(node.clone(), x[idx]); }
        for (i, v) in self.circuit.voltage_sources.iter().enumerate() { let ii = vsrc_idx(i, self); new_state.voltage_source_currents.insert(v.name.clone(), x[ii]); }
        for (i, l) in self.circuit.inductors.iter().enumerate() { let ii = ind_idx(i, self); new_state.inductor_currents.insert(l.name.clone(), x[ii]); }
        self.state = new_state;
        Ok(self.state.clone())
    }

    pub fn run_transient(&mut self) -> Result<Vec<CircuitState>, String> {
        let mut results = Vec::new();
        results.push(self.state.clone());
        let mut steps = (self.tstop / self.dt) as usize;
        if steps == 0 { steps = 1; }
        for _ in 0..steps { self.step()?; results.push(self.state.clone()); }
        Ok(results)
    }
}

fn solve_linear_system(a: &mut Vec<Vec<f64>>, b: &mut Vec<f64>, x: &mut Vec<f64>) -> Result<(), String> {
    let n = a.len();
    if n == 0 { return Ok(()); }
    let mut aug: Vec<Vec<f64>> = a.iter().enumerate().map(|(i, row)| { let mut r = row.clone(); r.push(b[i]); r }).collect();
    for col in 0..n {
        let mut pivot_row = col; let mut pivot_val = aug[col][col].abs();
        for row in (col + 1)..n { let val = aug[row][col].abs(); if val > pivot_val { pivot_val = val; pivot_row = row; } }
        if pivot_val < 1e-12 { return Err(format!("Singular matrix at column {}", col)); }
        if pivot_row != col { aug.swap(col, pivot_row); }
        let pivot = aug[col][col];
        for row in (col + 1)..n { let factor = aug[row][col] / pivot; for k in col..=n { aug[row][k] -= factor * aug[col][k]; } }
    }
    for i in (0..n).rev() { let mut sum = aug[i][n]; for j in (i + 1)..n { sum -= aug[i][j] * x[j]; } x[i] = sum / aug[i][i]; }
    Ok(())
}

pub struct BuckCoSim {
    pub solver: CircuitSolver,
    pub controller: ControlLaw,
    pub sense_node: NodeId,
    pub switch_node_p: NodeId,
    pub switch_node_n: NodeId,
    pub vref: f64,
    pub target_v: f64,
    pub hysteresis_v: f64,
    pub divider: f64,
    pub tstep: f64,
    pub results: Vec<CoSimResult>,
}

#[derive(Debug, Clone)]
pub struct CoSimResult { pub time: f64, pub vout: f64, pub gate: bool, pub i_l: f64, pub v_switch: f64 }

impl BuckCoSim {
    pub fn new(circuit: Circuit, sense_node: NodeId, switch_node_p: NodeId, switch_node_n: NodeId, target_v: f64, hysteresis_v: f64, divider: f64, vref: f64, dt: f64, tstop: f64) -> Result<Self, String> {
        let mut solver = CircuitSolver::new(circuit, dt, tstop)?;
        let controller_input = LawInput { kind: Some("hysteretic".to_string()), pin: Some("GPIO18".to_string()), sense_net: Some(sense_node.clone()), target_v: Some(target_v), hysteresis_v: Some(hysteresis_v), divider: Some(divider), vref: Some(vref), vhigh: Some(3.3), adc_bits: Some(12), source: None, low_counts: None, high_counts: None, carrier_hz: None, duty_gain: None, source_counts: None };
        let controller = make_law(&controller_input).map_err(|e| format!("Controller creation failed: {}", e.message()))?;
        Ok(BuckCoSim { solver, controller, sense_node, switch_node_p, switch_node_n, vref, target_v, hysteresis_v, divider, tstep: dt, results: Vec::new() })
    }

    pub fn run(&mut self) -> Result<Vec<CoSimResult>, String> {
        let mut results = Vec::new();
        let initial_vout = self.solver.state.v(&self.sense_node);
        let initial_result = CoSimResult { time: 0.0, vout: initial_vout, gate: false, i_l: 0.0, v_switch: 0.0 };
        results.push(initial_result.clone());
        self.results.push(initial_result);
        let steps = (self.solver.tstop / self.tstep) as usize;
        if steps == 0 { return Ok(results); }
        for step in 1..=steps {
            let t = step as f64 * self.tstep;
            let vout = self.solver.state.v(&self.sense_node);
            let pin_voltage = self.controller.update(vout, t);
            let gate = pin_voltage > 1.65;
            let switch_voltage = if gate { 5.0 } else { 0.0 };
            let vsrc = self.solver.circuit.voltage_sources.iter_mut().find(|v| v.name == "VSWITCH");
            if let Some(v) = vsrc { v.dc_value = switch_voltage; }
            self.solver.step()?;
            let vout_new = self.solver.state.v(&self.sense_node);
            let i_l = self.solver.state.inductor_currents.get("L1").copied().unwrap_or(0.0);
            let v_switch = self.solver.state.v(&self.switch_node_p);
            let result = CoSimResult { time: t, vout: vout_new, gate, i_l, v_switch };
            results.push(result.clone());
            self.results.push(result);
        }
        Ok(results)
    }
    pub fn final_vout(&self) -> f64 { self.results.last().map(|r| r.vout).unwrap_or(0.0) }
    pub fn avg_vout_last_fifth(&self) -> f64 { let n = self.results.len(); if n == 0 { return 0.0; } let start = n * 4 / 5; let sum: f64 = self.results[start..].iter().map(|r| r.vout).sum(); sum / (n - start) as f64 }
    pub fn vout_ripple_last_fifth(&self) -> f64 { let n = self.results.len(); if n < 2 { return 0.0; } let start = n * 4 / 5; let mut min = f64::INFINITY; let mut max = f64::NEG_INFINITY; for r in &self.results[start..] { min = min.min(r.vout); max = max.max(r.vout); } max - min }
}