/*
 * report_generator.rs - port of bridge/report_generator.py.
 *
 * Automated Engineering Lab & Test Bench Report Generator.
 * Produces a comprehensive, standalone HTML test report mirroring the Python
 * original one-to-one: testbench setup & architecture, 4-channel oscilloscope
 * waveforms, 6.5-digit true-RMS DMM readings & statistics, FFT spectrum & THD
 * analysis, Bode plot loop stability margins (PM, GM, crossover), power
 * efficiency & thermal loss breakdown, and a BOM / firmware code snapshot.
 *
 * Pure computation over numbers and strings: no solver, no Qt, no filesystem
 * beyond an optional write of `output_path`. Core stays dependency-free
 * (no chrono, no serde).
 *
 * Parity contract: `LabReportGenerator::generate_html_report` mirrors the
 * Python `LabReportGenerator.generate_html_report` static method, including
 * the `metrics.get(key, default)` fallback semantics and float formatting.
 */

use std::collections::BTreeMap;
use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

/// Default project name, mirroring the Python default argument.
pub const DEFAULT_PROJECT_NAME: &str =
    "ESP32 Mixed-Signal Hysteretic Buck Regulator";

/// A single report metric.
///
/// Mirrors Python `Dict[str, Any]` where telemetry values are floats and
/// status values (e.g. `stability_status`) are strings.
#[derive(Debug, Clone)]
pub enum MetricValue {
    F64(f64),
    Str(String),
}

/// Alias for the metrics bag, mirroring Python `Dict[str, Any]`.
pub type Metrics = BTreeMap<String, MetricValue>;

/// Lookup a numeric metric with a fallback default, mirroring
/// `metrics.get(key, default)`.
fn metric_f64(metrics: &Metrics, key: &str, default: f64) -> f64 {
    match metrics.get(key) {
        Some(MetricValue::F64(v)) => *v,
        _ => default,
    }
}

/// Lookup a string metric with a fallback default.
fn metric_str<'a>(metrics: &'a Metrics, key: &str, default: &'a str) -> &'a str {
    match metrics.get(key) {
        Some(MetricValue::Str(s)) => s.as_str(),
        _ => default,
    }
}

/// Format helpers mirroring Python `f"{v:.Nf}"` (fixed-point output).
fn fmt1(v: f64) -> String {
    format!("{:.1}", v)
}
fn fmt2(v: f64) -> String {
    format!("{:.2}", v)
}
fn fmt3(v: f64) -> String {
    format!("{:.3}", v)
}
fn fmt4(v: f64) -> String {
    format!("{:.4}", v)
}

/// Current UTC timestamp as `YYYY-MM-DD HH:MM:SS UTC`, mirroring
/// `time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())`.
///
/// Uses `SystemTime` plus a manual civil-calendar conversion (Howard
/// Hinnant's `civil_from_days`) so no `chrono` crate is needed.
fn utc_now_str() -> String {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(d) => {
            let secs = d.as_secs() as i64;
            let days = secs / 86400;
            let rem = secs % 86400;
            let hour = (rem / 3600) as u32;
            let minute = ((rem % 3600) / 60) as u32;
            let second = (rem % 60) as u32;
            let (y, m, day) = civil_from_days(days);
            format!(
                "{:04}-{:02}-{:02} {:02}:{:02}:{:02} UTC",
                y, m, day, hour, minute, second
            )
        }
        Err(_) => "1970-01-01 00:00:00 UTC".to_string(),
    }
}

/// Convert days since 1970-01-01 to `(year, month, day)` in the proleptic
/// Gregorian calendar. Howard Hinnant's `civil_from_days` algorithm.
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719468;
    // Floor division by 146097. Rust `/` truncates toward zero, so the
    // `z - 146096` adjustment makes the negative branch round down, matching
    // the mathematical floor used by `civil_from_days`.
    let era = (if z >= 0 { z } else { z - 146096 }) / 146097;
    let doe = z - era * 146097; // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365; // [0, 399]
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = doy - (153 * mp + 2) / 5 + 1; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    let y = if m <= 2 { y + 1 } else { y };
    (y, m as u32, d as u32)
}

/// HTML report generator mirroring `bridge/report_generator.py`.
pub struct LabReportGenerator;

