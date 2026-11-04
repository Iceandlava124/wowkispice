/*
 * parity_control_law.c - emits a fixed battery of control_law results.
 *
 * The companion parity_control_law.py computes the SAME battery from
 * bridge/control_law.py and diffs the two.  This is the gate that says the C
 * port is behaviourally the Python module, rather than merely passing a
 * re-written copy of its tests - a re-written test can be wrong in the same
 * way as the code it tests, a cross-implementation diff cannot.
 *
 * Output format: one `key<TAB>value` per line.
 *   doubles  -> %.17g  (the Python side parses and compares exactly, so the
 *                      formatting itself need not match)
 *   longs    -> %ld
 *   bools    -> true / false
 *   strings  -> verbatim, including spaces
 *   errors   -> empty string on success, the message on failure
 *
 * The battery is duplicated in parity_control_law.py.  Keys are index-based
 * (`adc12[3]`, `spec[7].low`) rather than value-derived, so a value that
 * formats differently on one side can never shift the key space; a case added
 * or removed on one side alone is caught as a key mismatch.
 */

#include "wowkispice/control_law.h"

#include <stdio.h>
#include <string.h>

#ifndef WOSP_FIRMWARE_MAIN_C
#define WOSP_FIRMWARE_MAIN_C "../firmware/esp32_buck_controller/src/main.c"
#endif

static const char *FW = WOSP_FIRMWARE_MAIN_C;
static char g_err[WOSP_ERRMSG_MAX];

static void emit_d(const char *key, double v)
{
    printf("%s\t%.17g\n", key, v);
}

static void emit_l(const char *key, long v)
{
    printf("%s\t%ld\n", key, v);
}

static void emit_b(const char *key, int v)
{
    printf("%s\t%s\n", key, v ? "true" : "false");
}

static void emit_s(const char *key, const char *v)
{
    printf("%s\t%s\n", key, v);
}

/* ---------------------------------------------------------------------- */
/* 1. ADC conversion grid                                                 */
/* ---------------------------------------------------------------------- */

/* Same list, same order, in parity_control_law.py. */
static const double ADC12_VOLTS[] = {
    -0.01, -0.001, 0.0, 3.3 / 8190, 3.3 / 8190 + 1e-9,
    0.1, 0.5, 1.0, 1.2, 1.6077, 1.625, 1.6359, 2.4,
    3.3 - 1e-9, 3.3, 3.30000001, 3.31, 10.0
};
static const double ADC16_VOLTS[] = {
    -1.0, 0.0, 0.0001, 2.5, 4.999999, 5.0, 5.5, 100.0
};

static void battery_adc(void)
{
    char key[128];
    size_t i;

    for (i = 0; i < sizeof ADC12_VOLTS / sizeof ADC12_VOLTS[0]; i++) {
        snprintf(key, sizeof key, "adc12[%u]", (unsigned)i);
        emit_l(key, wosp_to_counts_raw(ADC12_VOLTS[i], 3.3, 12));
    }
    for (i = 0; i < sizeof ADC16_VOLTS / sizeof ADC16_VOLTS[0]; i++) {
        snprintf(key, sizeof key, "adc16[%u]", (unsigned)i);
        emit_l(key, wosp_to_counts_raw(ADC16_VOLTS[i], 5.0, 16));
    }
    /* adc_bits extremes accepted by normalisation: 8 and 24. */
    emit_l("adc8[0]", wosp_to_counts_raw(1.0, 3.3, 8));
    emit_l("adc8[1]", wosp_to_counts_raw(3.3, 3.3, 8));
    emit_l("adc24[0]", wosp_to_counts_raw(1.0, 3.3, 24));
    emit_l("adc24[1]", wosp_to_counts_raw(3.3, 3.3, 24));
}

/* ---------------------------------------------------------------------- */
/* 2. Spec normalisation                                                  */
/* ---------------------------------------------------------------------- */

static wosp_law_input spec_base(void)
{
    wosp_law_input in;
    memset(&in, 0, sizeof in);
    in.has_kind = true;
    strcpy(in.kind, "hysteretic");
    in.has_pin = true;
    strcpy(in.pin, "GPIO18");
    in.has_sense_net = true;
    strcpy(in.sense_net, "vout");
    return in;
}

