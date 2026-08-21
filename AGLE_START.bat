@echo off
REM AGLE START -- starts the watchdog/service process infrastructure only.
REM This does NOT turn the Master Switch ON. Production permission is a
REM separate, human decision -- use `python agle.py switch on` (or edit
REM runtime\master_switch.json directly) for that.
cd /d "%~dp0"
python agle.py service start
echo.
pause
