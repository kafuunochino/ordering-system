@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -c "from PySide6 import QtWidgets"
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 pause
exit /b
:failed
echo Setup failed. Please check the error above.
pause
exit /b 1
