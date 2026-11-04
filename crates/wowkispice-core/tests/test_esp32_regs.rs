/*
 * test_esp32_regs.rs - port of tests/test_esp32_regs.py.
 *
 * Line-for-line transcription of the Python assertions; tests the Python
 * file does not have are labelled `// RUST-ONLY ADDITION`.
 */

use wowkispice_core::esp32_regs::{
    gate_bit, gpio_pin_reg, read_gate, sar1_result, GPIO_ENABLE_REG, GPIO_OUT_REG,
    MEAS1_DATA_SAR, MEAS1_DONE_SAR, MEAS1_START_FORCE, MEAS1_START_SAR, MMU_IPA_GPIO_BASE,
    DR_REG_GPIO_BASE, DR_REG_SENS_BASE, SAR1_EN_PAD,
    SAR1_EN_PAD_FORCE, SENS_SAR_MEAS_START1_REG, RegError, RegReader,
};

// ---------------------------------------------------------------- base addrs

#[test]
fn test_gpio_base_is_3ff44000() {
    // documented in esp32_regs.py as DR_REG_GPIO_BASE
    assert_eq!(DR_REG_GPIO_BASE, 0x3FF44000);
}

#[test]
fn test_sens_base_is_3ff48800() {
    assert_eq!(DR_REG_SENS_BASE, 0x3FF48800);
}

#[test]
fn test_instruction_fetch_alias_is_60004000() {
    // MMU_IPA_GPIO_BASE - the alias the firmware does not use
    assert_eq!(MMU_IPA_GPIO_BASE, 0x60004000);
}

// ---------------------------------------------------------------- GPIO regs

#[test]
fn test_gpio_out_reg() {
    assert_eq!(GPIO_OUT_REG, 0x3FF44004);
}

#[test]
fn test_gpio_enable_reg() {
    assert_eq!(GPIO_ENABLE_REG, 0x3FF44020);
}

#[test]
fn test_gate_bit_18() {
    assert_eq!(gate_bit(18).unwrap(), 1u64 << 18);
}

#[test]
fn test_gate_bit_range() {
    for pin in [0, 17, 31] {
        assert_eq!(gate_bit(pin).unwrap(), 1u64 << pin);
    }
    for pin in [-1, 32] {
        assert!(
            gate_bit(pin).is_err(),
            "expected ValueError for pin {}",
            pin
        );
    }
}

// RUST-ONLY ADDITION: the Python test only checks that a ValueError is
// raised; the port pins the verbatim message too, because the parity
// battery and any caller-visible diagnostic depend on the exact wording.
#[test]
fn test_gate_bit_error_message_is_verbatim_python() {
    assert_eq!(
        gate_bit(-1).unwrap_err().to_string(),
        "GPIO-1 is not in the 32-bit OUT/ENABLE word"
    );
    assert_eq!(
        gate_bit(32).unwrap_err().to_string(),
        "GPIO32 is not in the 32-bit OUT/ENABLE word"
    );
}

// ---------------------------------------------------------------- SENS regs

#[test]
fn test_sar_meas_start1_reg() {
    // sens_reg.h: SENS_SAR_MEAS_START1_REG = 0x3FF48854
    assert_eq!(SENS_SAR_MEAS_START1_REG, 0x3FF48854);
}

#[test]
fn test_measure1_data_sar() {
    assert_eq!(MEAS1_DATA_SAR, 0x0000FFFF);
}

#[test]
fn test_measure1_done_sar() {
    assert_eq!(MEAS1_DONE_SAR, 1 << 16);
}

#[test]
fn test_measure1_start_sar() {
    assert_eq!(MEAS1_START_SAR, 1 << 17);
}

#[test]
fn test_measure1_start_force() {
    assert_eq!(MEAS1_START_FORCE, 1 << 18);
}

#[test]
fn test_sar1_en_pad() {
    assert_eq!(SAR1_EN_PAD, 0x00000FFF << 19);
}

#[test]
fn test_sar1_en_pad_force() {
    assert_eq!(SAR1_EN_PAD_FORCE, 1 << 31);
}

#[test]
fn test_sar1_result_pack() {
    // 12-bit 0x0BAD packed with the done bit set
    let word = sar1_result(0x0BAD).unwrap();
    assert_eq!(word & 0xFFFF, 0x0BAD);
    assert_ne!(word & MEAS1_DONE_SAR, 0);
}

#[test]
fn test_sar1_result_rejects_out_of_range() {
    assert!(
        sar1_result(0x10000).is_err(),
        "expected ValueError for raw > 0xFFFF"
    );
}

// RUST-ONLY ADDITION: message wording, same reason as gate_bit above.
#[test]
fn test_sar1_result_error_message_is_verbatim_python() {
    assert_eq!(
        sar1_result(0x10000).unwrap_err().to_string(),
        "ADC raw 65536 out of range 0..65535"
    );
    assert_eq!(
        sar1_result(-1).unwrap_err().to_string(),
        "ADC raw -1 out of range 0..65535"
    );
}

// --------------------------------------------------------------- read_gate

// RUST-ONLY ADDITION: read_gate() has no Python test (it needs an emulated
// chip); the port's RegReader trait is checked against the Python function's
// documented expression `(client.readl(GPIO_OUT_REG) & gate_bit(pin)) != 0`,
// including the evaluation-order detail that a bad pin still performs one
// read before gate_bit raises.
struct FakeChip {
    word: u64,
    reads: Vec<u64>,
}

impl RegReader for FakeChip {
    fn readl(&mut self, addr: u64) -> u64 {
        self.reads.push(addr);
        self.word
    }
}

#[test]
fn test_read_gate_reads_the_out_word_and_tests_the_bit() {
    let mut chip = FakeChip { word: 0x0004_0000, reads: Vec::new() };
    assert!(read_gate(&mut chip, 18).unwrap());
    assert!(!read_gate(&mut chip, 17).unwrap());
    assert_eq!(chip.reads, vec![GPIO_OUT_REG, GPIO_OUT_REG]);

    let mut zero = FakeChip { word: 0, reads: Vec::new() };
    assert!(!read_gate(&mut zero, 5).unwrap());

    let mut all = FakeChip { word: 0xFFFF_FFFF, reads: Vec::new() };
    assert!(read_gate(&mut all, 31).unwrap());
    assert!(read_gate(&mut all, 0).unwrap());
}

#[test]
fn test_read_gate_with_a_bad_pin_still_reads_then_fails() {
    let mut chip = FakeChip { word: 0, reads: Vec::new() };
    let err = read_gate(&mut chip, 32).unwrap_err();
    assert_eq!(
        err.to_string(),
        "GPIO32 is not in the 32-bit OUT/ENABLE word"
    );
    // Python evaluates client.readl(...) before gate_bit(...): one read.
    assert_eq!(chip.reads.len(), 1);
    assert_eq!(chip.reads[0], GPIO_OUT_REG);
    // The error type is the same one gate_bit produces.
    assert_eq!(err, RegError::GpioNotInWord(32));
}

// RUST-ONLY ADDITION: gpio_pin_reg is the Python GPIO_PIN_REG function (the
// port must snake_case the name); Python's test file never calls it, so the
// stride is pinned here instead.
#[test]
fn test_gpio_pin_reg_stride() {
    assert_eq!(gpio_pin_reg(0), 0x3FF44088);
    assert_eq!(gpio_pin_reg(1), 0x3FF4408C);
    assert_eq!(gpio_pin_reg(31), 0x3FF44104);
    // Small negative pins stay non-negative and match Python exactly.
    assert_eq!(gpio_pin_reg(-1), 0x3FF44084);
}
