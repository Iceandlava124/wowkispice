"""firmware_runner.py - thin re-export shim over the M0 firmware-in-the-loop
driver so the long-settled ``bridge.firmware_runner`` name keeps resolving for
the test suite and any legacy caller.

The real implementation is ``bridge/qemu_monitor`` (the native Windows
Espressif QEMU monitor automation). This module exists so callers using the old
name keep working unchanged, and it is the module against which
``tests/test_fault_injection.py`` pins its environment gates.
"""

from __future__ import annotations

from .qemu_monitor import (  # noqa: F401
    QemuMonitor,
    QemuMonitorError,
    FirmwareCouplingCycle,
    _free_port,
    cycle_adc_and_gate,
    sweep_report,
    main,
)

__all__ = [
    "QemuMonitor",
    "QemuMonitorError",
    "FirmwareCouplingCycle",
    "_free_port",
    "cycle_adc_and_gate",
    "sweep_report",
    "main",
]
