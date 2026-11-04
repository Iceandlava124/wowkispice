/*
 * control_law.c - C port of bridge/control_law.py
 *
 * See control_law.h for the parity contract.  Two details are worth restating
 * here because they are where a naive port silently diverges from CPython:
 *
 *   Rounding.  Python's round() is round-half-to-EVEN; the obvious C
 *   equivalents (round(), lround()) round half AWAY from zero.  At an exact
 *   .5 the two disagree, and the ADC mapping lands on exact .5 at half an
 *   LSB.  wosp_round_half_even() reproduces Python's rule.
 *
 *   Newlines.  CPython reads the firmware source in text mode, so \r\n and a
 *   lone \r both become \n before the regex ever sees them.  Reading bytes
 *   raw would make the `^` anchor of the #define scan treat a lone-\r file
 *   differently.  wosp_read_text() applies the same translation.
 */

#include "wowkispice/control_law.h"
#include "wosp_str.h"

#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

/* ---------------------------------------------------------------------- */
/* Small helpers                                                          */
/* ---------------------------------------------------------------------- */

/* wosp_set_err() and wosp_copy_str() now live in wosp_str.c: a second module
 * (netlist.c) needs the same two, and two copies of a bounded copy drift. */

/*
 * Format a double the way Python's f"{x}" (i.e. str()/repr()) does, because
 * error messages carry interpolated floats and the parity harness compares
 * those messages as text.
 *
 * Two rules have to be reproduced or the text diverges:
 *   - repr() is the SHORTEST string that round-trips to the same double, not
 *     %g's 6 significant digits.
 *   - repr() always shows a decimal point or an exponent, so 0.0 renders as
 *     "0.0" while %g says "0".
 *   - repr() picks fixed notation for 1e-4 <= |x| < 1e16 and exponential
 *     outside that, where %g switches on the precision it happens to be using.
 *
 * The exponent is read off a %.17e rendering (which always round-trips), so
 * the branch decision cannot be skewed by the precision search that follows.
 */
static void wosp_pyfmt(double x, char *buf, size_t buflen)
{
    char probe[64];
    int p, exp10;

    if (isnan(x)) {
        wosp_copy_str(buf, buflen, "nan");
        return;
    }
    if (isinf(x)) {
        wosp_copy_str(buf, buflen, x > 0 ? "inf" : "-inf");
        return;
    }

    snprintf(probe, sizeof probe, "%.17e", x);
    {
        const char *e = strchr(probe, 'e');
        exp10 = e ? (int)strtol(e + 1, NULL, 10) : 0;
    }

    if (exp10 >= -4 && exp10 < 16) {
        char *dot;
        size_t len, dotpos;
        /*
         * %.17f always round-trips inside the fixed range (|x| < 1e16), so
         * this loop is a belt-and-braces guard rather than an expected path.
         */
        for (p = 0; p <= 17; p++) {
            snprintf(buf, buflen, "%.*f", p, x);
            if (strtod(buf, NULL) == x) {
                break;
            }
        }
        /*
         * Shortest means dropping trailing zeros - but repr() always keeps
         * one digit after the point ("100.0", never "100"), so the strip must
         * not run past dot+2.  %.0f yields no point at all, in which case the
         * point is simply added.
         */
        len = strlen(buf);
        dot = strchr(buf, '.');
        if (dot != NULL) {
            dotpos = (size_t)(dot - buf);
            while (len > dotpos + 2 && buf[len - 1] == '0') {
                buf[--len] = '\0';
            }
        } else if (len + 2 < buflen) {
            strcat(buf, ".0");
        }
    } else {
        char *e;
        size_t mant;
        for (p = 1; p <= 17; p++) {
            snprintf(buf, buflen, "%.*e", p, x);
            if (strtod(buf, NULL) == x) {
                break;
            }
        }
        /*
         * Exponent form strips the mantissa's trailing zeros outright:
         * repr(1e-05) is '1e-05', not '1.0e-05'.
         */
        e = strchr(buf, 'e');
        if (e != NULL) {
            mant = (size_t)(e - buf);
            while (mant > 1 && buf[mant - 1] == '0') {
                buf[--mant] = '\0';
                memmove(buf + mant, e, strlen(e) + 1);
                e = buf + mant;
            }
            if (mant > 1 && buf[mant - 1] == '.') {
                buf[mant - 1] = '\0';
                memmove(buf + mant - 1, e, strlen(e) + 1);
            }
        }
    }
}

/* Python str.strip(): removes leading/trailing whitespace. */
static void wosp_trim(char *s)
{
    size_t len = strlen(s);
    size_t start = 0;
    while (start < len && isspace((unsigned char)s[start])) {
        start++;
    }
    while (len > start && isspace((unsigned char)s[len - 1])) {
        len--;
    }
    memmove(s, s + start, len - start);
    s[len - start] = '\0';
}

