/*
 * netlist.rs - port of the sanitiser half of bridge/ngspice_wrapper.py.
 *
 * Scope: everything in the Python wrapper that is pure policy over strings
 * and files: SPICE-number parsing (_spice_seconds, used by _find_tstop),
 * the directive allowlist, the include-family directory allowlist with its
 * recursive depth-capped content scan, the cmd() allowlist validator, and
 * the sanitiser itself (_strip_normalize / _is_banned_directive /
 * _is_banned_cmd / validate_cmd / _check_include_path / _scan_included_file /
 * _sanitise_line), plus load_circuit()'s domestic phase (sanitize every
 * line, then insert the title comment / ".end" and remember tstop).
 *
 * NOT ported here: the ctypes/ngspice.dll engine itself (NgSpiceEngine.__init__,
 * the callbacks, cmd() calling ngSpice_Command, ngSpice_Circ loading).  Those
 * are FFI concerns and belong to the R2 phase; they stay in the Python
 * wrapper, which keeps gating them.
 *
 * Error messages are part of the parity contract: they are transcribed from
 * the Python f-strings VERBATIM, including two quirks that look like bugs
 * and must stay:
 *
 *   - the Python sanitiser prefixes every rejection with
 *     "ngSpice_Circ rejected the untrusted netlist: ", and load_circuit()
 *     re-wraps a failed line with the same prefix again, so a deck that
 *     embeds a banned line loads-fails with the prefix twice.  Kept.
 *   - the inner content scan prefixes rejected lines as "{path}: {exc}",
 *     so an error coming from inside an included file carries the path of
 *     the file next to the prefix.  Kept.
 *
 * DOCUMENTED DEVIATIONS / APPROXIMATIONS (as in control_law.rs):
 *   - PROJECT_ROOT is anchored at THIS CRATE (crates/wowkispice-core, two
 *     directories up from its manifest dir) instead of bridge/../.. — the
 *     same repo root in the real tree, derived from the Rust file instead
 *     of the Python one.
 *   - path handling reproduces ntpath (os.path.join/realpath/isabs) on
 *     Windows: backslash separators, drive letters, \\?\ prefix stripped
 *     from fs::canonicalize, and a lexical '..'/'.' collapse for the
 *     nonexistent targets Python's realpath happily normalizes.  Symlink
 *     resolution for the nonexistent case is impossible by definition; for
 *     existing files fs::canonicalize does what GetFinalPathNameByHandle
 *     did for Python.
 *   - whitespace character classes are the table Python's str uses
 *     (space/tab/CR/LF/VT/FF/\x1c..\x1f plus Unicode White_Space), but the
 *     \S+ matcher inside the include-argument regex works byte-wise, so a
 *     byte pair decoding to a Unicode whitespace character would not stop
 *     it as Python's char-wise \S does.  Netlist lines and Windows paths
 *     here are ASCII; noted rather than modelled.
 *   - validate_cmd()'s TypeError arm (non-str command) cannot occur in Rust.
 */

use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use crate::pycompat::{py_lower_ascii, py_repr_str, py_trim};

/// Shared rejection prefix; every sanitiser error starts with it (and
/// load_circuit() chains a second copy — see the header note).
const PREFIX: &str = "ngSpice_Circ rejected the untrusted netlist: ";

/// A sanitiser rejection: `msg` is byte-for-byte what Python's
/// `str(RuntimeError(...))` would report.
#[derive(Debug, Clone)]
pub struct SanitiseError {
    pub msg: String,
}

impl SanitiseError {
    fn new(msg: impl Into<String>) -> Self {
        SanitiseError { msg: msg.into() }
    }
    pub fn msg(&self) -> &str {
        &self.msg
    }
}

impl fmt::Display for SanitiseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.msg)
    }
}

// ------------------------------------------------------------------
// Directive allowlist (case-insensitive, default: no path traversal)
// ------------------------------------------------------------------

const ALLOWED_DIRECTIVES: &[&str] = &[
    "tran", "ac", "dc", "op", "ic", "nodeset", "step", "options", "param",
    "model", "subckt", "ends", "measure", "meas", "print", "save", "temp",
    "end", "noise", "disto", "include", "lib", "inc",
];

