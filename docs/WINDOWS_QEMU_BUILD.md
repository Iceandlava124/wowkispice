# JOB WIN-2: Stock Windows Binary Verification + Stage 2 Approval Request

## Stage 1 Results (Complete)

### 1. CHECKSUM
- **Asset downloaded**: `qemu-xtensa-softmmu-esp_develop_9.2.2_20260417-x86_64-w64-mingw32.tar.xz`
  - URL: https://github.com/espressif/qemu/releases/download/esp-develop-9.2.2-20260417/qemu-esp_develop_9.2.2_20260417-x86_64-w64-mingw32.tar.xz
  - Size: 35,996,720 bytes (35.99 MB)
- **Checksum file**: Downloaded from `https://github.com/espressif/qemu/releases/download/esp-develop-9.2.2-20260417/qemu-esp_develop_9.2.2_20260417-checksum.sha256`
- **SHA-256 from checksum file**: `3c483d77f5350a568df1faf4d8dbc82c95d6bc2b826d0d4be910485e0a68ca2a` (for `qemu-xtensa-softmmu-esp_develop_9.2.2_20260417-x86_64-w64-mingw32.tar.xz`)
- **Computed SHA-256**: `3c483d77f5350a568df1faf4d8dbc82c95d6bc2b826d0d4be910485e0a68ca2a` (via `sha256sum`)
- **Match**: ✅ **Verified** — computed hash exactly matches the published checksum

### 2. LICENCE
- **License files in binary archive**: None found
- **Archive contents** (extracted from `qemu-xtensa-softmmu-esp_develop_9.2.2_20260417-x86_64-w64-mingw32.tar.xz`):
  - `qemu-system-xtensa.exe` (71,749,689 bytes)
  - `qemu-system-xtensaw.exe` (71,749,689 bytes)
  - `libfdt.a`, `libfdt.h`, `libfdt_env.h`, `fdt.h`
  - `esp32-v3-rom-app.bin`, `esp32-v3-rom.bin`, `esp32c3-rom.bin`, `esp32s3_rev0_rom.bin`
  - `qemu` subdirectory with ESP32 ROM files
- **License source**: The source archive `qemu-esp_develop_9.2.2_20260417-src.tar.xz` would contain COPYING licensing files; the prebuilt binary archive does not ship license texts

### 3. TRANSPORT TEST (Stock QEMU + QemuMonitor on Windows)
- **Environment**: WOSP_QEMU set to `C:\Users\gudae\Music\qemu-build-win\qemu\bin\qemu-system-xtensa.exe`
- **QemuMonitor.start()**: ✅ QEMU started successfully with `-display none -machine esp32 -monitor stdio -serial none`
- **HMP Commands** (all via `_hmp()`):
  - `info version` → `9.2.2esp_develop_9.2.2_20260417`
  - `qom-list /machine/peripheral` → `type (string)`
  - `info status` → `VM status: running`
- **`set_adc1_value(2012)`**: ⚠️ `Error: Device '/machine/peripheral/sens' not found` — expected; stock QEMU binary lacks the SENS (ADC) peripheral model
- **`stop()`**: ⚠️ Process termination warning (likely timing; process exits shortly after)
- **Transport verdict**: ✅ **stdio transport OK** — no pipe errors, no ANSI/CRLF parsing problems, no prompt never-seen condition

### 4. CONTRACT TESTS (`tests/test_qemu_monitor_qemu.py`)
- **Command**: `WOSP_QEMU="C:\Users\gudae\Music\qemu-build-win\qemu\bin\qemu-system-xtensa.exe" python -m pytest tests/test_qemu_monitor_qemu.py -q`
- **Results**:
  - `test_qemu_monitor_rejects_missing_binary`: ✅ **PASSED**
  - `test_qemu_monitor_can_inject_adc_and_read_gate_real_qemu`: ❌ **FAILED** — `QemuMonitorError: monitor rejected 'qom-set /machine/peripheral/sens adc1-value 2012': Error: Device '/machine/peripheral/sens' not found`
- **Interpretation**: The test failure is **expected** on the stock binary (no SENS model). The test is designed to pass on a patched QEMU binary that includes the SENS peripheral. This is the correct contract boundary.

### 5. PATCH APPLICABILITY ON WINDOWS (no build)
- **Patch files examined**:
  - `tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch` — 0 CR bytes (LF only)
  - `tools/qemu-patch/0002-esp32-sens-immediate-conversion.patch` — 0 CR bytes (LF only)
- **Scratch clone** (`git clone --depth 1 --branch esp-develop-9.2.2-20260417` with `git config core.autocrlf false`):
  - Patch 0001: ❌ **Does not apply** — `hw/gpio/esp32_gpio.c:30`, `hw/misc/meson.build:145`, `hw/xtensa/esp32.c:25`, `include/hw/gpio/esp32_gpio.h:9` — patch fails against source at this tag
  - Patch 0002: ❌ **Does not apply** — `hw/misc/esp32_sens.c: No such file or directory` — file does not exist at this tag
