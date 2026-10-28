# QEMU handoff — patched ESP32 SAR ADC model: built, gate-tested, **reproduced from scratch**

## Status summary (2026-10-07, all verified by measurement)

| Item | Status |
| --- | --- |
| Native build of `qemu-system-xtensa` | **DONE** |
| SAR ADC + GPIO patch | **REGENERATED** from the working tree — now includes every fix (431 insertions, 6 files) |
| Gate 1: boot to `app_main`, control-loop samples, no fatal panic | **PASSED** — 900 000 samples / 90 s, 0 panics |
| Host ADC injection via `qom-set`, stable path | **VERIFIED** — `/machine/peripheral/sens`, identical across boots; Gate ON→OFF at 3456 |
| Reproducibility: fresh source export + patch → build → boot → inject | **PASSED** — clean configure, clean full build (2493 targets, exit 0), same behaviour |
| Automatic ngspice ↔ QEMU orchestrator bridge | **NOT WIRED** — deliberately next session's task |

## The binary

- Path: `/mnt<home>/Music/qemu-build/qemu-esp_develop_9.2.2_20260417/build/qemu-system-xtensa`
- QEMU 9.2.2, x86_64 native, TCG, `--target-list=xtensa-softmmu`
- Rebuild after editing a model file: `ninja -C build` in the source tree (incremental, ~1 min)

### Configure command (used for both the working build and the fresh-copy repro)

```bash
cd <qemu-source-tree>
./configure --target-list=xtensa-softmmu --disable-docs --disable-gtk \
            --disable-sdl --disable-vnc --disable-spice --enable-slirp
ninja -C build
```

Notes:
- MUST be a **native** build (an xtensa-cross attempt was wrong: the QEMU binary
  is a host program that emulates Xtensa via TCG; `xtensa-esp-elf` is only for
  compiling firmware).
- `--enable-slirp` matters: this fork compiles `net/slirp.c` unconditionally and
  needs `-I/usr/include/slirp` on that compile line. `libslirp-dev` is installed.

## The patch — tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch

**Regenerated 2026-10-07 from the current working tree** via
`git add -N` (for the two new files) + `git diff -- hw include`.
It is 528 lines, 431 insertions / 4 deletions across 6 files and includes all
fixes that the original proposal lacked:

1. QEMU 9.2 `QEMUTimer` API: `timer_init(...)` and `timer_mod(&s->conv_timer, ...)`
2. `realized_set_allowed = true` on `adc1-value`/`adc2-value`/`conversion-ns` —
   without it QEMU refuses `qom-set` after realize
   (`Attempt to set property ... after it was realized`,
   `hw/core/qdev-properties.c`)
3. Stable QOM path: `object_property_add_child(container_get(qdev_get_machine(),
   "/peripheral"), "sens", ...)` in `hw/xtensa/esp32.c`, so the device is always
   `/machine/peripheral/sens` (otherwise QEMU files it under
   `/machine/unattached/device[N]`, index shifting per run)

**Deliberately excluded from the patch:** `scripts/symlink-install-tree.py`
(a Windows-symlink fallback left over from abandoned native-Windows attempts;
inert on WSL — verified: the fresh-copy configure ran the unmodified script and
exited 0).

### Reproducibility test (the real one — PASSED)

1. `git archive HEAD` of the pinned repo (`40edcca`, pristine) → fresh dir
   `<home>/repro/src`
2. `patch -p1 --batch < new patch` → all 6 files, exit 0, no fuzz, no rejects
3. `./configure <flags above>` → exit 0, `slirp: enabled`
4. `ninja -C build` → exit 0 (2493 targets)
5. The fresh binary then reproduced today's working state:
   - `app_main` reached (1), `BUCK_CTRL` loop running
   - `qom-set /machine/peripheral/sens adc1-value 2012` → 30 lines of `Raw ADC: 2012`
   - `qom-set ... 3456` → 16 lines of `Raw ADC: 3456 | Gate: OFF`
   - **0 panics** (`grep -Eci "guru meditation|Interrupt wdt timeout"` = 0)

## Verified boot behaviour (working tree binary)

- `app_main()` reached, **900 000 control-loop iterations in 90 s**
- Old fatal `Interrupt wdt timeout` / Guru Meditation panic is **gone**
- Non-fatal `task_wdt` warnings still print every ~5 s (IDLE0 starved by the
  busy loop). Cosmetic; does not reset the guest.
- Gate reaction: `Gate: ON` at in-band 2012 → `Gate: OFF` at 3456 (the
  firmware's own 1995/2030 hysteresis responding to injected input)

## ADC injection from the host

Fixed path — no discovery needed:

```
(qemu) qom-get /machine/peripheral/sens adc1-value   -> 0
(qemu) qom-set /machine/peripheral/sens adc1-value 2012
   serial: BUCK_CTRL: Loop: ... | Raw ADC: 2012 | Gate: ON
(qemu) qom-set /machine/peripheral/sens adc1-value 3456
   serial: BUCK_CTRL: Loop: ... | Raw ADC: 3456 | Gate: OFF
```

Helper: `tools/demo_closed_loop.py` automates the whole session (boot →
inject → gate assertion → clean exit); `tmp/qom_set.py` was the one-shot
scratch version (not committed).
To open the monitor in a manual run, add:
`-monitor tcp:127.0.0.1:4444,server=on,wait=off`

## Environment notes

- WSL Ubuntu 24.04, native GCC 13.3, ninja 1.11, python3 3.12, glib 2.80,
  libslirp-dev 4.7.
- Serial/console logs should go to WSL-local paths (`/tmp/...`), not `/mnt/c`.
- Firmware flash image (4 MB): `firmware/esp32_buck_controller/.pio/build/esp32dev/qemu_flash.bin`
- Boot to `app_main` takes ~10.3 s guest time.
- Fresh-copy repro lives at `<home>/repro/src` (WSL ext4; build is fast there).

## Left as-is / known noise

- QEMU tree has untracked `configure*.log` and `.meson-venv/` leftovers at its
  root (from earlier configure experiments); harmless, ignored by the patch.
- `scripts/symlink-install-tree.py` remains modified in the working tree but
  excluded from the patch (see above).

## Next session (deliberately not started)

Wire `bridge/qemu_orchestrator.py`: discover/set `adc1-value` from the ngspice
side each iteration and read the gate decision back — the automatic
ngspice ↔ QEMU loop. Everything else is locked in.
