/*
 * parity_firmware.rs - Rust half of the firmware-parity battery.
 *
 * Computes a fixed battery of firmware facts from crates/wowkispice-core/src/
 * firmware.rs and prints KEY<TAB>VALUE lines for
 * crates/parity/python/parity_firmware.py to diff against bridge/firmware.py.
 *
 * Battery design (one fixed set of inputs, neither side derived from the
 * other's unit tests - an independent cross-implementation diff):
 *
 *   sha[i]      SHA-256 of deterministic payloads (incl. the empty payload,
 *              whose digest the Python side reports as "" - FirmwareImage's
 *              `sha256` is hashlib.sha256(data).hexdigest() if data else "").
 *   ihex[i]     Intel HEX parse results: "OK:<sha256>:<load>:<entry>" on
 *              success (sha over the decoded blob, load = min(address), entry
 *              from the 03/05 records), "ERR:<msg>" on rejection - error
 *              strings are compared as text, verbatim.
 *   elf[i]      ELF parse results: "OK:<sha256>:<entry>:<load>:<machine>" on
 *              success, "ERR:<msg>" on rejection.
 *   pin.ok      GPIO pin-profile JSON: "OK:<pin>:<mode>:<freq>:<duty>".
 *   pin.err.not_object - top-level JSON array rejected with the verbatim text.
 *   fw.<key>    load_firmware() over fixture images (hex_ok, hex_noend, elf_ok,
 *              bad_hex, bad_elf, empty, notimg, missing) via the NAME<TAB>PATH
 *              manifest - same fixture paths both sides, so path-embedding
 *              error messages compare byte-for-byte.
 *
 * The battery arrays / fixtures below must stay IDENTICAL to the driver's
 * SHA_CASES / IHEX_CASES / ELF_CASES / PIN / FW fixtures - a drift surfaces
 * immediately as a python-only/rust-only key.
 */

use std::collections::BTreeMap;
use std::fs;
use std::io::{BufWriter, Write};

use wowkispice_core::firmware::{
    self, load_firmware, parse_elf, parse_intel_hex, parse_pin_profile,
};
use wowkispice_core::gpio_model::ProfileSpec;
use wowkispice_core::pycompat::py_repr;

// ---------------------------------------------------------------- SHA battery

fn enc_sha(data: &[u8]) -> String {
    if data.is_empty() {
        String::new()
    } else {
        firmware::sha256_hex(data)
    }
}

// ---------------------------------------------------------------- Intel HEX

fn hex_record(rectype: u8, address: u16, data: &[u8]) -> String {
    let mut payload: Vec<u8> = Vec::new();
    payload.push(data.len() as u8);
    payload.push(((address >> 8) & 0xFF) as u8);
    payload.push((address & 0xFF) as u8);
    payload.push(rectype);
    payload.extend_from_slice(data);
    let sum: u32 = payload.iter().map(|&b| b as u32).sum();
    let checksum = ((256 - (sum % 256)) % 256) as u8;
    let mut s = String::from(":");
    for b in &payload {
        s.push_str(&format!("{:02X}", b));
    }
    s.push_str(&format!("{:02X}", checksum));
    s
}

fn enc_ihex(text: &str) -> String {
    match parse_intel_hex(text) {
        Ok((data, load, entry)) => format!("OK:{}:{}:{}", enc_sha(&data), load, entry),
        Err(e) => format!("ERR:{}", e.msg),
    }
}

