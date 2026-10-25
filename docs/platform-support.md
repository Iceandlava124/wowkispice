# Platform and resource support

This matrix records what actually runs on this machine, not what someone
*hopes* will run. The operational test is `python tools/run_tests.py`
(exits 0) and the boot check from `docs/toolchain.md` §6.

Legend: **CONFIRMED WORKING** / **CONFIRMED BROKEN** / **UNVERIFIED** /
**LATENT RISK** (the item is likely fine but has not been exercised).

| Component | Linux (this host) | macOS (arm64) | Windows native | WSL2 | Docker |
|---|---|---|---|---|---|
| Python bridge (stdlib + numpy/pytest) | **CONFIRMED WORKING** (Python 3.12.10, pytest 9.1.1) | not exercised | not exercised | not exercised | — |
| ngspice bridge (Windows DLL path) | **CONFIRMED WORKING** — the three physics proofs pass on this host (`tools/prove_physics_engine.py`, `tests/test_ngspice_dll_proof.py`) | — | **CONFIRMED WORKING** (bundled DLL, for .dll proofs) | — | — |
| ngspice bridge (system ngspice.so) | not exercised (no system ngspice installed) | — | — | — | — |
| Patched QEMU (`esp32_sens`) | **UNVERIFIED** — no Espressif QEMU, no `esp-develop-9.2.2-20260417` checkout, no IDA/AVR cross tools in this environment | — | Windows native: WSL2 only | **LATENT RISK** — Windows build tooling may be needed (see notes) | not exercised |
| Firmware build (`pio run --environment esp32dev`) | **UNVERIFIED** — PlatformIO 6.2.0 present, `pio run` starts but the FreeRTOS/DHCP compile fills a 4-core box in ~2 min; the fast path is blocked (see §Notes) | — | — | — | — |
| Firmware boot to `app_main` under patched QEMU | **UNVERIFIED** — because the QEMU and firmware builds are not present here | — | — | — | — |
| Full co-sim loop (ngspice ↔ QEMU ADC | GPIO) | **UNVERIFIED** | — | — | — | — |
| Self-check + test runner | **CONFIRMED WORKING** | — | — | — | — |

## What is and is not on this machine

* **ngspice (`.dll` for the physics proofs).** The windows DLLs, the
  `libomp140.x86_64.dll`, `samplerate.dll`, `sndfile.dll` and
  `ivlng.dll` live in `tools/ngspice_dll/`; the original 7z that holds the
  real DLL is `tools/ngspice-47_dll_64.7z`. The physics proofs are
  **CONFIRMED WORKING**.
* **Linux host ngspice.** Not installed; `find / -name ngspice` shows only
  the source tars and the extracted `tools/ngspice/` tree. If you need the
  system `ngspice` path for `bridge/ngspice_wrapper.py` resolution, install
  it and re-run the proofs; the wrapper already tries
  `WOSP_NGSPICE_LIB` before the bundled DLL.
* **QEMU.** Not installed anywhere in this environment. `which
  qemu-system-xtensa` returns nothing; Docker has a client (29.8.2) but no
  reachable daemon (error `failed to connect to the docker API at
  npipe:////./pipe/dockerDesktopLinuxEngine`), and `wsl --list --verbose`
  shows no distros installed. Consequently §6 of `docs/toolchain.md` is
  **UNVERIFIED** everywhere on this machine.
* **Python.** 3.12.10 in `.venv`; pytest 9.1.1; numpy 2.5.4; matplotlib
  3.11.2; PyQt5 5.15.11; pyqtgraph 0.14.0; pypdf 6.21.2.
* **CI.** `.github/workflows/cosim-ci.yml` exists but has never been
  executed on this checkout. The CI matrix rows that depend on QEMU and
  the ESP-IDF toolchain are therefore **UNVERIFIED**.

## Minimum requirements (from measurements)

The project's own measurement budget is the self-check + test runner on a
4-core, 16 GB box. The Firmware build is the first step whose cost is not
known (the toolchain and IDF are downloaded by PlatformIO); the ngspice
`.dll` proofs on this host take under a second of wall time. No minimum
spec is recorded yet because the firmware build has not completed here.

## Windows / macOS / WSL2 notes

* Windows native runs the Python bridge only (no Linux `.so` resolution
  path; the Windows DLL path is the one that works).
* macOS: nothing run yet. The same scripts should run unchanged; only the
  interpreter path and the ngspice resolution differ.
* WSL2: the recommended path for the full loop. The QEMU build, the
  firmware build and the boot test all need a Linux toolchain; Docker is
  optional.
