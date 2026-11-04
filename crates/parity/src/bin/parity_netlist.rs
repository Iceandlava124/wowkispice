/*
 * parity_netlist.rs - Rust half of the netlist-parity battery.
 *
 * Computes the fixed battery from crates/wowkispice-core/src/netlist.rs and
 * prints KEY<TAB>VALUE lines for crates/parity/python/parity_netlist.py to
 * diff against bridge/ngspice_wrapper.py.  Key space is index-based
 * (line[i], cmd[i], sec[i], inc[i], deck[i]); value encoding is "OK:<value>"
 * or "ERR:<exception text>" so error MESSAGE parity is checked as text.
 *
 * The include battery needs real files: the Python driver writes the fixture
 * set (deterministic names under circuits/components) and hands over a
 * manifest of NAME<TAB>PATH lines as argv[1] — same paths both sides, so
 * every message embedding a fixture path compares byte-for-byte.  The
 * binary is invoked with cwd=REPO by the driver, so cwd-anchored candidates
 * resolve identically on both sides.
 *
 * The battery arrays below must stay IDENTICAL to the driver's LINE_CASES /
 * CMD_CASES / SEC_CASES / include templates — a drift surfaces immediately
 * as a python-only/rust-only key.
 */

use std::collections::BTreeMap;
use std::fs;
use std::io::{BufWriter, Write};

use wowkispice_core::netlist;
use wowkispice_core::pycompat::py_repr;

const LINE_CASES: &[&str] = &[
    "* comment",                                      // 0: passes through
    "",                                               // 1: blank passes
    "   ",                                            // 2: whitespace -> ""
    "+  .control",                                    // 3: one '+' strips
    "++ .control",                                    // 4: R3 gap
    ".control",                                       // 5: banned, no trailing space
    ".CONtrol",                                       // 6: banned, case-folded
    ".endc",                                          // 7
    ".ENDC extra",                                    // 8: regex branch
    ".tran 1n 10n",                                   // 9
    ".ac dec 5 1k 1MHz",                              // 10
    ".dc 0 1 0.1",                                    // 11
    ".op",                                            // 12
    ".model mymosfet MOSFET",                         // 13
    ".measure dc V(node)",                            // 14
    ".meas tran v(out) MAX",                          // 15: alias
    ".MEAS tran v(out) MIN",                          // 16: alias upper
    ".noise v(out) 1 100",                            // 17
    ".temp 27",                                       // 18
    ".save all",                                      // 19
    ".ic v(out)=0",                                   // 20
    ".nodeset v(node)=1",                             // 21
    ".step param X 1 10 1",                           // 22
    ".options noopiter",                              // 23
    ".param A=1",                                     // 24
    ".subckt X 1 2",                                  // 25
    ".ends",                                          // 26
    ".end",                                           // 27
    ".foo",                                           // 28: bare unknown passes
    ".foo bar",                                       // 29: unknown with args banned
    "run",                                            // 30
    "alter V1 = 5.0",                                 // 31
    "alter V1 = sin(t)",                              // 32
    "bg_run",                                         // 33
    "destroy",                                        // 34
    "R1 1 0 cmd(shell echo pwned)",                   // 35: banned command
    "R1 1 0 Cmd(big)",                                // 36: 'Cmd(' branch
    "* cmd(.control) inside comment",                 // 37: comment wins
    "V1 in 0 DC 1k",                                  // 38: element line
    ".include",                                       // 39: no file argument
    ".control ",                                      // 40: trailing space
    ".CONTROL reminder",                              // 41
    "\n.control",                                     // 42: LF-prefixed
    "  .control x",                                   // 43
];

const CMD_CASES: &[&str] = &[
    "run",                                            // 0
    "alter v1 = 5.0",                                 // 1
    "setplot tran1",                                  // 2
    "tran 1u 10m uic",                                // 3
    "   ",                                            // 4: empty command
    "shell echo hi",                                  // 5: banned verb
    "shell echo PWNED> C:\\wosp_parity_marker.txt", // 6: vector 2
    "source \"C:\\out.cir\"",                        // 7
    "write \"C:\\x.txt\" v(out)",                    // 8
    "wrdata \"C:\\x.txt\" v(out)",                   // 9
    "hardcopy \"C:\\x.png\" v(out)",                 // 10
    "run\nshell echo PWNED",                          // 11: separator \n
    "run; shell echo PWNED",                          // 12
    "run | shell echo PWNED",                         // 13
    "run `shell echo PWNED`",                         // 14
    "run $x",                                         // 15
    "run <in",                                        // 16
    "run >out",                                       // 17
    "RUN",                                            // 18: verb folded, text raw
    "alter&stuff",                                    // 19: verb wins first
    "stop  ",                                         // 20: trailing space strip
];

const SEC_CASES: &[&str] = &[
    "1n", "5m", "10u", "2m", "5g", "7t", "3p", "12f", // 0-7
    "meg", "300", "1u", "0",                          // 8-11
    "1.5k", ".5", "5.", "-3m", "+2M", "1e5", "2meg",  // 12-18
    "1e", "5mk", "abc", "1..0", "--1", "6G", "4H", "7N", // 19-26
    "8K", "1e400", "2e-3",                            // 27-29
];

struct Fixture {
    models: String,
    outside: String,
    missing: String,
    cycle: String,
    nest_a: String,
    bad: String,
}

