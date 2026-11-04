/*
 * test_control_law.c - port of the Python control_law test contract.
 *
 * WHAT IS PORTED
 *
 *   tests/test_control_law_unit.py   all 18 tests
 *   tests/test_adc_conversion.py     all 12 tests
 *   tests/test_cosim_control.py      the control-law classes only
 *
 * Test functions keep the Python test's name, so the two suites stay
 * greppable against each other:
 *
 *     Select-String -Path tests\*.py -Pattern 'def (test_\w+)'
 *     Select-String -Path native\tests\test_control_law.c -Pattern 'RUN\((\w+)\)'
 *
 * Two Python tests share a name across files (test_inside_band_holds_previous_state
 * appears in both test_control_law_unit.py and test_cosim_control.py on
 * different fixtures), so the cosim one carries a _cosim suffix here.  Where
 * several Python tests were folded into one, or one was not transcribed, the
 * comment at the function says so - that is a deliberate, reviewable choice,
 * not a silent gap.
 *
 * WHAT IS NOT PORTED, AND WHY
 *
 *   test_cosim_control.py          TestNetlistEmission, TestEndToEndBuck and
 *                                  the save/reload and warning-path classes all
 *                                  call the ngspice solver through
 *                                  bridge/cosim_runner.py.  They are not
 *                                  control-law tests wearing a different name:
 *                                  they assert on netlist text, on a transient
 *                                  run regulating to 3.3 V, and on UI-level
 *                                  warning plumbing.  Porting them means
 *                                  porting the solver first.
 *
 *   bridge/control_law.py surface  The four tests at the bottom of this file
 *                                  are NOT ports.  They are marked C-ONLY
 *                                  ADDITIONS in a block comment because the
 *                                  Python suite leaves regulation_error()
 *                                  entirely untested and stats() only
 *                                  indirectly so.
 *
 * A test that does not exist here must not be read as "the Python test was
 * dropped" - check this list first, then the Python file.
 *
 * WHAT THIS CANNOT PROVE
 *
 * No test here measures real silicon; the firmware is read, not executed.
 * native/tools/parity_control_law.py additionally diffs this implementation
 * against bridge/control_law.py on a battery neither suite was transcribed
 * from, which is what catches a port and its ported test being wrong in the
 * same way.
 */

#include "wowkispice/control_law.h"
#include "wosp_test.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef WOSP_FIRMWARE_MAIN_C
#define WOSP_FIRMWARE_MAIN_C "../firmware/esp32_buck_controller/src/main.c"
#endif
#ifndef WOSP_TEST_TMPDIR
#define WOSP_TEST_TMPDIR "."
#endif

/* ---------------------------------------------------------------------- */
/* Fixtures                                                               */
/* ---------------------------------------------------------------------- */

static const char *FIRMWARE_MAIN_C = WOSP_FIRMWARE_MAIN_C;

/* {"kind": "hysteretic", "pin": "GPIO18", "sense_net": "vout"} */
static wosp_law_input base_hysteretic(void)
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

/*
 * The firmware's ADC_LOW_THRESHOLD/ADC_HIGH_THRESHOLD (1995/2030) are raw
 * counts at the ADC pin (firmware/esp32_buck_controller/src/main.c lines
 * 40-41).  Explicit counts are used so the decision boundary is bit-for-bit
 * the firmware's.
 */
static wosp_law_input fixture_with_counts(void)
{
    wosp_law_input in = base_hysteretic();
    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_divider = true;      in.divider = 0.5;
    in.has_vref = true;         in.vref = 3.3;
    in.has_adc_bits = true;     in.adc_bits = 12;
    in.has_low_counts = true;   in.low_counts = 1995;
    in.has_high_counts = true;  in.high_counts = 2030;
    return in;
}

/* The law described by the real firmware in this repo. */
static wosp_law_input firmware_law(const char *sense_net, double divider,
                                   char *err, size_t errlen)
{
    wosp_law_input in;
    memset(&in, 0, sizeof in);
    wosp_law_from_firmware_source_exact(FIRMWARE_MAIN_C, sense_net, divider,
                                        WOSP_DEFAULT_VHIGH, WOSP_DEFAULT_VREF,
                                        WOSP_DEFAULT_ADC_BITS,
                                        &in, err, errlen);
    return in;
}

/* Read a whole file as bytes; caller frees.  Returns NULL on failure. */
static char *slurp(const char *path)
{
    FILE *f = fopen(path, "rb");
    long size;
    char *buf;
    if (f == NULL) {
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size < 0) {
        fclose(f);
        return NULL;
    }
    buf = (char *)malloc((size_t)size + 1);
    if (buf == NULL) {
        fclose(f);
        return NULL;
    }
    if (fread(buf, 1, (size_t)size, f) != (size_t)size) {
        free(buf);
        fclose(f);
        return NULL;
    }
    buf[size] = '\0';
    fclose(f);
    return buf;
}

static void write_tmp(const char *name, const char *content,
                      char *out_path, size_t out_len)
{
    FILE *f;
    snprintf(out_path, out_len, "%s/%s", WOSP_TEST_TMPDIR, name);
    f = fopen(out_path, "wb");
    if (f != NULL) {
        fputs(content, f);
        fclose(f);
    }
}

/* Assert that a spec is rejected, labelling the failure like a subTest. */
static void expect_normalize_fail(const wosp_law_input *in, const char *label)
{
    wosp_law_spec s;
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_status st = wosp_normalize_law(in, &s, err, sizeof err);
    wosp_t_checks++;
    if (st == WOSP_OK) {
        wosp_t_check_fails++;
        printf("  x %s:%d: expected ControlLawError for %s\n",
               __FILE__, __LINE__, label);
    }
}

