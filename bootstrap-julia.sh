#!/usr/bin/env bash
# bootstrap-julia.sh - one-command setup for the WOWKISPICE Julia solver (POSIX).
# Layer 4: makes distribution reproducible.
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================"
echo "WOWKISPICE Julia Backend Bootstrap"
echo "============================================"

if ! command -v julia >/dev/null 2>&1; then
    echo "FAIL: julia not found on PATH."
    echo "Install Julia 1.9+ from https://julialang.org/downloads/ and re-run."
    exit 1
fi

echo; echo "[1/3] Julia version:"
julia --version

echo; echo "[2/3] Instantiating pinned environment (bridge/julia)..."
julia --project=bridge/julia -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'

echo; echo "[3/3] Smoke solve (RC circuit)..."
julia --project=bridge/julia bridge/julia/solve_julia.jl \
  '{"circuit":{"type":"rc","resistance":2000,"capacitance":1e-6,"input_voltage":5},"simulation":{"dt":1e-6,"tstop":0.001}}'

echo; echo "============================================"
echo "Julia backend ready. Use: cargo run -p wosp-cli -- sim rc --r 2000"
echo "============================================"
