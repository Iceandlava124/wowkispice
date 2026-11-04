/*
 * esp32_regs.rs - port of bridge/esp32_regs.py.
 *
 * The handful of ESP32 registers WOSP actually touches, transcribed from the
 * ESP-IDF 6.1.0 SoC headers (sens_reg.h, gpio_reg.h, reg_base.h) exactly as
 * the Python module documents them, so the bridge addresses the same
 * locations the firmware does rather than re-deriving them by hand.
 *
 * Every register has two aliases, and the port keeps both: the *data* alias
 * (DR_REG_*, 0x3FF4xxxx) is what ordinary C code reaches through the
 * SENS/GPIO structs and what firmware reads; the instruction-fetch alias
 * (MMU_IPA_*, 0x6000xxxx) is decoded by QEMU too.
 *
 * PARITY CONTRACT
 *
 *   tests/test_esp32_regs.py    base addresses, GPIO_OUT/ENABLE, gate_bit
 *                               range checks, every SENS_MEAS_START1 field,
 *                               sar1_result packing and its range error
 *
 * crates/parity/src/bin/parity_esp32_regs.rs and
 * crates/parity/python/esp32_regs/parity_esp32_regs.rs cross-check both
 * implementations over a shared battery of inputs (the battery is NOT
 * transcribed from the tests: register values, out-of-range pins and raws,
 * and read_gate() calls through a fake emulated chip).
 *
 * WHAT IS NOT PORTED, AND WHY IT IS NOT A BUG
 *
 *   1. read_gate() takes a duck-typed `client` in Python (anything with a
 *      .readl(addr) method).  The port models that surface as the RegReader
 *      trait instead - same call, same evaluation order (Python evaluates
 *      client.readl() BEFORE gate_bit(), so a bad pin still performs one
 *      read; the port does the same and the battery pins it down).
 *   2. Python ints are arbitrary precision; addresses and data words are
 *      u64 here.  Every value the module produces fits.
 *   3. GPIO_PIN_REG is named gpio_pin_reg: rustc's non_snake_case lint would
 *      otherwise fail the -D warnings build gate.  Every other name matches
 *      the Python spelling exactly.
 *   4. `pin` is i64.  Python also accepts floats (and would then raise
 *      TypeError at `1 << pin`); typed integer parameters are this port's
 *      contract, matching the tests, which pass ints only.
 *   5. gpio_pin_reg computes in wrapping i64, which equals Python's integer
 *      result modulo 2^64 - bit-for-bit identical for every pin whose Python
 *      result is non-negative (pin >= -268232226, far beyond any real use).
 *      More negative pins differ only in sign representation, on an address
 *      no caller can use either way.
 */

use std::fmt;

// ---------------------------------------------------------------- base addrs
pub const DR_REG_GPIO_BASE: u64 = 0x3FF44000;
pub const DR_REG_SENS_BASE: u64 = 0x3FF48800;
pub const MMU_IPA_GPIO_BASE: u64 = 0x60004000;
pub const MMU_IPA_SENS_BASE: u64 = 0x60009000;

// -------------------------------------------------------------------- GPIO
// GPIO_OUT_REG    : GPIO0~31 output value
// GPIO_ENABLE_REG : GPIO0~31 output enable
pub const GPIO_OUT_REG: u64 = DR_REG_GPIO_BASE + 0x0004;
pub const GPIO_ENABLE_REG: u64 = DR_REG_GPIO_BASE + 0x0020;

/// Per-pin register; on the original ESP32 it carries only interrupt cfg.
///
/// Python: `GPIO_PIN_REG(pin)` - no bounds check there either.
pub fn gpio_pin_reg(pin: i64) -> u64 {
    (DR_REG_GPIO_BASE as i64)
        .wrapping_add(0x0088)
        .wrapping_add(pin.wrapping_mul(4)) as u64
}

/// Errors carrying Python's ValueError messages verbatim (tests and the
/// parity battery compare them as text).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RegError {
    /// `gate_bit`: "GPIO{pin} is not in the 32-bit OUT/ENABLE word"
    GpioNotInWord(i64),
    /// `sar1_result`: "ADC raw {raw} out of range 0..65535"
    AdcRawOutOfRange(i64),
}

impl fmt::Display for RegError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RegError::GpioNotInWord(pin) => {
                write!(
                    f,
                    "GPIO{} is not in the 32-bit OUT/ENABLE word",
                    pin
                )
            }
            RegError::AdcRawOutOfRange(raw) => {
                write!(
                    f,
                    "ADC raw {} out of range 0..{}",
                    raw, MEAS1_DATA_SAR
                )
            }
        }
    }
}

impl std::error::Error for RegError {}

/// Bit mask for a low-numbered GPIO in the 32-bit OUT/ENABLE words.
pub fn gate_bit(pin: i64) -> Result<u64, RegError> {
    if !(0..32).contains(&pin) {
        return Err(RegError::GpioNotInWord(pin));
    }
    Ok(1u64 << (pin as u32))
}

// --------------------------------------------------------------------- SENS
// SENS_SAR_MEAS_START1_REG, the RTC SAR ADC1 controller. This is the register
// adc_oneshot_ll_* pokes, and the one a co-simulation bridge must model.
pub const SENS_SAR_MEAS_START1_REG: u64 = DR_REG_SENS_BASE + 0x0054;

pub const MEAS1_DATA_SAR: u64 = 0x0000FFFF; // bits [15:0]  conversion result
pub const MEAS1_DONE_SAR: u64 = 1 << 16; // bit  16     RO, set when conversion ends
pub const MEAS1_START_SAR: u64 = 1 << 17; // bit  17     SW start conversion
pub const MEAS1_START_FORCE: u64 = 1 << 18; // bit  18     select SW (not ULP) start
pub const SAR1_EN_PAD: u64 = 0x00000FFF << 19; // bits [30:19] channel enable bitmap
pub const SAR1_EN_PAD_FORCE: u64 = 1 << 31; // bit  31     select SW (not ULP) pad enable

/// Pack a 12-bit conversion result into a MEAS_START1 word, done bit set.
///
/// This is the word an emulated ADC model must present to the firmware, i.e.
/// what adc_oneshot_ll_get_event() and adc_oneshot_ll_get_raw_result() read.
pub fn sar1_result(raw: i64) -> Result<u64, RegError> {
    if !(0..=MEAS1_DATA_SAR as i64).contains(&raw) {
        return Err(RegError::AdcRawOutOfRange(raw));
    }
    Ok((raw as u64 & MEAS1_DATA_SAR) | MEAS1_DONE_SAR)
}

/// The emulated chip's register-read surface (Python: any object with a
/// `.readl(addr)` method - see the header note on evaluation order).
pub trait RegReader {
    fn readl(&mut self, addr: u64) -> u64;
}

/// Read a gate-drive pin's output level out of the emulated chip.
///
/// Evaluation order matters and matches Python: the read happens before the
/// `gate_bit` range check, so a bad pin still performs one read.
pub fn read_gate<R: RegReader>(chip: &mut R, pin: i64) -> Result<bool, RegError> {
    let word = chip.readl(GPIO_OUT_REG);
    let bit = gate_bit(pin)?;
    Ok((word & bit) != 0)
}
