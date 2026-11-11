@echo off
rem Puts JARVIS Home on the projector and makes it the home screen. The projector must be connected to this PC with a USB cable,
rem with USB debugging on (Settings > Developer options), and you must tap "Allow" the first time it asks.
rem   install_projector.bat            installs JARVIS Home and makes it the home screen
rem   install_projector.bat stock      gives the projector its own (Magcubic) home screen back
rem   install_projector.bat <ip:port>  uses a network address instead of the USB cable (adb connect)
setlocal
if not defined ANDROID_HOME set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
set "ADB=%ANDROID_HOME%\platform-tools\adb.exe"
set "APPS=%LOCALAPPDATA%\jarvis\app"
if not exist "%ADB%" (
  echo adb was not found at %ADB%. Install Android Studio, or set ANDROID_HOME.
  pause
  exit /b 1
)
for %%A in (%*) do (
  if /i "%%A"=="stock" goto stock
  echo %%A | findstr /r "[0-9]*\.[0-9]*\.[0-9]*\.[0-9]*:[0-9]" >nul && "%ADB%" connect %%A
)
"%ADB%" devices
"%ADB%" get-state >nul 2>nul
if errorlevel 1 (
  echo No projector found. Connect it with the USB cable, turn on USB debugging, and tap Allow if it asks.
  pause
  exit /b 1
)
if not exist "%APPS%\jarvis-home.apk" (
  echo JARVIS Home isn't built yet. Run build_launcher.bat first.
  pause
  exit /b 1
)
"%ADB%" install -r "%APPS%\jarvis-home.apk" || goto failed
"%ADB%" shell cmd package set-home-activity dev.jarvis.tv/.HomeActivity || goto failed
"%ADB%" shell input keyevent KEYCODE_HOME
echo.
echo Done: the projector's home screen is now JARVIS Home. To go back:  install_projector.bat stock
pause
exit /b 0

:stock
"%ADB%" shell cmd package set-home-activity com.htc.magcubicos/.activity.MainActivity || goto failed
"%ADB%" shell input keyevent KEYCODE_HOME
echo The projector's own home screen is back.
pause
exit /b 0

:failed
echo That did not work. Check that the projector is connected and has allowed this PC.
pause
exit /b 1
