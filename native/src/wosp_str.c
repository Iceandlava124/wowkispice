/*
 * wosp_str.c - shared string helpers.  See wosp_str.h.
 */

#include "wosp_str.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

void wosp_set_err(char *err, size_t errlen, const char *fmt, ...)
{
    va_list ap;
    if (err == NULL || errlen == 0) {
        return;
    }
    va_start(ap, fmt);
    vsnprintf(err, errlen, fmt, ap);
    va_end(ap);
}

void wosp_copy_str(char *dst, size_t dstlen, const char *src)
{
    size_t n;

    if (dstlen == 0) {
        return;
    }
    if (src == NULL) {
        dst[0] = '\0';
        return;
    }
    n = strlen(src);
    if (n >= dstlen) {
        n = dstlen - 1;
    }
    memcpy(dst, src, n);
    dst[n] = '\0';
}
