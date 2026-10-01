"""
renode_adc_peripheral.py - Custom Renode Python MMIO Peripheral Mock
Intercepts ESP32 ADC register reads (SENS_SAR_MEAS_START1_REG / SENS_SAR_READ_STATUS1_REG)
and returns digitized SPICE circuit voltages to the running firmware.
"""

# In Renode Python peripheral execution context:
# 'request' contains: request.type, request.offset, request.value, request.isRead, request.isWrite

import os

# Default ADC count if bridge is idling
current_adc_count = 2048

# Register offsets for ESP32 SENS_SAR peripheral
# 0x00: SENS_SAR_MEAS_START1_REG
# 0x04: SENS_SAR_READ_STATUS1_REG (contains ADC1 12-bit conversion result in bits [11:0])
# 0x1C: SENS_SAR_START_FORCE_REG

if request.isRead:
    if request.offset == 0x04 or request.offset == 0x00:
        # Return ADC1 raw conversion result + conversion done bit (bit 16)
        request.value = (1 << 16) | (current_adc_count & 0x0FFF)
    else:
        request.value = 0x00
elif request.isWrite:
    # Accept register writes
    pass
