@echo off
REM AGLE STOP -- stops the watchdog/service process infrastructure only.
REM This does NOT turn the Master Switch OFF and does NOT touch any
REM production ledger. It asks the watchdog to stop gracefully: it will
REM let an in-progress evaluation finish before exiting, so this can take
REM a while (up to several minutes) if a real cycle is running.
cd /d "%~dp0"
python agle.py service stop
echo.
pause
