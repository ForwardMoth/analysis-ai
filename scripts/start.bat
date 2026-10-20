@echo off
setlocal
cd /d "%~dp0.."
chcp 65001 >nul
if not exist ".venv-win\Scripts\python.exe" (
  echo Environment not found. Run scripts\setup.bat first.
  pause
  exit /b 1
)
".venv-win\Scripts\python.exe" src\app.py --port 8765 --open
if errorlevel 1 pause
