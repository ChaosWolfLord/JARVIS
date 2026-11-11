@echo off
rem One-time set-up for the Google (Calendar + Gmail) and Discord connections.
rem   connect.bat            (same as: connect.bat google)
rem   connect.bat google
rem   connect.bat discord
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set VENV=%LOCALAPPDATA%\jarvis\venv
if not exist "%VENV%\Scripts\python.exe" (
  echo Run run.bat once first, to set up the Python environment.
  pause
  exit /b 1
)
"%VENV%\Scripts\python.exe" -m server.connect %*
echo.
echo What is shown above is also saved in %LOCALAPPDATA%\jarvis\connect.log
pause
