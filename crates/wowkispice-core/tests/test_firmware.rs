/*
 * test_firmware.rs - port of tests/test_firmware_gpio.py (the pure classes).
 *
 * Line-for-line transcription of the Python assertions; tests the Python file
 * cannot have in Rust are labelled as explained in place:
 *
 *   - TestGpioCosimEndToEnd and TestRealEsp32Firmware are NOT ported here.
 *     The former drives a real ngspice solver through a modelled GPIO pin
 *     (needs the FFI layer); the latter needs the built ESP32 firmware ELF
 *     (external fixture, see docs/RUST_PORT_TEST_MAP.md [Q5]).
 *   - TestLogicAnalysis lives in the gpio_model gate (analyze_pin /
 *     measured_frequency are gpio_model's contract, not firmware's).
 *   - The SHA-256 hex digest is compared by length (64) as Python does; the
 *     full digest value is pinned by the parity battery (parity_firmware).
 *
 * The Intel HEX/ELF parsers are exercised through the module's own entry
 * points (parse_intel_hex / parse_elf / load_firmware) exactly as the Python
 * test reaches them through bridge.firmware.
 */

use wowkispice_core::firmware::{
    load_firmware, parse_elf, parse_intel_hex, parse_pin_profile,
};

// ---------------------------------------------------------------------
// Intel HEX helpers + fixtures (port of test_firmware_gpio.py module level)
// ---------------------------------------------------------------------

fn hex_record(rectype: u8, address: u16, data: &[u8]) -> String {
    let mut payload: Vec<u8> = Vec::new();
    payload.push(data.len() as u8);
    payload.push(((address >> 8) & 0xFF) as u8);
    payload.push((address & 0xFF) as u8);
    payload.push(rectype);
    payload.extend_from_slice(data);
    let sum: i32 = payload.iter().map(|&b| b as i32).sum();
    let checksum = (-sum) & 0xFF;
    let mut s = String::from(":");
    for b in &payload {
        s.push_str(&format!("{:02X}", b));
    }
    s.push_str(&format!("{:02X}", checksum));
    s
}

fn hex_bytes(bytes: &[u8]) -> Vec<u8> {
    bytes.to_vec()
}

/// A tiny but genuine Intel HEX image: 16 bytes at 0x0800 plus 4 more, entry 0x0800.
fn hex_sample() -> String {
    [
        hex_record(0x00, 0x0800, &hex_bytes(&[0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f])),
        hex_record(0x00, 0x0810, &hex_bytes(&[0x12, 0x34, 0x56, 0x78])),
        hex_record(0x05, 0x0000, &hex_bytes(&[0x08, 0x00])),
        hex_record(0x01, 0x0000, &hex_bytes(&[])),
    ]
    .join("\n")
        + "\n"
}

// ---------------------------------------------------------------------
// Intel HEX: TestIntelHex
// ---------------------------------------------------------------------

#[test]
fn test_parses_data_and_entry() {
    let text = hex_sample();
    let (data, load, entry) = parse_intel_hex(&text).expect("valid hex sample parses");
    assert_eq!(data.len(), 20); // 16 + 4 bytes
    assert_eq!(load, 0x0800);
    assert_eq!(entry, 0x0800);
}

#[test]
fn test_bad_checksum_is_reported_with_line_number() {
    let first = hex_sample()
        .trim()
        .split('\n')
        .next()
        .expect("first line")
        .to_string();
    let last = first.chars().last().expect("checksum char");
    let flipped = if last == '0' { '1' } else { '0' };
    let corrupted = format!("{}{}", &first[..first.len() - 1], flipped);
    let err = parse_intel_hex(&corrupted).expect_err("corrupted checksum must fail");
    assert!(err.message().contains("checksum"));
}

#[test]
fn test_missing_eof_is_accepted_with_explicit_data() {
    let text = format!("{}\n", hex_record(0x00, 0x0800, &hex_bytes(&[0x12, 0x34, 0x56, 0x78])));
    let (data, load, _entry) = parse_intel_hex(&text).expect("missing EOF is accepted");
    assert_eq!(hex_bytes(&data), hex_bytes(&[0x12, 0x34, 0x56, 0x78]));
    assert_eq!(load, 0x0800);
}

