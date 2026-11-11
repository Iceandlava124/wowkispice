/*
 * julia_bridge.rs - Rust ⇄ Julia JSON communication bridge.
 *
 * Provides functionality to invoke the Julia circuit solver
 * and exchange data via JSON protocol.
 *
 * FEATURE FLAG: This module is only compiled when the `julia` feature
 * is enabled (cargo test --features julia).  The baseline build
 * remains zero-dependency.
 *
 * JSON protocol:
 *   Input  (command line arg):  julia solve_julia.jl '{"circuit": {...}, "simulation": {...}}'
 *   Output (stdout):            {"status": "success"|"error", "times": [...], "vout": [...], ...}
 *
 * Rust-side JSON handling is minimal: we construct JSON strings manually
 * and parse the output using simple string operations.  This avoids
 * external crate dependencies while leveraging Julia's JSON.jl for
 * robust parsing on the Julia side.
 */

use std::process::Command;

use crate::standalone_sim::{Circuit, CoSimResult, CircuitState, VsSourceType, ComponentType};

/** Input parameters for a Julia circuit solve */
#[derive(Debug, Clone)]
pub struct JuliaInput {
    /** Circuit description */
    pub circuit: CircuitData,
    /** Simulation parameters */
    pub simulation: JuliaSimulation,
}

/** Circuit data for Julia input */
#[derive(Debug, Clone)]
pub struct CircuitData {
    pub name: String,
    pub resistors: Vec<ResistorData>,
    pub capacitors: Vec<CapacitorData>,
    pub inductors: Vec<InductorData>,
    pub diodes: Vec<DiodeData>,
    pub mosfets_n: Vec<MosfetData>,
    pub mosfets_p: Vec<MosfetData>,
    pub switches: Vec<SwitchData>,
    pub voltage_sources: Vec<VoltageSourceData>,
    pub current_sources: Vec<CurrentSourceData>,
    pub ground_node: String,
}

/** Resistor data */
#[derive(Debug, Clone)]
pub struct ResistorData {
    pub name: String,
    pub node1: String,
    pub node2: String,
    pub value: f64,
}

/** Capacitor data */
#[derive(Debug, Clone)]
pub struct CapacitorData {
    pub name: String,
    pub node1: String,
    pub node2: String,
    pub value: f64,
}

/** Inductor data */
#[derive(Debug, Clone)]
pub struct InductorData {
    pub name: String,
    pub node1: String,
    pub node2: String,
    pub value: f64,
}

/** Diode data */
#[derive(Debug, Clone)]
pub struct DiodeData {
    pub name: String,
    pub node_p: String,
    pub node_n: String,
    pub value: f64,
}

/** MOSFET data */
#[derive(Debug, Clone)]
pub struct MosfetData {
    pub name: String,
    pub node_d: String,  // drain
    pub node_s: String,  // source
    pub node_g: String,  // gate
    pub value: f64,
}

/** Switch data */
#[derive(Debug, Clone)]
pub struct SwitchData {
    pub name: String,
    pub node1: String,
    pub node2: String,
    pub value: f64,
}

/** Voltage source data */
#[derive(Debug, Clone)]
pub struct VoltageSourceData {
    pub name: String,
    pub node_p: String,
    pub node_n: String,
    pub kind: String,  // "Dc", "Pulse", "Sin", "PWL"
    pub dc_value: f64,
}

/** Current source data */
#[derive(Debug, Clone)]
pub struct CurrentSourceData {
    pub name: String,
    pub node1: String,
    pub node2: String,
    pub value: f64,
}

/** Simulation parameters for Julia */
#[derive(Debug, Clone)]
pub struct JuliaSimulation {
    pub dt: f64,
    pub tstop: f64,
    pub method: String,
    pub tolerance: f64,
}

/** Output result from Julia solver */
#[derive(Debug, Clone, PartialEq)]
pub struct JuliaOutput {
    /// Operation status
    pub status: String,
    /// Time points
    pub times: Vec<f64>,
    /// Output voltages at each time point
    pub vout: Vec<f64>,
    /// Final voltage value
    pub final_vout: f64,
    /// Average voltage
    pub avg_vout: f64,
    /// Voltage ripple
    pub vout_ripple: f64,
    /// Number of solver steps taken
    pub steps_taken: usize,
}