/// J4: directory allowlist for .include / .lib / .inc targets.
///
/// Policy default: nothing outside these directories is ever allowed.  The
/// entries are exactly the library paths the real tests load
/// (tests/test_components_library.py:16 and :34 -> circuits/components/
/// models.lib).  PROJECT_ROOT is anchored at THE REPO ROOT derived from this
/// file's location, never at the process working directory, so decisions do
/// not move with cwd.
pub fn project_root() -> String {
    // Cargo manifest dir is <repo>/crates/wowkispice-core; two dirs up is
    // the same "bridge/.." the Python wrapper derives, un-canonicalized
    // exactly like Python's os.path.abspath result.
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default()
}

/// The real ALLOWED_INCLUDE_DIRS, as Python keeps them: os.path.join(PROJECT_ROOT, 'circuits', 'components')
/// — unresolved (realpath happens per decision inside `_check_include_path`).
pub fn allowed_include_dirs() -> Vec<String> {
    vec![os_join(&os_join(&project_root(), "circuits"), "components")]
}

/// Maximum nesting depth when scanning included files (3b finding: a
/// .control block inside an allowed included file executed for real, so the
/// scan is recursive with this cap; a self-including cycle trips it).
const INCLUDE_SCAN_DEPTH_LIMIT: usize = 5;

// ------------------------------------------------------------------
// Internal helpers
// ------------------------------------------------------------------

/// Python's str.strip() (ASCII table — see pycompat.py_trim).
fn py_strip(s: &str) -> &str {
    py_trim(s)
}

/// Python's str.isspace() per character (the table behind `\s` / strip /
/// splitlines boundaries).
fn is_py_space(c: char) -> bool {
    matches!(
        c,
        ' ' | '\t'
            | '\n'
            | '\r'
            | '\x0b'
            | '\x0c'
            | '\x1c'
            | '\x1d'
            | '\x1e'
            | '\x1f'
            | '\u{0085}'
            | '\u{00a0}'
    ) || c.is_whitespace()
}

/// Remove leading whitespace/tabs, normalise CRLF, handle '+' continuations.
fn strip_normalize(line: &str) -> String {
    // Normalise CRLF -> LF
    let line = line.replace("\r\n", "\n").replace('\r', "\n");
    // Strip leading whitespace and tabs
    let line = line.trim_start_matches([' ', '\t']);
    // '+' continuation: if the remaining text starts with '+', strip it
    if line.starts_with('+') {
        line[1..].trim_start_matches([' ', '\t']).to_string()
    } else {
        line.to_string()
    }
}

/// Return (banned, directive_name) after checking the normalised line
/// against the allowlist.
///
/// Order matters and is transcribed: the exact `.control` / `.endc` match
/// comes first so that a bare directive with NO trailing whitespace is also
/// rejected (the regex branch below needs a whitespace boundary); then the
/// dot-directive regex; anything that is not a dot-directive at all passes.
fn is_banned_directive(norm: &str) -> (bool, Option<String>) {
    // First, check for explicitly banned directives that might have no
    // trailing whitespace
    let norm_lower = py_strip(&py_lower_ascii(norm)).to_string();
    if norm_lower == ".control" || norm_lower == ".endc" {
        let name = norm_lower
            .trim_start_matches('.')
            .trim()
            .to_string();
        return (true, Some(name));
    }
    // Then, regex-based check for dot-directives with trailing whitespace:
    // ^[ \t]*\.([a-zA-Z]+)\s (case-insensitive)
    if let Some(directive) = match_dot_dir_re(norm) {
        if ALLOWED_DIRECTIVES.contains(&directive.as_str()) {
            return (false, None);
        }
        return (true, Some(directive));
    }
    // Not a dot-directive, not banned
    (false, None)
}

/// Emulation of DOT_DIR_RE = ^[ \t]*\.([a-zA-Z]+)\s — returns the lowercased
/// capture when the pattern matches.
fn match_dot_dir_re(s: &str) -> Option<String> {
    let mut chars = s.char_indices().peekable();
    while let Some(&(_, c)) = chars.peek() {
        if c == ' ' || c == '\t' {
            chars.next();
        } else {
            break;
        }
    }
    let (_, lead) = chars.peek().copied()?;
    if lead != '.' {
        return None;
    }
    chars.next();
    let mut word = String::new();
    for (_, c) in chars.by_ref() {
        if c.is_ascii_alphabetic() {
            word.push(c);
        } else {
            // ([a-zA-Z]+)\s — at least one letter, then a whitespace boundary
            if word.is_empty() {
                return None;
            }
            if is_py_space(c) {
                return Some(py_lower_ascii(&word));
            }
            return None;
        }
    }
    None // letters then end-of-input: no \s, no match (Python identical)
}

