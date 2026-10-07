# SETUP.md — from a bare Windows PC to a working WOSP install

Written for someone who has never done any of this. Copy-paste each block in
order. Every command here was run and verified on the pilot machine
(Windows 11 + WSL2 Ubuntu, October 2026).

**Budget:** about 60–90 minutes the first time, most of it downloading
(~20 GB of disk: toolchains, ESP-IDF, QEMU source + build).

## What you are about to install

| Thing | Why you need it | Where it runs |
|---|---|---|
| WSL2 + Ubuntu | A real Linux inside Windows — everything gets *built* here | Windows |
| WOSP + Python env + ngspice | The app itself and its analog solver | Windows |
| PlatformIO | Compiles the ESP32 firmware | Windows |
| Espressif QEMU + the WOSP patch | The emulator that runs the firmware | WSL (Ubuntu) |
| Qucs-S *(optional)* | Schematic tool we studied for UI ideas — **not needed to run WOSP** | Windows |

**Prerequisites:** Windows 10 (21H2 or newer) or Windows 11, x64, admin
rights for the WSL install, internet, ~20 GB free disk.

---

## Part A — Install WSL2 + Ubuntu (~10 min)

Open **PowerShell as Administrator** and run:

```powershell
wsl --install -d Ubuntu
```

Restart the PC if it asks. When Ubuntu first opens, it wants a **Linux
username and password** — invent one; it is not your Windows login, and the
password will not echo while you type. That is normal.

Check it worked (in PowerShell):

```powershell
wsl -l -v
```

You want `Ubuntu` with **VERSION 2**. If you see VERSION 1:
`wsl --set-version Ubuntu 2`. If `wsl` is not recognised:
`wsl --update`.

Everything in Parts B and E happens **inside the Ubuntu window**.

## Part B — Linux build tools (paste into Ubuntu, ~5 min)

```bash
sudo apt update
sudo apt install -y build-essential ninja-build pkg-config git curl wget unzip \
  flex bison gperf cmake python3 python3-venv python3-pip \
  libglib2.0-dev libpixman-1-dev libgcrypt20-dev libslirp-dev \
  libffi-dev libssl-dev
```

Plain-English: the compiler and build tool (`build-essential`, `ninja`),
then the libraries QEMU compiles against (`glib`, `pixman`, `slirp`…), then
Python so QEMU's `configure` can build its own private meson. If you skip
this part, Part E fails with `glib-2.0 not found` or `libslirp.h: No such
file` — those names are your clue that a line above is missing.

## Part C — Clone WOSP, Python env, ngspice (Windows, ~5 min)

