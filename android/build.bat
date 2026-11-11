@echo off
rem Builds the JARVIS Android app and puts the file where the PC offers it to a phone that is being paired
rem (%LOCALAPPDATA%\jarvis\app\jarvis.apk). Needs Android Studio's Java and the Android SDK, which Android Studio installs.
rem Everything it generates goes under %LOCALAPPDATA%\jarvis-android, not into this folder.
rem   build.bat          the normal build (not debuggable)
rem   build.bat debug    a debug build, which can be inspected from the PC while it runs in the emulator (used for testing)
cd /d "%~dp0"
if not defined JAVA_HOME set "JAVA_HOME=C:\Program Files\Android\Android Studio\jbr"
if not defined ANDROID_HOME set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
if not exist "%JAVA_HOME%\bin\java.exe" (
  echo Java was not found at %JAVA_HOME%. Install Android Studio, or set JAVA_HOME.
  exit /b 1
)
if not exist "%ANDROID_HOME%\platforms" (
  echo The Android SDK was not found at %ANDROID_HOME%. Install Android Studio, or set ANDROID_HOME.
  exit /b 1
)
set "KIND=Release"
set "OUT=release\app-release.apk"
if /i "%~1"=="debug" (
  set "KIND=Debug"
  set "OUT=debug\app-debug.apk"
)
call "%~dp0gradlew.bat" --no-daemon "-Dorg.gradle.projectcachedir=%LOCALAPPDATA%\jarvis-android\project-cache" :app:assemble%KIND%
if errorlevel 1 exit /b 1
if not exist "%LOCALAPPDATA%\jarvis\app" mkdir "%LOCALAPPDATA%\jarvis\app"
copy /y "%LOCALAPPDATA%\jarvis-android\build\app\outputs\apk\%OUT%" "%LOCALAPPDATA%\jarvis\app\jarvis.apk" >nul
echo.
echo Built (%KIND%): %LOCALAPPDATA%\jarvis\app\jarvis.apk
echo On the PC press "Show pairing code" (status menu, Phone), then open the phone page on the phone and choose "Get the Android app".
