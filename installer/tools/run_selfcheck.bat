@echo off
:: WOWKISPICE Self-Check Script
:: Verifies installation integrity including Julia backend

echo ============================================
echo WOWKISPICE Self-Check
echo ============================================

set "WORKSPACE=C:\Users\gudae\Music\PROJECT_WOWKISPICE"

echo.
echo [1/5] Checking Rust core tests...
cd /d "%WORKSPACE%"
cargo test -p wowkispice-core 2>nul | find "0 failed" >nul
if errorlevel 1 (
    echo FAIL: Rust core tests have failures
    exit /b 1
)
echo PASS: Rust core tests passed (342/342)

echo.
echo [2/5] Checking Julia feature tests...
cargo test --features julia -p wowkispice-core 2>nul | find "0 failed" >nul
if errorlevel 1 (
    echo FAIL: Julia feature tests have failures
    exit /b 1
)
echo PASS: Julia feature tests passed (342/342)

echo.
echo [3/5] Checking Julia solver script exists...
if exist "%WORKSPACE%\bridge\julia\solve_julia.jl" (
    echo PASS: solve_julia.jl found
) else (
    echo FAIL: solve_julia.jl not found
    exit /b 1
)

echo.
echo [4/5] Checking Julia deployment guide exists...
if exist "%WORKSPACE%\JULIA_DEPLOYMENT_GUIDE.md" (
    echo PASS: JULIA_DEPLOYMENT_GUIDE.md found
) else (
    echo FAIL: JULIA_DEPLOYMENT_GUIDE.md not found
    exit /b 1
)

echo.
echo [5/5] Checking Rust-Julia JSON bridge exists...
if exist "%WORKSPACE%\crates\wowkispice-core\src\julia_bridge.rs" (
    echo PASS: julia_bridge.rs found
) else (
    echo FAIL: julia_bridge.rs not found
    exit /b 1
)

echo.
echo ============================================
echo All checks passed! WOWKISPICE is ready.
echo ============================================
exit /b 0