@echo off
rem The whole thing in one go: the JARVIS whiteboard plus finger tracking.
rem Opens the board in your browser (press F for fullscreen) and runs the camera tracker in this window.
rem Pinch thumb and index finger to draw, press and drag. First time: press K in the browser to calibrate.
rem Extra options pass to the tracker, e.g.  run_board.bat --zoom 200   or   run_board.bat --exposure -4 --gain 150
cd /d "%~dp0"
set PYTHONDONTWRITEBYTECODE=1
set VENV=%LOCALAPPDATA%\jarvis\venv
if not exist "%VENV%\Scripts\python.exe" (
  echo Run run.bat once first, to set up the Python environment.
  pause
  exit /b 1
)
"%VENV%\Scripts\python.exe" -m pip install -q -r requirements-tracker.txt

rem Start the board unless something is already listening on port 8000.
powershell -NoProfile -Command "try { (New-Object Net.Sockets.TcpClient).Connect('localhost', 8000); exit 0 } catch { exit 1 }"
if errorlevel 1 (
  start "JARVIS board" cmd /c "%~dp0run.bat"
  powershell -NoProfile -Command "for ($i = 0; $i -lt 30; $i++) { try { (New-Object Net.Sockets.TcpClient).Connect('localhost', 8000); exit 0 } catch { Start-Sleep 1 } }; exit 1"
)
"%VENV%\Scripts\python.exe" -W ignore -m tracker --mode finger --fast --view %*
pause

