/*
 * firmware.rs - port of bridge/firmware.py.
 *
 * Scope: everything in the Python module that is pure policy over bytes and
 * files - the FirmwareParseError contract, the FirmwareImage metadata
 * (path/format/data/entry/load/sections/SHA-256/size/name/summary/to_dict),
 * the Intel HEX parser (record types 00/01/02/04/03/05, checksums, EOF rules),
 * the ELF parser (32/64-bit, little/big endian, section table, PT_LOAD
 * segments), the load_firmware() file dispatch (.hex/.ihex/.elf, magic sniff),
 * and the GPIO pin-profile JSON parser (text -> pin -> spec structure; the
 * field validation itself lives in gpio_model::normalize_profile).
 *
 * NOT ported here: execution of the image (the Espressif/QEMU runner - see
 * bridge/qemu_orchestrator.py, which the module itself disclaims), the
 * analog/digital co-simulation halves (gpio_model + cosim_runner), and
 * tests/test_firmware_gpio.py's TestLogicAnalysis + TestGpioCosimEndToEnd
 * classes (the former lives in the gpio_model gate, the latter needs the live
 * ngspice solver and stays Python-gated).
 *
 * Error contract: every rejection carries the Python message verbatim through
 * FirmwareParseError (Display == str(exc)); the strings below are transcribed
 * from the f-strings in bridge/firmware.py and must not drift.
 *
 * DOCUMENTED DEVIATIONS / APPROXIMATIONS (as in netlist.rs / control_law.rs):
 *   - SHA-256 is implemented locally (this crate is dependency-free): the
 *     FIPS-180-4 compression with the standard IV and round constants.
 *   - The JSON parser is a minimal recursive-descent reader for flat JSON
 *     objects of flat objects (pin -> spec).  CPython's json module produces
 *     implementation-specific JSONDecodeError text that this port cannot
 *     reproduce without shipping a JSON implementation; a genuine parse error
 *     is wrapped as "pin profile is not valid JSON: <reason>" and the deviation
 *     is documented here rather than papered over.
 *   - Python's struct.unpack_from raises struct.error (NOT FirmwareParseError)
 *     on truncated headers; this port reads the fields it needs with explicit
 *     bounds checks that fail closed.  No test reaches the divergent path.
 */

use std::collections::BTreeMap;
use std::fmt;
use std::fs;

use crate::gpio_model::ProfileSpec;
use crate::netlist::py_splitlines;
use crate::pycompat::py_trim;

// ----------------------------------------------------------------------
// Errors
// ----------------------------------------------------------------------

/// Carries Python's FirmwareParseError messages verbatim (tests and the
/// parity battery compare them as text).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FirmwareParseError {
    pub msg: String,
}

impl FirmwareParseError {
    fn new(msg: impl Into<String>) -> Self {
        FirmwareParseError { msg: msg.into() }
    }

    pub fn message(&self) -> &str {
        &self.msg
    }
}

impl fmt::Display for FirmwareParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.msg)
    }
}

impl std::error::Error for FirmwareParseError {}

// ----------------------------------------------------------------------
// FirmwareImage + sections
// ----------------------------------------------------------------------

/// One ELF section: name, size, address, offset.  Field names mirror the
/// Python section dicts verbatim.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Section {
    pub name: String,
    pub size: u64,
    pub address: u64,
    pub offset: u64,
}

/// The parsed image plus the metadata we can state as fact.
#[derive(Debug, Clone, PartialEq)]
pub struct FirmwareImage {
    pub path: String,
    pub format: String, // "ihex" | "elf"
    pub data: Vec<u8>,
    pub entry_point: u64,
    pub load_address: u64,
    pub sections: Vec<Section>,
    pub sha256: String,
    pub machine: Option<String>,
}

impl FirmwareImage {
    fn ihex(path: &str, data: Vec<u8>, entry: u64, load: u64) -> Self {
        let digest = sha256_of(&data);
        FirmwareImage {
            path: path.to_string(),
            format: "ihex".to_string(),
            data,
            entry_point: entry,
            load_address: load,
            sections: Vec::new(),
            sha256: digest,
            machine: None,
        }
    }

