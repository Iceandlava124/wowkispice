/*
 * analysis_runner.rs - Post-simulation analysis: FFT, Bode, noise, Monte Carlo.
 *
 * Port of bridge/analysis_runner.py to Rust.
 *
 * The transient path lives in cosim_runner. This module covers the analyses
 * that need their own run:
 *
 *     run_fft()         replays the solved transient through a windowed FFT
 *     run_bode()        compiles the schematic with analysis="ac", solves the
 *                       sweep, and returns gain/phase plus margins
 *     run_noise()       compiles with analysis="noise" and returns the output
 *                       noise spectral density plus the integrated total
 *     run_monte_carlo() perturbs every R/C/L by +/-tol, recompiles and re-solves
 *                       the USER's schematic per sample, and returns yield stats
 *
 * All public functions return Result<BTreeMap<String, CadValue>, AnalysisError>,
 * mirroring Python's Dict[str, object] returns.
 *
 * The engine parameter is &NgSpiceEngine where the function only reads plots
 * (run_fft), and &mut NgSpiceEngine where it solves (load_circuit / cmd).
 *
 * Note: ngspice is a process-wide singleton. These functions deliberately do
 * NOT call engine.quit() - quitting would break every later engine in this
 * process (observed as a hang). Process exit tears it down.
 */

use std::collections::BTreeMap;

use crate::cad_engine::{CadValue, CompileOptions, SchematicNetlistEngine};
use crate::measurements::{bode_from_ac, fft_spectrum, phase_margin, thd};
use crate::ngspice_wrapper::{NgSpiceEngine, NgSpiceError};

pub type AnalysisResult<T> = Result<T, AnalysisError>;

/// Error raised when an analysis cannot produce the data it was asked for.
#[derive(Debug, Clone)]
pub struct AnalysisError {
    message: String,
}

impl AnalysisError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl std::fmt::Display for AnalysisError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for AnalysisError {}

impl From<NgSpiceError> for AnalysisError {
    fn from(e: NgSpiceError) -> Self {
        AnalysisError::new(e.to_string())
    }
}

// ---------------------------------------------------------------------------
// spice_value - SPICE component value parser
// ---------------------------------------------------------------------------

/// Parse a SPICE component value ('1k', '4.7u', '0.1meg', '10') into a plain
/// number.  Returns Err for strings that are not numbers (PULSE(...),
/// empty, mixed units) - callers skip those rather than guess.
pub fn spice_value(text: &str) -> AnalysisResult<f64> {
    let s = text.trim().to_lowercase();
    if s.is_empty() {
        return Err(AnalysisError::new("empty value".to_string()));
    }
    for (suffix, mult) in [
        ("meg", 1e6),
        ("mil", 2.54e-5),
        ("k", 1e3),
        ("m", 1e-3),
        ("u", 1e-6),
        ("n", 1e-9),
        ("p", 1e-12),
        ("f", 1e-15),
    ] {
        if s.ends_with(suffix) && s.len() > suffix.len() {
            match s[..s.len() - suffix.len()].parse::<f64>() {
                Ok(v) => return Ok(v * mult),
                Err(_) => break,
            }
        }
    }
    s.parse::<f64>()
        .map_err(|_| AnalysisError::new(format!("cannot parse spice value '{text}'")))
}

// ---------------------------------------------------------------------------
// run_fft
// ---------------------------------------------------------------------------