/* ---------------------------------------------------------------------- */
/* tests/test_control_law_unit.py::TestSpecNormalization                  */
/* ---------------------------------------------------------------------- */

static void test_normalize_fills_defaults(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = base_hysteretic();
    wosp_law_spec s;

    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_divider = true;      in.divider = 0.5;
    in.has_vref = true;         in.vref = 3.3;
    in.has_adc_bits = true;     in.adc_bits = 12;

    REQUIRE_OK(wosp_normalize_law(&in, &s, err, sizeof err));
    CHECK(s.kind == WOSP_LAW_HYSTERETIC);
    /* assert "low_counts" in law and "high_counts" in law */
    CHECK(s.low_counts != s.high_counts);
    CHECK(s.low_counts > 0);
    CHECK(s.high_counts > s.low_counts);
}

static void test_rejects_unknown_kind(void)
{
    /* normalize_law accepts only LAW_KINDS = ('hysteretic', 'pwm'); everything
     * else must raise, and the message must name the offending kind so a test
     * can match on it. */
    const char *bad[] = {"sine", "bang-bang"};
    size_t i;
    for (i = 0; i < sizeof bad / sizeof bad[0]; i++) {
        wosp_law_input in = base_hysteretic();
        wosp_law_spec s;
        char err[WOSP_ERRMSG_MAX] = {0};
        strcpy(in.kind, bad[i]);
        REQUIRE_FAIL(wosp_normalize_law(&in, &s, err, sizeof err));
        CHECK_STR_CONTAINS(err, bad[i]);
    }
    /* Empty kind must also be rejected. */
    {
        wosp_law_input in = base_hysteretic();
        wosp_law_spec s;
        char err[WOSP_ERRMSG_MAX] = {0};
        in.kind[0] = '\0';
        REQUIRE_FAIL(wosp_normalize_law(&in, &s, err, sizeof err));
    }
}

static void test_accepts_pwm_kind(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = base_hysteretic();
    wosp_law_spec s;

    strcpy(in.kind, "pwm");
    in.has_target_v = true; in.target_v = 3.3;
    in.has_vref = true;     in.vref = 3.3;
    in.has_adc_bits = true; in.adc_bits = 12;

    REQUIRE_OK(wosp_normalize_law(&in, &s, err, sizeof err));
    CHECK(s.kind == WOSP_LAW_PWM);
}

static void test_rejects_zero_divider(void)
{
    wosp_law_input in = base_hysteretic();
    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_divider = true;      in.divider = 0;
    expect_normalize_fail(&in, "divider=0");
}

static void test_rejects_negative_adc_bits(void)
{
    wosp_law_input in = base_hysteretic();
    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_vref = true;         in.vref = 3.3;
    in.has_adc_bits = true;     in.adc_bits = 4;   /* below the 8..24 floor */
    expect_normalize_fail(&in, "adc_bits=4");
}

/* ---------------------------------------------------------------------- */
/* tests/test_control_law_unit.py::TestHystereticDecision                 */
/* ---------------------------------------------------------------------- */

static void test_every_transition_around_1995_and_2030(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;

    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));

    /* The firmware's branch order is < low -> HIGH, > high -> LOW, else
     * hold - so exactly 1995 and exactly 2030 hold. */
    CHECK(wosp_law_decide(&law, 1992) == true);
    CHECK(wosp_law_decide(&law, 1994) == true);
    law.level = true;
    CHECK(wosp_law_decide(&law, 1995) == true);
    law.level = false;
    CHECK(wosp_law_decide(&law, 1995) == false);
    law.level = true;
    CHECK(wosp_law_decide(&law, 2030) == true);
    law.level = false;
    CHECK(wosp_law_decide(&law, 2030) == false);

    /* 2031 is above the high threshold, so the firmware drives LOW (main.c
     * uses strict `>`).  It never forces HIGH; instead it forces the gate OFF
     * from any prior ON state, and holds OFF when already OFF. */
    law.level = true;
    CHECK(wosp_law_decide(&law, 2031) == false);
    law.level = false;
    CHECK(wosp_law_decide(&law, 2031) == false);
    CHECK(wosp_law_decide(&law, 2033) == false);

    wosp_law_destroy(&law);
}

static void test_below_low_drives_high(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    CHECK(wosp_law_decide(&law, 1994) == true);
    wosp_law_destroy(&law);
}

static void test_above_high_drives_low(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    CHECK(wosp_law_decide(&law, 2030) == false);
    CHECK(wosp_law_decide(&law, 2031) == false);
    CHECK(wosp_law_decide(&law, 2032) == false);
    wosp_law_destroy(&law);
}

static void test_exact_at_high_holds_when_low(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    law.level = true;
    CHECK(wosp_law_decide(&law, 2030) == true);
    wosp_law_destroy(&law);
}

static void test_inside_band_holds_previous_state(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;
    long inside;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    inside = (law.low_counts + law.high_counts) / 2;   /* Python // on positives */
    law.level = true;
    CHECK(wosp_law_decide(&law, inside) == true);
    law.level = false;
    CHECK(wosp_law_decide(&law, inside) == false);
    wosp_law_destroy(&law);
}

/* ---------------------------------------------------------------------- */
/* tests/test_control_law_unit.py::TestDividerSemantics                   */
/* ---------------------------------------------------------------------- */

static void test_pin_referenced_net_needs_no_divider(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input spec = firmware_law("fb", 1.0, err, sizeof err);
    REQUIRE_OK(spec.has_pin ? WOSP_OK : WOSP_ERR_FILE);
    CHECK(spec.divider == 1.0);
    CHECK_EQ_LONG(spec.low_counts, 1995);
    CHECK_EQ_LONG(spec.high_counts, 2030);
}

