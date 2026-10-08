import re

p = "/mnt/c/Users/gudae/Music/PROJECT_WOWKISPICE/README.md"
raw = open(p, "rb").read().decode("utf-8")
t = raw.replace("\r\n", "\n")
assert "\r" not in t, "mixed line endings"
n0 = len(t)


def rep(old, new, label):
    global t
    c = t.count(old)
    assert c == 1, "%s: count=%d" % (label, c)
    t = t.replace(old, new)


# E1 - read-this-first blockquote
rep("""> **Read this first:** the firmware binary is *parsed, not executed* **inside the
> simulation loop**. Separately from the co-simulation, the real compiled image
> does boot under Espressif's QEMU through ROM, the second-stage bootloader and
> `app_main()` — a captured boot log, no instrumentation. It then panics on its
> first ADC read, because that QEMU models no SAR ADC. The ADC/GPIO model that
> would close the last loop is in `tools/qemu-patch/` and **has never been
> compiled**. See [firmware execution status](#firmware-execution-status).""",
    """> **Read this first:** the firmware binary is *parsed, not executed* **inside the
> simulation loop**. Separately from the co-simulation, the real compiled image
> boots under Espressif's QEMU through ROM, the second-stage bootloader and
> `app_main()` — and, since the ADC/GPIO model in `tools/qemu-patch/` was
> compiled in and verified (2026-10-07), it now **runs its control loop and
> responds to analog values injected from the host** via a QEMU monitor
> command. What is still missing is the *automatic* bridge: nothing feeds
> those values from ngspice or reads the gate decision back. See
> [firmware execution status](#firmware-execution-status).""", "E1")

# E2 - the PARTIAL checklist item (single long line) -> new precise status
m = re.search(r"- \[ \] \*\*PARTIAL —\*\* The compiled firmware executes.*", t)
assert m, "E2 anchor"
new_item = (
    "- [x] **ACHIEVED via manual QOM control —** The compiled firmware boots **and** runs its real "
    "control loop in the patched emulator, **and** responds to analog values injected from the host. "
    "Evidence: `qemu-system-xtensa` built from the pinned Espressif tree with "
    "`tools/qemu-patch/0001-esp32-model-sar-adc-and-gpio-output.patch` (regenerated from the working "
    "tree, re-verified by configuring and fully building a **fresh source export + patch**); a 90 s "
    "boot yields **900 000 control-loop samples with zero panics** — the former `adc_oneshot_read()` "
    "watchdog panic is gone — and `qom-set /machine/peripheral/sens adc1-value <n>` changes the sample "
    "reported on the next iteration, flipping the gate **ON → OFF at 3456** (the firmware’s own "
    "hysteresis reacting to injected input). Precisely what is *not* covered: feeding is **manual** (a "
    "monitor command) — the automatic orchestrator bridge (ngspice ↔ QEMU) is **not yet wired**; "
    "`bridge/qemu_orchestrator.py` neither sets `adc1-value` nor reads the gate decision back, so no "
    "closed loop passes through the emulated chip yet. Details: [docs/systems-map.md](docs/systems-map.md) "
    "§4/§8 and the \"Firmware execution status\" table.")
t = t[:m.start()] + new_item + t[m.end():]

# E3 - honesty caveat
rep("It does **not** mean the firmware works on silicon, the thresholds are calibrated, the QEMU patch compiles, or that there is a working analog↔emulated-chip data path today.",
    "It does **not** mean the firmware works on silicon or that the thresholds are calibrated. Two things this caveat used to warn about are now settled — the QEMU patch compiles and is reproducible from a fresh source export, and an analog↔emulated-chip data path exists — but that path is a **manual** `qom-set` command, not an automatic bridge.",
    "E3")

# E4 - limitation blockquote
rep("""> **Limitation, stated plainly:** the firmware *binary* is still parsed, not
> executed. What executes is the decision logic and its constants, lifted from
> the firmware's own source. Espressif's QEMU does boot the compiled `.elf`
> through ROM, the second-stage bootloader and `app_main()`, but nothing couples
> that guest to the analog solver yet — QEMU models no ESP32 SAR ADC, so the
> firmware panics at `adc_oneshot_read()` and completes 0 control-loop samples.
> The netlist says which mode a pin is in, and the editor never shows a
> behaviour the solver did not produce.""",
    """> **Limitation, stated plainly:** inside the co-simulation loop the firmware
> *binary* is still parsed, not executed — what executes there is the decision
> logic and its constants, lifted from the firmware's own source. Separately,
> the patched Espressif QEMU boots the compiled `.elf` through ROM, the
> bootloader, `app_main()` and a full control loop — **900 000 samples / 90 s,
> zero panics** — and a manual `qom-set /machine/peripheral/sens adc1-value N`
> feeds it analog values it visibly reacts to (gate ON → OFF at 3456). Nothing
> yet couples that guest to the analog solver *automatically*. The netlist says
> which mode a pin is in, and the editor never shows a behaviour the solver did
> not produce.""", "E4")


# E5 - firmware execution status table rows
def row(prefix, new):
    global t
    m = re.search(re.escape(prefix) + r".*", t)
    assert m, "E5 anchor %r" % prefix
    t = t[:m.start()] + new + t[m.end():]


row("| Execute compiled machine instructions | ",
    "| Execute compiled machine instructions | **Works (patched QEMU).** The real `.elf` runs through ROM, bootloader, `app_main()` and the full control loop: **900 000 samples / 90 s, zero panics**. `bridge/qemu_orchestrator.py` reads its UART but does not yet feed it values (not coupled to ngspice). |")
row("| Run the firmware's control loop | ",
    "| Run the firmware's control loop | **Works (patched QEMU), verified 2026-10-07** on a build made from `tools/qemu-patch/` + the pinned source. Under *stock* QEMU it still fails as before: 4 watchdog panics / 45 s, **0 control-loop samples** (`esp32.sens` unimplemented, `esp32_gpio_write()` drops writes). |")
row("| Fix the above | ",
    "| Respond to injected analog values | **Works, manually.** `qom-set /machine/peripheral/sens adc1-value N` (QEMU monitor) changes the sample the firmware prints; the gate flips **ON → OFF at 3456**. Fixed QOM path, identical across boots. |\n| Fix the above | **Done and verified.** `tools/qemu-patch/0001-*.patch` (6 files, 431 insertions) compiles, boots, and was re-verified end to end from a fresh source export + patch. The automatic ngspice ↔ QEMU bridge is the remaining, deliberately deferred step. |")

# E6 - repository structure
rep("""`tools/qemu-patch/` is an
  uncompiled QEMU device model.""",
    """`tools/qemu-patch/` is the
  compiled-and-boot-tested SAR ADC + GPIO QEMU device-model patch.""", "E6")

open(p, "wb").write(t.replace("\n", "\r\n").encode("utf-8"))
print("README updated: %d -> %d chars" % (n0, len(t)))
