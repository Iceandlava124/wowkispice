"""PROJECT_WOWKISPICE - mixed-signal co-simulator (ngspice + ESP32 firmware/QEMU)."""

__all__ = []


def _discover_diagnostics():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    return root / "tools" / "diagnostics.py"


_diagnostics = _discover_diagnostics()


def diagnostics():
    """Run the diagnostics command and return its text (decorated for the log).

    Prints OS, Python, ngspice and QEMU versions, binary checksums, and the
    last log path, redacting home directories and usernames.
    """
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(_diagnostics)],
        cwd=str(_diagnostics.parent),
        capture_output=True,
        text=True,
    )
    out = proc.stdout or ""
    err = proc.stderr or ""
    if proc.returncode != 0:
        return f"[diagnostics exited {proc.returncode}]\n{err}\n{out}"
    return out


if __name__ == "__main__":
    raise SystemExit(diagnostics())
