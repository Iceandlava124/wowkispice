/*
 * test_report_generator.rs - Rust gate for bridge/report_generator.py.
 *
 * Transcribes LabReportGenerator.generate_html_report: metrics.get(key,
 * default) fallback semantics, float formatting (.1/.2/.3/.4f), token
 * replacement, UTC timestamp, and HTML template structure.
 */

use std::collections::BTreeMap;
use wowkispice_core::report_generator::{
    civil_from_days, fmt1, fmt2, fmt3, fmt4, metric_f64, metric_str,
    utc_now_str, LabReportGenerator, MetricValue, Metrics,
};

fn metrics() -> Metrics {
    let mut m = BTreeMap::new();
    m.insert("dmm_vdc".to_string(), MetricValue::F64(3.3012));
    m.insert("dmm_vrms".to_string(), MetricValue::F64(3.3005));
    m.insert("p2p_ripple_mv".to_string(), MetricValue::F64(47.3));
    m.insert("efficiency_pct".to_string(), MetricValue::F64(92.7));
    m.insert("sw_freq_khz".to_string(), MetricValue::F64(250.4));
    m.insert("phase_margin_deg".to_string(), MetricValue::F64(68.3));
    m.insert("p_cond_mosfet".to_string(), MetricValue::F64(0.123));
    m.insert("p_cond_diode".to_string(), MetricValue::F64(0.045));
    m.insert("p_cond_passives".to_string(), MetricValue::F64(0.012));
    m.insert("p_switching".to_string(), MetricValue::F64(0.008));
    m.insert("p_loss_total".to_string(), MetricValue::F64(0.188));
    m.insert("tj_rise_c".to_string(), MetricValue::F64(7.5));
    m.insert("gain_margin_db".to_string(), MetricValue::F64(14.2));
    m.insert("f_crossover_hz".to_string(), MetricValue::F64(12500.0));
    m.insert("thd_pct".to_string(), MetricValue::F64(1.85));
    m.insert("stability_status".to_string(), MetricValue::Str("PASSED".to_string()));
    m
}

// ----------------------------------------------------------------------
// metric_f64 / metric_str fallbacks
// ----------------------------------------------------------------------

#[test]
fn test_metric_f64_present() {
    let m = metrics();
    assert!((metric_f64(&m, "dmm_vdc", 0.0) - 3.3012).abs() < 1e-9);
}

#[test]
fn test_metric_f64_missing_defaults() {
    let m = BTreeMap::new();
    assert_eq!(metric_f64(&m, "missing", 42.0), 42.0);
    assert_eq!(metric_f64(&m, "p_loss_total", 1.0), 1.0);
}

#[test]
fn test_metric_f64_wrong_type_falls_back() {
    let mut m = BTreeMap::new();
    m.insert("x".to_string(), MetricValue::Str("not a number".to_string()));
    assert_eq!(metric_f64(&m, "x", 9.9), 9.9);
}

#[test]
fn test_metric_str_present() {
    let m = metrics();
    assert_eq!(metric_str(&m, "stability_status", "UNKNOWN"), "PASSED");
}

#[test]
fn test_metric_str_missing_defaults() {
    let m = BTreeMap::new();
    assert_eq!(metric_str(&m, "missing", "default"), "default");
}

// ----------------------------------------------------------------------
// float formatting helpers (.1/.2/.3/.4f)
// ----------------------------------------------------------------------

#[test]
fn test_fmt1() {
    assert_eq!(fmt1(3.14159), "3.1");
    assert_eq!(fmt1(0.0), "0.0");
    assert_eq!(fmt1(-2.5), "-2.5");
}

#[test]
fn test_fmt2() {
    assert_eq!(fmt2(1.856), "1.86");
    assert_eq!(fmt2(0.0), "0.00");
}

#[test]
fn test_fmt3() {
    assert_eq!(fmt3(0.1234), "0.123");
    assert_eq!(fmt3(0.0), "0.000");
}

#[test]
fn test_fmt4() {
    assert_eq!(fmt4(3.3012), "3.3012");
    assert_eq!(fmt4(0.0), "0.0000");
}

// ----------------------------------------------------------------------
// UTC timestamp
// ----------------------------------------------------------------------

#[test]
fn test_utc_now_str_format() {
    let s = utc_now_str();
    // YYYY-MM-DD HH:MM:SS UTC = 23 chars
    assert!(s.len() == 23, "expected length 23, got {}: {}", s.len(), s);
    assert!(s.ends_with(" UTC"));
    assert_eq!(&s[4..5], "-");
    assert_eq!(&s[7..8], "-");
    assert_eq!(&s[10..11], " ");
    assert_eq!(&s[13..14], ":");
    assert_eq!(&s[16..17], ":");
}

// ----------------------------------------------------------------------
// civil_from_days (Howard Hinnant's algorithm)
// ----------------------------------------------------------------------

#[test]
fn test_civil_from_days_epoch() {
    // 1970-01-01 is day 0
    let (y, m, d) = civil_from_days(0);
    assert_eq!((y, m, d), (1970, 1, 1));
}

