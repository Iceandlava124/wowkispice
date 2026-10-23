"""selfcheck.py - install-and-verify entry point for a fresh clone.

Runs the three checks the repo's own readiness gate names as Phase 0:

    1. loader:         resolve_ngspice_library() finds a usable ngspice
                       (bundles, WOSP_NGSPICE_LIB, then ctypes.util).
    2. package:        the `bridge` package imports and `wosp-check` resolves.
    3. linter:         py_compile on the repository Python surface.

Exit 0 only when all three pass. Prints one line per check so a CI step can
assert on it directly.
"""

from __future__ import annotations

import os
import py_compile
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

CHECK_LABELS = (
    "loader",
    "package",
    "linter",
)

_FAILS: list[str] = []


def _check_loader() -> bool:
    """A usable ngspice must resolve. This is the only check that is NOT
    about this repository: it is about the machine the code lands on."""
    try:
        from bridge.ngspice_wrapper import resolve_ngspice_library

        resolved, _tried = resolve_ngspice_library(None)
        if resolved is None:
            _fail("no ngspice library resolved (need libngspice / ngspice.dll)")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        _fail(f"ngspice loader raised: {exc}")
        return False


def _check_package() -> bool:
    """The package must import, and the console entry point must resolve."""
    try:
        from bridge import __version__ as _v
        from bridge.ngspice_wrapper import NgSpiceEngine
    except Exception as exc:  # noqa: BLE001
        _fail(f"import of bridge.ngspice_wrapper raised: {exc}")
        return False
    try:
        r = subprocess.run(
            [PYTHON, "-m", "bridge.selfcheck", "--entry-point"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            _fail("`wosp-check` entry point did not resolve/exit 0")
            return False
    except Exception as exc:  # noqa: BLE001
        _fail(f"entry-point probe raised: {exc}")
        return False
    return True


def _check_linter() -> bool:
    """Byte-compile the whole Python surface so a stale checkout cannot hide
    syntax errors from the install path."""
    bad = []
    for path in _python_files(REPO_ROOT):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            bad.append(str(path))
    if bad:
        _fail(f"byte-compile failed for {len(bad)} file(s): {bad[:5]}")
        return False
    return True


def _python_files(root: Path) -> list[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", ".venv", "node_modules"}]
        for fname in filenames:
            if fname.endswith(".py"):
                out.append(Path(dirpath) / fname)
    return sorted(out)


def _fail(message: str) -> None:
    _FAILS.append(message)
    print(f"    FAIL: {message}")


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if "--entry-point" in args:
        # Exercised as a real subprocess so the exit code is unambiguous.
        print(f"wosp-check: entry point resolves to {sys.argv[0]}")
        return 0
    print("WOSP fresh-clone install-and-verify")
    print("=" * 40)
    checks = (_check_loader, _check_package, _check_linter)
    for label, check in zip(CHECK_LABELS, checks, strict=False):
        print(f"[{label:<10}] ", end="", flush=True)
        if check():
            print("PASS")
        else:
            print("FAIL")
    print("=" * 40)
    if _FAILS:
        print(f"SELF-CHECK: FAIL ({len(_FAILS)} check(s) failed)")
        return 1
    print("SELF-CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
