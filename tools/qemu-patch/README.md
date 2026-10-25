# tools/qemu-patch — the two patches behind the patched ESP32 QEMU

Status (2026-10-25): both patches are in this directory and **proven**
against the local build tree (evidence below). One thing stays
**UNVERIFIED: "binary rebuilt from patches 0001+0002 from scratch"** — the
`qemu-system-xtensa` binary in daily use was *not* rebuilt from these files
during this pass; the patches were matched against the source tree the
binary was built from instead.

`README.old.md` is the original patch-bundle README recovered from git
history (`60522dc^`), kept untouched for owner review.

## Pinned upstream (read from a clone, not from memory)

| Item | Value |
|---|---|
| Upstream | `https://github.com/espressif/qemu`, branch `esp-develop` |
| Tag | `esp-develop-9.2.2-20260417` (annotated tag object `6cdce334bfa5541a5e46c860a9b40a4fe5a13aae`) |
| Tagged commit | `40edccac415693c5130f91c01d84176ae6008566` |

Verify before patching:

```bash
git clone --depth 1 --branch esp-develop-9.2.2-20260417 https://github.com/espressif/qemu.git qemu-esp
cd qemu-esp
git rev-parse --short HEAD    # expect: 40edcca
git rev-parse 'esp-develop-9.2.2-20260417^{commit}'   # expect: 40edccac415693c5130f91c01d84176ae6008566
```

## The patches — apply in this order

| Order | File | sha256 | Size / endings |
|---|---|---|---|
| 1 | `0001-esp32-model-sar-adc-and-gpio-output.patch` | `1b67e3ae7cd64f5910df5dab942b8cec812b30899082036c133286f6e760a131` | 16,775 B, 528 lines, pure LF |
| 2 | `0002-esp32-sens-immediate-conversion.patch` | `d26ad45110f9c870d9e910864f4885ed0a621407387a0aed2f2d99f6570e0811` | 814 B, pure LF |

**What 0001 changes (6 files, +431/−4).** It turns stock QEMU's
`unimplemented-device` stub for the ESP32 sensor peripheral into a working
mixed-signal model and makes the GPIO output observable: `hw/misc/esp32_sens.c`
(new) implements the `SENS` register block (`SENS_SAR_MEAS_START1_REG`
0x3FF48854 and friends) with a 12-bit SAR conversion result word that the
host can inject through the `adc1-value` QOM property, and it fires the
completion interrupt; `hw/gpio/esp32_gpio.c` gains readable/writable
`GPIO_OUT`, `GPIO_OUT1` and `GPIO_ENABLE` registers so the firmware's GPIO18
gate decision can be latched and read back with HMP `xp` at 0x3FF44004;
`hw/xtensa/esp32.c`, `hw/misc/meson.build` and the two headers wire the
devices into the machine and declare their state. This is the patch that
makes the ADC-injection → gate-readback loop possible at all.

**What 0002 changes (1 file, +5/−2).** It edits only
`hw/misc/esp32_sens.c::esp32_sens_start()`: instead of arming
`timer_mod(&s->conv_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
s->conversion_ns)` — which never fires while the firmware busy-polls the
done bit in a tight `while (1)` with no blocking MMIO, because QEMU virtual
time only advances when a vCPU blocks (the `adc_oneshot_read` hang) — the
conversion is fired immediately with `esp32_sens_convert(s)`, with an
inline comment recording that reasoning.

## How SETUP.md Part E should apply them

Part E's checkout (`--branch esp-develop-9.2.2-20260417`, expect `40edcca`)
is correct as written; its apply step must run **both** patches in order
(the current SETUP.md applies only 0001 — that edit belongs to a later
pass, since SETUP.md is outside this job's allowlist):

```bash
cd ~/qemu-esp
git apply --check /mnt/c/Users/<you>/PROJECT_WOWKISPICE/tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch
git apply           /mnt/c/Users/<you>/PROJECT_WOWKISPICE/tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch
git apply --check /mnt/c/Users/<you>/PROJECT_WOWKISPICE/tools/qemu-patch/0002-esp32-sens-immediate-conversion.patch
git apply           /mnt/c/Users/<you>/PROJECT_WOWKISPICE/tools/qemu-patch/0002-esp32-sens-immediate-conversion.patch
```

(`patch -p1 < …` works too — keep the order: 0001 first, 0002 second.)

## Fidelity note

**0002 removes the modelled conversion delay: the ADC completes instantly
in emulated time and conversion timing is not modelled.** The real ESP32's
SAR conversion takes time; here `esp32_sens_start()` completes the
conversion on the same call. Any result that depends on conversion latency
(throughput at high sample rates, interrupt timing relative to conversion)
is therefore not covered by the model — see `docs/fidelity.md`.

## What was proven (2026-10-25), and what was not

Proven — in a fresh scratch clone at the pinned tag (outside this repo,
WSL):

1. `git apply --check` + `git apply` of **0001**: exit 0.
2. `git apply --check` + `git apply` of **0002**: exit 0.
3. The 6 patched files are **byte-identical** to the local build tree
   `C:\Users\gudae\Music\qemu-build\qemu-esp_develop_9.2.2_20260417`
   (`diff hw/misc/esp32_sens.c <build-tree>/hw/misc/esp32_sens.c` empty;
   the other five clean under `diff -q`).
4. The build tree's own commit of the model (`478892a`) is byte-identical
   to the recovered 0001.

Not proven — **UNVERIFIED: "binary rebuilt from patches 0001+0002 from
scratch."** The running binary's source tree also carries one unrelated
local edit (`scripts/symlink-install-tree.py`, excluded from both patches),
and no build log in this repo links the binary to a source state.

### Proposed rebuild command (NOT run)

```bash
cd ~/qemu-esp        # pinned tag + 0001 + 0002 applied, as above
./configure --target-list=xtensa-softmmu --disable-docs --disable-gtk --disable-sdl --disable-vnc --disable-spice --enable-slirp
ninja -C build
./build/qemu-system-xtensa --version        # expect: QEMU emulator version 9.2.2
```

(The `./configure` flags are SETUP.md Part E's verified line; a
`tools/build_qemu.sh` variant exists but still applies only 0001 — owner
follow-up.)
