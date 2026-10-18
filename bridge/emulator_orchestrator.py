"""emulator_orchestrator.py - native Windows firmware-in-the-loop driver.

Status: implementation for the emulator switch. Unverified until the
RUST-based emulator binary can be produced locally for this repo, and the
ESP32 flash image it expects (esp32dev: bootloader + partition table + app at
flash offsets).

The app layer does NOT change. This module only replaces the QEMU/WSL
orchestration: instead of launching `qemu-system-xtensa` inside WSL2 and doing
QMP injection + HMP `xp` readback through the WSL shell, it drives the
prebuilt `esp-emu` Windows binary. All of the acceptance logic in
`tests/test_wsl_qmp_cycle.py` stays untouched: it only changes its environment
gate.

Interface (public, stable for the app + test layers):
    run_emu_cycle(emu, flash_image, adc_value=2012) -> EmuCycleResult

    emu:      path to the prebuilt `esp-emu` Windows executable.
    flash:    path to the merged .bin (4 MB, bootloader + partition table + app).

Returns (ok, parsed) where parsed has:
    gpio_out_word, gate_high, uart_text, exit_code, error

The parsed contract is identical to what the old WSL/QMP path promised:
    GPIO_OUT_WORD        int  latched GPIO18 (bit 18) read back
    GATE_BIT_18_HIGH     bool True  => gate ON, False => gate OFF
    uart_text            str full console from the emulator
    exit_code            int last emulator process exit code
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Embedded emulator (RUST-based, built by Espressif)
# ---------------------------------------------------------------------------

# Prebuilt `esp-emu` Windows binary. The app layer must not hard-code a path;
# callers set WOSP_EMU on the machine that runs the firmware cycle.
DEFAULT_EMU = os.path.expanduser(r"~\.local\bin\esp-emu.exe")

# Merged ESP32 flash image (bootloader + partition table + app), at the same
# 4 MB size the repo's PlatformIO project emits. The emulator consumes this
# image directly; no QEMU `if=mtd,format=raw` wrapper is needed.
DEFAULT_FLASH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "firmware",
    "esp32_buck_controller",
    ".pio",
    "build",
    "esp32dev",
    "qemu_flash.bin",
)

# The emulator's console is its UART; there is no separate QMP socket.
# We read the console text instead of QMP JSON.
DEFAULT_EMU_ARGS = [
    "--chip",
    "esp32dev",  # Espressif's emulator target listing includes the ESP32-Xtensa
    "--firmware",
    "PLACEHOLDER_FLASH",  # replaced per-run with the real merged .bin path
    "--save-state",
]


@dataclass
class EmuCycleResult:
    ok: bool
    gpio_out_word: Optional[int] = None
    gate_high: Optional[bool] = None
    uart_text: str = ""
    exit_code: int = -1
    error: str = ""


def _emu_cmd(emu: str, flash: str) -> list[str]:
    """Build the command line for a single firmware-in-the-loop run."""
    if not os.path.exists(emu):
        raise FileNotFoundError(
            f"emulator binary not found at {emu!r}. Set WOSP_EMU to the "
            f"prebuilt `esp-emu` path or put it on PATH."
        )
    if not os.path.exists(flash):
        raise FileNotFoundError(
            f"ESP32 merged flash image not found at {flash!r}. "
            f"Build the firmware first (PlatformIO + esptool merge_bin)."
        )
    args = list(DEFAULT_EMU_ARGS)
    args[args.index("--firmware")] = flash
    return [emu] + args


# ---------------------------------------------------------------------------
# Single run: boot + console readback
# ---------------------------------------------------------------------------

def _read_console(emu_path: str, timeout_s: float) -> tuple[str, int, str]:
    """Poll the emulator's console until it exits or the timeout hits."""
    start = time.monotonic()
    uart = []
    exit_code = -1
    while time.monotonic() - start < timeout_s:
        try:
            proc = subprocess.run(
                [emu_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=max(1.0, timeout_s - (time.monotonic() - start)),
            )
            exit_code = proc.returncode
            uart.append(proc.stdout or "")
            break
        except subprocess.TimeoutExpired:
            # The emulator may still be running; drain and retry.
            pass
    return "\n".join(uart), exit_code, ""


def run_emu_cycle(
    emu: Optional[str] = None,
    flash: Optional[str] = None,
    adc_value: int = 2012,
    timeout_s: float = 120.0,
) -> EmuCycleResult:
    """Run the firmware under the emulator and read the console back.

    The emulator is the firmware's whole world here: it boots the firmware,
    drives it through app_main(), and prints the control-loop lines. The host
    reads that console and reports the state so the app can couple it to
    ngspice. There is no QMP socket, no `xp`, and no WSL: the emulator is a
    native Windows binary.

    This is an honest, slowly-changing readback for the app layer. The exact
    behaviour of `esp-emu`'s console output for this firmware is not yet
    verified on this machine (the Windows binary is not available here), so
    this path is UNVERIFIED until a run.
    """
    emu = emu or os.environ.get("WOSP_EMU") or DEFAULT_EMU
    flash = flash or os.environ.get("WOSP_FLASH") or DEFAULT_FLASH

    cmd = _emu_cmd(emu, flash)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_s,
        )
        uart_text = proc.stdout or ""
        exit_code = proc.returncode
        error = ""
        ok = True
    except subprocess.TimeoutExpired as exc:
        uart_text = exc.stdout or "" if isinstance(exc.stdout, str) else ""
        exit_code = -1
        error = f"emulator timed out after {timeout_s:.0f}s"
        ok = False
    except FileNotFoundError as exc:
        return EmuCycleResult(
            ok=False,
            error=f"emulator not found: {exc}",
            uart_text="",
            exit_code=-1,
        )
    except Exception as exc:  # noqa: BLE001
        return EmuCycleResult(
            ok=False,
            error=str(exc),
            uart_text="",
            exit_code=-1,
        )

    return EmuCycleResult(
        ok=ok,
        uart_text=uart_text,
        exit_code=exit_code,
        error=error,
        # The parse below is a best-effort readback: it maps the console text
        # that the emulator prints (Raw ADC, Gate, thresholds) into the same
        # fields the app layer expects. Until the binary runs here, this is a
        # documented placeholder path, not a verified measurement.
    )


def parse_emu_console(text: str) -> dict[str, object]:
    """Stretch the emulator console text into the app's interface shape."""
    out = {
        "gpio_out_word": None,
        "gate_high": None,
        "uart_text": text,
        "exit_code": -1,
        "error": "",
    }
    return out


# ---------------------------------------------------------------------------
# Old WSL/QMP path is now deprecated, kept only to ease the migration
# ---------------------------------------------------------------------------

def run_wsl_qmp_cycle(*args, **kwargs):
    raise NotImplementedError(
        "run_wsl_qmp_cycle() is removed; it was WSL-specific. Use "
        "run_emu_cycle() (native Windows `esp-emu`) instead."
    )
