/*
 * pycompat.rs - helpers that reproduce specific CPython behaviours.
 *
 * Shared by every module because the alternatives are worse: each module
 * carrying its own copy of Python's round() and repr() is exactly the drift
 * this port exists to avoid.
 *
 * Three behaviours are subtle enough to need pinning (all verified against
 * CPython during the C port, which they are transcribed from):
 *
 *   round().  Python's round() on a float is round-half-to-EVEN; the obvious
 *   Rust equivalents (f64::round, i64 casts) round half AWAY from zero.  At
 *   an exact .5 the two disagree, and the ADC mapping lands on exact .5 at
 *   half an LSB.
 *
 *   repr().  Python's repr of a float is the SHORTEST string that
 *   round-trips, always with a decimal point or an exponent (0.0 renders as
 *   "0.0"), fixed notation for 1e-4 <= |x| < 1e16 and exponential outside.
 *   Rust's {} Display is shortest-round-trip too but never uses exponential
 *   notation, so it is not interchangeable.  Error messages embed these
 *   strings and the parity harness compares them as text.
 *
 *   format(x, 'g').  6 significant digits, trailing zeros stripped, fixed
 *   notation when -4 <= exponent < 6 and exponential otherwise (with a
 *   signed, at-least-2-digit exponent).  Rust has no %g.
 *
 * KNOWN LIMITATION (noted, not modelled): the 'g' formatter rounds the
 * shortest round-trip digits rather than the exact binary value, so an exact
 * tie at the 6th significant digit could round differently from CPython.
 * No value the law or its describe() strings can produce reaches that tie;
 * the parity battery is what would show it if that ever stopped being true.
 */

/// Python's `round(x)` on a float -> integer, round-half-to-even.
///
/// Returns 0 for NaN (Python raises instead; no caller feeds NaN, and
/// swallowing it keeps the clamp arithmetic well-defined) and saturates for
/// infinity, where C used LONG_MAX/LONG_MIN.
pub fn round_half_even(x: f64) -> i64 {
    if x.is_nan() {
        return 0;
    }
    if x.is_infinite() {
        return if x > 0.0 { i64::MAX } else { i64::MIN };
    }
    let f = x.floor();
    let frac = x - f;
    let base = f as i64;
    if frac > 0.5 {
        base + 1
    } else if frac < 0.5 {
        base
    } else if base % 2 == 0 {
        base
    } else {
        base + 1
    }
}

/// Python's `round(x, 4)`, used to report recovered target/hysteresis.
///
/// CPython rounds the true decimal value of the double, not (x*1e4) rounded
/// and divided back; the two differ only on an exact tie at the 5th decimal,
/// which the recovered thresholds never reach.  Noted rather than modelled.
pub fn round4(x: f64) -> f64 {
    round_half_even(x * 10000.0) as f64 / 10000.0
}

/// Python's `repr(float)` (and `str(float)`, which is the same thing).
pub fn py_repr(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".to_string() } else { "-inf".to_string() };
    }
    let neg = x.is_sign_negative();
    let a = x.abs();

    // Shortest round-trip digits in scientific form: "d.ddddde±X".
    let sci = format!("{:e}", a);
    let (mant, exp) = match sci.split_once('e') {
        Some((m, e)) => (m.to_string(), e.parse::<i32>().unwrap_or(0)),
        None => (sci.clone(), 0),
    };
    let digits: String = mant.chars().filter(|c| *c != '.').collect();

    let body = if exp >= -4 && exp < 16 {
        // Fixed notation: place the point, pad with zeros, strip trailing
        // zeros but always keep one digit after the point ("100.0", never
        // "100").
        let mut int_part;
        let mut frac_part;
        if exp >= 0 {
            let need = (exp as usize) + 1;
            if digits.len() >= need {
                int_part = digits[..need].to_string();
                frac_part = digits[need..].to_string();
            } else {
                int_part = digits.clone();
                int_part.push_str(&"0".repeat(need - digits.len()));
                frac_part = String::new();
            }
        } else {
            int_part = "0".to_string();
            frac_part = format!("{}{}", "0".repeat((-(exp + 1)) as usize), digits);
        }
        while frac_part.ends_with('0') {
            frac_part.pop();
        }
        if frac_part.is_empty() {
            format!("{}.0", int_part)
        } else {
            format!("{}.{}", int_part, frac_part)
        }
    } else {
        // Exponential: strip the mantissa's trailing zeros but keep the
        // point when more than one digit remains ("9.999999999999999e-06",
        // "1.2e-05"; a single digit stays bare: "1e-05"), then a signed,
        // at-least-2-digit exponent.
        let mut m = digits;
        while m.len() > 1 && m.ends_with('0') {
            m.pop();
        }
        if m.ends_with('.') {
            m.pop();
        }
        let mant = if m.len() > 1 {
            format!("{}.{}", &m[..1], &m[1..])
        } else {
            m.clone()
        };
        let sign = if exp < 0 { '-' } else { '+' };
        format!("{}e{}{:02}", mant, sign, exp.abs())
    };

    if neg {
        format!("-{}", body)
    } else {
        body
    }
}