/* Python str.lower() for the ASCII range we care about. */
static void wosp_ascii_lower(char *s)
{
    for (; *s != '\0'; s++) {
        *s = (char)tolower((unsigned char)*s);
    }
}

/* os.path.basename(): accepts both separators, as Python does on Windows. */
static const char *wosp_basename(const char *path)
{
    const char *p;
    const char *last = path;
    for (p = path; *p != '\0'; p++) {
        if (*p == '/' || *p == '\\') {
            last = p + 1;
        }
    }
    return last;
}

static int wosp_is_ws(char c)
{
    return c == ' ' || c == '\t' || c == '\n' || c == '\r'
        || c == '\f' || c == '\v';
}

static int wosp_is_ident_start(char c)
{
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_';
}

static int wosp_is_ident_cont(char c)
{
    return wosp_is_ident_start(c) || (c >= '0' && c <= '9');
}

/*
 * Python's round() on a float: half-to-even, as the repr of round(0.5) is 0
 * and round(1.5) is 2.  Returns 0 for NaN (Python raises instead; no caller
 * feeds NaN, and swallowing it here keeps the clamp arithmetic well-defined).
 */
static long wosp_round_half_even(double x)
{
    double f, frac;
    long base;

    if (isnan(x)) {
        return 0;
    }
    if (isinf(x)) {
        return x > 0 ? LONG_MAX : LONG_MIN;
    }
    f = floor(x);
    frac = x - f;
    base = (long)f;
    if (frac > 0.5) {
        return base + 1;
    }
    if (frac < 0.5) {
        return base;
    }
    return (base % 2 == 0) ? base : base + 1;
}

/*
 * Python's round(x, 4), used to report the recovered target/hysteresis.
 * CPython rounds the true decimal value of the double, not (x*1e4) rounded
 * and divided back; the two differ only on an exact tie at the 5th decimal,
 * which the recovered thresholds never reach.  Noted rather than modelled.
 */
static double wosp_round4(double x)
{
    return wosp_round_half_even(x * 10000.0) / 10000.0;
}

/* ---------------------------------------------------------------------- */
/* ADC front end                                                          */
/* ---------------------------------------------------------------------- */

long wosp_to_counts_raw(double volts, double vref, int bits)
{
    long full = (1L << bits) - 1L;
    /* Same operation order as Python: volts / vref * full. */
    long r = wosp_round_half_even(volts / vref * (double)full);
    if (r < 0) {
        r = 0;
    }
    if (r > full) {
        r = full;
    }
    return r;
}

long wosp_to_counts(const wosp_law *law, double sense_v)
{
    if (law == NULL) {
        return 0;
    }
    /* Python: feedback = sense_v * self.divider, then _to_counts(...). */
    return wosp_to_counts_raw(sense_v * law->divider,
                              law->vref, law->adc_bits);
}

/* ---------------------------------------------------------------------- */
/* Spec normalisation                                                     */
/* ---------------------------------------------------------------------- */

