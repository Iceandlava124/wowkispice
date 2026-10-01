/**
 * @file main.c
 * @brief ESP32 Bare-Metal Hysteretic Buck Converter Controller
 * 
 * Target: Regulate 12V DC input down to 3.30V DC via closed-loop feedback.
 * Hardware:
 *   - Gate Drive: GPIO 18 (Digital Output)
 *   - Feedback Voltage: ADC1 Channel 0 (GPIO 36 / SENS_SAR_MEAS_START1_REG)
 *     Fed via a 2:1 resistive divider (V_feedback = V_out / 2).
 */

#include <stdio.h>
#include <stdint.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "driver/adc.h"
#include "esp_log.h"

#define GATE_PIN            GPIO_NUM_18
#define ADC_CHANNEL         ADC1_CHANNEL_0  // GPIO 36

// 12-bit ADC (0..4095 counts for 0..3.3V reference)
// Target V_out = 3.30V -> V_feedback = 1.65V
// Target Calibrated count: ~2012 (corresponding to 3.24V on output after inrush)
// Hysteresis Band: +-15 counts (+-20mV)
#define ADC_LOW_THRESHOLD   1995
#define ADC_HIGH_THRESHOLD  2030

static const char *TAG = "BUCK_CTRL";

void app_main(void)
{
    ESP_LOGI(TAG, "Starting ESP32 Buck Converter Closed-Loop Controller...");

    // 1. Configure Gate Drive GPIO as Output
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << GATE_PIN),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE
    };
    gpio_config(&io_conf);
    gpio_set_level(GATE_PIN, 0);

    // 2. Configure ADC1
    adc1_config_width(ADC_WIDTH_BIT_12);
    adc1_config_channel_atten(ADC_CHANNEL, ADC_ATTEN_DB_11); // 0..3.3V full scale

    ESP_LOGI(TAG, "Entering high-speed hysteretic control loop...");

    uint32_t loop_count = 0;
    int current_gate_state = 0;

    while (1) {
        // Sample feedback voltage from simulated analog circuit
        int raw_adc = adc1_get_raw(ADC_CHANNEL);

        // Hysteretic switching logic
        if (raw_adc < ADC_LOW_THRESHOLD) {
            if (!current_gate_state) {
                gpio_set_level(GATE_PIN, 1);
                current_gate_state = 1;
            }
        } else if (raw_adc > ADC_HIGH_THRESHOLD) {
            if (current_gate_state) {
                gpio_set_level(GATE_PIN, 0);
                current_gate_state = 0;
            }
        }

        loop_count++;
        if (loop_count % 10000 == 0) {
            ESP_LOGI(TAG, "Loop: %lu | Raw ADC: %d | Gate: %s", 
                     (unsigned long)loop_count, raw_adc, current_gate_state ? "ON" : "OFF");
        }
    }
}