/// FFT of an already-solved transient trace.
///
/// The engine must have run a transient analysis; this reads the plot it left
/// behind rather than solving anything again.
pub fn run_fft(
    engine: &NgSpiceEngine,
    net: &str,
    window: &str,
    fundamental_hz: Option<f64>,
) -> AnalysisResult<BTreeMap<String, CadValue>> {
    let times = engine.get_vector_array("time")?;
    if times.is_empty() {
        return Err(AnalysisError::new(
            "no transient data to analyse - run a transient simulation first".to_string(),
        ));
    }
    let values = engine.get_vector_array(net)?;
    if values.is_empty() {
        return Err(AnalysisError::new(format!(
            "no vector named '{net}' in the current plot"
        )));
    }

    let spectrum = fft_spectrum(&times, &values, window);
    if spectrum.freqs.is_empty() {
        return Err(AnalysisError::new(format!(
            "trace on '{net}' is too short to FFT ({} points)",
            values.len()
        )));
    }

    let mut out: BTreeMap<String, CadValue> = BTreeMap::new();
    out.insert(
        "freqs".to_string(),
        CadValue::List(spectrum.freqs.iter().map(|&f| CadValue::F64(f)).collect()),
    );
    out.insert(
        "magnitude".to_string(),
        CadValue::List(spectrum.magnitude.iter().map(|&m| CadValue::F64(m)).collect()),
    );
    out.insert(
        "dominant_hz".to_string(),
        spectrum
            .dominant_hz
            .map_or(CadValue::Null, |v| CadValue::F64(v)),
    );
    out.insert("n".to_string(), CadValue::I32(spectrum.n as i32));
    out.insert(
        "sample_rate_hz".to_string(),
        CadValue::F64(spectrum.sample_rate_hz),
    );
    out.insert(
        "noise_floor".to_string(),
        CadValue::F64(spectrum.noise_floor),
    );
    out.insert(
        "bin_width_hz".to_string(),
        CadValue::F64(spectrum.bin_width_hz),
    );
    out.insert("net".to_string(), CadValue::Str(net.to_string()));
    out.insert("window".to_string(), CadValue::Str(window.to_string()));

    let fundamental = fundamental_hz.or(spectrum.dominant_hz);
    out.insert(
        "fundamental_hz".to_string(),
        fundamental.map_or(CadValue::Null, |v| CadValue::F64(v)),
    );

    let thd_val = thd(&spectrum.freqs, &spectrum.magnitude, fundamental, 10);
    out.insert("thd".to_string(), thd_val.map_or(CadValue::Null, |v| CadValue::F64(v)));

    Ok(out)
}

// ---------------------------------------------------------------------------
// run_bode
// ---------------------------------------------------------------------------

/// AC sweep of a compiled schematic, returned as a Bode plot plus margins.
///
/// `output_net` is the node whose transfer function you want. `input_net` is
/// optional: when omitted the gain is referenced to the stamped 1 V AC source,
/// which is what ngspice's own .ac gives you.
pub fn run_bode(
    model: &SchematicNetlistEngine,
    output_net: &str,
    input_net: Option<&str>,
    start_hz: f64,
    stop_hz: f64,
    points_per_decade: i32,
    engine: &mut NgSpiceEngine,
) -> AnalysisResult<BTreeMap<String, CadValue>> {
    let opts = CompileOptions {
        analysis: "ac".to_string(),
        ac_start_hz: start_hz,
        ac_stop_hz: stop_hz,
        ac_points_per_decade: points_per_decade,
        ..Default::default()
    };
    let (lines, nets, warns) = model.compile_netlist(opts);
    if !lines.iter().any(|l| l.contains(".ac")) {
        return Err(AnalysisError::new(
            "the netlist contains no .ac card; nothing to sweep. "
                .to_string()
                + &warns.join(" "),
        ));
    }

    engine.load_circuit(&lines)?;
    engine.cmd("run")?;

    let mut freqs = engine.get_vector_array("frequency")?;
    if freqs.is_empty() {
        // Older ngspice names the sweep vector "frequency"; be tolerant.
        freqs = engine.get_vector_array("freq")?;
    }
    if freqs.is_empty() {
        return Err(AnalysisError::new(
            "ngspice produced no frequency vector - the sweep did not run".to_string(),
        ));
    }

    let (mut re, im) = engine.get_vector_complex(output_net)?;
    if re.is_empty() {
        return Err(AnalysisError::new(format!(
            "no vector named '{output_net}' in the AC plot; available nets: {}",
            if nets.is_empty() {
                "(none)".to_string()
            } else {
                nets.join(", ")
            }
        )));
    }

    if let Some(in_net) = input_net {
        let (in_re, in_im) = engine.get_vector_complex(in_net)?;
        if !in_re.is_empty() {
            re = _divide(&re, &im, &in_re, &in_im);
        }
    }
    // Deliberately no `quit`: sharedspice is a process-wide singleton, so
    // quitting it here would break every later NgSpiceEngine in this process
    // (observed as a hang, not an error). Process exit tears it down.

    let bode = bode_from_ac(&freqs, &re, &im, 1.0);
    if bode.freqs.is_empty() {
        return Err(AnalysisError::new(
            "AC sweep returned an empty Bode result".to_string(),
        ));
    }
    let margins = phase_margin(&bode.freqs, &bode.gain_db, &bode.phase_deg);

    let mut out: BTreeMap<String, CadValue> = BTreeMap::new();
    out.insert(
        "freqs".to_string(),
        CadValue::List(bode.freqs.iter().map(|&f| CadValue::F64(f)).collect()),
    );
    out.insert(
        "gain_db".to_string(),
        CadValue::List(bode.gain_db.iter().map(|&g| CadValue::F64(g)).collect()),
    );
    out.insert(
        "phase_deg".to_string(),
        CadValue::List(bode.phase_deg.iter().map(|&p| CadValue::F64(p)).collect()),
    );
    out.insert(
        "peak_db".to_string(),
        bode.peak_db.map_or(CadValue::Null, |v| CadValue::F64(v)),
    );
    out.insert(
        "peak_hz".to_string(),
        bode.peak_hz.map_or(CadValue::Null, |v| CadValue::F64(v)),
    );
    out.insert("net".to_string(), CadValue::Str(output_net.to_string()));
    out.insert(
        "input_net".to_string(),
        input_net.map_or(CadValue::Null, |s| CadValue::Str(s.to_string())),
    );

    let mut margins_map = BTreeMap::new();
    margins_map.insert(
        "crossover_hz".to_string(),
        margins
            .crossover_hz
            .map_or(CadValue::Null, |v| CadValue::F64(v)),
    );
    margins_map.insert(
        "gain_at_crossover_db".to_string(),
        margins
            .gain_at_crossover_db
            .map_or(CadValue::Null, |v| CadValue::F64(v)),
    );
    margins_map.insert(
        "phase_margin_deg".to_string(),
        margins
            .phase_margin_deg
            .map_or(CadValue::Null, |v| CadValue::F64(v)),
    );
    margins_map.insert(
        "gain_margin_db".to_string(),
        margins
            .gain_margin_db
            .map_or(CadValue::Null, |v| CadValue::F64(v)),
    );
    out.insert("margins".to_string(), CadValue::Map(margins_map));

    out.insert(
        "netlist".to_string(),
        CadValue::List(lines.iter().map(|l| CadValue::Str(l.clone())).collect()),
    );
    out.insert(
        "warnings".to_string(),
        CadValue::List(warns.iter().map(|w| CadValue::Str(w.clone())).collect()),
    );

    Ok(out)
}