    fn elf(
        path: &str,
        data: Vec<u8>,
        entry: u64,
        load: u64,
        sections: Vec<Section>,
        machine: String,
    ) -> Self {
        let digest = sha256_of(&data);
        FirmwareImage {
            path: path.to_string(),
            format: "elf".to_string(),
            data,
            entry_point: entry,
            load_address: load,
            sections,
            sha256: digest,
            machine: Some(machine),
        }
    }

    pub fn size_bytes(&self) -> usize {
        self.data.len()
    }

    pub fn name(&self) -> &str {
        crate::pycompat::py_basename(&self.path)
    }

    /// "name, N bytes, sha256:<12>, [load 0x..], [entry 0x..]" joined with
    /// ", " - verbatim from Python `FirmwareImage.summary()`.
    pub fn summary(&self) -> String {
        let mut parts: Vec<String> = Vec::new();
        parts.push(self.name().to_string());
        parts.push(format!("{} bytes", self.size_bytes()));
        parts.push(format!("sha256:{}", &self.sha256[..self.sha256.len().min(12)]));
        if self.load_address != 0 {
            parts.push(format!("load 0x{:08X}", self.load_address));
        }
        if self.entry_point != 0 {
            parts.push(format!("entry 0x{:08X}", self.entry_point));
        }
        parts.join(", ")
    }

    pub fn to_dict(&self) -> FirmwareImageDict {
        FirmwareImageDict {
            path: self.path.clone(),
            format: self.format.clone(),
            size_bytes: self.size_bytes(),
            entry_point: self.entry_point,
            load_address: self.load_address,
            sha256: self.sha256.clone(),
            sections: self.sections.clone(),
        }
    }
}

/// The dict-shaped view of an image (Python's `to_dict()`): same keys and
/// values, `sections` as a list of section dicts.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FirmwareImageDict {
    pub path: String,
    pub format: String,
    pub size_bytes: usize,
    pub entry_point: u64,
    pub load_address: u64,
    pub sha256: String,
    pub sections: Vec<Section>,
}

// ----------------------------------------------------------------------
// SHA-256 (FIPS-180-4; local implementation - this crate is dependency-free)
// ----------------------------------------------------------------------

const SHA256_K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
    0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
    0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
    0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
    0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
    0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
    0xc67178f2,
];

fn rotr_pub(x: u32, n: u32) -> u32 {
    (x >> n) | (x << (32 - n))
}

