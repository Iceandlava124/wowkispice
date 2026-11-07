#!/usr/bin/env bash
# tools/run_selfcheck.sh — POSIX-shell entry point for the environment gate.
# Delegates to tools/selfcheck.py under the project interpreter so the gate has
# exactly one implementation (the same one run_selfcheck.bat uses).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -x "$ROOT/.venv/bin/python" ]; then
  VENV_PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  VENV_PY="$ROOT/.venv/Scripts/python.exe"
else
  echo "ERROR: no project interpreter found under .venv." >&2
  echo "       Run tools/setup.sh (or setup.ps1 on Windows) first." >&2
  exit 1
fi

exec "$VENV_PY" "$ROOT/tools/selfcheck.py" "$@"