fn ihex_battery() -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = Vec::new();

    // 0: valid sample - data + start-address + EOF
    let text = format!(
        "{}\n{}\n{}\n{}\n",
        hex_record(0x00, 0x0800, &[0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f]),
        hex_record(0x00, 0x0810, &[0x12, 0x34, 0x56, 0x78]),
        hex_record(0x05, 0x0000, &[0x08, 0x00]),
        hex_record(0x01, 0x0000, &[]),
    );
    out.push(("ihex[0]".to_string(), enc_ihex(&text)));

    // 1: bad checksum - valid record, checksum digit flipped
    let mut bad = hex_record(0x00, 0x0800, &[0x11, 0x22]);
    let last = bad.chars().last().unwrap();
    bad.pop();
    bad.push(if last == '0' { '1' } else { '0' });
    out.push(("ihex[1]".to_string(), enc_ihex(&bad)));

    // 2: garbage line
    out.push(("ihex[2]".to_string(), enc_ihex("garbage\n")));

    // 3: data record, no EOF - accepted
    let text = format!("{}\n", hex_record(0x00, 0x0800, &[0x12, 0x34, 0x56, 0x78]));
    out.push(("ihex[3]".to_string(), enc_ihex(&text)));

    // 4: data after EOF record - error on the offending line
    let text = format!(
        "{}\n{}\n{}\n",
        hex_record(0x00, 0x0800, &[0x11, 0x22]),
        hex_record(0x01, 0x0000, &[]),
        hex_record(0x00, 0x0810, &[0x33]),
    );
    out.push(("ihex[4]".to_string(), enc_ihex(&text)));

    // 5: invalid hex digits
    out.push(("ihex[5]".to_string(), enc_ihex(":ZZ00008000\n")));

    // 6: record too short (4-byte payload < the 5-byte minimum)
    out.push(("ihex[6]".to_string(), enc_ihex(":02000008\n")));

    // 7: length byte 5 does not match a 2-byte record
    out.push(("ihex[7]".to_string(), enc_ihex(":0500000800AABB\n")));

    // 8: code-only HEX (EOF only, no data)
    out.push(("ihex[8]".to_string(), enc_ihex(":00000001FF\n")));

    // 9: extended linear address (04) -> base 0x00200000, entry via 05
    let text = format!(
        "{}\n{}\n{}\n",
        hex_record(0x04, 0x0000, &[0x00, 0x20]),
        hex_record(0x00, 0x0000, &[0xAA, 0xBB]),
        hex_record(0x05, 0x0000, &[0x00, 0x20]),
    );
    out.push(("ihex[9]".to_string(), enc_ihex(&text)));

    out
}

// ---------------------------------------------------------------- ELF

fn put16(b: &mut [u8], off: usize, v: u16) {
    b[off] = (v & 0xff) as u8;
    b[off + 1] = ((v >> 8) & 0xff) as u8;
}

fn put32(b: &mut [u8], off: usize, v: u32) {
    b[off] = (v & 0xff) as u8;
    b[off + 1] = ((v >> 8) & 0xff) as u8;
    b[off + 2] = ((v >> 16) & 0xff) as u8;
    b[off + 3] = ((v >> 24) & 0xff) as u8;
}

/// Minimal ELF32 LE ET_EXEC, one PT_LOAD, no section table.
fn elf32(entry: u64, machine: u16, load: u64, payload: &[u8]) -> Vec<u8> {
    let mut blob = vec![0u8; 84 + payload.len()];
    blob[0] = 0x7f;
    blob[1] = b'E';
    blob[2] = b'L';
    blob[3] = b'F';
    blob[4] = 1; // 32-bit
    blob[5] = 1; // little-endian
    blob[6] = 1; // version
    put16(&mut blob, 16, 2); // e_type = ET_EXEC
    put16(&mut blob, 18, machine);
    put32(&mut blob, 20, 1); // e_version
    put32(&mut blob, 24, entry as u32); // e_entry
    put32(&mut blob, 28, 52); // e_phoff
    put32(&mut blob, 32, 0); // e_shoff = 0 (no sections)
    put32(&mut blob, 36, 0); // e_flags
    put16(&mut blob, 40, 52); // e_ehsize
    put16(&mut blob, 42, 32); // e_phentsize
    put16(&mut blob, 44, 1); // e_phnum
    put16(&mut blob, 46, 40); // e_shentsize
    put16(&mut blob, 48, 0); // e_shnum
    put16(&mut blob, 50, 0); // e_shstrndx
    put32(&mut blob, 52, 1); // PT_LOAD p_type
    put32(&mut blob, 56, 84); // p_offset
    put32(&mut blob, 60, load as u32); // p_vaddr
    put32(&mut blob, 64, load as u32); // p_paddr
    put32(&mut blob, 68, payload.len() as u32);
    put32(&mut blob, 72, payload.len() as u32);
    put32(&mut blob, 76, 5);
    put32(&mut blob, 80, 4);
    for (i, &b) in payload.iter().enumerate() {
        blob[84 + i] = b;
    }
    blob
}

fn enc_elf(blob: &[u8]) -> String {
    match parse_elf(blob) {
        Ok((data, entry, load, _sections, machine)) => {
            format!("OK:{}:{}:{}:{}", enc_sha(&data), entry, load, machine)
        }
        Err(e) => format!("ERR:{}", e.msg),
    }
}

