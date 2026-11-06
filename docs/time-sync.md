# Time synchronisation contract

This document describes what the firmware-in-the-loop path actually does when
ngspice and QEMU are coupled. It is written from the code in
`bridge/binary_runner.py` and the measurements recorded in
`docs/CURRENT-STATUS.md` row R7. It does not claim hard lockstep: the two
processes remain loosely coupled.

## Who owns time

ngspice is the master clock. Every accepted transient timestep evaluates the
`external` source that represents the MCU pin, which calls
`run_binary_cosim`'s callback. QEMU never advances the SPICE timeline.

```
ngspice accepts a timestep
  -> read the sense node (pre-divider voltage)
  -> convert to ADC counts (v_pin = sense_net * divider, clamped)
  -> QemuMonitor.set_adc1_value(counts) over HMP
  -> wait for the firmware to act on the sample
  -> QemuMonitor.read_gate() -> 3.3 V / 0.0 V
  -> return that voltage to ngspice for this timestep
```

The sense conversion is `_adc_counts_from_voltage()`:

```
v_pin  = v_sense * divider
counts = round(v_pin / vref * (2**adc_bits - 1)), clamped to the ADC range
```

Defaults are the board values: `divider=0.5`, `vref=3.3 V`, `adc_bits=12`.
For the buck converter's 2:1 feedback divider, 3.3 V at `vout` is 1.65 V at
the pin and 2048 counts.

## Synchronisation modes

`run_binary_cosim(..., sync_mode=...)` selects how the callback waits between
injecting an ADC sample and reading the gate.

| Mode | Behaviour | Use |
| --- | --- | --- |
| `adaptive` (default) | Poll `read_gate()` every `sync_poll_interval` (5 ms) until three consecutive readings agree or `sync_poll_timeout` (100 ms) expires. | Normal runs; tolerates the firmware's 16x oversampling and host scheduling jitter. |
| `fixed` | Sleep `sync_poll_timeout`, then read the gate once. | Deliberate fixed-delay experiments. |
| `none` / `off` | Read the gate once with no delay. | Diagnostics only; expect stale gate values. |

An unknown mode is reported in `run.warnings` and falls back to `adaptive`
rather than being accepted silently.

## Measured latency (R7)

From `tools/loop_repeat.py`, 10 consecutive runs against the patched QEMU and
the shipped firmware (`docs/CURRENT-STATUS.md` R7):

- Gate-flip time after injection, n=30: min 0.0203 s, mean 0.0217 s,
  p50 0.0205 s, p95 0.0218 s, max 0.051 s. **Observed bound: <= 0.051 s.**
- `read_gate` HMP round trip: mean 33.7 ms, p50 40.3 ms, p95 50.5 ms,
  max 71.2 ms (n=617). A later busy-host re-measurement saw a 550 ms outlier,
  so this is a typical range, not a hard real-time guarantee.
- `set_adc1_value` HMP round trip: mean 14.7 ms, p50 10.4 ms, p95 31.2 ms,
  max 40.4 ms (n=40); one cold-start run had a 4.85 s first-call outlier.

The harness treats the adaptive timeout as a fallback, not a deadline: if the
firmware does not settle, the callback returns the last reading and the run
continues. Communication failures are counted and reported in
`run.warnings`; they are not silently swallowed.

## Limits

- QEMU runs the firmware asynchronously under TCG at roughly real-time speed.
  There is no CPU-stepping control, so a timestep does not guarantee that the
  firmware executed exactly once.
- The firmware oversamples the ADC 16x, so a single injection can take several
  firmware loop iterations to change the gate.
- `adaptive` polling reads the gate repeatedly; its cost is visible in the
  latency numbers above and should be included in any timing budget.
- The path is validated by unit/double tests on every gate run and by real
  QEMU contract tests when a patched binary is available. It is not a
  substitute for measuring the final board.

## Reproducing the measurement

```powershell
# Real emulator contract tests (needs a patched qemu-system-xtensa)
tools\run_emulator_tests.ps1

# Ten-run gate-flip/latency loop against the shipped firmware
.venv\Scripts\python.exe tools\loop_repeat.py
```

Both commands report their own warnings; a missing `WOSP_QEMU` or firmware
image is an error, not a skipped pass.
