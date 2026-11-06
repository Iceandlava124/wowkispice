@echo off
REM WOWKISPICE Self-Check Batch File
REM Calls the Python self-check script

set SCRIPT_DIR=%~dp0
python "%SCRIPT_DIR%tools\selfcheck.py"
exit %errorlevel%