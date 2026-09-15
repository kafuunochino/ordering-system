@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" build_exe.py
if errorlevel 1 goto :failed
echo Built: dist\SanmuOrdering.exe
pause
exit /b 0
:failed
echo Build failed. Please check the error above.
pause
exit /b 1