/* Index order mirrored exactly in parity_control_law.py. */
static wosp_law_input spec_at(int i)
{
    wosp_law_input in = spec_base();

    switch (i) {
    case 0: /* fixture with the firmware's explicit counts */
        in.has_target_v = true;     in.target_v = 3.3;
        in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
        in.has_divider = true;      in.divider = 0.5;
        in.has_vref = true;         in.vref = 3.3;
        in.has_adc_bits = true;     in.adc_bits = 12;
        in.has_low_counts = true;   in.low_counts = 1995;
        in.has_high_counts = true;  in.high_counts = 2030;
        break;
    case 1: /* counts derived from target and hysteresis */
        in.has_target_v = true;     in.target_v = 3.3;
        in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
        in.has_divider = true;      in.divider = 0.5;
        in.has_vref = true;         in.vref = 3.3;
        in.has_adc_bits = true;     in.adc_bits = 12;
        break;
    case 2: /* pwm */
        strcpy(in.kind, "pwm");
        in.has_target_v = true;     in.target_v = 3.3;
        in.has_carrier_hz = true;   in.carrier_hz = 1000;
        in.has_duty_gain = true;    in.duty_gain = 0.5;
        break;
    case 3: /* defaults only - every default must materialise */
        break;
    case 4: /* explicit counts overriding a round-trip through volts */
        in.has_target_v = true;     in.target_v = 1.0;
        in.has_hysteresis_v = true; in.hysteresis_v = 0.01;
        in.has_low_counts = true;   in.low_counts = 1995;
        in.has_high_counts = true;  in.high_counts = 2030;
        break;
    case 5: /* only low_counts given -> both recomputed */
        in.has_target_v = true;     in.target_v = 3.3;
        in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
        in.has_divider = true;      in.divider = 0.5;
        in.has_vref = true;         in.vref = 3.3;
        in.has_adc_bits = true;     in.adc_bits = 12;
        in.has_low_counts = true;   in.low_counts = 1995;
        break;
    case 6: /* kind is case-insensitive in Python */
        strcpy(in.kind, "HYSTERETIC");
        break;
    case 7: /* pin is stripped */
        strcpy(in.pin, "   GPIO42\t");
        break;
    /* --- invalid from here on --- */
    case 8:
        strcpy(in.kind, "banana");
        break;
    case 9:
        in.has_divider = true;      in.divider = 0;
        break;
    case 10:
        in.has_low_counts = true;   in.low_counts = 2000;
        in.has_high_counts = true;  in.high_counts = 2000;
        break;
    case 11:
        in.has_vhigh = true;        in.vhigh = 99;
        break;
    case 12:
        in.has_pin = false;
        break;
    case 13:
        in.has_sense_net = false;
        break;
    case 14:
        in.has_adc_bits = true;     in.adc_bits = 40;
        break;
    case 15:
        in.has_target_v = true;     in.target_v = 3.3;
        in.has_hysteresis_v = true; in.hysteresis_v = 0;
        break;
    case 16:
        in.has_target_v = true;     in.target_v = 1.0;
        in.has_hysteresis_v = true; in.hysteresis_v = 2.0;
        break;
    case 17:
        strcpy(in.kind, "pwm");
        in.has_carrier_hz = true;   in.carrier_hz = 0;
        break;
    case 18:
        in.has_vref = true;         in.vref = 0;
        break;
    case 19:
        in.has_target_v = true;     in.target_v = -5;
        break;
    default:
        break;
    }
    return in;
}

#define SPEC_COUNT 20

