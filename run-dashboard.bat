@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual env not found — run setup first.
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"
python "%~dp0EnergyDashboard2.py" %*
if errorlevel 1 pause
