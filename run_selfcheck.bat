@echo off
title WOSP Environment Self-Check
cd /d "%~dp0"

REM Prefer the repo's .venv, fall back to the system python.
REM (goto, not if/else blocks: unescaped parens inside echo text in a
REM  parenthesised block make cmd mis-parse the script.)
if exist ".venv\Scripts\python.exe" goto :have_venv

echo No virtual environment found - falling back to the system python.
echo Run setup.ps1 or run_editor.bat once for a complete environment.
echo.
python tools\selfcheck.py %*
exit /b %errorlevel%

:have_venv
.venv\Scripts\python.exe tools\selfcheck.py %*
exit /b %errorlevel%