#[test]
fn test_civil_from_days_known_dates() {
    // Day 0 = 1970-01-01, day 365 = 1971-01-01 (1970 is not a leap year)
    let (y, m, d) = civil_from_days(365);
    assert_eq!((y, m, d), (1971, 1, 1));

    // 2000-02-29 (leap day): days from epoch to 2000-01-01 = 10957,
    // + 31 (Jan) + 28 (to Feb 29) = 11016
    let (y, m, d) = civil_from_days(11016);
    assert_eq!((y, m, d), (2000, 2, 29));

    // negative days (before epoch)
    let (y, m, d) = civil_from_days(-1);
    assert_eq!((y, m, d), (1969, 12, 31));
}

// ----------------------------------------------------------------------
// LabReportGenerator::generate_html_report
// ----------------------------------------------------------------------

#[test]
fn test_generate_html_report_contains_project_name() {
    let m = metrics();
    let html = LabReportGenerator::generate_html_report(&m, Some("My Buck"), None);
    assert!(html.contains("My Buck"));
    assert!(!html.contains("{project_name}"), "unfilled template token");
}

#[test]
fn test_generate_html_report_default_project_name() {
    let m = metrics();
    let html = LabReportGenerator::generate_html_report(&m, None, None);
    assert!(html.contains("ESP32 Mixed-Signal Hysteretic Buck Regulator"));
}

#[test]
fn test_generate_html_report_contains_all_metrics() {
    let m = metrics();
    let html = LabReportGenerator::generate_html_report(&m, None, None);
    for token in [
        "3.3012",      // dmm_vdc (.4f)
        "3.3005",      // dmm_vrms (.4f)
        "47.3",        // p2p_ripple_mv (.1f)
        "92.7",        // efficiency_pct (.1f)
        "250.4",       // sw_freq_khz (.1f)
        "68.3",        // phase_margin_deg (.1f)
        "0.123",       // p_cond_mosfet (.3f)
        "0.045",       // p_cond_diode (.3f)
        "0.012",       // p_cond_passives (.3f)
        "0.008",       // p_switching (.3f)
        "0.188",       // p_loss_total (.3f)
        "7.5",         // tj_rise_c (.1f)
        "14.2",        // gain_margin_db (.1f)
        "12500.0",     // f_crossover_hz (.1f)
        "1.85",        // thd_pct (.2f)
        "PASSED",      // stability_status
    ] {
        assert!(
            html.contains(token),
            "HTML missing metric token {token:?}"
        );
    }
}

#[test]
fn test_generate_html_report_missing_metrics_use_defaults() {
    let m = BTreeMap::new();
    let html = LabReportGenerator::generate_html_report(&m, None, None);
    // dmm_vdc defaults to 0.0 -> "0.0000"
    assert!(html.contains("0.0000 V"));
    // p_loss_total defaults to 1.0 -> "1.000"
    assert!(html.contains("1.000 W"));
    // stability_status defaults to "PASSED"
    assert!(html.contains("PASSED"));
}

#[test]
fn test_generate_html_report_no_unfilled_tokens() {
    let m = metrics();
    let html = LabReportGenerator::generate_html_report(&m, None, None);
    // Any token starting with '{' that remains indicates an unfilled placeholder
    // (but literal CSS/HTML braces are fine). Just check known tokens are gone.
    for token in [
        "{project_name}", "{t_str}", "{stability_status}", "{dmm_vdc}",
        "{dmm_vrms}", "{p2p_ripple_mv}", "{efficiency_pct}", "{sw_freq_khz}",
        "{phase_margin_deg}", "{p_cond_mosfet}", "{p_cond_mosfet_pct}",
        "{p_cond_diode}", "{p_cond_diode_pct}", "{p_cond_passives}",
        "{p_cond_passives_pct}", "{p_switching}", "{p_switching_pct}",
        "{p_loss_total}", "{tj_rise_c}", "{gain_margin_db}",
        "{f_crossover_hz}", "{thd_pct}",
    ] {
        assert!(!html.contains(token), "unfilled token {token:?} in HTML");
    }
}

#[test]
fn test_generate_html_report_writes_output_path() {
    let m = metrics();
    let tmp = std::env::temp_dir().join("wosp_report_generator_test.html");
    let tmp_str = tmp.to_string_lossy().to_string();
    let html = LabReportGenerator::generate_html_report(&m, None, Some(&tmp_str));
    assert!(std::path::Path::new(&tmp_str).exists());
    let written = std::fs::read_to_string(&tmp_str).unwrap();
    assert_eq!(written, html);
    let _ = std::fs::remove_file(&tmp_str);
}

#[test]
fn test_generate_html_report_structure() {
    let m = metrics();
    let html = LabReportGenerator::generate_html_report(&m, None, None);
    assert!(html.contains("<!DOCTYPE html>"));
    assert!(html.contains("<title>"));
    assert!(html.contains("WOWKISPICE Co-Simulation Test Report"));
    assert!(html.contains("Executive Summary & DC Precision Telemetry"));
    assert!(html.contains("Power & Thermal Dissipation Breakdown"));
    assert!(html.contains("Small-Signal Frequency Response & Stability Margins"));
    assert!(html.contains("</html>"));
}
