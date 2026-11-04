/*
 * netlist.c - C port of the pure logic in bridge/ngspice_wrapper.py.
 *
 * See netlist.h for the parity contract.  Four details are worth restating
 * here, because each is a place a naive port silently diverges from CPython:
 *
 *   Regexes.  ngspice_wrapper.py leans on four patterns (SPICE numbers,
 *   include arguments, dot-directives, forbidden command characters).  There
 *   is no regex engine in this dependency-free core, so each is written as a
 *   scanner.  That is not a shortcut: all four are anchored and simple
 *   enough that a scanner is easier to audit than a pattern string, and the
 *   parity battery exists to prove the two agree on the awkward cases
 *   (`.include ""`, `.include  foo` with two spaces, `5meg` vs `5m`,
 *   `timestep = 0` NOT matching the `time =` search).
 *
 *   Whitespace.  Python's str.strip()/str.split() use str.isspace(), which
 *   for ASCII is space, \t \n \r \v \f \x1c \x1d \x1e \x1f - note \x1a is
 *   NOT whitespace to Python, though it looks like one.  wosp_strip() and
 *   wosp_split() reproduce exactly that set.  \x85 and U+00A0 are also
 *   isspace() in Python but are multi-byte in UTF-8 and are outside this
 *   port's ASCII contract; see the note on wosp_strip().
 *
 *   Case folding.  Python's str.lower() is Unicode-aware (and maps one
 *   codepoint to two, for U+0130).  Every fold here is ASCII-only, which is
 *   identical for every byte a netlist or an ngspice log line contains.  The
 *   parity battery is deliberately ASCII so a divergence would be a real
 *   bug rather than an unportable character.
 *
 *   realpath.  The include tests compare the REWRITTEN LINE against
 *   os.path.realpath(), so an equivalent path is not enough - the string has
 *   to match, which means resolving the case the filesystem actually holds.
 *   wosp_realpath() does that with GetFinalPathNameByHandle() on Windows.
 */

#include "wowkispice/netlist.h"
#include "wosp_str.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifdef _WIN32
#include <direct.h>
#include <windows.h>
#define nl_getcwd _getcwd
#else
#include <limits.h>
#include <unistd.h>
#define nl_getcwd getcwd
#endif

/* Every rejection ngspice_wrapper.py prefixes its message with.  The Python
 * suite asserts on substrings inside it, so it is a literal, not a format. */
#define NL_PREFIX "ngSpice_Circ rejected the untrusted netlist: "

#define NL_PATH_MAX 4096
#define NL_LINE_MAX 8192

/* ---------------------------------------------------------------------- */
/* ASCII string primitives that mirror specific Python methods            */
/* ---------------------------------------------------------------------- */

/*
 * str.isspace() restricted to ASCII: space, \t \n \r \v \f and the four
 * C0 separators \x1c-\x1f.  Deliberately excludes \x1a, which Python also
 * reports as NOT whitespace despite it being a control character - the
 * asymmetry is real and reproducing it costs one line.
 *
 * \x85 (NEL) and U+00A0 are isspace() in Python but are two bytes in UTF-8;
 * treating either byte alone would split a character.  Netlist input and
 * ngspice log lines are ASCII, so they are out of contract rather than
 * approximated.
 */
static int nl_isws(unsigned char c)
{
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' ||
           c == '\v' || c == '\f' ||
           c == 0x1c || c == 0x1d || c == 0x1e || c == 0x1f;
}

/* ASCII str.lower(), in place.  Non-ASCII bytes pass through untouched. */
static void nl_lower(char *s)
{
    for (; *s; s++) {
        if (*s >= 'A' && *s <= 'Z') {
            *s = (char)(*s - 'A' + 'a');
        }
    }
}

/* str.strip(): drop leading and trailing ASCII whitespace. */
void wosp_strip(const char *s, char *out, size_t outlen)
{
    const char *end;

    if (outlen == 0) {
        return;
    }
    while (*s && nl_isws((unsigned char)*s)) {
        s++;
    }
    end = s + strlen(s);
    while (end > s && nl_isws((unsigned char)end[-1])) {
        end--;
    }
    {
        size_t n = (size_t)(end - s);
        if (n >= outlen) {
            n = outlen - 1;
        }
        memcpy(out, s, n);
        out[n] = '\0';
    }
}

/* str.lstrip(' \t'): ONLY spaces and tabs - not newlines. */
void wosp_lstrip_sp(const char *s, char *out, size_t outlen)
{
    size_t n;

    if (outlen == 0) {
        return;
    }
    while (*s == ' ' || *s == '\t') {
        s++;
    }
    n = strlen(s);
    if (n >= outlen) {
        n = outlen - 1;
    }
    memcpy(out, s, n);
    out[n] = '\0';
}

/*
 * Split into tokens, writing each NUL-terminated into `buf` so the pointers
 * stay valid after the source is gone.  Tokens point into `buf`, never into
 * `s`, so the caller may discard the source immediately.
 */
static size_t nl_split_copy(const char *s, char *buf, size_t buflen,
                            const char **tok, size_t cap)
{
    size_t n = 0, used = 0;

    while (*s) {
        const char *t;
        size_t len;
        while (*s && nl_isws((unsigned char)*s)) {
            s++;
        }
        if (!*s) {
            break;
        }
        t = s;
        while (*s && !nl_isws((unsigned char)*s)) {
            s++;
        }
        len = (size_t)(s - t);
        if (n >= cap || used + len + 1 > buflen) {
            break;
        }
        memcpy(buf + used, t, len);
        buf[used + len] = '\0';
        tok[n] = buf + used;
        used += len + 1;
        n++;
    }
    return n;
}

/* str.startswith("*") / str.startswith(prefix). */
static int nl_starts_with(const char *s, const char *prefix)
{
    return strncmp(s, prefix, strlen(prefix)) == 0;
}

/* `"needle" in haystack`, ASCII case-insensitive - Python's
 * `marker in line.lower()`. */
static int nl_contains_ci(const char *hay, const char *needle)
{
    size_t nl = strlen(needle);
    size_t i;

    for (i = 0; hay[i]; i++) {
        size_t j;
        for (j = 0; j < nl; j++) {
            char a = hay[i + j], b = needle[j];
            if (!a) {
                return 0;
            }
            if (a >= 'A' && a <= 'Z') {
                a = (char)(a - 'A' + 'a');
            }
            if (b >= 'A' && b <= 'Z') {
                b = (char)(b - 'A' + 'a');
            }
            if (a != b) {
                break;
            }
        }
        if (j == nl) {
            return 1;
        }
    }
    return 0;
}

/*
 * Python repr() of a str, for validate_cmd()'s two %r interpolations.
 * Single quotes unless the text contains one and no double quote, then
 * double quotes; \t \n \r \\ and the active quote are escaped, and any other
 * non-printable goes out as \xhh - which is what CPython does.
 */
