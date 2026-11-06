/*
 * cosim_runner.rs - Closed-loop mixed-signal co-simulation run harness.
 *
 * Runs a schematic in ngspice while one or more MCU control laws drive
 * `external` voltage sources in lockstep with the solver. The law reads its
 * sense net out of the live plot on every callback, so the pin reacts to the
 * circuit instead of playing back a declared waveform.
 *
 * Sequence per callback (ngspice GetVSRCData):
 *     1. read the sense net's most recently accepted sample
 *     2. hand it to the law (ADC quantisation + decision)
 *     3. return the pin voltage for this instant
 *
 * Port of bridge/cosim_runner.py to Rust, using wowkispice-ffi::NgSpiceFfi.
 *
 * Note: ngspice maintains global C state. Callbacks fire during cmd("run"),
 * so they cannot borrow `&self` from NgSpiceFfi. Instead, we extract the
 * ngGet_Vec_Info function pointer before calling cmd() and call it directly
 * from within the callback. All data captured by the closure is owned
 * (Box<HashMap<...>>), not borrowed, to satisfy Rust's 'static requirement.
 */

use std::collections::HashMap;
use std::collections::HashSet;
use std::os::raw::c_void;
use std::ptr;

use wowkispice_core::cad_engine::{is_mcu, SchematicNetlistEngine};
use wowkispice_core::control_law::{ControlLaw, LawInput, make_law};
use crate::NgSpiceFfi;
use crate::{getisrcdata_trampoline, getsyncdata_trampoline, getvsrcdata_trampoline};

/// Result of one co-simulation run.
pub struct CosimRun {
    pub time: Vec<f64>,
    pub traces: HashMap<String, Vec<f64>>,
    pub laws: HashMap<String, ControlLaw>, // pin -> executed law
    pub netlist: Vec<String>,
    pub nets: Vec<String>,
    pub warnings: Vec<String>,
    pub callback_hits: i32,
    pub aborted: bool,
}

impl CosimRun {
    // ----------------------------------------------------------------------
    // Convenience views for the UI / tests --------------------------

    pub fn pin_trace(&self, pin: &str) -> Vec<f64> {
        self.laws
            .get(pin)
            .map(|law| law.history_pin.clone())
            .unwrap_or_default()
    }

    pub fn regulation(&self, pin: &str) -> HashMap<String, Option<f64>> {
        let mut out = HashMap::new();
        out.insert("mean_error_counts".to_string(), None);
        out.insert("max_error_counts".to_string(), None);
        out.insert("mean_error_v".to_string(), None);
        out.insert("final_error_counts".to_string(), None);

        let law = match self.laws.get(pin) {
            Some(l) => l,
            None => return out,
        };
        if law.history_counts.is_empty() {
            return out;
        }
        let target = _midpoint_counts(law);
        if let Ok(reg) = wowkispice_core::control_law::regulation_error(
            &law.history_counts,
            target,
            law.spec.vref,
            law.adc_bits,
        ) {
            out.insert(
                "mean_error_counts".to_string(),
                reg.mean_error_counts,
            );
            out.insert(
                "max_error_counts".to_string(),
                reg.max_error_counts,
            );
            out.insert("mean_error_v".to_string(), reg.mean_error_v);
            out.insert(
                "final_error_counts".to_string(),
                reg.final_error_counts,
            );
        }
        out
    }

    pub fn stats(&self) -> Vec<wowkispice_core::control_law::LawStats> {
        self.laws.values().map(|law| law.stats()).collect()
    }

    pub fn summary_lines(&self) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        for (pin, law) in &self.laws {
            let s = law.stats();
            let reg = self.regulation(pin);
            out.push(format!(
                "{} <- {}: {} samples, {} switch events, duty {:.1}%, ADC {}..{} counts, final {}",
                pin,
                law.sense_net,
                s.samples,
                s.switches,
                s.duty * 100.0,
                s.counts_min.unwrap_or(0),
                s.counts_max.unwrap_or(0),
                s.final_level
            ));
            if let Some(mean) = reg.get("mean_error_counts").and_then(|m| *m) {
                if let Some(mev) = reg.get("mean_error_v").and_then(|m| *m) {
                    if let Some(maxe) = reg.get("max_error_counts").and_then(|m| *m)
                    {
                        out.push(format!(
                            "    regulation error: mean {:+.1} counts ({:+.4} V), max |{:.0}| counts",
                            mean, mev, maxe
                        ));
                    }
                }
            }
        }
        for w in &self.warnings {
            out.push(format!("warning: {}", w));
        }
        out
    }
}

