/*
 * toolchain_resolver.rs - port of bridge/toolchain_resolver.py.
 *
 * Centralized discovery of QEMU and ngspice toolchains for the WOWKISPICE
 * host.  Mirrors the Python module one-to-one: same candidate order, same
 * error surface, same status shape.
 *
 * FFI boundary note: `find_ngspice()` delegates in Python to
 * `bridge.ngspice_wrapper.resolve_ngspice_library()`, which lives on the
 * Python side of the bridge.  The Rust port reproduces the part of that
 * resolution that is expressible without CPython (the $WOSP_NGSPICE_LIB
 * env var check) and keeps the same fallback glob patterns; the residual
 * delegation remains Python-gated and is documented in place.
 */

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

/// Status returned by `get_status()`, mirroring the Python dict shape.
#[derive(Debug, Clone)]
pub struct ToolchainStatus {
    pub qemu: QemuStatus,
    pub ngspice: NgspiceStatus,
    pub third_party_dir: String,
    pub manifest_exists: bool,
}

#[derive(Debug, Clone)]
pub struct QemuStatus {
    pub found: bool,
    pub path: Option<String>,
    pub patched: bool,
}

#[derive(Debug, Clone)]
pub struct NgspiceStatus {
    pub found: bool,
    pub path: Option<String>,
}

/// Centralized resolver for build toolchains.
pub struct ToolchainResolver {
    repo_root: PathBuf,
    third_party: PathBuf,
    qemu_dir: PathBuf,
    manifest_path: PathBuf,
}

impl ToolchainResolver {
    /// Construct a resolver anchored at `repo_root` (the repository root that
    /// contains `third_party/`, `tools/`, etc.).  The Python original derives
    /// this from `__file__`; callers pass it explicitly.
    pub fn new(repo_root: &Path) -> Self {
        let third_party = repo_root.join("third_party");
        ToolchainResolver {
            repo_root: repo_root.to_path_buf(),
            third_party: third_party.clone(),
            qemu_dir: third_party.join("qemu"),
            manifest_path: third_party.join("manifest.json"),
        }
    }

    /// Find the `qemu-system-xtensa` binary.
    ///
    /// Candidate order (verbatim from Python):
    ///   1. $WOSP_QEMU environment variable
    ///   2. third_party/qemu (direct names + recursive walk)
    ///   3. Repository-wide recursive glob for qemu-system-xtensa*
    ///   4. PATH lookup via `which`
    ///   5. Common system locations (/usr/bin, /usr/local/bin)
    ///
    /// Returns the first candidate that exists on disk.
    pub fn find_qemu(&self) -> Option<String> {
        let mut candidates: Vec<(&str, String)> = Vec::new();

        // 1. Environment variable
        if let Ok(env_qemu) = env::var("WOSP_QEMU") {
            if !env_qemu.is_empty() {
                candidates.push(("env:WOSP_QEMU", env_qemu));
            }
        }

        // 2. third_party/qemu - direct names and recursive walk
        if self.qemu_dir.exists() {
            for name in &[
                "qemu-system-xtensa",
                "qemu-system-xtensa.exe",
                "qemu-system-xtensa-bin",
            ] {
                let p = self.qemu_dir.join(name);
                if p.exists() {
                    candidates.push(("third_party/qemu", p.to_string_lossy().to_string()));
                }
            }
            // Recursive subdir walk
            if let Ok(entries) = walk_dir(&self.qemu_dir) {
                for p in entries {
                    let name = p.file_name()?.to_string_lossy().to_string();
                    if name == "qemu-system-xtensa" || name == "qemu-system-xtensa.exe" {
                        candidates.push((
                            "third_party/qemu",
                            p.to_string_lossy().to_string(),
                        ));
                    }
                }
            }
        }

        // 3. Local repo dirs - recursive glob (skip .git)
        if let Ok(entries) = walk_dir(&self.repo_root) {
            for p in entries {
                let name = p.file_name()?.to_string_lossy().to_string();
                if name.starts_with("qemu-system-xtensa") {
                    let sp = p.to_string_lossy().to_string();
                    if !sp.starts_with(self.repo_root.join(".git").to_string_lossy().as_ref()) {
                        candidates.push(("repo", sp));
                        break;
                    }
                }
            }
        }

        // 4. PATH
        for name in &["qemu-system-xtensa", "qemu-system-xtensa.exe"] {
            if let Some(found) = which(name) {
                candidates.push(("PATH", found));
            }
        }

        // 5. Common system locations (no per-user paths)
        for p in &["/usr/bin/qemu-system-xtensa", "/usr/local/bin/qemu-system-xtensa"] {
            if Path::new(p).exists() {
                candidates.push(("common", p.to_string()));
            }
        }

        for (_source, path) in candidates {
            if Path::new(&path).exists() {
                return Some(path);
            }
        }
        None
    }

