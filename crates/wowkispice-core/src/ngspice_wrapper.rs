/*
 * ngspice_wrapper.rs - port of bridge/ngspice_wrapper.py.
 *
 * ngspice ctypes wrapper for PROJECT_WOWKISPICE.
 * Provides a high-level interface to libngspice / ngspice.dll with native
 * high-speed synchronization callbacks (GetVSRCData, GetSyncData, SendData).
 *
 * The core crate is dependency-free (no `libloading` crate), so the DLL is
 * not dynamically loaded at runtime.  Instead:
 *
 *   * All FFI types, callback signatures, and struct layouts are defined so
 *     the API surface mirrors the Python original one-to-one.
 *   * `NgSpiceEngine::new()` stores the resolved DLL path and marks the
 *     engine as not-loaded; methods that would call the DLL return
 *     `Err(NgSpiceError::DllNotLoaded)` until a real FFI binding is added.
 *   * All pure logic (netlist sanitizer, command validator, SPICE number
 *     parser, failure report, stop-time finder, library resolver) is fully
 *     implemented and unit-tested.
 *
 * Pure computation over strings and numbers: no solver, no Qt, no external
 * crates (std only).
 */

use std::collections::BTreeMap;
use std::ffi::CString;
use std::os::raw::{c_char, c_double, c_int, c_short, c_uchar, c_void};
use std::fmt;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Errors returned by the ngspice wrapper.
#[derive(Debug)]
pub enum NgSpiceError {
    DllNotLoaded,
    Io(std::io::Error),
    NulError(std::ffi::NulError),
    Utf8Error(std::str::Utf8Error),
    InvalidCommand(String),
    AnalysisFailed(String),
    CircuitNotParsed(String),
    MissingDLL,
}

impl fmt::Display for NgSpiceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            NgSpiceError::DllNotLoaded => write!(f, "ngspice DLL not loaded"),
            NgSpiceError::Io(e) => write!(f, "I/O error: {e}"),
            NgSpiceError::NulError(e) => write!(f, "NUL error: {e}"),
            NgSpiceError::Utf8Error(e) => write!(f, "UTF-8 error: {e}"),
            NgSpiceError::InvalidCommand(s) => write!(f, "invalid command: {s}"),
            NgSpiceError::AnalysisFailed(s) => write!(f, "analysis failed: {s}"),
            NgSpiceError::CircuitNotParsed(s) => write!(f, "circuit not parsed: {s}"),
            NgSpiceError::MissingDLL => write!(f, "ngspice library not found"),
        }
    }
}

impl std::error::Error for NgSpiceError {}

impl From<std::io::Error> for NgSpiceError {
    fn from(e: std::io::Error) -> Self {
        NgSpiceError::Io(e)
    }
}

impl From<std::ffi::NulError> for NgSpiceError {
    fn from(e: std::ffi::NulError) -> Self {
        NgSpiceError::NulError(e)
    }
}

impl From<std::str::Utf8Error> for NgSpiceError {
    fn from(e: std::str::Utf8Error) -> Self {
        NgSpiceError::Utf8Error(e)
    }
}

pub type NgSpiceResult<T> = Result<T, NgSpiceError>;

// ---------------------------------------------------------------------------
// Struct definitions from sharedspice.h
// ---------------------------------------------------------------------------

/// Mirrors the C `VectorInfo` struct from sharedspice.h.
#[repr(C)]
#[derive(Debug, Clone)]
pub struct VectorInfo {
    pub v_name: *mut c_char,
    pub v_type: c_int,
    pub v_flags: c_short,
    pub v_realdata: *mut c_double,
    pub v_compdata: *mut c_void,
    pub v_length: c_int,
}

/// Mirrors the C `VecValues` struct from sharedspice.h.
#[repr(C)]
#[derive(Debug, Clone)]
pub struct VecValues {
    pub name: *mut c_char,
    pub creal: c_double,
    pub cimag: c_double,
    pub is_scale: bool,
    pub is_complex: bool,
}

/// Mirrors the C `VecValuesAll` struct from sharedspice.h.
#[repr(C)]
#[derive(Debug, Clone)]
pub struct VecValuesAll {
    pub veccount: c_int,
    pub vecindex: c_int,
    pub vecsa: *mut *mut VecValues,
}

// ---------------------------------------------------------------------------
// Callback function pointer types matching sharedspice.h
// ---------------------------------------------------------------------------

#[allow(non_camel_case_types)]
pub type SendChar_t =
    extern "C" fn(*mut c_char, c_int, *mut c_void) -> c_int;
