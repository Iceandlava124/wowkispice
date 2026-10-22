"""binary_runner.py - M1 wall-clock sampled-data hardware-in-the-loop runner.

Thin re-export shim so the long-settled ``bridge.binary_runner`` name keeps
resolving for the test suite and any legacy caller. The real driver is
``bridge/qemu_monitor``; this module exists so callers that import
``bridge.binary_runner`` keep working unchanged.
"""

from __future__ import annotations

from . import qemu_monitor as binary_runner

__all__ = ["binary_runner"]
