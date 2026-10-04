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
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_log.h"

#define GATE_PIN            GPIO_NUM_18
#define ADC_CHANNEL         ADC_CHANNEL_0  // GPIO 36 (ADC1 channel 0)

// Samples averaged per control decision. A single uncalibrated ESP32 ADC
// reading carries several counts of noise, which is the same order as the
// hysteresis band, so one sample is not enough to decide on.
#define ADC_OVERSAMPLE_N    16

// 12-bit ADC (0..4095 counts for 0..3.3V reference)
// Target V_out = 3.30V -> V_feedback = 1.65V
// Target Calibrated count: ~2012 (corresponding to 3.24V on output after inrush)
// Hysteresis Band: +-15 counts (+-20mV)
//
// IMPORTANT: these are RAW counts, not millivolts. Calibration maps raw count
// to millivolts, but the decision below is still made on the raw value, so
// the thresholds stay in counts. Recalibrate the band against a measured
// transfer curve before trusting it in millivolts; see the log line printed
// at startup, which reports the measured millivolt value of each threshold.
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

    // 2. Configure ADC1 (oneshot driver)
    // ESP-IDF >= 5.2 folded unit init, channel config, and bitwidth into the
    // oneshot driver. ADC_ATTEN_DB_11 was renamed ADC_ATTEN_DB_12; it is the
    // same ~12 dB input attenuation and still the widest range (~0-3.1V).
    adc_oneshot_unit_handle_t adc_unit;
    adc_oneshot_unit_init_cfg_t unit_cfg = {
        .unit_id = ADC_UNIT_1,
    };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit_cfg, &adc_unit));

    adc_oneshot_chan_cfg_t chan_cfg = {
        .atten    = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_12,
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc_unit, ADC_CHANNEL, &chan_cfg));

    // 3. Calibration
    // The ESP32 ADC is only accurate after eFuse calibration. On this target
    // the driver offers line fitting (curve fitting is not available for
    // ESP32 in ESP-IDF 6.1), so ask the driver which eFuse calibration is
    // actually burnt rather than assuming, and fall back to the default
    // reference if none is. If calibration cannot be created we continue
    // uncalibrated: that is degraded but still better than not running.
    adc_cali_handle_t adc_cali_handle = NULL;
    bool cali_ok = false;
#if ADC_CALI_SCHEME_LINE_FITTING_SUPPORTED
    // The ESP32 line-fitting driver has no `option` member: it always uses the
    // calibration burnt into eFuse when one is present. check_efuse() is a
    // query, so call it to decide whether to set default_vref.
    adc_cali_line_fitting_efuse_val_t cali_val;
    esp_err_t efuse_err = adc_cali_scheme_line_fitting_check_efuse(&cali_val);

    adc_cali_line_fitting_config_t cali_cfg = {
        .unit_id  = ADC_UNIT_1,
        .atten    = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_12,
        .default_vref = 1100,   // ESP32 nominal internal reference, mV
    };
    if (efuse_err != ESP_OK) {
        ESP_LOGW(TAG, "ADC eFuse calibration unavailable (%s); default vref used",
                 esp_err_to_name(efuse_err));
    }

    esp_err_t cali_err = adc_cali_create_scheme_line_fitting(&cali_cfg, &adc_cali_handle);
    if (cali_err == ESP_OK) {
        cali_ok = true;
        ESP_LOGI(TAG, "ADC calibration enabled (%s scheme)",
                 efuse_err == ESP_OK ? "eFuse line-fitting" : "default-vref line-fitting");
    } else {
        ESP_LOGW(TAG, "ADC calibration unavailable (%s); running uncalibrated",
                 esp_err_to_name(cali_err));
    }
#else
    ESP_LOGW(TAG, "No ADC calibration scheme on this target; running uncalibrated");
#endif

    // Report what the raw-count thresholds actually correspond to in mV, so
    // the band can be sanity-checked against a real measurement.
    for (int t = 0; t < 2; t++) {
        int thr = t ? ADC_HIGH_THRESHOLD : ADC_LOW_THRESHOLD;
        int mv = 0;
        if (cali_ok) {
            adc_cali_raw_to_voltage(adc_cali_handle, thr, &mv);
            ESP_LOGI(TAG, "threshold %d counts = %d mV", thr, mv);
        } else {
            ESP_LOGI(TAG, "threshold %d counts (uncalibrated)", thr);
        }
    }

    ESP_LOGI(TAG, "Entering high-speed hysteretic control loop...");

    uint32_t loop_count = 0;
    int current_gate_state = 0;

    while (1) {
        // Oversample the feedback node. Averaging N readings cuts the
        // random noise term by sqrt(N); a single reading is not reliable
        // enough to decide against a band this narrow.
        int sum = 0;
        int samples_ok = 0;
        for (int i = 0; i < ADC_OVERSAMPLE_N; i++) {
            int s = 0;
            if (adc_oneshot_read(adc_unit, ADC_CHANNEL, &s) == ESP_OK) {
                sum += s;
                samples_ok++;
            }
        }
        if (samples_ok == 0) {
            // Every read failed: hold the last decision rather than acting
            // on a garbage sample.
            continue;
        }
        int raw_adc = sum / samples_ok;

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
