# Layer 1: Numerical Credibility — COMPLETE

Layer 1 establishes that the solver's numbers are trustworthy, not just that
tests pass. Status verified 2026-11-20.

## Gates (all enforced in Julia CI on Windows/Linux/macOS)

| Gate | File | Evidence |
|---|---|---|
| Solver methods | `test_parameters.jl` | 6 methods (tsit5, rosenbrock23, rodas5p, fbdf, vern7, auto) agree on RC closed-form within 2.3e-5 |
| Invalid method | `test_parameters.jl` | unknown method returns structured `invalid_method` error |
| Tolerance convergence | `test_parameters.jl` | error drops 1.3e-7 → 3.6e-10 as tol tightens 1e-3 → 1e-9 |
| Validation corpus | `validation_corpus.jl` | 9 cases (4 RC, 3 RL, RLC underdamped, diode) vs independent closed-form physics; max error 4.4e-8 |
| Stiff circuit | `test_stiff.jl` | stiff RL (tau=1us, 1000 tau span): auto solver 28 steps vs explicit Tsit5 285,168 steps; auto hits analytic exactly |

## Delivered capabilities

- **Auto stiff detection**: default method is `auto` = AutoTsit5(Rosenbrock23()), which
  switches to a stiff solver when needed. Proven 10,000x more efficient on stiff circuits.
- **Structured errors**: invalid solver methods no longer throw; they return a
  JSON error with `error_type=invalid_method`.
- **Method echo**: results include `method` and `algorithm` so callers see what ran.
- **CLI**: `--method` flag (default auto); all methods selectable from the command line.

## Bugs found and fixed during Layer 1

- **Diode physics bug**: the original diode ODE had no junction capacitance, so
  `dV/dt = current` (dimensionally wrong) and voltage ramped linearly instead
  of settling at `Vt·ln(1+Iin/Is)`. Added `C_j=1nF` charge-balance model.
  The validation corpus caught this — diode now matches analytic to 4.7e-15.
- **CLI CI assertion**: auto method changed final_vout from 2.399999e-1 to
  2.400000e-1; assertion widened to accept both.

## Known limitation (honest)

`cross_tool_validation.py` compares Julia vs ngspice on the same RC circuit. The
bundled Windows `ngspice.dll` segfaults on the transient (exit 0xC0000005) — the
same C-level abort seen in the Co-Sim CI. Therefore:
- It is a **manual tool**, run where a working system ngspice is available.
- It is NOT a CI gate, to avoid a flaky environment-dependent failure.
- Independent validation is provided instead by the closed-form corpus above,
  which is genuinely independent of the solver implementation.

## Next layer

Layer 2: Verification & Validation discipline — non-vacuous requirements
traceability and independent-review gates.
