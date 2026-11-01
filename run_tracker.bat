@echo off
rem Starts the IR pen tracker. Start run.bat first, then this. Extra options pass straight through, e.g.
rem   run_tracker.bat --source sim          (a pretend pen, to try the whole chain without hardware)
rem   run_tracker.bat --view                (shows what the camera sees)
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set VENV=%LOCALAPPDATA%\jarvis\venv
if not exist "%VENV%\Scripts\python.exe" (
  echo Run run.bat once first, to set up the Python environment.
  pause
  exit /b 1
)
"%VENV%\Scripts\python.exe" -m pip install -q -r requirements-tracker.txt
"%VENV%\Scripts\python.exe" -W ignore -m tracker %*
pause
