/*
 * parity_gpio_model.rs - Rust half of the gpio_model-parity battery.
 *
 * Computes a fixed battery of GPIO facts from
 * crates/wowkispice-core/src/gpio_model.rs and prints KEY<TAB>VALUE lines
 * for crates/parity/python/parity_gpio_model.py to diff against
 * bridge/gpio_model.py.
 *
 * Battery design: one fixed set of synthetic inputs, computed independently
 * on both sides. Keys are index-based (spice[i], desc[i], dir[i], ana[i],
 * freq[i]) plus named keys where helpful. Floats are compared as doubles;
 * strings are compared as text.
 */

use std::io::{BufWriter, Write};

use wowkispice_core::gpio_model::*;

fn enc_opt_f64(v: Option<f64>) -> String {
    match v {
        None => "None".to_string(),
        Some(x) => format_e10(x),
    }
}

/// Format an f64 like Python's `f"{v:.10e}"`: 10 decimal places, minimum
/// 2-digit exponent with explicit sign (e.g. `1.0000000000e+03`, `-1.71e-04`).
fn format_e10(v: f64) -> String {
    let s = format!("{:.10e}", v);
    if let Some(e_pos) = s.find('e') {
        let (base, exp) = s.split_at(e_pos);
        let exp_str = &exp[1..]; // skip 'e'
        let (sign, num) = if exp_str.starts_with('+') || exp_str.starts_with('-') {
            (&exp_str[..1], &exp_str[1..])
        } else {
            ("+", exp_str)
        };
        // Python uses minimum 2 exponent digits
        let num_padded = if num.len() >= 2 {
            num.to_string()
        } else {
            format!("0{}", num)
        };
        return format!("{}e{}{}", base, sign, num_padded);
    }
    s
}

fn enc_levels(levels: &[(f64, bool)]) -> String {
    let parts: Vec<String> = levels
        .iter()
        .map(|(t, l)| format!("{}:{}", enc_opt_f64(Some(*t)), if *l { "True" } else { "False" }))
        .collect();
    parts.join("|")
}

fn main() {
    let stdout = std::io::stdout();
    let lock = stdout.lock();
    let mut writer = BufWriter::new(lock);

    let mut out: Vec<(String, String)> = Vec::new();

    // ---- spice[i]: spice_card
    out.push((
        "spice[0]".to_string(),
        spice_card("static", Some(3.3), Some(1), None, None, None, 1e-7).unwrap(),
    ));
    out.push((
        "spice[1]".to_string(),
        spice_card("static", Some(3.3), Some(0), None, None, None, 1e-7).unwrap(),
    ));
    out.push((
        "spice[2]".to_string(),
        spice_card(
            "square",
            Some(3.3),
            None,
            Some(1000.0),
            Some(0.25),
            None,
            1e-7,
        )
        .unwrap(),
    ));
    out.push((
        "spice[3]".to_string(),
        spice_card("static", None, None, None, None, None, 1e-7).unwrap(),
    ));

    // ---- desc[i]: describe_pin
    out.push((
        "desc[0]".to_string(),
        describe_pin(
            "GPIO18", "square", Some(3.3), None, Some(1000.0), Some(0.5), None,
        )
        .unwrap(),
    ));
    out.push((
        "desc[1]".to_string(),
        describe_pin("GPIO5", "static", Some(3.3), Some(1), None, None, None)
            .unwrap(),
    ));

    // ---- dir[i]: pin_direction
    out.push(("dir[0]".to_string(), pin_direction("GND")));
    out.push(("dir[1]".to_string(), pin_direction("VCC")));
    out.push(("dir[2]".to_string(), pin_direction("A0")));
    out.push(("dir[3]".to_string(), pin_direction("ADC1")));
    out.push(("dir[4]".to_string(), pin_direction("GPIO18")));
    out.push(("dir[5]".to_string(), pin_direction("D13")));
    out.push(("dir[6]".to_string(), pin_direction("TX")));

    // ---- ana[i]: analyze_pin
    {
        let mut times = Vec::with_capacity(2000);
        let mut values = Vec::with_capacity(2000);
        for i in 0..2000 {
            times.push(i as f64 * 5e-6);
            values.push(if (i / 100) % 2 == 0 { 3.3 } else { 0.0 });
        }
        let info = analyze_pin(&times, &values, 1.65);
        out.push((
            "ana[0]".to_string(),
            format!(
                "points={}|transitions={}|duty={}|v_min={}|v_max={}|levels={}",
                info.points,
                info.transitions,
                enc_opt_f64(Some(info.duty)),
                enc_opt_f64(info.v_min),
                enc_opt_f64(info.v_max),
                enc_levels(&info.levels)
            ),
        ));
    }

    {
        let times: Vec<f64> = (0..10).map(|i| i as f64 * 1e-3).collect();
        let values = vec![3.3; 10];
        let info = analyze_pin(&times, &values, 1.65);
        out.push((
            "ana[1]".to_string(),
            format!(
                "points={}|transitions={}|duty={}|v_min={}|v_max={}|levels={}",
                info.points,
                info.transitions,
                enc_opt_f64(Some(info.duty)),
                enc_opt_f64(info.v_min),
                enc_opt_f64(info.v_max),
                enc_levels(&info.levels)
            ),
        ));
    }

    // ---- freq[i]: measured_frequency
    {
        let mut times = Vec::with_capacity(2000);
        let mut values = Vec::with_capacity(2000);
        for i in 0..2000 {
            times.push(i as f64 * 5e-6);
            values.push(if (i / 100) % 2 == 0 { 3.3 } else { 0.0 });
        }
        out.push((
            "freq[0]".to_string(),
            enc_opt_f64(measured_frequency(&times, &values, 1.65)),
        ));
    }

    {
        let times: Vec<f64> = (0..10).map(|i| i as f64 * 1e-3).collect();
        let values = vec![3.3; 10];
        out.push(("freq[1]".to_string(), enc_opt_f64(
            measured_frequency(&times, &values, 1.65),
        )));
    }

    for (key, value) in out {
        writeln!(writer, "{}\t{}", key, value).expect("stdout write");
    }
    writer.flush().expect("stdout flush");
}
