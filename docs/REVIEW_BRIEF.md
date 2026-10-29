# REVIEW_BRIEF.md — one page for the human reviewer (R12)

Purpose: an independent read of the core path — sanitiser, ADC conversion,
monitor, callback — plus how to reproduce every claim. Thirty to sixty
minutes. Evidence for everything cited lives in `docs/SCORECARD.md` and
`logs/activity.jsonl` (job labels `R*-01`/`R*-02`).

## What to read, and where

| Area | File | Lines |
|---|---|---|
| Netlist sanitiser (directive allowlist) | `bridge/ngspice_wrapper.py` | 469–560 (`ALLOWED_DIRECTIVES` 471, `ALLOWED_INCLUDE_DIRS` 492, `Cmd_ALLOWED` 513, `_is_banned_directive` 544) and `validate_cmd` 572; `cmd()` entry point 349 |
| ADC conversion (volts → counts) | `bridge/control_law.py` | 185–224 (`_to_counts`), hysteresis `decide` 226/286/320 |
| ADC conversion (divider, per step) | `bridge/binary_runner.py` | 18–23 (`_adc_counts_from_voltage`) |
| QEMU monitor (inject / read / lifecycle) | `bridge/qemu_monitor.py` | class 64, `start` 101, `set_adc1_value` 216, `read_gate` 231, reaper `_cleanup_all_monitors` 29 |
| Per-step callback (solver ↔ firmware) | `bridge/binary_runner.py` | `run_binary_cosim` 65, `sense` 182, `callback` 193–224 (`engine.set_vsrc_callback`), `_read_until_stable` 32 |

Supporting: `docs/requirements.md` (14 requirements, each mapped to an
executed test), `THIRD_PARTY_NOTICES.md` (quoted licences), and the two
open-defect files `docs/KNOWN_ISSUES.md` / `docs/SCORECARD.md`.

## Five questions for the reviewer

1. **Sanitiser:** is the directive allowlist (`ALLOWED_DIRECTIVES` +
   `ALLOWED_INCLUDE_DIRS` + `Cmd_ALLOWED`) fail-closed — i.e. can any
   directive or path reach `ngSpice_Command` without passing it, including
   through case tricks, comments or `.control` blocks?
2. **ADC conversion:** do `_to_counts` and `_adc_counts_from_voltage`
   implement the same divider arithmetic as the firmware's own reading of
   `main.c`, and are the boundary clamps (0 and 4095) correct on overflow
   and negative volts?
3. **Monitor:** when `set_adc1_value` or `read_gate` fails (broken pipe,
   timeout, QEMU gone), does the error surface to the caller as an
   exception with context, or can any path swallow it and continue?
4. **Callback:** in `run_binary_cosim`, can a callback exception or a
   stalled `_read_until_stable` hang the simulation forever, and are the
   hit count / gate flip assertions evaluated against real emulator output
   rather than cached state?
5. **Evidence discipline:** does anything in the scorecard's PASS rows rest
   on a mocked double where the row wording says "real" (the known
   doubles-based families are listed in `ROADMAP.md` §2.3)?

## How to run the tests

```powershell
# full gate (488 passed, 3 skipped expected; exit 0)
python tools\run_tests.py

# strict variant: any skipped contract test fails the run (exit 3)
python tools\run_tests.py --require-emulator

# focused suites for the four areas
python -m pytest tests\test_ngspice_sanitiser.py tests\test_adc_conversion.py -q
python -m pytest tests\test_qemu_monitor_unit.py tests\test_binary_runner.py -q

# environment + solver + full suite in one command
.\run_selfcheck.bat
```

## How to run the loop

```powershell
# Track B: contract tests against the real emulator inside WSL
powershell -ExecutionPolicy Bypass -File tools\run_emulator_tests.ps1

# install sanity demo: boots firmware, injects ADC 3456, expects a gate flip
python tools\demo_closed_loop.py
```

Track B needs the WSL build (SETUP.md Part E). The demo exits 2 with
`FAIL: qemu-system-xtensa not found` when no emulator is present — that is
the documented, measured behaviour (log #174/#180/#181).

R12 remains an owner-set row: record your answers to the five questions in
`docs/SCORECARD.md` under a dated section; the row passes only when you do.