/** Error information from Julia */
#[derive(Debug, Clone)]
pub struct JuliaError {
    /// Error status
    pub status: String,
    /// Error message
    pub message: String,
}

/// Convert a Rust Circuit to JuliaInput structure
fn circuit_to_julia_input(
    circuit: &Circuit,
    dt: f64,
    tstop: f64,
    method: &str,
    tolerance: f64,
) -> JuliaInput {
    // Map voltage source types
    let kind_map = |vs: &VsSourceType| -> String {
        match vs.kind {
            VsSourceType::Dc => "Dc".to_string(),
            VsSourceType::Pulse => "Pulse".to_string(),
            VsSourceType::Sin => "Sin".to_string(),
            VsSourceType::Pwl => "PWL".to_string(),
        }
    };

    let res_data: Vec<ResistorData> = circuit.resistors.iter().map(|r| ResistorData {
        name: r.name.clone(),
        node1: r.node1.clone(),
        node2: r.node2.clone(),
        value: r.value,
    }).collect();

    let cap_data: Vec<CapacitorData> = circuit.capacitors.iter().map(|c| CapacitorData {
        name: c.name.clone(),
        node1: c.node1.clone(),
        node2: c.node2.clone(),
        value: c.value,
    }).collect();

    let ind_data: Vec<InductorData> = circuit.inductors.iter().map(|l| InductorData {
        name: l.name.clone(),
        node1: l.node1.clone(),
        node2: l.node2.clone(),
        value: l.value,
    }).collect();

    let mosf_n_data: Vec<MosfetData> = circuit.mosfets_n.iter().map(|m| MosfetData {
        name: m.name.clone(),
        node_d: m.node_p.clone(),
        node_s: m.node_n.clone(),
        node_g: "G".to_string(),
        value: m.value,
    }).collect();

    let mosf_p_data: Vec<MosfetData> = circuit.mosfets_p.iter().map(|m| MosfetData {
        name: m.name.clone(),
        node_d: m.node_p.clone(),
        node_s: m.node_n.clone(),
        node_g: "G".to_string(),
        value: m.value,
    }).collect();

    let sw_data: Vec<SwitchData> = circuit.switches.iter().map(|s| SwitchData {
        name: s.name.clone(),
        node1: s.node1.clone(),
        node2: s.node2.clone(),
        value: s.value,
    }).collect();

    let vsrc_data: Vec<VoltageSourceData> = circuit.voltage_sources.iter().map(|v| VoltageSourceData {
        name: v.name.clone(),
        node_p: v.node_p.clone(),
        node_n: v.node_n.clone(),
        kind: kind_map(&v.kind),
        dc_value: v.dc_value,
    }).collect();

    let isrc_data: Vec<CurrentSourceData> = circuit.current_sources.iter().map(|i| CurrentSourceData {
        name: i.name.clone(),
        node1: i.node1.clone(),
        node2: i.node2.clone(),
        value: i.value,
    }).collect();

    JuliaInput {
        circuit: CircuitData {
            name: circuit.name.clone(),
            resistors: res_data,
            capacitors: cap_data,
            inductors: ind_data,
            diodes: circuit.diodes.iter().map(|d| DiodeData {
                name: d.name.clone(),
                node_p: d.node_p.clone(),
                node_n: d.node_n.clone(),
                value: d.value,
            }).collect(),
            mosfets_n: mosf_n_data,
            mosfets_p: mosf_p_data,
            switches: sw_data,
            voltage_sources: vsrc_data,
            current_sources: isrc_data,
            ground_node: circuit.ground_node.clone(),
        },
        simulation: JuliaSimulation {
            dt,
            tstop,
            method: method.to_string(),
            tolerance,
        },
    }
}

/// Serialize JuliaInput to a JSON string manually (no external crates)
fn to_json_string(input: &JuliaInput) -> String {
    let circuit = &input.circuit;
    let sim = &input.simulation;

    format!(
        r#"{{"circuit":{{"name":"{}","resistors":[{}],"capacitors":[{}],"inductors":[{}],"diodes":[{}],"mosfets_n":[{}],"mosfets_p":[{}],"switches":[{}],"voltage_sources":[{}],"current_sources":[{}],"ground_node":"{}"}},"simulation":{{"dt":{},"tstop":{},"method":"{}","tolerance":{}}}}}"#,
        circuit.name,
        resistors_to_json(&circuit.resistors),
        capacitors_to_json(&circuit.capacitors),
        inductors_to_json(&circuit.inductors),
        diodes_to_json(&circuit.diodes),
        mosfets_n_to_json(&circuit.mosfets_n),
        mosfets_p_to_json(&circuit.mosfets_p),
        switches_to_json(&circuit.switches),
        voltage_sources_to_json(&circuit.voltage_sources),
        current_sources_to_json(&circuit.current_sources),
        circuit.ground_node,
        sim.dt,
        sim.tstop,
        sim.method,
        sim.tolerance,
    )
}

