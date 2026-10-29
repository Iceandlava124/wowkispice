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

**Supported emulator: exactly one.** Anything that runs the firmware runs it
inside Espressif's patched QEMU, built in WSL2 (Part E below) — no other
emulator is supported. There is no native Windows emulator and no Rust
emulator in this repo: `bridge/emulator_orchestrator.py` is an unused stub
with no binary behind it (banner in its docstring, facts and the open owner
decision in `docs/KNOWN_ISSUES.md`).

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

**First checkpoint** — the environment, then the test suite:

```powershell
.\run_selfcheck.bat                  # deps + ngspice + a known solve + suites
python tools\run_tests.py            # suites only
```

Expect `SELF-CHECK: PASS` and `488 tests passed, 3 skipped (the UNEXECUTED
QEMU contract tests)`, both with
exit code 0. If it is not green, stop and fix that before continuing —
everything later assumes this line.

**Interpreter note (measured 2026-10-28):** `python` below must resolve to
the `.venv` interpreter. Where bare `python` is a system Python without
this project's packages (on this box: an MSYS2 CPython 3.14),
`python tools\run_tests.py` fails with 5 collection errors and a missing
timeout plugin. Use `.venv\Scripts\python ...` instead, or activate the
venv first (`\.venv\Scripts\Activate.ps1`).

### Two test tracks — which command covers what

| Track | Command | Covers |
|---|---|---|
| **A — product suite, no WSL** | `python tools\run_tests.py` | everything native Windows; the 3 qemu-marker contract tests skip as UNEXECUTED, each reason naming the exact missing item (unset `WOSP_QEMU` / bad path / Linux ELF on Windows) |
| **A — strict variant** | `python tools\run_tests.py --require-emulator` | same run, but a skipped or absent contract test fails the run (exit 3) |
| **B — emulator contract** (needs the Part E build) | `powershell -ExecutionPolicy Bypass -File tools\run_emulator_tests.ps1` | runs `tests/test_qemu_monitor_qemu.py` inside WSL; non-zero if WSL is missing, the binary is missing, or **any test is skipped or fails** |

Verified 2026-10-24 on this box: Track A default (363 passed, 2 UNEXECUTED
skips with exact-item reasons), Track A `--require-emulator` with no binary
configured (fails, as designed), Track B against the built
`qemu-system-xtensa` (2 passed, 0 skips).

Re-verified 2026-10-28 (job R9-01): Track A default -> **483 passed,
3 skipped** (`GATE: all collected tests passed`, two runs of 120.66 s and
186.13 s in `logs/out/00177.txt` / `00178.txt`); the 3 skips are the three
qemu-marker contract tests at `tests/test_qemu_monitor_qemu.py:78/105/117`
(`:117` is the third, added after the 2026-10-24 line above). Track A
`--require-emulator` -> **exit 3** with those skip reasons printed
(`logs/cmd/r9_exit3.py`, `logs/out/00179.txt`). `\.\run_selfcheck.bat` ->
`SELF-CHECK: PASS` (`logs/out/00173.txt`). Track B not re-run at that point.

Re-verified 2026-10-29: Track A default -> **488 passed, 3 skipped**,
exit 0 (log #226); Track A `--require-emulator` -> **exit 3** with the
skip reasons printed (log #234); Track B -> **3 passed, 0 skips**, exit 0
(log #201); `setup.ps1` re-run idempotent, exit 0 "Setup complete"
(log #235); `run_selfcheck.bat` -> `SELF-CHECK: PASS`, gate green in
120.5 s (log #236).

UNVERIFIED steps: Track A via the `run_tests.bat` cmd wrapper (not re-run in
this pass); Track B on a machine without the Part E build (expected: exit 2
with the missing path printed — not executed here).

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

Apply the WOSP patch (adjust `/mnt/c<home>/` to your Windows username):

```bash
patch -p1 < /mnt/c<home>/PROJECT_WOWKISPICE/tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch
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
.\run_selfcheck.bat                  # -> SELF-CHECK: PASS
python tools\run_tests.py            # -> 488 tests passed, 3 skipped (UNEXECUTED QEMU contract tests)
python tools\demo_closed_loop.py     # -> PASS in ~40 seconds (needs the Part E emulator)
```

Without the Part E emulator, the demo exits **2** with
`FAIL: qemu-system-xtensa not found` (measured 2026-10-28; it searches
`--qemu`, `$WOSP_QEMU`, a sibling `qemu-build` checkout and `~/qemu-esp`).
The two lines above it need no emulator.

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
and WSL-style (`<home>/...`) paths work; a Linux QEMU on Windows is
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
<home>\PROJECT_WOWKISPICE\                this repo (Windows)
  .venv\                                   Python env (setup.ps1)
  tools\ngspice_dll\                       ngspice DLL (setup.ps1)
  firmware\esp32_buck_controller\.pio\     firmware build + qemu_flash.bin
  tools\demo_closed_loop.py                install sanity check
\\wsl$\<distro>\home\<you>\qemu-esp\       QEMU source (WSL)
  build\qemu-system-xtensa                 the emulator binary
<home>\AppData\Local\Temp\             demo serial logs (wosp-demo-*.log)
```

When all five checkpoints pass — tests green, firmware merged, QEMU
`--version` 9.2.2, demo `PASS` — your install is complete.