static void nl_repr(const char *s, char *out, size_t outlen)
{
    char quote = '\'';
    size_t o = 0;
    size_t i;

    if (outlen == 0) {
        return;
    }
    if (strchr(s, '\'') != NULL && strchr(s, '"') == NULL) {
        quote = '"';
    }
    if (o + 1 < outlen) {
        out[o++] = quote;
    }
    for (i = 0; s[i] && o + 6 < outlen; i++) {
        unsigned char c = (unsigned char)s[i];
        const char *esc = NULL;
        char hex[8];

        if (c == '\\') {
            esc = "\\\\";
        } else if ((char)c == quote) {
            esc = (quote == '\'') ? "\\'" : "\\\"";
        } else if (c == '\n') {
            esc = "\\n";
        } else if (c == '\r') {
            esc = "\\r";
        } else if (c == '\t') {
            esc = "\\t";
        } else if (c < 0x20 || c == 0x7f) {
            snprintf(hex, sizeof hex, "\\x%02x", c);
            esc = hex;
        }

        if (esc != NULL) {
            size_t el = strlen(esc);
            if (o + el + 2 > outlen) {
                break;
            }
            memcpy(out + o, esc, el);
            o += el;
        } else {
            out[o++] = (char)c;
        }
    }
    if (o + 1 < outlen) {
        out[o++] = quote;
    }
    out[o] = '\0';
}

/* ---------------------------------------------------------------------- */
/* Allowlists - transcribed from NgSpiceEngine's class attributes         */
/* ---------------------------------------------------------------------- */

/* ALLOWED_DIRECTIVES.  Order is irrelevant; membership is. */
static const char *NL_ALLOWED_DIRECTIVES[] = {
    "tran", "ac", "dc", "op", "ic", "nodeset",
    "step", "options", "param", "model", "subckt",
    "ends", "measure", "meas", "print", "save", "temp", "end",
    "noise", "disto",
    "include", "lib", "inc",
};
#define NL_N_DIRECTIVES \
    (sizeof NL_ALLOWED_DIRECTIVES / sizeof NL_ALLOWED_DIRECTIVES[0])

/* Cmd_ALLOWED - the verbs the legitimate code actually sends. */
static const char *NL_ALLOWED_CMDS[] = {
    "run", "bg_run", "reset", "destroy",
    "alter", "stop", "setplot", "tran",
};
#define NL_N_CMDS (sizeof NL_ALLOWED_CMDS / sizeof NL_ALLOWED_CMDS[0])

/* Characters that let one string carry a second command or a redirection.
 * `cmd("shell echo PWNED> <marker>")` is exactly this shape. */
static const char NL_CMD_FORBIDDEN[] = "\r\n;|&`$<>";

/* FAILURE_MARKERS.  Case is folded at compare time, as Python folds it by
 * lowering the whole line first. */
static const char *NL_FAILURE_MARKERS[] = {
    "error on line",
    "circuit not parsed",
    "run simulation(s) aborted",
    "timestep too small",
    "could not be simulated successfully",
    "dc solution failed",
};
#define NL_N_MARKERS \
    (sizeof NL_FAILURE_MARKERS / sizeof NL_FAILURE_MARKERS[0])

static const char *NL_INCLUDE_FAMILY[] = { "include", "lib", "inc" };

static int nl_in_list(const char *needle, const char *const *list, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) {
        if (strcmp(needle, list[i]) == 0) {
            return 1;
        }
    }
    return 0;
}

/* ---------------------------------------------------------------------- */
/* SPICE numbers: _spice_seconds() and _find_tstop()                      */
/* ---------------------------------------------------------------------- */

/*
 * SPICE_SCALE.  'meg' is the only spelling that means mega, and the pattern
 * tries it before the single-letter class - so '5meg' is 5e6 and '5m' is
 * 5e-3.  Getting that order backwards is the classic SPICE parsing bug.
 */
typedef struct {
    const char *suffix;
    double scale;
} nl_scale;

static const nl_scale NL_SCALES[] = {
    { "meg", 1e6 },
    { "t",   1e12 },
    { "g",   1e9 },
    { "k",   1e3 },
    { "m",   1e-3 },
    { "u",   1e-6 },
    { "n",   1e-9 },
    { "p",   1e-12 },
    { "f",   1e-15 },
};

/*
 * SPICE_NUMBER_RE, scanned rather than matched:
 *
 *     ^([+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)(meg|[tgkmunpf])?$
 *
 * The number and the exponent are greedy in a way a hand-written scanner can
 * get wrong at `1.5e` (no digits after e -> the exponent must be given back
 * and then the whole match fails, because 'e' is not a scale suffix).
 */
static int nl_spice_number(const char *tok, double *mant, int *has_suffix,
                           char *suffix, size_t suffixlen)
{
    const char *p = tok;
    const char *num_start = p;
    int saw_digit = 0;

    if (*p == '+' || *p == '-') {
        p++;
    }
    while (*p >= '0' && *p <= '9') {
        p++;
        saw_digit = 1;
    }
    if (*p == '.') {
        p++;
        while (*p >= '0' && *p <= '9') {
            p++;
            saw_digit = 1;
        }
    }
    if (!saw_digit) {
        return 0;
    }

    /*
     * Optional exponent - only when it is a COMPLETE one.  `1.5e` must fail
     * outright rather than fall back to reading 'e' as a scale suffix: the
     * regex's exponent group is optional, so a partial one is given back,
     * and 'e' is not in [tgkmunpf], so nothing else can match either.
     */
    if (*p == 'e' || *p == 'E') {
        const char *q = p + 1;
        int exp_digit = 0;
        if (*q == '+' || *q == '-') {
            q++;
        }
        while (*q >= '0' && *q <= '9') {
            q++;
            exp_digit = 1;
        }
        if (exp_digit) {
            p = q;
        }
    }
    {
        char numbuf[64];
        size_t n = (size_t)(p - num_start);
        if (n >= sizeof numbuf) {
            return 0;
        }
        memcpy(numbuf, num_start, n);
        numbuf[n] = '\0';
        *mant = strtod(numbuf, NULL);
    }

    /* Optional scale suffix, whole-string.  'meg' is tried before the
     * single-letter class, exactly as the regex alternation is ordered. */
    if (*p == '\0') {
        *has_suffix = 0;
        suffix[0] = '\0';
        return 1;
    }
    if ((p[0] == 'm' || p[0] == 'M') &&
        (p[1] == 'e' || p[1] == 'E') && (p[2] == 'g' || p[2] == 'G') &&
        p[3] == '\0') {
        wosp_copy_str(suffix, suffixlen, "meg");
        *has_suffix = 1;
        return 1;
    }
    if (strchr("tgkmunpfTGKMUNPF", p[0]) != NULL && p[1] == '\0') {
        suffix[0] = (char)((p[0] >= 'A' && p[0] <= 'Z')
                           ? p[0] - 'A' + 'a' : p[0]);
        suffix[1] = '\0';
        *has_suffix = 1;
        return 1;
    }
    return 0;               /* trailing junk -> not a SPICE number */
}

int wosp_spice_seconds(const char *token, double *out)
{
    char stripped[NL_LINE_MAX];
    double mant, scale = 1.0;
    int has_suffix = 0;
    char suffix[8];
    size_t i;

    wosp_strip(token, stripped, sizeof stripped);
    if (!nl_spice_number(stripped, &mant, &has_suffix, suffix, sizeof suffix)) {
        return 0;
    }
    if (has_suffix) {
        for (i = 0; i < sizeof NL_SCALES / sizeof NL_SCALES[0]; i++) {
            if (strcmp(suffix, NL_SCALES[i].suffix) == 0) {
                scale = NL_SCALES[i].scale;
                break;
            }
        }
    }
    *out = mant * scale;
    return 1;
}

