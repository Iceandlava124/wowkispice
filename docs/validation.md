# Validation and tolerance policy

This document records the closed-form references and tolerances that the
co-simulation and ngspice tests assert against. Every tolerance below is justified
by the solver state it depends on; none of them is "whichever passes".

## 1. RC step: `v(t) = V0 * (1 - e^(-t / (R*C)))`

- `R = 1 kOhm`, `C = 1 uF` => `tau = 1.0 ms`, `V0 = 3.3 V`.
- Assertion points:
  - `v(tau) = V0 * (1 - 1/e) = 2.08599 V`
  - `v(5*tau) = V0 * (1 - e^-5) = 3.29612 V`
  - point-by-point RMSE across the whole transient.
- Tolerances:
  - `RMSE < 0.008 V`. ngspice's transient solver uses a relative tolerance
    (`reltol = 1e-3` in the default `tran`) and an absolute tolerance of
    `1e-12` on each node. A sub-millivolt RMSE is the direct, non-negotiable
    check that the C-API wrapper is reading the same vector the solver wrote.
  - `max |err| < 0.025 V`. Points near `t = 0` and near the fast-rising
    first-step are where the accumulator error concentrates; this caps the
    single worst point so a mean does not hide one bad step.
  - `v(tau)` within `delta = 0.015 V` of `2.08599 V`.
  - `v(5*tau) >= V0 * 0.990` (settling criterion).

These match the solver settings of `tests/test_ngspice_bridge.py` exactly; the
same justify-every-number rule is applied in `docs/validation.md` for the RLC
proofs (Section 2), `test_ngspice_dll_proof.py` (sections PROOF 1-3) and the
closed-loop tests (Section 3).

## 2. RLC underdamped: `wd`, `zeta`, `alpha`

For `R=1.6 O` `L=100 uH` `C=10 uF` driven by a 5 V step:

- `w0 = 1 / sqrt(L*C) = 31622.78 rad/s`
- `alpha = R / (2*L) = 8000 Np/s`
- `zeta = alpha / w0 = 0.2530`
- `wd = sqrt(w0^2 - alpha^2) = 30396.4 Np/s`
- `fd_expected = wd / (2*pi) = 4837.4 Hz`

Assertions:

- ringing frequency: the mean interval between successive peaks of the output
  equals `1/(2*half_period)`, and `|measured_fd - fd_expected| / fd_expected
  < RLC_FREQ_TOLERANCE` (= 3%).
- envelope decay: `alpha_meas = ln(a0/an) / (t0 - tn)` must match `alpha`
  within `RLC_ENVELOPE_TOLERANCE` (= 10%).

The frequency target is 3% because a `tran` solve with `tstep = 0.5 uS` and
`2 ms` of ringing has ~4000 samples per cycle at `fd_expected`; a 3% error is
larger than the solver's local truncation error and small enough that a real
phase error in the netlist would still be caught. The envelope target is 10%
because the decay is inferred from the first and last ringing peaks, where
small absolute errors in the peak amplitude translate into a larger fractional
error on the small early peaks.

## 3. Closed-loop control

The factory firmware `firmware/esp32_buck_controller/src/main.c` declares
`ADC_LOW_THRESHOLD 1995` and `ADC_HIGH_THRESHOLD 2030` and states in its own
comment that these are raw counts at the ADC pin, divider already folded in.
The deterministic contract:

- `low_counts == 1995`, `high_counts == 2030`, `low < high`.
- A 2:1 divider on the sense net is reflected in the counts, never applied a
  second time (`divider=1.0` for a pin-referenced sense net).
- The regulated output must sit on the target the firmware encodes
  (`3.2436 V` nominal).

`test_cosim_control.py` asserts these counts at the source level;
`test_closed_loop_buck.py` asserts the same counts in the mock controller, so
the two independent implementations cannot drift apart silently.

Tolerances:

- `|mean(vout) - 1.62| < 0.12 V` for the 1x-divider `vout` node (the output
  node the firmware regulates to `3.2436 V`, divided by 2 at the midnet).
- `|reg mean_error_counts| < 200 counts` (start-up transient) over the tail of
  the run.
- A 10x load sweep must hold the output inside `0.10 V` of target.
- Switching must be real: `switch_count > 20` in a 5 ms run, and the pin duty
  must decrease as the load is increased (a replayed waveform could not do
  this).

## 4. Edge-case and non-convergence policy

When ngspice reports `ngSpice_Command("run")` returning a non-zero code, no
matrix is solved, and no trace is produced:

- `run()` and `load_circuit()` must return the failure to the caller as a
  raised exception or a non-empty `warnings` list. They must not return a half
  solved plot.
- `probelist()`/`get_vector_array()` on a node that ngspice never computed must
  return `[]`, never `0.0` as the "answer".
- A netlist that goes singular or contains a parse error produces a
  deterministic error message naming the failing line. Tests asserting this
  belong in the fault layer with `pytest-timeout` so a hung solver cannot
  stall the suite.

## 5. Failure shapes that are NOT silent

All of the above is implemented in a way you can see in the tests: any path
that would otherwise return a tidy-looking zero must instead append a warning
or raise, and the test asserts the warning or the exception. A decorated zero
that passes a test is a test that is not reading the signal.

## 6. Convergence and failure marking

- `xfail(strict=True, reason="NOT IMPLEMENTED - <requirement>")` is used ONLY
  for requirements whose implementation is in flight and whose tests make a
  specific behaviour claim that the current code cannot yet make. A strict
  xfail that fails is reported as a failure, so it can never be used to hide a
  regression.
- `skip` is used only when the *environment* cannot provide a binary
  (QEMU, ngspice), and the reason names the missing binary explicitly.
  A skip must never hide a failure when the binary is present; the CI
  `--strict` marker gate makes that visible.
