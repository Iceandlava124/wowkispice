@echo off
title WOWKISPICE — Pro Mixed-Signal Co-Simulation Workbench
cd /d "%~dp0"
echo ======================================================================
echo  Launching WOWKISPICE Mixed-Signal Workbench...
echo ======================================================================
.\.venv\Scripts\python.exe ui\ltspice_workbench.py
pause
