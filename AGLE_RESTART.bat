@echo off
REM AGLE RESTART -- restarts the watchdog/service process infrastructure
REM only (stop, then start). Does NOT touch the Master Switch.
cd /d "%~dp0"
python agle.py service restart
echo.
pause