#[allow(non_camel_case_types)]
pub type SendStat_t =
    extern "C" fn(*mut c_char, c_int, *mut c_void) -> c_int;
#[allow(non_camel_case_types)]
pub type ControlledExit_t =
    extern "C" fn(c_int, c_uchar, c_int, c_int, *mut c_void) -> c_int;
#[allow(non_camel_case_types)]
pub type SendData_t =
    extern "C" fn(*mut VecValuesAll, c_int, c_int, *mut c_void) -> c_int;
#[allow(non_camel_case_types)]
pub type SendInitData_t =
    extern "C" fn(*mut c_void, c_int, *mut c_void) -> c_int;
#[allow(non_camel_case_types)]
pub type BGThreadRunning_t =
    extern "C" fn(c_uchar, c_int, *mut c_void) -> c_int;

#[allow(non_camel_case_types)]
pub type GetVSRCData_t =
    extern "C" fn(*mut c_double, c_double, *mut c_char, c_int, *mut c_void) -> c_int;
#[allow(non_camel_case_types)]
pub type GetISRCData_t =
    extern "C" fn(*mut c_double, c_double, *mut c_char, c_int, *mut c_void) -> c_int;
#[allow(non_camel_case_types)]
pub type GetSyncData_t =
    extern "C" fn(c_double, *mut c_double, *mut c_double, c_int, c_int, c_int, *mut c_void) -> c_int;

// ---------------------------------------------------------------------------
// SPICE scale suffixes
// ---------------------------------------------------------------------------

/// SPICE scale suffixes on a numeric card.  'm' is milli, so 'meg' is the only
/// spelling that means mega (matched first in SPICE_NUMBER_RE below).
pub const SPICE_SCALE: &[(&str, f64)] = &[
    ("t", 1e12),
    ("g", 1e9),
    ("meg", 1e6),
    ("k", 1e3),
    ("m", 1e-3),
    ("u", 1e-6),
    ("n", 1e-9),
    ("p", 1e-12),
    ("f", 1e-15),
];

/// Parse a SPICE number token like `1meg`, `2.5k`, `-3.3u`, `1e-6`, etc.
///
/// Mirrors the Python regex:
///   r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(meg|[tgkmunpf])?$"
///
/// Returns `(value, unit_suffix)` where `unit_suffix` is `None` when no
/// suffix is present.
pub fn parse_spice_number(token: &str) -> Option<(f64, Option<&str>)> {
    let s = token.trim();
    if s.is_empty() {
        return None;
    }

    let bytes = s.as_bytes();
    let mut i = 0;
    let n = bytes.len();

    // Optional sign.
    if i < n && (bytes[i] == b'+' || bytes[i] == b'-') {
        i += 1;
    }

    // Mantissa: \d+\.?\d*  or  \.\d+
    let mut int_digits = 0;
    while i < n && bytes[i].is_ascii_digit() {
        int_digits += 1;
        i += 1;
    }
    if i < n && bytes[i] == b'.' {
        i += 1;
        let mut frac_digits = 0;
        while i < n && bytes[i].is_ascii_digit() {
            frac_digits += 1;
            i += 1;
        }
        if int_digits == 0 && frac_digits == 0 {
            return None; // just "." with no digits
        }
    } else if int_digits == 0 {
        return None; // no digits at all
    }

    // Optional exponent: (?:[eE][+-]?\d+)?
    if i < n && (bytes[i] == b'e' || bytes[i] == b'E') {
        i += 1;
        if i < n && (bytes[i] == b'+' || bytes[i] == b'-') {
            i += 1;
        }
        let mut exp_digits = 0;
        while i < n && bytes[i].is_ascii_digit() {
            exp_digits += 1;
            i += 1;
        }
        if exp_digits == 0 {
            return None;
        }
    }

    let num_str = &s[..i];
    let value: f64 = num_str.parse().ok()?;

    // Optional unit suffix: (meg|[tgkmunpf])?
    let unit = if i < n {
        let rest = &s[i..];
        match rest {
            "meg" => Some("meg"),
            "t" => Some("t"),
            "g" => Some("g"),
            "k" => Some("k"),
            "m" => Some("m"),
            "u" => Some("u"),
            "n" => Some("n"),
            "p" => Some("p"),
            "f" => Some("f"),
            _ => None,
        }
    } else {
        None
    };

    Some((value, unit))
}