impl LabReportGenerator {
    /// Generate a rich, standalone HTML test report with embedded styling and
    /// tables. Mirrors `LabReportGenerator.generate_html_report` exactly.
    ///
    /// `project_name` defaults to `DEFAULT_PROJECT_NAME` when `None`.
    /// If `output_path` is `Some`, the HTML is also written there (UTF-8).
    pub fn generate_html_report(
        metrics: &Metrics,
        project_name: Option<&str>,
        output_path: Option<&str>,
    ) -> String {
        let project_name = project_name.unwrap_or(DEFAULT_PROJECT_NAME);
        let t_str = utc_now_str();
        let stability_status = metric_str(metrics, "stability_status", "PASSED");

        let p_loss_total = metric_f64(metrics, "p_loss_total", 1.0);
        let loss_denom = p_loss_total + 1e-6;
        let loss_pct = |v: f64| format!("{:.1}%", (v / loss_denom) * 100.0);

        // Pre-compute every interpolated value so the template below holds
        // only literal structure plus `{token}` placeholders.
        let dmm_vdc = fmt4(metric_f64(metrics, "dmm_vdc", 0.0));
        let dmm_vrms = fmt4(metric_f64(metrics, "dmm_vrms", 0.0));
        let p2p_ripple_mv = fmt1(metric_f64(metrics, "p2p_ripple_mv", 0.0));
        let efficiency_pct = fmt1(metric_f64(metrics, "efficiency_pct", 0.0));
        let sw_freq_khz = fmt1(metric_f64(metrics, "sw_freq_khz", 0.0));
        let phase_margin_deg = fmt1(metric_f64(metrics, "phase_margin_deg", 0.0));
        let p_cond_mosfet = fmt3(metric_f64(metrics, "p_cond_mosfet", 0.0));
        let p_cond_mosfet_pct = loss_pct(metric_f64(metrics, "p_cond_mosfet", 0.0));
        let p_cond_diode = fmt3(metric_f64(metrics, "p_cond_diode", 0.0));
        let p_cond_diode_pct = loss_pct(metric_f64(metrics, "p_cond_diode", 0.0));
        let p_cond_passives = fmt3(metric_f64(metrics, "p_cond_passives", 0.0));
        let p_cond_passives_pct = loss_pct(metric_f64(metrics, "p_cond_passives", 0.0));
        let p_switching = fmt3(metric_f64(metrics, "p_switching", 0.0));
        let p_switching_pct = loss_pct(metric_f64(metrics, "p_switching", 0.0));
        let p_loss_total_s = fmt3(p_loss_total);
        let tj_rise_c = format!("+{:.1} °C Rise", metric_f64(metrics, "tj_rise_c", 0.0));
        let gain_margin_db = fmt1(metric_f64(metrics, "gain_margin_db", 0.0));
        let f_crossover_hz = fmt1(metric_f64(metrics, "f_crossover_hz", 0.0));
        let thd_pct = fmt2(metric_f64(metrics, "thd_pct", 0.0));

        let mut html = HTML_TEMPLATE.replace("{project_name}", project_name);
        html = html.replace("{t_str}", &t_str);
        html = html.replace("{stability_status}", stability_status);
        html = html.replace("{dmm_vdc}", &dmm_vdc);
        html = html.replace("{dmm_vrms}", &dmm_vrms);
        html = html.replace("{p2p_ripple_mv}", &p2p_ripple_mv);
        html = html.replace("{efficiency_pct}", &efficiency_pct);
        html = html.replace("{sw_freq_khz}", &sw_freq_khz);
        html = html.replace("{phase_margin_deg}", &phase_margin_deg);
        html = html.replace("{p_cond_mosfet}", &p_cond_mosfet);
        html = html.replace("{p_cond_mosfet_pct}", &p_cond_mosfet_pct);
        html = html.replace("{p_cond_diode}", &p_cond_diode);
        html = html.replace("{p_cond_diode_pct}", &p_cond_diode_pct);
        html = html.replace("{p_cond_passives}", &p_cond_passives);
        html = html.replace("{p_cond_passives_pct}", &p_cond_passives_pct);
        html = html.replace("{p_switching}", &p_switching);
        html = html.replace("{p_switching_pct}", &p_switching_pct);
        html = html.replace("{p_loss_total}", &p_loss_total_s);
        html = html.replace("{tj_rise_c}", &tj_rise_c);
        html = html.replace("{gain_margin_db}", &gain_margin_db);
        html = html.replace("{f_crossover_hz}", &f_crossover_hz);
        html = html.replace("{thd_pct}", &thd_pct);

        if let Some(path) = output_path {
            let _ = fs::write(path, &html);
        }
        html
    }
}

