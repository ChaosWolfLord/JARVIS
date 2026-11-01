@echo off
rem One double-click: signs JARVIS in to Google again, with permission to save Gmail drafts and add calendar events.
rem Needs your browser in front of you: the sign-in page opens and this waits up to 10 minutes.
cd /d "%~dp0"
call "%~dp0connect.bat" google write
