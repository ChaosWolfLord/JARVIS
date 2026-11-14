@echo off
rem Takes JARVIS out of the Start menu (and the Desktop, if install_shortcut.bat desktop put it there). JARVIS itself is not touched.
rem Add /quiet to skip the "press a key" at the end.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$gone = 0; foreach ($p in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) { $f = Join-Path $p 'JARVIS.lnk'; if (Test-Path $f) { Remove-Item $f; Write-Host ('Removed: ' + $f); $gone++ } };" ^
  "if ($gone -eq 0) { Write-Host 'There was no JARVIS shortcut to remove.' }"
if /i not "%~1"=="/quiet" pause