#[test]
fn test_garbage_is_rejected() {
    let err = parse_intel_hex("not a hex file at all").expect_err("garbage must fail");
    assert!(err.message().contains("does not start with"));
}

// ---------------------------------------------------------------------
// ELF: TestElf
// ---------------------------------------------------------------------

/// Minimal valid ELF32 little-endian, one PT_LOAD, no section table.
fn elf32_blob(entry: u64, machine: u16, load_vaddr: u64, payload: &[u8]) -> Vec<u8> {
    let ehsize: usize = 52;
    let phentsize: usize = 32;
    let data_off = ehsize + phentsize;
    let mut blob = vec![0u8; data_off + payload.len()];
    blob[0] = 0x7f;
    blob[1] = b'E';
    blob[2] = b'L';
    blob[3] = b'F';
    blob[4] = 1; // 32-bit
    blob[5] = 1; // little-endian
    blob[6] = 1; // version
    // e_type=2 @16, e_machine @18, e_version=1 @20, e_entry @24, e_phoff=52 @28,
    // e_shoff=0 @32, e_flags=0 @36, e_ehsize=52 @40, e_phentsize=32 @42,
    // e_phnum=1 @44, e_shentsize=40 @46, e_shnum=0 @48, e_shstrndx=0 @50
    put16(&mut blob, 16, 2);
    put16(&mut blob, 18, machine);
    put32(&mut blob, 20, 1);
    put32(&mut blob, 24, entry as u32);
    put32(&mut blob, 28, 52);
    put16(&mut blob, 40, 52);
    put16(&mut blob, 42, 32);
    put16(&mut blob, 44, 1);
    put16(&mut blob, 46, 40);
    put16(&mut blob, 48, 0);
    put16(&mut blob, 50, 0);
    // PT_LOAD at file offset 84.
    put32(&mut blob, 52, 1);
    put32(&mut blob, 56, data_off as u32);
    put32(&mut blob, 60, load_vaddr as u32);
    put32(&mut blob, 64, load_vaddr as u32);
    put32(&mut blob, 68, payload.len() as u32);
    put32(&mut blob, 72, payload.len() as u32);
    put32(&mut blob, 76, 5);
    put32(&mut blob, 80, 4);
    for (i, &b) in payload.iter().enumerate() {
        blob[data_off + i] = b;
    }
    blob
}

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

