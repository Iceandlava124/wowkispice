@echo off
setlocal
set "REPO=%~dp0"
if not exist "%REPO%.venv\Scripts\python.exe" (
    echo ERROR: .venv not found. Run setup.ps1 first.
    exit /b 1
)
"%REPO%.venv\Scripts\python.exe" "%REPO%tools\selfcheck.py" %*
set "RC=%ERRORLEVEL%"
rem endlocal on its own drops ERRORLEVEL back to 0, so carry the real code
rem across it (measured: a clone printed SELF-CHECK: FAIL and exited 0).
endlocal & exit /b %RC%