wosp_status wosp_normalize_law(const wosp_law_input *in,
                               wosp_law_spec *out,
                               char *err, size_t errlen)
{
    wosp_law_input empty;
    wosp_law_spec s;
    char kind[32];
    double vhigh, vref, divider, target_v;
    int adc_bits;

    if (out == NULL) {
        wosp_set_err(err, errlen, "normalize_law: null output spec");
        return WOSP_ERR_INVALID_ARG;
    }
    if (in == NULL) {
        /* dict(spec or {}) - None and {} normalise alike. */
        memset(&empty, 0, sizeof empty);
        in = &empty;
    }

    memset(&s, 0, sizeof s);

    /* kind: str(spec.get("kind", "hysteretic")).lower() */
    if (in->has_kind) {
        wosp_copy_str(kind, sizeof kind, in->kind);
    } else {
        wosp_copy_str(kind, sizeof kind, "hysteretic");
    }
    wosp_ascii_lower(kind);
    if (strcmp(kind, "hysteretic") != 0 && strcmp(kind, "pwm") != 0) {
        wosp_set_err(err, errlen,
                     "unsupported law kind '%s' (use hysteretic or pwm)", kind);
        return WOSP_ERR_KIND;
    }
    s.kind = (strcmp(kind, "pwm") == 0) ? WOSP_LAW_PWM : WOSP_LAW_HYSTERETIC;

    /* pin: str(spec.get("pin", "")).strip() */
    if (in->has_pin) {
        wosp_copy_str(s.pin, sizeof s.pin, in->pin);
        wosp_trim(s.pin);
    }
    if (s.pin[0] == '\0') {
        wosp_set_err(err, errlen, "law needs a 'pin' naming the MCU output pin");
        return WOSP_ERR_PIN;
    }

    /* sense_net: str(spec.get("sense_net", "")).strip() */
    if (in->has_sense_net) {
        wosp_copy_str(s.sense_net, sizeof s.sense_net, in->sense_net);
        wosp_trim(s.sense_net);
    }
    if (s.sense_net[0] == '\0') {
        wosp_set_err(err, errlen,
                     "law for %s needs a 'sense_net' - the analog net the "
                     "firmware reads back (e.g. 'vout')", s.pin);
        return WOSP_ERR_SENSE_NET;
    }

    /* `not 0 < vhigh <= 24` - note NaN fails this, as in Python. */
    vhigh = in->has_vhigh ? in->vhigh : WOSP_DEFAULT_VHIGH;
    if (!(vhigh > 0.0 && vhigh <= 24.0)) {
        char f[64];
        wosp_pyfmt(vhigh, f, sizeof f);
        wosp_set_err(err, errlen, "vhigh must be 0..24 V, got %s", f);
        return WOSP_ERR_VHIGH;
    }
    vref = in->has_vref ? in->vref : WOSP_DEFAULT_VREF;
    if (!(vref > 0.0 && vref <= 24.0)) {
        char f[64];
        wosp_pyfmt(vref, f, sizeof f);
        wosp_set_err(err, errlen, "vref must be 0..24 V, got %s", f);
        return WOSP_ERR_VREF;
    }

    adc_bits = in->has_adc_bits ? in->adc_bits : WOSP_DEFAULT_ADC_BITS;
    if (!(adc_bits >= 8 && adc_bits <= 24)) {
        wosp_set_err(err, errlen, "adc_bits must be 8..24, got %d", adc_bits);
        return WOSP_ERR_ADC_BITS;
    }

    divider = in->has_divider ? in->divider : 1.0;
    if (!(divider > 0.0 && divider <= 1.0)) {
        char f[64];
        wosp_pyfmt(divider, f, sizeof f);
        wosp_set_err(err, errlen, "divider must be in (0, 1], got %s", f);
        return WOSP_ERR_DIVIDER;
    }

    /* `if target_v <= 0` - unlike the checks above, NaN slips past in Python. */
    target_v = in->has_target_v ? in->target_v : 3.3;
    if (target_v <= 0.0) {
        char f[64];
        wosp_pyfmt(target_v, f, sizeof f);
        wosp_set_err(err, errlen, "target_v must be > 0, got %s", f);
        return WOSP_ERR_TARGET;
    }

    s.target_v = target_v;
    s.vhigh = vhigh;
    s.vref = vref;
    s.adc_bits = adc_bits;
    s.divider = divider;

    if (s.kind == WOSP_LAW_HYSTERETIC) {
        double hyst = in->has_hysteresis_v ? in->hysteresis_v : 0.04;
        if (hyst <= 0.0) {
            char f[64];
            wosp_pyfmt(hyst, f, sizeof f);
            wosp_set_err(err, errlen, "hysteresis_v must be > 0, got %s", f);
            return WOSP_ERR_HYSTERESIS;
        }
        if (hyst >= target_v) {
            char f1[64], f2[64];
            wosp_pyfmt(hyst, f1, sizeof f1);
            wosp_pyfmt(target_v, f2, sizeof f2);
            wosp_set_err(err, errlen,
                         "hysteresis_v (%s) must be smaller than target_v (%s)",
                         f1, f2);
            return WOSP_ERR_HYSTERESIS;
        }
        s.hysteresis_v = hyst;

        /*
         * Explicit counts win - that is how a spec imported from firmware
         * source keeps the file's exact decision boundary.  If EITHER is
         * missing both are recomputed, exactly as Python's
         * `if low is None or high is None`.
         */
        if (in->has_low_counts && in->has_high_counts) {
            s.low_counts = in->low_counts;
            s.high_counts = in->high_counts;
        } else {
            s.low_counts = wosp_to_counts_raw((target_v - hyst) * divider,
                                              vref, adc_bits);
            s.high_counts = wosp_to_counts_raw((target_v + hyst) * divider,
                                               vref, adc_bits);
        }
        if (s.low_counts >= s.high_counts) {
            wosp_set_err(err, errlen,
                         "threshold counts must increase, got low=%ld high=%ld",
                         s.low_counts, s.high_counts);
            return WOSP_ERR_THRESHOLDS;
        }
    } else {
        double freq = in->has_carrier_hz ? in->carrier_hz : 20000.0;
        double gain = in->has_duty_gain ? in->duty_gain : 0.25;
        if (freq <= 0.0) {
            char f[64];
            wosp_pyfmt(freq, f, sizeof f);
            wosp_set_err(err, errlen, "carrier_hz must be > 0, got %s", f);
            return WOSP_ERR_CARRIER;
        }
        if (gain <= 0.0) {
            char f[64];
            wosp_pyfmt(gain, f, sizeof f);
            wosp_set_err(err, errlen, "duty_gain must be > 0, got %s", f);
            return WOSP_ERR_DUTY_GAIN;
        }
        s.carrier_hz = freq;
        s.duty_gain = gain;
    }

    /* source is echoed verbatim; source_counts is dropped, as in Python. */
    if (in->has_source) {
        s.has_source = true;
        wosp_copy_str(s.source, sizeof s.source, in->source);
    }

    *out = s;
    return WOSP_OK;
}

