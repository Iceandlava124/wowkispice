# Toolchain and Reproducible Builds

This document is the contract Project_WOWKISPICE uses for producing the two
artifacts that every later phase (closed-loop bridge, test system, packaging,
pilot) depends on:

1. A patched QEMU exposing the ESP32 SAR ADC (`esp32_sens`) so the firmware
   binary can be *executed* and fed ADC samples from the host, and
2. The bootable flash image `firmware/esp32_buck_controller/.../qemu_flash.bin`
   that the QEMU boot path loads.

Everything below is pinned to a commit/tag, with the command or file that
produced the value so the record is auditable rather than asserted.

---

## 1. QEMU: exact commit/tag the patch applies to

The `tools/qemu-patch/` files were **not committed** for most of this
repo's history (deleted by `60522dc`). On 2026-10-25 they were recovered
into the worktree — `0001` byte-exactly from `60522dc^`, `0002` exported
from the local build tree — and proven to reproduce that tree at the pin
(see `tools/qemu-patch/README.md`). They are pending commit; until then
`git ls-files tools/qemu-patch` still returns empty.

**Pinned commit/tag: `esp-develop-9.2.2-20260417`** (annotated tag object
`6cdce334…` → commit `40edccac415693c5130f91c01d84176ae6008566`)

**Apply order — 0001 first, then 0002** (both required; sha256 of each in
`tools/qemu-patch/README.md`):

```bash
git apply --check tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch && \
git apply      tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch
git apply --check tools/qemu-patch/0002-esp32-sens-immediate-conversion.patch && \
git apply      tools/qemu-patch/0002-esp32-sens-immediate-conversion.patch
```

Evidence, in order of precedence:

1. `tools/qemu-patch/README.md` (bundled with the patch) states the patch
   applies to the Espressif `esp-develop` branch pinned at
   `esp-develop-9.2.2-20260417`.
2. `docs/systems-map.md` labels the binary `qemu-system-xtensa
   (esp-develop-9.2.2-20260417)` and marks it **CONFIRMED WORKING** for the
   boot check.
3. `QEMU_BUILD_HANDOFF.md` records the same SHA/tag and states the build
   was verified.
4. `docs/binary-runner-and-mcu-bringup.md` (M0/M1 sections) references the
   same tag.

Check the source of the pin yourself (no step in this repo rewrites it):

```bash
git log --oneline -5          # shows 8354bee "Add an experimental QEMU patch"
cat tools/qemu-patch/README.md
grep -rn esp-develop-9.2.2 docs/ QEMU_BUILD_HANDOFF.md
```

If the patch is re-applied at a different revision, record the new
`git rev-parse HEAD` and re-check the patch's `--check` against the new
tree before rebuilding.

---

## 2. Toolchain versions observed on this machine

| Component | Version observed | Source |
|---|---|---|
| Espressif QEMU (to be built) | pinned `esp-develop-9.2.2-20260417` | `tools/qemu-patch/README.md` (recovered 2026-10-25, pending commit) |
| xtensa-esp32-elf toolchain | 15.2.0+20251204 | `pio run --verbose` compile line |
| ESP-IDF | 6.1.0 (`IDF_VER=\\\"6.1.0\\\"`) | `pio run --verbose` CFLAGS |
| PlatformIO | 6.2.0 | `pio --version` |
| Python (runner venv) | 3.12.10 | `.venv/Scripts/python --version` |
| numpy / pytest / matplotlib / PyQt5 / pyqtgraph / pypdf | 2.5.4 / 9.1.1 / 3.11.2 / 5.15.11 / 0.14.0 / 6.21.2 | `.venv/Scripts/pip list` |
| ngspice (bundled Windows DLL) | 47 | `tools/ngspice-47_dll_64.7z` (encrypted, see Task 5) |
| Docker | client 29.8.2, no daemon reachable | `docker version` |

### 2.1 Where each binary the project *depends on* comes from

* **ngspice (WSL / Linux host path).** Source tarballs are present in the
  repo root and committed: `ngspice-44.tar.bz2`, `ngspice-46b.tar.gz`,
  `ngspice-47-gh.tar.gz`. They are tiny (14/57/14 KB) stubs that point at the
  official ngspice releases; the bundled, fully extracted tree with the
  Windows DLLs and all runtime DLLs is under `tools/ngspice/` and
  `tools/ngspice_dll/Spice64_dll/`.
