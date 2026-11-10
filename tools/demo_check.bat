@echo off
rem Run this a few minutes before showing JARVIS to people: it checks the AI, lights, speakers and network and says what to fix.
cd /d "%~dp0.."
set PYTHONDONTWRITEBYTECODE=1
"%LOCALAPPDATA%\jarvis\venv\Scripts\python.exe" tools\demo_check.py
pause
