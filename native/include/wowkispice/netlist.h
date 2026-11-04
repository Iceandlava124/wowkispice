/*
 * netlist.h - C port of the pure logic in bridge/ngspice_wrapper.py.
 *
 * WHAT IS PORTED
 * --------------
 * Everything in ngspice_wrapper.py that decides whether a string is allowed,
 * without touching the simulator:
 *
 *   resolve_ngspice_library()  -> wosp_resolve_ngspice_library()
 *   _spice_seconds()           -> wosp_spice_seconds()
 *   _find_tstop()              -> wosp_find_tstop()
 *   _failure_report()          -> wosp_failure_report()
 *   validate_cmd()             -> wosp_validate_cmd()
 *   _strip_normalize()         -> wosp_strip_normalize()
 *   _is_banned_directive()     -> wosp_is_banned_directive()
 *   _is_banned_cmd()           -> wosp_is_banned_cmd()
 *   _sanitise_line()           -> wosp_sanitise_line()
 *   _check_include_path()      -> wosp_check_include_path()
 *   _scan_included_file()      -> wosp_scan_included_file()
 *   load_circuit()'s deck prep -> wosp_prepare_deck()
 *
 * WHAT IS NOT PORTED, AND WHY
 * ---------------------------
 * NgSpiceEngine itself, its six ctypes callbacks, the ngSpice_Init /
 * ngSpice_Init_Sync wiring, cmd()'s trip through ngSpice_Command(),
 * request_stop()'s thread, and every vector accessor (get_node_voltage,
 * get_vector_array, get_vector_complex) all call into ngspice.dll.  They are
 * the FFI layer, not the policy: the policy is everything above, and it is
 * what the Python suite actually asserts on (tests/test_ngspice_sanitiser.py,
 * TestFailureReportClassifier, the validate_cmd cases in
 * tests/test_security_vectors.py).
 *
 * wosp_prepare_deck() covers load_circuit()'s sanitise-and-normalise half.
 * The half that hands the deck to ngSpice_Circ is deliberately absent: it is
 * one call into the DLL, and pretending otherwise would mean a "ported"
 * load_circuit that cannot load anything.
 *
 * validate_cmd() has no C equivalent of Python's TypeError branch (a C
 * `const char *` cannot be "not a string"), so that one Python path is
 * unportable by construction rather than omitted.
 *
 * WHAT THIS CANNOT PROVE
 * ----------------------
 * No test here measures real silicon, and none of it runs the solver.  The
 * parity harness in native/tools/parity_netlist.py diffs this implementation
 * against bridge/ngspice_wrapper.py on a battery neither test suite was
 * transcribed from, which is what catches a port and its ported test being
 * wrong in the same way.
 */

#ifndef WOSP_NETLIST_H
#define WOSP_NETLIST_H

#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Rejection messages are one line of ngspice's own output plus context, so
 * the same bound the Python side effectively has (it joins at most 8 pieces)
 * is plenty. */
#define WOSP_NL_ERRMSG_MAX 1024

/* tests/test_ngspice_sanitiser.py::TestIncludedFileContent pins this as the
 * cycle cap: a self-including file must fail fast with the depth message. */
#define WOSP_NL_INCLUDE_SCAN_DEPTH_LIMIT 5

/*
 * Every rejection carries a message that the Python suite asserts on by
 * substring, so the enum exists only to let a caller tell "rejected" from
 * "accepted" without parsing text.  Nothing branches on the specific value;
 * the text is the contract.
 */
typedef enum {
    WOSP_NL_OK = 0,
    WOSP_NL_REJECTED = 1
} wosp_nl_status;

/*
 * Resolve the ngspice shared library, mirroring resolve_ngspice_library()'s
 * order exactly: explicit argument, then $WOSP_NGSPICE_LIB, then the bundled
 * Windows DLL beside the repository, then a system search.
 *
 * Returns 1 and fills `out_path` when a candidate exists, else 0 and leaves
 * `out_path` empty.  `tried` receives the candidates in the order they were
 * attempted, newline-joined, in the wording Python uses - it is only ever
 * interpolated into the "not found" message, but that message is asserted on.
 *
 * `bundled_rel` is the path of the bundled DLL relative to the repository
 * root, i.e. "tools/ngspice_dll/Spice64_dll/dll-vs/ngspice.dll".  Python
 * derives it from its own file location; C has no equivalent of __file__, so
 * the caller passes it (native/tools/parity_netlist.c passes the same string
 * Python computes).
 */
int wosp_resolve_ngspice_library(const char *explicit_path,
                                 const char *repo_root,
                                 const char *bundled_rel,
                                 char *out_path, size_t outlen,
                                 char *tried, size_t triedlen);

/*
 * One .tran argument converted to seconds.  Returns 1 and stores the value
 * when `token` is a SPICE number, 0 otherwise - which is Python's Optional.
 */
int wosp_spice_seconds(const char *token, double *out);

/*
 * Stop time of the deck's .tran card.  Returns 1 and stores it, or 0 when the
 * deck has no .tran card OR the card's stop time is not a SPICE number.
 *
 * Faithfully as buggy as the original: the FIRST .tran with at least three
 * fields decides, and a malformed stop time returns 0 without looking at any
 * later .tran card.
 */