You need **Git** and **Python 3.11+** on Windows
(<https://git-scm.com>, <https://python.org> — accept "Add to PATH").

```powershell
cd $env:USERPROFILE
git clone <this repo's URL> PROJECT_WOWKISPICE
cd PROJECT_WOWKISPICE
powershell -ExecutionPolicy Bypass -File setup.ps1
```

`setup.ps1` creates `.venv`, installs `requirements.txt`, downloads the
ngspice DLL (4 MB, checksum-verified) into `tools/ngspice_dll/`, and proves
Python can bind it. It is idempotent — rerun it any time.

**First checkpoint** — the test suite:

```powershell
python tools\run_tests.py
```

Expect `257 tests passed, all suites green` and exit code 0. If it is not
green, stop and fix that before continuing — everything later assumes this
line.

## Part D — Build the ESP32 firmware (Windows, first run ~15-30 min)

Install PlatformIO with its official installer:

```powershell
python -c "import urllib.request; exec(urllib.request.urlopen('https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py').read())"
```

This creates `%USERPROFILE%\.platformio\` (its own Python env, `penv`).
If that download fails (some networks block `raw.githubusercontent.com`),
use the plain pip route instead: `python -m pip install platformio pyserial`
and swap `& "$env:USERPROFILE\.platformio\penv\Scripts\pio.exe" run` below
for `python -m platformio run`.
Then build:

```powershell
cd $env:USERPROFILE\PROJECT_WOWKISPICE\firmware\esp32_buck_controller
& $env:USERPROFILE\.platformio\penv\Scripts\pio.exe run -e esp32dev
```

First run downloads the Espressif toolchain + ESP-IDF (~1.5 GB) and
compiles. Success ends with `RAM: [...] Flash: [...]`.

Now merge the pieces into the one 4 MB flash image the emulator boots
(exact offsets come from PlatformIO's own `*-flash_args` files):

```powershell
$PIOENV = "$env:USERPROFILE\.platformio"
& "$PIOENV\penv\Scripts\python.exe" "$PIOENV\packages\tool-esptoolpy\esptool.py" --chip esp32 merge_bin -o .pio\build\esp32dev\qemu_flash.bin --flash_size 4MB --fill-flash-size 4MB 0x1000 .pio\build\esp32dev\bootloader.bin 0x8000 .pio\build\esp32dev\partitions.bin 0x10000 .pio\build\esp32dev\firmware.bin
```

**Checkpoint:** `.pio\build\esp32dev\qemu_flash.bin` exists and is exactly
**4,194,304 bytes**. (If you installed PlatformIO with `pip install
platformio` instead of the installer, `esptool.py` lives inside that Python
environment — adjust the paths.)

> Note for the curious: `pio` may not be on PATH after the installer; the
> full paths above always work. Add `%USERPROFILE%\.platformio\penv\Scripts`
> to PATH if you want a short `pio`.

## Part E — Build QEMU with the WOSP patch (Ubuntu, first run ~20-40 min)

Back in the **Ubuntu** window:

```bash
cd ~
git clone --depth 1 --branch esp-develop-9.2.2-20260417 https://github.com/espressif/qemu.git qemu-esp
cd qemu-esp
git rev-parse --short HEAD        # expect: 40edcca
```

Apply the WOSP patch (adjust `/mnt/c/Users/<you>/` to your Windows username):

```bash
patch -p1 < /mnt/c/Users/<you>/PROJECT_WOWKISPICE/tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch
```

- `patching file ...` for **6 files** = good.
- `previously applied` = your tree already has it; continue.
- `Hunk ... FAILED` = wrong source version — recheck the tag/`40edcca`.

Configure and build — **exactly** these flags (copy-paste matters here):

```bash
./configure --target-list=xtensa-softmmu --disable-docs --disable-gtk --disable-sdl --disable-vnc --disable-spice --enable-slirp
ninja -C build
```

Why these: it is a **native** x86-64 build (the xtensa cross-compiler is for
firmware only — do not cross-compile QEMU), and `--enable-slirp` is required
because this fork compiles `net/slirp.c` unconditionally.

**Checkpoint:**

```bash
./build/qemu-system-xtensa --version     # QEMU emulator version 9.2.2
./build/qemu-system-xtensa -machine help | grep esp32   # esp32, esp32s3
```

Keep the source in your WSL home (`~/qemu-esp`) — building on `/mnt/c`
(Windows disk) works but is noticeably slower.

## Part F — Prove the whole install works (Windows, ~2 min)

```powershell
cd $env:USERPROFILE\PROJECT_WOWKISPICE
python tools\run_tests.py            # -> 257 tests passed, all suites green
python tools\demo_closed_loop.py     # -> PASS in ~40 seconds
```

The demo boots the real firmware in QEMU, waits for its control loop,
injects an ADC sample of 3456 through the QEMU monitor at the fixed path
`/machine/peripheral/sens`, and requires the firmware's own hysteresis to
flip the gate. Expected ending:

```
  gate                          : ON -> OFF
  panics                        : 0
PASS: the install boots the firmware, takes injected analog values and reacts.
```

Exit code 0 = your install works. It finds QEMU automatically (a sibling
`qemu-build` checkout or `~/qemu-esp`); if yours lives elsewhere, pass
`--qemu` or set `WOSP_QEMU` — both Windows-style (`C:\...\qemu-system-xtensa`)
and WSL-style (`/home/you/...`) paths work; a Linux QEMU on Windows is
launched through WSL automatically. The `task_wdt` warnings you may see in
longer runs are expected and harmless.

## Part G — Optional: Qucs-S (study material only)

WOSP runs fine without it. Qucs-S is the open-source schematic tool whose UI
grammar we deliberately imitate; it is installed only so humans can compare
screens, and its GPL-2.0 code **must never be copied into this Apache-2.0
repo** (see README → Third-party material). Install: download the Windows
installer from <https://qucs-s.github.io/> (Downloads), defaults are fine.
Anything you save under `docs/qucs-reference/` stays local — that folder is
gitignored on purpose.

## Part H — Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `wsl` is not recognised | WSL missing / old Windows | Part A; `wsl --update` |
| `Package libglib2.0-dev has no installation candidate` | apt not updated | `sudo apt update`, retry Part B |
| `glib-2.0 not found` during QEMU configure | Part B skipped | rerun Part B |
| `libslirp.h: No such file or directory` building QEMU | libslirp-dev missing or `--disable-slirp` used | `sudo apt install libslirp-dev`, rerun configure with `--enable-slirp` |
| `meson` version complaints | Ubuntu's meson is too old | Ignore — `./configure` builds its own (needs `python3-venv`) |
| `patch ... Hunk FAILED` | wrong QEMU source | Part E: check tag + `40edcca` |
| QEMU build painfully slow | source on `/mnt/c` | build from `~/qemu-esp` instead |
| `task_wdt: Task watchdog got triggered` in demo output | busy loop starves the idle task | Expected; non-fatal — demo still PASSes |
| `qemu-system-xtensa not found` (demo) | built elsewhere | `--qemu PATH` or `set WOSP_QEMU=...` |
| `flash image missing` (demo) | Part D not done (or `.pio` not built) | rerun Part D incl. the merge step |
| tests: `FileNotFoundError` on DLL | ngspice not fetched | rerun `setup.ps1` |
| `pio` not recognised | not on PATH | use the full path from Part D |
| QEMU configure: symlink / Developer Mode warning | Windows-only quirk | Harmless under WSL — continue |

## Where everything lives (default paths)

```
C:\Users\<you>\PROJECT_WOWKISPICE\        this repo (Windows)
  .venv\                                   Python env (setup.ps1)
  tools\ngspice_dll\                       ngspice DLL (setup.ps1)
  firmware\esp32_buck_controller\.pio\     firmware build + qemu_flash.bin
  tools\demo_closed_loop.py                install sanity check
\\wsl$\<distro>\home\<you>\qemu-esp\       QEMU source (WSL)
  build\qemu-system-xtensa                 the emulator binary
C:\Users\<you>\AppData\Local\Temp\         demo serial logs (wosp-demo-*.log)
```

When all five checkpoints pass — tests green, firmware merged, QEMU
`--version` 9.2.2, demo `PASS` — your install is complete.
