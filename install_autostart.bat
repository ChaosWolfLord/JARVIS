@echo off
rem Makes JARVIS start by itself when you sign in to Windows (puts a shortcut in your Startup folder).
rem Undo it any time with remove_autostart.bat. Nothing else on the PC is changed.
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
powershell -NoProfile -Command "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%STARTUP%\JARVIS.lnk'); $s.TargetPath = '%~dp0JARVIS.bat'; $s.WorkingDirectory = '%~dp0'; $s.WindowStyle = 7; $s.Description = 'Starts JARVIS'; $s.Save()"
if exist "%STARTUP%\JARVIS.lnk" (
  echo JARVIS will now start when you sign in. Shortcut: %STARTUP%\JARVIS.lnk
) else (
  echo Couldn't create the shortcut.
)
pause
