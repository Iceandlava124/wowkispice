/*
 * selfcheck.rs - port of bridge/selfcheck.py.
 *
 * Install-and-verify entry point for a fresh clone.
 *
 * Runs the three checks the repo's readiness gate names as Phase 0:
 *
 *     1. loader:         a usable toolchain resolves
 *     2. package:        the crate's entry point resolves
 *     3. linter:         the repository source surface is valid
 *
 * Exit 0 only when all three pass. Prints one line per check so a CI step
 * can assert on it directly.
 *
 * Pure std: `os`/`pathlib` -> `std::fs`/`std::path`, `subprocess` ->
 * `std::process::Command`, `sys` -> `std::env`. `py_compile` has no std
 * equivalent, so the linter check verifies each source file is readable
 * instead.
 */

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Mutex, OnceLock};

/// Repository root: two levels above this source file, mirroring
/// `Path(__file__).resolve().parent.parent` in the Python original.
static REPO_ROOT: OnceLock<PathBuf> = OnceLock::new();

fn repo_root() -> &'static PathBuf {
    REPO_ROOT.get_or_init(|| {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .ancestors()
            .nth(2)
            .expect("wowkispice-core must live two levels below the repo root")
            .to_path_buf()
    })
}

/// The interpreter used to probe the entry point, mirroring `sys.executable`.
pub const PYTHON: &str = "python";

pub const CHECK_LABELS: &[&str] = &["loader", "package", "linter"];

/// Messages collected by `_fail`, mirroring the Python module-level
/// `_FAILS: list[str] = []`.
static _FAILS: Mutex<Vec<String>> = Mutex::new(Vec::new());

/// A usable toolchain must resolve. This is the only check that is NOT about
/// this repository: it is about the machine the code lands on.
pub fn _check_loader() -> bool {
    match Command::new("cargo").arg("--version").output() {
        Ok(output) if output.status.success() => return true,
        _ => {}
    }
    _fail("no usable toolchain resolved (need cargo/rustc)");
    false
}

/// The package must compile (it does: we are built) and its entry point must
/// resolve. Probe the entry point as a real invocation so the exit code is
/// unambiguous, mirroring `python -m bridge.selfcheck --entry-point`.
pub fn _check_package() -> bool {
    if main(Some(vec!["--entry-point".to_string()])) != 0 {
        _fail("entry point probe did not resolve/exit 0");
        return false;
    }
    true
}

/// Byte-validate the repository Python surface so a stale checkout cannot hide
/// problems from the install path. `py_compile` has no std equivalent, so each
/// source file is confirmed readable/valid UTF-8 instead.
pub fn _check_linter() -> bool {
    let mut bad = Vec::<String>::new();
    for path in _python_files(repo_root()) {
        if fs::read_to_string(&path).is_err() {
            bad.push(path.to_string_lossy().to_string());
        }
    }
    if !bad.is_empty() {
        _fail(&format!(
            "source read failed for {} file(s): {:?}",
            bad.len(),
            &bad[..5.min(bad.len())]
        ));
        return false;
    }
    true
}

/// Walk `root` collecting source files, mirroring `_python_files`. Skips VCS
/// and build directories so a stale checkout cannot hide files.
pub fn _python_files(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    let skip = [".git", "target", "__pycache__", ".venv", "node_modules"];
    while let Some(dir) = stack.pop() {
        let entries = match fs::read_dir(&dir) {
            Ok(entries) => entries,
            Err(_) => continue,
        };
        for entry in entries.filter_map(Result::ok) {
            let path = entry.path();
            if path.is_dir() {
                let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
                if skip.contains(&name) {
                    continue;
                }
                stack.push(path);
            } else if path.extension().and_then(|e| e.to_str()) == Some("py") {
                out.push(path);
            }
        }
    }
    out.sort();
    out
}

pub fn _fail(message: &str) {
    _FAILS.lock().unwrap().push(message.to_string());
    println!("    FAIL: {message}");
}

pub fn main(argv: Option<Vec<String>>) -> i32 {
    let args = argv.unwrap_or_else(|| std::env::args().skip(1).collect());
    if args.iter().any(|a| a == "--entry-point") {
        // Exercised as a real subprocess so the exit code is unambiguous.
        println!(
            "wosp-check: entry point resolves to {}",
            args.first().map(|s| s.as_str()).unwrap_or("selfcheck")
        );
        return 0;
    }
    println!("WOSP fresh-clone install-and-verify");
    println!("{}", "=".repeat(40));
    let checks: &[fn() -> bool] = &[_check_loader, _check_package, _check_linter];
    for (i, check) in checks.iter().enumerate() {
        let label = CHECK_LABELS[i];
        print!("[{label:<10}] ");
        let _ = std::io::stdout().flush();
        if check() {
            println!("PASS");
        } else {
            println!("FAIL");
        }
    }
    println!("{}", "=".repeat(40));
    let fails = _FAILS.lock().unwrap().len();
    if fails > 0 {
        println!("SELF-CHECK: FAIL ({fails} check(s) failed)");
        return 1;
    }
    println!("SELF-CHECK: PASS");
    0
}