// ---------------------------------------------------------------------------
// spice_value is defined above
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// run_noise
// ---------------------------------------------------------------------------

/// Small-signal noise analysis of a compiled schematic.
///
/// Compiles with analysis="noise" (ngspice's `.noise V(out) src dec ...`
/// card), solves, and returns the output/input noise spectral density
/// (V/sqrt(Hz)) versus frequency plus the integrated totals. ngspice puts
/// the spectrum in its `noise1` plot and the integrated totals in the
/// `noise2` plot that is current when `run` returns - hence the setplot.
pub fn run_noise(
    model: &SchematicNetlistEngine,
    output_net: &str,
    start_hz: f64,
    stop_hz: f64,
    points_per_decade: i32,
    engine: &mut NgSpiceEngine,
) -> AnalysisResult<BTreeMap<String, CadValue>> {
    let opts = CompileOptions {
        analysis: "noise".to_string(),
        noise_output_net: Some(output_net.to_string()),
        ac_start_hz: start_hz,
        ac_stop_hz: stop_hz,
        ac_points_per_decade: points_per_decade,
        ..Default::default()
    };
    let (lines, nets, warns) = model.compile_netlist(opts);
    if !nets.contains(&output_net.to_string()) {
        return Err(AnalysisError::new(format!(
            "'{output_net}' is not a probeable net of this schematic"
        )));
    }
    if !lines.iter().any(|l| l.to_lowercase().starts_with(".noise")) {
        return Err(AnalysisError::new(
            "the netlist contains no .noise card; nothing to analyse. "
                .to_string()
                + &warns.join(" "),
        ));
    }

    engine.load_circuit(&lines)?;
    let rc = engine.cmd("run")?;
    if rc != 0 {
        return Err(AnalysisError::new(format!(
            "ngspice noise run failed (rc {rc})"
        )));
    }

    // After `run` the current plot is this run's Integrated Noise plot; the
    // spectrum sits in the noise plot numbered one below it.  Locate by
    // description + numbering, never by the literal name "noise1": the
    // numbers keep incrementing inside one shared ngspice session.
    let plots = _plot_list(engine)?;
    let int_plot = plots
        .iter()
        .find(|(_, desc, cur)| *cur && desc.contains("Integrated Noise"))
        .map(|(name, _, _)| name.clone())
        .or_else(|| {
            plots
                .iter()
                .find(|(_, desc, _)| desc.contains("Integrated Noise"))
                .map(|(name, _, _)| name.clone())
        });
    let mut spec_plot = None;
    if let Some(ref ip) = int_plot {
        if ip.starts_with("noise") {
            let suffix = &ip["noise".len()..];
            if suffix.chars().all(|c| c.is_ascii_digit()) {
                if let Ok(num) = suffix.parse::<usize>() {
                    let want = format!("noise{}", num - 1);
                    if plots.iter().any(|(n, _, _)| n == &want) {
                        spec_plot = Some(want);
                    }
                }
            }
        }
    }
    if spec_plot.is_none() {
        spec_plot = plots
            .iter()
            .find(|(_, desc, _)| desc.contains("Noise Spectral Density Curves"))
            .map(|(name, _, _)| name.clone());
    }
    let int_plot = int_plot.ok_or_else(|| {
        AnalysisError::new(
            "ngspice produced no noise plots - the .noise run did not "
                .to_string()
                + "(ngspice has: "
                + &plots
                    .iter()
                    .map(|(n, _, _)| n.as_str())
                    .collect::<Vec<&str>>()
                    .join(", ")
                + ")",
        )
    })?;
    let spec_plot = spec_plot.ok_or_else(|| {
        AnalysisError::new(
            "ngspice produced no noise plots - the .noise run did not "
                .to_string()
                + "(ngspice has: "
                + &plots
                    .iter()
                    .map(|(n, _, _)| n.as_str())
                    .collect::<Vec<&str>>()
                    .join(", ")
                + ")",
        )
    })?;

    engine.cmd(&format!("setplot {int_plot}"))?;
    let total_out = engine.get_vector_array("onoise_total")?;
    let total_in = engine.get_vector_array("inoise_total")?;
    engine.cmd(&format!("setplot {spec_plot}"))?; // the spectral-density plot
    let freqs = engine.get_vector_array("frequency")?;
    let onoise = engine.get_vector_array("onoise_spectrum")?;
    let inoise = engine.get_vector_array("inoise_spectrum")?;
    if freqs.is_empty() || onoise.is_empty() || freqs.len() != onoise.len() {
        return Err(AnalysisError::new(
            "ngspice produced no noise spectrum - the .noise run did not complete"
                .to_string(),
        ));
    }

    let mut out: BTreeMap<String, CadValue> = BTreeMap::new();
    out.insert("net".to_string(), CadValue::Str(output_net.to_string()));
    out.insert(
        "freqs".to_string(),
        CadValue::List(freqs.iter().map(|&f| CadValue::F64(f)).collect()),
    );
    out.insert(
        "onoise_density".to_string(),
        CadValue::List(onoise.iter().map(|&o| CadValue::F64(o)).collect()),
    );
    out.insert(
        "inoise_density".to_string(),
        CadValue::List(
            inoise.iter().map(|&i| CadValue::F64(i)).collect(),
        ),
    );
    out.insert(
        "total_output".to_string(),
        total_out.first().map_or(CadValue::Null, |&v| CadValue::F64(v)),
    );
    out.insert(
        "total_input".to_string(),
        total_in.first().map_or(CadValue::Null, |&v| CadValue::F64(v)),
    );
    out.insert(
        "netlist".to_string(),
        CadValue::List(lines.iter().map(|l| CadValue::Str(l.clone())).collect()),
    );
    out.insert(
        "warnings".to_string(),
        CadValue::List(warns.iter().map(|w| CadValue::Str(w.clone())).collect()),
    );

    Ok(out)
}

