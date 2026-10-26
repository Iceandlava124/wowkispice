#!/usr/bin/env bash
# One-shot setup for PROJECT_WOWKISPICE on Linux and macOS.
#
# Creates the virtualenv, installs Python dependencies, and verifies that a
# libngspice is reachable. Unlike Windows, ngspice publishes no prebuilt
# binaries for Linux/macOS - the supported route is a system package, which
# bridge/ngspice_wrapper.py picks up via ctypes.util.find_library.
#
# If you already have a libngspice .so/.dylib somewhere (conda, Homebrew, a
# source build), point the loader at it instead:
#     export WOSP_NGSPICE_LIB=/full/path/to/libngspice.so
#
# Safe to re-run: every step is skipped when already satisfied.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

step() { printf '\033[36m==> %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m    %s\033[0m\n' "$1"; }
warn() { printf '\033[33m    %s\033[0m\n' "$1"; }

# ---------------------------------------------------------------------------
# 1. Virtualenv + Python dependencies
# ---------------------------------------------------------------------------
VENV_PY="$ROOT/.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
  step "Creating virtualenv"
  PY="${PYTHON:-python3}"
  command -v "$PY" >/dev/null 2>&1 || PY=python
  command -v "$PY" >/dev/null 2>&1 || {
    echo "python3 not found. Install Python 3.10+ and re-run." >&2
    exit 1
  }
  "$PY" -m venv "$ROOT/.venv"
  "$VENV_PY" -m pip install --upgrade pip
fi

step "Installing Python dependencies"
"$VENV_PY" -m pip install -r "$ROOT/requirements.txt"

# ---------------------------------------------------------------------------
# 2. Verify libngspice resolves
# ---------------------------------------------------------------------------
step "Checking for libngspice"

PROBE=$(mktemp --suffix=.py)
trap 'rm -f "$PROBE"' EXIT
cat > "$PROBE" <<'PY'
import os, sys
sys.path.insert(0, os.environ["WOSP_ROOT"])
from bridge.ngspice_wrapper import resolve_ngspice_library
path, tried = resolve_ngspice_library(os.environ.get("WOSP_NGSPICE_LIB") or None)
for t in tried:
    print("    tried:", t)
if path is None:
    sys.exit(1)
print("    resolved:", path)
PY
export WOSP_ROOT="$ROOT"

if WOSP_NGSPICE_LIB="${WOSP_NGSPICE_LIB:-}" "$VENV_PY" "$PROBE"; then
  step "Verifying the loader binds libngspice"
  BIND=$(mktemp --suffix=.py)
  cat > "$BIND" <<'PY'
import os, sys
sys.path.insert(0, os.environ["WOSP_ROOT"])
from bridge.ngspice_wrapper import resolve_ngspice_library, NgSpiceEngine
p = os.environ.get("WOSP_NGSPICE_LIB") or None
assert resolve_ngspice_library(p)[0] is not None, "resolver cannot find libngspice"
NgSpiceEngine(verbose=p, dll_path=p).load_circuit(
    ["* probe", "V1 in 0 DC 1", "R1 in 0 1k", ".op", ".end"])
print("BIND_OK")
PY
  if ! WOSP_NGSPICE_LIB="${WOSP_NGSPICE_LIB:-}" "$VENV_PY" "$BIND"; then
    echo "libngspice was found but could not be loaded." >&2
    exit 1
  fi
  rm -f "$BIND"
  ok "libngspice loads."
  step "Cleaning up orphaned processes"
  "$VENV_PY" tools/cleanup_qemu.py 2>&1 | tail -2 || true
  step "Checking for prebuilt patched QEMU"
  "$VENV_PY" tools/fetch_qemu.py 2>&1 | tail -3 || true
  step "Running environment doctor"
  "$VENV_PY" tools/doctor.py 2>&1 | tail -20 || true
  "$VENV_PY" -c "from bridge.toolchain_resolver import ToolchainResolver; r=ToolchainResolver(); print(r.write_env_local())" 2>&1 | tail -1 || true
  ok "Setup complete."
  printf '\nNext:\n  python tools/doctor.py  # check environment health\n  ./run_tests.py  # or: python tools/run_tests.py\n  python ui/schematic_editor.py\n'
  exit 0
fi

# ---------------------------------------------------------------------------
# 3. Not found - tell the user exactly how to fix it
# ---------------------------------------------------------------------------
cat >&2 <<EOF

$(printf '\033[31mPROJECT_WOWKISPICE needs libngspice, which is not installed on this machine.\033[0m')

Install it with your package manager:

  Debian / Ubuntu   sudo apt-get update && sudo apt-get install -y ngspice libngspice0
  Fedora / RHEL     sudo dnf install -y ngspice
  Arch              sudo pacman -S ngspice
  Alpine            sudo apk add ngspice
  macOS (Homebrew)  brew install ngspice

Then re-run ./setup.sh to confirm.

If you already have a shared library somewhere (conda, a source build, a
vendored copy), skip the package manager and point the loader at it:

  export WOSP_NGSPICE_LIB=/full/path/to/libngspice.so

No Windows .7z download step exists here: ngspice does not publish prebuilt
Linux or macOS binaries, so a system package is the supported route.
EOF
exit 1