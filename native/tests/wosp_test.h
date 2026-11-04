/*
 * wosp_test.h - a minimal test harness for the native suite.
 *
 * Deliberately dependency-free: the Python suite's only third-party need is
 * pytest, and the C port must build with nothing but a C11 compiler so the
 * gate stays runnable on a bare toolchain.
 *
 * Convention: every test function declares `char err[WOSP_ERRMSG_MAX] = {0};`
 * because REQUIRE_OK/REQUIRE_FAIL print it on failure.
 */

#ifndef WOSP_TEST_H
#define WOSP_TEST_H

#include <math.h>
#include <stdio.h>
#include <string.h>

static int wosp_t_run;
static int wosp_t_failed;
static int wosp_t_checks_total;     /* across every test, for the report */
static int wosp_t_checks;           /* within the test now running */
static int wosp_t_check_fails;
static const char *wosp_t_cur;

static void wosp_t_begin(const char *name)
{
    wosp_t_cur = name;
    wosp_t_checks = 0;
    wosp_t_check_fails = 0;
}

static void wosp_t_end(void)
{
    wosp_t_run++;
    wosp_t_checks_total += wosp_t_checks;
    if (wosp_t_check_fails) {
        wosp_t_failed++;
        printf("FAIL %s (%d of %d checks failed)\n",
               wosp_t_cur, wosp_t_check_fails, wosp_t_checks);
    } else {
        printf("ok   %s\n", wosp_t_cur);
    }
}

static int wosp_t_report(void)
{
    printf("\n%d tests, %d checks, %d failed\n",
           wosp_t_run, wosp_t_checks_total, wosp_t_failed);
    if (wosp_t_failed) {
        printf("GATE: native control_law tests FAILED\n");
        return 1;
    }
    printf("GATE: all native control_law tests passed\n");
    return 0;
}

#define CHECK(cond)                                                        \
    do {                                                                   \
        wosp_t_checks++;                                                   \
        if (!(cond)) {                                                     \
            wosp_t_check_fails++;                                          \
            printf("  x %s:%d: %s\n", __FILE__, __LINE__, #cond);          \
        }                                                                  \
    } while (0)

#define CHECK_MSG(cond, ...)                                               \
    do {                                                                   \
        wosp_t_checks++;                                                   \
        if (!(cond)) {                                                     \
            wosp_t_check_fails++;                                          \
            printf("  x %s:%d: %s -- ", __FILE__, __LINE__, #cond);        \
            printf(__VA_ARGS__);                                           \
            printf("\n");                                                  \
        }                                                                  \
    } while (0)

#define CHECK_EQ_LONG(actual, expected)                                    \
    do {                                                                   \
        long a_ = (long)(actual), e_ = (long)(expected);                   \
        wosp_t_checks++;                                                   \
        if (a_ != e_) {                                                    \
            wosp_t_check_fails++;                                          \
            printf("  x %s:%d: %s == %s (got %ld, want %ld)\n",            \
                   __FILE__, __LINE__, #actual, #expected, a_, e_);        \
        }                                                                  \
    } while (0)

/* assertAlmostEqual(x, y, delta=t) */
#define CHECK_NEAR(actual, expected, tol)                                  \
    do {                                                                   \
        double a_ = (double)(actual), e_ = (double)(expected);             \
        double t_ = (double)(tol);                                         \
        wosp_t_checks++;                                                   \
        if (!(fabs(a_ - e_) <= t_)) {                                      \
            wosp_t_check_fails++;                                          \
            printf("  x %s:%d: %s ~= %s (got %.12g, want %.12g, tol %g)\n",\
                   __FILE__, __LINE__, #actual, #expected, a_, e_, t_);    \
        }                                                                  \
    } while (0)

/* assertAlmostEqual(x, y, places=3): |a-b| < 0.5 * 10^-places */
#define CHECK_PLACES(actual, expected, places)                             \
    CHECK_NEAR((actual), (expected), 0.5 / pow(10.0, (double)(places)))

#define CHECK_STR_CONTAINS(haystack, needle)                               \
    do {                                                                   \
        const char *h_ = (haystack);                                       \
        const char *n_ = (needle);                                         \
        wosp_t_checks++;                                                   \
        if (h_ == NULL || strstr(h_, n_) == NULL) {                        \
            wosp_t_check_fails++;                                          \
            printf("  x %s:%d: %s does not contain %s\n  got: %s\n",       \
                   __FILE__, __LINE__, #haystack, n_, h_ ? h_ : "(null)"); \
        }                                                                  \
    } while (0)

/* with pytest.raises(...) / self.assertRaises(...) */
#define REQUIRE_FAIL(status)                                               \
    do {                                                                   \
        wosp_t_checks++;                                                   \
        if ((status) == WOSP_OK) {                                         \
            wosp_t_check_fails++;                                          \
            printf("  x %s:%d: expected an error, got WOSP_OK\n",          \
                   __FILE__, __LINE__);                                    \
        }                                                                  \
    } while (0)

/* Needs `char err[WOSP_ERRMSG_MAX]` in scope. */
#define REQUIRE_OK(status)                                                 \
    do {                                                                   \
        wosp_t_checks++;                                                   \
        if ((status) != WOSP_OK) {                                         \
            wosp_t_check_fails++;                                          \
            printf("  x %s:%d: expected success, got %d (%s)\n",           \
                   __FILE__, __LINE__, (int)(status), err);                \
        }                                                                  \
    } while (0)

#define RUN(fn)                                                            \
    do {                                                                   \
        wosp_t_begin(#fn);                                                 \
        fn();                                                              \
        wosp_t_end();                                                      \
    } while (0)

#endif /* WOSP_TEST_H */