static void battery_specs(void)
{
    int i;
    for (i = 0; i < SPEC_COUNT; i++) {
        char key[128];
        wosp_law_input in = spec_at(i);
        wosp_law_spec s;
        wosp_status st;

        g_err[0] = '\0';
        st = wosp_normalize_law(&in, &s, g_err, sizeof g_err);

        snprintf(key, sizeof key, "spec[%d]", i);
        emit_s(key, (st == WOSP_OK) ? "" : g_err);

        if (st == WOSP_OK) {
            snprintf(key, sizeof key, "spec[%d].kind", i);
            emit_s(key, s.kind == WOSP_LAW_PWM ? "pwm" : "hysteretic");
            snprintf(key, sizeof key, "spec[%d].pin", i);
            emit_s(key, s.pin);
            snprintf(key, sizeof key, "spec[%d].sense_net", i);
            emit_s(key, s.sense_net);
            snprintf(key, sizeof key, "spec[%d].target", i);
            emit_d(key, s.target_v);
            snprintf(key, sizeof key, "spec[%d].vhigh", i);
            emit_d(key, s.vhigh);
            snprintf(key, sizeof key, "spec[%d].vref", i);
            emit_d(key, s.vref);
            snprintf(key, sizeof key, "spec[%d].divider", i);
            emit_d(key, s.divider);
            snprintf(key, sizeof key, "spec[%d].adc_bits", i);
            emit_l(key, s.adc_bits);
            /*
             * Keyed on kind: Python's normalized dict holds low/high counts
             * only for a hysteretic law and carrier/gain only for a pwm one,
             * so emitting both would invent keys neither side really has.
             */
            if (s.kind == WOSP_LAW_HYSTERETIC) {
                snprintf(key, sizeof key, "spec[%d].low", i);
                emit_l(key, s.low_counts);
                snprintf(key, sizeof key, "spec[%d].high", i);
                emit_l(key, s.high_counts);
                snprintf(key, sizeof key, "spec[%d].hyst", i);
                emit_d(key, s.hysteresis_v);
            } else {
                snprintf(key, sizeof key, "spec[%d].carrier", i);
                emit_d(key, s.carrier_hz);
                snprintf(key, sizeof key, "spec[%d].gain", i);
                emit_d(key, s.duty_gain);
            }
            snprintf(key, sizeof key, "spec[%d].source", i);
            emit_s(key, s.has_source ? s.source : "(none)");
        }
    }
}

/* ---------------------------------------------------------------------- */
/* 3. Decision table                                                      */
/* ---------------------------------------------------------------------- */

static const long DECIDE_COUNTS[] = {
    0, 100, 1990, 1994, 1995, 1996, 2012, 2029, 2030, 2031, 2035, 4095
};

static void battery_decide(void)
{
    char key[128];
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = spec_at(0);
    wosp_law law;
    size_t i;
    int pass;

    if (wosp_law_create(&in, &law, err, sizeof err) != WOSP_OK) {
        emit_s("decide.setup", err);
        return;
    }
    emit_s("decide.setup", "");

    /* Two passes: decide() must hold the PREVIOUS level inside the band, so
     * the same counts must give different answers depending on law.level. */
    for (pass = 0; pass < 2; pass++) {
        law.level = (pass == 1);
        for (i = 0; i < sizeof DECIDE_COUNTS / sizeof DECIDE_COUNTS[0]; i++) {
            snprintf(key, sizeof key, "decide[%d][%u]",
                     pass, (unsigned)i);
            emit_b(key, wosp_law_decide(&law, DECIDE_COUNTS[i]));
        }
    }

    /* And the ADC front end on this law: sense volts -> counts, with the
     * sense divider applied. */
    emit_l("law.to_counts[0]", wosp_to_counts(&law, 0.0));
    emit_l("law.to_counts[1]", wosp_to_counts(&law, 2.4));
    emit_l("law.to_counts[2]", wosp_to_counts(&law, 3.3));
    emit_l("law.to_counts[3]", wosp_to_counts(&law, 6.6));

    wosp_law_destroy(&law);
}

/* ---------------------------------------------------------------------- */
/* 4. update() sequence and the telemetry it produces                     */
/* ---------------------------------------------------------------------- */

static const double UPD_VOLTS[] = {
    0.0, 5.0, 5.0, 3.25, 3.25, 0.0, 1.6, 3.3, 0.0, 4.0
};
static const double UPD_TIME[] = {
    0.0, 1e-6, 2e-6, 3e-6, 4e-6, 5e-6, 6e-6, 7e-6, 8e-6, 9e-6
};