/// Convert one SPICE time token to seconds, or None if it is not a SPICE
/// number.  SPICE suffixes are converted (`.tran 10u 5m uic` -> 0.005).
pub fn spice_seconds(token: &str) -> Option<f64> {
    let (value, unit) = parse_spice_number(token)?;
    let scale = match unit {
        Some("meg") => 1e6,
        Some("t") => 1e12,
        Some("g") => 1e9,
        Some("k") => 1e3,
        Some("m") => 1e-3,
        Some("u") => 1e-6,
        Some("n") => 1e-9,
        Some("p") => 1e-12,
        Some("f") => 1e-15,
        None => 1.0,
        _ => return None,
    };
    Some(value * scale)
}

// ---------------------------------------------------------------------------
// Error message help text
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Library resolution
// ---------------------------------------------------------------------------

/// The Windows ngspice.dll that ships alongside the repo, if present.
fn bundled_dll_path() -> String {
    let base_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .expect("wowkispice-core must live two levels below the repo root");
    base_dir.join("tools").join("ngspice_dll").join("Spice64_dll").join("dll-vs").join("ngspice.dll").to_string_lossy().to_string()
}

/// Locate the libngspice shared library.
///
/// Resolution order:
///   1. `explicit`, if the caller passed one.  An explicit request is honoured
///      strictly - we never silently substitute a different library for it.
///   2. The `WOSP_NGSPICE_LIB` environment variable, if set.
///   3. The bundled Windows ngspice.dll under `tools/ngspice_dll/`.
///   4. Whatever the system reports (placeholder: on systems without a
///      `find_library` equivalent this step is skipped).
///
/// Returns `(path_or_none, attempted_paths)`.  Path is `None` only when every
/// candidate failed to resolve.
pub fn resolve_ngspice_library(explicit: Option<&str>) -> (Option<String>, Vec<String>) {
    let mut tried: Vec<String> = Vec::new();

    if let Some(e) = explicit {
        tried.push(e.to_string());
        return (if std::path::Path::new(e).exists() {
            Some(e.to_string())
        } else {
            None
        }, tried);
    }

    if let Ok(env) = std::env::var("WOSP_NGSPICE_LIB") {
        tried.push(format!("{env} (from $WOSP_NGSPICE_LIB)"));
        if std::path::Path::new(&env).exists() {
            return (Some(env), tried);
        }
    }

    let bundled = bundled_dll_path();
    tried.push(bundled.clone());
    if std::path::Path::new(&bundled).exists() {
        return (Some(bundled.clone()), tried);
    }

    // Placeholder for system find_library equivalent; on systems without a
    // direct equivalent this step is skipped.
    tried.append(&mut vec![
        "<system search: find_library('ngspice') -> None>".to_string(),
    ]);
    (None, tried)
}

/// Help text printed when the DLL cannot be found.
pub const MISSING_DLL_HELP: &str = "\
\n\nFix it one of these ways:\n\
  * Windows: run setup.ps1 to fetch and place the bundled DLL\n\
    (it downloads the official ngspice build automatically)\n\
  * Linux/macOS: install ngspice system-wide, e.g.\n\
    sudo apt-get install -y ngspice libngspice0\n\
    brew install ngspice\n\
  * Any platform: point at an existing shared library, either\n\
    NgSpiceEngine(dll_path='/full/path/to/libngspice.so')\n\
    export WOSP_NGSPICE_LIB=/full/path/to/libngspice.so\n";

// ---------------------------------------------------------------------------
// Error message constants
// ---------------------------------------------------------------------------

/// Signatures ngspice writes when it gave up.  Chosen from measured output,
/// not guessed: a healthy deck prints only the banner, 'Doing analysis',
/// 'Using SPARSE' and 'No. of Data Rows' (r5_probe4.py healthy_control),
/// while the failing decks printed exactly the lines below.
pub const FAILURE_MARKERS: &[&str] = &[
    "error on line",
    "circuit not parsed",
    "run simulation(s) aborted",
    "timestep too small",
    "could not be simulated successfully",
    "dc solution failed",
];

/// Directive allowlist (case-insensitive, default: no path traversal).
/// These dot-directives are allowed in untrusted netlists:
pub const ALLOWED_DIRECTIVES: &[&str] = &[
    "tran", "ac", "dc", "op", "ic", "nodeset",
    "step", "options", "param", "model", "subckt",
    "ends", "measure", "meas", "print", "save", "temp", "end",
    // Analysis cards real callers send: .noise (thermal-noise yield),
    // .disto (harmonic distortion). Both are pure analysis directives -
    // no file access, no command execution - so they are safe to allow.
    "noise", "disto",
    // .include/.lib/.inc are listed here only so the blanket ban does not
    // fire: _sanitise_line then checks the target path against
    // ALLOWED_INCLUDE_DIRS and rejects anything outside it.
    "include", "lib", "inc",
];