void wosp_describe_law(const wosp_law_input *in, char *buf, size_t buflen)
{
    wosp_law law;
    char err[WOSP_ERRMSG_MAX];

    if (buf == NULL || buflen == 0) {
        return;
    }
    err[0] = '\0';
    if (wosp_law_create(in, &law, err, sizeof err) != WOSP_OK) {
        snprintf(buf, buflen, "<invalid control law: %s>", err);
        return;
    }
    wosp_law_describe(&law, buf, buflen);
    wosp_law_destroy(&law);
}

/* ---------------------------------------------------------------------- */
/* The executable law                                                     */
/* ---------------------------------------------------------------------- */

static wosp_status wosp_hist_push(wosp_law *law, double t, long counts)
{
    if (law->n_hist == law->cap_hist) {
        size_t cap = (law->cap_hist == 0) ? 256 : law->cap_hist * 2;
        double *nt, *np;
        long *nc;
        if (cap < law->cap_hist) {
            return WOSP_ERR_NOMEM; /* overflow */
        }
        nt = (double *)realloc(law->hist_time, cap * sizeof *nt);
        if (nt == NULL) {
            return WOSP_ERR_NOMEM;
        }
        law->hist_time = nt;
        np = (double *)realloc(law->hist_pin, cap * sizeof *np);
        if (np == NULL) {
            return WOSP_ERR_NOMEM;
        }
        law->hist_pin = np;
        nc = (long *)realloc(law->hist_counts, cap * sizeof *nc);
        if (nc == NULL) {
            return WOSP_ERR_NOMEM;
        }
        law->hist_counts = nc;
        law->cap_hist = cap;
    }
    law->hist_time[law->n_hist] = t;
    law->hist_pin[law->n_hist] = law->level ? law->vhigh : 0.0;
    law->hist_counts[law->n_hist] = counts;
    law->n_hist++;
    return WOSP_OK;
}

wosp_status wosp_law_create(const wosp_law_input *in, wosp_law *law,
                            char *err, size_t errlen)
{
    wosp_status st;

    if (law == NULL) {
        wosp_set_err(err, errlen, "law_create: null law");
        return WOSP_ERR_INVALID_ARG;
    }
    memset(law, 0, sizeof *law);

    st = wosp_normalize_law(in, &law->spec, err, errlen);
    if (st != WOSP_OK) {
        return st;
    }

    wosp_copy_str(law->pin, sizeof law->pin, law->spec.pin);
    wosp_copy_str(law->sense_net, sizeof law->sense_net, law->spec.sense_net);
    law->vhigh = law->spec.vhigh;
    law->divider = law->spec.divider;
    law->vref = law->spec.vref;
    law->adc_bits = law->spec.adc_bits;
    law->level = false;
    law->switch_count = 0;

    if (law->spec.kind == WOSP_LAW_HYSTERETIC) {
        law->low_counts = law->spec.low_counts;
        law->high_counts = law->spec.high_counts;
    } else {
        law->carrier_hz = law->spec.carrier_hz;
        law->duty_gain = law->spec.duty_gain;
        law->target_counts = wosp_to_counts_raw(law->spec.target_v * law->divider,
                                                law->vref, law->adc_bits);
        law->duty = 0.0;
    }
    return WOSP_OK;
}

void wosp_law_destroy(wosp_law *law)
{
    if (law == NULL) {
        return;
    }
    free(law->hist_time);
    free(law->hist_pin);
    free(law->hist_counts);
    law->hist_time = NULL;
    law->hist_pin = NULL;
    law->hist_counts = NULL;
    law->n_hist = 0;
    law->cap_hist = 0;
}

bool wosp_law_decide(wosp_law *law, long counts)
{
    if (law == NULL) {
        return false;
    }

    if (law->spec.kind == WOSP_LAW_HYSTERETIC) {
        /*
         * The firmware's own branch order: counts < low -> drive HIGH,
         * counts > high -> drive LOW, otherwise hold.  Thresholds are
         * inclusive: a sample sitting exactly on low_counts or high_counts
         * holds, which is what stops the regulator chattering on the boundary.
         */
        if (counts < law->low_counts) {
            return true;
        }
        if (counts > law->high_counts) {
            return false;
        }
        return law->level;
    }

    /* pwm */
    {
        double denom = ((double)law->target_counts > 1.0)
                     ? (double)law->target_counts : 1.0;
        double error = ((double)law->target_counts - (double)counts) / denom;
        double duty = error * law->duty_gain;
        double period, t, phase;

        if (duty < 0.0) {
            duty = 0.0;
        }
        if (duty > 1.0) {
            duty = 1.0;
        }
        law->duty = duty;

        period = 1.0 / law->carrier_hz;
        /* update() appends AFTER decide(), so this is the previous time. */
        t = (law->n_hist > 0) ? law->hist_time[law->n_hist - 1] : 0.0;
        /* Python's % on floats always yields [0, period). */
        phase = fmod(t, period);
        if (phase < 0.0) {
            phase += period;
        }
        return phase < law->duty * period;
    }
}