/// The HTML report template, identical in structure to the Python f-string
/// output. `{token}` placeholders are filled by `generate_html_report` via
/// `str::replace`; every brace below is literal CSS/HTML, so no `format!`
/// brace-doubling is required (the template is a raw string).
const HTML_TEMPLATE: &str = r#"<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>WOWKISPICE Engineering Lab Test Report - {project_name}</title>
<style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0d1117; color: #e6edf3; margin: 0; padding: 30px; }
    .container { max-width: 1100px; margin: 0 auto; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 30px; }
    h1 { color: #58a6ff; font-size: 26px; border-bottom: 2px solid #30363d; padding-bottom: 12px; margin-top: 0; }
    h2 { color: #3fb950; font-size: 18px; margin-top: 25px; border-bottom: 1px solid #21262d; padding-bottom: 6px; }
    .badge { display: inline-block; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; background: #238636; color: #ffffff; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; margin: 20px 0; }
    .card { background: #21262d; border: 1px solid #30363d; border-radius: 6px; padding: 15px; }
    .card-title { font-size: 11px; text-transform: uppercase; color: #8b949e; letter-spacing: 0.5px; }
    .card-val { font-size: 22px; font-weight: bold; color: #58a6ff; font-family: 'Consolas', monospace; margin-top: 5px; }
    table { width: 100%; border-collapse: collapse; margin: 15px 0; background: #0d1117; border-radius: 6px; overflow: hidden; }
    th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #21262d; font-size: 13px; }
    th { background: #21262d; color: #e6edf3; }
    td.mono { font-family: 'Consolas', monospace; color: #79c0ff; }
    .footer { margin-top: 40px; text-align: center; color: #8b949e; font-size: 12px; border-top: 1px solid #30363d; padding-top: 15px; }
</style>
</head>
<body>
<div class="container">
    <h1>⚡ WOWKISPICE Co-Simulation Test Report</h1>
    <p style="color: #8b949e; font-size: 13px;">
        <strong>Project:</strong> {project_name} | <strong>Generated:</strong> {t_str} | <span class="badge">STATUS: {stability_status}</span>
    </p>

    <h2>1. Executive Summary & DC Precision Telemetry</h2>
    <div class="grid">
        <div class="card">
            <div class="card-title">DC Output Voltage</div>
            <div class="card-val">{dmm_vdc} V</div>
        </div>
        <div class="card">
            <div class="card-title">True RMS Voltage</div>
            <div class="card-val">{dmm_vrms} V</div>
        </div>
        <div class="card">
            <div class="card-title">Output Ripple (Vp-p)</div>
            <div class="card-val" style="color: #f778ba;">{p2p_ripple_mv} mV</div>
        </div>
        <div class="card">
            <div class="card-title">Power Efficiency (η)</div>
            <div class="card-val" style="color: #3fb950;">{efficiency_pct} %</div>
        </div>
        <div class="card">
            <div class="card-title">Switching Frequency</div>
            <div class="card-val">{sw_freq_khz} kHz</div>
        </div>
        <div class="card">
            <div class="card-title">Phase Margin (PM)</div>
            <div class="card-val" style="color: #d29922;">{phase_margin_deg}°</div>
        </div>
    </div>

    <h2>2. Power & Thermal Dissipation Breakdown</h2>
    <table>
        <thead>
            <tr>
                <th>Subsystem Component</th>
                <th>Loss Mechanism</th>
                <th>Estimated Dissipation (W)</th>
                <th>Loss Ratio (%)</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Power MOSFET (IRF540N)</td>
                <td>Conduction Loss ($I_{RMS}^2 R_{DS(on)}$)</td>
                <td class="mono">{p_cond_mosfet} W</td>
                <td>{p_cond_mosfet_pct}</td>
            </tr>
            <tr>
                <td>Schottky Diode (1N5819)</td>
                <td>Forward Conduction ($V_F \cdot I_D$)</td>
                <td class="mono">{p_cond_diode} W</td>
                <td>{p_cond_diode_pct}</td>
            </tr>
            <tr>
                <td>Inductor & Capacitor</td>
                <td>Copper DCR & ESR Dissipation</td>
                <td class="mono">{p_cond_passives} W</td>
                <td>{p_cond_passives_pct}</td>
            </tr>
            <tr>
                <td>Gate Drive & Switching</td>
                <td>$E_{sw} \cdot f_{sw}$ Transition Overlap</td>
                <td class="mono">{p_switching} W</td>
                <td>{p_switching_pct}</td>
            </tr>
            <tr style="font-weight: bold; background: #21262d;">
                <td>Total Dissipation & Junction Rise</td>
                <td>$\Delta T_J = P_{loss} \cdot 40^\circ\text{C/W}$</td>
                <td class="mono">{p_loss_total} W</td>
                <td style="color: #f85149;">{tj_rise_c}</td>
            </tr>
        </tbody>
    </table>

    <h2>3. Small-Signal Frequency Response & Stability Margins</h2>
    <table>
        <thead>
            <tr>
                <th>Stability Metric</th>
                <th>Measured Value</th>
                <th>Target Specification</th>
                <th>Compliance Status</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Phase Margin (PM)</td>
                <td class="mono">{phase_margin_deg} Degrees</td>
                <td>&ge; 45.0 Degrees</td>
                <td style="color: #3fb950;">PASS</td>
            </tr>
            <tr>
                <td>Gain Margin (GM)</td>
                <td class="mono">{gain_margin_db} dB</td>
                <td>&ge; 10.0 dB</td>
                <td style="color: #3fb950;">PASS</td>
            </tr>
            <tr>
                <td>Gain Crossover Frequency ($f_{gc}$)</td>
                <td class="mono">{f_crossover_hz} Hz</td>
                <td>100 Hz - 50 kHz</td>
                <td style="color: #3fb950;">PASS</td>
            </tr>
            <tr>
                <td>Total Harmonic Distortion (THD)</td>
                <td class="mono">{thd_pct} %</td>
                <td>&le; 5.0 %</td>
                <td style="color: #3fb950;">PASS</td>
            </tr>
        </tbody>
    </table>

    <div class="footer">
        Generated automatically by WOWKISPICE Studio &bull; High-Fidelity Hardware-Firmware Co-Simulation Engine
    </div>
</div>
</body>
</html>"#;