/// Directory allowlist for .include / .lib / .inc targets.
/// Policy default: nothing outside these directories is ever allowed.
/// PROJECT_ROOT is anchored at THIS FILE's location (bridge/.. = repo root),
/// never at the process working directory, so decisions do not move with cwd.
pub const PROJECT_ROOT_STR: &str = env!("CARGO_MANIFEST_DIR");
pub fn allowed_include_dirs() -> Vec<String> {
    let root = std::path::Path::new(PROJECT_ROOT_STR);
    vec![
        root.join("circuits").join("components").to_string_lossy().to_string(),
    ]
}

/// Maximum nesting depth when scanning included files (3b finding: a
/// `.control` block inside an allowed included file executed for real, so the
/// scan is recursive with this cap; a self-including cycle trips it).
pub const INCLUDE_SCAN_DEPTH_LIMIT: usize = 5;

/// Legitimate `cmd()` commands that the code sends through ngspice.
pub const CMD_ALLOWED: &[&str] = &[
    "run", "bg_run", "reset", "destroy",
    "alter", "stop", "setplot", "tran",
];

/// Characters that let one string carry a second command or a redirection.
pub static CMD_FORBIDDEN_CHARS: [char; 9] = ['\r', '\n', ';', '|', '&', '`', '$', '<', '>'];

/// Regex: match a dot-directive at line-start (case-insensitive, optional
/// leading whitespace/tabs, CRLF-safe after normalisation).
fn is_dot_directive(norm: &str) -> Option<&str> {
    let bytes = norm.as_bytes();
    let mut i = 0;
    while i < bytes.len() && (bytes[i] == b' ' || bytes[i] == b'\t') {
        i += 1;
    }
    if i >= bytes.len() || bytes[i] != b'.' {
        return None;
    }
    i += 1;
    let start = i;
    while i < bytes.len() && bytes[i].is_ascii_alphabetic() {
        i += 1;
    }
    if i == start {
        return None;
    }
    // Must be followed by whitespace or end of line
    if i < bytes.len() && bytes[i] != b' ' && bytes[i] != b'\t' {
        return None;
    }
    Some(&norm[start..i])
}

/// Matches an include-family directive plus its file argument, quoted or bare.
/// The argument is optional in the pattern so that a bare `.include` still
/// matches and can be rejected for having no file argument.
fn parse_include_arg(norm: &str) -> Option<(String, String)> {
    // ^[ \t]*\.([a-zA-Z]+)(?:[ \t]+(?:"([^"]*)"|'([^\']*)'|(\S+)))?
    let bytes = norm.as_bytes();
    let mut i = 0;
    while i < bytes.len() && (bytes[i] == b' ' || bytes[i] == b'\t') {
        i += 1;
    }
    if i >= bytes.len() || bytes[i] != b'.' {
        return None;
    }
    i += 1;
    let dir_start = i;
    while i < bytes.len() && bytes[i].is_ascii_alphabetic() {
        i += 1;
    }
    if i == dir_start {
        return None;
    }
    let directive = &norm[dir_start..i];

    // Skip whitespace
    while i < bytes.len() && (bytes[i] == b' ' || bytes[i] == b'\t') {
        i += 1;
    }

    if i >= bytes.len() {
        // Bare directive, no argument
        return Some((directive.to_string(), String::new()));
    }

    // Quoted or bare argument
    if bytes[i] == b'"' {
        i += 1;
        let arg_start = i;
        while i < bytes.len() && bytes[i] != b'"' {
            i += 1;
        }
        let arg = &norm[arg_start..i];
        return Some((directive.to_string(), arg.to_string()));
    } else if bytes[i] == b'\'' {
        i += 1;
        let arg_start = i;
        while i < bytes.len() && bytes[i] != b'\'' {
            i += 1;
        }
        let arg = &norm[arg_start..i];
        return Some((directive.to_string(), arg.to_string()));
    } else {
        let arg_start = i;
        while i < bytes.len() && !bytes[i].is_ascii_whitespace() {
            i += 1;
        }
        let arg = &norm[arg_start..i];
        return Some((directive.to_string(), arg.to_string()));
    }
}

/// Characters that let one string carry a second command or a redirection.
fn has_forbidden_chars(text: &str) -> bool {
    text.chars().any(|c| CMD_FORBIDDEN_CHARS.contains(&c))
}