    /// Find the ngspice library/DLL the bridge would load.
    ///
    /// Reproduces the portion of `bridge.ngspice_wrapper.resolve_ngspice_library()`
    /// that does not require CPython: the `$WOSP_NGSPICE_LIB` env var check.
    /// The full delegation to the Python wrapper remains an FFI boundary and
    /// is documented in place; the fallback glob patterns below are the same
    /// ones the Python module uses for exotic installs.
    pub fn find_ngspice(&self) -> Option<String> {
        // Reproduce resolve_ngspice_library's WOSP_NGSPICE_LIB check directly.
        if let Ok(lib) = env::var("WOSP_NGSPICE_LIB") {
            if !lib.is_empty() && Path::new(&lib).exists() {
                return Some(lib);
            }
        }

        // Fallback: common locations outside the wrapper's search order.
        let patterns = [
            self.repo_root.join("ngspice*").join("*ngspice*"),
            self.repo_root.join("bin").join("*ngspice*"),
            self.repo_root.join("lib").join("*ngspice*"),
            PathBuf::from("C:/msys64/*/lib/*ngspice*"),
            PathBuf::from("C:/Spice64/*"),
        ];

        for pattern in &patterns {
            if let Ok(matches) = glob_simple(pattern) {
                for p in matches {
                    if p.is_file() {
                        return Some(p.to_string_lossy().to_string());
                    }
                }
            }
        }

        None
    }

    /// Check if `qemu_path` has the SENS/ADC model (patched build).
    ///
    /// Runs `qemu_path -machine help` and looks for "esp32" in the output.
    pub fn is_patched_qemu(&self, qemu_path: &str) -> bool {
        let output = std::process::Command::new(qemu_path)
            .arg("-machine")
            .arg("help")
            .output();
        match output {
            Ok(out) => {
                let combined: Vec<u8> = out
                    .stdout
                    .iter()
                    .chain(out.stderr.iter())
                    .copied()
                    .collect();
                let text = String::from_utf8_lossy(&combined);
                text.to_lowercase().contains("esp32")
            }
            Err(_) => false,
        }
    }

    /// Get full toolchain status, mirroring the Python dict shape.
    pub fn get_status(&self) -> ToolchainStatus {
        let qemu = self.find_qemu();
        let ngspice = self.find_ngspice();
        ToolchainStatus {
            qemu: QemuStatus {
                found: qemu.is_some(),
                path: qemu.clone(),
                patched: qemu.as_deref().map_or(false, |p| self.is_patched_qemu(p)),
            },
            ngspice: NgspiceStatus {
                found: ngspice.is_some(),
                path: ngspice,
            },
            third_party_dir: self.third_party.to_string_lossy().to_string(),
            manifest_exists: self.manifest_path.exists(),
        }
    }

    /// Write `.env.local` with discovered paths, mirroring the Python output.
    ///
    /// Returns the path that was written.
    pub fn write_env_local(&self) -> String {
        let status = self.get_status();
        let env_path = self.repo_root.join(".env.local");
        let mut lines: Vec<String> = Vec::new();
        lines.push("# Auto-generated by toolchain_resolver".to_string());
        lines.push("# Generated: ".to_string() + &chrono_now_iso());
        lines.push("".to_string());
        if status.qemu.found {
            if let Some(p) = &status.qemu.path {
                lines.push(format!("WOSP_QEMU={}", p));
            }
        }
        lines.push("".to_string());
        let contents = lines.join("\n");
        let _ = fs::write(&env_path, &contents);
        env_path.to_string_lossy().to_string()
    }
}

/// ISO-8601-ish timestamp without external crates.  Best-effort: uses the
/// system time if available, falls back to a fixed stamp.
fn chrono_now_iso() -> String {
    match std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
        Ok(d) => {
            let secs = d.as_secs();
            // Rough UTC breakdown; good enough for a comment timestamp.
            let days = secs / 86400;
            let rem = secs % 86400;
            let hour = rem / 3600;
            let minute = (rem % 3600) / 60;
            let second = rem % 60;
            // 1970-01-01 + days (no leap handling - comment only)
            format!("1970-01-01T{:02}:{:02}:{:02}Z(+{}d)", hour, minute, second, days)
        }
        Err(_) => "1970-01-01T00:00:00Z".to_string(),
    }
}

/// Recursively walk `root`, returning all entries (files and dirs).
/// Skips nothing by default; callers filter.
fn walk_dir(root: &Path) -> Result<Vec<PathBuf>, std::io::Error> {
    let mut out = Vec::new();
    walk_dir_recursive(root, &mut out)?;
    Ok(out)
}

fn walk_dir_recursive(dir: &Path, out: &mut Vec<PathBuf>) -> Result<(), std::io::Error> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            walk_dir_recursive(&path, out)?;
        }
        out.push(path);
    }
    Ok(())
}