/// Return (banned, cmd_name) after checking the normalised line against the
/// cmd allowlist.  NOTE: the caller passes the raw normalised line (not
/// lowercased) — the Python code's comment claims otherwise, but its
/// behaviour compares `norm` itself, and that is what is transcribed; it is
/// exactly what makes the "R1 1 0 cmd(...)" rejection fire.
fn is_banned_cmd(norm: &str) -> (bool, Option<String>) {
    if !CMD_ALLOWED.contains(&norm) {
        let first = norm.split_whitespace().next().unwrap_or("");
        let cmd_name = if first.is_empty() { None } else { Some(first.to_string()) };
        return (true, cmd_name);
    }
    (false, None)
}

// ------------------------------------------------------------------
// validate_cmd — the cmd() path into ngspice's command language
// ------------------------------------------------------------------

/// Legitimate cmd() commands that the code sends through ngSpice_Command,
/// enumerated by grepping every `.cmd(` call site under bridge/, ui/, tests/
/// and tools/ (job R4-01).  Nothing else is sent.
const CMD_ALLOWED: &[&str] = &["run", "bg_run", "reset", "destroy", "alter", "stop", "setplot", "tran"];

/// Return the command text if it is an allowed ngspice command, else raise.
///
/// Rules, in order: the verb (first token) must be in Cmd_ALLOWED; the whole
/// string must then be free of control and redirection characters.
pub fn validate_cmd(command: &str) -> Result<String, SanitiseError> {
    // (Python raises TypeError for non-str; the Rust type system rules
    // that arm out.)
    let text = py_strip(command).to_string();
    if text.is_empty() {
        return Err(SanitiseError::new("ngSpice_Command rejected: empty command"));
    }
    // Verb first: for `shell ...` the actionable reason is the verb, not the
    // redirection character that happens to follow it.
    let verb = py_lower_ascii(text.split_whitespace().next().unwrap_or(""));
    if !CMD_ALLOWED.contains(&verb.as_str()) {
        return Err(SanitiseError::new(format!(
            "ngSpice_Command rejected the command (not on allowlist: {}) @cmd: {}",
            py_repr_str(&verb),
            text
        )));
    }
    // CMD_FORBIDDEN_CHARS = [\r\n;|&`$<>]
    let offending = text.chars().find(|c| matches!(c, '\r' | '\n' | ';' | '|' | '&' | '`' | '$' | '<' | '>'));
    if let Some(offending) = offending {
        return Err(SanitiseError::new(format!(
            "ngSpice_Command rejected the command (character {} not permitted) @cmd: {}",
            py_repr_str(&offending.to_string()),
            text
        )));
    }
    Ok(text)
}

// ------------------------------------------------------------------
// The include-argument regex
// ------------------------------------------------------------------

/// Emulation of INCLUDE_ARG_RE =
///   ^[ \t]*\.([a-zA-Z]+)(?:[ \t]+(?:"([^"]*)"|'([^']*)'|(\S+)))?
/// (case-insensitivity irrelevant for the word lookup used: caller lowers).
struct IncArgMatch {
    word: String,
    /// byte spans of groups 2 (dquoted), 3 (squoted), 4 (bare) when present
    g2: Option<(usize, usize)>,
    g3: Option<(usize, usize)>,
    g4: Option<(usize, usize)>,
}