int wosp_find_tstop(const char *const *lines, size_t n, double *out)
{
    size_t i;

    for (i = 0; i < n; i++) {
        const char *tok[8];
        char tokbuf[NL_LINE_MAX];
        size_t nt;

        nt = nl_split_copy(lines[i], tokbuf, sizeof tokbuf, tok, 8);
        if (nt >= 3) {
            char verb[16];
            wosp_copy_str(verb, sizeof verb, tok[0]);
            nl_lower(verb);
            if (strcmp(verb, ".tran") == 0) {
                /* Faithful to the original: the FIRST .tran with three or
                 * more fields decides, and a malformed stop time returns
                 * "none" without ever looking at a later .tran card. */
                return wosp_spice_seconds(tok[2], out);
            }
        }
    }
    return 0;
}

/* ---------------------------------------------------------------------- */
/* _failure_report()                                                      */
/* ---------------------------------------------------------------------- */

/*
 * `time\s*=\s*([0-9.eE+-]+)` searched anywhere in the line.  Note
 * "timestep = 0" does NOT match: after folding, `time` is followed by `step`
 * rather than by optional whitespace and '=', so the search fails there and
 * continues - which is what makes a marker with no time read as a failure
 * rather than as "reached the end".
 */
static int nl_time_search(const char *s, double *out)
{
    const char *p = s;

    while ((p = strstr(p, "time")) != NULL) {
        const char *q = p + 4;
        const char *num;
        char buf[64];
        size_t n;
        char *endp;

        while (*q == ' ' || *q == '\t' || *q == '\n' || *q == '\r' ||
               *q == '\v' || *q == '\f') {
            q++;
        }
        if (*q != '=') {
            p += 4;
            continue;
        }
        q++;
        while (*q == ' ' || *q == '\t' || *q == '\n' || *q == '\r' ||
               *q == '\v' || *q == '\f') {
            q++;
        }
        num = q;
        while (*q && (isdigit((unsigned char)*q) || *q == '.' ||
                      *q == 'e' || *q == 'E' || *q == '+' || *q == '-')) {
            q++;
        }
        if (q == num) {
            p += 4;
            continue;
        }
        n = (size_t)(q - num);
        if (n >= sizeof buf) {
            return 0;
        }
        memcpy(buf, num, n);
        buf[n] = '\0';
        *out = strtod(buf, &endp);
        if (endp == buf) {
            return 0;       /* unparsable: Python raises -> no match */
        }
        return 1;
    }
    return 0;
}

/* malloc'd copy - strdup() is POSIX and this core is built -std=c11, where
 * it is not guaranteed to be declared. */
static char *nl_strdup(const char *s)
{
    size_t n = strlen(s) + 1;
    char *p = (char *)malloc(n);
    if (p != NULL) {
        memcpy(p, s, n);
    }
    return p;
}

/* Growable list of message fragments, because Python's dedup check runs over
 * the WHOLE list while only the first 8 are ever printed. */
typedef struct {
    char **item;
    size_t n, cap;
} nl_list;

static int nl_list_push(nl_list *l, const char *s)
{
    size_t i;
    for (i = 0; i < l->n; i++) {
        if (strcmp(l->item[i], s) == 0) {
            return 1;               /* `follower not in matched` */
        }
    }
    if (l->n == l->cap) {
        size_t cap = l->cap ? l->cap * 2 : 8;
        char **grown = (char **)realloc(l->item, cap * sizeof *grown);
        if (grown == NULL) {
            return 0;
        }
        l->item = grown;
        l->cap = cap;
    }
    l->item[l->n] = nl_strdup(s);
    if (l->item[l->n] == NULL) {
        return 0;
    }
    l->n++;
    return 1;
}

static void nl_list_free(nl_list *l)
{
    size_t i;
    for (i = 0; i < l->n; i++) {
        free(l->item[i]);
    }
    free(l->item);
    l->item = NULL;
    l->n = l->cap = 0;
}

int wosp_failure_report(const char *const *lines, size_t n,
                        int has_tstop, double tstop,
                        char *out, size_t outlen)
{
    nl_list matched;
    int produced_rows = 0;
    int skip_next = 0;
    size_t i;
    size_t o = 0;
    size_t shown = 0;

    matched.item = NULL;
    matched.n = matched.cap = 0;

    for (i = 0; i < n; i++) {
        if (nl_contains_ci(lines[i], "no. of data rows")) {
            produced_rows = 1;
            break;
        }
    }

    for (i = 0; i < n; i++) {
        char lowered[NL_LINE_MAX];
        char stripped[NL_LINE_MAX];
        int is_marker = 0;
        size_t m;

        if (skip_next) {
            skip_next = 0;
            continue;
        }
        wosp_copy_str(lowered, sizeof lowered, lines[i]);
        nl_lower(lowered);

        for (m = 0; m < NL_N_MARKERS; m++) {
            if (strstr(lowered, NL_FAILURE_MARKERS[m]) != NULL) {
                is_marker = 1;
                break;
            }
        }
        if (!is_marker) {
            continue;
        }

        /*
         * A transient that already reached tstop is not a failure even when
         * ngspice says so afterwards: measured on three decks that each
         * printed `No. of Data Rows` first and `Timestep too small; time =
         * <tstop>` second while holding a complete, correct result.  Dropping
         * the marker also swallows the `run simulation(s) aborted` line that
         * follows it, because that companion only ever appears alongside it.
         */
        if (has_tstop && produced_rows &&
            strstr(lowered, "timestep too small") != NULL) {
            double reported;
            if (nl_time_search(lines[i], &reported) &&
                reported >= tstop * (1.0 - 1e-6)) {
                skip_next = 1;
                continue;
            }
        }

        wosp_strip(lines[i], stripped, sizeof stripped);
        if (!nl_list_push(&matched, stripped)) {
            nl_list_free(&matched);
            return 0;
        }
        if (i + 1 < n) {
            char follower[NL_LINE_MAX];
            wosp_strip(lines[i + 1], follower, sizeof follower);
            if (follower[0] != '\0') {
                nl_list_push(&matched, follower);
            }
        }
    }

    if (matched.n == 0) {
        nl_list_free(&matched);
        if (outlen) {
            out[0] = '\0';
        }
        return 0;
    }

    /* " | ".join(matched[:8]) */
    for (i = 0; i < matched.n && i < 8; i++) {
        size_t len = strlen(matched.item[i]);
        if (shown && o + 3 < outlen) {
            memcpy(out + o, " | ", 3);
            o += 3;
        }
        if (o + len + 1 > outlen) {
            len = (o + 1 < outlen) ? outlen - 1 - o : 0;
        }
        memcpy(out + o, matched.item[i], len);
        o += len;
        shown++;
    }
    if (outlen) {
        out[o < outlen ? o : outlen - 1] = '\0';
    }
    nl_list_free(&matched);
    return 1;
}

/* ---------------------------------------------------------------------- */
/* validate_cmd()                                                         */
/* ---------------------------------------------------------------------- */