/// Helper: serialize resistors to JSON array
fn resistors_to_json(resistors: &[ResistorData]) -> String {
    if resistors.is_empty() {
        return "[]".to_string();
    }
    let items: Vec<String> = resistors.iter().map(|r| {
        format!(
            r#"{{"name":"{}","node1":"{}","node2":"{}","value":{}}}"#,
            r.name, r.node1, r.node2, r.value
        )
    }).collect();
    format!("[{}]", items.join(","))
}

/// Helper: serialize capacitors to JSON array
fn capacitors_to_json(caps: &[CapacitorData]) -> String {
    if caps.is_empty() {
        return "[]".to_string();
    }
    let items: Vec<String> = caps.iter().map(|c| {
        format!(
            r#"{{"name":"{}","node1":"{}","node2":"{}","value":{}}}"#,
            c.name, c.node1, c.node2, c.value
        )
    }).collect();
    format!("[{}]", items.join(","))
}

/// Helper: serialize inductors to JSON array
fn inductors_to_json(inds: &[InductorData]) -> String {
    if inds.is_empty() {
        return "[]".to_string();
    }
    let items: Vec<String> = inds.iter().map(|i| {
        format!(
            r#"{{"name":"{}","node1":"{}","node2":"{}","value":{}}}"#,
            i.name, i.node1, i.node2, i.value
        )
    }).collect();
    format!("[{}]", items.join(","))
}

/// Helper: serialize diodes to JSON array
fn diodes_to_json(diodes: &[DiodeData]) -> String {
    if diodes.is_empty() {
        return "[]".to_string();
    }
    let items: Vec<String> = diodes.iter().map(|d| {
        format!(
            r#"{{"name":"{}","node_p":"{}","node_n":"{}","value":{}}}"#,
            d.name, d.node_p, d.node_n, d.value
        )
    }).collect();
    format!("[{}]", items.join(","))
}

/// Helper: serialize mosfets_n to JSON array
fn mosfets_n_to_json(mosfets: &[MosfetData]) -> String {
    if mosfets.is_empty() {
        return "[]".to_string();
    }
    let items: Vec<String> = mosfets.iter().map(|m| {
        format!(
            r#"{{"name":"{}","node_d":"{}","node_s":"{}","value":{}}}"#,
            m.name, m.node_d, m.node_s, m.value
        )
    }).collect();
    format!("[{}]", items.join(","))
}

/// Helper: serialize mosfets_p to JSON array
fn mosfets_p_to_json(mosfets: &[MosfetData]) -> String {
    if mosfets.is_empty() {
        return "[]".to_string();
    }
    let items: Vec<String> = mosfets.iter().map(|m| {
        format!(
            r#"{{"name":"{}","node_d":"{}","node_s":"{}","value":{}}}"#,
            m.name, m.node_d, m.node_s, m.value
        )
    }).collect();
    format!("[{}]", items.join(","))
}

/// Helper: serialize switches to JSON array
fn switches_to_json(switches: &[SwitchData]) -> String {
    if switches.is_empty() {
        return "[]".to_string();
    }
    let items: Vec<String> = switches.iter().map(|s| {
        format!(
            r#"{{"name":"{}","node1":"{}","node2":"{}","value":{}}}"#,
            s.name, s.node1, s.node2, s.value
        )
    }).collect();
    format!("[{}]", items.join(","))
}

/// Helper: serialize voltage_sources to JSON array
fn voltage_sources_to_json(vsrcs: &[VoltageSourceData]) -> String {
    if vsrcs.is_empty() {
        return "[]".to_string();
    }
    let items: Vec<String> = vsrcs.iter().map(|v| {
        format!(
            r#"{{"name":"{}","node_p":"{}","node_n":"{}","kind":"{}","dc_value":{}}}"#,
            v.name, v.node_p, v.node_n, v.kind, v.dc_value
        )
    }).collect();
    format!("[{}]", items.join(","))
}