double wosp_law_update(wosp_law *law, double sense_v, double time_s)
{
    long counts;
    bool previous;

    if (law == NULL) {
        return NAN;
    }
    counts = wosp_to_counts(law, sense_v);
    previous = law->level;
    law->level = wosp_law_decide(law, counts);
    if (law->level != previous) {
        law->switch_count++;
    }
    if (wosp_hist_push(law, time_s, counts) != WOSP_OK) {
        law->oom = true;
        return NAN;
    }
    return law->level ? law->vhigh : 0.0;
}

void wosp_law_describe(const wosp_law *law, char *buf, size_t buflen)
{
    if (law == NULL || buf == NULL || buflen == 0) {
        return;
    }
    if (law->spec.kind == WOSP_LAW_HYSTERETIC) {
        snprintf(buf, buflen,
                 "hysteretic on %s: HIGH below %ld counts, LOW above %ld "
                 "counts, hold in between (target %g V via %gx divider)",
                 law->sense_net, law->low_counts, law->high_counts,
                 law->spec.target_v, law->divider);
    } else {
        snprintf(buf, buflen,
                 "PWM on %s: %g Hz carrier, duty = min(1, gain %g x error "
                 "toward %g V)",
                 law->sense_net, law->carrier_hz, law->duty_gain,
                 law->spec.target_v);
    }
}

wosp_status wosp_law_get_stats(const wosp_law *law, wosp_law_stats *out)
{
    size_t i, n;
    double midpoint, high = 0.0;

    if (law == NULL || out == NULL) {
        return WOSP_ERR_INVALID_ARG;
    }
    memset(out, 0, sizeof *out);
    out->kind = law->spec.kind;
    wosp_copy_str(out->pin, sizeof out->pin, law->pin);
    wosp_copy_str(out->sense_net, sizeof out->sense_net, law->sense_net);

    n = law->n_hist;
    out->samples = (long)n;
    out->switches = law->switch_count;

    midpoint = law->vhigh / 2.0;
    for (i = 0; i < n; i++) {
        if (law->hist_pin[i] > midpoint) {
            high += 1.0;
        }
    }
    out->duty = (n > 0) ? high / (double)n : 0.0;

    if (n > 0) {
        out->has_counts = true;
        out->counts_min = law->hist_counts[0];
        out->counts_max = law->hist_counts[0];
        for (i = 1; i < n; i++) {
            if (law->hist_counts[i] < out->counts_min) {
                out->counts_min = law->hist_counts[i];
            }
            if (law->hist_counts[i] > out->counts_max) {
                out->counts_max = law->hist_counts[i];
            }
        }
        out->counts_last = law->hist_counts[n - 1];
    }
    out->final_level_high = law->level;
    return WOSP_OK;
}

/* ---------------------------------------------------------------------- */
/* Firmware import                                                        */
/* ---------------------------------------------------------------------- */

/*
 * Read a file as CPython's text mode would: bytes in, then universal
 * newline translation (\r\n -> \n, then a lone \r -> \n).  Invalid UTF-8 is
 * left alone rather than replaced with U+FFFD; replacement can only ever
 * rewrite non-ASCII bytes, and the #define scan matches ASCII exclusively, so
 * the two are indistinguishable here.
 */
static char *wosp_read_text(const char *path, size_t *out_len,
                            char *err, size_t errlen)
{
    struct stat st;
    FILE *f;
    char *raw = NULL, *text = NULL;
    size_t cap, len = 0, i, o;

    if (stat(path, &st) != 0) {
        wosp_set_err(err, errlen, "firmware source not found: %s", path);
        return NULL;
    }
    f = fopen(path, "rb");
    if (f == NULL) {
        wosp_set_err(err, errlen, "cannot read firmware source %s: %s",
                     path, strerror(errno));
        return NULL;
    }
    cap = (size_t)(st.st_size > 0 ? st.st_size + 1 : 4096);
    raw = (char *)malloc(cap);
    if (raw == NULL) {
        fclose(f);
        wosp_set_err(err, errlen, "cannot read firmware source %s: out of memory",
                     path);
        return NULL;
    }
    len = fread(raw, 1, cap - 1, f);
    fclose(f);
    raw[len] = '\0';

    /* In-place universal-newline translation; output never grows. */
    text = raw;
    for (i = 0, o = 0; i < len; i++) {
        if (raw[i] == '\r') {
            if (i + 1 < len && raw[i + 1] == '\n') {
                i++;
            }
            text[o++] = '\n';
        } else {
            text[o++] = raw[i];
        }
    }
    text[o] = '\0';
    *out_len = o;
    return text;
}

