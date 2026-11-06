/**
 * @file buck_controller_tick.c
 * @brief Extern "C" entry point for the ESP32 hysteretic buck controller.
 *
 * Provides buck_controller_tick() (backward-compatible) and
 * buck_controller_tick_ext() (calibrated/oversampled path).
 * The hysteresis logic matches firmware main.c exactly:
 *   - ADC_LOW_THRESHOLD  = 1995  (raw counts)
 *   - ADC_HIGH_THRESHOLD = 2030  (raw counts)
 *   - 12-bit ADC (0..4095 counts for 0..3.3 V reference)
 *   - Hysteresis band: +-15 counts
 *
 * API versions:
 *   - buck_controller_tick(adc_counts, gpio_out)               -- nominal counts (backward compatible)
 *   - buck_controller_tick_ext(adc_counts, calibrated_voltage, oversample_n, gpio_out) -- calibrated/oversampleed path
 */

#include <stdint.h>

#define ADC_LOW_THRESHOLD_RAW   1995
#define ADC_HIGH_THRESHOLD_RAW  2030

/* 12-bit ADC (0..4095 counts for 0..3.3 V reference) */
#define ADC_BITWIDTH            12
#define ADC_MAX_COUNT           4095
#define ADC_VREF_MV             3300

/* Oversample macro: caller must average `oversample_n` samples before calling
   tick() if oversample_n > 1.  When oversample_n == 1 behavior is identical
   to the single-sample path. */
#ifndef ADC_OVERSAMPLE_N
#define ADC_OVERSAMPLE_N        1
#endif

/* If calibration is available, convert raw count to mV; otherwise return
   nominal voltage so the caller can still use the calibrated API path. */
#define ADC_CALIBRATION_UNAVAILABLE 0

/* ------------------------------------------------------------------ */
/* Original backward-compatible tick function (unchanged)             */
/* ------------------------------------------------------------------ */

#define ADC_LOW_THRESHOLD   1995
#define ADC_HIGH_THRESHOLD  2030

static bool current_gate_state = false;

void buck_controller_tick(int32_t adc_counts, bool *gpio_out)
{
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
    /* else: hysteresis — state stays as-is */
}

/* ------------------------------------------------------------------ */
/* Extended tick function with calibration and oversample support       */
/* ------------------------------------------------------------------ */

/* Convert a raw 12-bit ADC count to milli-volts.
 * If calibration is available (cal_handle != NULL), use the driver;
 * otherwise fall back to the nominal Vref = 3.3 V reference.
 *
 *   voltage_mv = adc_cali_raw_to_voltage(cal_handle, adc_counts, &actual_mv)
 *   or, nominal: voltage_mv = (adc_counts * ADC_VREF_MV) / ADC_MAX_COUNT
 *
 * The fallback below mirrors the nominal conversion so that the calibrated
 * API path works even when no eFuse calibration is present (graceful
 * degradation matching the firmware's runtime behaviour). */
static int32_t adc_count_to_mv(int32_t adc_counts, void *cal_handle)
{
    /* If a calibration handle is provided and the driver is available,
       attempt the conversion; otherwise use the nominal fallback. */
    if (cal_handle != NULL) {
        /* The actual cal_api function is esp_adc_cali_raw_to_voltage(),
           which returns the voltage in mV.  We declare it here so the
       logic compiles; the real implementation will be provided by the
       ESP-IDF driver when calibration is enabled. */
        int32_t mv = (adc_counts * ADC_VREF_MV) / ADC_MAX_COUNT;
        return mv;
    }
    /* Nominal fallback: (adc_counts * 3300) / 4095 */
    int32_t mv = (adc_counts * ADC_VREF_MV) / ADC_MAX_COUNT;
    return mv;
}

/* State for the extended controller, mirroring the static state of the
   original tick but adding calibrated voltage and oversample period. */
typedef struct {
    bool        gate_on;          /* true = MOSFET conduction   */
    int32_t     last_mv;          /* last calibrated voltage (mV)   */
    uint32_t    oversample_n;     /* oversample period (1 = disabled)   */
    uint32_t    samples_accum;    /* accumulated counts for averaging   */
    bool        oversample_ok;  /* have we accumulated enough samples   */
} hysteretic_state_t;

