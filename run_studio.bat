@echo off
setlocal
cd /d "%~dp0"
echo ==============================================================================
echo  Launching WOWKISPICE Virtual Electronics Lab Studio
echo  Mixed-Signal Hardware + Firmware Co-Simulation Laboratory Rack
echo ==============================================================================

if exist .\.venv\Scripts\python.exe (
    set "PYTHON_EXE=.\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" ui/studio_app.py
pause