/// Helper: serialize current_sources to JSON array
fn current_sources_to_json(isrcs: &[CurrentSourceData]) -> String {
    if isrcs.is_empty() {
        return "[]".to_string();
    }
    let items: Vec<String> = isrcs.iter().map(|i| {
        format!(
            r#"{{"name":"{}","node1":"{}","node2":"{}","value":{}}}"#,
            i.name, i.node1, i.node2, i.value
        )
    }).collect();
    format!("[{}]", items.join(","))
}

/// Parse Julia output JSON string into JuliaOutput structure.
/// Uses minimal string parsing (no external JSON crates).
fn parse_julia_output(json: &str) -> Result<JuliaOutput, String> {
    let mut status = String::new();
    let mut times = Vec::new();
    let mut vout = Vec::new();
    let mut final_vout = 0.0f64;
    let mut avg_vout = 0.0f64;
    let mut vout_ripple = 0.0f64;
    let mut steps_taken = 0usize;

    // Simple JSON parsing: extract key-value pairs
    // We look for patterns like "status":"value" or "status": value
    let mut in_string = false;
    let mut current_key = String::new();
    let mut current_value = String::new();
    let mut keys_collected = 0usize;
    let mut values_collected = Vec::new();

    for ch in json.chars() {
        if ch == '"' && (keys_collected == 0 || json.as_bytes()[json.as_bytes().len() - 1] != 92) {
            // Toggle in_string state, but handle escaped quotes
            // Actually let's use a simpler approach: just find key-value pairs
        }
    }

    // Even simpler: use line-by-line parsing for the specific format we expect
    // The Julia output format is: {"status":"success","times":[...],"vout":[...],...}
    // We'll find each field by searching for the key pattern

    // Extract status
    if let Some(pos) = json.find("\"status\"") {
        let after = &json[pos + 10..];
        if let Some(end) = after.find('"') {
            status = after[1..end].to_string();
            keys_collected += 1;
        }
    }

    // Extract times
    if let Some(pos) = json.find("\"times\"") {
        let after = &json[pos + 9..];
        if let Some(start_bracket) = after.find('[') {
            if let Some(end_bracket) = after[start_bracket..].find(']') {
                let bracket_content = &after[start_bracket + 1..start_bracket + end_bracket];
                // Split by comma to get individual time values
                for part in bracket_content.split(',') {
                    if let Ok(t) = part.trim().parse::<f64>() {
                        times.push(t);
                    }
                }
                keys_collected += 1;
            }
        }
    }

    // Extract vout
    if let Some(pos) = json.find("\"vout\"") {
        let after = &json[pos + 8..];
        if let Some(start_bracket) = after.find('[') {
            if let Some(end_bracket) = after[start_bracket..].find(']') {
                let bracket_content = &after[start_bracket + 1..start_bracket + end_bracket];
                for part in bracket_content.split(',') {
                    if let Ok(v) = part.trim().parse::<f64>() {
                        vout.push(v);
                    }
                }
                keys_collected += 1;
            }
        }
    }

    // Extract final_vout
    if let Some(pos) = json.find("\"final_vout\"") {
        let after = &json[pos + 13..];
        if let Some(end) = after.find(',') || after.find('}') {
            let num_str = if after.find('}').is_some() {
                &after[..after.find('}').unwrap()]
            } else {
                &after[..after.find(',').unwrap()]
            };
            if let Ok(v) = num_str.trim().parse::<f64>() {
                final_vout = v;
            }
            keys_collected += 1;
        }
    }

    // Extract avg_vout
    if let Some(pos) = json.find("\"avg_vout\"") {
        let after = &json[pos + 11..];
        if let Some(end) = after.find(',') {
            if let Ok(v) = after[..end].trim().parse::<f64>() {
                avg_vout = v;
            }
        } else if let Some(end) = after.find('}') {
            if let Ok(v) = after[..end].trim().parse::<f64>() {
                avg_vout = v;
            }
        }
        keys_collected += 1;
    }

    // Extract vout_ripple
    if let Some(pos) = json.find("\"vout_ripple\"") {
        let after = &json[pos + 14..];
        if let Some(end) = after.find(',') || after.find('}') {
            let num_str = if after.find('}').is_some() {
                &after[..after.find('}').unwrap()]
            } else {
                &after[..after.find(',').unwrap()]
            };
            if let Ok(v) = num_str.trim().parse::<f64>() {
                vout_ripple = v;
            }
        }
        keys_collected += 1;
    }

    // Extract steps_taken
    if let Some(pos) = json.find("\"steps_taken\"") {
        let after = &json[pos + 14..];
        if let Some(end) = after.find(',') || after.find('}') {
            if let Ok(v) = after[..end].trim().parse::<usize>() {
                steps_taken = v;
            }
        }
        keys_collected += 1;
    }

    Ok(JuliaOutput {
        status,
        times,
        vout,
        final_vout,
        avg_vout,
        vout_ripple,
        steps_taken,
    })
}