static void test_undivided_node_regulates_to_half(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input spec = firmware_law("vout", 0.5, err, sizeof err);
    double lo = 0, hi = 0;
    REQUIRE_OK(wosp_implied_output_voltages(&spec, 0.5, &lo, &hi, err, sizeof err));
    CHECK_NEAR(lo, 3.2154, 0.01);
    CHECK_NEAR(hi, 3.2718, 0.01);
}

static void test_reapplying_divider_twice_halves_the_target(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input spec = firmware_law("vout", 0.5, err, sizeof err);
    wosp_law_spec s;

    spec.divider = 1.0;              /* spec["divider"] = 1.0 */
    REQUIRE_OK(wosp_normalize_law(&spec, &s, err, sizeof err));
    CHECK_EQ_LONG(s.low_counts, 1995);
    CHECK_EQ_LONG(s.high_counts, 2030);
}

/* ---------------------------------------------------------------------- */
/* tests/test_control_law_unit.py::TestFidelityGap                        */
/* ---------------------------------------------------------------------- */

static void test_firmware_still_oversamples(void)
{
    char *src = slurp(FIRMWARE_MAIN_C);
    CHECK(src != NULL);
    if (src != NULL) {
        CHECK_STR_CONTAINS(src, "ADC_OVERSAMPLE_N");
        free(src);
    }
}

static void test_firmware_still_calibrates(void)
{
    char *src = slurp(FIRMWARE_MAIN_C);
    CHECK(src != NULL);
    if (src != NULL) {
        CHECK_STR_CONTAINS(src, "adc_cali");
        free(src);
    }
}

static void test_firmware_still_says_counts_are_raw(void)
{
    char *src = slurp(FIRMWARE_MAIN_C);
    CHECK(src != NULL);
    if (src != NULL) {
        CHECK_STR_CONTAINS(src, "RAW counts");
        free(src);
    }
}

/* ---------------------------------------------------------------------- */
/* tests/test_control_law_unit.py::TestAdcFrontEndAndThresholds           */
/* ---------------------------------------------------------------------- */

static void test_to_counts_applies_the_sense_divider(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = base_hysteretic();
    wosp_law law;

    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_divider = true;      in.divider = 0.5;
    in.has_vref = true;         in.vref = 3.3;
    in.has_adc_bits = true;     in.adc_bits = 12;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));

    /* 2.4 V at the sense node is 1.2 V at the ADC once the 0.5 divider has
     * done its work; dropping the divider reports counts for double the
     * voltage the firmware actually samples. */
    CHECK_EQ_LONG(wosp_to_counts(&law, 2.4), wosp_to_counts_raw(1.2, 3.3, 12));
    CHECK(wosp_to_counts(&law, 2.4) != wosp_to_counts_raw(2.4, 3.3, 12));
    wosp_law_destroy(&law);
}

static void test_equal_threshold_counts_are_rejected(void)
{
    /* low == high leaves no band to hold a state in, so a law built from it
     * would decide purely on which side of one number the sample sits. */
    wosp_law_input in = base_hysteretic();
    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_divider = true;      in.divider = 0.5;
    in.has_vref = true;         in.vref = 3.3;
    in.has_adc_bits = true;     in.adc_bits = 12;
    in.has_low_counts = true;   in.low_counts = 2000;
    in.has_high_counts = true;  in.high_counts = 2000;
    expect_normalize_fail(&in, "low_counts == high_counts");
}

/* ---------------------------------------------------------------------- */
/* tests/test_adc_conversion.py::TestToCountsClampAndRounding             */
/* ---------------------------------------------------------------------- */

static void test_negative_maps_to_zero(void)
{
    /* -0.001 V must be clamped to 0 counts, not wrapped. */
    CHECK_EQ_LONG(wosp_to_counts_raw(-0.001, 3.3, 12), 0);
}

static void test_exact_half_lsb_rounds_down(void)
{
    /* A voltage exactly half an LSB above 0 must round to 0 counts.  The
     * halfway point of the 12-bit range in volts is 3.3/8190.  This lands on
     * an exact .5 in counts, so it is the case that distinguishes Python's
     * round-half-to-even from C's round-half-away-from-zero. */
    CHECK_EQ_LONG(wosp_to_counts_raw(3.3 / 8190, 3.3, 12), 0);
    /* One ulp above the half-LSB boundary must round up to 1. */
    CHECK_EQ_LONG(wosp_to_counts_raw(3.3 / 8190 + 1e-9, 3.3, 12), 1);
}

static void test_exact_full_scale_clips_to_max(void)
{
    /* 3.3 V is exactly full scale and must map to 4095, never 4096. */
    CHECK_EQ_LONG(wosp_to_counts_raw(3.3, 3.3, 12), 4095);
}

static void test_just_below_full_scale(void)
{
    /* One ulp below full scale is a real count, not clipped. */
    CHECK_EQ_LONG(wosp_to_counts_raw(3.3 - 1e-9, 3.3, 12), 4095);
}

static void test_above_vref_clips(void)
{
    CHECK_EQ_LONG(wosp_to_counts_raw(3.31, 3.3, 12), 4095);
}

static void test_clamp_behaviour_without_float(void)
{
    /* The clamp must hold even for a voltage clearly above Vref but tiny
     * enough that exact half-lsb rounding would otherwise matter. */
    CHECK_EQ_LONG(wosp_to_counts_raw(3.30000001, 3.3, 12), 4095);
}

/*
 * TestLawCountsAtThresholds - each Python test kept its own name so the two
 * suites stay greppable against each other.  They are separate functions
 * rather than one combined table because a failure must name the exact
 * boundary that broke.
 */

static void test_decide_below_low_drives_high(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;

    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    /* firmware branch: raw_adc < ADC_LOW_THRESHOLD -> drive HIGH */
    CHECK(wosp_law_decide(&law, 1994) == true);
    CHECK(wosp_law_decide(&law, 1993) == true);
    wosp_law_destroy(&law);
}

