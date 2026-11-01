@echo off
rem Stops JARVIS (the server, the pen tracker if it was started with JARVIS.bat) but leaves the board window alone.
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
"%LOCALAPPDATA%\jarvis\venv\Scripts\python.exe" -m server.supervisor --stop
pause
