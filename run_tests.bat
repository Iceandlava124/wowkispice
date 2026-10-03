@echo off
title WOSP Test Suite
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found. Run run_editor.bat once first.
    exit /b 1
)

.venv\Scripts\python.exe tools\run_tests.py