static void test_decide_at_low_drives_high_hold(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;

    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    /* Exactly at ADC_LOW_THRESHOLD holds the previous state, because the
     * firmware's hold region is the inclusive band [1995, 2030]. */
    law.level = true;
    CHECK(wosp_law_decide(&law, 1995) == true);
    law.level = false;
    CHECK(wosp_law_decide(&law, 1995) == false);
    /* Just below still drives HIGH. */
    CHECK(wosp_law_decide(&law, 1994) == true);
    wosp_law_destroy(&law);
}

static void test_decide_inside_band_holds(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;
    long inside;

    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    /* Python's `//` on positives is C's truncating `/`. */
    inside = (law.low_counts + law.high_counts) / 2;
    law.level = true;
    CHECK(wosp_law_decide(&law, inside) == true);
    law.level = false;
    CHECK(wosp_law_decide(&law, inside) == false);
    law.level = true;
    CHECK(wosp_law_decide(&law, inside + 1) == true);
    law.level = false;
    CHECK(wosp_law_decide(&law, inside + 1) == false);
    wosp_law_destroy(&law);
}

static void test_decide_at_high_drives_low_hold(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;

    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    /* Exactly at ADC_HIGH_THRESHOLD holds the previous state. */
    law.level = true;
    CHECK(wosp_law_decide(&law, 2030) == true);
    law.level = false;
    CHECK(wosp_law_decide(&law, 2030) == false);
    /* Just above still drives LOW. */
    CHECK(wosp_law_decide(&law, 2031) == false);
    wosp_law_destroy(&law);
}

static void test_decide_above_high_drives_low(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;

    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    CHECK(wosp_law_decide(&law, 2031) == false);
    CHECK(wosp_law_decide(&law, 2032) == false);
    wosp_law_destroy(&law);
}

static void test_update_counts_switches_only_on_change(void)
{
    /*
     * With the firmware's real thresholds (1995/2030), two readings inside
     * the hysteresis band must not change the level or switch_count.
     *
     * The Python comment says 3.25 V through the 2:1 divider is "2023
     * counts".  That arithmetic is off: 1.625/3.3*4095 = 2016.48 -> 2016,
     * which is still inside (1995, 2030), and the Python test asserts only
     * that the second reading matches the first and that no switch occurred -
     * it never pins the count value, so neither does this port.  The wrong
     * number is prose nobody depends on; a port that "fixed" it by asserting
     * 2023 would be asserting something neither implementation produces.
     */
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;
    long first;

    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    wosp_law_update(&law, 3.25, 0.0);
    CHECK(law.n_hist >= 1);
    first = law.hist_counts[law.n_hist - 1];
    wosp_law_update(&law, 3.25, 1e-6);
    CHECK_EQ_LONG(law.hist_counts[law.n_hist - 1], first);
    CHECK_EQ_LONG(law.switch_count, 0);
    wosp_law_destroy(&law);
}

/* ---------------------------------------------------------------------- */
/* tests/test_cosim_control.py::TestControlLawSpec                        */
/* ---------------------------------------------------------------------- */

static void test_hysteretic_counts_come_from_target_and_hysteresis(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = base_hysteretic();
    wosp_law law;

    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_divider = true;      in.divider = 0.5;
    in.has_vref = true;         in.vref = 3.3;
    in.has_adc_bits = true;     in.adc_bits = 12;

    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    /* (3.3 -+ 0.165) V through a 0.5 divider, 12-bit over a 3.3 V reference */
    CHECK_EQ_LONG(law.spec.low_counts, 1945);
    CHECK_EQ_LONG(law.spec.high_counts, 2150);
    CHECK(law.low_counts < law.high_counts);
    wosp_law_destroy(&law);
}

static void test_explicit_counts_are_preserved_verbatim(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = base_hysteretic();
    wosp_law law;

    in.has_target_v = true;     in.target_v = 1.0;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.01;
    in.has_low_counts = true;   in.low_counts = 1995;
    in.has_high_counts = true;  in.high_counts = 2030;

    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    CHECK_EQ_LONG(law.low_counts, 1995);
    CHECK_EQ_LONG(law.high_counts, 2030);
    wosp_law_destroy(&law);
}

static void test_rejects_nonsense(void)
{
    wosp_law_input base = base_hysteretic();
    wosp_law_input in;

    in = base; strcpy(in.kind, "sine");
    expect_normalize_fail(&in, "kind=sine");

    in = base; in.has_hysteresis_v = true; in.hysteresis_v = 0;
    expect_normalize_fail(&in, "hysteresis_v=0 (no dead band)");

    in = base; in.has_target_v = true; in.target_v = 1.0;
    in.has_hysteresis_v = true; in.hysteresis_v = 2.0;
    expect_normalize_fail(&in, "hysteresis_v > target_v");

    in = base; in.has_vhigh = true; in.vhigh = 99;
    expect_normalize_fail(&in, "vhigh=99");

    in = base; in.has_divider = true; in.divider = 0;
    expect_normalize_fail(&in, "divider=0");

    in = base; in.has_low_counts = true; in.low_counts = 3000;
    in.has_high_counts = true; in.high_counts = 100;
    expect_normalize_fail(&in, "low_counts > high_counts");

    in = base; in.has_adc_bits = true; in.adc_bits = 40;
    expect_normalize_fail(&in, "adc_bits=40");

    in = base; in.has_pin = false;
    expect_normalize_fail(&in, "no pin");

    in = base; in.has_sense_net = false;
    expect_normalize_fail(&in, "no sense_net");

    in = base; strcpy(in.kind, "pwm");
    in.has_pin = true; strcpy(in.pin, "P1");
    in.has_carrier_hz = true; in.carrier_hz = 0;
    expect_normalize_fail(&in, "pwm carrier_hz=0");
}

