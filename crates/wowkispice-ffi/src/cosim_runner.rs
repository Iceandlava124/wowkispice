/*
 * cosim_runner.rs - Closed-loop mixed-signal co-simulation run harness.
 *
 * Stub port of bridge/cosim_runner.py. The full port requires wiring the
 * ngspice FFI callbacks (GetVSRCData) into the control law loop, which needs
 * careful lifetime management. For now, this module provides the public
 * surface (CosimRun, run_cosim, describe_run) with stub implementations that
 * record warnings instead of running the solver.
 */

use std::collections::HashMap;

use wowkispice_core::cad_engine::SchematicNetlistEngine;
use wowkispice_core::control_law::LawSpec;

/// Result of one co-simulation run.
pub struct CosimRun {
    pub time: Vec<f64>,
    pub traces: HashMap<String, Vec<f64>>,
    pub laws: HashMap<String, String>, // pin -> law description
    pub netlist: Vec<String>,
    pub nets: Vec<String>,
    pub warnings: Vec<String>,
    pub callback_hits: i32,
    pub aborted: bool,
}

impl CosimRun {
    pub fn pin_trace(&self, _pin: &str) -> Vec<f64> {
        Vec::new()
    }

    pub fn regulation(&self, _pin: &str) -> HashMap<String, Option<f64>> {
        HashMap::new()
    }

    pub fn stats(&self) -> Vec<wowkispice_core::control_law::LawStats> {
        Vec::new()
    }

    pub fn summary_lines(&self) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        out.push(format!(
            "Closed-loop run: {} points, {} control callbacks, {} law(s)",
            run_time_len(&self.time),
            self.callback_hits,
            self.laws.len()
        ));
        for w in &self.warnings {
            out.push(format!("warning: {}", w));
        }
        out
    }
}

/// Compile `model`, execute the netlist, and drive each entry of `laws`.
///
/// Stub implementation: loads the netlist into ngspice and runs it, but does
/// not yet drive control laws via the VSRC callback. Returns warnings for
/// any declared laws that could not be wired.
pub fn run_cosim(
    model: &SchematicNetlistEngine,
    laws: &HashMap<String, LawSpec>,
    vin: f64,
    tstep_us: f64,
    duration_ms: f64,
    probe_nets: Option<&[&str]>,
) -> CosimRun {
    let mut run = CosimRun {
        time: Vec::new(),
        traces: HashMap::new(),
        laws: HashMap::new(),
        netlist: Vec::new(),
        nets: Vec::new(),
        warnings: Vec::new(),
        callback_hits: 0,
        aborted: false,
    };

    let opts = wowkispice_core::cad_engine::CompileOptions {
        vin,
        tstep_us,
        duration_ms,
        ..Default::default()
    };
    let (lines, nets, netlist_warnings) = model.compile_netlist(opts);
    run.netlist = lines.iter().map(|s| s.clone()).collect();
    let probe_refs: Vec<&str> = match probe_nets {
        Some(s) => s.to_vec(),
        None => nets.iter().map(|s| s.as_str()).collect(),
    };
    run.nets = probe_refs.iter().map(|s| s.to_string()).collect();
    run.warnings = netlist_warnings;

    for (pin, _spec) in laws {
        run.warnings.push(format!(
            "control law for {} not yet implemented in Rust FFI",
            pin
        ));
        run.laws.insert(pin.clone(), format!("{} (not implemented)", pin));
    }

    if laws.is_empty() {
        run.warnings
            .push("no executable control law; nothing was closed-loop".to_string());
        return run;
    }

    let mut engine = match crate::NgSpiceFfi::new() {
        Ok(e) => e,
        Err(exc) => {
            run.warnings.push(format!("cannot start ngspice: {}", exc));
            return run;
        }
    };

    engine.init(None, None, None).expect("ngSpice_Init should succeed");

    let netlist_refs: Vec<&str> = run.netlist.iter().map(|s| s.as_str()).collect();
    if let Err(e) = engine.load_circuit(&netlist_refs) {
        run.warnings.push(format!("load_circuit failed: {}", e));
        return run;
    }
    if let Err(e) = engine.cmd("run") {
        run.warnings.push(format!("run failed: {}", e));
        return run;
    }

    run.time = engine
        .get_vector_array("time")
        .unwrap_or_else(|_| Vec::new());
    for net in &run.nets {
        if let Ok(values) = engine.get_vector_array(net) {
            if !values.is_empty() {
                run.traces.insert(net.clone(), values);
            }
        }
    }

    run
}

/// Multi-line console report for a co-simulation run.
pub fn describe_run(run: &CosimRun) -> String {
    let header = format!(
        "Closed-loop run: {} points, {} control callbacks, {} law(s)",
        run.time.len(),
        run.callback_hits,
        run.laws.len()
    );
    let mut out = vec![header];
    out.extend(run.summary_lines());
    out.join("\n")
}

fn run_time_len(times: &[f64]) -> usize {
    times.len()
}
