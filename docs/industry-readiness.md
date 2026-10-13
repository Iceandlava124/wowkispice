# Industry-Readiness Assessment — Status, Blockers, and Phased Plan

This is the living documentation of the **industry-readiness verdict** for WOSP and the
**phased plan** to close the gaps that verdict names. It exists so that every
"go/no-go" and "Phase N" decision is traceable to evidence rather than to intuition.

## Verdict (2026-10-09)

- **YES as a pilot/prototyping/teaching tool** — a real analog solver, a genuine UI,
  firmware-adjacent tooling, and a working test hub, all verifiable in one checkout
  (`python tools/selfcheck.py` → `SELF-CHECK: PASS`, exit 0).
- **NO as a production engineering tool.** See the blockers below, each with evidence.

### Blockers, with evidence

1. **Silent substitutions** — `bridge/cad_engine.py::generate_bom()` returns a
   hardcoded reference BOM (ESP32-WROOM-32E $2.65, IRF540NPBF $0.72, …) regardless of
   what is drawn, and a user-drawn-but-empty schematic silently falls back to a
   legacy reference netlist. A simulation result can disagree with the drawing and
   nobody is told. Trust-killer.
2. **Fidelity boundary** — the loop is model-driven, not firmware-driven. The
   controller is a Python model whose three constants were scraped from C source
   (`bridge/control_law.py`); the real firmware binary executes only under QEMU and is
   not yet coupled to the solver (`docs/binary-runner-and-mcu-bringup.md` M0/M1).
3. **No external validation corpus** — only 2 physics proofs vs. commercial
   simulator references, no converged-edge-case policy, no declared tolerance/rounding
   policy for model outputs.
4. **No packaging/versioning** — no `pyproject.toml` or `setup.py`, no `__version__`,
   no release tags; `requirements.txt` uses `>=` only with no lockfile; a fresh-clone
   bootstrap runs an unpinned python venv; CI has never executed in this environment.
5. **Coverage asymmetry** — QEMU firmware-boot path has 0 tests, `studio_engine` has 9,
   `components_library` has 2, `industrial_verification` has 5. The self-check does not
   count as coverage of the simulator core.
6. **Compliance implied, not established** — the qualification battery is a self-check
   (DO-254/ISO 26262/IEC 61508 content exists in code, but no traceability, DO-330,
   TCL, SBOM, disclaimers, or audit trail); component library is reverse-engineered with
   no vendor models, tolerances, or corners.
7. **Windows-centric, no installer/i18n/crash reporting**, and the save format's version
   tag is written but `load_dict` does not validate/migrate it.

## Phased Plan

Acceptance criteria for each phase are stated as **checkable gates** (command +
expected output). They are the contract each phase must satisfy before the next
starts.

| Phase | Goal | Acceptance criterion (when `python tools/selfcheck.py` and `python tools/run_tests.py` pass) |
|---|---|---|
| **0 — Honest & installable** | Kill the silent substitutions; make a fresh clone install-and-verify | 1. `run_selfcheck.bat`/`selfcheck.py` prints `SELF-CHECK: PASS` on a fresh clone with a pinned venv + `requirements.txt` + lockfile; 2. `cad_engine.generate_bom()` returns a **drawing-derived** BOM (compare against the placed/schematic netlist) and never falls back to a legacy netlist silently (`--debug` dump equals the scaffold); 3. Commit and release tags exist (`pyproject.toml` + `__version__`, `1.0.0` shipped). |
| **1 — Engineering credibility** | Build the validation corpus and name the fidelity boundary | 1. `tools/benchmarks/` (or `tests/...`) holds a documented oracle set: RLC ringing frequency, divider semantics, step response against closed-form values, plus a convergence/edge-case policy for `run` failures; 2. `metrics['fidelity']` or a docs section states exactly what the model may be used for and what it may not (no model claims about the compiled firmware); 3. CI runs clean end to end on a fresh clone (workflow executed, not merely YAML-parsed). |
| **2 — Product hardening** | Turn the pilot into a usable engineering tool | 1. Binary runner M0/M1 complete and `TestBinaryRunner`-style tests green in the runner; 2. Save format validated on load with migration of field order/version (no silent reserialization); 3. Qual battery emits a traceable report (SBOM, TCL, DO-330-adjacent artifact) and the test suite asserts its presence; 4. Installer + cross-platform paths (setup.sh done, macOS tested, i18n/a11y baseline) all `CONFIRMED WORKING` in `docs/systems-map.md` flags. |
| **3 — Regulated workflows** *(optional, 3rd-party/academic scope)* | Enable formal qualification | 1. DO-330-style traceability matrix plus SBOM toolchain (e.g. `pip-audit` + CycloneDX) verified; 2. Pilot checklist run and recorded with evidence artifacts; 3. Release notes that quote the self-check verdict, test counts, and open defects for every tagged release. |

## Where the phases sit relative to existing artifacts

- **Phase 0** is mostly a cleanup + packaging job: the self-check exists and passes
  (this is the environment gate, not the engineering gate); the BOM and fallback
  fixes are straightforward edits; the lockfile/versioning work is the only new
  machinery.
- **Phase 1** is the engineering-credibility job that the binary runner (M0/M1, in
  `docs/binary-runner-and-mcu-bringup.md`) directly enables, plus the validation corpus
  and CI.
- **Phase 2** is the UI/tool/product job: QEMU integration, format migration, quality
  report artifacts, installer.
- **Phase 3** is optional and regulated-workflow scope; it needs an external
  certification authority and tooling that does not exist here.

## Automated guards (already in the tree)

- `tools/selfcheck.py` — environment gate (5 checks), run first on any machine
  (`run_selfcheck.bat`). This is the *prototype gate*, not a substitute for the
  validation corpus.
- `tools/run_tests.py` — 17 suites, 309 tests, exit 0.
- `docs/systems-map.md` — every artifact is flagged CONFIRMED WORKING /
  CONFIRMED BROKEN / UNVERIFIED / LATENT RISK; no claim of "probably fine".
- `docs/binary-runner-and-mcu-bringup.md` — the M0/M1 and per-MCU bring-up contract
  (interfaces, milestones, acceptance tests, traps).