static void test_describe_never_raises_on_junk(void)
{
    char buf[WOSP_ERRMSG_MAX];
    wosp_law_input in;
    memset(&in, 0, sizeof in);
    in.has_kind = true;
    strcpy(in.kind, "banana");
    wosp_describe_law(&in, buf, sizeof buf);
    CHECK_STR_CONTAINS(buf, "invalid");
}

/* ---------------------------------------------------------------------- */
/* tests/test_cosim_control.py::TestHystereticDecision                    */
/* ---------------------------------------------------------------------- */

/* counts_for(volts) = _to_counts(volts * 0.5, 3.3, 12) */
static long counts_for(double volts)
{
    return wosp_to_counts_raw(volts * 0.5, 3.3, 12);
}

static void test_below_band_drives_high(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = base_hysteretic();
    wosp_law law;
    long below;

    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_divider = true;      in.divider = 0.5;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));

    below = counts_for(3.3 - 0.5);
    CHECK(below < law.low_counts);
    CHECK(wosp_law_decide(&law, below) == true);
    wosp_law_destroy(&law);
}

static void test_above_band_drives_low(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = base_hysteretic();
    wosp_law law;
    long above;

    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_divider = true;      in.divider = 0.5;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));

    above = counts_for(3.3 + 0.5);
    CHECK(above > law.high_counts);
    CHECK(wosp_law_decide(&law, above) == false);
    wosp_law_destroy(&law);
}

/*
 * Same name as the test_control_law_unit.py test of the same name, but a
 * different fixture: this one runs on counts derived from target+hysteresis
 * (1945/2150) rather than the firmware's explicit 1995/2030, so it exercises
 * the derived-threshold path.  C allows one identifier per function, hence
 * the _cosim suffix here - it names the source file, not a variation.
 */
static void test_inside_band_holds_previous_state_cosim(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = base_hysteretic();
    wosp_law law;
    long inside;

    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_divider = true;      in.divider = 0.5;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));

    inside = (law.low_counts + law.high_counts) / 2;
    law.level = true;
    CHECK(wosp_law_decide(&law, inside) == true);
    law.level = false;
    CHECK(wosp_law_decide(&law, inside) == false);
    wosp_law_destroy(&law);
}

static void test_update_counts_switches_only_on_a_level_change(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = base_hysteretic();
    wosp_law law;
    long low, high;
    double v;

    in.has_target_v = true;     in.target_v = 3.3;
    in.has_hysteresis_v = true; in.hysteresis_v = 0.165;
    in.has_divider = true;      in.divider = 0.5;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));

    low = counts_for(0.0);
    high = counts_for(5.0);

    v = wosp_law_update(&law, 0.0, 0.0);
    CHECK(v == 3.3);                    /* LOW counts -> HIGH */
    CHECK_EQ_LONG(law.switch_count, 1);
    v = wosp_law_update(&law, 5.0, 1e-6);
    CHECK(v == 0.0);                    /* HIGH counts -> LOW */
    CHECK_EQ_LONG(law.switch_count, 2);
    wosp_law_update(&law, 5.0, 2e-6);   /* hold LOW */
    CHECK_EQ_LONG(law.switch_count, 2);

    /* 0 V sense reads as 0 counts; 5 V through the 0.5 divider saturates
     * nothing. */
    CHECK_EQ_LONG(low, 0);
    CHECK_EQ_LONG(high, 3102);

    wosp_law_destroy(&law);
}

/* ---------------------------------------------------------------------- */
/* tests/test_cosim_control.py::TestFirmwareImport                        */
/* ---------------------------------------------------------------------- */

static void test_reads_thresholds_and_gate_pin_from_real_source(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_firmware_constants c;
    REQUIRE_OK(wosp_read_firmware_constants(FIRMWARE_MAIN_C, &c, err, sizeof err));
    CHECK(strcmp(c.pin, "GPIO18") == 0);
    CHECK_EQ_LONG(c.low, 1995);
    CHECK_EQ_LONG(c.high, 2030);
}

static void test_imported_spec_keeps_the_file_counts(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input spec = firmware_law("fb", 1.0, err, sizeof err);
    wosp_law_spec s;

    REQUIRE_OK(spec.has_pin ? WOSP_OK : WOSP_ERR_FILE);
    CHECK(strcmp(spec.pin, "GPIO18") == 0);
    CHECK(strcmp(spec.source, "main.c") == 0);
    REQUIRE_OK(wosp_normalize_law(&spec, &s, err, sizeof err));
    CHECK_EQ_LONG(s.low_counts, 1995);
    CHECK_EQ_LONG(s.high_counts, 2030);
}

static void test_missing_file_and_missing_constants_are_reported(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_firmware_constants c;
    char path[1024];

    REQUIRE_FAIL(wosp_read_firmware_constants("does/not/exist.c", &c,
                                              err, sizeof err));
    CHECK_STR_CONTAINS(err, "not found");

    write_tmp("empty.c", "int main(void) { return 0; }\n", path, sizeof path);
    err[0] = '\0';
    REQUIRE_FAIL(wosp_read_firmware_constants(path, &c, err, sizeof err));
    CHECK_STR_CONTAINS(err, "ADC_LOW_THRESHOLD");
}

static void test_inverted_thresholds_are_rejected(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_firmware_constants c;
    char path[1024];

    write_tmp("bad.c",
              "#define ADC_LOW_THRESHOLD 3000\n"
              "#define ADC_HIGH_THRESHOLD 100\n"
              "#define GATE_PIN GPIO_NUM_4\n",
              path, sizeof path);
    REQUIRE_FAIL(wosp_read_firmware_constants(path, &c, err, sizeof err));
    CHECK_STR_CONTAINS(err, "nonsense thresholds");
}

