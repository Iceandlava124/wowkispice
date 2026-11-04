/*
 * control_law.h - C port of bridge/control_law.py
 *
 * Executable MCU firmware behaviour for mixed-signal co-simulation: ngspice
 * calls back at every timestep for any source declared `external`, the law
 * reads the *simulated* feedback node and returns the pin voltage for that
 * instant, so the analog solver sees a pin that reacts to the circuit.
 *
 * PARITY CONTRACT
 *
 *   tests/test_control_law_unit.py          spec normalisation, decision table
 *   tests/test_adc_conversion.py            ADC clamp/round at the boundaries
 *   tests/test_cosim_control.py             firmware import, divider semantics
 *                                           (control-law portions only; the
 *                                           netlist/end-to-end classes need
 *                                           the solver and are not ported yet)
 *
 * native/tests/test_control_law.c is a line-for-line port of those
 * assertions, and native/tools/parity_control_law.py cross-checks both
 * implementations over a shared battery of inputs.
 *
 * WHAT THIS DOES NOT MODEL, AND WHY IT IS NOT A BUG
 *
 * firmware/esp32_buck_controller/src/main.c does four things this law does
 * not.  They are listed here loudly, because the alternative is a simulation
 * that stays plausible and green while being quietly wrong.
 *
 *   1. ADC_OVERSAMPLE_N = 16.  Deliberately NOT modelled: those 16 reads are
 *      microseconds apart in real time while solver timesteps here are
 *      sub-microsecond, so "average the last 16 samples" has no defensible
 *      analogue in this loop.  What it means in practice: the modelled loop
 *      switches more often than the firmware would.
 *   2. adc_cali line-fitting calibration.  This law assumes a flat
 *      counts = volts/vref*full_scale mapping with vref = 3.3 V.  On real
 *      silicon the calibration curve is neither flat nor exactly 3.3 V.
 *   3. The attenuation setting itself is not read from the source.
 *   4. ESP_ERROR_CHECK guards on init failure have no counterpart.
 *
 * native/tests/test_control_law.c::test_fidelity_gap pins this gap
 * deliberately: it asserts main.c still declares ADC_OVERSAMPLE_N and still
 * calls adc_cali.  If someone removes them, the test fails and forces this
 * comment to be revisited.  A fidelity gap nobody can notice is how a model
 * rots.
 *
 * WHICH NET IS `sense_net`? THIS IS THE WHOLE BALLGAME.
 *
 * The firmware's #define ADC_LOW_THRESHOLD 1995 / ADC_HIGH_THRESHOLD 2030 are
 * raw counts measured AT THE ADC PIN, and its own comment says so.  The
 * divider is already reflected in them.  Passing the undivided output node as
 * `sense_net` and leaving divider=1.0 regulates to 1.62 V instead of 3.24 V -
 * exactly the divider ratio, silently.  wosp_implied_output_voltages() exists
 * so a caller can check before trusting a run.
 *
 * SPEC (JSON, per MCU) maps onto wosp_law_input field-by-field:
 *
 *   {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout",
 *    "target_v": 3.3, "hysteresis_v": 0.04, "divider": 0.5,
 *    "vhigh": 3.3, "vref": 3.3, "adc_bits": 12}
 *
 * `divider` is the attenuation from the sense net to the ADC pin, so
 * v_pin = sense_net * divider.  `adc_bits`/`vref` quantise the read exactly as
 * a real ADC would, so the modelled thresholds are counts, not float volts.
 */

#ifndef WOWKISPICE_CONTROL_LAW_H
#define WOWKISPICE_CONTROL_LAW_H

#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define WOSP_DEFAULT_VHIGH    3.3
#define WOSP_DEFAULT_VREF     3.3
#define WOSP_DEFAULT_ADC_BITS 12

#define WOSP_PIN_MAX     64
#define WOSP_NET_MAX     64
#define WOSP_SOURCE_MAX  260
#define WOSP_ERRMSG_MAX  512

typedef enum {
    WOSP_LAW_HYSTERETIC = 0,
    WOSP_LAW_PWM         = 1
} wosp_law_kind;

/*
 * Status codes live in wowkispice/status.h, shared with the netlist module.
 * The comment that used to sit here - that every failure also writes a
 * human-readable message carrying the Python wording - still holds and now
 * lives there.
 */
#include "wowkispice/status.h"

/*
 * A raw, caller-supplied spec.  Every field is optional and carries a presence
 * flag, because the Python side passes an untyped dict where a key is either
 * absent, None, or a value - and absent and None behave identically
 * (spec.get(key, default)).  Defaults live in wosp_normalize_law().
 *
 * `has_source_counts` is the nested {"low": .., "high": ..} dict that
 * law_from_firmware_source() records.  wosp_normalize_law() deliberately
 * DROPS it (as Python does); it only survives on the input so that
 * ..._exact() can copy it into low_counts/high_counts.
 */
