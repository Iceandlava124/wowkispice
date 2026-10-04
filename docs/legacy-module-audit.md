# Legacy Module Audit

**Date:** 2026-10-04 · **Status:** current. Supersedes the 2026-10-03 draft,
which was a pre-cleanup proposal ("nothing deleted, nothing moved") and is no
longer accurate.

This records what the legacy generation of WOSP modules is, what happened to it,
and what is still outstanding. It exists so cleanup decisions are made from
evidence rather than from filenames that merely *look* old.

## Method

Every claim below is backed by a grep over first-party files only
(`bridge/*.py`, `bridge/*.resc`, `bridge/*.repl`, `ui/*.py`, `tools/*.py`,
`tests/*.py`, `*.bat`, `Dockerfile`, `docker-compose.yml`,
`.github/workflows/*.yml`, `README.md`). Vendored trees (`.venv/`,
`tools/renode/`) and build output are excluded.

## What the cleanup actually did

The UI polish pass acted on the 2026-10-03 audit and deleted the tkinter
generation outright rather than maintaining three parallel shells:

| Deleted | Replaced by |
|---|---|
| `ui/studio_app.py` (1,105 LOC) | the Qt editor; its qualification battery now sits under **Tools ▸ Qualification** (`bridge/industrial_verification.py`) |
| `ui/ltspice_workbench.py` (706 LOC) | `ui/schematic_editor.py` |
| `ui/dashboard.py` (388 LOC) | nothing — the metric cards were seeded from hardcoded literals, not measured values |
| `run_studio.bat`, `run_workbench.bat` | `run_editor.bat` |

That was ~2,200 LOC of parallel UI removed with **zero test deletions**: the
bridge modules underneath were kept, and the one capability worth keeping (the
fault-injection / temperature-corner qualification battery) was ported.

## 1. Still dead — no importer, no test, no launcher

### `bridge/circuit_stepper.py` (82 LOC)
Unchanged since the first audit. The only text matches anywhere are its own
docstring and two bullet points in `overnight/01-implementation-plan.md`, which
is a planning document, not an importer. No Python import, no test reference,
no launcher, no `__main__` guard — it is not runnable standalone.

**Still outstanding.** This is the one deletion the audit recommended and
nothing has actioned it.

## 2. Renode cluster — abandoned, retained for reference

Four files, 152 LOC. Nothing in the active editor or bridge core imports them.

| File | LOC | Referenced by |
|---|---|---|
| `bridge/renode_orchestrator.py` | 86 | `docker-compose.yml`, `.github/workflows/cosim-ci.yml` (both as subprocess argv) |
| `bridge/renode_adc_peripheral.py` | 36 | `bridge/esp32_buck.repl:18` as a *string*, not an import |
| `bridge/run_cosim.resc` | 12 | `bridge/renode_orchestrator.py:74` |
| `bridge/esp32_buck.repl` | 18 | `bridge/run_cosim.resc:6` |

`bridge/renode_adc_peripheral.py` is worse than unreferenced: it is not
importable. `import bridge.renode_adc_peripheral` raises
`NameError: name 'request' is not defined`, because `request` is injected by
Renode's peripheral loader. It is a paste-in desktop-script fragment, not a
module. Both it and `renode_orchestrator.py` now say so at the top.

**Why Renode was dropped**, established 2026-10-03 and confirmed since:
Renode cannot decode the Xtensa `entry` instruction, which appears 393 times in
an ordinary ESP-IDF build. It therefore executed *zero* instructions of this
firmware. The `--mode renode` path shells out to `tools/renode/renode.exe`,
which is gitignored and has never been run.

**The emulator target is now QEMU**, not Renode. `bridge/qemu_orchestrator.py`
boots the real `.elf` through ROM, second-stage bootloader and `app_main()` in
Espressif's QEMU. It is not coupled to ngspice, and the firmware completes 0
control-loop samples because that QEMU models no SAR ADC. See
`tools/qemu-patch/README.md` for the device model that would close that gap.

**A trap worth naming.** `renode_orchestrator.py --mode benchmark` does **not**
touch Renode. It branches straight to `bridge/mock_controller.run_closed_loop_simulation`,
a pure-Python closed loop. The filename implies emulator coverage that the
benchmark mode never provided. CI and `docker-compose.yml` both call only that
mode.

## 3. Still coupled — keep

| File | LOC | What depends on it |
|---|---|---|
| `bridge/studio_engine.py` | 653 | `bridge/industrial_verification.py:23`, `tests/test_studio_suite.py` (9 tests), `tests/test_sota_suite.py` (7 tests) |
| `bridge/industrial_verification.py` | 440 | `tests/test_industrial_verification.py` (5 tests) |
| `bridge/report_generator.py` | 178 | `tests/test_sota_suite.py` |
| `bridge/mock_controller.py` | 194 | `bridge/renode_orchestrator.py:27`, `tests/test_closed_loop_buck.py` (1 test), plus Docker and CI via `--mode benchmark` |

The blast radius is still **22 tests**. `ui/studio_app.py` and
`ui/ltspice_workbench.py` dropped out of this list because they are gone; their
bridge dependencies were kept deliberately.

**Known defect in `mock_controller.py`:** a module-level `engine` global is
shared across calls rather than being constructed per run. Unfixed, and it is
the module CI and Docker still exercise.

## Near-duplicates

| Pair | Evidence |
|---|---|
| `studio_engine.run_simulation` vs `measurements.fft_spectrum` | `bridge/studio_engine.py:205-208` inlines `np.fft.rfft` with an `np.hanning` window. `measurements.fft_spectrum` implements radix-2 with a **Blackman** window and parabolic peak interpolation. `studio_engine` does not import `measurements`. Two FFT implementations with different windows exist side by side. |
| `studio_engine.run_real_spice_bode` vs `analysis_runner.run_bode` | Two independent AC-sweep paths; only the latter backs the PyQt5 Bode tab. |
| `mock_controller.run_closed_loop_simulation` vs `cosim_runner.run_cosim` | Two closed-loop implementations — a Python `GetVSRCData` callback versus ngspice `external` sources. Only the second is wired into the active editor. |

## Isolation of the active core

`ui/schematic_editor.py` and `bridge/cosim_runner.py` import **nothing** outside
the active bridge modules (`ngspice_wrapper`, `cad_engine`, `control_law`,
`cosim_runner`, `measurements`, `gpio_model`, `serial_console`, `kicad_export`,
`analysis_runner`). The legacy generation is genuinely separable — at the cost of
the 22 tests and 2 launcher scripts listed above.

## Outstanding

| Item | Status |
|---|---|
| `bridge/circuit_stepper.py` (82 LOC, dead) | **Still not deleted** |
| `engine` module-global in `mock_controller.py` | **Unfixed** |
| Renode cluster (4 files, 152 LOC) | Retained deliberately; no code path reaches Renode |
| `tools/qemu-patch/` | **Uncompiled.** Applies cleanly to the pinned Espressif source, never through a compiler |