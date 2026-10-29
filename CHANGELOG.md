# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keep-a-changelog.com/).

## Unreleased

### Scorecard session (2026-10-28 / 2026-10-29)
- `tools/check_traceability.py` rewritten: parses the real 4-column
  requirements table and hyphenated IDs, unions source `req` markers with
  junit, and still fails on zero requirements or zero marked tests.
- CI (`.github/workflows/cosim-ci.yml`) now triggers on `baseline-fix`,
  with `tests/test_ci_workflow.py` asserting the YAML and the branch.
- `bridge/ngspice_wrapper.py`: failed analyses raise; transient runs that
  finished are not raised on (R5), on top of the verb allowlist guard (R4).
- Security: tracked-file user-path pattern tightened and home paths
  redacted; licence text for ngspice/PyQt5/QEMU quoted from files into
  `THIRD_PARTY_NOTICES.md`; `pyproject.toml` licence matches `LICENSE`.
- Docs reconciled to measured output: README, SETUP, ROADMAP,
  PROJECT_STATUS, requirements.md/requirements-matrix (SOL-01 retired on
  gate-flip evidence), plus `docs/REVIEW_BRIEF.md` for the human review.
- `.gitattributes` gains `*.c`/`*.h` LF rules; `tools/agentlog.ps1` records
  exact exit codes (PS 5.1 `-Command` collapse fixed).
- Tests: +`test_ci_workflow.py`, `test_tool_fixes.py`,
  `test_adversarial_stress.py` and the `req` marker set; suite now
  488 passed / 3 skipped / 0 failed.

### Polish (Task 8)
- Added `docs/KNOWN_ISSUES.md` describing the remaining bridge/runtime issues
  and limitations in this phase.
- Added type hints and docstrings on public functions in `bridge/`.
- Added `.editorconfig` and a pyproject-equipped lint/format configuration
  (ruff + black).
- Standardized CLI entry-point messages; added `--help` text to every CLI
  entry point.
- Added `ngspice_bridge_router.py` as the canonical bridge entry point.
- Tidy the top-level layout and refreshed `.gitignore`.
- Added `CHANGELOG.md` with an "Unreleased" section.

## [1.0.0] - 2026-10-XX

### Added
- Apache-2.0 license.
- Self-check environment gate (`tools/selfcheck.py`).
- Co-simulation runner (`bridge/cosim_runner.py`) and model
  (`bridge/control_law.py`).
- Schematic editor UI and KiCad export.
- ngspice physics proofs (`tools/prove_physics_engine.py`,
  `tests/test_ngspice_dll_proof.py`) - three independent solver proofs.
- QEMU firmware-boot orchestrator and `esp32_sens` patch.

### Changed
- Terminology and file paths aligned across README, docs, and code.

[1.0.0]: https://github.com/PROJECT_WOWKISPICE/project/releases/tag/1.0.0