wosp_nl_status wosp_validate_cmd(const char *command,
                                 char *out, size_t outlen,
                                 char *err, size_t errlen)
{
    char text[NL_LINE_MAX];
    char verb[128];
    const char *tok[4];
    char tokbuf[NL_LINE_MAX];
    size_t nt;
    const char *bad;

    wosp_strip(command, text, sizeof text);
    if (text[0] == '\0') {
        wosp_set_err(err, errlen, "ngSpice_Command rejected: empty command");
        return WOSP_NL_REJECTED;
    }

    /*
     * Verb first: for `shell ...` the actionable reason is the verb, not the
     * redirection character that happens to follow it - so the allowlist is
     * checked before the forbidden-character scan, as in Python.
     */
    nt = nl_split_copy(text, tokbuf, sizeof tokbuf, tok, 4);
    wosp_copy_str(verb, sizeof verb, nt ? tok[0] : "");
    nl_lower(verb);
    if (!nl_in_list(verb, NL_ALLOWED_CMDS, NL_N_CMDS)) {
        char rv[256];
        nl_repr(verb, rv, sizeof rv);
        wosp_set_err(err, errlen,
                     "ngSpice_Command rejected the command "
                     "(not on allowlist: %s) @cmd: %s",
                     rv, text);
        return WOSP_NL_REJECTED;
    }

    bad = strpbrk(text, NL_CMD_FORBIDDEN);
    if (bad != NULL) {
        char one[2], rc[16];
        one[0] = *bad;
        one[1] = '\0';
        nl_repr(one, rc, sizeof rc);
        wosp_set_err(err, errlen,
                     "ngSpice_Command rejected the command "
                     "(character %s not permitted) @cmd: %s",
                     rc, text);
        return WOSP_NL_REJECTED;
    }

    if (outlen) {
        wosp_copy_str(out, outlen, text);
    }
    return WOSP_NL_OK;
}

/* ---------------------------------------------------------------------- */
/* _strip_normalize() and the two banned checks                           */
/* ---------------------------------------------------------------------- */

void wosp_strip_normalize(const char *line, char *out, size_t outlen)
{
    char work[NL_LINE_MAX];
    size_t i, o = 0;
    char lstripped[NL_LINE_MAX];

    /* CRLF and lone CR -> LF, before anything else looks at the line. */
    for (i = 0; line[i] != '\0' && o + 1 < sizeof work; i++) {
        if (line[i] == '\r') {
            if (line[i + 1] == '\n') {
                i++;
            }
            work[o++] = '\n';
        } else {
            work[o++] = line[i];
        }
    }
    work[o] = '\0';

    wosp_lstrip_sp(work, lstripped, sizeof lstripped);

    /* One '+' continuation is consumed, then its own leading blanks. */
    if (lstripped[0] == '+') {
        char after[NL_LINE_MAX];
        wosp_lstrip_sp(lstripped + 1, after, sizeof after);
        wosp_copy_str(lstripped, sizeof lstripped, after);
    }
    wosp_copy_str(out, outlen, lstripped);
}

void wosp_is_banned_directive(const char *norm, int *banned,
                              char *name, size_t namelen)
{
    char lowered[NL_LINE_MAX];
    char stripped[NL_LINE_MAX];
    const char *p;
    size_t n = 0;

    *banned = 0;
    name[0] = '\0';

    /*
     * .control/.endc are checked as whole (lowered, stripped) lines first,
     * because they are the two directives that must be refused even with no
     * trailing whitespace - and DOT_DIR_RE below REQUIRES that whitespace.
     * That is why `.control` is caught here and `.foo` is not: `.foo` has no
     * trailing space, so no regex matches, and unknown directives pass.
     */
    wosp_copy_str(lowered, sizeof lowered, norm);
    nl_lower(lowered);
    wosp_strip(lowered, stripped, sizeof stripped);
    if (strcmp(stripped, ".control") == 0 || strcmp(stripped, ".endc") == 0) {
        *banned = 1;
        /* Python: norm_lower.lstrip('.').strip() */
        p = stripped;
        while (*p == '.') {
            p++;
        }
        while (nl_isws((unsigned char)*p)) {
            p++;
        }
        wosp_copy_str(name, namelen, p);
        return;
    }

    /* DOT_DIR_RE: ^[ \t]*\.([a-zA-Z]+)\s */
    p = norm;
    while (*p == ' ' || *p == '\t') {
        p++;
    }
    if (*p != '.') {
        return;
    }
    p++;
    if (!isalpha((unsigned char)*p)) {
        return;
    }
    while (isalpha((unsigned char)*p)) {
        if (n + 1 < namelen) {
            name[n] = (char)tolower((unsigned char)*p);
        }
        n++;
        p++;
    }
    if (n >= namelen) {
        n = namelen - 1;
    }
    name[n] = '\0';
    if (!nl_isws((unsigned char)*p)) {
        name[0] = '\0';
        return;                 /* no trailing whitespace -> no match */
    }
    if (nl_in_list(name, NL_ALLOWED_DIRECTIVES, NL_N_DIRECTIVES)) {
        name[0] = '\0';
        return;
    }
    *banned = 1;
}

void wosp_is_banned_cmd(const char *norm, int *banned,
                        char *name, size_t namelen)
{
    char stripped[NL_LINE_MAX];
    const char *tok[4];
    char tokbuf[NL_LINE_MAX];
    size_t nt;

    *banned = 0;
    name[0] = '\0';

    wosp_strip(norm, stripped, sizeof stripped);
    if (nl_in_list(stripped, NL_ALLOWED_CMDS, NL_N_CMDS)) {
        return;
    }
    nt = nl_split_copy(stripped, tokbuf, sizeof tokbuf, tok, 4);
    wosp_copy_str(name, namelen, nt ? tok[0] : "");
    *banned = 1;
}

/* ---------------------------------------------------------------------- */
/* Include handling                                                       */
/* ---------------------------------------------------------------------- */

/*
 * INCLUDE_ARG_RE, scanned:
 *
 *     ^[ \t]*\.([a-zA-Z]+)(?:[ \t]+(?:"([^"]*)"|'([^']*)'|(\S+)))?
 *
 * Returns 1 when the pattern matches at all (it always does for a
 * dot-directive), sets `name` to group 1, and sets `*grp` to 2, 3 or 4 for
 * the file argument or 0 when the optional group is absent.  `gs`/`ge` are
 * the span of that group, which the rewrite splices over - so a QUOTED
 * include keeps its quotes and a BARE one does not, exactly as Python does.
 */
static int nl_include_arg(const char *s, char *name, size_t namelen,
                          int *grp, size_t *gs, size_t *ge)
{
    const char *p = s;
    size_t n = 0;

    *grp = 0;
    *gs = *ge = 0;
    name[0] = '\0';

    while (*p == ' ' || *p == '\t') {
        p++;
    }
    if (*p != '.') {
        return 0;
    }
    p++;
    if (!isalpha((unsigned char)*p)) {
        return 0;
    }
    while (isalpha((unsigned char)*p)) {
        if (n + 1 < namelen) {
            name[n] = *p;
        }
        n++;
        p++;
    }
    if (n >= namelen) {
        n = namelen - 1;
    }
    name[n] = '\0';

    /* Optional: one or more blanks, then a quoted or bare argument. */
    if (*p != ' ' && *p != '\t') {
        return 1;
    }
    {
        const char *q = p;
        while (*q == ' ' || *q == '\t') {
            q++;
        }
        if (*q == '\0') {
            return 1;
        }
        if (*q == '"') {
            const char *close = strchr(q + 1, '"');
            if (close != NULL) {
                *grp = 2;
                *gs = (size_t)(q + 1 - s);
                *ge = (size_t)(close - s);
                return 1;
            }
        } else if (*q == '\'') {
            const char *close = strchr(q + 1, '\'');
            if (close != NULL) {
                *grp = 3;
                *gs = (size_t)(q + 1 - s);
                *ge = (size_t)(close - s);
                return 1;
            }
        }
        /* \S+ : everything up to the next whitespace byte. */
        {
            const char *start = q;
            while (*q && !nl_isws((unsigned char)*q)) {
                q++;
            }
            if (q == start) {
                return 1;
            }
            *grp = 4;
            *gs = (size_t)(start - s);
            *ge = (size_t)(q - s);
        }
    }
    return 1;
}