typedef struct {
    char name[128];
    char value[512];
} wosp_define;

/*
 * The regex `^\s*#define\s+(name)\s+(value)` with MULTILINE.
 *
 * `^` anchors at a line start and `\s*` may cross blank lines, so "#define"
 * is only a match when every character back to a line start is whitespace.
 * The value stops at CR, LF or '/' (to cut a // comment) and must be at
 * least one character.  Matches are non-overlapping: scanning resumes past
 * the value, so a "#define" that lives *inside* a value is never rescanned.
 */
static int wosp_next_define(const char *text, size_t len, size_t *pos,
                            wosp_define *d)
{
    size_t i;

    for (i = *pos; i + 7 <= len; i++) {
        size_t j, ws_start, ns, vs, name_len, val_len;
        int ok_line;

        if (memcmp(text + i, "#define", 7) != 0) {
            continue;
        }

        /* Walk back through whitespace; a line start must be reached. */
        ok_line = 0;
        if (i == 0) {
            ok_line = 1;
        } else {
            size_t k = i;
            while (k > 0 && wosp_is_ws(text[k - 1])) {
                if (text[k - 1] == '\n') {
                    ok_line = 1;
                    break;
                }
                k--;
            }
            if (k == 0) {
                ok_line = 1;
            }
        }
        if (!ok_line) {
            continue;
        }

        j = i + 7;
        ws_start = j;
        while (j < len && wosp_is_ws(text[j])) {
            j++;
        }
        if (j == ws_start) {                 /* \s+ needs at least one */
            continue;
        }
        if (j >= len || !wosp_is_ident_start(text[j])) {
            continue;
        }
        ns = j;
        while (j < len && wosp_is_ident_cont(text[j])) {
            j++;
        }
        name_len = j - ns;

        ws_start = j;
        while (j < len && wosp_is_ws(text[j])) {
            j++;
        }
        if (j == ws_start) {                 /* \s+ needs at least one */
            continue;
        }

        vs = j;
        while (j < len && text[j] != '\r' && text[j] != '\n' && text[j] != '/') {
            j++;
        }
        if (j == vs) {                       /* [^\r\n/]+ needs at least one */
            continue;
        }
        val_len = j - vs;

        if (name_len >= sizeof d->name || val_len >= sizeof d->value) {
            *pos = j;
            continue;
        }
        memcpy(d->name, text + ns, name_len);
        d->name[name_len] = '\0';
        memcpy(d->value, text + vs, val_len);
        d->value[val_len] = '\0';
        *pos = j;
        return 1;
    }
    *pos = len;
    return 0;
}

/*
 * Python's `re.search(r"(\d+)\s*$", text)`: the digit run immediately before
 * any trailing whitespace, which is also the leftmost such run because
 * anything between it and the end would have to be whitespace.  Python's \d
 * also matches non-ASCII digits; firmware sources are ASCII, and int() would
 * reject the CJK range anyway once parsed, so digits are taken as ASCII.
 */
static int wosp_parse_int(const char *text, long *out)
{
    size_t len = strlen(text);
    size_t end = len;
    size_t start;
    long v = 0;
    size_t k;

    while (end > 0 && wosp_is_ws(text[end - 1])) {
        end--;
    }
    if (end == 0 || text[end - 1] < '0' || text[end - 1] > '9') {
        return 0;
    }
    start = end;
    while (start > 0 && text[start - 1] >= '0' && text[start - 1] <= '9') {
        start--;
    }
    if (end - start > 18) {
        return 0;   /* beyond int64; no firmware constant is this large */
    }
    for (k = start; k < end; k++) {
        v = v * 10 + (text[k] - '0');
    }
    *out = v;
    return 1;
}

typedef enum {
    SLOT_NONE = 0,
    SLOT_LOW,
    SLOT_HIGH,
    SLOT_PIN
} wosp_slot;

/* The _ALIASES table. */
static wosp_slot wosp_alias_for(const char *name)
{
    if (strcmp(name, "ADC_LOW_THRESHOLD") == 0) {
        return SLOT_LOW;
    }
    if (strcmp(name, "ADC_HIGH_THRESHOLD") == 0) {
        return SLOT_HIGH;
    }
    if (strcmp(name, "GATE_PIN") == 0) {
        return SLOT_PIN;
    }
    return SLOT_NONE;
}

