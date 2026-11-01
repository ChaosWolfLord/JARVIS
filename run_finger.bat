@echo off
rem Starts the camera-only finger tracker with a window showing what the camera sees.
rem Keep your hands out of view for the first second or two. Press q in the window to quit.
rem Extra options pass straight through, for example:  run_finger.bat --roi 0.15,0.05,0.85,0.7 --dwell 1.2
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set VENV=%LOCALAPPDATA%\jarvis\venv
if not exist "%VENV%\Scripts\python.exe" (
  echo Run run.bat once first, to set up the Python environment.
  pause
  exit /b 1
)
"%VENV%\Scripts\python.exe" -m pip install -q -r requirements-tracker.txt
"%VENV%\Scripts\python.exe" -W ignore -m tracker --mode finger --view %*
pause
