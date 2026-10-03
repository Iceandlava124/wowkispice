@echo off
title WOSP Schematic Editor
cd /d "%~dp0"

REM ngspice is not committed (12.9 MB of vendor DLL). setup.ps1 downloads it.
if not exist "tools\ngspice_dll\Spice64_dll\dll-vs\ngspice.dll" (
    echo ngspice not found - running setup for the first time...
    powershell -ExecutionPolicy Bypass -File setup.ps1
    if errorlevel 1 (
        echo.
        echo Setup failed. See the message above.
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo.
echo   WOSP Schematic Editor - LTspice-style canvas + real ngspice solver
echo   Palette: click a part, click canvas. Wire: click pin, click pin.
echo   F2 = simulate   R = rotate   Del = delete   E = edit value   Ctrl+Z = undo
echo.
.venv\Scripts\python.exe ui\schematic_editor.py