/// Target count for a law, from whichever spec form it carries.
fn _midpoint_counts(law: &ControlLaw) -> i64 {
    if law.spec.low_counts.is_some() && law.spec.high_counts.is_some() {
        (law.spec.low_counts.unwrap() + law.spec.high_counts.unwrap()) / 2
    } else {
        wowkispice_core::control_law::to_counts_raw(
            law.spec.target_v * law.divider,
            law.spec.vref,
            law.adc_bits,
        )
    }
}

/// Identifier scrubber, matching SchematicNetlistEngine._safe.
fn _safe(name: &str) -> String {
    name.chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '_' { c } else { '_' })
        .collect()
}

/// Designator for pin - the SPICE source designator the netlister assigns to an MCU pin.
fn designator_for_pin(model: &SchematicNetlistEngine, pin: &str) -> String {
    for comp in model.components.values() {
        if !is_mcu(comp.comp_type.as_str()) {
            continue;
        }
        if comp.pins.contains_key(pin) {
            return format!("V{}_{}", _safe(comp.comp_id.as_str()), _safe(pin));
        }
    }
    String::new()
}

/// Build a map from SPICE source designator to MCU pin name.
/// Owned so it can be captured by the callback closure.
fn build_source_to_pin(model: &SchematicNetlistEngine) -> HashMap<String, String> {
    let mut map = HashMap::new();
    for comp in model.components.values() {
        if !is_mcu(comp.comp_type.as_str()) {
            continue;
        }
        let safe_cid = _safe(comp.comp_id.as_str());
        for pin in comp.pins.keys() {
            let designator = format!("V{}_{}", safe_cid, _safe(pin));
            map.insert(designator, pin.clone());
        }
    }
    map
}

/// Warn when a declared law has no matching `external` source card.
fn _check_laws_against_netlist(
    model: &SchematicNetlistEngine,
    laws: &HashMap<String, ControlLaw>,
    run: &mut CosimRun,
) {
    let mut external_cards: HashSet<String> = HashSet::new();
    for line in &run.netlist {
        let stripped = line.trim();
        if stripped.is_empty() || stripped.starts_with("*") {
            continue;
        }
        if stripped.to_lowercase().contains("external") {
            if let Some(first) = stripped.split_whitespace().next() {
                external_cards.insert(first.to_uppercase());
            }
        }
    }
    if external_cards.is_empty() {
        run.warnings.push(
            "netlist has no `external` source, so no law can be driven; "
                .to_string()
                + "attach a control law to a wired MCU pin",
        );
        return;
    }
    for pin in laws.keys() {
        let designator = designator_for_pin(model, pin);
        if designator.is_empty() {
            continue;
        }
        let matched = external_cards.iter().any(|card| {
            designator.to_uppercase() == *card
                || card.starts_with(&format!("{}_", designator.to_uppercase()))
        });
        if !matched {
            run.warnings.push(format!(
                "{}: netlist has no `external` source for {}; the pin is probably unwired",
                pin, designator
            ));
        }
    }
}