// ---------------------------------------------------------------------------
// run_monte_carlo
// ---------------------------------------------------------------------------

/// Per-schematic tolerance / yield analysis.
///
/// Perturbs every R/C/L value by +/- tol_pct (uniform, seeded RNG), then
/// recompiles and re-solves the USER's schematic once per sample and records
/// the settled (final) value of `output_net`. The component values are
/// always restored, even on failure.
///
/// This is deliberately per-schematic: unlike studio_engine's parametric
/// Monte Carlo, every sample here is a real solve of the drawn circuit.
/// Source (V/I) values are NOT perturbed.
pub fn run_monte_carlo(
    model: &mut SchematicNetlistEngine,
    output_net: &str,
    iterations: usize,
    tol_pct: f64,
    yield_pct: f64,
    seed: Option<u64>,
    perturb: &[&str],
    engine: &mut NgSpiceEngine,
) -> AnalysisResult<BTreeMap<String, CadValue>> {
    if iterations < 2 {
        return Err(AnalysisError::new(
            "monte carlo needs at least 2 iterations".to_string(),
        ));
    }
    let opts = CompileOptions::default();
    let (lines, nets, warns) = model.compile_netlist(opts);
    if !nets.contains(&output_net.to_string()) {
        return Err(AnalysisError::new(format!(
            "'{output_net}' is not a probeable net of this schematic"
        )));
    }

    let mut comps: Vec<(String, f64)> = Vec::new();
    for (comp_id, comp) in model.components.iter() {
        let ct = comp.comp_type.to_uppercase();
        if !perturb.iter().any(|p| ct == p.to_uppercase()) {
            continue;
        }
        match spice_value(&comp.value) {
            Ok(base) => comps.push((comp_id.clone(), base)),
            Err(_) => continue, // PULSE(...) etc.: not a tolerance part
        }
    }
    if comps.is_empty() {
        return Err(AnalysisError::new(
            "no sweepable R/C/L parts with numeric values - nothing to "
                .to_string()
                + "tolerate",
        ));
    }

    let mut rng = SimpleRng::new(seed.unwrap_or(0));

    fn metric(
        model: &SchematicNetlistEngine,
        output_net: &str,
        engine: &mut NgSpiceEngine,
    ) -> AnalysisResult<f64> {
        let opts = CompileOptions::default();
        let (run_lines, _nets, _warns) = model.compile_netlist(opts);
        engine.load_circuit(&run_lines)?;
        let _rc = engine.cmd("run")?;
        let trace = engine.get_vector_array(output_net)?;
        if trace.is_empty() {
            return Err(AnalysisError::new(format!(
                "monte carlo sample failed to solve on '{output_net}'"
            )));
        }
        Ok(*trace.last().unwrap())
    }

    // Snapshot original values so we can restore them in all unwind paths.
    let originals: Vec<(String, String)> = comps
        .iter()
        .map(|(cid, _)| {
            (
                cid.clone(),
                model.components.get(cid).unwrap().value.clone(),
            )
        })
        .collect();

    let mut samples: Vec<f64> = Vec::with_capacity(iterations + 1);
    let nominal_result = metric(model, output_net, engine);
    let nominal = match nominal_result {
        Ok(v) => v,
        Err(e) => {
            // Restore before propagating
            for (cid, val) in &originals {
                if let Some(comp) = model.components.get_mut(cid) {
                    comp.value = val.clone();
                }
            }
            return Err(e);
        }
    };
    samples.push(nominal);

    let mut sample_err = None;
    for _ in 0..iterations {
        for (cid, base) in &comps {
            let u = 2.0 * rng.uniform() - 1.0; // [-1, 1)
            let new_val = base * (1.0 + u * tol_pct / 100.0);
            if let Some(comp) = model.components.get_mut(cid) {
                comp.value = crate::pycompat::py_g(new_val);
            }
        }
        match metric(model, output_net, engine) {
            Ok(v) => samples.push(v),
            Err(e) => {
                sample_err = Some(e);
                break;
            }
        }
    }

    // Restore original values (always, even on failure)
    for (cid, val) in &originals {
        if let Some(comp) = model.components.get_mut(cid) {
            comp.value = val.clone();
        }
    }

    if let Some(e) = sample_err {
        return Err(e);
    }

    let n = samples.len() as f64;
    let mean: f64 = samples.iter().sum::<f64>() / n;
    let variance: f64 = samples.iter().map(|&s| (s - mean) * (s - mean)).sum::<f64>() / n;
    let std = variance.sqrt();
    let band = nominal.abs() * (yield_pct / 100.0);
    let within = samples
        .iter()
        .filter(|&&s| (s - nominal).abs() <= band)
        .count();

    let mut out: BTreeMap<String, CadValue> = BTreeMap::new();
    out.insert("net".to_string(), CadValue::Str(output_net.to_string()));
    out.insert("iterations".to_string(), CadValue::I32(iterations as i32));
    out.insert("tol_pct".to_string(), CadValue::F64(tol_pct));
    out.insert("yield_pct_spec".to_string(), CadValue::F64(yield_pct));
    out.insert(
        "yield_actual_pct".to_string(),
        CadValue::F64(100.0 * within as f64 / n),
    );
    out.insert("nominal".to_string(), CadValue::F64(nominal));
    out.insert(
        "samples".to_string(),
        CadValue::List(samples.iter().map(|&s| CadValue::F64(s)).collect()),
    );
    out.insert("mean".to_string(), CadValue::F64(mean));
    out.insert("std".to_string(), CadValue::F64(std));
    out.insert(
        "min".to_string(),
        CadValue::F64(samples.iter().copied().fold(f64::INFINITY, f64::min)),
    );
    out.insert(
        "max".to_string(),
        CadValue::F64(
            samples
                .iter()
                .copied()
                .fold(f64::NEG_INFINITY, f64::max),
        ),
    );
    out.insert(
        "cv".to_string(),
        if mean != 0.0 {
            CadValue::F64(std / mean)
        } else {
            CadValue::Null
        },
    );
    out.insert(
        "parts".to_string(),
        CadValue::List(
            comps
                .iter()
                .map(|(cid, _)| {
                    model
                        .components
                        .get(cid)
                        .map(|c| {
                            if c.name.is_empty() {
                                CadValue::Str(cid.clone())
                            } else {
                                CadValue::Str(c.name.clone())
                            }
                        })
                        .unwrap_or(CadValue::Str(cid.clone()))
                })
                .collect(),
        ),
    );
    out.insert(
        "netlist".to_string(),
        CadValue::List(lines.iter().map(|l| CadValue::Str(l.clone())).collect()),
    );
    out.insert(
        "warnings".to_string(),
        CadValue::List(warns.iter().map(|w| CadValue::Str(w.clone())).collect()),
    );

    Ok(out)
}