/* ---------------------------------------------------------------------- */
/* tests/test_cosim_control.py::TestDividerSemantics                      */
/* ---------------------------------------------------------------------- */

static void test_thresholds_are_counts_at_the_pin(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input s = firmware_law("fb", 1.0, err, sizeof err);
    REQUIRE_OK(s.has_pin ? WOSP_OK : WOSP_ERR_FILE);
    CHECK_EQ_LONG(s.low_counts, 1995);
    CHECK_EQ_LONG(s.high_counts, 2030);
    CHECK(s.divider == 1.0);   /* a pin-referenced sense net needs no divider */
}

static void test_pin_voltages_invert_the_firmware_mapping(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input s = firmware_law("fb", 1.0, err, sizeof err);
    double lo = 0, hi = 0;
    REQUIRE_OK(wosp_implied_pin_voltages(&s, &lo, &hi, err, sizeof err));
    /* 1995/4095*3.3 and 2030/4095*3.3 */
    CHECK_PLACES(lo, 1.6077, 3);
    CHECK_PLACES(hi, 1.6359, 3);
}

static void test_midpoint_matches_the_firmware_comment(void)
{
    /* main.c claims ~2012 counts is 3.24 V out.  Check it. */
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input s = firmware_law("fb", 1.0, err, sizeof err);
    double lo = 0, hi = 0, mid_out;
    REQUIRE_OK(wosp_implied_pin_voltages(&s, &lo, &hi, err, sizeof err));
    mid_out = ((lo + hi) / 2.0) / 0.5;      /* 2:1 divider to vout */
    CHECK_PLACES(mid_out, 3.2436, 3);
    CHECK_PLACES(mid_out, 3.24, 1);
}

static void test_picking_the_undivided_node_halves_the_target(void)
{
    /* The trap: sense_net='vout' regulates to half the intended voltage. */
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input s = firmware_law("fb", 1.0, err, sizeof err);
    double lo = 0, hi = 0;
    REQUIRE_OK(wosp_implied_output_voltages(&s, 0.5, &lo, &hi, err, sizeof err));
    CHECK_PLACES(lo, 3.2154, 3);
    CHECK_PLACES(hi, 3.2718, 3);
    /* Same numbers with the divider applied twice would be half again. */
    CHECK_PLACES(hi / 2.0, 1.6359, 3);
}

static void test_bad_pin_divider_is_rejected(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input s = firmware_law("fb", 1.0, err, sizeof err);
    double lo = 0, hi = 0;
    REQUIRE_FAIL(wosp_implied_output_voltages(&s, 0.0, &lo, &hi, err, sizeof err));
    CHECK_STR_CONTAINS(err, "pin_divider");
}

static void test_undivided_sense_net_with_a_divider_reproduces_the_counts(void)
{
    /* Naming the undivided net must not change the switching points.  This
     * was wrong and nothing caught it: law_from_firmware_source() divided its
     * recovered target by `divider` but left hysteresis_v in pin volts, so
     * normalize_law() multiplied both by divider again and the band came out
     * halved - 2004/2020 instead of 1995/2030, a 35% narrower deadband. */
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input vout;
    wosp_law_spec s;

    memset(&vout, 0, sizeof vout);
    REQUIRE_OK(wosp_law_from_firmware_source(FIRMWARE_MAIN_C, "vout", 0.5,
                                             WOSP_DEFAULT_VHIGH,
                                             WOSP_DEFAULT_VREF,
                                             WOSP_DEFAULT_ADC_BITS,
                                             &vout, err, sizeof err));
    REQUIRE_OK(wosp_normalize_law(&vout, &s, err, sizeof err));
    CHECK_EQ_LONG(s.low_counts, 1995);
    CHECK_EQ_LONG(s.high_counts, 2030);
}

static void test_the_two_sense_nets_agree_exactly(void)
{
    /* fb at divider 1.0 and vout at divider 0.5 are one law, not two. */
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input ia, ib;
    wosp_law_spec a, b;

    memset(&ia, 0, sizeof ia);
    memset(&ib, 0, sizeof ib);
    REQUIRE_OK(wosp_law_from_firmware_source(FIRMWARE_MAIN_C, "fb", 1.0,
                                             WOSP_DEFAULT_VHIGH,
                                             WOSP_DEFAULT_VREF,
                                             WOSP_DEFAULT_ADC_BITS,
                                             &ia, err, sizeof err));
    REQUIRE_OK(wosp_law_from_firmware_source(FIRMWARE_MAIN_C, "vout", 0.5,
                                             WOSP_DEFAULT_VHIGH,
                                             WOSP_DEFAULT_VREF,
                                             WOSP_DEFAULT_ADC_BITS,
                                             &ib, err, sizeof err));
    REQUIRE_OK(wosp_normalize_law(&ia, &a, err, sizeof err));
    REQUIRE_OK(wosp_normalize_law(&ib, &b, err, sizeof err));
    CHECK_EQ_LONG(a.low_counts, b.low_counts);
    CHECK_EQ_LONG(a.high_counts, b.high_counts);
    CHECK_PLACES(a.target_v, b.target_v * 0.5, 4);
}

/* ---------------------------------------------------------------------- */
/* tests/test_cosim_control.py::TestFidelityGap                           */
/* ---------------------------------------------------------------------- */

/*
 * `#define\s+ADC_OVERSAMPLE_N\s+(\d+)` - the value must still be a #define,
 * because the point of the test is that the constant remains a constant the
 * firmware actually compiles.
 */