static void battery_update(void)
{
    char key[128];
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = spec_at(0);
    wosp_law law;
    wosp_law_stats st;
    size_t i;

    if (wosp_law_create(&in, &law, err, sizeof err) != WOSP_OK) {
        emit_s("update.setup", err);
        return;
    }
    emit_s("update.setup", "");

    for (i = 0; i < sizeof UPD_VOLTS / sizeof UPD_VOLTS[0]; i++) {
        double v = wosp_law_update(&law, UPD_VOLTS[i], UPD_TIME[i]);
        snprintf(key, sizeof key, "update[%u].pin", (unsigned)i);
        emit_d(key, v);
        snprintf(key, sizeof key, "update[%u].switches", (unsigned)i);
        emit_l(key, law.switch_count);
        snprintf(key, sizeof key, "update[%u].counts", (unsigned)i);
        emit_l(key, law.hist_counts[law.n_hist - 1]);
    }

    if (wosp_law_get_stats(&law, &st) == WOSP_OK) {
        emit_l("stats.samples", st.samples);
        emit_l("stats.switches", st.switches);
        emit_d("stats.duty", st.duty);
        emit_l("stats.has_counts", st.has_counts ? 1 : 0);
        emit_l("stats.min", st.counts_min);
        emit_l("stats.max", st.counts_max);
        emit_l("stats.last", st.counts_last);
        emit_s("stats.final", st.final_level_high ? "HIGH" : "LOW");
        emit_s("stats.pin", st.pin);
        emit_s("stats.sense_net", st.sense_net);
        emit_s("stats.kind", st.kind == WOSP_LAW_PWM ? "pwm" : "hysteretic");
    }
    wosp_law_destroy(&law);
}

/* ---------------------------------------------------------------------- */
/* 5. PWM behaviour                                                       */
/* ---------------------------------------------------------------------- */

static void battery_pwm(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in;
    wosp_law law;
    int i;
    double low_error = 0, high_error = 0;

    memset(&in, 0, sizeof in);
    in.has_kind = true;       strcpy(in.kind, "pwm");
    in.has_pin = true;        strcpy(in.pin, "PWM0");
    in.has_sense_net = true;  strcpy(in.sense_net, "vout");
    in.has_target_v = true;   in.target_v = 3.3;
    in.has_carrier_hz = true; in.carrier_hz = 1000;
    in.has_duty_gain = true;  in.duty_gain = 0.5;

    if (wosp_law_create(&in, &law, err, sizeof err) != WOSP_OK) {
        emit_s("pwm.setup", err);
        return;
    }
    emit_s("pwm.setup", "");
    emit_d("pwm.target_counts", (double)law.target_counts);

    for (i = 0; i < 2000; i++) {
        wosp_law_update(&law, 3.0, i * 1e-7);
        low_error = law.duty;
        wosp_law_update(&law, 0.5, i * 1e-7);
        high_error = law.duty;
    }
    emit_d("pwm.low_error", low_error);
    emit_d("pwm.high_error", high_error);
    emit_l("pwm.switches", law.switch_count);
    emit_l("pwm.samples", (long)law.n_hist);

    {
        wosp_law_stats st;
        if (wosp_law_get_stats(&law, &st) == WOSP_OK) {
            emit_d("pwm.stats.duty", st.duty);
            emit_l("pwm.stats.switches", st.switches);
        }
    }
    wosp_law_destroy(&law);

    /* Saturating case: gain 100 must clamp to 1.0, never exceed it. */
    memset(&in, 0, sizeof in);
    in.has_kind = true;       strcpy(in.kind, "pwm");
    in.has_pin = true;        strcpy(in.pin, "PWM0");
    in.has_sense_net = true;  strcpy(in.sense_net, "vout");
    in.has_target_v = true;   in.target_v = 3.3;
    in.has_duty_gain = true;  in.duty_gain = 100.0;
    if (wosp_law_create(&in, &law, err, sizeof err) == WOSP_OK) {
        wosp_law_update(&law, 0.0, 0.0);
        emit_d("pwm.saturated", law.duty);
        wosp_law_destroy(&law);
    }
}

/* ---------------------------------------------------------------------- */
/* 6. Firmware import and divider semantics                               */
/* ---------------------------------------------------------------------- */

