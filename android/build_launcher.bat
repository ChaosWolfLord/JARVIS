@echo off
rem Builds JARVIS Home (the projector's home screen) and leaves it at %LOCALAPPDATA%\jarvis\app\jarvis-home.apk.
rem Needs Android Studio's Java and the Android SDK, which Android Studio installs. Install it on the projector with install_projector.bat.
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
call "%~dp0gradlew.bat" --no-daemon "-Dorg.gradle.projectcachedir=%LOCALAPPDATA%\jarvis-android\project-cache" :launcher:assembleRelease
if errorlevel 1 exit /b 1
if not exist "%LOCALAPPDATA%\jarvis\app" mkdir "%LOCALAPPDATA%\jarvis\app"
copy /y "%LOCALAPPDATA%\jarvis-android\build\launcher\outputs\apk\release\launcher-release.apk" "%LOCALAPPDATA%\jarvis\app\jarvis-home.apk" >nul
if errorlevel 1 exit /b 1
echo.
echo Built: %LOCALAPPDATA%\jarvis\app\jarvis-home.apk
echo Next: install_projector.bat