fn elf_battery() -> Vec<(String, String)> {
    let payload: Vec<u8> = vec![1, 2, 3, 4, 5, 6, 7, 8];
    let mut out: Vec<(String, String)> = Vec::new();

    // 0: valid ELF32 LE, ARM, one PT_LOAD
    let blob = elf32(0x0800_0041, 0x28, 0x0800_0000, &payload);
    out.push(("elf[0]".to_string(), enc_elf(&blob)));

    // 1: bad magic
    let mut bad = blob.clone();
    bad[1] = b'X';
    out.push(("elf[1]".to_string(), enc_elf(&bad)));

    // 2: unknown class (3)
    let mut badclass = blob.clone();
    badclass[4] = 3;
    out.push(("elf[2]".to_string(), enc_elf(&badclass)));

    // 3: no loadable segments (e_phnum = 0)
    let mut noload = blob.clone();
    put16(&mut noload, 44, 0);
    out.push(("elf[3]".to_string(), enc_elf(&noload)));

    out
}

// ---------------------------------------------------------------- GPIO pin profile

const PIN_OK_JSON: &str =
    r#"{"GPIO18": {"mode": "square", "freq_hz": 1000.0, "duty": 0.5, "vhigh": 3.3}}"#;

fn enc_pin(text: &str) -> String {
    match parse_pin_profile(text) {
        Ok(map) => {
            let spec: &ProfileSpec = map.get("GPIO18").expect("battery pin GPIO18");
            let mode = spec.mode.clone();
            let freq = spec.freq_hz.unwrap_or(0.0);
            let duty = spec.duty.unwrap_or(0.0);
            format!("OK:GPIO18:{}:{}:{}", mode, py_repr(freq), py_repr(duty))
        }
        Err(e) => format!("ERR:{}", e.msg),
    }
}

// ---------------------------------------------------------------- load_firmware

struct Fixture {
    hex_ok: String,
    hex_noend: String,
    elf_ok: String,
    bad_hex: String,
    bad_elf: String,
    empty: String,
    notimg: String,
    missing: String,
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

fn fw_value(path: &str) -> String {
    match load_firmware(path) {
        Ok(img) => {
            if img.format == "elf" {
                let machine = img.machine.clone().unwrap_or_default();
                format!(
                    "OK:{}:{}:{}:{}",
                    img.sha256, img.entry_point, img.load_address, machine
                )
            } else {
                format!(
                    "OK:{}:{}:{}",
                    img.sha256, img.load_address, img.entry_point
                )
            }
        }
        Err(e) => format!("ERR:{}", e.msg),
    }
}

// ---------------------------------------------------------------- battery

fn battery(fix: &Fixture) -> Vec<(String, String)> {
    let mut out = Vec::new();

    let sha_payloads: [Vec<u8>; 3] = [Vec::new(), b"hello world".to_vec(), vec![1, 2, 3, 4, 5, 6, 7, 8]];
    for (i, data) in sha_payloads.iter().enumerate() {
        out.push((format!("sha[{}]", i), enc_sha(data)));
    }

    for (k, v) in ihex_battery() {
        out.push((k, v));
    }
    for (k, v) in elf_battery() {
        out.push((k, v));
    }

    out.push(("pin.ok".to_string(), enc_pin(PIN_OK_JSON)));
    out.push(("pin.err.not_object".to_string(), enc_pin("[1,2,3]")));

    out.push(("fw.hex_ok".to_string(), fw_value(&fix.hex_ok)));
    out.push(("fw.hex_noend".to_string(), fw_value(&fix.hex_noend)));
    out.push(("fw.elf_ok".to_string(), fw_value(&fix.elf_ok)));
    out.push(("fw.bad_hex".to_string(), fw_value(&fix.bad_hex)));
    out.push(("fw.bad_elf".to_string(), fw_value(&fix.bad_elf)));
    out.push(("fw.empty".to_string(), fw_value(&fix.empty)));
    out.push(("fw.notimg".to_string(), fw_value(&fix.notimg)));
    out.push(("fw.missing".to_string(), fw_value(&fix.missing)));

    out
}

fn main() {
    let mut args = std::env::args();
    let _prog = args.next();
    let manifest = args.next().unwrap_or_else(|| {
        eprintln!("usage: parity_firmware <manifest-file>");
        std::process::exit(2);
    });

    let map = load_manifest(&manifest);
    let fix = Fixture {
        hex_ok: fixture(&map, "hex_ok"),
        hex_noend: fixture(&map, "hex_noend"),
        elf_ok: fixture(&map, "elf_ok"),
        bad_hex: fixture(&map, "bad_hex"),
        bad_elf: fixture(&map, "bad_elf"),
        empty: fixture(&map, "empty"),
        notimg: fixture(&map, "notimg"),
        missing: fixture(&map, "missing"),
    };

    let stdout = std::io::stdout();
    let lock = stdout.lock();
    let mut writer = BufWriter::new(lock);
    for (key, value) in battery(&fix) {
        writeln!(writer, "{}\t{}", key, value).expect("stdout write");
    }
    writer.flush().expect("stdout flush");
}