fn load_manifest(path: &str) -> BTreeMap<String, String> {
    let text = fs::read_to_string(path).expect("manifest readable");
    let mut map: BTreeMap<String, String> = BTreeMap::new();
    for line in text.lines() {
        if line.is_empty() {
            continue;
        }
        let (name, val) = line
            .split_once('\t')
            .unwrap_or_else(|| panic!("manifest line lacks TAB: {:?}", line));
        map.insert(name.trim().to_string(), val.to_string());
    }
    map
}

fn fixture(map: &BTreeMap<String, String>, name: &str) -> String {
    match map.get(name) {
        Some(s) if !s.is_empty() => s.clone(),
        _ => panic!("manifest missing fixture {:?}", name),
    }
}

/// "OK:<value>" / "ERR:<msg>" encoders — same shape as the Python driver.
/// Values are wire-escaped by BOTH sides (backslash first, then \n \r \t),
/// because some payloads (separated commands) embed real newlines; the
/// driver compares the escaped forms, same text-equivalence.
fn esc(v: &str) -> String {
    v.replace('\\', "\\\\")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}

fn enc_line(line: &str) -> String {
    match netlist::sanitise_line(line) {
        Ok(s) => esc(&format!("OK:{}", s)),
        Err(e) => esc(&format!("ERR:{}", e.msg())),
    }
}

fn enc_cmd(command: &str) -> String {
    match netlist::validate_cmd(command) {
        Ok(s) => esc(&format!("OK:{}", s)),
        Err(e) => esc(&format!("ERR:{}", e.msg())),
    }
}

fn enc_sec(token: &str) -> String {
    match netlist::spice_seconds(token) {
        Some(v) => esc(&format!("OK:{}", py_repr(v))),
        None => "OK:None".to_string(),
    }
}

fn enc_deck(lines: &[String]) -> String {
    let owned: Vec<&str> = lines.iter().map(String::as_str).collect();
    match netlist::sanitise_deck(&owned) {
        Ok(deck) => {
            let tstop = match deck.tstop {
                Some(t) => py_repr(t),
                None => "None".to_string(),
            };
            esc(&format!(
                "OK:{}\u{1f}{}",
                deck.lines.join("\u{1f}").to_string(),
                tstop
            ))
        }
        Err(e) => esc(&format!("ERR:{}", e.msg())),
    }
}

fn enc_inc(line: &str) -> String {
    enc_line(line)
}

fn battery(fix: &Fixture) -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = Vec::new();
    for (i, case) in LINE_CASES.iter().enumerate() {
        out.push((format!("line[{}]", i), enc_line(case)));
    }
    for (i, case) in CMD_CASES.iter().enumerate() {
        out.push((format!("cmd[{}]", i), enc_cmd(case)));
    }
    for (i, case) in SEC_CASES.iter().enumerate() {
        out.push((format!("sec[{}]", i), enc_sec(case)));
    }
    // include battery — fixture-driven, same 12 templates as the driver
    let m = &fix.models;
    let inc_cases = [
        format!(".include \"{}\"", m),                                   // 0
        ".include circuits/components/models.lib".to_string(),           // 1
        format!(".include \"{}\"", fix.outside),                         // 2
        ".include \"circuits/components/../../../secrets.lib\"".to_string(), // 3
        ".include".to_string(),                                          // 4
        format!(".lib \"{}\"", m),                                       // 5
        format!(".lib \"{}\"", fix.outside),                             // 6
        format!(".include \"{}\"", fix.missing),                         // 7
        format!(".include \"{}\"", fix.cycle),                           // 8
        format!(".include \"{}\"", fix.bad),                             // 9
        format!(".include \"{}\"", fix.nest_a),                          // 10
        format!(".inc \"{}\"", m),                                       // 11
    ];
    for (i, case) in inc_cases.iter().enumerate() {
        out.push((format!("inc[{}]", i), enc_inc(case)));
    }
    // deck battery — sanitise_deck's domestic phase
    let decks: [Vec<String>; 5] = [
        vec![
            "* polarity".to_string(),
            "V1 in 0 DC 1".to_string(),
            "R1 in out 1k".to_string(),
            ".op".to_string(),
        ],
        vec!["* tran".to_string(), ".tran 1u 5m uic".to_string()],
        vec![
            "* bad".to_string(),
            format!(".include \"{}\"", fix.bad),
            "V1 in 0 DC 1".to_string(),
            "R1 in out 1k".to_string(),
            ".op".to_string(),
            ".end".to_string(),
        ],
        vec![],
        vec!["V1 in 0 DC 1".to_string(), ".ac dec 10 1 1e5".to_string()],
    ];
    for (i, deck) in decks.iter().enumerate() {
        out.push((format!("deck[{}]", i), enc_deck(deck)));
    }
    out
}

fn main() {
    let mut args = std::env::args();
    let _prog = args.next();
    let manifest = args.next().unwrap_or_else(|| {
        eprintln!("usage: parity_netlist <manifest-file>");
        std::process::exit(2);
    });

    let map = load_manifest(&manifest);
    let fix = Fixture {
        models: fixture(&map, "models"),
        outside: fixture(&map, "outside"),
        missing: fixture(&map, "missing"),
        cycle: fixture(&map, "cycle"),
        nest_a: fixture(&map, "nest_a"),
        bad: fixture(&map, "bad"),
    };

    let stdout = std::io::stdout();
    let lock = stdout.lock();
    let mut writer = BufWriter::new(lock);
    for (key, value) in battery(&fix) {
        writeln!(writer, "{}\t{}", key, value).expect("stdout write");
    }
    writer.flush().expect("stdout flush");
}
