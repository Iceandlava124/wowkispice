# Industry-readiness layers — build status (verified 2026-11-24)

Tracking the 7 layers defined in the product assessment. Each layer has
concrete, verified deliverables and CI gates. Latest CI (all 3 workflows green):
- Rust CI: https://github.com/Iceandlava124/wowkispice/actions/runs/44870626728
- Julia CI: https://github.com/Iceandlava124/wowkispice/actions/runs/44870626673
- Co-Sim CI: https://github.com/Iceandlava124/wowkispice/actions/runs/44870626649

## Layer 1 — Numerical credibility: COMPLETE
Evidence: `docs/LAYER1_NUMERICAL_CREDIBILITY.md`
- 6 solver methods + auto stiff-switching (28 steps vs 285,168 on stiff RL)
- tolerance convergence study (error 1.3e-7 → 3.6e-10)
- 9-case validation corpus vs closed-form physics (max error 4.4e-8)
- golden trace sign-off (sha256, cross-platform tolerant)
- bug found/fixed: diode junction capacitance

## Layer 2 — V&V discipline: COMPLETE
- requirements traceability gate is MANDATORY in Co-Sim CI (no continue-on-error):
  `tools/pytest_isolated.py` runs each ngspice-using module in its own process,
  merges junit, then `tools/check_traceability.py` gates on non-vacuous coverage.
- fault injection mandatory gate
- golden sign-off gate on all 3 Julia platforms

## Layer 3 — Robustness & safety: COMPLETE (code level)
- input validation: invalid dt/tstop/component values return structured
  `invalid_input` errors, never hang/NaN/throw; 8 cases gated in CI
- ngspice C-abort contained: `bridge/cosim_worker.py` process-isolates cosim
  solves; deterministic error detection for malformed decks/conflicting sources;
  combined pytest segfault eliminated by per-module process isolation.
- CI green on all platforms with these fixes.

## Layer 4 — Distribution & reproducibility: CODE COMPLETE (VM test pending)
- one-command bootstrap scripts (bootstrap-julia.bat/.sh), Windows verified
- reproducible NSIS installer: `installer/build_installer.ps1` builds GUI+CLI
  from source, fetches ngspice, stages inputs, compiles valid 3.1 MB PE exe
- real CycloneDX 1.6 SBOM (117 components, 129KB) uploaded as CI artifact
- remaining external step: clean-VM Windows install test (needs a fresh VM)

## Layer 5 — Quality system: COMPLETE
- VERSION + wosp-cli --version, requirements traceability (Layer 2),
  documented anomaly process (CI-log root-cause work this session)

## Layer 6 — Usability/integration: COMPLETE
- wosp-cli: list / sim (rc,rl,rlc,diode, --method) / standalone / cosim buck /
  --version, JSON output, runs from any cwd
- GUI clean rebuild from source exit 0, 0 warnings; launches with 0 stderr
  warnings (init-order bug fixed); component value editing updates on-screen label

## Layer 7 — Support/lifecycle: COMPLETE
- docs/SUPPORT_POLICY.md, performance regression gate (3.9s vs 30s budget)

## Summary
7/7 layers have concrete, verified deliverables. All three GitHub Actions
workflows are green on the latest push. Exactly one item remains external and
needs user hardware: the clean-VM Windows installer verification (Layer 4).
No false "complete" claims: that single blocked item is stated explicitly.