static int nl_is_abs(const char *p)
{
    /* os.path.isabs() on Windows: a leading separator, or drive-letter plus
     * separator.  'C:x' (drive-relative) is NOT absolute - Python agrees. */
    if (p[0] == '\\' || p[0] == '/') {
        return 1;
    }
    if (((p[0] >= 'A' && p[0] <= 'Z') || (p[0] >= 'a' && p[0] <= 'z')) &&
        p[1] == ':' && (p[2] == '\\' || p[2] == '/')) {
        return 1;
    }
    return 0;
}

/* os.path.exists(): a directory counts, unlike isfile.  Library resolution
 * uses this one (Python calls os.path.exists there); the include allowlist
 * uses nl_isfile, because a directory is not a file to scan. */
static int nl_exists(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0;
}

static int nl_isfile(const char *path)
{
    struct stat st;
    if (stat(path, &st) != 0) {
        return 0;
    }
#ifdef S_ISDIR
    return !S_ISDIR(st.st_mode);
#else
    return (st.st_mode & _S_IFMT) != _S_IFDIR;
#endif
}

static void nl_join(char *out, size_t outlen, const char *a, const char *b)
{
    size_t la = strlen(a);
    int need_sep = la > 0 && a[la - 1] != '\\' && a[la - 1] != '/';

    wosp_copy_str(out, outlen, a);
    if (need_sep && la + 1 < outlen) {
        out[la] = '\\';
        out[la + 1] = '\0';
    }
    if (b && *b) {
        size_t cur = strlen(out);
        wosp_copy_str(out + cur, outlen - cur, b);
    }
}

/* Forward declarations for the include recursion. */
static wosp_nl_status nl_sanitise(const char *line, int depth,
                                  char *out, size_t outlen,
                                  char *err, size_t errlen);

wosp_nl_status wosp_scan_included_file(const char *path, int depth,
                                       char *err, size_t errlen)
{
    FILE *f;
    char *content = NULL;
    size_t cap = 0, len = 0;
    int c;

    f = fopen(path, "rb");
    if (f == NULL) {
        wosp_set_err(err, errlen,
                     NL_PREFIX "included file unreadable: %s", path);
        return WOSP_NL_REJECTED;
    }
    while ((c = fgetc(f)) != EOF) {
        if (len + 1 >= cap) {
            size_t ncap = cap ? cap * 2 : 8192;
            char *grown = (char *)realloc(content, ncap);
            if (grown == NULL) {
                free(content);
                fclose(f);
                wosp_set_err(err, errlen,
                             NL_PREFIX "included file unreadable: %s", path);
                return WOSP_NL_REJECTED;
            }
            content = grown;
            cap = ncap;
        }
        content[len++] = (char)c;
    }
    fclose(f);
    if (content == NULL) {
        content = (char *)malloc(1);
        if (content == NULL) {
            return WOSP_NL_OK;      /* empty file: nothing to scan */
        }
    }
    content[len] = '\0';

    /*
     * Python reads with encoding='utf-8', errors='replace' and splits with
     * str.splitlines().  Splitting here is on \n and \r only: splitlines()
     * also breaks on \v \f \x1c-\x1e \x85 U+2028 U+2029, none of which occur
     * in a .lib file, and splitting a UTF-8 continuation byte would corrupt
     * the line rather than merely split it differently.
     */
    {
        char *p = content;
        while (*p) {
            char *nl = strpbrk(p, "\n\r");
            char line[NL_LINE_MAX];
            char probe[NL_LINE_MAX];
            size_t n;
            wosp_nl_status st;

            n = nl ? (size_t)(nl - p) : strlen(p);
            if (n >= sizeof line) {
                n = sizeof line - 1;
            }
            memcpy(line, p, n);
            line[n] = '\0';

            wosp_strip(line, probe, sizeof probe);
            if (probe[0] != '\0') {
                st = nl_sanitise(line, depth, NULL, 0, err, errlen);
                if (st != WOSP_NL_OK) {
                    char wrapped[NL_LINE_MAX];
                    /* Python re-raises naming the file, keeping the inner
                     * message whole - so the prefix appears twice. */
                    snprintf(wrapped, sizeof wrapped,
                             NL_PREFIX "%s: %s", path, err);
                    wosp_copy_str(err, errlen, wrapped);
                    free(content);
                    return WOSP_NL_REJECTED;
                }
            }
            if (!nl) {
                break;
            }
            p = nl + (*nl == '\r' && nl[1] == '\n' ? 2 : 1);
        }
    }
    free(content);
    return WOSP_NL_OK;
}

wosp_nl_status wosp_check_include_path(const char *raw, const char *directive,
                                       int depth,
                                       char *out, size_t outlen,
                                       char *err, size_t errlen)
{
    char candidates[2][NL_PATH_MAX];
    size_t ncand = 0;
    char allowed[NL_PATH_MAX];
    char inside[4][NL_PATH_MAX];
    size_t ninside = 0;
    size_t i;

    if (raw[0] == '\0') {
        wosp_set_err(err, errlen,
                     NL_PREFIX ".%s with no file argument @line", directive);
        return WOSP_NL_REJECTED;
    }
    if (depth >= WOSP_NL_INCLUDE_SCAN_DEPTH_LIMIT) {
        wosp_set_err(err, errlen,
                     NL_PREFIX ".%s nesting exceeds depth %d @line: %s",
                     directive, WOSP_NL_INCLUDE_SCAN_DEPTH_LIMIT, raw);
        return WOSP_NL_REJECTED;
    }

    if (nl_is_abs(raw)) {
        wosp_copy_str(candidates[0], sizeof candidates[0], raw);
        ncand = 1;
    } else {
        /* Tried against cwd first, then the repo root - and a candidate
         * INSIDE the allowlist is preferred over one outside it, so a
         * foreign cwd with a look-alike path cannot win. */
        char cwd[NL_PATH_MAX];
        if (nl_getcwd(cwd, sizeof cwd) != NULL) {
            nl_join(candidates[ncand], sizeof candidates[0], cwd, raw);
            ncand++;
        }
        {
            char root[NL_PATH_MAX];
            if (wosp_project_root(root, sizeof root)) {
                nl_join(candidates[ncand], sizeof candidates[0], root, raw);
                ncand++;
            }
        }
    }

    {
        char root[NL_PATH_MAX];
        wosp_project_root(root, sizeof root);
        nl_join(allowed, sizeof allowed, root, "circuits\\components");
    }

    for (i = 0; i < ncand && ninside < 4; i++) {
        char resolved[NL_PATH_MAX];
        if (!wosp_realpath(candidates[i], resolved, sizeof resolved)) {
            continue;
        }
        /* resolved == allowed, or a descendant of it. */
        if (strcmp(resolved, allowed) == 0 ||
            (strncmp(resolved, allowed, strlen(allowed)) == 0 &&
             (resolved[strlen(allowed)] == '\\' ||
              resolved[strlen(allowed)] == '/'))) {
            wosp_copy_str(inside[ninside], sizeof inside[0], resolved);
            ninside++;
        }
    }

    /* Prefer an allowlisted candidate that exists as a file; one that
     * resolved inside but cannot be read says so rather than falling through
     * to the outside error, which is clearer and fails closed. */
    for (i = 0; i < ninside; i++) {
        if (nl_isfile(inside[i])) {
            if (wosp_scan_included_file(inside[i], depth + 1,
                                        err, errlen) != WOSP_NL_OK) {
                return WOSP_NL_REJECTED;
            }
            if (outlen) {
                wosp_copy_str(out, outlen, inside[i]);
            }
            return WOSP_NL_OK;
        }
    }
    if (ninside > 0) {
        wosp_set_err(err, errlen,
                     NL_PREFIX ".%s file not found or unreadable @line: %s",
                     directive, inside[0]);
        return WOSP_NL_REJECTED;
    }
    wosp_set_err(err, errlen,
                 NL_PREFIX ".%s outside allowed directories @line: %s",
                 directive, raw);
    return WOSP_NL_REJECTED;
}

