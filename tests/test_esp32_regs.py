"""test_esp32_regs.py - Unit: ESP32 register/address constants.

The constants must match the ESP-IDF 6.1.0 SoC headers the module documents
(register/soc/soc for base addresses, sens_reg.h for the SENS SAR controller)
and the datasheet for the GPIO bit assignments. The assertions come from the
docs, not from the module under test.
"""

import sys

sys.path.insert(0, ".")

from bridge import esp32_regs as regs


class TestBaseAddresses:
    def test_gpio_base_is_3ff44000(self):
        # documented in esp32_regs.py as DR_REG_GPIO_BASE
        assert regs.DR_REG_GPIO_BASE == 0x3FF44000

    def test_sens_base_is_3ff48800(self):
        assert regs.DR_REG_SENS_BASE == 0x3FF48800

    def test_instruction_fetch_alias_is_60004000(self):
        # MMU_IPA_GPIO_BASE - the alias the firmware does not use
        assert regs.MMU_IPA_GPIO_BASE == 0x60004000


class TestGpioRegisters:
    def test_gpio_out_reg(self):
        assert regs.GPIO_OUT_REG == 0x3FF44004

    def test_gpio_enable_reg(self):
        assert regs.GPIO_ENABLE_REG == 0x3FF44020

    def test_gate_bit_18(self):
        assert regs.gate_bit(18) == (1 << 18)

    def test_gate_bit_range(self):
        for pin in (0, 17, 31):
            assert regs.gate_bit(pin) == (1 << pin)
        for pin in (-1, 32):
            try:
                regs.gate_bit(pin)
            except ValueError:
                pass
            else:
                raise AssertionError("expected ValueError for pin %d" % pin)


class TestSensRegisters:
    def test_sar_meas_start1_reg(self):
        # sens_reg.h: SENS_SAR_MEAS_START1_REG = 0x3FF48854
        assert regs.SENS_SAR_MEAS_START1_REG == 0x3FF48854

    def test_measure1_data_sar(self):
        assert regs.MEAS1_DATA_SAR == 0x0000FFFF

    def test_measure1_done_sar(self):
        assert regs.MEAS1_DONE_SAR == (1 << 16)

    def test_measure1_start_sar(self):
        assert regs.MEAS1_START_SAR == (1 << 17)

    def test_measure1_start_force(self):
        assert regs.MEAS1_START_FORCE == (1 << 18)

    def test_sar1_en_pad(self):
        assert regs.SAR1_EN_PAD == (0x00000FFF << 19)

    def test_sar1_en_pad_force(self):
        assert regs.SAR1_EN_PAD_FORCE == (1 << 31)

    def test_sar1_result_pack(self):
        # 12-bit 0x0BAD packed with the done bit set
        word = regs.sar1_result(0x0BAD)
        assert (word & 0xFFFF) == 0x0BAD
        assert (word & regs.MEAS1_DONE_SAR) != 0

    def test_sar1_result_rejects_out_of_range(self):
        try:
            regs.sar1_result(0x10000)
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for raw > 0xFFFF")
