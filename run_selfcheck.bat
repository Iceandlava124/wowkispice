@echo off
setlocal
set "REPO=%~dp0"
if not exist "%REPO%.venv\Scripts\python.exe" (
    echo ERROR: .venv not found. Run setup.ps1 first.
    exit /b 1
)
"%REPO%.venv\Scripts\python.exe" "%REPO%tools\selfcheck.py" %*
endlocal
