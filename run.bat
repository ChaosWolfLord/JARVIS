@echo off
rem Starts JARVIS. The Python environment lives outside OneDrive so it isn't synced.
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set VENV=%LOCALAPPDATA%\jarvis\venv
if not exist "%VENV%\Scripts\python.exe" (
  python -m venv "%VENV%"
  "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt
)
start "" http://localhost:8000
"%VENV%\Scripts\python.exe" -m uvicorn server.main:app --port 8000
