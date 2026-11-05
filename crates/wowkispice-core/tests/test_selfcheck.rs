/*
 * test_selfcheck.rs - Rust gate for bridge/selfcheck.py.
 *
 * Transcribes the fresh-clone install-and-verify checks:
 *   loader:   a usable toolchain (cargo) resolves
 *   package:  the entry point (`--entry-point`) resolves and exits 0
 *   linter:   the repository Python surface is readable (py_compile analog)
 * Plus entry-point propagation (exit codes).
 */

use std::fs;
use std::path::Path;
use wowkispice_core::selfcheck::main;

// ----------------------------------------------------------------------
// main: entry point
// ----------------------------------------------------------------------

#[test]
fn test_main_entry_point_returns_zero() {
    assert_eq!(main(Some(vec!["--entry-point".to_string()])), 0);
}

#[test]
fn test_main_entry_point_with_args() {
    assert_eq!(
        main(Some(vec![
            "--entry-point".to_string(),
            "extra".to_string(),
        ])),
        0
    );
}

// ----------------------------------------------------------------------
// main: loader check
// ----------------------------------------------------------------------

#[test]
fn test_main_loader_check_passes() {
    // cargo is on PATH in this environment, so the loader check passes.
    let rc = main(Some(vec![]));
    assert_eq!(rc, 0, "selfcheck should PASS when cargo is available");
}

// ----------------------------------------------------------------------
// Package check: the crate compiles (we are built) and entry point resolves
// ----------------------------------------------------------------------

#[test]
fn test_main_package_check() {
    // The package compiles (this test is running inside it) and the entry
    // point resolves, so main() with no args should return 0.
    assert_eq!(main(Some(vec![])), 0);
}

// ----------------------------------------------------------------------
// Linter check: repository Python files are readable
// ----------------------------------------------------------------------

#[test]
fn test_linter_reads_python_files() {
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .expect("wowkispice-core must live two levels below the repo root");
    let py_files: Vec<_> = fs::read_dir(repo_root.join("bridge"))
        .unwrap()
        .filter_map(Result::ok)
        .filter(|e| e.path().extension().and_then(|s| s.to_str()) == Some("py"))
        .collect();
    assert!(!py_files.is_empty(), "bridge/ should contain Python files");
    for f in py_files {
        let content = fs::read_to_string(f.path());
        assert!(
            content.is_ok(),
            "Python file {} should be readable",
            f.path().display()
        );
    }
}
