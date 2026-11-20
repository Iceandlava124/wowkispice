@echo off
REM bootstrap-julia.bat - one-command setup for the WOWKISPICE Julia solver.
REM Layer 4: makes distribution reproducible. Checks Julia, instantiates the
REM pinned Project.toml/Manifest.toml environment, and runs a smoke solve.

setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo WOWKISPICE Julia Backend Bootstrap
echo ============================================

where julia >nul 2>nul
if errorlevel 1 (
    echo FAIL: julia not found on PATH.
    echo Install Julia 1.9+ from https://julialang.org/downloads/ and re-run.
    exit /b 1
)

echo.
echo [1/3] Julia version:
julia --version

echo.
echo [2/3] Instantiating pinned environment (bridge/julia)...
julia --project=bridge/julia -e "using Pkg; Pkg.instantiate(); Pkg.precompile()"
if errorlevel 1 (
    echo FAIL: Pkg.instantiate failed
    exit /b 1
)

echo.
echo [3/3] Smoke solve (RC circuit)...
julia --project=bridge/julia bridge/julia/solve_julia.jl "{\"circuit\":{\"type\":\"rc\",\"resistance\":2000,\"capacitance\":1e-6,\"input_voltage\":5},\"simulation\":{\"dt\":1e-6,\"tstop\":0.001}}"
if errorlevel 1 (
    echo FAIL: smoke solve failed
    exit /b 1
)

echo.
echo ============================================
echo Julia backend ready. Use: cargo run -p wosp-cli -- sim rc --r 2000
echo ============================================
exit /b 0
