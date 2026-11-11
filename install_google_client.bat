@echo off
rem Puts the Google "client" file you downloaded (client_secret_....json, usually in your Downloads folder) where JARVIS looks for it,
rem then tells you the next step. Double-click it; nothing is sent anywhere.
cd /d "%~dp0"
call "%~dp0connect.bat" install %*
