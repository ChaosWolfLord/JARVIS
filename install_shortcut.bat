@echo off
rem Adds JARVIS to the Start menu, with its own icon, so you open it like any other app: press the Windows key and type JARVIS.
rem   install_shortcut.bat            the Start menu
rem   install_shortcut.bat desktop    the Start menu and a shortcut on the Desktop
rem Add /quiet to skip the "press a key" at the end. Undo it any time with remove_shortcut.bat. Nothing else on the PC is changed.
rem To keep JARVIS on the taskbar: open it from the Start menu, right-click its taskbar icon, Pin to taskbar (or right-click it in the Start menu, More, Pin to taskbar).
rem To start it when you sign in as well: install_autostart.bat.
set "WANT_DESKTOP=0"
set "QUIET=0"
for %%A in (%*) do (
  if /i "%%A"=="desktop" set "WANT_DESKTOP=1"
  if /i "%%A"=="/quiet" set "QUIET=1"
)
set "HERE=%~dp0"
set "WANT_DESKTOP_ARG=%WANT_DESKTOP%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$here = $env:HERE; $target = Join-Path $here 'JARVIS.bat'; $icon = Join-Path $here 'assets\JARVIS.ico';" ^
  "$places = @([Environment]::GetFolderPath('Programs')); if ($env:WANT_DESKTOP_ARG -eq '1') { $places += [Environment]::GetFolderPath('Desktop') };" ^
  "foreach ($p in $places) { $s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $p 'JARVIS.lnk')); $s.TargetPath = $target; $s.WorkingDirectory = $here.TrimEnd('\');" ^
  "  if (Test-Path $icon) { $s.IconLocation = $icon + ',0' }; $s.WindowStyle = 7; $s.Description = 'JARVIS: the projected AI whiteboard'; $s.Save(); Write-Host ('Added: ' + (Join-Path $p 'JARVIS.lnk')) }"
if not exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\JARVIS.lnk" (
  echo Couldn't create the shortcut.
) else (
  echo Done. Press the Windows key and type JARVIS.
)
if "%QUIET%"=="0" pause
