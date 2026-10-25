# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keep-a-changelog.com/).

## Unreleased

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