fn match_include_arg(s: &str) -> Option<IncArgMatch> {
    let b = s.as_bytes();
    let mut i = 0;
    while i < b.len() && (b[i] == b' ' || b[i] == b'\t') {
        i += 1;
    }
    if i >= b.len() || b[i] != b'.' {
        return None;
    }
    i += 1;
    let wstart = i;
    while i < b.len() && b[i].is_ascii_alphabetic() {
        i += 1;
    }
    if i == wstart {
        return None;
    }
    let word = s[wstart..i].to_string();

    // The optional argument part: [ \t]+ then one of the three forms; if the
    // alternation fails after whitespace was consumed, the whole optional
    // group matches empty (regex backtracking) — spans simply stay None.
    let ws_start = i;
    let mut k = i;
    while k < b.len() && (b[k] == b' ' || b[k] == b'\t') {
        k += 1;
    }
    let (mut g2, mut g3, mut g4): (Option<(usize, usize)>, Option<(usize, usize)>, Option<(usize, usize)>)
        = (None, None, None);
    if k > ws_start && k < b.len() {
        // alt 1: "([^"]*)"
        if b[k] == b'"' {
            let mut e = k + 1;
            while e < b.len() && b[e] != b'"' {
                e += 1;
            }
            if e < b.len() {
                g2 = Some((k + 1, e));
            }
        // alt 2: '([^']*)'
        } else if b[k] == b'\'' {
            let mut e = k + 1;
            while e < b.len() && b[e] != b'\'' {
                e += 1;
            }
            if e < b.len() {
                g3 = Some((k + 1, e));
            }
        // alt 3: (\S+) — byte-wise: stops at the Python whitespace table
        } else if !is_py_space_byte(b[k]) {
            let mut e = k;
            while e < b.len() && !is_py_space_byte(b[e]) {
                e += 1;
            }
            g4 = Some((k, e));
        }
    }

    Some(IncArgMatch { word, g2, g3, g4 })
}

fn is_py_space_byte(c: u8) -> bool {
    matches!(
        c,
        b' ' | b'\t' | b'\n' | b'\r' | 0x0b | 0x0c | 0x1c | 0x1d | 0x1e | 0x1f
    )
}

// ------------------------------------------------------------------
// Include-path validation and recursive content scan
// ------------------------------------------------------------------

/// Validate a .include/.lib/.inc target and scan its content.
///
/// A relative argument is tried both against the process cwd and against the
/// repo root; a candidate INSIDE the allowlist is preferred over one outside
/// it, so a foreign cwd with a look-alike path cannot win.  The matched
/// candidate is realpath'd before the comparison, so '..' and symlinks
/// collapse first and cannot escape the allowlist.  Returns the validated
/// absolute path, which sanitise_line rewrites into the netlist line.
fn check_include_path(raw: &str, directive: &str, depth: usize) -> Result<String, SanitiseError> {
    if raw.is_empty() {
        return Err(SanitiseError::new(format!(
            "{}.{} with no file argument @line",
            PREFIX, directive
        )));
    }
    if depth >= INCLUDE_SCAN_DEPTH_LIMIT {
        return Err(SanitiseError::new(format!(
            "{}.{} nesting exceeds depth {} @line: {}",
            PREFIX, directive, INCLUDE_SCAN_DEPTH_LIMIT, raw
        )));
    }
    let mut candidates: Vec<String> = Vec::new();
    if py_isabs(raw) {
        candidates.push(raw.to_string());
    } else {
        candidates.push(os_join(&py_getcwd(), raw));
        candidates.push(os_join(&project_root(), raw));
    }
    let allowed: Vec<String> = allowed_include_dirs().iter().map(|d| py_realpath(d)).collect();
    let mut inside: Vec<String> = Vec::new();
    for cand in &candidates {
        let resolved = py_realpath(cand);
        for d in &allowed {
            let child_marker = format!("{}{}", d, OS_SEP);
            if resolved == *d || resolved.starts_with(&child_marker) {
                inside.push(resolved.clone());
                break;
            }
        }
    }
    // Prefer an allowlisted candidate that exists as a file; if one resolved
    // inside the allowlist but cannot be read, say so rather than falling
    // through to the outside error (clearer and fail-closed).
    for resolved in &inside {
        if py_isfile(resolved) {
            scan_included_file(resolved, depth + 1)?;
            return Ok(resolved.clone());
        }
    }
    if !inside.is_empty() {
        return Err(SanitiseError::new(format!(
            "{}.{} file not found or unreadable @line: {}",
            PREFIX, directive, inside[0]
        )));
    }
    Err(SanitiseError::new(format!(
        "{}.{} outside allowed directories @line: {}",
        PREFIX, directive, raw
    )))
}

