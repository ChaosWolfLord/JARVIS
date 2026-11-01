@echo off
rem Same as JARVIS.bat, but in a window that shows what the server prints. Closing the window stops JARVIS.
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set VENV=%LOCALAPPDATA%\jarvis\venv
if not exist "%VENV%\Scripts\python.exe" (
  python -m venv "%VENV%"
  "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt
)
"%VENV%\Scripts\python.exe" -m server.supervisor %*
echo.
echo The log is in %LOCALAPPDATA%\jarvis\logs\jarvis.log
pause
