import re

p = "/mnt/c/Users/gudae/Music/PROJECT_WOWKISPICE/tools/qemu-patch/README.md"
raw = open(p, "rb").read().decode("utf-8")
crlf = "\r\n" in raw
t = raw.replace("\r\n", "\n") if crlf else raw
n0 = len(t)


def rep(old, new, label):
    global t
    c = t.count(old)
    assert c == 1, "%s: count=%d" % (label, c)
    t = t.replace(old, new)


# 1 - "Driving it from the host": the stable path question is now answered
rep("""The exact path is not pinned down here. The device is created with `qdev_new()`
on the SoC's `esp32-periph-bus`, so it will land somewhere under
`/machine/soc/esp32-periph-bus/` with an auto-generated instance suffix rather
than the tidy `/machine/soc/sens` one might expect. If a stable, hand-writable
path matters, give it an explicit id at creation time
(`device_set_id(sens, "sens")`) — that is a one-line change.""",
    """The path **is** pinned down: the patch parents the device at creation time
(`object_property_add_child(container_get(qdev_get_machine(), "/peripheral"),
"sens", …)`), so it is always `/machine/peripheral/sens` — verified identical
across independent boots. (Without that, QEMU files it under
`/machine/unattached/device[N]`, whose index shifts between runs.) Note the
injection properties are declared with `realized_set_allowed = true`; without
that flag QEMU refuses `qom-set` after the SoC realizes the device.""",
    "host-driving")

# 2 - Applying and building
rep("""```bash
tar xf qemu-esp_develop_9.2.2_20260417-src.tar.xz
cd qemu-esp_develop_9.2.2_20260417
git apply /path/to/0001-esp32-model-sar-adc-and-gpio-output.patch
./configure --target-list=xtensa-softmmu --enable-trace-backends=nop
ninja -j4
```""",
    """```bash
tar xf qemu-esp_develop_9.2.2_20260417-src.tar.xz
cd qemu-esp_develop_9.2.2_20260417
patch -p1 < /path/to/0001-esp32-model-sar-adc-and-gpio-output.patch
./configure --target-list=xtensa-softmmu --disable-docs --disable-gtk \\
            --disable-sdl --disable-vnc --disable-spice --enable-slirp
ninja -C build
```

`--enable-slirp` matters: this fork compiles `net/slirp.c` unconditionally and
needs `pkg-config --cflags slirp` on that compile line (`libslirp-dev`
required). The build must be **native** — `qemu-system-xtensa` is an x86-64
program that emulates Xtensa via TCG; the xtensa toolchain is only for
firmware.""",
    "applying")

# 3 - Status section
m = re.search(r"## Status\n\n\*\*Not compiled\.\*\*.*?(?=\n## )", t, re.S)
assert m, "status anchor"
new_status = """## Status

**Compiled, boot-tested, and reproducible from scratch — 2026-10-07.**

- Regenerated from the working tree: the patch now includes the QEMU 9.2
  `QEMUTimer` fixes, the `realized_set_allowed` injection-property fix, and
  the stable `/machine/peripheral/sens` QOM path, none of which the original
  proposal had.
- `patch -p1` applies it cleanly to a pristine export of the pinned commit
  (exit 0, no fuzz, no rejects); configure and a full `ninja -C build` then
  complete with exit 0.
- The resulting `qemu-system-xtensa` boots the real `qemu_flash.bin` through
  ROM, bootloader and `app_main()`, completes **900 000 control-loop samples
  in 90 s with zero panics** (the stock-QEMU `Interrupt wdt timeout` panic is
  gone; residual `task_wdt` warnings are non-fatal), and answers
  `qom-set /machine/peripheral/sens adc1-value N` — the firmware prints
  `Raw ADC: 2012`, then at 3456 flips the gate **ON → OFF**, i.e. its own
  1995/2030 hysteresis reacting to injected input.
- Build prerequisites (all present in WSL Ubuntu 24.04): `ninja`, `pkg-config`,
  `flex`, `bison`, `libglib2.0-dev`, `libpixman-1-dev`, `libslirp-dev`,
  python3 >= 3.10 (`./configure` builds its own meson venv).

Still not wired: `bridge/qemu_orchestrator.py` does not feed `adc1-value`
programmatically — feeding is a manual monitor command, and nothing reads the
gate decision back into ngspice. That is the next session's task.

"""
t = t[:m.start()] + new_status + t[m.end():]

out = t.replace("\n", "\r\n") if crlf else t
open(p, "wb").write(out.encode("utf-8"))
print("qemu-patch README updated: %d -> %d chars (crlf=%s)" % (n0, len(t), crlf))