wosp_status wosp_read_firmware_constants(const char *path,
                                         wosp_firmware_constants *out,
                                         char *err, size_t errlen)
{
    char *text;
    size_t len = 0, pos = 0;
    wosp_define d;
    int has_low = 0, has_high = 0, has_pin = 0;
    long low = 0, high = 0, pin_num = 0;
    wosp_status rc = WOSP_OK;

    if (path == NULL || out == NULL) {
        wosp_set_err(err, errlen, "read_firmware_constants: null argument");
        return WOSP_ERR_INVALID_ARG;
    }

    text = wosp_read_text(path, &len, err, errlen);
    if (text == NULL) {
        return WOSP_ERR_FILE;
    }

    while (wosp_next_define(text, len, &pos, &d)) {
        long v;
        wosp_slot slot = wosp_alias_for(d.name);
        if (slot == SLOT_NONE) {
            continue;
        }
        /* A define whose value has no trailing digits is skipped, not
         * treated as zero - Python does `continue` on _parse_int() None. */
        if (!wosp_parse_int(d.value, &v)) {
            continue;
        }
        if (slot == SLOT_LOW) {
            low = v;
            has_low = 1;                     /* last definition wins */
        } else if (slot == SLOT_HIGH) {
            high = v;
            has_high = 1;
        } else {
            pin_num = v;
            has_pin = 1;
        }
    }
    free(text);

    if (!has_low || !has_high || !has_pin) {
        char missing[64] = "";
        size_t m = 0;
        const char *need[3];
        int i;
        need[0] = has_low ? NULL : "low";
        need[1] = has_high ? NULL : "high";
        need[2] = has_pin ? NULL : "pin";
        for (i = 0; i < 3; i++) {
            if (need[i] == NULL) {
                continue;
            }
            if (m > 0) {
                m += (size_t)snprintf(missing + m, sizeof missing - m, "/");
            }
            m += (size_t)snprintf(missing + m, sizeof missing - m, "%s",
                                  need[i]);
        }
        wosp_set_err(err, errlen,
                     "%s has no %s constant; expected #define "
                     "ADC_LOW_THRESHOLD / ADC_HIGH_THRESHOLD / GATE_PIN",
                     wosp_basename(path), missing);
        return WOSP_ERR_NO_CONSTANTS;
    }

    if (low >= high) {
        wosp_set_err(err, errlen,
                     "nonsense thresholds in %s: ADC_LOW_THRESHOLD (%ld) >= "
                     "ADC_HIGH_THRESHOLD (%ld)",
                     wosp_basename(path), low, high);
        return WOSP_ERR_BAD_CONSTANTS;
    }

    out->low = low;
    out->high = high;
    snprintf(out->pin, sizeof out->pin, "GPIO%ld", pin_num);
    return rc;
}

wosp_status wosp_law_from_firmware_source(const char *path,
                                          const char *sense_net,
                                          double divider,
                                          double vhigh, double vref,
                                          int adc_bits,
                                          wosp_law_input *out,
                                          char *err, size_t errlen)
{
    wosp_firmware_constants c;
    wosp_status st;
    long full;
    double midpoint, half_band, target_v, hyst_v;

    if (out == NULL) {
        wosp_set_err(err, errlen, "law_from_firmware_source: null output");
        return WOSP_ERR_INVALID_ARG;
    }
    st = wosp_read_firmware_constants(path, &c, err, errlen);
    if (st != WOSP_OK) {
        return st;
    }

    full = (1L << adc_bits) - 1L;
    /* Same operation order as Python: (low + high) / 2.0 / full * vref. */
    midpoint = ((double)c.low + (double)c.high) / 2.0 / (double)full * vref;
    half_band = fabs((double)c.high - (double)c.low) / 2.0 / (double)full * vref;
    /* A non-unit divider means the caller pointed at an undivided net, so
     * BOTH the target and the band move to that net's scale. */
    target_v = (divider != 0.0) ? midpoint / divider : midpoint;
    hyst_v = (divider != 0.0) ? half_band / divider : half_band;

    memset(out, 0, sizeof *out);
    out->has_kind = true;
    wosp_copy_str(out->kind, sizeof out->kind, "hysteretic");
    out->has_pin = true;
    wosp_copy_str(out->pin, sizeof out->pin, c.pin);
    out->has_sense_net = true;
    wosp_copy_str(out->sense_net, sizeof out->sense_net, sense_net);
    out->has_target_v = true;
    out->target_v = wosp_round4(target_v);
    out->has_hysteresis_v = true;
    out->hysteresis_v = wosp_round4(hyst_v);
    out->has_vhigh = true;
    out->vhigh = vhigh;
    out->has_vref = true;
    out->vref = vref;
    out->has_adc_bits = true;
    out->adc_bits = adc_bits;
    out->has_divider = true;
    out->divider = divider;
    out->has_source = true;
    wosp_copy_str(out->source, sizeof out->source, wosp_basename(path));
    /* Preserve the source numbers verbatim; wosp_normalize_law() recomputes
     * low/high from target/hysteresis, and the recovered target is a rational
     * fraction that must not drift. */
    out->has_source_counts = true;
    out->source_low = c.low;
    out->source_high = c.high;
    return WOSP_OK;
}

