@echo off
rem Stops JARVIS starting by itself when you sign in.
set "LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\JARVIS.lnk"
if exist "%LINK%" (
  del "%LINK%"
  echo Removed. JARVIS will no longer start by itself.
) else (
  echo JARVIS wasn't set to start by itself.
)
pause