static int oversample_define_value(long *out)
{
    char *src = slurp(FIRMWARE_MAIN_C);
    const char *p;
    if (src == NULL) {
        return 0;
    }
    p = strstr(src, "#define");
    while (p != NULL) {
        const char *q = p + 7;
        while (*q == ' ' || *q == '\t') {
            q++;
        }
        if (strncmp(q, "ADC_OVERSAMPLE_N", 16) == 0) {
            const char *r = q + 16;
            long v = 0;
            int digits = 0;
            while (*r == ' ' || *r == '\t') {
                r++;
            }
            while (*r >= '0' && *r <= '9') {
                v = v * 10 + (*r - '0');
                r++;
                digits = 1;
            }
            free(src);
            if (digits) {
                *out = v;
                return 1;
            }
            return 0;
        }
        p = strstr(p + 7, "#define");
    }
    free(src);
    return 0;
}

static void test_oversample_count_is_not_silently_ignored(void)
{
    /* Oversampling changes the loop, so its value must stay visible. */
    long n = 0;
    CHECK(oversample_define_value(&n) == 1);
    if (n) {
        CHECK(n >= 1);
    } else {
        CHECK_MSG(0, "ADC_OVERSAMPLE_N is not a #define any more");
    }
}

/* ---------------------------------------------------------------------- */
/* tests/test_cosim_control.py::TestPwmLaw                                */
/* ---------------------------------------------------------------------- */

static void test_duty_grows_as_feedback_falls(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in;
    wosp_law law;
    double low_error = 0, high_error = 0;
    int i;

    memset(&in, 0, sizeof in);
    in.has_kind = true;       strcpy(in.kind, "pwm");
    in.has_pin = true;        strcpy(in.pin, "PWM0");
    in.has_sense_net = true;  strcpy(in.sense_net, "vout");
    in.has_target_v = true;   in.target_v = 3.3;
    in.has_carrier_hz = true; in.carrier_hz = 1000;
    in.has_duty_gain = true;  in.duty_gain = 0.5;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));

    for (i = 0; i < 2000; i++) {
        wosp_law_update(&law, 3.0, i * 1e-7);   /* close to target */
        low_error = law.duty;
        wosp_law_update(&law, 0.5, i * 1e-7);   /* far below target */
        high_error = law.duty;
    }
    CHECK(high_error > low_error);
    CHECK(high_error <= 1.0);
    CHECK(low_error >= 0.0);
    wosp_law_destroy(&law);
}

static void test_duty_saturates_rather_than_exceeding_one(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in;
    wosp_law law;

    memset(&in, 0, sizeof in);
    in.has_kind = true;       strcpy(in.kind, "pwm");
    in.has_pin = true;        strcpy(in.pin, "PWM0");
    in.has_sense_net = true;  strcpy(in.sense_net, "vout");
    in.has_target_v = true;   in.target_v = 3.3;
    in.has_duty_gain = true;  in.duty_gain = 100.0;
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    wosp_law_update(&law, 0.0, 0.0);
    CHECK(law.duty <= 1.0);
    wosp_law_destroy(&law);
}

/* ---------------------------------------------------------------------- */
/* C-ONLY ADDITIONS - not ports of any Python test.                       */
/*                                                                        */
/* Marked loudly because the file header promises a port, and a reader who */
/* assumes every test here mirrors one over there would be wrong.          */
/*                                                                        */
/* They cover API that the Python suite does not test:                    */
/*   - regulation_error() has NO test in tests/ at all.                   */
/*   - stats() is asserted exactly once, indirectly, inside an end-to-end  */
/*     test of the report line (test_cosim_control.py line 278); its       */
/*     shape on an empty run and its counts fields are otherwise           */
/*     unexercised.                                                        */
/*   - describe() is covered in Python via describe_law(), but not for an  */
/*     already-constructed law.                                           */
/*                                                                        */
/* If the Python suite grows equivalents, fold these into the ported set   */
/* and delete this note.                                                  */
/* ---------------------------------------------------------------------- */

static void test_stats_reports_a_run(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_law_input in = fixture_with_counts();
    wosp_law law;
    wosp_law_stats st;
    int i;

    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    REQUIRE_OK(wosp_law_get_stats(&law, &st));
    CHECK_EQ_LONG(st.samples, 0);
    CHECK_EQ_LONG(st.switches, 0);
    CHECK(st.duty == 0.0);
    CHECK(st.has_counts == false);       /* Python reports None, not 0 */
    CHECK(st.final_level_high == false); /* "LOW" */

    for (i = 0; i < 10; i++) {
        wosp_law_update(&law, (i % 2) ? 5.0 : 0.0, i * 1e-6);
    }
    REQUIRE_OK(wosp_law_get_stats(&law, &st));
    CHECK_EQ_LONG(st.samples, 10);
    CHECK(st.switches >= 2);
    CHECK(st.duty > 0.0 && st.duty < 1.0);
    CHECK(st.has_counts == true);
    CHECK_EQ_LONG(st.counts_min, 0);
    CHECK_EQ_LONG(st.counts_max, 3102);
    CHECK_EQ_LONG(st.counts_last, 3102);
    CHECK(st.kind == WOSP_LAW_HYSTERETIC);
    CHECK(strcmp(st.pin, "GPIO18") == 0);
    CHECK(strcmp(st.sense_net, "vout") == 0);
    wosp_law_destroy(&law);
}

static void test_describe_names_the_law(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    char buf[WOSP_ERRMSG_MAX];
    wosp_law_input in;
    wosp_law law;

    /* A spec with a pin and a sense net - describe() needs both, which is
     * precisely why describe_law() exists for the case where it has neither.
     * Materialised into `in` because a function call is not an lvalue and so
     * cannot have its address taken. */
    in = base_hysteretic();
    REQUIRE_OK(wosp_law_create(&in, &law, err, sizeof err));
    wosp_law_describe(&law, buf, sizeof buf);
    CHECK_STR_CONTAINS(buf, "hysteretic");
    CHECK_STR_CONTAINS(buf, "vout");
    wosp_law_destroy(&law);
}

