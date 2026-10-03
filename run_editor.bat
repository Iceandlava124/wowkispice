@echo off
title WOSP Schematic Editor
cd /d "%~dp0"

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