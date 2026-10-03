@echo off
title WOSP Test Suite
cd /d "%~dp0"

REM ngspice is not committed (12.9 MB of vendor DLL). setup.ps1 downloads it.
if not exist "tools\ngspice_dll\Spice64_dll\dll-vs\ngspice.dll" (
    if exist ".venv\Scripts\python.exe" (
        echo ngspice not found - running setup...
        powershell -ExecutionPolicy Bypass -File setup.ps1 -SkipPython
        if errorlevel 1 goto :nospice
    ) else (
        echo No virtual environment found. Run run_editor.bat once first.
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found. Run run_editor.bat once first.
    exit /b 1
)

.venv\Scripts\python.exe tools\run_tests.py
exit /b %errorlevel%

:nospice
echo.
echo ngspice could not be set up automatically.
echo Run this by hand for the full message:
echo     powershell -ExecutionPolicy Bypass -File setup.ps1
exit /b 1