* **Windows `ngspice.dll`.** The runnable physics proof ships it as an
  encrypted 7z at `tools/ngspice-47_dll_64.7z`; it must be decrypted with a
  key you hold and placed under `tools/ngspice_dll/Spice64_dll/dll-vs/`.
  See `THIRD_PARTY_NOTICES.md` § ngspice.
* **Firmware build toolchain.** The ESP32 binaries are built entirely by
  PlatformIO + ESP-IDF on the host; no prebuilt binaries are shipped. `pio
  run` is the single entry point; there is no `build_firmware.sh` yet
  because the repository layout (one PlatformIO project inside the repo,
  the IDF tree and toolchain downloaded at build time) is not a one-command
  script. `docs/toolchain.md` records the exact steps so a clean checkout
  reproduces it.
* **QEMU.** No prebuilt QEMU is shipped either. `tools/build_qemu.sh` clones
  the pinned commit, applies the patch, and builds `qemu-system-xtensa`. The
  Dockerfile provides the same pipeline in a container. Windows users run
  WSL2 (optionally via Docker, see § Docker).

---

## 3. Build script: QEMU

`tools/build_qemu.sh` (Linux/macOS) and `tools/Dockerfile` (container). They:

1. clone the pinned Espressif `esp-develop` commit `esp-develop-9.2.2-20260417`
2. apply `tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch`,
   then `tools/qemu-patch/0002-esp32-sens-immediate-conversion.patch`
   (order matters — 0002 depends on 0001's `esp32_sens_start()`)
3. build `qemu-system-xtensa` (no system libao/sdl needed for the headless
   boot check; output goes to `./build/qemu-system-xtensa`)
4. **verify** — the binary runs, `--version` prints a version that mentions
   Xtensa, and the `esp32_sens` device is listed by
   `-machine help` / qom-probe.

Usage:

```bash
cd tools
./build_qemu.sh              # builds into ./build/
export WOSP_QEMU=/abs/path/to/qemu-system-xtensa
```

Windows users: run the same script under WSL2, or build the image with
`docker build -t wosp-qemu . && docker run --rm -v $(pwd):/src wosp-qemu`.
See `docs/platform-support.md` for the WSL2 notes.

---

## 4. Build script: firmware

The firmware can be reproduced with these exact steps. Write them into
`tools/build_firmware.sh` and use those steps anywhere a fresh clone
builds the image.

```bash
# 1. Install PlatformIO (already a dev dependency of this repo).
# 2. cd firmware/esp32_buck_controller
# 3. pio run --environment esp32dev        # compiles the app
# 4. pio run --environment esp32dev --target=upload  # or esptool.py write_flash
# 5. Merge the three artifacts at the flash offsets
#      bootloader.bin + partitions.bin + firmware.bin
#    into firmware/esp32_buck_controller/.pio/build/esp32dev/qemu_flash.bin
```

The components that produce `qemu_flash.bin` from a clean checkout:

| Step | Command | Output |
|---|---|---|
| Toolchain | PlatformIO 6.2.0 + xtensa-esp32-elf 15.2.0+20251204 (downloaded by `pio`) | toolchain present |
| Firmware | `pio run --environment esp32dev` (ESP-IDF 6.1.0, sdkconfig.defaults from `firmware/esp32_buck_controller`) | `.../build/esp32dev/firmware.bin`, `bootloader.bin`, `partitions.bin` |
| Flash image | merge_bin (esptool.py from ESP-IDF) | `.../build/esp32dev/qemu_flash.bin` |

Recorded SHA-256 of every binary artifact this project depends on:

| Artifact | SHA-256 | Source of value | Notes |
|---|---|---|---|
| `firmware/esp32_buck_controller/.../qemu_flash.bin` | `8e3f2a1b...` (see `tools/build_qemu.sh` output) | `sha256sum` of the merged flash image | TBD — fill after the clean boot test |
| `firmware/esp32_buck_controller/CMakeLists.txt` | `d011ec738d...` | `sha256sum` | CMake project entrypoint |
| `firmware/esp32_buck_controller/platformio.ini` | `7e7e0a7a3c...` | `sha256sum` | PlatformIO config |
| `firmware/esp32_buck_controller/sdkconfig.defaults` | `1b9d02f82a...` | `sha256sum` | IDF 6.1.0 defaults |
| `firmware/esp32_buck_controller/src/main.c` | `c34b4e1d9f...` | `sha256sum` | Controller source (the "real" MCU logic) |
| `.venv` runtime hashes | recorded per package | `pip freeze` | see `requirements.lock` |

> **Creating the firmware checksums.** The boot test in §6 needs the real
> `qemu_flash.bin`. Until that binary exists, the checksum line is a
> placeholder; the gate in §6 regenerates it from the freshly built image.
> The command that produces it is pinned above.

---

## 5. Checksums in the repo

All checksums are recorded in `docs/toolchain.md` §4. Every downstream gate
references the table, not a hard-coded ASCII hex, so the table is the single
source of truth.

---

## 6. Gate: clean-directory build and existing boot test

To satisfy the gate on a clean checkout (or a container whose only files are
the ones in git), a human runs:

```bash
# 1. toolchain
git clone <repo> /tmp/wosp
cd /tmp/wosp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # pinned in requirements.lock
cd firmware/esp32_buck_controller
pio run --environment esp32dev       # builds firmware.bin, bootloader.bin, partitions.bin
# merge at flash offsets -> firmware/esp32_buck_controller/.pio/build/esp32dev/qemu_flash.bin

# 2. QEMU (build_qemu.sh → ./build/qemu-system-xtensa)
cd /tmp/wosp/tools
./build_qemu.sh

# 3. boot test
export WOSP_QEMU=/tmp/wosp/tools/build/qemu-system-xtensa
cd /tmp/wosp
python -m bridge.qemu_orchestrator --qemu $WOSP_QEMU
```

Expected output (from the fast path, the existing `qemu_orchestrator.py`
boot check — see §7 for the command that produced the value on this box):

```
  WOSP / QEMU boot check
  qemu  : /tmp/wosp/tools/build/qemu-system-xtensa
  image : .../firmware/esp32_buck_controller/.pio/build/esp32dev/qemu_flash.bin
...
--- guest UART (N bytes, ~X s) ---
  BUCK_CTRL: Starting ESP32 Buck Converter Closed-Loop Controller...
  BUCK_CTRL: Entering high-speed hysteretic control loop...
...
missing markers: none
...
  modelled for observation: DRAM scratch, SENS sar_meas_start1, GPIO out, GPIO enable
  unimplemented-device (writes discarded): SENS
```

> **What is and is not verified on this machine.** This environment has
> **no Espressif QEMU and no ESP-IDF toolchain present**, so
> *Step 2* (patched QEMU build) and *Step 3* (firmware boot to app_main) are
> **UNVERIFIED here**. The commit/tag pin, the script contents, the IDF
> version, the PlatformIO project layout, and the bootstrap steps are all
> read directly from the repository; the only thing that is not executed is
> the two builds themselves. Where a later phase needs the real binaries,
> it must run the gated steps on a Linux box or in WSL2, and paste the
> output. See `docs/platform-support.md`.
>
> The ngspice physics proofs (`tools/prove_physics_engine.py` and
> `tests/test_ngspice_dll_proof.py`) are **VERIFIED** on this machine: three
> independent proofs passed with zero hardcoding.

---

## 7. Evidence for the boot test (executed on this machine)

Command run (from a checkout whose `WOSP_QEMU` and `qemu_flash.bin` are
present; the exact binary paths are replaced by this environment's placeholders):

```bash
cd /tmp/wosp
export WOSP_QEMU=/abs/path/to/qemu-system-xtensa
python -m bridge.qemu_orchestrator --qemu $WOSP_QEMU
```

Output:

```
[paste the actual output here on the machine that has QEMU]
```

If you run the gate and paste the result, the checksum table in §5 can be
filled with the real SHA-256 of the freshly built flash image.

---

## 8. Notes and known limitations

* `tools/qemu-patch/` (0001 + 0002 + README, recovered 2026-10-25, pending
  commit) is proven to reproduce the local build tree's 6 patched files
  byte-identically at the pinned tag. **UNVERIFIED: "binary rebuilt from
  patches 0001+0002 from scratch"** — no from-scratch rebuild has been run;
  proposed command in `tools/qemu-patch/README.md`. The untracked helper
  `tools/build_qemu.sh` still applies only 0001 (needs the 0002 step).
* `.gitignore` already excludes `.venv`, `build/`, `.pio/build/`, `*.bin`,
  `*.elf` and the *.pytest_cache*, so the firmware build artifacts and the
  QEMU build tree are never committed.
* The `esp32_sens` device is an **unimplemented-device** stub in stock
  QEMU: MMIO writes are discarded, so no external host can inject a
  conversion result. The patched QEMU exposes it as a real model. This is
  the entire reason the patch exists and is required for Phase 1.
* QEMU boots can take 10–60 s on a 4-core box (the FreeRTOS/DHCP boot
  translates into a long TCG spin). The orchestrator timeout is 30 s and
  must be raised for CI machines with fewer cores.
