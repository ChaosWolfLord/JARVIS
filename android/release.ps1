# Builds the app and publishes it as a GitHub release, which is what the website's Download button and the app's update check both read.
#   powershell -File android\release.ps1            (needs the GitHub CLI, signed in:  gh auth login)
# It reads the version from app\build.gradle.kts, uses android\release-notes\<version>.md as the release text (shown in the app's
# update dialog), and uploads the file as "jarvis.apk" (that exact name: the links depend on it).
# The app must always be built on THIS PC: Android only installs an update over an app signed with the same key, and the key is this PC's.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$gradle = Get-Content "app\build.gradle.kts" -Raw
$version = [regex]::Match($gradle, 'versionName\s*=\s*"([^"]+)"').Groups[1].Value
if (-not $version) { throw "Could not find versionName in app\build.gradle.kts" }
$tag = "v$version"

& gh release view $tag *> $null
if ($LASTEXITCODE -eq 0) { throw "Release $tag already exists. Raise versionName and versionCode in app\build.gradle.kts first." }

cmd /c "build.bat"
if ($LASTEXITCODE -ne 0) { throw "The build failed." }

$apk = Join-Path $env:LOCALAPPDATA "jarvis\app\jarvis.apk"
if (-not (Test-Path $apk)) { throw "Built file not found: $apk" }
$hash = (Get-FileHash $apk -Algorithm SHA256).Hash.ToLower()

$notesFile = Join-Path $PSScriptRoot "release-notes\$version.md"
$notes = if (Test-Path $notesFile) { (Get-Content $notesFile -Raw).Trim() } else { "JARVIS app $version." }
$notes += "`n`nSHA-256 of jarvis.apk: $hash"

$body = Join-Path $env:TEMP "jarvis-release-notes.md"
Set-Content -Path $body -Value $notes -Encoding utf8
& gh release create $tag $apk --title "JARVIS app $version" --notes-file $body
if ($LASTEXITCODE -ne 0) { throw "Publishing the release failed." }
Write-Output "Published $tag. The website and every phone with the app will see it."