/* ---------------------------------------------------------------------- */
/* _sanitise_line() - the single choke point                              */
/* ---------------------------------------------------------------------- */

static wosp_nl_status nl_sanitise(const char *line, int depth,
                                  char *out, size_t outlen,
                                  char *err, size_t errlen)
{
    char norm[NL_LINE_MAX];
    char again[NL_LINE_MAX];
    int banned = 0;
    char dname[64];
    char iname[64];
    int grp;
    size_t gs, ge;

    wosp_strip_normalize(line, norm, sizeof norm);

    /* Blank and comment lines pass through untouched. */
    if (norm[0] == '\0' || norm[0] == '*') {
        if (outlen) {
            wosp_copy_str(out, outlen, norm);
        }
        return WOSP_NL_OK;
    }

    wosp_is_banned_directive(norm, &banned, dname, sizeof dname);
    if (banned) {
        wosp_set_err(err, errlen,
                     NL_PREFIX "banned directive @line: .%s", dname);
        return WOSP_NL_REJECTED;
    }

    /*
     * .include / .lib / .inc: allowlisted only after the argument resolves
     * inside the allowlist AND its own content passes these same rules, then
     * rewritten to the validated absolute path - so ngspice reads exactly the
     * file that was checked, whatever the cwd.
     */
    if (nl_include_arg(norm, iname, sizeof iname, &grp, &gs, &ge)) {
        char lowered[32];
        wosp_copy_str(lowered, sizeof lowered, iname);
        nl_lower(lowered);
        if (nl_in_list(lowered, NL_INCLUDE_FAMILY, 3)) {
            char raw[NL_LINE_MAX];
            char resolved[NL_PATH_MAX];
            char built[NL_PATH_MAX + 4];
            char rebuilt[NL_LINE_MAX];
            size_t n, head, rlen, tail;

            /* The file argument is whatever group matched - the interior of
             * double quotes, of single quotes, or a bare word.  grp == 0
             * means the optional group was absent, i.e. no argument at all,
             * which _check_include_path rejects by name. */
            raw[0] = '\0';
            if (grp != 0 && ge > gs) {
                n = ge - gs;
                if (n >= sizeof raw) {
                    n = sizeof raw - 1;
                }
                memcpy(raw, norm + gs, n);
                raw[n] = '\0';
            }

            if (wosp_check_include_path(raw, lowered, depth,
                                        resolved, sizeof resolved,
                                        err, errlen) != WOSP_NL_OK) {
                return WOSP_NL_REJECTED;
            }

            /*
             * Python picks the replacement's quoting off the group it spliced:
             * a bare argument (group 4) becomes quoted only when the resolved
             * path contains a space, while a quoted one keeps the quotes it
             * already had because only the INTERIOR span is replaced.
             */
            if (grp == 4 && strchr(resolved, ' ') != NULL) {
                snprintf(built, sizeof built, "\"%s\"", resolved);
            } else {
                wosp_copy_str(built, sizeof built, resolved);
            }

            /* Splice: norm[:gs] + replacement + norm[ge:] */
            head = gs;
            rlen = strlen(built);
            tail = strlen(norm + ge);
            if (head + rlen + tail >= sizeof rebuilt) {
                wosp_set_err(err, errlen,
                             NL_PREFIX "netlist line too long to rewrite");
                return WOSP_NL_REJECTED;
            }
            memcpy(rebuilt, norm, head);
            memcpy(rebuilt + head, built, rlen);
            memcpy(rebuilt + head + rlen, norm + ge, tail);
            rebuilt[head + rlen + tail] = '\0';
            wosp_copy_str(norm, sizeof norm, rebuilt);
        }
    }

    /*
     * `cmd(` in netlist content must hit the banned-command check.  The
     * second half of the Python condition (`'Cmd(' in norm`) is redundant -
     * it is implied by the case-folded first half - and is kept out rather
     * than reimplemented as a no-op.
     */
    {
        char lowered[NL_LINE_MAX];
        wosp_copy_str(lowered, sizeof lowered, norm);
        nl_lower(lowered);
        if (strstr(lowered, "cmd(") != NULL) {
            int banned_cmd = 0;
            char cname[128];
            wosp_is_banned_cmd(norm, &banned_cmd, cname, sizeof cname);
            if (banned_cmd) {
                wosp_set_err(err, errlen,
                             NL_PREFIX "banned command in netlist @line");
                return WOSP_NL_REJECTED;
            }
        }
    }

    /* Re-check after normalisation: a '+' continuation that only became a
     * directive on the second strip must still be refused. */
    wosp_strip_normalize(norm, again, sizeof again);
    wosp_copy_str(norm, sizeof norm, again);
    wosp_is_banned_directive(norm, &banned, dname, sizeof dname);
    if (banned) {
        wosp_set_err(err, errlen,
                     NL_PREFIX "banned directive @line: .%s", dname);
        return WOSP_NL_REJECTED;
    }

    if (outlen) {
        wosp_copy_str(out, outlen, norm);
    }
    return WOSP_NL_OK;
}

wosp_nl_status wosp_sanitise_line(const char *line, int depth,
                                  char *out, size_t outlen,
                                  char *err, size_t errlen)
{
    return nl_sanitise(line, depth, out, outlen, err, errlen);
}

/* ---------------------------------------------------------------------- */
/* load_circuit()'s deck preparation                                      */
/* ---------------------------------------------------------------------- */