wosp_status wosp_law_from_firmware_source_exact(const char *path,
                                                const char *sense_net,
                                                double divider,
                                                double vhigh, double vref,
                                                int adc_bits,
                                                wosp_law_input *out,
                                                char *err, size_t errlen)
{
    wosp_status st = wosp_law_from_firmware_source(path, sense_net, divider,
                                                   vhigh, vref, adc_bits,
                                                   out, err, errlen);
    if (st != WOSP_OK) {
        return st;
    }
    out->has_low_counts = true;
    out->low_counts = out->source_low;
    out->has_high_counts = true;
    out->high_counts = out->source_high;
    return WOSP_OK;
}

/* ---------------------------------------------------------------------- */
/* Divider sanity check                                                   */
/* ---------------------------------------------------------------------- */

wosp_status wosp_implied_pin_voltages(const wosp_law_input *in,
                                      double *lo, double *hi,
                                      char *err, size_t errlen)
{
    wosp_law_spec s;
    wosp_status st;
    double full;

    if (lo == NULL || hi == NULL) {
        wosp_set_err(err, errlen, "implied_pin_voltages: null output");
        return WOSP_ERR_INVALID_ARG;
    }
    st = wosp_normalize_law(in, &s, err, errlen);
    if (st != WOSP_OK) {
        return st;
    }
    if (s.kind != WOSP_LAW_HYSTERETIC) {
        /* Python raises KeyError here (a normalised pwm spec has no
         * low_counts); both implementations refuse. */
        wosp_set_err(err, errlen,
                     "spec has no low_counts/high_counts (kind '%s')",
                     s.kind == WOSP_LAW_PWM ? "pwm" : "hysteretic");
        return WOSP_ERR_THRESHOLDS;
    }
    full = (double)((1 << s.adc_bits) - 1);
    *lo = (double)s.low_counts / full * s.vref;
    *hi = (double)s.high_counts / full * s.vref;
    return WOSP_OK;
}

wosp_status wosp_implied_output_voltages(const wosp_law_input *in,
                                         double pin_divider,
                                         double *lo, double *hi,
                                         char *err, size_t errlen)
{
    wosp_status st;

    /* Python computes the pin voltages first and validates pin_divider
     * after, so an invalid spec and a bad divider report the spec error. */
    st = wosp_implied_pin_voltages(in, lo, hi, err, errlen);
    if (st != WOSP_OK) {
        return st;
    }
    if (pin_divider <= 0.0) {
        char f[64];
        wosp_pyfmt(pin_divider, f, sizeof f);
        wosp_set_err(err, errlen, "pin_divider must be > 0, got %s", f);
        return WOSP_ERR_PIN_DIVIDER;
    }
    *lo /= pin_divider;
    *hi /= pin_divider;
    return WOSP_OK;
}

/* ---------------------------------------------------------------------- */
/* Per-run performance metric                                             */
/* ---------------------------------------------------------------------- */

wosp_status wosp_law_regulation_error(const long *samples, size_t n,
                                      long target_counts, double vref,
                                      int adc_bits, wosp_regulation_error *out,
                                      char *err, size_t errlen)
{
    size_t start, tn, i;
    const long *tail;
    double sum = 0.0, mean, lsb_v;
    long maxabs = 0;

    if (out == NULL) {
        wosp_set_err(err, errlen, "regulation_error: null output");
        return WOSP_ERR_INVALID_ARG;
    }
    memset(out, 0, sizeof *out);

    if (n == 0) {
        out->has = false;               /* Python returns all-None */
        return WOSP_OK;
    }
    if (n == 1) {
        /* Python slices its only sample away and divides by zero. */
        wosp_set_err(err, errlen,
                     "regulation_error needs at least 2 samples "
                     "(Python raises ZeroDivisionError here)");
        return WOSP_ERR_INVALID_ARG;
    }

    start = n / 5;
    if (start < 1) {
        start = 1;
    }
    tail = samples + start;
    tn = n - start;

    for (i = 0; i < tn; i++) {
        long e = tail[i] - target_counts;
        long a = (e < 0) ? -e : e;
        sum += (double)e;
        if (a > maxabs) {
            maxabs = a;
        }
    }
    mean = sum / (double)tn;
    lsb_v = vref / (double)((1L << adc_bits) - 1L > 1
                            ? (1L << adc_bits) - 1L : 1L);

    out->has = true;
    out->mean_error_counts = mean;
    out->max_error_counts = (double)maxabs;
    out->mean_error_v = mean * lsb_v;
    out->final_error_counts = (double)(tail[tn - 1] - target_counts);
    return WOSP_OK;
}