/// Invoke the Julia circuit solver with the given circuit and simulation parameters
///
/// # Arguments
/// * `circuit` - The circuit to solve
/// * `dt` - Time step
/// * `tstop` - Simulation stop time
/// * `method` - ODE solver method (e.g., "Tsit5", "Rodas5")
/// * `tolerance` - Solver tolerance
///
/// # Returns
/// * `Ok(JuliaOutput)` if the solve succeeded
/// * `Err(String)` if the invocation or solve failed
pub fn solve_circuit_julia(
    circuit: &Circuit,
    dt: f64,
    tstop: f64,
    method: &str,
    tolerance: f64,
) -> Result<JuliaOutput, String> {
    // Convert circuit to Julia input
    let input = circuit_to_julia_input(circuit, dt, tstop, method, tolerance);

    // Serialize to JSON string
    let json_input = to_json_string(&input);

    // Invoke Julia solver
    let output = Command::new("julia")
        .arg("bridge/julia/solve_julia.jl")
        .arg(&json_input)
        .output();

    match output {
        Ok(child_output) => {
            if child_output.status.success() {
                let stdout = String::from_utf8(child_output.stdout.clone())
                    .map_err(|e| format!("Failed to parse Julia stdout: {}", e))?;

                // Parse JSON output using minimal string parsing
                parse_julia_output(&stdout)
            } else {
                let stderr = String::from_utf8(child_output.stderr.clone())
                    .map_err(|e| format!("Julia error: {}", e))?;
                Err(format!("Julia solver failed with exit code {:?}\nstderr: {}", child_output.status, stderr))
            }
        }
        Err(e) => Err(format!("Failed to invoke Julia solver: {}", e)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_circuit_to_json_serialization() {
        let circuit = Circuit::default();
        let input = circuit_to_julia_input(&circuit, 1e-6, 0.01, "Tsit5", 1e-6);
        let json = to_json_string(&input);
        // Just verify it serializes without error and contains expected fields
        assert!(json.contains("\"name\""));
        assert!(json.contains("\"resistors\""));
        assert!(json.contains("\"simulation\""));
    }

    #[test]
    fn test_julia_input_has_required_fields() {
        let circuit = Circuit::default();
        let input = circuit_to_julia_input(&circuit, 1e-6, 0.01, "Tsit5", 1e-6);
        assert!(!input.simulation.method.is_empty());
        assert!(input.simulation.dt > 0.0);
        assert!(input.simulation.tstop > 0.0);
    }

    #[test]
    fn test_julia_output_parsing() {
        // Simulate a Julia output JSON string
        let json = r#"{"status":"success","times":[0.0,9.999999999999999e-5,0.01],"vout":[0.0,0.4758129095056101,4.995005e9],"final_vout":4.995005e9,"avg_vout":3.8105525440788703,"vout_ripple":4.999772950111696,"steps_taken":3}"#;

        let result = parse_julia_output(json);
        assert!(result.is_ok());
        let output = result.unwrap();
        assert_eq!(output.status, "success");
        assert_eq!(output.times.len(), 3);
        assert_eq!(output.vout.len(), 3);
        assert!(output.final_vout > 0.0);
        assert!(output.avg_vout > 0.0);
        assert!(output.vout_ripple > 0.0);
        assert_eq!(output.steps_taken, 3);
    }

    #[test]
    fn test_julia_output_error_parsing() {
        // Simulate an error Julia output
        let json = r#"{"status":"error","message":"Solver failed to converge"}"#;

        // This should still return a JuliaOutput, just with status "error"
        // The parse function handles whatever keys are present
        let result = parse_julia_output(json);
        assert!(result.is_ok());
        let output = result.unwrap();
        assert_eq!(output.status, "error");
    }
}