/// Compile `model`, execute the netlist, and drive each entry of `laws`.
///
/// `laws` maps an MCU pin name to a control-law spec. Every pin in it must be
/// a wired MCU output pin that the netlist emitted as an `external` source;
/// anything else is reported in `run.warnings`.
pub fn run_cosim(
    model: &SchematicNetlistEngine,
    laws: &HashMap<String, wowkispice_core::control_law::LawSpec>,
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
    let (netlist_lines, nets, netlist_warnings) = model.compile_netlist(opts);
    run.netlist = netlist_lines.iter().map(|s| s.clone()).collect();
    let probe_refs: Vec<&str> = match probe_nets {
        Some(p) => p.iter().map(|s| *s).collect(),
        None => nets.iter().map(|s| s.as_str()).collect(),
    };
    run.nets = probe_refs.iter().map(|s| s.to_string()).collect();
    run.warnings = netlist_warnings;

    // Build the laws first: a bad spec must fail before we spend time solving.
    let mut executables: HashMap<String, ControlLaw> = HashMap::new();
    for (pin, spec) in laws {
        let input = LawInput {
            kind: Some(spec.kind.as_str().to_string()),
            pin: Some(spec.pin.clone()),
            sense_net: Some(spec.sense_net.clone()),
            target_v: Some(spec.target_v),
            hysteresis_v: spec.hysteresis_v,
            vhigh: Some(spec.vhigh),
            vref: Some(spec.vref),
            adc_bits: Some(spec.adc_bits),
            divider: Some(spec.divider),
            low_counts: spec.low_counts,
            high_counts: spec.high_counts,
            carrier_hz: spec.carrier_hz,
            duty_gain: spec.duty_gain,
            source: spec.source.clone(),
            source_counts: None,
        };
        match make_law(&input) {
            Ok(law) => {
                executables.insert(pin.clone(), law);
            }
            Err(exc) => {
                run.warnings.push(format!(
                    "control law for {} rejected: {}",
                    pin, exc.message()
                ));
            }
        }
    }
    run.laws = executables.clone();

    if executables.is_empty() {
        run.warnings
            .push("no executable control law; nothing was closed-loop".to_string());
        return run;
    }

    _check_laws_against_netlist(model, &executables, &mut run);

    let mut engine = match NgSpiceFfi::new() {
        Ok(e) => e,
        Err(exc) => {
            run.warnings.push(format!("cannot start ngspice: {}", exc));
            return run;
        }
    };

    // ngSpice_Init requires callbacks; pass no-op closures for stat/control
    // since we only need GetVSRCData for co-simulation.
    engine.init(None, None, None, None).expect("ngSpice_Init should succeed");

    // Extract the ngGet_Vec_Info function pointer BEFORE calling cmd(),
    // because callbacks fire during cmd("run") when &self is mutably borrowed.
    // The callback closure captures the function pointer (Copy), not &self.
    let get_vec_info_fn = engine.get_vec_info_fn();

    // Box the callback state (laws map + get_vec_info function pointer).
    // All data is owned so the closure is 'static and can be passed to
    // ngSpice_Init_Sync.
    let laws_box = Box::new(executables.clone());
    let _source_to_pin = build_source_to_pin(model);

    // Call ngSpice_Init_Sync directly via the function pointer.
    // The callback trampoline (getvsrcdata_trampoline) is defined in lib.rs
    // and accessible from this module since they're in the same crate.
    let _hits = 0i32;
    let ud = Box::new((laws_box, get_vec_info_fn));
    let userdata = Box::into_raw(ud) as *mut c_void;

    let rc = unsafe {
        engine.ngspice_init_sync_fn().expect("ngSpice_Init_Sync should be resolved")(
            getvsrcdata_trampoline,
            getisrcdata_trampoline,
            getsyncdata_trampoline,
            ptr::null_mut(),
            userdata,
        )
    };
    if rc != 0 {
        unsafe {
            drop(Box::from_raw(userdata));
        }
        run.warnings.push(format!(
            "ngSpice_Init_Sync returned {rc}"
        ));
        return run;
    }

    let netlist_refs: Vec<&str> = run.netlist.iter().map(|s| s.as_str()).collect();
    if let Err(e) = engine.load_circuit(&netlist_refs) {
        run.warnings.push(format!("load_circuit failed: {}", e));
        return run;
    }
    if let Err(e) = engine.cmd("run") {
        run.warnings.push(format!("run failed: {}", e));
        return run;
    }

    run.callback_hits = _hits;
    run.aborted = false;

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

    for (pin, law) in &executables {
        if law.history_counts.is_empty() {
            run.warnings.push(format!(
                "{}: control law never ran (no `external` source matched); \
                 check the pin is wired and the MCU emits it",
                pin
            ));
        }
    }
    if run.time.is_empty() {
        run.warnings.push("ngspice produced no time vector".to_string());
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
