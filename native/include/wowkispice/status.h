/*
 * status.h - status codes shared by every native module.
 *
 * Extracted from control_law.h when netlist.c needed a status of its own:
 * one library with two status enums would make every caller ask which one a
 * given function returns, and would let a control-law code be mistaken for a
 * netlist rejection at a call site that only checks for non-zero.
 *
 * Every failure also writes a human-readable message into the caller's `err`
 * buffer when one is supplied; the messages carry the same wording as the
 * Python exceptions they port, so a test can match on a substring of either.
 */

#ifndef WOSP_STATUS_H
#define WOSP_STATUS_H

typedef enum {
    WOSP_OK                   = 0,
    WOSP_ERR_INVALID_ARG      = 1,
    WOSP_ERR_KIND             = 2,
    WOSP_ERR_PIN              = 3,
    WOSP_ERR_SENSE_NET        = 4,
    WOSP_ERR_VHIGH            = 5,
    WOSP_ERR_VREF             = 6,
    WOSP_ERR_ADC_BITS         = 7,
    WOSP_ERR_DIVIDER          = 8,
    WOSP_ERR_TARGET           = 9,
    WOSP_ERR_HYSTERESIS       = 10,
    WOSP_ERR_THRESHOLDS       = 11,
    WOSP_ERR_CARRIER          = 12,
    WOSP_ERR_DUTY_GAIN        = 13,
    WOSP_ERR_FILE             = 14,
    WOSP_ERR_NO_CONSTANTS     = 15,
    WOSP_ERR_BAD_CONSTANTS    = 16,
    WOSP_ERR_PIN_DIVIDER      = 17,
    WOSP_ERR_NOMEM            = 18,

    /*
     * A policy refusal rather than a malformed argument: the netlist
     * sanitiser rejecting a banned directive, an include outside the
     * allowlist, or a command not on the verb allowlist.  The distinction
     * matters because these are EXPECTED outcomes of untrusted input, not
     * programming errors - a caller treats them as "refused", and the `err`
     * buffer says which rule fired.
     */
    WOSP_ERR_REJECTED         = 19
} wosp_status;

#endif /* status.h */