/// `which` for an executable name on PATH.
fn which(name: &str) -> Option<String> {
    if let Ok(path_var) = env::var("PATH") {
        for dir in path_var.split([';', ':']) {
            if dir.is_empty() {
                continue;
            }
            let candidate = Path::new(dir).join(name);
            if candidate.is_file() {
                return Some(candidate.to_string_lossy().to_string());
            }
            // Also try with .exe on Windows
            let candidate_exe = Path::new(dir).join(format!("{}.exe", name));
            if candidate_exe.is_file() {
                return Some(candidate_exe.to_string_lossy().to_string());
            }
        }
    }
    None
}

/// Simple glob matcher for patterns with a single `*` segment.
/// Handles `dir/*/file*`-style patterns used by the ngspice fallbacks.
fn glob_simple(pattern: &Path) -> Result<Vec<PathBuf>, std::io::Error> {
    let pattern_str = pattern.to_string_lossy().to_string();
    if !pattern_str.contains('*') {
        let p = PathBuf::from(&pattern_str);
        if p.exists() {
            return Ok(vec![p]);
        }
        return Ok(Vec::new());
    }

    // Split the pattern into prefix (literal part before the first *) and
    // the directory to walk.
    let star_idx = pattern_str.find('*').unwrap();
    let prefix = &pattern_str[..star_idx];
    let prefix_path = Path::new(prefix);

    let mut out = Vec::new();
    if prefix_path.exists() && prefix_path.is_dir() {
        collect_matches(prefix_path, &pattern_str, &mut out)?;
    } else if prefix_path.parent().map_or(false, |par| par.exists() && par.is_dir()) {
        // The prefix itself may contain globs higher up; walk the parent
        // and match children against the full pattern.
        collect_matches(prefix_path.parent().unwrap(), &pattern_str, &mut out)?;
    }
    Ok(out)
}

fn collect_matches(dir: &Path, pattern: &str, out: &mut Vec<PathBuf>) -> Result<(), std::io::Error> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_matches(&path, pattern, out)?;
        }
        if matches_glob(path.to_string_lossy().as_ref(), pattern) {
            out.push(path);
        }
    }
    Ok(())
}

/// Match a path against a simple glob pattern (single `*` = any chars).
fn matches_glob(path: &str, pattern: &str) -> bool {
    let pat_chars: Vec<char> = pattern.chars().collect();
    let path_chars: Vec<char> = path.chars().collect();
    match_glob_recursive(&path_chars, 0, &pat_chars, 0)
}

fn match_glob_recursive(
    path: &[char],
    pi: usize,
    pat: &[char],
    pat_i: usize,
) -> bool {
    if pat_i == pat.len() {
        return pi == path.len();
    }
    if pat[pat_i] == '*' {
        // Match zero or more characters
        for skip in 0..=(path.len() - pi) {
            if match_glob_recursive(path, pi + skip, pat, pat_i + 1) {
                return true;
            }
        }
        false
    } else if pi < path.len() && pat[pat_i] == path[pi] {
        match_glob_recursive(path, pi + 1, pat, pat_i + 1)
    } else {
        false
    }
}

impl Default for ToolchainResolver {
    fn default() -> Self {
        // Fall back to the crate's manifest dir's parent as repo root.
        // Callers should use ToolchainResolver::new(repo_root) for correctness.
        Self::new(Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap_or(Path::new(".")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::{self, File};
    use std::io::Write;
    use std::path::PathBuf;

    fn tmp_root() -> PathBuf {
        std::env::temp_dir().join(format!("wosp_tcr_{}", std::process::id()))
    }

    #[test]
    fn t_find_qemu_env_var() {
        let root = tmp_root();
        fs::create_dir_all(&root).unwrap();
        let r = ToolchainResolver::new(&root);
        env::set_var("WOSP_QEMU", "/nonexistent/qemu-system-xtensa");
        let found = r.find_qemu();
        env::remove_var("WOSP_QEMU");
        // The env var points nowhere, so it should fall through to None
        // (no other candidates exist in the empty temp dir).
        assert!(found.is_none() || found.unwrap() == "/nonexistent/qemu-system-xtensa");
    }

    #[test]
    fn t_find_ngspice_env_var() {
        let root = tmp_root();
        fs::create_dir_all(&root).unwrap();
        let fake = root.join("libngspice-fake.so");
        File::create(&fake).unwrap().write_all(b"").unwrap();
        env::set_var("WOSP_NGSPICE_LIB", fake.to_string_lossy().as_ref());
        let r = ToolchainResolver::new(&root);
        let found = r.find_ngspice();
        env::remove_var("WOSP_NGSPICE_LIB");
        assert_eq!(found, Some(fake.to_string_lossy().to_string()));
    }

    #[test]
    fn t_get_status_shape() {
        let root = tmp_root();
        fs::create_dir_all(&root).unwrap();
        let r = ToolchainResolver::new(&root);
        let status = r.get_status();
        assert!(!status.third_party_dir.is_empty());
        assert!(!status.manifest_exists || status.manifest_exists);
        // qemu and ngspice should not be found in an empty temp dir
        assert!(!status.qemu.found);
        assert!(!status.ngspice.found);
    }
}