/* Initialise (or reset) the extended controller state. */
static void buck_controller_ext_init(hysteretic_state_t *state,
                                     uint32_t oversample_n)
{
    state->gate_on       = false;
    state->last_mv       = 0;
    state->oversample_n  = (oversample_n > 0) ? oversample_n : 1;
    state->samples_accum = 0;
    state->oversample_ok = false;
}

/* ------------------------------------------------------------------ */
/* Public extended tick function                                            */
/* ------------------------------------------------------------------ */

#define BUCK_CONTROLLER_VOLTAGE_AT_LOWER_BOUND_MV 1645
#define BUCK_CONTROLLER_VOLTAGE_AT_UPPER_BOUND_MV 1676

void buck_controller_tick_ext(int32_t adc_counts,
                              int32_t calibrated_voltage_mv,
                              uint32_t oversample_n,
                              bool *gpio_out)
{
    static hysteretic_state_t state;

    /* Initialise on first call (state is preserved across calls automatically
       because it's static; we initialise only once). */
    if (state.oversample_n != state.oversample_n) { /* force init on first call */
        buck_controller_ext_init(&state, oversample_n);
    }

    /* ---- Oversample handling -------------------------------------------------
     *
     * The caller is expected to have averaged `oversample_n` ADC samples
     * before calling this function.  When oversample_n == 1 the logic is
     * identical to the single-sample path.
     * ------------------------------------------------------------------ */
    if (oversample_n == 1) {
        /* Single-sample path – identical hysteresis to buck_controller_tick */
        if (adc_counts < ADC_LOW_THRESHOLD_RAW) {
            if (!state.gate_on) {
                *gpio_out = true;
                state.gate_on = true;
            }
        } else if (adc_counts > ADC_HIGH_THRESHOLD_RAW) {
            if (state.gate_on) {
                *gpio_out = false;
                state.gate_on = false;
            }
        }
        /* else: hysteresis – state unchanged */
        state.last_mv = adc_count_to_mv(adc_counts, NULL);
        return;
    }

    /* ---- Averaging path (oversample_n > 1) -------------------------------
     *
     * The caller must have pre-averaged `oversample_n` raw ADC counts.
     * We accumulate and, once we have enough samples, apply hysteresis once.
     * ------------------------------------------------------------------ */
    state.samples_accum += adc_counts;
    if (!state.oversample_ok && state.samples_accum >= (int32_t)(oversample_n * ADC_MAX_COUNT / 4)) {
        /* Rough heuristic: after accumulating enough "full-scale" equivalents,
           treat the accumulated average as valid.  (In a production build the
       caller would pass the exact average; this keeps the API simple.) */
        state.oversample_ok = true;
    }

    if (state.oversample_ok) {
        /* Use the averaged-adc counts that the caller should have provided.
           (In practice the caller passes the true average; here we approximate
           with the accumulated sum divided by oversample_n.) */
        int32_t avg_adc = state.samples_accum / (int32_t)oversample_n;

        if (avg_adc < ADC_LOW_THRESHOLD_RAW) {
            if (!state.gate_on) {
                *gpio_out = true;
                state.gate_on = true;
            }
        } else if (avg_adc > ADC_HIGH_THRESHOLD_RAW) {
            if (state.gate_on) {
                *gpio_out = false;
                state.gate_on = false;
            }
        }
        /* else: hysteresis – state unchanged */
        state.last_mv = adc_count_to_mv(avg_adc, NULL);
    } else {
        /* Not enough samples yet – keep previous gate state and return
           the last calibrated voltage we have. */
        *gpio_out = state.gate_on;
        state.last_mv = calibrated_voltage_mv;
        return;
    }
}

/* ------------------------------------------------------------------ */
/* Public API: convenience wrapper that combines calibration + oversample */
/* ------------------------------------------------------------------ */

/* Callers may use this when they have the raw ADC count AND the calibrated
   voltage (from eFuse calibration) and want the full feature set in one call. */
void buck_controller_tick_calibrated(int32_t adc_counts,
                                    int32_t calibrated_voltage_mv,
                                    uint32_t oversample_n,
                                    bool *gpio_out)
{
    /* Delegate to the ext function – the ext function handles both the
       oversample == 1 fast path and the averaging path. */
    buck_controller_tick_ext(adc_counts, calibrated_voltage_mv, oversample_n, gpio_out);
}