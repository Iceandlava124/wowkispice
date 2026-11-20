# Industry-readiness layers — build status

Tracking the 7 layers defined in the product assessment. Each layer has
concrete, verified deliverables. Updated 2026-11-20.

## Layer 1 — Numerical credibility: COMPLETE
Evidence: `docs/LAYER1_NUMERICAL_CREDIBILITY.md`
- 6 solver methods + auto stiff-switching (28 steps vs 285,168 on stiff RL)
- tolerance convergence study (error 1.3e-7 → 3.6e-10)
- 9-case validation corpus vs closed-form physics (max error 4.4e-8)
- golden trace sign-off (sha256, cross-platform tolerant)
- bug found/fixed: diode junction capacitance

## Layer 2 — V&V discipline: COMPLETE (1 informational gate)
- non-vacuous requirements traceability checker wired in CI (informational
  until ngspice C-level abort fixed; checker runs and reports real gaps)
- fault injection is a mandatory CI gate
- golden sign-off gate on all platforms

## Layer 3 — Robustness & safety: COMPLETE (code level)
- input validation in Julia solver: invalid dt/tstop/component values return
  structured `invalid_input` errors, never hang/NaN/throw
- 8 validation cases gated in CI
- known limitation: ngspice C-level abort on some circuits is environment
  dependent (documented; not triggered by the validated Julia path)

## Layer 4 — Distribution & reproducibility: PARTIAL
- one-command bootstrap scripts (bootstrap-julia.bat/.sh), Windows verified
- real CycloneDX 1.6 SBOM (117 components, 129KB) uploaded as CI artifact
- remaining: clean-VM installer test (needs VM), signed artifacts

## Layer 5 — Quality system: IN PROGRESS
- VERSION file + CHANGELOG.md exist
- requirements traceability non-vacuous (Layer 2)
- remaining: per-release sign-off record, documented anomaly process

## Layer 6 — Usability/integration: PARTIAL
- wosp-cli working product (list/sim/standalone, JSON output, any cwd)
- remaining: GUI build/launch verification in this environment

## Layer 7 — Support/lifecycle: NOT STARTED
- support policy, deprecation policy, perf regression CI

## Honest summary
Layers 1-3 are substantively complete with verified evidence. The remaining
layers have concrete gaps that need resources (VM for installer, GUI runtime)
or are straightforward documentation/CI work. No false "complete" claims.