/// Apply the same line rules to every line of an included file, recursively
/// up to the depth cap, re-raising rejections with the file path so the
/// error names where the banned content lives.
fn scan_included_file(path: &str, depth: usize) -> Result<(), SanitiseError> {
    let content: String = match fs::read(path) {
        Ok(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
        Err(exc) => {
            // Python: open() raising OSError is re-raised as RuntimeError
            // "...included file unreadable: {path} ({exc})".  Python formats
            //NotFoundError as "[Errno 2] No such file or directory: '<path>'";
            // other kinds avoid being invented here — they cannot be hit
            // through the isfile()-gated call path in normal use.
            let py_text = if exc.kind() == std::io::ErrorKind::NotFound {
                format!("[Errno 2] No such file or directory: '{}'", path)
            } else {
                format!("[Errno 5] Input/output error: '{}'", path)
            };
            return Err(SanitiseError::new(format!(
                "{}included file unreadable: {} ({})",
                PREFIX, path, py_text
            )));
        }
    };
    for line in py_splitlines(&content) {
        if py_strip(&line).is_empty() {
            continue;
        }
        if let Err(exc) = sanitise_line_depth(&line, depth) {
            return Err(SanitiseError::new(format!(
                "{}{}: {}",
                PREFIX, path, exc.msg
            )));
        }
    }
    Ok(())
}

// ------------------------------------------------------------------
// The sanitiser itself
// ------------------------------------------------------------------

/// Process a single netlist line through the sanitiser (depth 0).
///
/// Raises SanitiseError with the Python error message verbatim if the line
/// contains a banned directive or command.  Returns the normalised line if
/// safe.
pub fn sanitise_line(line: &str) -> Result<String, SanitiseError> {
    sanitise_line_depth(line, 0)
}

/// `_sanitise_line(line, depth=depth)`: the include scan calls this with the
/// recursion depth for nested includes.
pub fn sanitise_line_depth(line: &str, depth: usize) -> Result<String, SanitiseError> {
    let mut norm = strip_normalize(line);

    // Skip blank lines and comment lines (starting with *); they pass through
    if norm.is_empty() || norm.starts_with('*') {
        return Ok(norm);
    }

    // Check for banned dot-directives
    let (banned, directive) = is_banned_directive(&norm);
    if banned {
        let d = directive.unwrap_or_default();
        return Err(SanitiseError::new(format!(
            "{}banned directive @line: .{}",
            PREFIX, d
        )));
    }

    // .include / .lib / .inc: pass the allowlist only after the file argument
    // resolves inside ALLOWED_INCLUDE_DIRS, its content passes the same rules
    // (recursive, depth-capped), and the line is rewritten to the validated
    // absolute path (3c: ngspice then reads exactly what was checked,
    // whatever the cwd).
    if let Some(inc) = match_include_arg(&norm) {
        if matches!(
            py_lower_ascii(&inc.word).as_str(),
            "include" | "lib" | "inc"
        ) {
            let dir = py_lower_ascii(&inc.word);
            // raw = g2 or g3 or g4 or '' — Python truthiness: an EMPTY
            // quoted argument ("") falls through to the next alternative.
            let raw: String = inc
                .g2
                .and_then(|(a, b)| pick_span(&norm, a, b))
                .or_else(|| inc.g3.and_then(|(a, b)| pick_span(&norm, a, b)))
                .or_else(|| inc.g4.and_then(|(a, b)| pick_span(&norm, a, b)))
                .unwrap_or_default();
            let resolved = check_include_path(&raw, &dir, depth)?;
            // grp = 2 if g2 is not None else 3 if g3 is not None else 4
            let grp = if inc.g2.is_some() {
                2
            } else if inc.g3.is_some() {
                3
            } else {
                4
            };
            let (gs, ge) = match grp {
                2 => inc.g2.unwrap(),
                3 => inc.g3.unwrap(),
                _ => inc.g4.unwrap(),
            };
            let replacement = if grp != 4 || !resolved.contains(' ') {
                resolved.clone()
            } else {
                format!("\"{}\"", resolved)
            };
            norm = format!("{}{}{}", &norm[..gs], replacement, &norm[ge..]);
        }
    }

    // Check for banned cmd() references in netlist content.  Legitimate code
    // sends: run, bg_run, reset, destroy, alter.  Look for 'cmd(' pattern
    // (case-insensitive) in the normalised line.  (Python also re-tests
    // 'Cmd(' in norm — redundant since .lower() already folded it, and
    // transcribed anyway.)
    if py_lower_ascii(&norm).contains("cmd(") || norm.contains("Cmd(") {
        let (banned_cmd, _cmd_name) = is_banned_cmd(&norm);
        if banned_cmd {
            return Err(SanitiseError::new(format!(
                "{}banned command in netlist @line",
                PREFIX
            )));
        }
    }

    // Re-check after normalization (in case '+' continuation changed things)
    norm = strip_normalize(&norm);
    let (banned, directive) = is_banned_directive(&norm);
    if banned {
        let d = directive.unwrap_or_default();
        return Err(SanitiseError::new(format!(
            "{}banned directive @line: .{}",
            PREFIX, d
        )));
    }

    Ok(norm)
}

/// Byte-span slice helper for the include-argument groups.
fn pick_span(s: &str, a: usize, b: usize) -> Option<String> {
    if a == b {
        return Some(String::new()); // empty quoted arg: present but falsy
    }
    Some(s[a..b].to_string())
}

// ------------------------------------------------------------------
// load_circuit()'s domestic phase
// ------------------------------------------------------------------

/// The pure result of load_circuit(): sanitised lines ready to hand to
/// ngspice, plus the deck's tstop (None without a .tran card).
#[derive(Debug)]
pub struct SanitisedDeck {
    pub lines: Vec<String>,
    pub tstop: Option<f64>,
}

/// Sanitise every line before passing to ngspice, rejecting untrusted
/// directives, file-output commands, and shell commands.  This is
/// load_circuit() minus the ngSpice_Circ call (FFI stays in Python):
/// - skip completely empty lines,
/// - sanitise each line (rejections re-wrapped with ANOTHER copy of the
///   prefix — verbatim Python, see the header note),
/// - ensure the netlist has a title comment and .end marker,
/// - remember the transient stop time so a failed analysis can be told
///   apart from a reached one (R5).
pub fn sanitise_deck(netlist_lines: &[&str]) -> Result<SanitisedDeck, SanitiseError> {
    let mut sanitised: Vec<String> = Vec::new();
    for line in netlist_lines {
        // Skip completely empty lines (they are implicit)
        if py_strip(line).is_empty() {
            continue;
        }
        let sline = sanitise_line(line).map_err(|exc| {
            SanitiseError::new(format!("{}{}", PREFIX, exc.msg))
        })?;
        sanitised.push(sline);
    }

    // Ensure the netlist has a title comment and .end marker
    if sanitised.is_empty() || !sanitised[0].starts_with('*') {
        sanitised.insert(0, "* WOWKISPICE circuit".to_string());
    }
    if !sanitised.iter().any(|l| py_lower_ascii(l) == ".end") {
        sanitised.push(".end".to_string());
    }

    let tstop = find_tstop(&sanitised);

    Ok(SanitisedDeck { lines: sanitised, tstop })
}

/// Stop time of the deck's .tran card, or None when it has none.
///
/// Parsed from the sanitised deck; SPICE suffixes are converted
/// (`.tran 10u 5m uic` -> 0.005).
pub fn find_tstop(lines: &[String]) -> Option<f64> {
    for raw in lines {
        let parts: Vec<&str> = raw.split_whitespace().collect();
        if !parts.is_empty()
            && py_lower_ascii(parts[0]) == ".tran"
            && parts.len() >= 3
        {
            return spice_seconds(parts[2]);
        }
    }
    None
}

// ------------------------------------------------------------------
// SPICE number parsing
// ------------------------------------------------------------------

/// One .tran argument in seconds, or None if it is not a SPICE number.
/// SPICE_NUMBER_RE = ^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(meg|[tgkmunpf])?$
/// 'm' is milli, so 'meg' is the only spelling meaning mega (tried first).
pub fn spice_seconds(token: &str) -> Option<f64> {
    let t = py_strip(token);
    let (mant, scale) = match_spice_number_re(t)?;
    Some(mant * scale)
}

/// Hand-rolled emulation of SPICE_NUMBER_RE, returning
/// (parsed number, scale multiplier).
fn match_spice_number_re(t: &str) -> Option<(f64, f64)> {
    let chars: Vec<char> = t.chars().collect();
    let b = &chars[..];
    let mut i = 0;

    // optional sign
    if i < b.len() && (b[i] == '+' || b[i] == '-') {
        i += 1;
    }

    // mantissa: \d+\.?\d* | \.\d+
    let mut digits_before = 0usize;
    let mut digits_after = 0usize;
    let mut has_dot = false;
    while i < b.len() && b[i].is_ascii_digit() {
        i += 1;
        digits_before += 1;
    }
    if i < b.len() && b[i] == '.' {
        has_dot = true;
        i += 1;
        while i < b.len() && b[i].is_ascii_digit() {
            i += 1;
            digits_after += 1;
        }
    }
    // alternation check: either the whole-digits form or dot-leading digits
    if digits_before == 0 && (!has_dot || digits_after == 0) {
        return None;
    }

    // optional exponent: [eE][+-]?\d+ — a malformed 'e' makes the exponent
    // group NOT participate, leaving 'e...' unmatched; since the suffix
    // cannot eat 'e', the overall match fails (Python backtracking result).
    let mut exp_valid = false;
    if i < b.len() && (b[i] == 'e' || b[i] == 'E') {
        let mut j = i + 1;
        if j < b.len() && (b[j] == '+' || b[j] == '-') {
            j += 1;
        }
        let mut any = false;
        while j < b.len() && b[j].is_ascii_digit() {
            j += 1;
            any = true;
        }
        if any {
            exp_valid = true;
            i = j;
        }
    }
    // a bare 'e' that did not form a valid exponent kills the overall match
    if i < b.len() && (b[i] == 'e' || b[i] == 'E') && !exp_valid {
        return None;
    }

    // numeric text so far: sign + mantissa (+ validated exponent)
    let lead: String = b[..i].iter().collect();

    // optional suffix: meg (first, because 'm' != meg) or [tgkmunpf]
    let mut scale = 1.0;
    if i < b.len() {
        let tail: String = b[i..].iter().collect();
        let lower = py_lower_ascii(&tail);
        if lower == "meg" {
            scale = 1e6;
            i += 3;
        } else if lower.len() == 1
            && matches!(lower.as_str(), "t" | "g" | "k" | "m" | "u" | "n" | "p" | "f")
        {
            scale = match lower.as_str() {
                "t" => 1e12,
                "g" => 1e9,
                "k" => 1e3,
                "m" => 1e-3,
                "u" => 1e-6,
                "n" => 1e-9,
                "p" => 1e-12,
                "f" => 1e-15,
                _ => unreachable!(),
            };
            i += 1;
        }
    }
    if i != b.len() {
        return None; // trailing junk: no overall match (Python identical)
    }

    // Rust's f64 FromStr rejects "12." and ".5" which Python's float()
    // accepts; normalise to the shapes it parses before the conversion.
    let mut numeric = lead;
    if numeric.ends_with('.') {
        numeric.push('0');
    }
    if matches!(numeric.chars().next(), Some('.') ) {
        numeric = format!("0{}", numeric);
    } else if (numeric.starts_with('-') || numeric.starts_with('+')) && numeric.len() > 1 && numeric.as_bytes()[1] == b'.' {
        numeric = format!("{}0{}",
            numeric.chars().next().unwrap(),
            &numeric[1..]);
    }
    let val: f64 = numeric.parse::<f64>().ok()?;
    Some((val, scale))
}

// ------------------------------------------------------------------
// ntpath helpers (os.path semantics on Windows)
// ------------------------------------------------------------------

const OS_SEP: char = '\\';

/// ntpath.splitdrive()
fn split_drive(s: &str) -> (&str, &str) {
    let b = s.as_bytes();
    if b.len() >= 2 && b[1] == b':' {
        return (&s[..2], &s[2..]);
    }
    // UNC: \\server\share\... — the device part ends at the second
    // separator
    if b.len() >= 4 && b[0] == b'\\' && b[1] == b'\\' {
        let mut i = 2;
        while i < b.len() && b[i] != b'\\' {
            i += 1;
        }
        if i < b.len() {
            let mut j = i + 1;
            while j < b.len() && b[j] != b'\\' {
                j += 1;
            }
            return (&s[..j], &s[j..]);
        }
    }
    ("", s)
}

/// ntpath.isabs()
fn py_isabs(s: &str) -> bool {
    let (d, r) = split_drive(s);
    s == d || (!r.is_empty() && (r.starts_with('\\') || r.starts_with('/')))
}

/// ntpath.join(), restricted to the argument shapes the sanitiser feeds:
/// absolute-with-drive replaces; a rooted argument keeps the drive; the rest
/// is a plain concatenation.
fn os_join(a: &str, b: &str) -> String {
    if py_isabs(b) {
        return b.to_string();
    }
    if b.starts_with('\\') || b.starts_with('/') {
        let (d, _) = split_drive(a);
        if !d.is_empty() {
            return format!("{}{}", d, b);
        }
    }
    if a.ends_with('\\') || a.ends_with('/') {
        format!("{}{}", a, b)
    } else {
        format!("{}{}{}", a, OS_SEP, b)
    }
}

/// os.getcwd() (lossy on the rare non-Unicode cwd).
fn py_getcwd() -> String {
    std::env::current_dir()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default()
}

/// os.path.isfile()
fn py_isfile(path: &str) -> bool {
    fs::metadata(path).map(|m| m.is_file()).unwrap_or(false)
}

/// os.path.expanduser("~") on Windows: USERPROFILE.
fn py_expanduser_tilde() -> String {
    std::env::var("USERPROFILE").unwrap_or_else(|_| String::new())
}

/// os.path.realpath(): canonicalize (resolving symlinks and the on-disk
/// casing like GetFinalPathNameByHandle), strip the \\?\ prefix Rust adds;
/// for paths that do not exist (Python's realpath still normalizes those)
/// fall back to a lexical '..'/'.' collapse on the drive-anchored form.
pub fn py_realpath(path: &str) -> String {
    let cand: PathBuf = Path::new(path).to_path_buf();
    let abs: PathBuf = if py_isabs(path) {
        cand
    } else {
        PathBuf::from(py_getcwd()).join(&cand)
    };
    match fs::canonicalize(&abs) {
        Ok(resolved) => strip_unc_prefix(resolved.to_string_lossy().as_ref()),
        Err(_) => lexical_normalize(abs.to_string_lossy().as_ref()),
    }
}

/// \\?\C:\... -> C:\... ; \\?\UNC\server\share -> \\server\share
fn strip_unc_prefix(p: &str) -> String {
    if let Some(rest) = p.strip_prefix(r"\\?\UNC\") {
        return format!("\\\\{}", rest.replace('\\', OS_SEP.to_string().as_str()));
    }
    if let Some(rest) = p.strip_prefix(r"\\?\") {
        return rest.replace('/', "\\");
    }
    p.replace('/', "\\")
}

/// Lexical normalization for paths that do not exist on disk (the case
/// Python's realpath handles through ntpath.normpath): collapse '.', '..'
/// and repeated separators; keep the drive/root intact.
fn lexical_normalize(p: &str) -> String {
    let bytes = p.as_bytes();
    let (prefix_len, has_drive, sep_after_drive) = if bytes.len() >= 2 && bytes[1] == b':' {
        let sep = bytes.len() >= 3 && (bytes[2] == b'\\' || bytes[2] == b'/');
        (if sep { 3 } else { 2 }, true, sep)
    } else if !bytes.is_empty() && (bytes[0] == b'\\' || bytes[0] == b'/') {
        (1, false, true)
    } else {
        (0, false, false)
    };

    let mut comps: Vec<&str> = Vec::new();
    for comp in p[prefix_len..].split(['/', '\\']) {
        match comp {
            "" | "." => {}
            ".." => {
                comps.pop();
            }
            other => comps.push(other),
        }
    }

    if has_drive {
        let drive = p[..2].to_string(); // "C:"
        if sep_after_drive {
            let mut out = drive;
            out.push(OS_SEP);
            out.push_str(&comps.join(&OS_SEP.to_string()));
            out
        } else {
            // drive-relative tail stays attached ("C:foo" -> "C:foo")
            if comps.is_empty() {
                drive
            } else {
                format!("{}{}", drive, comps.join(&OS_SEP.to_string()))
            }
        }
    } else if prefix_len == 1 {
        // rooted, drive-less: "\foo\bar"
        format!("\\\\{}", comps.join(&OS_SEP.to_string()))
    } else {
        comps.join(&OS_SEP.to_string())
    }
}

/// Python's str.splitlines(): $\n \r\n \r \x0b \x0c \x1c \x1d \x1e \x85
/// U+2028 U+2029 boundaries (the ones reachable in practice).
pub fn py_splitlines(content: &str) -> Vec<String> {
    let mut lines: Vec<String> = Vec::new();
    let mut cur = String::new();
    let mut chars = content.chars().peekable();
    while let Some(c) = chars.next() {
        let is_break = matches!(
            c,
            '\n' | '\r' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{0085}' | '\u{2028}' | '\u{2029}'
        );
        if !is_break {
            cur.push(c);
            continue;
        }
        // \r\n is a single boundary
        if c == '\r' && chars.peek() == Some(&'\n') {
            chars.next();
        }
        lines.push(std::mem::take(&mut cur));
        continue;
    }
    lines.push(cur);
    lines
}

pub fn expanduser_tilde() -> String {
    py_expanduser_tilde()
}

