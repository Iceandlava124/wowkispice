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

use crate::standalone_sim::{Circuit, VsSourceType};

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
    // Map voltage source types (vs is a &VsSourceType, an enum with variants Dc/Pulse/Sin/Pwl)
    let kind_map = |vs: &VsSourceType| -> String {
        match vs {
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
        node_d: m.node1.clone(),
        node_s: m.node2.clone(),
        node_g: "G".to_string(),
        value: m.value,
    }).collect();

    let mosf_p_data: Vec<MosfetData> = circuit.mosfets_p.iter().map(|m| MosfetData {
        name: m.name.clone(),
        node_d: m.node1.clone(),
        node_s: m.node2.clone(),
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
                node_p: d.node1.clone(),
                node_n: d.node2.clone(),
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

/// Escape a string for embedding inside a JSON string literal.
/// Escapes `\"` and `\\`, plus control characters. Required because
/// `to_json_string` builds JSON manually — an unescaped `"` would corrupt the document.
fn escape_json_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 8);
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            _ => out.push(ch),
        }
    }
    out
}

/// Serialize JuliaInput to a JSON string manually (no external crates)
fn to_json_string(input: &JuliaInput) -> String {
    let circuit = &input.circuit;
    let sim = &input.simulation;

    format!(
        r#"{{"circuit":{{"name":"{}","resistors":[{}],"capacitors":[{}],"inductors":[{}],"diodes":[{}],"mosfets_n":[{}],"mosfets_p":[{}],"switches":[{}],"voltage_sources":[{}],"current_sources":[{}],"ground_node":"{}"}},"simulation":{{"dt":{},"tstop":{},"method":"{}","tolerance":{}}}}}"#,
        escape_json_string(&circuit.name),
        resistors_to_json(&circuit.resistors),
        capacitors_to_json(&circuit.capacitors),
        inductors_to_json(&circuit.inductors),
        diodes_to_json(&circuit.diodes),
        mosfets_n_to_json(&circuit.mosfets_n),
        mosfets_p_to_json(&circuit.mosfets_p),
        switches_to_json(&circuit.switches),
        voltage_sources_to_json(&circuit.voltage_sources),
        current_sources_to_json(&circuit.current_sources),
        escape_json_string(&circuit.ground_node),
        sim.dt,
        sim.tstop,
        escape_json_string(&sim.method),
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
            escape_json_string(&r.name), escape_json_string(&r.node1), escape_json_string(&r.node2), r.value
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
            escape_json_string(&c.name), escape_json_string(&c.node1), escape_json_string(&c.node2), c.value
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
            escape_json_string(&i.name), escape_json_string(&i.node1), escape_json_string(&i.node2), i.value
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
            escape_json_string(&d.name), escape_json_string(&d.node_p), escape_json_string(&d.node_n), d.value
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
            escape_json_string(&m.name), escape_json_string(&m.node_d), escape_json_string(&m.node_s), m.value
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
            escape_json_string(&m.name), escape_json_string(&m.node_d), escape_json_string(&m.node_s), m.value
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
            escape_json_string(&s.name), escape_json_string(&s.node1), escape_json_string(&s.node2), s.value
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
            escape_json_string(&v.name), escape_json_string(&v.node_p), escape_json_string(&v.node_n), escape_json_string(&v.kind), v.dc_value
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
            escape_json_string(&i.name), escape_json_string(&i.node1), escape_json_string(&i.node2), i.value
        )
    }).collect();
    format!("[{}]", items.join(","))
}

/// Maximum number of bytes of Julia stdout/stderr to include in error messages.
/// Longer output is truncated to keep error messages usable.
const MAX_ERROR_OUTPUT: usize = 4096;

/// Truncate a string to MAX_ERROR_OUTPUT bytes, appending a note about truncation.
fn truncate_output(s: &str) -> String {
    if s.len() <= MAX_ERROR_OUTPUT {
        s.to_string()
    } else {
        format!("{}...(truncated, {} bytes total)", &s[..MAX_ERROR_OUTPUT], s.len())
    }
}

