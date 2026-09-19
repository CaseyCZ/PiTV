@echo off
setlocal EnableExtensions
title PiTV SD Installer

set "PITV_REPO=CaseyCZ/PiTV"
set "PITV_API=https://api.github.com/repos/%PITV_REPO%/releases/latest"
set "PITV_TMP=%TEMP%\PiTV-SD-Installer"
set "PITV_PS1=%PITV_TMP%\PiTV-SD-Installer.ps1"
set "PITV_SUMS=%PITV_TMP%\SHA256SUMS.txt"

if not exist "%PITV_TMP%" mkdir "%PITV_TMP%" >nul 2>&1

echo.
echo PiTV SD Installer
echo -----------------
echo Hledam nejnovější verzi na GitHubu...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$api='%PITV_API%';" ^
  "$tmp='%PITV_TMP%';" ^
  "$ps1='%PITV_PS1%';" ^
  "$sums='%PITV_SUMS%';" ^
  "try {" ^
  "  $r=Invoke-RestMethod -UseBasicParsing -Headers @{'User-Agent'='PiTV-SD-Installer'} -Uri $api;" ^
  "  $asset=$r.assets | Where-Object name -eq 'PiTV-SD-Installer.ps1' | Select-Object -First 1;" ^
  "  $sumAsset=$r.assets | Where-Object name -eq 'SHA256SUMS.txt' | Select-Object -First 1;" ^
  "  if(-not $asset -or -not $sumAsset){ throw 'Release neobsahuje požadované instalační soubory.' }" ^
  "  Invoke-WebRequest -UseBasicParsing -Headers @{'User-Agent'='PiTV-SD-Installer'} -Uri $asset.browser_download_url -OutFile $ps1;" ^
  "  Invoke-WebRequest -UseBasicParsing -Headers @{'User-Agent'='PiTV-SD-Installer'} -Uri $sumAsset.browser_download_url -OutFile $sums;" ^
  "  $line=Get-Content $sums | Where-Object { $_ -match '\s+PiTV-SD-Installer\.ps1$' } | Select-Object -First 1;" ^
  "  if(-not $line){ throw 'V SHA256SUMS chybí PiTV-SD-Installer.ps1.' }" ^
  "  $expected=($line -split '\s+')[0].ToLowerInvariant();" ^
  "  $actual=(Get-FileHash -Algorithm SHA256 $ps1).Hash.ToLowerInvariant();" ^
  "  if($actual -ne $expected){ Remove-Item $ps1 -Force -ErrorAction SilentlyContinue; throw 'SHA256 kontrola instalátoru selhala.' }" ^
  "  Write-Host ('Spouštím ' + $r.name + ' ...') -ForegroundColor Cyan;" ^
  "  exit 0" ^
  "} catch {" ^
  "  Write-Host ('CHYBA: ' + $_.Exception.Message) -ForegroundColor Red;" ^
  "  exit 1" ^
  "}"

if errorlevel 1 (
  echo.
  echo Nepodarilo se nacist overeny latest release.
  echo Zkus to znovu za chvili nebo stahni release rucne:
  echo https://github.com/%PITV_REPO%/releases/latest
  echo.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PITV_PS1%"
set "PITV_EXIT=%ERRORLEVEL%"

endlocal & exit /b %PITV_EXIT%