typedef struct {
    bool  has_kind;            char kind[32];
    bool  has_pin;             char pin[WOSP_PIN_MAX];
    bool  has_sense_net;       char sense_net[WOSP_NET_MAX];
    bool  has_target_v;        double target_v;
    bool  has_hysteresis_v;    double hysteresis_v;
    bool  has_vhigh;           double vhigh;
    bool  has_vref;            double vref;
    bool  has_adc_bits;        int adc_bits;
    bool  has_divider;         double divider;
    bool  has_low_counts;      long low_counts;
    bool  has_high_counts;     long high_counts;
    bool  has_carrier_hz;      double carrier_hz;
    bool  has_duty_gain;       double duty_gain;
    bool  has_source;          char source[WOSP_SOURCE_MAX];
    bool  has_source_counts;   long source_low, source_high;
} wosp_law_input;

/* A normalised spec: every field filled, no presence flags needed. */
typedef struct {
    wosp_law_kind kind;
    char   pin[WOSP_PIN_MAX];
    char   sense_net[WOSP_NET_MAX];
    double target_v, vhigh, vref, divider;
    int    adc_bits;
    /* hysteretic only */
    double hysteresis_v;
    long   low_counts, high_counts;
    /* pwm only */
    double carrier_hz, duty_gain;
    /* echoed when the spec named a firmware source */
    bool   has_source;
    char   source[WOSP_SOURCE_MAX];
} wosp_law_spec;

/* Run summary; identical shape for every law kind so callers can print it. */
typedef struct {
    wosp_law_kind kind;
    char   pin[WOSP_PIN_MAX];
    char   sense_net[WOSP_NET_MAX];
    long   samples, switches;
    double duty;
    bool   has_counts;                 /* false when there are no samples */
    long   counts_min, counts_max, counts_last;
    bool   final_level_high;
} wosp_law_stats;

/*
 * Steady-state regulation error of a run, in counts and in volts.
 *
 * Operates on samples already in counts space, so no volts<->counts round
 * trip can smear the measurement.
 */
typedef struct {
    bool   has;                        /* false when there are no samples */
    double mean_error_counts, max_error_counts;
    double mean_error_v, final_error_counts;
} wosp_regulation_error;

/*
 * The executable law.  A single struct rather than a class hierarchy: the two
 * kinds share the ADC front end, the telemetry and the state a caller needs to
 * report a run honestly, and differ only in decide().  The extra kind-specific
 * fields simply sit unused for the other kind.
 */
typedef struct {
    wosp_law_spec spec;
    char   pin[WOSP_PIN_MAX];
    char   sense_net[WOSP_NET_MAX];
    double vhigh, divider, vref;
    int    adc_bits;
    bool   level;
    long   switch_count;
    /* hysteretic */
    long   low_counts, high_counts;
    /* pwm */
    double carrier_hz, duty_gain, target_counts, duty;
    /* history: three parallel arrays, index-aligned, grown on demand */
    double *hist_time;
    double *hist_pin;
    long   *hist_counts;
    size_t  n_hist, cap_hist;
    bool    oom;                       /* set if a history push failed */
} wosp_law;

/* Constants of the form `#define ADC_HIGH_THRESHOLD 2030`. */
typedef struct {
    long low, high;
    char pin[WOSP_PIN_MAX];            /* "GPIO18" */
} wosp_firmware_constants;

/*
 * Fill defaults and reject nonsense so callers never guard twice.
 * `in` may be NULL (treated as an empty spec, matching normalize_law(None)).
 * Never mutates the input.  Returns WOSP_OK or WOSP_ERR_* with `err` set.
 */
wosp_status wosp_normalize_law(const wosp_law_input *in,
                               wosp_law_spec *out,
                               char *err, size_t errlen);

/* Volts -> ADC counts, clipped to the converter's full scale. */
long wosp_to_counts_raw(double volts, double vref, int bits);

/* Build the right law for a (raw or normalised) spec.  Caller owns `law` and
 * must release it with wosp_law_destroy(), even on failure. */
wosp_status wosp_law_create(const wosp_law_input *in, wosp_law *law,
                            char *err, size_t errlen);
void wosp_law_destroy(wosp_law *law);

/* Sense node -> ADC counts, including the divider and clipping. */
long wosp_to_counts(const wosp_law *law, double sense_v);