/// Parse Julia output JSON string into JuliaOutput structure.
/// Uses minimal string parsing (no external JSON crates).
/// Robust: handles whitespace, key order variation, and edge cases.
fn parse_julia_output(json: &str) -> Result<JuliaOutput, String> {
    let mut status = String::new();
    let mut times = Vec::new();
    let mut vout = Vec::new();
    let mut final_vout = 0.0f64;
    let mut avg_vout = 0.0f64;
    let mut vout_ripple = 0.0f64;
    let mut steps_taken = 0usize;

    // Robust JSON field extraction: find each field by key name,
    // then extract its value handling commas and closing braces correctly.
    fn extract_number_after_key<'a>(json: &'a str, key: &str) -> Option<&'a str> {
        // Find the key: "key" pattern
        let key_pattern = format!("\"{}\"", key);
        if let Some(key_pos) = json.find(&key_pattern) {
            let after_key = &json[key_pos + key_pattern.len()..];
            // Skip any whitespace before the colon
            let after_space = after_key.trim_start();
            // Skip the colon after the key
            let after_colon = after_space.strip_prefix(':')?;
            // Trim whitespace
            let trimmed = after_colon.trim();
            // If the value is an array, find the matching ']' and return the whole array
            if trimmed.starts_with('[') {
                if let Some(end) = trimmed.find(']') {
                    return Some(&trimmed[..end + 1]);
                }
                return None;
            }
            // Extract the number: find comma or closing brace, whichever comes first
            let mut end_pos: Option<usize> = None;
            // Search for comma or } in the remaining text
            if let Some(cpos) = trimmed.find(',') {
                end_pos = Some(cpos);
            }
            if let Some(bpos) = trimmed.find('}') {
                // Take the earlier of the two positions
                end_pos = match end_pos {
                    Some(ep) if bpos < ep => Some(bpos),
                    None => Some(bpos),
                    Some(_) => end_pos,
                };
            }
            // Extract substring up to the delimiter
            let num_str = if let Some(ep) = end_pos {
                &trimmed[..ep]
            } else {
                trimmed
            };
            // Return the number string (trimmed of whitespace)
            Some(num_str.trim())
        } else {
            None
        }
    }

    // Extract string field after key (value between quotes)
    fn extract_string_after_key<'a>(json: &'a str, key: &str) -> Option<String> {
        let key_pattern = format!("\"{}\"", key);
        if let Some(key_pos) = json.find(&key_pattern) {
            let after_key = &json[key_pos + key_pattern.len()..];
            // Skip any whitespace before the colon
            let after_space = after_key.trim_start();
            let after_colon = after_space.strip_prefix(':')?;
            let trimmed = after_colon.trim();
            // The value must start with a quote; find the value between the quotes
            let value = trimmed.strip_prefix('"')?;
            let end_quote = value.find('"')?;
            Some(value[..end_quote].to_string())
        } else {
            None
        }
    }

    // Extract status (string field)
    if let Some(s) = extract_string_after_key(json, "status") {
        status = s;
        // Also verify it's a valid status value
        if status != "success" && status != "error" {
            // Still accept it - could be other status values
        }
    }

    // Extract times (array of f64)
    if let Some(num_str) = extract_number_after_key(json, "times") {
        // Parse the array content: remove brackets and split by comma
        let inner = num_str.trim();
        // Remove [ and ] brackets (stable: trim_start_matches / trim_end_matches)
        let inner = inner.trim_start_matches('[').trim_end_matches(']').trim();
        for part in inner.split(',') {
            if let Ok(t) = part.trim().parse::<f64>() {
                times.push(t);
            }
        }
    }
    // Only count as collected if we found the times key; if times is empty that's OK

    // Extract vout (array of f64)
    if let Some(num_str) = extract_number_after_key(json, "vout") {
        let inner = num_str.trim();
        let inner = inner.trim_start_matches('[').trim_end_matches(']').trim();
        for part in inner.split(',') {
            if let Ok(v) = part.trim().parse::<f64>() {
                vout.push(v);
            }
        }
    }

    // Extract final_vout (single f64)
    if let Some(num_str) = extract_number_after_key(json, "final_vout") {
        if let Ok(v) = num_str.parse::<f64>() {
            final_vout = v;
        }
    }

    // Extract avg_vout (single f64)
    if let Some(num_str) = extract_number_after_key(json, "avg_vout") {
        if let Ok(v) = num_str.parse::<f64>() {
            avg_vout = v;
        }
    }

    // Extract vout_ripple (single f64)
    if let Some(num_str) = extract_number_after_key(json, "vout_ripple") {
        if let Ok(v) = num_str.parse::<f64>() {
            vout_ripple = v;
        }
    }

    // Extract steps_taken (usize)
    if let Some(num_str) = extract_number_after_key(json, "steps_taken") {
        if let Ok(v) = num_str.parse::<usize>() {
            steps_taken = v;
        }
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
            let raw_stdout = child_output.stdout.clone();
            let raw_stderr = child_output.stderr.clone();
            if child_output.status.success() {
                let stdout = String::from_utf8(raw_stdout)
                    .map_err(|e| format!("Failed to parse Julia stdout as UTF-8: {}", e))?;

                // Parse JSON output. The parser always returns Ok(...) for JSON with the
                // fields it knows (missing keys default to 0), so we check .status below.
                let output = parse_julia_output(&stdout)
                    .map_err(|e| format!("Failed to parse Julia output as JSON: {}\nstdout: {}", e, truncate_output(&stdout)))?;

                // Check if Julia reported an error inside the success exit code
                if output.status == "error" {
                    // Julia reported an error in the JSON output;
                    // the minimal parser doesn't extract a message field,
                    // so we provide a generic description plus the raw stdout
                    // to make debugging possible
                    Err(format!("Julia solver reported error (status: {}); output: times={:?}, vout={:?}, final_vout={}, avg_vout={}, vout_ripple={}, steps_taken={}\nstdout: {}",
                                output.status, output.times, output.vout, output.final_vout, output.avg_vout, output.vout_ripple, output.steps_taken, truncate_output(&stdout)))
                } else {
                    Ok(output)
                }
            } else {
                let stderr = String::from_utf8(raw_stderr)
                    .map_err(|e| format!("Julia process failed with exit code {:?} and non-UTF-8 stderr: {}", child_output.status, e))?;
                let stdout_str = String::from_utf8(raw_stdout)
                    .unwrap_or_else(|_| "<non-UTF-8 stdout>".to_string());
                Err(format!("Julia solver failed with exit code {:?}\nstderr: {}\nstdout: {}",
                            child_output.status, truncate_output(&stderr), truncate_output(&stdout_str)))
            }
        }
        Err(e) => Err(format!("Failed to invoke Julia solver (is Julia installed and on PATH?): {}", e)),
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

    // ---------- Round-trip / edge-case tests (added during code hardening) ----------

    /// Round-trip: build JuliaInput from a Circuit, serialize to JSON, then feed
    /// the serialized JSON back through the *output* parser to verify the
    /// JSON is structurally valid and all simulation parameters survive.
    #[test]
    fn test_round_trip_input_serialization() {
        let circuit = Circuit::default();
        let input = circuit_to_julia_input(&circuit, 1e-6, 0.01, "Tsit5", 1e-6);
        let json = to_json_string(&input);

        // The input JSON should be parseable as a Julia-style output object:
        // it has the same shape (object at top level) with "simulation"
        // instead of output fields — so verify our output parser at least does
        // not panic and extracts what exists (it looks for "times" / "vout",
        // both absent here).
        let result = parse_julia_output(&json);
        assert!(result.is_ok());
        let output = result.unwrap();
        // No output fields in an input document: everything defaults to 0/empty
        assert_eq!(output.times.len(), 0);
        assert_eq!(output.vout.len(), 0);

        // Verify structural shape by checking key ordering and field presence
        assert!(json.starts_with("{\"circuit\":{\"name\":"));
        assert!(json.contains("\"simulation\":{"));
        assert!(json.contains("\"method\":\"Tsit5\""));
        assert!(json.contains("\"dt\":1e-6") || json.contains("\"dt\":0.000001"));
        assert!(json.contains("\"tstop\":0.01"));
        // Balance the braces: { appears the same number of times as }
        assert_eq!(json.matches('{').count(), json.matches('}').count());
        // Balance the arrays
        assert_eq!(json.matches('[').count(), json.matches(']').count());
    }

    /// Round-trip: take a known-good Julia success response, feed it through the
    /// output parser, then re-serialize the parsed JuliaOutput structure to a
    /// canonical JSON representation and verify it contains the same values.
    #[test]
    fn test_round_trip_output_parse_values() {
        let json = r#"{"status":"success","times":[0.0,0.001,0.002],"vout":[0.0,2.5,4.99],"final_vout":4.99,"avg_vout":2.49,"vout_ripple":4.99,"steps_taken":2}"#;

        let result = parse_julia_output(json);
        assert!(result.is_ok());
        let output = result.unwrap();

        // Verify every field parses to the expected value
        assert_eq!(output.status, "success");
        assert_eq!(output.times, vec![0.0, 0.001, 0.002]);
        assert_eq!(output.vout, vec![0.0, 2.5, 4.99]);
        assert!((output.final_vout - 4.99).abs() < 1e-12);
        assert!((output.avg_vout - 2.49).abs() < 1e-12);
        assert!((output.vout_ripple - 4.99).abs() < 1e-12);
        assert_eq!(output.steps_taken, 2);

        // Re-serialize to a JSON object and verify the same field names exist
        let reserialized = format!(
            r#"{{"status":"{}","times":[{}],"vout":[{}],"final_vout":{},"avg_vout":{},"vout_ripple":{},"steps_taken":{}}}"#,
            output.status,
            output
                .times
                .iter()
                .map(|t| format!("{:e}", t))
                .collect::<Vec<_>>()
                .join(","),
            output
                .vout
                .iter()
                .map(|v| format!("{:e}", v))
                .collect::<Vec<_>>()
                .join(","),
            output.final_vout,
            output.avg_vout,
            output.vout_ripple,
            output.steps_taken
        );
        // The reserialized form must still contain the same core fields
        assert!(reserialized.contains("\"status\":\"success\""));
        assert!(reserialized.contains("\"times\":["));
        assert!(reserialized.contains("\"vout\":["));
        assert!(reserialized.contains("\"steps_taken\":2"));

        // And it must parse back correctly
        let reparsed = parse_julia_output(&reserialized);
        assert!(reparsed.is_ok());
        let reparsed = reparsed.unwrap();
        assert_eq!(reparsed.status, "success");
        assert_eq!(reparsed.steps_taken, 2);
    }

    /// Edge case: Julia output with extra whitespace — must still parse.
    #[test]
    fn test_parse_julia_output_with_whitespace() {
        let json = r#"{ "status" : "success" , "times" : [ 0.0 , 0.01 ] , "vout" : [ 0.0 , 4.9 ] , "final_vout" : 4.9 , "avg_vout" : 2.45 , "vout_ripple" : 4.9 , "steps_taken" : 1 }"#;

        let result = parse_julia_output(json);
        assert!(result.is_ok());
        let output = result.unwrap();
        assert_eq!(output.status, "success");
        assert_eq!(output.times, vec![0.0, 0.01]);
        assert_eq!(output.vout, vec![0.0, 4.9]);
        assert_eq!(output.steps_taken, 1);
    }

    /// Edge case: Julia output with keys in a different order.
    #[test]
    fn test_parse_julia_output_with_reordered_keys() {
        // Keys in different order than the canonical format
        let json = r#"{"steps_taken":2,"vout":[0.0,4.9],"times":[0.0,0.01],"status":"success","vout_ripple":4.9,"avg_vout":2.45,"final_vout":4.9}"#;

        let result = parse_julia_output(json);
        assert!(result.is_ok());
        let output = result.unwrap();
        assert_eq!(output.status, "success");
        assert_eq!(output.times, vec![0.0, 0.01]);
        assert_eq!(output.vout, vec![0.0, 4.9]);
        assert_eq!(output.steps_taken, 2);
        assert!((output.final_vout - 4.9).abs() < 1e-12);
        assert!((output.avg_vout - 2.45).abs() < 1e-12);
        assert!((output.vout_ripple - 4.9).abs() < 1e-12);
    }

    /// Edge case: Julia output with missing fields — must use defaults, not panic.
    #[test]
    fn test_parse_julia_output_missing_fields() {
        // Only status is present; everything else should default gracefully
        let json = r#"{"status":"success"}"#;

        let result = parse_julia_output(json);
        assert!(result.is_ok());
        let output = result.unwrap();
        assert_eq!(output.status, "success");
        assert_eq!(output.times.len(), 0);
        assert_eq!(output.vout.len(), 0);
        assert_eq!(output.final_vout, 0.0);
        assert_eq!(output.steps_taken, 0);
    }

    /// Edge case: Convergence-failure output (Julia's error shape) — missing
    /// output fields must be tolerated.
    #[test]
    fn test_parse_julia_output_convergence_failure() {
        // Julia failure output only has status + error_type + error_message + solve_time_ms
        let json = r#"{"status":"error","error_type":"convergence_failure","error_message":"Solver failed to converge","solve_time_ms":12.5}"#;

        let result = parse_julia_output(json);
        assert!(result.is_ok());
        let output = result.unwrap();
        assert_eq!(output.status, "error");
        assert_eq!(output.times.len(), 0);
        assert_eq!(output.vout.len(), 0);
        // No steps/output fields means 0 — caller must treat this as an error,
        // which is now enforced in solve_circuit_julia via the status=="error" check
        assert_eq!(output.steps_taken, 0);
    }
}