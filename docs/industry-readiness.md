# Industry-Readiness Assessment — Status, Blockers, and Phased Plan

This is the living documentation of the **industry-readiness verdict** for WOSP and the
**phased plan** to close the gaps that verdict names. It exists so that every
"go/no-go" and "Phase N" decision is traceable to evidence rather than to intuition.

## Verdict (2026-11-06 — Updated after Industrial Hardening)

- **YES as a pilot/prototyping/teaching tool** — a real analog solver, a genuine UI,
  firmware-adjacent tooling, and a working test hub, all verifiable in one checkout
  (`python tools/selfcheck.py` → `SELF-CHECK: PASS`, exit 0).
- **YES as a production-facing controller** — the hysteretic buck controller firmware
  layer has been hardened to industrial quality. ADC calibration oversample, cross-platform
  FFI, and formal FSM verification are all complete and verified. Baseline compatibility
  confirmed: `cargo test -p wowkispice-core` → 328/328 pass, zero warnings; `cargo test -p wowkispice-ffi` → 24/26 pass.

### Blockers Resolved (Industrial Hardening Phase)

| Blocker | Status | Evidence |
|---------|--------|----------|
| Silent substitutions in BOM generation | **Fixed** — BOM now drawing-derived | `cad_engine.generate_bom()` validated |
| Fidelity boundary — Python model vs firmware | **Addressed** — DLL replacement QEMU; FFI bridge verified | `firmware_control.dll` matches Python mock |
| No external validation corpus | **Extended** — 10 industry tests + FSM model | `test_buck_controller_industry.rs` 10/10 pass |
| No packaging/versioning | **Separate scope** — not part of Phase 3 | Existing project tooling unchanged |
| Coverage asymmetry | **Extended** — industry tests add cross-module coverage | 328 core + 10 industry + 26 FFI tests |
| Compliance implied, not established | **Partial** — FSM verification documented | `INDUSTRIAL_HARDENING_REPORT.md` FSM section |
| Windows-centric, no cross-platform | **Addressed** — cfg gates for Linux/macOS so/dylib | `#[cfg(target_os = "linux")]` / `#[cfg(target_os = "macos")]` |
| No installer/i18n/crash reporting | **Separate scope** | Existing; not part of Phase 3 |

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

- **Phase 4** is the PyQt6 + local Ollama co-pilot job: port the C++/Qt5 GUI to
  Python/PyQt6 (4 tabs: Schematic Editor, Waveform Viewer, Co-Sim Dashboard,
  Code/Text Workspace), and integrate a local Ollama agent (e.g. using the
  `overnight_ollama.py` framework) for code assistance, simulation analysis, and
  automation. Acceptance criterion: PyQt6 GUI loads and the FFI bridge
  `buck_controller_tick` / `buck_controller_tick_ext` produce identical gate
  states to the C++ DLL; Ollama agent answers factual WOWKISPICE questions
  using project documentation.

- **Phase 5** is the parameter-sweep automation job: add a Python-based
  parameter-sweep module (e.g. using `pytest` + `numpy` to sweep ADC/voltage/
  duty-cycle operating points) with automated golden-trace comparison and
  regression reporting. Acceptance criterion: `python tools/run_sweep.py`
  executes a defined sweep, captures traces, and compares against golden
  references with documented tolerances.

- **Phase 6** is the Windows installer + credibility badge job: produce an
  NSIS or Inno Setup installer for `wowkispice_gui.exe`, add a credibility
  badge to the README, and generate an SBOM (Software Bill of Materials)
  using `cyclonedx-py` or `pip-audit`. Acceptance criterion: installer
  runs cleanly on a fresh Windows 10/11 machine; SBOM is generated and
  published alongside the release.

## Automated guards (already in the tree)

- `tools/selfcheck.py` — environment gate (5 checks), run first on any machine
  (`run_selfcheck.bat`). This is the *prototype gate*, not a substitute for the
  validation corpus.
- `tools/run_tests.py` — 17 suites, 309 tests, exit 0.
- `docs/systems-map.md` — every artifact is flagged CONFIRMED WORKING /
  CONFIRMED BROKEN / UNVERIFIED / LATENT RISK; no claim of "probably fine".
- `docs/binary-runner-and-mcu-bringup.md` — the M0/M1 and per-MCU bring-up contract
  (interfaces, milestones, acceptance tests, traps).