/// Simple seeded PRNG (xorshift64*).  Used where Python would use
/// `random.Random(seed)`.  Deterministic for a given seed - no OS entropy.
pub struct SimpleRng {
    state: u64,
}

impl SimpleRng {
    pub fn new(seed: u64) -> Self {
        let mut state = seed;
        if state == 0 {
            state = 1;
        }
        Self { state }
    }

    /// Return f64 in [0, 1).
    pub fn uniform(&mut self) -> f64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        let x = x.wrapping_mul(0x2545F4914F6CDD1D);
        (x >> 11) as f64 / (1u64 << 53) as f64
    }
}

// ---------------------------------------------------------------------------
// _plot_list
// ---------------------------------------------------------------------------

/// (name, description, is_current) for every plot ngspice has open.
///
/// Reads the listing a bare `setplot` prints. Plots are located by their
/// DESCRIPTION rather than by name because the numbers in ac1/disto1/disto2
/// increment across runs inside one shared session.
fn _plot_list(engine: &mut NgSpiceEngine) -> AnalysisResult<Vec<(String, String, bool)>> {
    let start = engine.output_logs.len();
    engine.cmd("setplot")?;
    let mut plots: Vec<(String, String, bool)> = Vec::new();
    let mut listing = false;
    for raw in engine.output_logs[start..].iter() {
        let mut line = raw.as_str();
        for prefix in ["stdout ", "stderr "] {
            if let Some(rest) = line.strip_prefix(prefix) {
                line = rest;
            }
        }
        let line = line.trim_end();
        if line.contains("List of plots available") {
            listing = true;
            continue;
        }
        if !listing {
            continue;
        }
        let tokens: Vec<&str> = line.split_whitespace().collect();
        let mut current = false;
        let tokens = if tokens.first() == Some(&"Current") {
            current = true;
            &tokens[1..]
        } else {
            &tokens[..]
        };
        if tokens.len() >= 2 {
            plots.push((tokens[0].to_string(), tokens[1..].join(" "), current));
        }
    }
    Ok(plots)
}