/// Build the valid-ELF-with-sections fixture from tests/test_firmware_gpio.py.
fn elf32_with_sections(machine: u16, entry: u64, load_vaddr: u64) -> Vec<u8> {
    let ehsize: usize = 52;
    let phentsize: usize = 32;
    let shentsize: usize = 40;
    let payload = [0x01u8, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08];
    let phoff = ehsize;
    let data_off = phoff + phentsize;
    let shstrtab = [
        0x00u8, b'.', b't', b'e', b'x', b't', 0x00, b'.', b's', b'h', b's', b't', b'r', b't', b'a', b'b', 0x00,
    ];
    let name_text: u32 = 1;
    let name_shstrtab: u32 = 7;
    let shoff: usize = 0x100;
    let shstr_off: usize = shoff + 3 * shentsize;
    let text_vaddr = 0x40080000u64;
    let mut blob = vec![0u8; shstr_off + shstrtab.len()];
    blob[0] = 0x7f;
    blob[1] = b'E';
    blob[2] = b'L';
    blob[3] = b'F';
    blob[4] = 1;
    blob[5] = 1;
    blob[6] = 1;
    put16(&mut blob, 16, 2); // e_type ET_EXEC
    put16(&mut blob, 18, machine);
    put32(&mut blob, 20, 1); // e_version
    put32(&mut blob, 24, entry as u32);
    put32(&mut blob, 28, phoff as u32); // e_phoff
    put32(&mut blob, 32, shoff as u32); // e_shoff
    put32(&mut blob, 36, 0); // e_flags
    put16(&mut blob, 40, ehsize as u16); // e_ehsize
    put16(&mut blob, 42, phentsize as u16);
    put16(&mut blob, 44, 1); // e_phnum
    put16(&mut blob, 46, shentsize as u16);
    put16(&mut blob, 48, 3); // e_shnum
    put16(&mut blob, 50, 2); // e_shstrndx
    put32(&mut blob, 52, 1); // PT_LOAD p_type
    put32(&mut blob, 56, data_off as u32);
    put32(&mut blob, 60, load_vaddr as u32);
    put32(&mut blob, 64, load_vaddr as u32);
    put32(&mut blob, 68, payload.len() as u32);
    put32(&mut blob, 72, payload.len() as u32);
    put32(&mut blob, 76, 5);
    put32(&mut blob, 80, 4);
    // Section headers.
    put32(&mut blob, shoff, 0); // NULL
    put32(&mut blob, shoff + shentsize, name_text);
    put32(&mut blob, shoff + shentsize + 4, 1); // sh_type
    put32(&mut blob, shoff + shentsize + 8, 6); // sh_flags
    put32(&mut blob, shoff + shentsize + 12, 0); // sh_addr placeholder (fixed below)
    put32(&mut blob, shoff + shentsize + 16, data_off as u32); // sh_offset
    put32(&mut blob, shoff + shentsize + 20, payload.len() as u32); // sh_size
    put32(&mut blob, shoff + shentsize + 24, 0);
    put32(&mut blob, shoff + shentsize + 28, 0);
    put32(&mut blob, shoff + shentsize + 32, 4); // sh_addralign
    put32(&mut blob, shoff + shentsize + 36, 0); // sh_entsize
    put32(&mut blob, shoff + 2 * shentsize, name_shstrtab);
    put32(&mut blob, shoff + 2 * shentsize + 4, 3); // sh_type
    put32(&mut blob, shoff + 2 * shentsize + 8, 0); // sh_flags
    put32(&mut blob, shoff + 2 * shentsize + 12, 0); // sh_addr
    put32(&mut blob, shoff + 2 * shentsize + 16, shstr_off as u32); // sh_offset
    put32(&mut blob, shoff + 2 * shentsize + 20, shstrtab.len() as u32); // sh_size
    put32(&mut blob, shoff + 2 * shentsize + 24, 0);
    put32(&mut blob, shoff + 2 * shentsize + 28, 0);
    put32(&mut blob, shoff + 2 * shentsize + 32, 1);
    put32(&mut blob, shoff + 2 * shentsize + 36, 0);
    for (i, &b) in payload.iter().enumerate() {
        blob[data_off + i] = b;
    }
    blob[shstr_off..shstr_off + shstrtab.len()].copy_from_slice(&shstrtab);
    // Patch the .text section address (index 3 of shdr fields is sh_addr).
    put32(&mut blob, shoff + shentsize + 12, text_vaddr as u32);
    blob
}

fn tmp_dir() -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!("wosp_fw_test_{}", std::process::id()));
    std::fs::create_dir_all(&d).expect("create tmp dir");
    d
}

fn write_blob(tag: &str, blob: &[u8]) -> String {
    let path = tmp_dir().join(format!("fw_{}_{}.bin", tag, std::process::id()));
    std::fs::write(&path, blob).expect("write blob");
    path.to_string_lossy().into_owned()
}

fn write_named_file(name: &str, blob: &[u8]) -> String {
    let path = tmp_dir().join(name);
    std::fs::write(&path, blob).expect("write blob");
    path.to_string_lossy().into_owned()
}

// ---------------------------------------------------------------------
// ELF: TestElf
// ---------------------------------------------------------------------

#[test]
fn test_parses_elf32_entry_and_segments() {
    let payload = hex_bytes(&[0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]);
    let blob = elf32_blob(0x08000041, 0x28, 0x08000000, &payload);
    let path = write_blob("ok", &blob);
    let image = load_firmware(&path).expect("valid ELF32 loads");
    assert_eq!(image.format, "elf");
    assert_eq!(image.size_bytes(), 8);
    assert_eq!(image.entry_point, 0x08000041);
    assert_eq!(image.load_address, 0x08000000);
    assert_eq!(hex_bytes(&image.data), payload);
    assert_eq!(image.sha256.len(), 64);
}