int wosp_find_tstop(const char *const *lines, size_t n, double *out);

/*
 * Classify the output of one ngspice call.  Returns 1 and fills `out` with
 * the joined failure report, or 0 when ngspice reported no failure.
 *
 * `lines` must be ONLY the output produced by the call being checked.
 * `has_tstop`/`tstop` are Python's Optional[float]: has_tstop == 0 means
 * "no transient known", which fails closed.
 */
int wosp_failure_report(const char *const *lines, size_t n,
                        int has_tstop, double tstop,
                        char *out, size_t outlen);

/*
 * Return `command` unchanged (stripped) when it is an allowed ngspice
 * command, else 1 with the reason in `err`.  Mirrors validate_cmd().
 */
wosp_nl_status wosp_validate_cmd(const char *command,
                                 char *out, size_t outlen,
                                 char *err, size_t errlen);

/*
 * Python's str.strip(): leading/trailing whitespace of any kind.  Provided
 * because several rules key off it and the tests assert on its result.
 */
void wosp_strip(const char *s, char *out, size_t outlen);

/* Python's str.lstrip(' \t') - ONLY spaces and tabs, unlike wosp_strip. */
void wosp_lstrip_sp(const char *s, char *out, size_t outlen);

/*
 * _strip_normalize(): CRLF -> LF, drop leading blanks, consume one '+'.
 * Always succeeds; `out` receives the normalised line.
 */
void wosp_strip_normalize(const char *line, char *out, size_t outlen);

/*
 * _is_banned_directive().  Sets *banned to 1 and fills `name` with the
 * directive (without its leading dot) when the line must be refused, else 0
 * with `name` empty.
 */
void wosp_is_banned_directive(const char *norm, int *banned,
                              char *name, size_t namelen);

/* _is_banned_cmd().  Same shape; `name` is the offending verb. */
void wosp_is_banned_cmd(const char *norm, int *banned,
                        char *name, size_t namelen);

/*
 * _sanitise_line(): the single choke point for untrusted netlist input.
 * On success `out` receives the normalised, rewritten line.  On rejection
 * `err` receives the full Python message, punctuation included.
 *
 * `depth` is the include-nesting depth (0 at the top level).
 */
wosp_nl_status wosp_sanitise_line(const char *line, int depth,
                                  char *out, size_t outlen,
                                  char *err, size_t errlen);

/*
 * _check_include_path().  Validates a .include/.lib/.inc target, scans the
 * file's own lines recursively, and returns the absolute path to rewrite the
 * netlist line with.  Rejections carry the Python message verbatim.
 */
wosp_nl_status wosp_check_include_path(const char *raw, const char *directive,
                                       int depth,
                                       char *out, size_t outlen,
                                       char *err, size_t errlen);

/* _scan_included_file(): apply the line rules to every line of a file. */
wosp_nl_status wosp_scan_included_file(const char *path, int depth,
                                       char *err, size_t errlen);

/*
 * load_circuit()'s deck preparation, minus the ngSpice_Circ call: sanitise
 * every non-blank line, insert the title comment when the deck does not
 * start with one, append ".end" when absent, and re-parse the stop time.
 *
 * The prepared lines are written into `arena` (one NUL-terminated string
 * each) and `out_lines[i]` points into it; `arena_len` bounds it and the
 * call fails with WOSP_NL_REJECTED if the deck does not fit.  Python has no
 * equivalent limit because it appends to a list of Python strings - this is
 * a C-shaped constraint, not a behavioural one, and the parity battery stays
 * far below it.
 *
 * Returns WOSP_NL_OK or WOSP_NL_REJECTED.
 */
wosp_nl_status wosp_prepare_deck(const char *const *lines, size_t n,
                                 char *arena, size_t arena_len,
                                 char **out_lines, size_t cap,
                                 size_t *out_n,
                                 int *has_tstop, double *tstop,
                                 char *err, size_t errlen);

/*
 * The message NgSpiceEngine.__init__ raises when nothing resolves, built
 * from the newline-joined `tried` list wosp_resolve_ngspice_library()
 * produced.  Included because it is the only place a caller sees the
 * candidates, and getting the wording wrong would hide which paths were
 * actually attempted.
 */
void wosp_missing_library_message(const char *tried,
                                  char *out, size_t outlen);

/*
 * Canonical form of a path: separators unified, "." and ".." collapsed, and
 * on Windows each component replaced by the name the filesystem actually
 * holds.  Python's os.path.realpath does the same, and the include tests
 * compare the rewritten line against it, so the two must produce identical
 * strings - not merely equivalent paths.
 */
int wosp_realpath(const char *path, char *out, size_t outlen);

/* The repository root, derived from this module's own location the way
 * Python derives PROJECT_ROOT from ngspice_wrapper.py's location - never
 * from the process working directory, so decisions do not move with cwd.
 * Returns 1 on success. */
int wosp_project_root(char *out, size_t outlen);

/* Set by wosp_set_project_root() so the parity harness and the test binary
 * can point at a repository root they choose, exactly as Python's is fixed
 * at import time by __file__. */
void wosp_set_project_root(const char *root);

#ifdef __cplusplus
}
#endif

#endif /* netlist.h */