wosp_nl_status wosp_prepare_deck(const char *const *lines, size_t n,
                                 char *arena, size_t arena_len,
                                 char **out_lines, size_t cap,
                                 size_t *out_n,
                                 int *has_tstop, double *tstop,
                                 char *err, size_t errlen)
{
    size_t i, used = 0, count = 0;

    *out_n = 0;
    *has_tstop = 0;
    *tstop = 0.0;

    for (i = 0; i < n; i++) {
        char probe[NL_LINE_MAX];
        char sline[NL_LINE_MAX];
        size_t len;

        wosp_strip(lines[i], probe, sizeof probe);
        if (probe[0] == '\0') {
            continue;               /* blanks are implicit */
        }
        if (nl_sanitise(lines[i], 0, sline, sizeof sline,
                        err, errlen) != WOSP_NL_OK) {
            /* Python re-raises with the same prefix a second time, so the
             * message a caller sees is doubled. */
            char wrapped[NL_LINE_MAX];
            snprintf(wrapped, sizeof wrapped, NL_PREFIX "%s", err);
            wosp_copy_str(err, errlen, wrapped);
            return WOSP_NL_REJECTED;
        }
        len = strlen(sline);
        if (count >= cap || used + len + 1 > arena_len) {
            wosp_set_err(err, errlen,
                         "prepared deck exceeds the caller's arena "
                         "(%zu lines, %zu bytes)", n, arena_len);
            return WOSP_NL_REJECTED;
        }
        memcpy(arena + used, sline, len + 1);
        out_lines[count++] = arena + used;
        used += len + 1;
    }

    /*
     * A deck needs a title comment as its first line - ngspice reads the
     * first line as the title whether or not it looks like one.  The title's
     * text is stored at the END of the arena rather than the front, because
     * the lines already there cannot move; only the pointer array shifts.
     */
    if (count == 0 || !nl_starts_with(out_lines[0], "*")) {
        static const char title[] = "* WOWKISPICE circuit";
        size_t len = sizeof title;      /* includes the terminator */
        if (count >= cap || used + len > arena_len) {
            wosp_set_err(err, errlen, "prepared deck exceeds the arena");
            return WOSP_NL_REJECTED;
        }
        if (count > 0) {
            memmove(out_lines + 1, out_lines, count * sizeof *out_lines);
        }
        memcpy(arena + used, title, len);
        out_lines[0] = arena + used;
        used += len;
        count++;
    }

    /* ...and an .end, or ngspice keeps reading past the deck. */
    {
        int has_end = 0;
        for (i = 0; i < count; i++) {
            char lowered[NL_LINE_MAX];
            wosp_copy_str(lowered, sizeof lowered, out_lines[i]);
            nl_lower(lowered);
            if (strcmp(lowered, ".end") == 0) {
                has_end = 1;
                break;
            }
        }
        if (!has_end) {
            static const char e[] = ".end";
            size_t len = sizeof e;
            if (used + len > arena_len) {
                wosp_set_err(err, errlen, "prepared deck exceeds the arena");
                return WOSP_NL_REJECTED;
            }
            memcpy(arena + used, e, len);
            out_lines[count++] = arena + used;
            used += len;
        }
    }

    *out_n = count;
    *has_tstop = wosp_find_tstop((const char *const *)out_lines, count, tstop);
    return WOSP_NL_OK;
}

/* ---------------------------------------------------------------------- */
/* Path handling: realpath, project root, library resolution              */
/* ---------------------------------------------------------------------- */

#ifdef _WIN32

/* Strip \\?\ (and \\?\UNC\) from GetFinalPathNameByHandle's answer. */
static void nl_unprefix(char *p)
{
    if (strncmp(p, "\\\\?\\UNC\\", 8) == 0) {
        memmove(p + 2, p + 8, strlen(p + 8) + 1);
        p[0] = '\\';
        p[1] = '\\';
    } else if (strncmp(p, "\\\\?\\", 4) == 0) {
        memmove(p, p + 4, strlen(p + 4) + 1);
    }
}

/*
 * Canonical case + separator form of an EXISTING path, via a handle - which
 * is also how os.path.realpath() gets it, so the strings match rather than
 * merely denote the same file.  Returns 0 when the path does not exist.
 */
static int nl_canonical(const char *path, char *out, size_t outlen)
{
    HANDLE h;
    char buf[NL_PATH_MAX];
    DWORD n;

    h = CreateFileA(path, 0,
                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        return 0;
    }
    n = GetFinalPathNameByHandleA(h, buf, sizeof buf, FILE_NAME_NORMALIZED);
    CloseHandle(h);
    if (n == 0 || n >= sizeof buf) {
        return 0;
    }
    nl_unprefix(buf);
    wosp_copy_str(out, outlen, buf);
    return 1;
}

/*
 * Fall back to the deepest EXISTING ancestor: a path whose leaf is not there
 * yet still has its prefix on disk in a particular case, and Python
 * normalises exactly that far too.
 */
static int nl_canonical_prefix(const char *path, char *out, size_t outlen)
{
    char work[NL_PATH_MAX];
    char best[NL_PATH_MAX];
    char *slash;

    wosp_copy_str(work, sizeof work, path);
    if (nl_canonical(work, best, sizeof best)) {
        wosp_copy_str(out, outlen, best);
        return 1;
    }
    for (;;) {
        slash = strrchr(work, '\\');
        if (slash == NULL) {
            slash = strrchr(work, '/');
        }
        if (slash == NULL) {
            break;
        }
        /* Keep the root ("C:\") intact rather than eating into it. */
        if (slash == work + 2 && work[1] == ':') {
            break;
        }
        if (slash == work) {
            break;
        }
        *slash = '\0';
        if (nl_canonical(work, best, sizeof best)) {
            /* Re-attach the tail that was not canonicalisable. */
            size_t bl = strlen(best), tl = strlen(path) - strlen(work);
            if (bl + 1 + tl < outlen) {
                memcpy(out, best, bl);
                out[bl] = '\\';
                memcpy(out + bl + 1, path + strlen(work) + 1, tl);
                out[bl + 1 + tl] = '\0';
            }
            return 1;
        }
    }
    wosp_copy_str(out, outlen, path);
    return 0;
}

#endif /* _WIN32 */

int wosp_realpath(const char *path, char *out, size_t outlen)
{
    char abs[NL_PATH_MAX];
    char norm[NL_PATH_MAX];
    size_t i = 0, o = 0;
    char root[NL_PATH_MAX];
    size_t rootlen = 0;
    const char *comps[128];
    size_t ncomp = 0;
    char storage[128][256];
    size_t used = 0;

    if (path == NULL || path[0] == '\0' || outlen == 0) {
        return 0;
    }

    /* 1. Absolute, with / and \ unified. */
    if (nl_is_abs(path)) {
        wosp_copy_str(abs, sizeof abs, path);
    } else {
        char cwd[NL_PATH_MAX];
        if (nl_getcwd(cwd, sizeof cwd) == NULL) {
            return 0;
        }
        nl_join(abs, sizeof abs, cwd, path);
    }
    for (i = 0; abs[i] != '\0' && o + 1 < sizeof norm; i++) {
        norm[o++] = (abs[i] == '/') ? '\\' : abs[i];
    }
    norm[o] = '\0';

    /* 2. Split off the root: "C:\" or "\\server\share\". */
    if (((norm[0] >= 'A' && norm[0] <= 'Z') ||
         (norm[0] >= 'a' && norm[0] <= 'z')) && norm[1] == ':') {
        rootlen = 2;
        if (norm[2] == '\\') {
            rootlen = 3;
        }
    } else if (norm[0] == '\\' && norm[1] == '\\') {
        char *s1 = strchr(norm + 2, '\\');
        if (s1 == NULL) {
            rootlen = strlen(norm);
        } else {
            char *s2 = strchr(s1 + 1, '\\');
            rootlen = s2 ? (size_t)(s2 - norm) + 1 : strlen(norm);
        }
    } else if (norm[0] == '\\') {
        rootlen = 1;
    }
    if (rootlen >= sizeof root) {
        return 0;
    }
    memcpy(root, norm, rootlen);
    root[rootlen] = '\0';

    /* 3. Collapse "." and ".." lexically.  (Python resolves these after
     * following symlinks; this repository has none, and the parity battery
     * would show it if that ever stopped being true.) */
    i = rootlen;
    while (norm[i]) {
        char comp[256];
        size_t n = 0;
        while (norm[i] == '\\') {
            i++;
        }
        if (!norm[i]) {
            break;
        }
        while (norm[i] && norm[i] != '\\' && n + 1 < sizeof comp) {
            comp[n++] = norm[i++];
        }
        comp[n] = '\0';
        if (strcmp(comp, ".") == 0) {
            continue;
        }
        if (strcmp(comp, "..") == 0) {
            if (ncomp > 0) {
                ncomp--;
            }
            continue;
        }
        if (ncomp < 128 && used + n + 1 <= sizeof storage) {
            memcpy(storage[ncomp], comp, n + 1);
            comps[ncomp] = storage[ncomp];
            used += n + 1;
            ncomp++;
        }
    }

    /* 4. Reassemble. */
    wosp_copy_str(abs, sizeof abs, root);
    for (i = 0; i < ncomp; i++) {
        size_t cur = strlen(abs);
        int need_sep = cur > 0 && abs[cur - 1] != '\\';
        if (need_sep && cur + 1 < sizeof abs) {
            abs[cur++] = '\\';
            abs[cur] = '\0';
        }
        wosp_copy_str(abs + cur, sizeof abs - cur, comps[i]);
    }

#ifdef _WIN32
    /* 5. Canonicalise to the case the filesystem actually holds, so the
     *    rewritten netlist line string-matches os.path.realpath(). */
    return nl_canonical_prefix(abs, out, outlen);
#else
    {
        char resolved[NL_PATH_MAX];
        if (realpath(abs, resolved) == NULL) {
            wosp_copy_str(out, outlen, abs);
            return 1;
        }
        wosp_copy_str(out, outlen, resolved);
        return 1;
    }
#endif
}