static void battery_firmware(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_firmware_constants c;
    wosp_law_input spec;
    wosp_law_spec norm;
    double lo = 0, hi = 0;
    double dividers[] = {1.0, 0.5};
    int d;

    if (wosp_read_firmware_constants(FW, &c, err, sizeof err) == WOSP_OK) {
        emit_s("fw.setup", "");
        emit_s("fw.pin", c.pin);
        emit_l("fw.low", c.low);
        emit_l("fw.high", c.high);
    } else {
        emit_s("fw.setup", err);
        return;
    }

    for (d = 0; d < 2; d++) {
        char key[128];
        double div = dividers[d];

        memset(&spec, 0, sizeof spec);
        if (wosp_law_from_firmware_source(FW, "vout", div,
                                          WOSP_DEFAULT_VHIGH,
                                          WOSP_DEFAULT_VREF,
                                          WOSP_DEFAULT_ADC_BITS,
                                          &spec, err, sizeof err) != WOSP_OK) {
            snprintf(key, sizeof key, "fw.div[%d]", d);
            emit_s(key, err);
            continue;
        }
        snprintf(key, sizeof key, "fw.div[%d]", d);
        emit_s(key, "");
        snprintf(key, sizeof key, "fw.div[%d].target", d);
        emit_d(key, spec.target_v);
        snprintf(key, sizeof key, "fw.div[%d].hyst", d);
        emit_d(key, spec.hysteresis_v);
        snprintf(key, sizeof key, "fw.div[%d].source", d);
        emit_s(key, spec.source);
        snprintf(key, sizeof key, "fw.div[%d].src_low", d);
        emit_l(key, spec.source_low);
        snprintf(key, sizeof key, "fw.div[%d].src_high", d);
        emit_l(key, spec.source_high);

        if (wosp_normalize_law(&spec, &norm, err, sizeof err) == WOSP_OK) {
            snprintf(key, sizeof key, "fw.div[%d].low", d);
            emit_l(key, norm.low_counts);
            snprintf(key, sizeof key, "fw.div[%d].high", d);
            emit_l(key, norm.high_counts);
            snprintf(key, sizeof key, "fw.div[%d].target_norm", d);
            emit_d(key, norm.target_v);
        }
    }

    /* _exact() must reproduce the file's integers verbatim. */
    memset(&spec, 0, sizeof spec);
    if (wosp_law_from_firmware_source_exact(FW, "fb", 1.0,
                                             WOSP_DEFAULT_VHIGH,
                                             WOSP_DEFAULT_VREF,
                                             WOSP_DEFAULT_ADC_BITS,
                                             &spec, err, sizeof err) == WOSP_OK) {
        emit_s("fw.exact", "");
        emit_l("fw.exact.low", spec.low_counts);
        emit_l("fw.exact.high", spec.high_counts);
        emit_d("fw.exact.divider", spec.divider);
        emit_s("fw.exact.pin", spec.pin);
        emit_s("fw.exact.source", spec.source);

        if (wosp_normalize_law(&spec, &norm, err, sizeof err) == WOSP_OK) {
            emit_l("fw.exact.norm_low", norm.low_counts);
            emit_l("fw.exact.norm_high", norm.high_counts);
        }

        if (wosp_implied_pin_voltages(&spec, &lo, &hi, err, sizeof err) == WOSP_OK) {
            emit_d("fw.pin_v.lo", lo);
            emit_d("fw.pin_v.hi", hi);
            emit_d("fw.pin_v.mid", (lo + hi) / 2.0);
        }
        if (wosp_implied_output_voltages(&spec, 0.5, &lo, &hi,
                                         err, sizeof err) == WOSP_OK) {
            emit_d("fw.out_v.lo", lo);
            emit_d("fw.out_v.hi", hi);
        }
        /* A bad pin divider must be rejected, after the pin voltages are
         * computed - the same order Python validates in. */
        g_err[0] = '\0';
        emit_l("fw.bad_div.status",
               wosp_implied_output_voltages(&spec, 0.0, &lo, &hi,
                                            g_err, sizeof g_err) == WOSP_OK ? 0 : 1);
        emit_s("fw.bad_div.msg", g_err);

        /* Re-derive from the undivided node: the switching points must not
         * move, but the reported target halves. */
        memset(&spec, 0, sizeof spec);
        if (wosp_law_from_firmware_source(FW, "vout", 0.5,
                                          WOSP_DEFAULT_VHIGH,
                                          WOSP_DEFAULT_VREF,
                                          WOSP_DEFAULT_ADC_BITS,
                                          &spec, err, sizeof err) == WOSP_OK
            && wosp_normalize_law(&spec, &norm, err, sizeof err) == WOSP_OK) {
            emit_l("fw.vout_half.low", norm.low_counts);
            emit_l("fw.vout_half.high", norm.high_counts);
            emit_d("fw.vout_half.target", norm.target_v);
        }
    } else {
        emit_s("fw.exact", err);
    }

    /* A source with none of the three constants must be refused. */
    emit_s("fw.empty_source",
           wosp_read_firmware_constants("does/not/exist.c", &c,
                                        err, sizeof err) == WOSP_OK ? "" : err);
}

