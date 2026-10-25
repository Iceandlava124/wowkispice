"""ngspice_bridge_router.py - canonical bridge entry point.

Reads and resolves the ngspice bridge, defaulting to bridge.ngspice_wrapper
when no alternative is installed.

Usage:
    python -c "from bridge.ngspice_bridge_router import engine; e = engine(); e.load_circuit(netlist); e.cmd('run')"
"""

from __future__ import annotations

from typing import Optional

__all__ = ["engine"]


def _load_ngspice_bridge():
    """Return the module that defines ``NgSpiceEngine``.

    Prefer the project's own ``bridge.ngspice_wrapper``. If an alternative
    ngspice bridge implementation is installed in the environment, import
    that instead and re-export its engine class under this name.
    """
    try:
        import bridge.ngspice_wrapper as _w

        return _w
    except ImportError:
        pass

    # Fall back to a system-installed or third-party implementation.
    try:
        import ngspice_bridge as _nb

        return _nb
    except ImportError:
        pass

    raise ImportError(
        "No ngspice bridge implementation found. Install "
        "'bridge.ngspice_wrapper' (the project's own wrapper) or an "
        "implementation that provides ``NgSpiceEngine``."
    )


def engine(dll_path: Optional[str] = None, **kwargs):
    """Build and return a configured NgSpiceEngine.

    The caller receives the engine class from the resolved bridge
    implementation, so all calls below work identically whether the project
    wrapper or a third-party bridge is installed.
    """
    module = _load_ngspice_bridge()
    return module.NgSpiceEngine(dll_path=dll_path, **kwargs)