/*
 * PROJECT_ROOT is fixed at import time by __file__ in Python, so it never
 * moves with cwd.  The C equivalent is a compile-time constant (set by
 * CMake from this file's own location), overridable at runtime so the test
 * binary and the parity harness can point at a repository they choose.
 */
static char g_root[NL_PATH_MAX];
static int g_root_set = 0;

void wosp_set_project_root(const char *root)
{
    if (root != NULL && root[0] != '\0') {
        wosp_copy_str(g_root, sizeof g_root, root);
        g_root_set = 1;
    }
}

int wosp_project_root(char *out, size_t outlen)
{
    if (!g_root_set) {
        const char *env = getenv("WOSP_PROJECT_ROOT");
        if (env != NULL && env[0] != '\0') {
            wosp_copy_str(g_root, sizeof g_root, env);
        } else {
#ifdef WOSP_PROJECT_ROOT
            wosp_copy_str(g_root, sizeof g_root, WOSP_PROJECT_ROOT);
#else
            return 0;
#endif
        }
        g_root_set = 1;
    }
    /* Canonicalise so the allowlist comparison is against the same string
     * os.path.realpath() would produce for it. */
    {
        char canon[NL_PATH_MAX];
        if (wosp_realpath(g_root, canon, sizeof canon)) {
            wosp_copy_str(out, outlen, canon);
        } else {
            wosp_copy_str(out, outlen, g_root);
        }
    }
    return 1;
}

/*
 * The bundled DLL lives at a path derived from the repository root, the way
 * Python derives it from __file__.  C has no __file__, so the caller passes
 * the repository root and this appends Python's own relative path.
 */
static const char *NL_BUNDLED_REL =
    "tools/ngspice_dll/Spice64_dll/dll-vs/ngspice.dll";

int wosp_resolve_ngspice_library(const char *explicit_path,
                                 const char *repo_root,
                                 const char *bundled_rel,
                                 char *out_path, size_t outlen,
                                 char *tried, size_t triedlen)
{
    char acc[NL_PATH_MAX * 2];
    size_t used = 0;

    if (outlen) {
        out_path[0] = '\0';
    }
    if (triedlen) {
        tried[0] = '\0';
    }

#define NL_TRY(entry, label)                                                  \
    do {                                                                      \
        size_t el = strlen(entry);                                            \
        size_t ll = strlen(label);                                            \
        if (used + el + ll + 2 < sizeof acc) {                                \
            if (used) {                                                       \
                acc[used++] = '\n';                                           \
            }                                                                 \
            memcpy(acc + used, label, ll);                                    \
            used += ll;                                                       \
            memcpy(acc + used, entry, el);                                    \
            used += el;                                                       \
            acc[used] = '\0';                                                 \
        }                                                                     \
    } while (0)

    /* 1. An explicit request is honoured strictly: never silently replaced. */
    if (explicit_path != NULL) {
        NL_TRY(explicit_path, "");
        wosp_copy_str(tried, triedlen, acc);
        if (nl_exists(explicit_path)) {
            wosp_copy_str(out_path, outlen, explicit_path);
            return 1;
        }
        return 0;
    }

    /* 2. $WOSP_NGSPICE_LIB. */
    {
        const char *env = getenv("WOSP_NGSPICE_LIB");
        if (env != NULL && env[0] != '\0') {
            char labelled[NL_PATH_MAX + 64];
            snprintf(labelled, sizeof labelled, "%s (from $WOSP_NGSPICE_LIB)",
                     env);
            NL_TRY(env, labelled);
            if (nl_exists(env)) {
                wosp_copy_str(tried, triedlen, acc);
                wosp_copy_str(out_path, outlen, env);
                return 1;
            }
        }
    }

    /* 3. The bundled Windows DLL beside the repository. */
    {
        char root[NL_PATH_MAX];
        char bundled[NL_PATH_MAX];
        const char *rel = (bundled_rel != NULL) ? bundled_rel : NL_BUNDLED_REL;
        int got_root;
        if (repo_root != NULL && repo_root[0] != '\0') {
            wosp_copy_str(root, sizeof root, repo_root);
            got_root = 1;
        } else {
            got_root = wosp_project_root(root, sizeof root);
        }
        if (got_root) {
            nl_join(bundled, sizeof bundled, root, rel);
            NL_TRY(bundled, "");
            if (nl_exists(bundled)) {
                wosp_copy_str(tried, triedlen, acc);
                wosp_copy_str(out_path, outlen, bundled);
                return 1;
            }
        }
    }

    /*
     * 4. A system-installed library.  Python asks ctypes.util.find_library,
     *    which on this platform returns None - there is no soname to look up
     *    and no ld to ask.  C has no equivalent either, so the same
     *    "<system search ... -> None>" placeholder is recorded rather than
     *    inventing a search Python does not perform.
     */
    NL_TRY("<system search: find_library('ngspice') -> None>", "");
    wosp_copy_str(tried, triedlen, acc);
    return 0;

#undef NL_TRY
}

void wosp_missing_library_message(const char *tried,
                                  char *out, size_t outlen)
{
    /* Verbatim from ngspice_wrapper.py: the help text is the only thing a
     * user sees when nothing resolves, so its wording is part of the port. */
    static const char HELP[] =
        "\n\nFix it one of these ways:\n"
        "  * Windows: run setup.ps1 to fetch and place the bundled DLL\n"
        "    (it downloads the official ngspice build automatically)\n"
        "  * Linux/macOS: install ngspice system-wide, e.g.\n"
        "      sudo apt-get install -y ngspice libngspice0\n"
        "      brew install ngspice\n"
        "  * Any platform: point at an existing shared library, either\n"
        "      NgSpiceEngine(dll_path='/full/path/to/libngspice.so')\n"
        "      export WOSP_NGSPICE_LIB=/full/path/to/libngspice.so\n";
    char indented[NL_PATH_MAX * 2];
    size_t i, o = 0;

    /* Python joins with "\n  ", so every newline inside an entry gets the
     * same two-space indent. */
    for (i = 0; tried[i] != '\0' && o + 4 < sizeof indented; i++) {
        if (tried[i] == '\n') {
            indented[o++] = '\n';
            indented[o++] = ' ';
            indented[o++] = ' ';
        } else {
            indented[o++] = tried[i];
        }
    }
    indented[o] = '\0';

    snprintf(out, outlen, "ngspice library not found. Tried:\n  %s%s",
             indented, HELP);
}