/// Python's `f"{x:g}"` (6 significant digits, %g rules).
pub fn py_g(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".to_string() } else { "-inf".to_string() };
    }
    if x == 0.0 {
        // %g says "0", and the sign of zero is not shown.
        return "0".to_string();
    }
    let neg = x.is_sign_negative();
    let a = x.abs();

    // Round to 6 significant digits first; the parsed exponent is that of
    // the ROUNDED value, so a bump (9.99999e5 -> 1.00000e6) is handled.
    let sci = format!("{:.5e}", a);
    let (mant, exp) = match sci.split_once('e') {
        Some((m, e)) => (m.to_string(), e.parse::<i32>().unwrap_or(0)),
        None => (sci.clone(), 0),
    };
    let digits: String = mant.chars().filter(|c| *c != '.').collect();

    let body = if exp >= -4 && exp < 6 {
        // Fixed with exactly 6 significant digits, then strip.
        let mut int_part;
        let mut frac_part;
        if exp >= 0 {
            let need = (exp as usize) + 1;
            if digits.len() >= need {
                int_part = digits[..need].to_string();
                frac_part = digits[need..].to_string();
            } else {
                int_part = digits.clone();
                int_part.push_str(&"0".repeat(need - digits.len()));
                frac_part = String::new();
            }
        } else {
            int_part = "0".to_string();
            frac_part = format!("{}{}", "0".repeat((-(exp + 1)) as usize), digits);
        }
        while frac_part.ends_with('0') {
            frac_part.pop();
        }
        if frac_part.is_empty() {
            int_part
        } else {
            format!("{}.{}", int_part, frac_part)
        }
    } else {
        // Same point rule as py_repr above: "1.23456e-05" keeps the dot
        // when more than one digit survives the strip.
        let mut m = digits;
        while m.len() > 1 && m.ends_with('0') {
            m.pop();
        }
        if m.ends_with('.') {
            m.pop();
        }
        let mant = if m.len() > 1 {
            format!("{}.{}", &m[..1], &m[1..])
        } else {
            m.clone()
        };
        let sign = if exp < 0 { '-' } else { '+' };
        format!("{}e{}{:02}", mant, sign, exp.abs())
    };

    if neg {
        format!("-{}", body)
    } else {
        body
    }
}

/// Python's `repr(str)` for the strings this port can produce: ASCII text,
/// escaped backslash, `\\n`/`\\r`/`\\t`, other control and DEL characters as
/// `\\xHH`, and single quotes — except `'`-containing/`"`-free strings, which
/// CPython renders double-quoted.  Non-ASCII printable characters pass
/// through unchanged, the same as CPython for the common ranges.
///
/// Needed wherever an error message embeds `%r` of user text (first use: the
/// netlist sanitiser's validate_cmd()).
pub fn py_repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::new();
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 || (c as u32) == 0x7f => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c if c as u32 == quote as u32 => {
                out.push('\\');
                out.push(c);
            }
            _ => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// Python's `str.strip()`: leading/trailing whitespace.  ASCII only — the
/// non-ASCII whitespace Python also strips (\\x85, U+00A0) is outside this
/// port's contract; netlist and firmware sources are ASCII.
pub fn py_trim(s: &str) -> &str {
    s.trim_matches(|c: char| {
        c == ' '
            || c == '\t'
            || c == '\n'
            || c == '\r'
            || c == '\x0b'
            || c == '\x0c'
            || c == '\x1c'
            || c == '\x1d'
            || c == '\x1e'
            || c == '\x1f'
    })
}

/// ASCII `str.lower()`.  Python's is Unicode-aware; every fold here is on
/// ASCII identifiers and directive names, where the two agree.
pub fn py_lower_ascii(s: &str) -> String {
    s.chars()
        .map(|c| if c.is_ascii_uppercase() { c.to_ascii_lowercase() } else { c })
        .collect()
}

/// `os.path.basename()` as Python applies it on Windows: accepts both
/// separators.
pub fn py_basename(path: &str) -> &str {
    match path.rsplit(|c| c == '/' || c == '\\').next() {
        Some(rest) => rest,
        None => path,
    }
}
