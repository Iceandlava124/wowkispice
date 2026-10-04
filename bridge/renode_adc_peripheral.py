"""
renode_adc_peripheral.py - Custom Renode Python MMIO Peripheral Mock

ABANDONED, AND NOT IMPORTABLE. The intent was to intercept ESP32 ADC register
reads (SENS_SAR_MEAS_START1_REG / SENS_SAR_READ_STATUS1_REG) and feed digitized
SPICE voltages back to the running firmware. That never happened: Renode cannot
decode the Xtensa `entry` instruction, so it executed none of our firmware and
no ESP32 ever read a voltage through this model.

The body below is a paste-in Renode desktop-script fragment, not a module --
`request` is injected by Renode's peripheral loader -- so importing this file
raises NameError. Retained only as a record. See docs/legacy-module-audit.md.
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
