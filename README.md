# WOSP — mixed-signal virtual lab for power electronics

WOSP is a Windows-first schematic editor wired to the **real ngspice solver**,
with a control layer whose decision logic comes from **real ESP32 firmware
source**, plus an optional path to boot that firmware inside **Espressif's
patched QEMU**. The demo case is a buck converter whose hysteresis controller
(1995/2030 ADC counts) switches the gate.

Draw a schematic → simulate it in ngspice → attach a control law imported
from firmware source → let it drive the gate each timestep → inspect
waveforms → export to KiCad/SPICE/BOM/PDF.

## Status (verified 2026-10-24)

| Check | Result |
|---|---|
| `python tools/run_tests.py` | **363 passed, 2 skipped, exit 0** |
| `run_selfcheck.bat` (fresh clone) | **SELF-CHECK: PASS**, full suite gate green (173 s) |
| QEMU contract tests (`tests/test_qemu_monitor_qemu.py`) | **2 passed under WSL** against the built patched `qemu-system-xtensa` 9.2.2 (skipped/UNEXECUTED on the Windows side: the emulator is a Linux binary) |
| Automatic ngspice↔firmware loop | **not built** — each track works, the coupling between them is manual (see [docs/architecture.md](docs/architecture.md)) |

Honest boundaries (details in [PROJECT_STATUS.md](PROJECT_STATUS.md)):

- The solver, editor, co-simulation, measurements and exports are real and
  test-backed.
- Running the firmware under patched QEMU works **manually** (inject ADC
  with `qom-set`, read GPIO18 with `xp`); the automatic bridge is the open
  Phase-1 deliverable.
- This is a lab/teaching tool, not a calibrated instrument.

## Quick start (Windows, no firmware/QEMU needed)

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1   # venv, deps, ngspice DLL
.\run_selfcheck.bat                                  # -> SELF-CHECK: PASS
python tools\run_tests.py                            # -> 363 passed, exit 0
.\run_editor.bat                                     # open the schematic editor
```

Keys in the editor: click a part then the canvas to place; click pin-to-pin to
wire; **F2** simulate, **R** rotate, **Del** delete, **E** edit value,
**Ctrl+Z** undo.

The full install — firmware build, patched QEMU in WSL, boot demo — is
[SETUP.md](SETUP.md), copy-paste from a bare PC (60–90 min first time).

## Architecture

Two tracks that share the same numbers (full diagram in
[docs/architecture.md](docs/architecture.md)):

```
track 1 (automatic):  netlist -> ngspice -> bridge/ngspice_wrapper.py
                      -> bridge/control_law.py  (_to_counts, decide)
track 2 (manual):     firmware.elf -> patched QEMU (esp32_sens model)
                      -> qom-set adc1-value N  /  xp GPIO18 gate readback
```

Key modules: `bridge/ngspice_wrapper.py` (solver C-API), `bridge/control_law.py`
(hysteresis + ADC mapping, mirrors `firmware/`), `bridge/qemu_monitor.py`
(QMP/HMP injection), `bridge/qemu_orchestrator.py` (boot + console),
`bridge/firmware.py` (ELF/HEX parse), `ui/schematic_editor.py` (editor).

**Supported emulator: exactly one.** The firmware runs under Espressif's
patched QEMU built in WSL2 (SETUP.md Part E), and nothing else — there is no
native Windows emulator and no Rust emulator in this repo;
`bridge/emulator_orchestrator.py` is an unused stub with no binary behind it
(banner in its docstring, facts and the open owner decision in
[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)).

## Testing — two tracks

**Track A — product suite, no WSL needed** (the daily gate):

```powershell
python tools\run_tests.py                      # full suite; exit 0 only when green
python tools\run_tests.py --require-emulator   # same, but a skipped/absent emulator test = exit 3
.\run_selfcheck.bat                            # environment + solver + full suite in one command
```

The 2 qemu-marker contract tests skip by default with the **exact missing
item** in the reason (`WOSP_QEMU not set and no qemu-system-xtensa in PATH…`,
`WOSP_QEMU set but binary not found at <path>`, or `not running under Linux:
<path> is a Linux ELF…`) — labeled UNEXECUTED, never "passing". Default keeps
them visible-but-allowed; `--require-emulator` makes any such skip fail the
whole run.

**Track B — emulator contract** (needs the SETUP.md Part E QEMU build):

```powershell
powershell -ExecutionPolicy Bypass -File tools\run_emulator_tests.ps1
```

Prints which locator it used (`$env:WOSP_QEMU` first, else the documented
sibling `qemu-build` default), runs `tests/test_qemu_monitor_qemu.py` inside
WSL, prints the pytest summary, and exits non-zero if WSL or the binary is
missing or if **any test is skipped or fails** — it never reports success for
a skip. Verified on this box: **2 passed, 0 skips**.

The exact command it runs (kept identical here so doc and script agree):

```bash
wsl -- bash -lc "cd '/mnt/c/<home>/Music/PROJECT_WOWKISPICE' && WOSP_QEMU='/mnt/c/<home>/Music/qemu-build/qemu-esp_develop_9.2.2_20260417/build/qemu-system-xtensa' python3 -m pytest tests/test_qemu_monitor_qemu.py -v"
```

UI tests run headless via `QT_QPA_PLATFORM=offscreen`.

## Known limits

Tracked in [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md). The two that matter:

1. **PyQt5 must be ≥ 5.15.11** — 5.15.9 segfaults at import on Windows/Python
   3.12 (pinned in `requirements.txt` / `requirements.lock`).
2. **Emulator contract green under WSL, but the binary is not yet reproducible
   from tracked patches** — the contract tests pass under WSL via
   `tools\run_emulator_tests.ps1` (2 passed, 0 skips: one exercises the real
   emulator, one the missing-binary error path). The patched binary was built
   from a local source tree and is NOT yet reproducible from tracked patches
   (see [tools/qemu-patch/](tools/qemu-patch/) and
   [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)); no from-scratch rebuild has
   been verified.

## Docs

- [SETUP.md](SETUP.md) — bare PC → working install, step by step
- [PROJECT_STATUS.md](PROJECT_STATUS.md) — honest product map
- [docs/architecture.md](docs/architecture.md) — what is automatic vs manual
- [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) — open decisions and defects
- [docs/toolchain.md](docs/toolchain.md) — firmware/QEMU build gates

## Third-party material

- ngspice is **GPLv2+**; its Windows DLL ships encrypted in
  `tools/ngspice-47_dll_64.7z` and is unlocked by `setup.ps1`.
- Qucs-S (optional, study material only) is **GPL-2.0** — never copy its code
  into this Apache-2.0 repo.
- QEMU source is **GPL-2.0** and lives outside this repo (built in WSL).

## License

See [LICENSE](LICENSE).
