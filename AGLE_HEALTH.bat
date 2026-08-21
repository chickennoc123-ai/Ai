@echo off
REM AGLE HEALTH -- one-click live health check.
REM Double-click this file. It runs the real production CLI command
REM (python agle.py health) and leaves the console open so the result can
REM be read. It does nothing else: no GUI, no dashboard, no dependencies
REM beyond a working `python` on PATH and this repository.
cd /d "%~dp0"
python agle.py health
echo.
pause