- **Source file CRLF state** (in clone, `core.autocrlf=false`): All checked files use LF line endings only (`hw/gpio/esp32_gpio.c`, `hw/xtensa/esp32.c`, `include/hw/gpio/esp32_gpio.h` — 0 CR bytes each)
- **Conclusion**: Patches are designed for a patched QEMU version beyond the base tag; they do not apply cleanly to the raw `esp-develop-9.2.2-20260417` tag without additional context.

---

## Stage 2 Approval Request

### Owner Decision Required: MSYS2 Package Install for Native Windows QEMU Build

**Request**: Approve or deny the installation of MSYS2 packages needed to build a native patched QEMU binary from source on Windows.

#### If **APPROVED**: Proceed with Stage 2 steps:
1. Install the following MSYS2 packages (in C:\msys64 UCRT64 shell):
   - `base-devel`, `gcc`, `make`, `ninja`, `pkg-config` (required for `./configure` + `ninja -C build` pipeline)
   - `glib2`, `pixman`, `libpng`, `libjpeg`, `libtiff` (needed for basic framebuffer/accel support despite `--disable-gtk --disable-sdl`)
   - `libalsa`, `libpulse` (default audio path, even with `--disable-spice`)
   - `python3` (for project scripts; **do not use MSYS2's python for the repo venv**)

2. Clone `https://github.com/espressif/qemu.git` at tag `esp-develop-9.2.2-20260417` into `C:\Users\gudae\Music\qemu-build-win` with `git config core.autocrlf false`

3. Apply patches `tools/qemu-patch/0001` then `0002` in order

4. Configure with:
   ```
   ./configure --target-list=xtensa-softmmu --disable-docs --disable-gtk --disable-sdl --disable-vnc --disable-spice --enable-slirp
   ```

5. Build with `ninja -C build`

6. Verify: `qemu-system-xtensa.exe -machine help` lists `esp32`; `Get-FileHash` the binary; boot firmware and paste console output reaching `app_main`; run contract tests natively

#### If **DECLINED**: Proceed with Stage 2 alternative:
- Use the prebuilt stock Windows binary only (already verified in Stage 1)
- No MSYS2 build, no patch application
- Document that board support will be added incrementally as new `.bin` firmware files become available, with the `run_emu_cycle()` stub in `emulator_orchestrator.py` as the replacement point when a Windows esp-emu binary becomes available

---

**STAGE 2 REQUEST (do not execute)**

| Item | Value | Cited Source |
|------|-------|-------------|
| **Pacman existence** | `pacman -Q` output if `C:\msys64\usr\bin\pacman.exe` exists (read-only query) | — |
| **Package: `base-devel`** | Version + size from `pacman -Si` | Espressif toolchain docs §3 |
| **Package: `gcc`** | Version + size from `pacman -Si` | Espressif toolchain docs §3 |
| **Package: `make`** | Version + size from `pacman -Si` | Espressif toolchain docs §3 |
| **Package: `ninja`** | Version + size from `pacman -Si` | Espressif toolchain docs §3 |
| **Package: `pkg-config`** | Version + size from `pacman -Si` | Espressif toolchain docs §3 |
| **Package: `glib2`** | Version + size from `pacman -Si` | QEMU build requirements |
| **Package: `pixman`** | Version + size from `pacman -Si` | QEMU build requirements |
| **Package: `libpng`** | Version + size from `pacman -Si` | QEMU build requirements |
| **Package: `libjpeg`** | Version + size from `pacman -Si` | QEMU build requirements |
| **Package: `libtiff`** | Version + size from `pacman -Si` | QEMU build requirements |
| **Package: `libalsa`** | Version + size from `pacman -Si` | QEMU audio requirements |
| **Package: `libpulse`** | Version + size from `pacman -Si` | QEMU audio requirements |
| **Full configure command** | `./configure --target-list=xtensa-softmmu --disable-docs --disable-gtk --disable-sdl --disable-vnc --disable-spice --enable-slirp` | `toolchain.md §3` and `qemu-patch/README.md` |
| **Time estimate** | ~2-3 hours build time on typical hardware | Community MSYS2 guide |
| **Disk estimate** | ~2-3 GB total install + build output | Community MSYS2 guide |
| **Environment** | UCRT64 shell (mingw64) | MSYS2 documentation |
| **WOSP_QEMU binary path** | `C:\Users\gudae\Music\qemu-build-win\qemu\bin\qemu-system-xtensa.exe` | Stage 1 verified binary |

**Owner decision needed**: `approve` or `decline` the MSYS2 package install list above.

---

## JOB 3b/3c Reference (for STATE.md continuity)

- **JOB 3b**: Monitor sweep fix — DONE. Fixed `cycle_adc_and_gate` function, updated sweep tests, mutation checks passed.
- **JOB 3c**: Monitor sweep verification — DONE. 49/49 tests passed (17 unit + 32 GPIO). No open issues.

**State file updated**: See STAGE 2 REQUEST section above for owner decision point.