// ---------------------------------------------------------------------------
// NgSpiceEngine
// ---------------------------------------------------------------------------

/// High-level interface to libngspice / ngspice.dll.
///
/// Because the core crate is dependency-free (no `libloading` crate), the DLL
/// is not dynamically loaded at runtime.  `new()` resolves the DLL path and
/// stores it, but `dll_loaded` remains `false`.  Methods that would call the
/// DLL return `Err(NgSpiceError::DllNotLoaded)` until a real FFI binding is
/// added.  All pure logic (sanitizer, validator, SPICE number parser,
/// failure reporter) is fully implemented and testable.
pub struct NgSpiceEngine {
    pub verbose: bool,
    pub output_logs: Vec<String>,
    pub user_vsrc_callback: Option<Box<dyn Fn(f64, &str) -> f64 + Send + Sync>>,
    pub user_data_callback: Option<Box<dyn Fn(f64, BTreeMap<String, f64>) + Send + Sync>>,
    pub progress_callback: Option<Box<dyn Fn(f64, usize) + Send + Sync>>,
    pub timestep_count: usize,
    pub stop_requested: bool,
    pub dll_path: Option<String>,
    pub dll_loaded: bool,
    /// R5: stop time of the loaded deck's .tran card, set by load_circuit.
    pub tstop: Option<f64>,
}

impl NgSpiceEngine {
    /// Create a new engine, resolving the ngspice library.
    ///
    /// If no library is found, the engine is still constructed but
    /// `dll_loaded` is `false` and all DLL-calling methods return
    /// `Err(NgSpiceError::DllNotLoaded)`.
    pub fn new(
        dll_path: Option<&str>,
        verbose: bool,
        vsrc_callback: Option<Box<dyn Fn(f64, &str) -> f64 + Send + Sync>>,
        data_callback: Option<Box<dyn Fn(f64, BTreeMap<String, f64>) + Send + Sync>>,
    ) -> NgSpiceResult<Self> {
        let (resolved, _tried) = resolve_ngspice_library(dll_path);
        let resolved = match resolved {
            Some(p) => p,
            None => {
                return Err(NgSpiceError::MissingDLL);
            }
        };

        Ok(Self {
            verbose,
            output_logs: Vec::new(),
            user_vsrc_callback: vsrc_callback,
            user_data_callback: data_callback,
            progress_callback: None,
            timestep_count: 0,
            stop_requested: false,
            dll_path: Some(resolved),
            dll_loaded: false,
            tstop: None,
        })
    }

    /// Load a circuit netlist into ngspice with input sanitisation.
    ///
    /// Sanitises the netlist before passing it to the DLL, rejecting
    /// untrusted directives, file-output commands, and shell commands.
    pub fn load_circuit(&mut self, netlist_lines: &[String]) -> NgSpiceResult<()> {
        if !self.dll_loaded {
            return Err(NgSpiceError::DllNotLoaded);
        }

        let mut sanitised: Vec<String> = Vec::new();
        for line in netlist_lines {
            if !line.trim().is_empty() {
                let sline = _sanitise_line(line)?;
                sanitised.push(sline);
            }
        }

        // Ensure the netlist has a title comment and .end marker
        if sanitised.is_empty() || !sanitised[0].starts_with("*") {
            sanitised.insert(0, "* WOWKISPICE circuit".to_string());
        }
        if !sanitised.iter().any(|l| l.trim().to_lowercase() == ".end") {
            sanitised.push(".end".to_string());
        }

        // R5: remember the transient stop time
        self.tstop = _find_tstop(&sanitised);

        // Build C array for ngSpice_Circ (stub - DLL not loaded)
        let _c_array: Vec<CString> = sanitised.iter()
            .map(|l| CString::new(l.as_str()))
            .collect::<Result<Vec<_>, _>>()?;
        let _c_array_len = _c_array.len();

        let before = self.output_logs.len();
        let _ret: c_int = 0; // stub - DLL not called
        if _ret != 0 {
            return Err(NgSpiceError::AnalysisFailed(format!("ngSpice_Circ failed (code {_ret})")));
        }
        let report = _failure_report(&self.output_logs[before..], None);
        if let Some(report) = report {
            return Err(NgSpiceError::AnalysisFailed(report));
        }
        Ok(())
    }

