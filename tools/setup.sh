#!/usr/bin/env bash
# tools/setup.sh — non-Windows / POSIX-shell bootstrap for WOWKISPICE.
# Creates .venv, installs requirements, ensures the ngspice DLL directory.
# Works on Linux/macOS and on Windows under Git Bash / MSYS2, where a venv
# uses Scripts/python.exe instead of bin/python.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "WOWKISPICE bootstrap"
echo "Repo root: $ROOT"

if [ ! -d "$ROOT/.venv" ]; then
  python3 -m venv "$ROOT/.venv"
  echo "Created .venv"
else
  echo ".venv already exists — reusing it"
fi

# A venv created on Windows (or by the Windows Python) uses Scripts/, not bin/.
if [ -x "$ROOT/.venv/bin/python" ]; then
  VENV_PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  VENV_PY="$ROOT/.venv/Scripts/python.exe"
else
  echo "ERROR: no interpreter found under .venv (looked for bin/python and Scripts/python.exe)."
  echo "       Delete .venv and re-run this script."
  exit 1
fi
echo "venv interpreter: $VENV_PY"

"$VENV_PY" -m pip install --upgrade pip setuptools wheel

if [ -f "$ROOT/requirements.txt" ]; then
  "$VENV_PY" -m pip install -r "$ROOT/requirements.txt"
  echo "Installed requirements from requirements.txt"
else
  echo "WARNING: requirements.txt not found at $ROOT/requirements.txt"
fi

# The tracked archive is tools/ngspice-47_dll_64.7z; the DLL itself must be
# present under tools/ngspice_dll for the FFI bridge to load it.
NGSPICE_DIR="$ROOT/tools/ngspice_dll"
mkdir -p "$NGSPICE_DIR"
if find "$NGSPICE_DIR" -name 'ngspice.dll' -size +100k | grep -q .; then
  echo "ngspice.dll already present under tools/ngspice_dll"
else
  echo "NOTE: ngspice.dll not found under tools/ngspice_dll."
  echo "      Extract it from tools/ngspice-47_dll_64.7z (the Windows DLL archive),"
  echo "      or point WOSP_NGSPICE_LIB at an installed libngspice."
fi

echo ""
echo "Bootstrap complete. Next:"
echo "  \"$VENV_PY\" tools/selfcheck.py"
echo "  bash tools/run_selfcheck.sh"