// ---------------------------------------------------------------------------
// run_disto
// ---------------------------------------------------------------------------

/// Harmonic distortion (`.disto`) with the `.ac` reference run: HD2/HD3
/// versus frequency.
///
/// ngspice executes three analyses for this deck and leaves three plots
/// open (AC reference at f1, distortion at 2f1, distortion at 3f1). They
/// are located by description, then HD = |V_harmonic| / |V_f1| per the
/// ngspice manual - the raw .disto output is an AC voltage, not a ratio.
pub fn run_disto(
    model: &SchematicNetlistEngine,
    output_net: &str,
    start_hz: f64,
    stop_hz: f64,
    points_per_decade: i32,
    engine: &mut NgSpiceEngine,
) -> AnalysisResult<BTreeMap<String, CadValue>> {
    let opts = CompileOptions {
        analysis: "disto".to_string(),
        ac_start_hz: start_hz,
        ac_stop_hz: stop_hz,
        ac_points_per_decade: points_per_decade,
        ..Default::default()
    };
    let (lines, nets, warns) = model.compile_netlist(opts);
    if !nets.contains(&output_net.to_string()) {
        return Err(AnalysisError::new(format!(
            "'{output_net}' is not a probeable net of this schematic"
        )));
    }
    if !lines.iter().any(|l| l.to_lowercase().starts_with(".disto")) {
        return Err(AnalysisError::new(
            "the netlist contains no .disto card; nothing to analyse. "
                .to_string()
                + &warns.join(" "),
        ));
    }

    engine.load_circuit(&lines)?;
    let rc = engine.cmd("run")?;
    if rc != 0 {
        return Err(AnalysisError::new(format!(
            "ngspice distortion run failed (rc {rc})"
        )));
    }

    let plots = _plot_list(engine)?;

    fn find<'a>(plots: &'a [(String, String, bool)], marker: &str) -> Option<&'a str> {
        for (name, desc, _cur) in plots {
            if desc.contains(marker) {
                return Some(name);
            }
        }
        None
    }

    let ac_plot = find(&plots, "(AC Analysis)");
    let d2_plot = find(&plots, "DISTORTION - 2nd harmonic");
    let d3_plot = find(&plots, "DISTORTION - 3rd harmonic");
    let missing: Vec<&str> = [
        ("AC reference", ac_plot),
        ("2nd harmonic", d2_plot),
        ("3rd harmonic", d3_plot),
    ]
    .iter()
    .filter_map(|(m, p)| if p.is_none() { Some(*m) } else { None })
    .collect();
    if !missing.is_empty() {
        return Err(AnalysisError::new(
            "distortion plots missing: ".to_string()
                + &missing.join(", ")
                + " (ngspice has: "
                + &plots
                    .iter()
                    .map(|(n, _, _)| n.as_str())
                    .collect::<Vec<&str>>()
                    .join(", ")
                + ")",
        ));
    }

    engine.cmd(&format!("setplot {}", ac_plot.unwrap()))?;
    let freqs = engine.get_vector_array("frequency")?;
    let (re1, im1) = engine.get_vector_complex(output_net)?;
    engine.cmd(&format!("setplot {}", d2_plot.unwrap()))?;
    let (re2, im2) = engine.get_vector_complex(output_net)?;
    engine.cmd(&format!("setplot {}", d3_plot.unwrap()))?;
    let (re3, im3) = engine.get_vector_complex(output_net)?;
    if freqs.is_empty() || re1.is_empty() {
        return Err(AnalysisError::new(
            "distortion run produced no frequency/fundamental data".to_string(),
        ));
    }
    let mag1: Vec<f64> = re1.iter().zip(im1.iter()).map(|(&a, &b)| (a * a + b * b).sqrt()).collect();
    if !mag1.iter().any(|&m| m > 0.0) {
        return Err(AnalysisError::new(
            "the AC reference is all zeros - no excitation at f1 "
                .to_string()
                + "(did the source get its AC magnitude?)",
        ));
    }
    let mag2: Vec<f64> = re2.iter().zip(im2.iter()).map(|(&a, &b)| (a * a + b * b).sqrt()).collect();
    let mag3: Vec<f64> = re3.iter().zip(im3.iter()).map(|(&a, &b)| (a * a + b * b).sqrt()).collect();
    let hd2: Vec<f64> = mag1
        .iter()
        .zip(mag2.iter())
        .map(|(&m1, &m2)| if m1 > 0.0 { m2 / m1 } else { 0.0 })
        .collect();
    let hd3: Vec<f64> = mag1
        .iter()
        .zip(mag3.iter())
        .map(|(&m1, &m3)| if m1 > 0.0 { m3 / m1 } else { 0.0 })
        .collect();

    let mut out: BTreeMap<String, CadValue> = BTreeMap::new();
    out.insert("net".to_string(), CadValue::Str(output_net.to_string()));
    out.insert(
        "freqs".to_string(),
        CadValue::List(freqs.iter().map(|&f| CadValue::F64(f)).collect()),
    );
    out.insert(
        "hd2".to_string(),
        CadValue::List(hd2.iter().map(|&h| CadValue::F64(h)).collect()),
    );
    out.insert(
        "hd3".to_string(),
        CadValue::List(hd3.iter().map(|&h| CadValue::F64(h)).collect()),
    );
    out.insert(
        "fundamental".to_string(),
        CadValue::List(mag1.iter().map(|&m| CadValue::F64(m)).collect()),
    );
    out.insert(
        "netlist".to_string(),
        CadValue::List(lines.iter().map(|l| CadValue::Str(l.clone())).collect()),
    );
    out.insert(
        "warnings".to_string(),
        CadValue::List(warns.iter().map(|w| CadValue::Str(w.clone())).collect()),
    );

    Ok(out)
}

