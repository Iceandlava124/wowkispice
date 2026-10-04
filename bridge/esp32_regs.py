"""
esp32_regs.py - The handful of ESP32 registers WOSP actually touches.

Values are transcribed from the ESP-IDF 6.1.0 SoC headers under
``components/soc/esp32/register/soc`` (sens_reg.h, gpio_reg.h, reg_base.h) so
the bridge addresses the same locations the firmware does, rather than
re-deriving them by hand.

One subtlety worth stating, because it is easy to get wrong: every register has
two aliases. The *data* alias (``DR_REG_*``) sits in the 0x3FF4xxxx window and
is what ordinary C code reaches through the ``SENS``/``GPIO`` structs. The
*instruction fetch / system bus* alias (``MMU_IPA_*``) is the 0x6000xxxx
window. Both are decoded by QEMU, so both are listed here, but firmware reads
the data alias.
"""

__all__ = [
    "DR_REG_GPIO_BASE", "DR_REG_SENS_BASE", "MMU_IPA_GPIO_BASE", "MMU_IPA_SENS_BASE",
    "GPIO_OUT_REG", "GPIO_ENABLE_REG", "GPIO_PIN_REG",
    "SENS_SAR_MEAS_START1_REG",
    "MEAS1_START_FORCE", "MEAS1_START_SAR", "MEAS1_DONE_SAR", "MEAS1_DATA_SAR",
    "SAR1_EN_PAD_FORCE", "SAR1_EN_PAD",
    "sar1_result", "read_gate", "gate_bit",
]

# ---------------------------------------------------------------- base addrs
DR_REG_GPIO_BASE = 0x3FF44000
DR_REG_SENS_BASE = 0x3FF48800
MMU_IPA_GPIO_BASE = 0x60004000
MMU_IPA_SENS_BASE = 0x60009000

# -------------------------------------------------------------------- GPIO
# GPIO_OUT_REG    : GPIO0~31 output value
# GPIO_ENABLE_REG : GPIO0~31 output enable
GPIO_OUT_REG = DR_REG_GPIO_BASE + 0x0004
GPIO_ENABLE_REG = DR_REG_GPIO_BASE + 0x0020


def GPIO_PIN_REG(pin):
    """Per-pin register; on the original ESP32 it carries only interrupt cfg."""
    return DR_REG_GPIO_BASE + 0x0088 + 4 * pin


def gate_bit(pin):
    """Bit mask for a low-numbered GPIO in the 32-bit OUT/ENABLE words."""
    if not 0 <= pin < 32:
        raise ValueError("GPIO%d is not in the 32-bit OUT/ENABLE word" % pin)
    return 1 << pin


# --------------------------------------------------------------------- SENS
# SENS_SAR_MEAS_START1_REG, the RTC SAR ADC1 controller. This is the register
# adc_oneshot_ll_* pokes, and the one a co-simulation bridge must model.
SENS_SAR_MEAS_START1_REG = DR_REG_SENS_BASE + 0x0054

MEAS1_DATA_SAR = 0x0000FFFF        # bits [15:0]  conversion result
MEAS1_DONE_SAR = 1 << 16           # bit  16     RO, set when conversion ends
MEAS1_START_SAR = 1 << 17          # bit  17     SW start conversion
MEAS1_START_FORCE = 1 << 18        # bit  18     select SW (not ULP) start
SAR1_EN_PAD = 0x00000FFF << 19     # bits [30:19] channel enable bitmap
SAR1_EN_PAD_FORCE = 1 << 31        # bit  31     select SW (not ULP) pad enable


def sar1_result(raw):
    """Pack a 12-bit conversion result into a MEAS_START1 word, done bit set.

    This is the word an emulated ADC model must present to the firmware, i.e.
    what adc_oneshot_ll_get_event() and adc_oneshot_ll_get_raw_result() read.
    """
    if not 0 <= raw <= MEAS1_DATA_SAR:
        raise ValueError("ADC raw %r out of range 0..%d" % (raw, MEAS1_DATA_SAR))
    return (raw & MEAS1_DATA_SAR) | MEAS1_DONE_SAR


def read_gate(client, pin):
    """Read a gate-drive pin's output level out of the emulated chip."""
    return (client.readl(GPIO_OUT_REG) & gate_bit(pin)) != 0