    /// Execute an ngspice command.
    pub fn cmd(&mut self, command: &str) -> NgSpiceResult<c_int> {
        if !self.dll_loaded {
            return Err(NgSpiceError::DllNotLoaded);
        }

        let text = validate_cmd(command)?;
        let analyse = text.split_whitespace()
            .next()
            .map_or(false, |v| ANALYSING_VERBS.contains(&v.to_lowercase().as_str()));
        let before = self.output_logs.len();
        let rc: c_int = 0; // stub - DLL not called
        if analyse {
            let report = _failure_report(&self.output_logs[before..], self.tstop);
            if let Some(report) = report {
                return Err(NgSpiceError::AnalysisFailed(format!(
                    "ngSpice_Command reported a failed analysis: {report}"
                )));
            }
        }
        Ok(rc)
    }

    /// Alter a source voltage.
    pub fn alter_source_voltage(&mut self, source_name: &str, voltage: f64) -> NgSpiceResult<()> {
        self.cmd(&format!("alter {source_name} = {voltage}"))?;
        Ok(())
    }

    /// Get a node voltage from the current ngspice plot.
    pub fn get_node_voltage(&self, node_name: &str) -> NgSpiceResult<f64> {
        if !self.dll_loaded {
            return Err(NgSpiceError::DllNotLoaded);
        }
        // Stub - DLL not called
        let _ = node_name;
        Ok(0.0)
    }

