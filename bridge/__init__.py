"""bridge - WOSP core runtime: simulator wiring, firmware-in-the-loop path.

The public surface of the package, so ``import bridge`` gets the pieces app and
test layers actually use:

- ``qemu_orchestrator`` - boot the real ESP32 firmware under patched Espressif QEMU
  (TCG boot watch, qtest memory probe, console log). Execution layer.
- ``qemu_monitor`` - M0 automation: QMP connect, programmatic ``qom-set`` ADC
  injection, HMP ``xp`` gate readback, one-cycle coupling, sweep.
- ``firmware_runner`` - thin, deliberate re-export shim so the long-settled
  ``bridge.firmware_runner`` name keeps resolving for the test suite and any
  legacy callers. The real driver is ``qemu_monitor``.
- ``binary_runner`` - M1 wall-clock sampled-data hardware-in-the-loop runner.
"""

from __future__ import annotations

from . import binary_runner as binary_runner
from . import qemu_monitor as qemu_monitor
from . import qemu_orchestrator as qemu_orchestrator

# The executor module comes first in __all__: it owns QEMU boot/watch and the
# qtest memory probe, and tests import it directly.
__all__ = [
    "binary_runner",
    "qemu_monitor",
    "qemu_orchestrator",
    # Thin shim kept only so the long-settled name resolves.
    "firmware_runner",
]

try:
    from . import firmware_runner as firmware_runner  # noqa: F401
except ImportError:  # pragma: no cover - the shim is load-bearing for tests
    import warnings
    warnings.warn(
        "bridge.firmware_runner is not importable; unifying the module surface. "
        "See docs/binary-runner-and-mcu-bringup.md.",
        ImportWarning,
        stacklevel=2,
    )