static void test_regulation_error_skips_startup(void)
{
    /* Ignores the first fifth of the samples: an inductor charging from zero
     * is start-up, not regulation error.  n=5 skips exactly one sample. */
    char err[WOSP_ERRMSG_MAX] = {0};
    long samples[] = {0, 12, 8, 12, 8};
    wosp_regulation_error re;

    REQUIRE_OK(wosp_law_regulation_error(samples, 5, 10, 3.3, 12, &re,
                                     err, sizeof err));
    CHECK(re.has == true);
    CHECK_NEAR(re.mean_error_counts, 0.0, 1e-12);   /* mean of +2,-2,+2,-2 */
    CHECK_NEAR(re.max_error_counts, 2.0, 1e-12);
    CHECK_NEAR(re.final_error_counts, -2.0, 1e-12); /* tail[-1] = 8 */
    CHECK_NEAR(re.mean_error_v, 0.0, 1e-12);
}

static void test_regulation_error_empty_and_single_sample(void)
{
    char err[WOSP_ERRMSG_MAX] = {0};
    wosp_regulation_error re;
    long one[] = {1995};

    REQUIRE_OK(wosp_law_regulation_error(NULL, 0, 10, 3.3, 12, &re,
                                     err, sizeof err));
    CHECK(re.has == false);      /* Python returns all-None */

    /* Python raises ZeroDivisionError for a single sample; C refuses by
     * status.  Both are failures - neither invents a number. */
    REQUIRE_FAIL(wosp_law_regulation_error(one, 1, 10, 3.3, 12, &re,
                                       err, sizeof err));
}

/* ---------------------------------------------------------------------- */

int main(void)
{
    /* tests/test_control_law_unit.py */
    RUN(test_normalize_fills_defaults);
    RUN(test_rejects_unknown_kind);
    RUN(test_accepts_pwm_kind);
    RUN(test_rejects_zero_divider);
    RUN(test_rejects_negative_adc_bits);

    RUN(test_every_transition_around_1995_and_2030);
    RUN(test_below_low_drives_high);
    RUN(test_above_high_drives_low);
    RUN(test_exact_at_high_holds_when_low);
    RUN(test_inside_band_holds_previous_state);

    RUN(test_pin_referenced_net_needs_no_divider);
    RUN(test_undivided_node_regulates_to_half);
    RUN(test_reapplying_divider_twice_halves_the_target);

    RUN(test_firmware_still_oversamples);
    RUN(test_firmware_still_calibrates);
    RUN(test_firmware_still_says_counts_are_raw);

    RUN(test_to_counts_applies_the_sense_divider);
    RUN(test_equal_threshold_counts_are_rejected);

    /* tests/test_adc_conversion.py */
    RUN(test_negative_maps_to_zero);
    RUN(test_exact_half_lsb_rounds_down);
    RUN(test_exact_full_scale_clips_to_max);
    RUN(test_just_below_full_scale);
    RUN(test_above_vref_clips);
    RUN(test_clamp_behaviour_without_float);

    /* tests/test_adc_conversion.py::TestLawCountsAtThresholds.  Each Python
     * test keeps its own name; see the note above the block. */
    RUN(test_decide_below_low_drives_high);
    RUN(test_decide_at_low_drives_high_hold);
    RUN(test_decide_inside_band_holds);
    RUN(test_decide_at_high_drives_low_hold);
    RUN(test_decide_above_high_drives_low);
    RUN(test_update_counts_switches_only_on_change);

    /* tests/test_cosim_control.py (control-law classes only) */
    RUN(test_hysteretic_counts_come_from_target_and_hysteresis);
    RUN(test_explicit_counts_are_preserved_verbatim);
    RUN(test_rejects_nonsense);
    RUN(test_describe_never_raises_on_junk);

    RUN(test_below_band_drives_high);
    RUN(test_above_band_drives_low);
    RUN(test_inside_band_holds_previous_state_cosim);
    RUN(test_update_counts_switches_only_on_a_level_change);

    RUN(test_reads_thresholds_and_gate_pin_from_real_source);
    RUN(test_imported_spec_keeps_the_file_counts);
    RUN(test_missing_file_and_missing_constants_are_reported);
    RUN(test_inverted_thresholds_are_rejected);

    RUN(test_thresholds_are_counts_at_the_pin);
    RUN(test_pin_voltages_invert_the_firmware_mapping);
    RUN(test_midpoint_matches_the_firmware_comment);
    RUN(test_picking_the_undivided_node_halves_the_target);
    RUN(test_bad_pin_divider_is_rejected);
    RUN(test_undivided_sense_net_with_a_divider_reproduces_the_counts);
    RUN(test_the_two_sense_nets_agree_exactly);

    /*
     * tests/test_cosim_control.py::TestFidelityGap has four tests.  Three of
     * them assert the same three substrings as the unit file's fidelity trio
     * already run above (ADC_OVERSAMPLE_N, adc_cali, "RAW counts") against the
     * same main.c, so they are one coverage each, not two; C cannot give two
     * functions one name anyway.  The fourth is run here.
     */
    RUN(test_oversample_count_is_not_silently_ignored);

    RUN(test_duty_grows_as_feedback_falls);
    RUN(test_duty_saturates_rather_than_exceeding_one);

    /* C-only additions, not ports - see the block comment above them. */
    RUN(test_stats_reports_a_run);
    RUN(test_describe_names_the_law);
    RUN(test_regulation_error_skips_startup);
    RUN(test_regulation_error_empty_and_single_sample);

    return wosp_t_report();
}
