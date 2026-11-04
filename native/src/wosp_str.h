/*
 * wosp_str.h - string helpers shared by the native modules.
 *
 * Deliberately NOT under include/wowkispice/: these are implementation
 * details of the port, not API.  They live in one place because the modules
 * would otherwise each carry their own copy of a bounded copy and a
 * printf-shaped error writer, and the two copies would drift - the exact
 * failure mode this port exists to avoid.
 *
 * (They were first written as statics inside control_law.c.  A second module
 * needing them is what promoted them here.)
 */

#ifndef WOSP_STR_H
#define WOSP_STR_H

#include <stddef.h>

/*
 * Copy at most dstlen-1 bytes and always NUL-terminate.  Silently truncates
 * rather than failing: every caller is filling a fixed message buffer, and a
 * truncated message beats a corrupt one.
 *
 * Not strncpy(): that warns at -O2 ("output may be truncated") because the
 * truncation is by design, and no amount of care removes the warning while
 * the call still reads as a bounded copy.  A bounded memcpy says exactly what
 * happens and stays silent.
 */
void wosp_copy_str(char *dst, size_t dstlen, const char *src);

/* snprintf() into a caller-supplied error buffer, tolerating err == NULL. */
void wosp_set_err(char *err, size_t errlen, const char *fmt, ...);

#endif /* wosp_str.h */
