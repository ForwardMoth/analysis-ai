@echo off
rem One-time Windows setup: creates .venv-win and installs the dependencies.
setlocal
cd /d "%~dp0.."
chcp 65001 >nul

set "PY="
py -3.11 -c "import sys" >nul 2>&1 && set "PY=py -3.11"
if not defined PY (
  py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
)
if not defined PY (
  echo Python 3.11 or 3.12 was not found. Install it with:
  echo     winget install Python.Python.3.11
  echo then run this script again.
  pause
  exit /b 1
)

if not exist ".venv-win\Scripts\python.exe" (
  echo Creating .venv-win ...
  %PY% -m venv .venv-win || (pause & exit /b 1)
)
".venv-win\Scripts\python.exe" -m pip install --upgrade pip || (pause & exit /b 1)
".venv-win\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)

where ffmpeg >nul 2>&1 || (
  echo.
  echo FFmpeg was not found. Install it with:
  echo     winget install Gyan.FFmpeg
  echo then reopen the terminal ^(PATH is refreshed only for new windows^).
)
echo.
echo Done. Start the app with "AI Interview.bat".
pause