/*
 * One decision.  For the hysteretic kind this reads law->level to hold the
 * previous state inside the band, so `law` is not const.  For the pwm kind it
 * reads the last history timestamp (the PREVIOUS timestep: update() appends
 * after decide() runs, exactly as Python does) and updates law->duty.
 */
bool wosp_law_decide(wosp_law *law, long counts);

/* One solver timestep.  Returns the pin voltage for this instant and records
 * telemetry.  Returns NAN and sets law->oom if history could not grow. */
double wosp_law_update(wosp_law *law, double sense_v, double time_s);

/* One-line human description into `buf`. */
void wosp_law_describe(const wosp_law *law, char *buf, size_t buflen);

/*
 * Run summary.  Named `..._get_stats` rather than `..._stats` because a C
 * typedef and a function share one identifier namespace: Python's
 * `law.stats()` cannot be transcribed literally without redeclaring the
 * wosp_law_stats struct as a function.
 */
wosp_status wosp_law_get_stats(const wosp_law *law, wosp_law_stats *out);

/* One-line human description; never fails - invalid specs yield
 * "<invalid control law: ...>", mirroring describe_law(). */
void wosp_describe_law(const wosp_law_input *in, char *buf, size_t buflen);

/*
 * Pull the ADC thresholds and gate pin out of a C firmware source.
 * Returns {"low": int, "high": int, "pin": "GPIO18"}.  Fails with
 * WOSP_ERR_NO_CONSTANTS if the file holds none of the names - we would rather
 * say so than silently simulate a made-up controller.
 *
 * Text is read with Python's universal-newline translation (\r\n and lone \r
 * both become \n) so the #define scan sees byte-identical input to CPython.
 */
wosp_status wosp_read_firmware_constants(const char *path,
                                         wosp_firmware_constants *out,
                                         char *err, size_t errlen);

/*
 * Build a control-law spec from a real firmware C source.  The thresholds in
 * that firmware are already *scaled* counts (its comments state the divider is
 * folded in), so divider=1.0 is the default.
 *
 * Pass `divider` only when `sense_net` is NOT the net the ADC pin samples -
 * i.e. when it is the undivided output and the pin sees it attenuated.
 */
wosp_status wosp_law_from_firmware_source(const char *path,
                                          const char *sense_net,
                                          double divider,
                                          double vhigh, double vref,
                                          int adc_bits,
                                          wosp_law_input *out,
                                          char *err, size_t errlen);

/* As above, but pins low_counts/high_counts to the file's own integers
 * instead of a round-trip through volts, so what the solver sees is
 * bit-for-bit the firmware's decision boundary. */
wosp_status wosp_law_from_firmware_source_exact(const char *path,
                                                const char *sense_net,
                                                double divider,
                                                double vhigh, double vref,
                                                int adc_bits,
                                                wosp_law_input *out,
                                                char *err, size_t errlen);

/* Voltages the ADC pin must see to cross the low and high thresholds. */
wosp_status wosp_implied_pin_voltages(const wosp_law_input *in,
                                      double *lo, double *hi,
                                      char *err, size_t errlen);

/*
 * What the schematic's output node will be regulated to.  `pin_divider` is the
 * schematic's pin-to-output attenuation (0.5 for the 100k/100k divider in
 * circuits/buck_converter.cir).  Call this before trusting a run: if the
 * sense net is the undivided output node rather than the divider output, the
 * returned numbers are half what you expect, and that is the signature of a
 * mis-wired sense net rather than a bad circuit.
 */
wosp_status wosp_implied_output_voltages(const wosp_law_input *in,
                                         double pin_divider,
                                         double *lo, double *hi,
                                         char *err, size_t errlen);

/*
 * Steady-state regulation error of a run.  Operates on samples already in
 * counts space, so no volts<->counts round trip can smear the measurement.
 * Ignores the first fifth of the samples: an inductor charging from zero is
 * start-up, not regulation error.
 *
 * Prefixed `wosp_law_` rather than Python's plain `regulation_error` because
 * a typedef and a function share one identifier namespace in C: without the
 * prefix this declaration redeclares the wosp_regulation_error struct as a
 * function.  Same reason wosp_law_stats is exposed as wosp_law_get_stats.
 *
 * n == 0 yields has == false (Python returns all-None).  n == 1 is an error:
 * Python slices the single sample away and then divides by zero, raising
 * ZeroDivisionError - both implementations reject it, C by status instead of
 * by exception.
 */
wosp_status wosp_law_regulation_error(const long *samples, size_t n,
                                      long target_counts, double vref,
                                      int adc_bits, wosp_regulation_error *out,
                                      char *err, size_t errlen);

#ifdef __cplusplus
}
#endif

#endif /* WOWKISPICE_CONTROL_LAW_H */