/* ---------------------------------------------------------------------- */
/* 7. Regulation error                                                    */
/* ---------------------------------------------------------------------- */

static const long REG_A[] = {0, 12, 8, 12, 8};
static const long REG_B[] = {100, 101, 99, 100, 100, 102, 98, 100, 100, 100};
static const long REG_C[] = {5, 5, 5, 5, 5, 5, 5, 5, 5, 5,
                             5, 5, 5, 5, 5, 5, 5, 5, 5, 5};
static const long REG_ONE[] = {1995};

static void battery_regulation(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_regulation_error re;
    int has;

    has = (wosp_law_regulation_error(REG_A, 5, 10, 3.3, 12, &re,
                                 err, sizeof err) == WOSP_OK) && re.has;
    emit_l("regA.has", has ? 1 : 0);
    if (has) {
        emit_d("regA.mean", re.mean_error_counts);
        emit_d("regA.max", re.max_error_counts);
        emit_d("regA.final", re.final_error_counts);
        emit_d("regA.mean_v", re.mean_error_v);
    }

    has = (wosp_law_regulation_error(REG_B, 10, 100, 3.3, 12, &re,
                                 err, sizeof err) == WOSP_OK) && re.has;
    emit_l("regB.has", has ? 1 : 0);
    if (has) {
        emit_d("regB.mean", re.mean_error_counts);
        emit_d("regB.max", re.max_error_counts);
        emit_d("regB.final", re.final_error_counts);
    }

    has = (wosp_law_regulation_error(REG_C, 20, 5, 5.0, 16, &re,
                                 err, sizeof err) == WOSP_OK) && re.has;
    emit_l("regC.has", has ? 1 : 0);
    if (has) {
        emit_d("regC.mean", re.mean_error_counts);
        emit_d("regC.max", re.max_error_counts);
    }

    has = (wosp_law_regulation_error(NULL, 0, 10, 3.3, 12, &re,
                                 err, sizeof err) == WOSP_OK) && re.has;
    emit_l("regEmpty.has", has ? 1 : 0);

    /* One sample: Python divides by zero, C refuses.  Both must fail.
     *
     * Only the STATUS is compared.  The two messages are deliberately
     * different - Python raises ZeroDivisionError ("division by zero"), C
     * returns a status explaining the precondition - and neither is a
     * transcription of the other, so diffing the text would be comparing two
     * sentences that were never meant to match.  Each side pins its own
     * wording in its own unit test: native/tests/test_control_law.c asserts
     * the status text, tests/test_cosim_control.py asserts the exception.
     */
    emit_l("regOne.status",
           wosp_law_regulation_error(REG_ONE, 1, 10, 3.3, 12, &re,
                                 err, sizeof err) == WOSP_OK ? 0 : 1);
}

/* ---------------------------------------------------------------------- */
/* 8. describe_law                                                        */
/* ---------------------------------------------------------------------- */

static void battery_describe(void)
{
    char buf[WOSP_ERRMSG_MAX];
    wosp_law_input in;

    /* NB: spec_at() returns by value, and a function call is not an lvalue,
     * so it must be materialised before its address can be taken. */
    in = spec_at(0);
    wosp_describe_law(&in, buf, sizeof buf);
    emit_s("desc.fixture", buf);

    in = spec_at(2);
    wosp_describe_law(&in, buf, sizeof buf);
    emit_s("desc.pwm", buf);

    memset(&in, 0, sizeof in);
    in.has_kind = true;
    strcpy(in.kind, "banana");
    wosp_describe_law(&in, buf, sizeof buf);
    emit_s("desc.invalid", buf);
}

int main(void)
{
    battery_adc();
    battery_specs();
    battery_decide();
    battery_update();
    battery_pwm();
    battery_firmware();
    battery_regulation();
    battery_describe();
    return 0;
}