// ---------------------------------------------------------------------------
// _divide - complex division H = N / D
// ---------------------------------------------------------------------------

/// Complex division H = N / D, used to reference gain to a real input node.
/// Returns only the real part of the quotient.
pub fn _divide(nre: &[f64], nim: &[f64], dre: &[f64], dim: &[f64]) -> Vec<f64> {
    let mut out = Vec::with_capacity(nre.len());
    for i in 0..nre.len() {
        let a = nre[i];
        let b = nim[i];
        let c = dre[i];
        let d = dim[i];
        let denom = c * c + d * d;
        if denom <= 0.0 {
            out.push(0.0);
        } else {
            out.push((a * c + b * d) / denom);
        }
    }
    out
}

// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_spice_value_plain_number() {
        assert_eq!(spice_value("10").unwrap(), 10.0);
        assert_eq!(spice_value("3.14").unwrap(), 3.14);
        assert_eq!(spice_value("0").unwrap(), 0.0);
        assert_eq!(spice_value("-5.5").unwrap(), -5.5);
    }

    #[test]
    fn test_spice_value_suffixes() {
        assert!((spice_value("1k").unwrap() - 1000.0).abs() < f64::EPSILON);
        assert!((spice_value("1K").unwrap() - 1000.0).abs() < f64::EPSILON);
        assert!((spice_value("4.7u").unwrap() - 4.7e-6).abs() < f64::EPSILON);
        assert!((spice_value("100n").unwrap() - 100e-9).abs() < f64::EPSILON);
        assert!((spice_value("2.2p").unwrap() - 2.2e-12).abs() < f64::EPSILON);
        assert!((spice_value("1f").unwrap() - 1e-15).abs() < f64::EPSILON);
        assert!((spice_value("1meg").unwrap() - 1e6).abs() < f64::EPSILON);
        assert!((spice_value("100m").unwrap() - 0.1).abs() < f64::EPSILON);
        // mil: 1 mil = 2.54e-5 inches
        assert!((spice_value("10mil").unwrap() - 10.0 * 2.54e-5).abs() < f64::EPSILON);
    }

    #[test]
    fn test_spice_value_strips_whitespace() {
        assert_eq!(spice_value("  1k  ").unwrap(), 1000.0);
    }

    #[test]
    fn test_spice_value_empty_errors() {
        assert!(spice_value("").is_err());
        assert!(spice_value("   ").is_err());
    }

    #[test]
    fn test_spice_value_invalid_errors() {
        assert!(spice_value("PULSE(0 1 0 1n 1n 1u 10u)").is_err());
        assert!(spice_value("1k2").is_err()); // mixed units
    }

    #[test]
    fn test_divide_complex() {
        // (1+2i) / (3+4i) = ((1*3 + 2*4) + i(2*3 - 1*4)) / (9+16) = (11 + 2i) / 25
        // real part = 11/25 = 0.44
        let result = _divide(&[1.0], &[2.0], &[3.0], &[4.0]);
        assert!((result[0] - 0.44).abs() < f64::EPSILON);

        // (3+4i) / (3+4i) = 1 + 0i → real part = 1.0
        let result = _divide(&[3.0], &[4.0], &[3.0], &[4.0]);
        assert!((result[0] - 1.0).abs() < f64::EPSILON);

        // zero denominator → 0.0
        let result = _divide(&[1.0], &[2.0], &[0.0], &[0.0]);
        assert!((result[0] - 0.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_analysis_error_display() {
        let err = AnalysisError::new("something went wrong");
        assert_eq!(err.message(), "something went wrong");
        assert_eq!(err.to_string(), "something went wrong");
    }

    #[test]
    fn test_run_fft_no_transient_data() {
        // Engine stub has no DLL - get_vector_array returns Err
        let engine = NgSpiceEngine::new(None, false, None, None).unwrap();
        let result = run_fft(&engine, "v(out)", "hann", None);
        assert!(result.is_err());
    }

    #[test]
    fn test_run_bode_no_dll() {
        let model = SchematicNetlistEngine::new();
        let mut engine = NgSpiceEngine::new(None, false, None, None).unwrap();
        let result = run_bode(&model, "v(out)", None, 1.0, 1e6, 20, &mut engine);
        assert!(result.is_err());
    }

    #[test]
    fn test_run_monte_carlo_insufficient_iterations() {
        let mut model = SchematicNetlistEngine::new();
        let mut engine = NgSpiceEngine::new(None, false, None, None).unwrap();
        let result = run_monte_carlo(
            &mut model, "v(out)", 1, 5.0, 5.0, None, &["R", "C", "L"], &mut engine,
        );
        assert!(result.is_err());
        assert!(result.unwrap_err().message().contains("at least 2 iterations"));
    }

    #[test]
    fn test_simple_rng_deterministic() {
        let mut rng1 = SimpleRng::new(42);
        let mut rng2 = SimpleRng::new(42);
        for _ in 0..100 {
            assert!((rng1.uniform() - rng2.uniform()).abs() < f64::EPSILON);
        }
    }

    #[test]
    fn test_simple_rng_different_seeds() {
        let mut rng1 = SimpleRng::new(1);
        let mut rng2 = SimpleRng::new(2);
        let mut different = false;
        for _ in 0..100 {
            if (rng1.uniform() - rng2.uniform()).abs() > f64::EPSILON {
                different = true;
                break;
            }
        }
        assert!(different);
    }
}