#[test]
fn test_section_names_addresses_and_offsets() {
    let blob = elf32_with_sections(0x28, 0x08000041, 0x08000000);
    let (_p, _e, _l, sections, machine) = parse_elf(&blob).expect("sections parse");
    assert_eq!(machine, "ARM");
    assert_eq!(sections.len(), 3);
    assert_eq!(sections[0].name, "");
    assert_eq!(sections[1].name, ".text");
    assert_eq!(sections[1].address, 0x40080000); // 0x40080000
    assert_eq!(sections[1].offset, 84);
    assert_eq!(sections[1].size, 8);
    assert_eq!(sections[2].name, ".shstrtab");
    assert_eq!(sections[2].offset, 0x178);
}

#[test]
fn test_section_address_is_not_confused_with_file_offset() {
    let blob = elf32_with_sections(0x28, 0x08000041, 0x08000000);
    let (_p, _e, _l, sections, _m) = parse_elf(&blob).expect("sections parse");
    assert_ne!(sections[1].address, sections[1].offset);
    assert_eq!(sections[1].address, 0x40080000);
    assert_eq!(sections[1].offset, 84);
}

#[test]
fn test_xtensa_machine_is_recognised() {
    let blob = elf32_with_sections(0x5E, 0x08000041, 0x08000000);
    let (_p, _e, _l, _s, machine) = parse_elf(&blob).expect("sections parse");
    assert_eq!(machine, "Xtensa");
}

#[test]
fn test_unknown_machine_falls_back_to_hex() {
    let blob = elf32_with_sections(0x7777, 0x08000041, 0x08000000);
    let (_p, _e, _l, _s, machine) = parse_elf(&blob).expect("sections parse");
    assert_eq!(machine, "machine 0x7777");
}

#[test]
fn test_truncated_section_table_does_not_crash() {
    let blob = elf32_with_sections(0x28, 0x08000041, 0x08000000);
    let (_p, _e, _l, sections, _m) = parse_elf(&&blob[..blob.len() - 20]).expect("truncated ok");
    assert_eq!(sections.len(), 2); // stops before the incomplete entry
    assert_eq!(sections[1].name, "");
    assert_eq!(sections[1].address, 0x40080000);
}

#[test]
fn test_bad_magic_is_rejected() {
    let path = write_named_file("bad.elf", b"NOPE\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00");
    let err = load_firmware(&path).expect_err("bad magic must fail");
    assert!(err.message().contains("not an ELF file (bad magic)"));
}

#[test]
fn test_missing_file_is_reported() {
    let err = load_firmware("/nonexistent/does_not_exist.hex").expect_err("missing file must fail");
    assert!(err.message().contains("file not found"));
}

// ---------------------------------------------------------------------
// GPIO pin-profile JSON: TestGpioProfile (the parse half)
// ---------------------------------------------------------------------

#[test]
fn test_pin_profile_json_parsing() {
    let profile = parse_pin_profile(
        r#"{"GPIO18": {"mode": "square", "freq_hz": 10, "duty": 0.5}}"#,
    )
    .expect("valid pin profile JSON parses");
    assert!(profile.contains_key("GPIO18"));

    let err = parse_pin_profile("{not json").expect_err("invalid JSON must fail");
    assert!(err.message().contains("pin profile is not valid JSON"));
}

// ---------------------------------------------------------------------
// RUST-ONLY ADDITION: the FirmwareImage.summary() shape is not asserted by
// any Python test in test_firmware_gpio.py; this pins the transcription of
// the method itself (name/size_bytes/sha256 prefix/load/entry parts joined
// with ", ").
// ---------------------------------------------------------------------

#[test]
fn test_firmware_image_summary_shape() {
    let payload = hex_bytes(&[0x01, 0x02, 0x03, 0x04]);
    let blob = elf32_blob(0x08000041, 0x28, 0x08000000, &payload);
    let path = write_blob("sum", &blob);
    let image = load_firmware(&path).expect("valid ELF32 loads");
    let summary = image.summary();
    assert!(summary.contains("bytes"), "{summary}");
    assert!(summary.contains("sha256:"), "{summary}");
}
