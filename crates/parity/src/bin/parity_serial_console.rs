/*
 * parity_serial_console.rs - Rust half of the serial_console-parity battery.
 *
 * Computes a fixed battery of UART-console facts from
 * crates/wowkispice-core/src/serial_console.rs and prints KEY<TAB>VALUE lines
 * for crates/parity/python/parity_serial_console.py to diff against
 * bridge/serial_console.py.
 *
 * Battery design: one fixed set of inputs, computed independently on both
 * sides. Keys are index-based (pu[i], sc[i], gs[i]) plus named keys.
 * Strings are compared as text; counts as integers.
 */

use std::io::{BufWriter, Write};

use wowkispice_core::serial_console::*;

fn main() {
    let stdout = std::io::stdout();
    let lock = stdout.lock();
    let mut writer = BufWriter::new(lock);

    let mut out: Vec<(String, String)> = Vec::new();

    // ---- pu[i]: parse_uart
    out.push((
        "pu[0]".to_string(),
        enc_lines(&parse_uart("")),
    ));
    out.push((
        "pu[1]".to_string(),
        enc_lines(&parse_uart("hello")),
    ));
    out.push((
        "pu[2]".to_string(),
        enc_lines(&parse_uart("a\nb\nc")),
    ));
    out.push((
        "pu[3]".to_string(),
        enc_lines(&parse_uart("a\r\nb\r\nc\r\n")),
    ));
    out.push((
        "pu[4]".to_string(),
        enc_lines(&parse_uart("a\r\nb\nc\r\nd")),
    ));
    out.push((
        "pu[5]".to_string(),
        enc_lines(&parse_uart("a\n\nb\n\n")),
    ));
    out.push((
        "pu[6]".to_string(),
        enc_lines(&parse_uart("  a  \n\tb\t\n")),
    ));
    out.push((
        "pu[7]".to_string(),
        enc_lines(&parse_uart("a\nb")),
    ));

    // ---- sc[i]: SerialConsole behavior
    {
        let mut c = SerialConsole::new(10);
        c.write("line1\nline2\nline3\n");
        out.push((
            "sc[0]".to_string(),
            format!("count={}|total_seen={}|text={}|dropped={}", c.count(), c.total_seen(), enc_text(&c.text()), c.dropped),
        ));
    }

    {
        let mut c = SerialConsole::new(3);
        c.write("a\nb\nc\nd\ne\n");
        out.push((
            "sc[1]".to_string(),
            format!("count={}|total_seen={}|dropped={}|text={}", c.count(), c.total_seen(), c.dropped, enc_text(&c.text())),
        ));
    }

    {
        let c = SerialConsole::default();
        out.push(("sc[2]".to_string(), format!("max_lines={}", c.max_lines)));
    }

    {
        let mut c = SerialConsole::new(0); // clamps to 1
        c.write("x\ny\nz\n");
        out.push((
            "sc[3]".to_string(),
            format!("count={}|total_seen={}|dropped={}|text={}", c.count(), c.total_seen(), c.dropped, enc_text(&c.text())),
        ));
    }

    // ---- gs[i]: grep + summary
    {
        let mut c = SerialConsole::new(10);
        c.write("Error: something failed\nWarning: be careful\ninfo: all good\n");
        let hits = c.grep("error");
        let s = c.summary();
        out.push((
            "gs[0]".to_string(),
            format!("hits={}|lines={}|dropped={}|truncated={}|max_lines={}",
                enc_lines(&hits), s.lines, s.dropped, if s.truncated { "True" } else { "False" }, s.max_lines),
        ));
    }

    {
        let mut c = SerialConsole::new(10);
        c.write("hello world\n");
        let hits = c.grep("xyz");
        let s = c.summary();
        out.push((
            "gs[1]".to_string(),
            format!("hits={}|lines={}|dropped={}|truncated={}|max_lines={}",
                enc_lines(&hits), s.lines, s.dropped, if s.truncated { "True" } else { "False" }, s.max_lines),
        ));
    }

    // ---- clear + text round-trip
    {
        let mut c = SerialConsole::new(10);
        c.write("line1\nline2\n");
        c.clear();
        out.push((
            "clear[0]".to_string(),
            format!("count={}|total_seen={}|text={}", c.count(), c.total_seen(), c.text()),
        ));
    }

    for (key, value) in out {
        writeln!(writer, "{}\t{}", key, value).expect("stdout write");
    }
    writer.flush().expect("stdout flush");
}

fn enc_text(s: &str) -> String {
    s.replace('\n', "\\n").replace('\t', "\\t").replace('\r', "\\r")
}

fn enc_lines(lines: &[String]) -> String {
    lines.join("||")
}
