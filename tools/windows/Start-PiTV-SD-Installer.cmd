@echo off
setlocal EnableExtensions
title PiTV SD Installer

set "PITV_REPO=CaseyCZ/PiTV"
set "PITV_API=https://api.github.com/repos/%PITV_REPO%/releases/latest"
set "PITV_TMP=%TEMP%\PiTV-SD-Installer"
set "PITV_ZIP=%PITV_TMP%\latest.zip"
set "PITV_APP=%PITV_TMP%\app"

if exist "%PITV_APP%" rmdir /s /q "%PITV_APP%" >nul 2>&1
if not exist "%PITV_TMP%" mkdir "%PITV_TMP%" >nul 2>&1
mkdir "%PITV_APP%" >nul 2>&1

echo.
echo PiTV SD Installer
echo -----------------
echo Kontroluji nejnovější verzi...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$api='%PITV_API%'; $zip='%PITV_ZIP%'; $app='%PITV_APP%';" ^
  "$r=Invoke-RestMethod -UseBasicParsing -Headers @{'User-Agent'='PiTV-SD-Installer'} -Uri $api;" ^
  "$asset=$r.assets | Where-Object { $_.name -match '^PiTV-SD-Installer-Windows-v.+\.zip$' } | Select-Object -First 1;" ^
  "if(-not $asset){ throw 'Nejnovější release neobsahuje PiTV SD Installer ZIP.' }" ^
  "Invoke-WebRequest -UseBasicParsing -Headers @{'User-Agent'='PiTV-SD-Installer'} -Uri $asset.browser_download_url -OutFile $zip;" ^
  "if($asset.digest -and $asset.digest -match '^sha256:(.+)$'){" ^
  "  $expected=$Matches[1].ToLowerInvariant(); $actual=(Get-FileHash -Algorithm SHA256 $zip).Hash.ToLowerInvariant();" ^
  "  if($actual -ne $expected){ Remove-Item $zip -Force -ErrorAction SilentlyContinue; throw 'SHA256 kontrola staženého balíčku selhala.' }" ^
  "}" ^
  "Expand-Archive -Path $zip -DestinationPath $app -Force;" ^
  "$installer=Get-ChildItem -Path $app -Filter 'PiTV-SD-Installer.ps1' -Recurse | Select-Object -First 1;" ^
  "if(-not $installer){ throw 'V balíčku chybí PiTV-SD-Installer.ps1.' }" ^
  "Set-Content -Path (Join-Path $app 'installer-path.txt') -Value $installer.FullName -Encoding ASCII;" ^
  "Write-Host ('Spouštím ' + $r.name + ' ...') -ForegroundColor Cyan;"

if errorlevel 1 (
  echo.
  echo Nepodarilo se nacist nejnovější PiTV SD Installer.
  echo Zkus to znovu nebo otevri:
  echo https://github.com/%PITV_REPO%/releases/latest
  echo.
  pause
  exit /b 1
)

set /p PITV_PS1=<"%PITV_APP%\installer-path.txt"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PITV_PS1%"
set "PITV_EXIT=%ERRORLEVEL%"

endlocal & exit /b %PITV_EXIT%