/// Lowercase-hex SHA-256 of `data` (FIPS-180-4).
pub fn sha256_hex(data: &[u8]) -> String {
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];
    let bit_len = (data.len() as u64) * 8;
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    for shift in (0..64).rev() {
        if shift % 8 == 0 {
            msg.push(((bit_len >> shift) & 0xff) as u8);
        }
    }
    for chunk in msg.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            let o = i * 4;
            w[i] = u32::from_be_bytes([chunk[o], chunk[o + 1], chunk[o + 2], chunk[o + 3]]);
        }
        for i in 16..64 {
            let x = w[i - 15];
            let s0 = rotr_pub(x, 7) ^ rotr_pub(x, 18) ^ (x >> 3);
            let y = w[i - 2];
            let s1 = rotr_pub(y, 17) ^ rotr_pub(y, 19) ^ (y >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let (mut a, mut b, mut c, mut d) = (h[0], h[1], h[2], h[3]);
        let (mut e, mut f, mut g, mut hh) = (h[4], h[5], h[6], h[7]);
        for i in 0..64 {
            let s1 = rotr_pub(e, 6) ^ rotr_pub(e, 11) ^ rotr_pub(e, 25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(SHA256_K[i])
                .wrapping_add(w[i]);
            let s0 = rotr_pub(a, 2) ^ rotr_pub(a, 13) ^ rotr_pub(a, 22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }
    let mut out = String::with_capacity(64);
    for x in h {
        out.push_str(&format!("{:08x}", x));
    }
    out
}

/// SHA-256 of the image payload, as the FirmwareImage stores it: the real
/// digest for non-empty data, the empty string for empty data (Python:
/// `hashlib.sha256(data).hexdigest() if data else ""`).
fn sha256_of(data: &[u8]) -> String {
    if data.is_empty() {
        String::new()
    } else {
        sha256_hex(data)
    }
}

// ----------------------------------------------------------------------
// Intel HEX
// ----------------------------------------------------------------------

fn hex_val(b: u8) -> Option<u8> {
    match b {
        b'0'..=b'9' => Some(b - b'0'),
        b'a'..=b'f' => Some(b - b'a' + 10),
        b'A'..=b'F' => Some(b - b'A' + 10),
        _ => None,
    }
}

/// `bytes.fromhex` semantics: ASCII whitespace skipped, pairs required, both
/// cases accepted; `None` on any deviation (Python raises ValueError).
fn hex_decode(s: &str) -> Option<Vec<u8>> {
    let b = s.as_bytes();
    let mut clean = Vec::with_capacity(b.len());
    for &c in b {
        if !(c == b' ' || c == b'\t' || c == b'\n' || c == b'\r') {
            clean.push(c);
        }
    }
    if clean.len() % 2 != 0 {
        return None;
    }
    let mut out = Vec::with_capacity(clean.len() / 2);
    let mut i = 0;
    while i < clean.len() {
        let hi = hex_val(clean[i])?;
        let lo = hex_val(clean[i + 1])?;
        out.push((hi << 4) | lo);
        i += 2;
    }
    Some(out)
}

fn int_from_bytes(b: &[u8]) -> u64 {
    let mut v = 0u64;
    for &x in b {
        v = (v << 8) | x as u64;
    }
    v
}

/// Parse Intel HEX.  Returns (data, load_address, entry_point).
///
/// Record types 00 (data), 01 (EOF), 02 (extended segment address),
/// 04 (extended linear address) and 03/05 (start address) are handled;
/// 06 is ignored silently, exactly like Python.
pub fn parse_intel_hex(text: &str) -> Result<(Vec<u8>, u64, u64), FirmwareParseError> {
    let mut memory: std::collections::BTreeMap<u64, u8> = std::collections::BTreeMap::new();
    let mut base: u64 = 0;
    let mut entry: u64 = 0;
    let mut saw_eof = false;

    for (idx, raw) in py_splitlines(text).iter().enumerate() {
        let lineno = idx + 1;
        let line = py_trim(raw);
        if line.is_empty() {
            continue;
        }
        if saw_eof {
            return Err(FirmwareParseError::new(format!(
                "line {}: data after EOF record",
                lineno
            )));
        }
        if !line.starts_with(':') {
            return Err(FirmwareParseError::new(format!(
                "line {}: record does not start with ':'",
                lineno
            )));
        }
        let payload = match hex_decode(&line[1..]) {
            Some(p) => p,
            None => {
                return Err(FirmwareParseError::new(format!(
                    "line {}: invalid hex digits",
                    lineno
                )))
            }
        };
        if payload.len() < 5 {
            return Err(FirmwareParseError::new(format!(
                "line {}: record too short ({} bytes)",
                lineno,
                payload.len()
            )));
        }
        let count = payload[0] as usize;
        if payload.len() != count + 5 {
            return Err(FirmwareParseError::new(format!(
                "line {}: length byte {} does not match record size",
                lineno,
                count
            )));
        }
        let address = ((payload[1] as u64) << 8) | (payload[2] as u64);
        let rectype = payload[3];
        let data = &payload[4..4 + count];
        let sum: u32 = payload.iter().map(|&b| b as u32).sum();
        if (sum & 0xff) != 0 {
            return Err(FirmwareParseError::new(format!(
                "line {}: bad checksum",
                lineno
            )));
        }

        if rectype == 0x00 {
            for (i, &byte) in data.iter().enumerate() {
                memory.insert(base + address + i as u64, byte);
            }
        } else if rectype == 0x01 {
            saw_eof = true;
        } else if rectype == 0x02 {
            base = int_from_bytes(&data) << 4;
        } else if rectype == 0x04 {
            base = int_from_bytes(&data) << 16;
        } else if rectype == 0x03 || rectype == 0x05 {
            entry = int_from_bytes(&data);
        }
    }

    if memory.is_empty() {
        return Err(FirmwareParseError::new(
            "no data records found (is this a code-only HEX?)".to_string(),
        ));
    }
    let min_addr = *memory.keys().next().unwrap();
    let max_addr = *memory.keys().next_back().unwrap();
    let len = (max_addr - min_addr + 1) as usize;
    let mut blob = vec![0u8; len];
    for (&addr, &byte) in &memory {
        blob[(addr - min_addr) as usize] = byte;
    }
    Ok((blob, min_addr, entry))
}

// ----------------------------------------------------------------------
// ELF
// ----------------------------------------------------------------------

fn rd(b: &[u8], off: usize, len: usize, be: bool) -> u64 {
    let mut v: u64 = 0;
    for i in 0..len {
        let idx = if be { off + (len - 1 - i) } else { off + i };
        v |= (b[idx] as u64) << (8 * i);
    }
    v
}

fn rd16(b: &[u8], off: usize, le: bool) -> u16 {
    rd(b, off, 2, !le) as u16
}

fn rd32(b: &[u8], off: usize, le: bool) -> u32 {
    rd(b, off, 4, !le) as u32
}

fn rd64(b: &[u8], off: usize, le: bool) -> u64 {
    rd(b, off, 8, !le)
}

fn elf_machine_name(e_machine: u16) -> String {
    match e_machine {
        0x03 => "x86".to_string(),
        0x08 => "MIPS".to_string(),
        0x14 => "PowerPC".to_string(),
        0x15 => "PowerPC64".to_string(),
        0x28 => "ARM".to_string(),
        0x3E => "x86-64".to_string(),
        0xB7 => "AArch64".to_string(),
        0xF3 => "RISC-V".to_string(),
        0x5E => "Xtensa".to_string(),
        _ => format!("machine 0x{:X}", e_machine),
    }
}

/// Parse a 32- or 64-bit little/big-endian ELF.  Returns
/// (loadable_bytes, entry_point, load_address, sections, machine).
///
/// Only loadable segments are read - .text/.rodata/.data in practice.  The
/// section-name table is read best effort; stripped images have none.
pub fn parse_elf(
    blob: &[u8],
) -> Result<(Vec<u8>, u64, u64, Vec<Section>, String), FirmwareParseError> {
    if blob.len() < 52 || blob[0] != 0x7f || blob[1] != b'E' || blob[2] != b'L' || blob[3] != b'F' {
        return Err(FirmwareParseError::new(
            "not an ELF file (bad magic)".to_string(),
        ));
    }
    let ei_class = blob[4];
    let ei_data = blob[5];
    if ei_class != 1 && ei_class != 2 {
        return Err(FirmwareParseError::new(format!(
            "unknown ELF class {}",
            ei_class
        )));
    }
    let le = ei_data == 1;

    let (e_entry, e_phoff, e_shoff, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx) =
        if ei_class == 1 {
            // Elf32_Ehdr after e_ident.
            (
                rd32(blob, 24, le) as u64,
                rd32(blob, 28, le) as u64,
                rd32(blob, 32, le) as u64,
                rd16(blob, 42, le),
                rd16(blob, 44, le),
                rd16(blob, 46, le),
                rd16(blob, 48, le),
                rd16(blob, 50, le),
            )
        } else {
            (
                rd64(blob, 24, le),
                rd64(blob, 32, le),
                rd64(blob, 40, le),
                rd16(blob, 54, le),
                rd16(blob, 56, le),
                rd16(blob, 58, le),
                rd16(blob, 60, le),
                rd16(blob, 62, le),
            )
        };
    let e_machine = rd16(blob, 18, le);

    let mut sections: Vec<Section> = Vec::new();
    if e_shoff != 0 && e_shnum != 0 && e_shentsize != 0 && e_shstrndx < e_shnum {
        let mut shstr_off = e_shoff + e_shstrndx as u64 * e_shentsize as u64;
        if shstr_off + e_shentsize as u64 > blob.len() as u64 {
            shstr_off = 0;
        }
        let shstr_off_us = shstr_off as usize;
        let (_sh_name, _sh_type, _sh_flags, _sh_addr, _sh_off, sh_size) = if ei_class == 1 {
            (
                rd32(blob, shstr_off_us, le) as u64,
                rd32(blob, shstr_off_us + 4, le) as u64,
                rd32(blob, shstr_off_us + 8, le) as u64,
                rd32(blob, shstr_off_us + 12, le) as u64,
                rd32(blob, shstr_off_us + 16, le) as u64,
                rd32(blob, shstr_off_us + 20, le) as u64,
            )
        } else {
            (
                rd32(blob, shstr_off_us, le) as u64,
                rd32(blob, shstr_off_us + 4, le) as u64,
                rd64(blob, shstr_off_us + 8, le),
                rd64(blob, shstr_off_us + 16, le),
                rd64(blob, shstr_off_us + 24, le),
                rd64(blob, shstr_off_us + 32, le),
            )
        };

        let mut names: Vec<u8> = Vec::new();
        let names_valid = shstr_off != 0 && sh_size != 0 && _sh_off + sh_size <= blob.len() as u64;
        if names_valid {
            let arr_off = _sh_off as usize;
            names = blob[arr_off..arr_off + sh_size as usize].to_vec();
        }

        let shentsize = e_shentsize as usize;
        for i in 0..e_shnum as usize {
            let off = e_shoff as usize + i * shentsize;
            if off + shentsize > blob.len() {
                break;
            }
            let (_nm, _t, _f, addr, offset, size) = if ei_class == 1 {
                (
                    rd32(blob, off, le) as u64,
                    rd32(blob, off + 4, le) as u64,
                    rd32(blob, off + 8, le) as u64,
                    rd32(blob, off + 12, le) as u64,
                    rd32(blob, off + 16, le) as u64,
                    rd32(blob, off + 20, le) as u64,
                )
            } else {
                (
                    rd32(blob, off, le) as u64,
                    rd32(blob, off + 4, le) as u64,
                    rd64(blob, off + 8, le),
                    rd64(blob, off + 16, le),
                    rd64(blob, off + 24, le),
                    rd64(blob, off + 32, le),
                )
            };

            let mut name = String::new();
            if !names.is_empty() && (_nm as usize) < names.len() {
                let mut end = names.len();
                let mut k = _nm as usize;
                while k < names.len() {
                    if names[k] == 0 {
                        end = k;
                        break;
                    }
                    k += 1;
                }
                name = String::from_utf8_lossy(&names[_nm as usize..end]).into_owned();
            }
            sections.push(Section {
                name,
                size,
                address: addr,
                offset,
            });
        }
    }

    let mut chunks: Vec<(u64, Vec<u8>)> = Vec::new();
    for i in 0..e_phnum as usize {
        let off = e_phoff as usize + i * e_phentsize as usize;
        if off + e_phentsize as usize > blob.len() {
            break;
        }
        let (p_type, p_offset, p_vaddr, p_filesz) = if ei_class == 1 {
            (
                rd32(blob, off, le) as u64,
                rd32(blob, off + 4, le) as u64,
                rd32(blob, off + 8, le) as u64,
                rd32(blob, off + 16, le) as u64,
            )
        } else {
            (
                rd32(blob, off, le) as u64,
                rd64(blob, off + 8, le),
                rd64(blob, off + 16, le),
                rd64(blob, off + 32, le),
            )
        };
        if p_type == 1 && p_filesz != 0 {
            let start = p_offset as usize;
            let end = start + p_filesz as usize;
            if end <= blob.len() {
                chunks.push((p_vaddr, blob[start..end].to_vec()));
            }
        }
    }

    if chunks.is_empty() {
        return Err(FirmwareParseError::new(
            "ELF contains no loadable segments".to_string(),
        ));
    }
    chunks.sort_by_key(|c| c.0);
    let mut payload: Vec<u8> = Vec::new();
    for (_, data) in &chunks {
        payload.extend_from_slice(data);
    }
    Ok((payload, e_entry, chunks[0].0, sections, elf_machine_name(e_machine)))
}

// ----------------------------------------------------------------------
// load_firmware - file dispatch
// ----------------------------------------------------------------------

/// Load a .hex / .elf image and return a FirmwareImage of verified metadata.
pub fn load_firmware(path: &str) -> Result<FirmwareImage, FirmwareParseError> {
    let exists = fs::metadata(path).map(|m| m.is_file()).unwrap_or(false);
    if !exists {
        return Err(FirmwareParseError::new(format!("file not found: {}", path)));
    }
    let bytes = fs::read(path)
        .map_err(|e| FirmwareParseError::new(format!("file not found: {} ({})", path, e)))?;
    if bytes.is_empty() {
        return Err(FirmwareParseError::new("file is empty".to_string()));
    }

    let is_elf_magic = bytes.len() >= 2 && bytes[0] == 0x7f && bytes[1] == b'E';
    if is_elf_magic || path.to_lowercase().ends_with(".elf") {
        let (data, entry, load, sections, machine) = parse_elf(&bytes)?;
        return Ok(FirmwareImage::elf(path, data, entry, load, sections, machine));
    }

    let lower = path.to_lowercase();
    if lower.ends_with(".hex") || lower.ends_with(".ihex") || bytes[0] == b':' {
        let text = String::from_utf8_lossy(&bytes).into_owned();
        let (data, load, entry) = parse_intel_hex(&text)?;
        return Ok(FirmwareImage::ihex(path, data, entry, load));
    }

    Err(FirmwareParseError::new(
        "unsupported image: expected Intel HEX (.hex) or ELF (.elf)".to_string(),
    ))
}

// ----------------------------------------------------------------------
// GPIO pin-profile JSON parser (text -> pin -> spec structure)
// ----------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
enum JsonVal {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<JsonVal>),
    Obj(BTreeMap<String, JsonVal>),
}

struct JsonParser<'a> {
    s: &'a [u8],
    i: usize,
}

impl<'a> JsonParser<'a> {
    fn new(s: &'a str) -> Self {
        JsonParser {
            s: s.as_bytes(),
            i: 0,
        }
    }

    fn ws(&mut self) {
        while self.i < self.s.len() && matches!(self.s[self.i], b' ' | b'\t' | b'\n' | b'\r') {
            self.i += 1;
        }
    }

    fn peek(&mut self) -> Option<u8> {
        self.ws();
        self.s.get(self.i).copied()
    }

    fn eat(&mut self, c: u8) -> bool {
        if self.peek() == Some(c) {
            self.i += 1;
            true
        } else {
            false
        }
    }

    fn eat_lit(&mut self, lit: &[u8]) -> bool {
        if self.s.len() - self.i >= lit.len() && &self.s[self.i..self.i + lit.len()] == lit {
            self.i += lit.len();
            true
        } else {
            false
        }
    }

    fn parse_value(&mut self) -> Result<JsonVal, String> {
        let c = match self.peek() {
            Some(c) => c,
            None => return Err("unexpected end of input".to_string()),
        };
        match c {
            b'{' => {
                self.i += 1;
                let mut obj = BTreeMap::new();
                if self.eat(b'}') {
                    return Ok(JsonVal::Obj(obj));
                }
                loop {
                    let key = self.parse_string()?;
                    if !self.eat(b':') {
                        return Err("expected ':'".to_string());
                    }
                    let v = self.parse_value()?;
                    obj.insert(key, v);
                    if self.eat(b',') {
                        continue;
                    }
                    if self.eat(b'}') {
                        break;
                    }
                    return Err("expected ',' or '}'".to_string());
                }
                Ok(JsonVal::Obj(obj))
            }
            b'[' => {
                self.i += 1;
                let mut arr = Vec::new();
                if self.eat(b']') {
                    return Ok(JsonVal::Arr(arr));
                }
                loop {
                    let v = self.parse_value()?;
                    arr.push(v);
                    if self.eat(b',') {
                        continue;
                    }
                    if self.eat(b']') {
                        break;
                    }
                    return Err("expected ',' or ']'".to_string());
                }
                Ok(JsonVal::Arr(arr))
            }
            b'"' => Ok(JsonVal::Str(self.parse_string()?)),
            b't' => {
                if self.eat_lit(b"true") {
                    Ok(JsonVal::Bool(true))
                } else {
                    Err("invalid literal".to_string())
                }
            }
            b'f' => {
                if self.eat_lit(b"false") {
                    Ok(JsonVal::Bool(false))
                } else {
                    Err("invalid literal".to_string())
                }
            }
            b'n' => {
                if self.eat_lit(b"null") {
                    Ok(JsonVal::Null)
                } else {
                    Err("invalid literal".to_string())
                }
            }
            c if c == b'-' || (b'0'..=b'9').contains(&c) => self.parse_number(),
            _ => Err(format!("unexpected byte {}", c)),
        }
    }

    fn parse_string(&mut self) -> Result<String, String> {
        if self.peek() != Some(b'"') {
            return Err("expected string".to_string());
        }
        self.i += 1;
        let mut out = String::new();
        loop {
            let c = match self.peek() {
                Some(c) => c,
                None => return Err("unterminated string".to_string()),
            };
            self.i += 1;
            if c == b'"' {
                return Ok(out);
            }
            if c == b'\\' {
                let e = self.peek().ok_or_else(|| "unterminated escape".to_string())?;
                self.i += 1;
                match e {
                    b'"' => out.push('"'),
                    b'\\' => out.push('\\'),
                    b'/' => out.push('/'),
                    b'b' => out.push('\u{0008}'),
                    b'f' => out.push('\u{000C}'),
                    b'n' => out.push('\n'),
                    b'r' => out.push('\r'),
                    b't' => out.push('\t'),
                    b'u' => {
                        let hex = std::str::from_utf8(&self.s[self.i..self.i + 4])
                            .ok()
                            .and_then(|s| u32::from_str_radix(s, 16).ok());
                        self.i += 4;
                        let cp = hex.unwrap_or(0);
                        out.push(char::from_u32(cp).unwrap_or('\u{FFFD}'));
                    }
                    _ => return Err("invalid escape".to_string()),
                }
            } else {
                out.push(c as char);
            }
        }
    }

    fn parse_number(&mut self) -> Result<JsonVal, String> {
        let start = self.i;
        while self.i < self.s.len() {
            let c = self.s[self.i];
            if (b'0'..=b'9').contains(&c) || c == b'-' || c == b'+' || c == b'.' || c == b'e' || c == b'E'
            {
                self.i += 1;
            } else {
                break;
            }
        }
        let text = std::str::from_utf8(&self.s[start..self.i]).map_err(|_| "invalid number".to_string())?;
        let v: f64 = text.parse().map_err(|_| "invalid number".to_string())?;
        Ok(JsonVal::Num(v))
    }
}

/// Parse a JSON text into a flat object-of-objects (pin -> spec).  Returns
/// the per-pin specs with recognised fields mapped; unknown fields are
/// dropped (the typed narrowing documented in gpio_model's header).
pub fn parse_pin_profile(
    text: &str,
) -> Result<BTreeMap<String, ProfileSpec>, FirmwareParseError> {
    let mut p = JsonParser::new(text);
    let v = p
        .parse_value()
        .map_err(|e| FirmwareParseError::new(format!("pin profile is not valid JSON: {}", e)))?;
    let obj = match v {
        JsonVal::Obj(obj) => obj,
        _ => {
            return Err(FirmwareParseError::new(
                "pin profile must be a JSON object of pin -> spec".to_string(),
            ))
        }
    };
    let mut out = BTreeMap::new();
    for (pin, val) in obj {
        let spec_map = match val {
            JsonVal::Obj(m) => m,
            _ => {
                return Err(FirmwareParseError::new(
                    "pin profile must be a JSON object of pin -> spec".to_string(),
                ))
            }
        };
        let mut spec = ProfileSpec::default();
        for (k, v) in spec_map {
            match v {
                JsonVal::Str(s) => {
                    if k == "mode" {
                        spec.mode = s;
                    }
                }
                JsonVal::Num(n) => {
                    if k == "level" {
                        spec.level = Some(n as i32);
                    } else if k == "vhigh" {
                        spec.vhigh = n;
                    } else if k == "freq_hz" {
                        spec.freq_hz = Some(n);
                    } else if k == "duty" {
                        spec.duty = Some(n);
                    } else if k == "phase_s" {
                        spec.phase_s = Some(n);
                    }
                }
                _ => {}
            }
        }
        out.insert(pin, spec);
    }
    Ok(out)
}

