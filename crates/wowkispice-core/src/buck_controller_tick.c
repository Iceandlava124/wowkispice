/**
 * @file buck_controller_tick.c
 * @brief Extern "C" entry point for the ESP32 hysteretic buck controller.
 *
 * This provides a C callable function that the Rust solver can invoke at each
 * timestep, replacing the QEMU monitor loop.  The hysteresis thresholds and
 * divider logic match the firmware in main.c exactly:
 *   - ADC_LOW_THRESHOLD  = 1995  (raw counts, ~1.645 V at ADC after 2:1 divider)
 *   - ADC_HIGH_THRESHOLD = 2030  (raw counts, ~1.676 V at ADC after 2:1 divider)
 *   - 12-bit ADC (0..4095 counts for 0..3.3 V reference)
 *   - Hysteresis band: +-15 counts
 *
 * API:  buck_controller_tick(adc_counts, &gpio_out) -> true=gate ON, false=gate OFF
 */

#include <stdint.h>

#define ADC_LOW_THRESHOLD   1995
#define ADC_HIGH_THRESHOLD  2030

/**
 * Tick the hysteretic buck controller.
 *
 * @param adc_counts   Raw 12-bit ADC count (averaged sample, matching the
 *                     firmware's oversample-then-average pattern).
 * @param gpio_out     Pointer to bool that receives the gate state:
 *                     true = gate driven HIGH ( MOSFET on ),
 *                     false = gate driven LOW  ( MOSFET off ).
 * @return true  if the gate is ON after this tick,
 *         false if the gate is OFF after this tick.
 *
 * Hysteretic logic (identical to main.c):
 *   - adc_counts <  LOW_THRESHOLD  => gate ON  (if it wasn't already)
 *   - adc_counts >  HIGH_THRESHOLD => gate OFF (if it wasn't already)
 *   - otherwise                          => state unchanged (hysteresis)
 */
void buck_controller_tick(int32_t adc_counts, bool *gpio_out)
{
    static bool current_gate_state = false;  // persistent across ticks

    if (adc_counts < ADC_LOW_THRESHOLD) {
        if (!current_gate_state) {
            *gpio_out = true;
            current_gate_state = true;
        }
    } else if (adc_counts > ADC_HIGH_THRESHOLD) {
        if (current_gate_state) {
            *gpio_out = false;
            current_gate_state = false;
        }
    }
    // else: hysteresis — state stays as-is
}