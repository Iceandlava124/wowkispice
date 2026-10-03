@echo off
setlocal
cd /d "%~dp0"

rem Make sure the Ollama server is running
curl -s http://127.0.0.1:11434/api/version >nul 2>nul
if errorlevel 1 (
    echo Starting Ollama server...
    start "" "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve
    timeout /t 5 /nobreak >nul
)

rem Run the overnight batch (extra args pass through, e.g. --only 01,05)
".venv\Scripts\python.exe" tools\overnight_ollama.py %*

echo.
echo Results are in overnight\
pause
