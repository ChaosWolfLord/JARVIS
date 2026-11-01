@echo off
rem Starts JARVIS and keeps it running: the board server (restarted if it stops), the full-screen board window,
rem and the pen tracker too if JARVIS_TRACKER_ARGS is set in .env. No console window stays open.
rem Run it again any time: if JARVIS is already running it just opens the board window.
rem   JARVIS_debug.bat  shows the log in a window.      JARVIS_stop.bat  stops everything.
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set VENV=%LOCALAPPDATA%\jarvis\venv
if not exist "%VENV%\Scripts\python.exe" (
  python -m venv "%VENV%"
  "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt
)
start "" "%VENV%\Scripts\pythonw.exe" -m server.supervisor %*