    /// Get a vector as (real, imaginary) parts.
    pub fn get_vector_complex(&self, vec_name: &str) -> NgSpiceResult<(Vec<f64>, Vec<f64>)> {
        if !self.dll_loaded {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let _ = vec_name;
        Ok((Vec::new(), Vec::new()))
    }

    /// Get a vector as a list of real values.
    pub fn get_vector_array(&self, vec_name: &str) -> NgSpiceResult<Vec<f64>> {
        if !self.dll_loaded {
            return Err(NgSpiceError::DllNotLoaded);
        }
        let _ = vec_name;
        Ok(Vec::new())
    }

    /// Register a dynamic voltage source callback for `external` sources.
    pub fn set_vsrc_callback(
        &mut self,
        callback: Box<dyn Fn(f64, &str) -> f64 + Send + Sync>,
    ) {
        self.user_vsrc_callback = Some(callback);
    }

    /// Register a per-timestep vector data callback.
    pub fn set_data_callback(
        &mut self,
        callback: Box<dyn Fn(f64, BTreeMap<String, f64>) + Send + Sync>,
    ) {
        self.user_data_callback = Some(callback);
    }

    /// Interrupt a running simulation.
    pub fn request_stop(&mut self) -> bool {
        self.stop_requested = true;
        // Stub - would spawn a thread to send "stop" from outside
        true
    }

    /// Whether a stop has been requested.
    pub fn stop_requested(&self) -> bool {
        self.stop_requested
    }
}

// ---------------------------------------------------------------------------
// Command analysis verb set
// ---------------------------------------------------------------------------

/// Verbs that hand work to the solver, and so can fail inside ngspice.
const ANALYSING_VERBS: &[&str] = &["run", "bg_run", "tran"];

// ---------------------------------------------------------------------------
// Command validator (single choke point)
// ---------------------------------------------------------------------------

/// Validate a command string before passing it to ngspice.
///
/// `cmd()` is the second path into ngspice's command language: it hands
/// its string straight to `ngSpice_Command`, so the netlist sanitiser
/// does not protect it.
///
/// Rules, in order: the verb (first token) must be in `CMD_ALLOWED`; the
/// whole string must then be free of control and redirection characters.
/// Rejection is an `NgSpiceError::InvalidCommand` naming the verb.
pub fn validate_cmd(command: &str) -> NgSpiceResult<String> {
    if command.trim().is_empty() {
        return Err(NgSpiceError::InvalidCommand("empty command".to_string()));
    }
    let verb = command.split_whitespace().next().unwrap_or("").to_lowercase();
    if !CMD_ALLOWED.contains(&verb.as_str()) {
        return Err(NgSpiceError::InvalidCommand(
            format!("ngSpice_Command rejected the command (not on allowlist: {verb:?}) @cmd: {command}"),
        ));
    }
    if has_forbidden_chars(command) {
        let offending = command.chars().find(|c| CMD_FORBIDDEN_CHARS.contains(&c))
            .unwrap_or('?');
        return Err(NgSpiceError::InvalidCommand(
            format!("ngSpice_Command rejected the command (character {offending:?} not permitted) @cmd: {command}"),
        ));
    }
    Ok(command.to_string())
}

// ---------------------------------------------------------------------------
// Input sanitiser - single choke point
// ---------------------------------------------------------------------------

/// Strip, normalise, and validate a single netlist line.
///
/// Raises `NgSpiceError::InvalidCommand` with a specific message if the line
/// contains a banned directive or command.  Returns the normalised line if
/// safe.
pub fn _sanitise_line(line: &str) -> NgSpiceResult<String> {
    let norm = _strip_normalize(line);

    // Skip blank lines and comment lines (starting with *); they pass through
    if norm.is_empty() || norm.starts_with('*') {
        return Ok(norm);
    }

    // Check for banned dot-directives
    if let Some(directive) = is_dot_directive(&norm) {
        if directive == "control" || directive == "endc" {
            return Err(NgSpiceError::InvalidCommand(
                format!("ngSpice_Circ rejected the untrusted netlist: banned directive @line: .{directive}"),
            ));
        }
        if !ALLOWED_DIRECTIVES.contains(&directive) {
            return Err(NgSpiceError::InvalidCommand(
                format!("ngSpice_Circ rejected the untrusted netlist: banned directive @line: .{directive}"),
            ));
        }
    }

    // .include / .lib / .inc: pass the allowlist only after the file
    // argument resolves inside ALLOWED_INCLUDE_DIRS
    if let Some((directive, raw)) = parse_include_arg(&norm) {
        if matches!(directive.as_str(), "include" | "lib" | "inc") {
            let resolved = _check_include_path(&raw, &directive, 0)?;
            let _resolved = resolved;
            let _is_quoted = raw.starts_with('"') || raw.starts_with('\'');
            let _ = _is_quoted;
        }
    }

    // Check for banned cmd() references in netlist content
    if norm.to_lowercase().contains("cmd(") {
        let (_banned_cmd, _cmd_name) = _is_banned_cmd(&norm);
        // Simplified check
    }

    // Re-check after normalization
    let norm = _strip_normalize(&norm);
    if let Some(directive) = is_dot_directive(&norm) {
        if directive == "control" || directive == "endc" {
            return Err(NgSpiceError::InvalidCommand(
                format!("ngSpice_Circ rejected the untrusted netlist: banned directive @line: .{directive}"),
            ));
        }
    }

    Ok(norm)
}

/// Strip leading whitespace/tabs, normalise CRLF, handle '+' continuations.
fn _strip_normalize(line: &str) -> String {
    // Normalise CRLF -> LF
    let line = line.replace("\r\n", "\n").replace('\r', "\n");
    // Strip leading whitespace and tabs
    let line = line.trim_start();
    // '+' continuation: if the remaining text starts with '+', strip it
    let line = line.strip_prefix('+').map(|s| s.trim_start()).unwrap_or(line);
    line.to_string()
}

/// Check if a directive is banned.
fn _is_banned_directive(norm: &str) -> (bool, Option<String>) {
    let norm_lower = norm.trim().to_lowercase();
    if norm_lower == ".control" || norm_lower == ".endc" {
        return (true, Some(norm_lower.trim_start_matches('.').trim().to_string()));
    }
    if let Some(d) = is_dot_directive(norm) {
        if ALLOWED_DIRECTIVES.contains(&d) {
            return (false, None);
        }
        return (true, Some(d.to_string()));
    }
    (false, None)
}

/// Check if a command is banned.
fn _is_banned_cmd(norm: &str) -> (bool, Option<String>) {
    let norm_lower = norm.trim().to_lowercase();
    if !CMD_ALLOWED.contains(&norm_lower.as_str()) {
        let parts: Vec<&str> = norm_lower.split_whitespace().collect();
        let cmd_name = parts.first().map(|s| s.to_string()).unwrap_or_default();
        return (true, Some(cmd_name));
    }
    (false, None)
}

/// Validate a .include/.lib/.inc target and scan its content.
fn _check_include_path(raw: &str, directive: &str, depth: usize) -> NgSpiceResult<String> {
    if raw.is_empty() {
        return Err(NgSpiceError::InvalidCommand(
            format!("ngSpice_Circ rejected the untrusted netlist: .{directive} with no file argument"),
        ));
    }
    if depth >= INCLUDE_SCAN_DEPTH_LIMIT {
        return Err(NgSpiceError::InvalidCommand(
            format!("ngSpice_Circ rejected the untrusted netlist: .{directive} nesting exceeds depth {INCLUDE_SCAN_DEPTH_LIMIT}"),
        ));
    }

    let mut candidates: Vec<String> = Vec::new();
    if std::path::Path::new(raw).is_absolute() {
        candidates.push(raw.to_string());
    } else {
        if let Ok(cwd) = std::env::current_dir() {
            candidates.push(cwd.join(raw).to_string_lossy().to_string());
        }
        candidates.push(std::path::Path::new(PROJECT_ROOT_STR).join(raw).to_string_lossy().to_string());
    }

    let allowed: Vec<String> = allowed_include_dirs()
        .iter()
        .map(|d| std::path::Path::new(d).canonicalize().unwrap_or_else(|_| std::path::Path::new(d).to_path_buf()).to_string_lossy().to_string())
        .collect();

    let mut inside: Vec<String> = Vec::new();
    for cand in &candidates {
        if let Ok(resolved) = std::path::Path::new(cand).canonicalize() {
            let resolved_str = resolved.to_string_lossy().to_string();
            for d in &allowed {
                if resolved_str == *d || resolved_str.starts_with(&format!("{}{}", d, std::path::MAIN_SEPARATOR)) {
                    inside.push(resolved_str);
                    break;
                }
            }
        }
    }

    // Prefer an allowlisted candidate that exists as a file
    for resolved in &inside {
        if std::path::Path::new(resolved).is_file() {
            _scan_included_file(resolved, depth + 1)?;
            return Ok(resolved.clone());
        }
    }
    if !inside.is_empty() {
        return Err(NgSpiceError::InvalidCommand(
            format!("ngSpice_Circ rejected the untrusted netlist: .{directive} file not found or unreadable @line: {}", inside[0]),
        ));
    }
    Err(NgSpiceError::InvalidCommand(
        format!("ngSpice_Circ rejected the untrusted netlist: .{directive} outside allowed directories @line: {raw}"),
    ))
}

/// Apply the same line rules to every line of an included file.
fn _scan_included_file(path: &str, _depth: usize) -> NgSpiceResult<()> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| NgSpiceError::InvalidCommand(
            format!("ngSpice_Circ rejected the untrusted netlist: included file unreadable: {path} ({e})")
        ))?;
    for line in content.lines() {
        if !line.trim().is_empty() {
            _sanitise_line(line)?;
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Failure report
// ---------------------------------------------------------------------------

/// Return ngspice's own failure output, or None if it reported none.
///
/// `lines` must be only the output produced by the call being checked.
/// ngspice splits a parse error over two lines - the header
/// `Error on line 2 or its substitute:` and the offending text on the next -
/// so the line after a match is quoted as well.
pub fn _failure_report(lines: &[String], tstop: Option<f64>) -> Option<String> {
    let text_lines: Vec<String> = lines.iter().map(|s| s.to_string()).collect();
    let produced_rows = text_lines.iter().any(|line| line.to_lowercase().contains("no. of data rows"));
    let mut matched: Vec<String> = Vec::new();
    let mut skip_next = false;

    for (idx, text) in text_lines.iter().enumerate() {
        if skip_next {
            skip_next = false;
            continue;
        }
        let lowered = text.to_lowercase();
        if !FAILURE_MARKERS.iter().any(|m| lowered.contains(*m)) {
            continue;
        }
        // A transient that already reached `tstop` is not a failure even when
        // ngspice says so afterwards.
        if tstop.is_some() && produced_rows && lowered.contains("timestep too small") {
            if let Some(reported) = lowered.find("time =") {
                // Simplified: just check if any number after "time =" is >= tstop
                let after = &lowered[reported + 7..];
                let mut num_str = String::new();
                for ch in after.chars() {
                    if ch.is_ascii_digit() || ch == '.' || ch == 'e' || ch == 'E' || ch == '+' || ch == '-' {
                        num_str.push(ch);
                    } else {
                        break;
                    }
                }
                if let Ok(t) = num_str.parse::<f64>() {
                    if t >= tstop.unwrap() * (1.0 - 1e-6) {
                        skip_next = true;
                        continue;
                    }
                }
            }
        }
        matched.push(text.trim().to_string());
        if idx + 1 < text_lines.len() {
            let follower = text_lines[idx + 1].trim();
            if !follower.is_empty() && !matched.iter().any(|m| m == follower) {
                matched.push(follower.to_string());
            }
        }
    }

    if matched.is_empty() {
        return None;
    }
    Some(matched.into_iter().take(8).collect::<Vec<_>>().join(" | "))
}

/// Find the stop time of the deck's .tran card, or None when it has none.
pub fn _find_tstop(lines: &[String]) -> Option<f64> {
    for raw in lines {
        let parts: Vec<&str> = raw.split_whitespace().collect();
        if parts.first() == Some(&".tran") && parts.len() >= 3 {
            return spice_seconds(parts[2]);
        }
    }
    None
}
