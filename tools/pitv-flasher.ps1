# PiTV Flasher for Windows
# Writes Ubuntu Server 24.04 LTS ARM64 to an SD card and prepares zero-touch PiTV installation.
# Run from Windows PowerShell / Terminal. Requires administrator rights.

[CmdletBinding()]
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "== $Text ==" -ForegroundColor Cyan
}

function Fail([string]$Text) {
    Write-Host ""
    Write-Host "CHYBA: $Text" -ForegroundColor Red
    exit 1
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-Admin {
    if ($DryRun -or (Test-Admin)) { return }
    if (-not $PSCommandPath) {
        Fail "Spusť uložený skript jako správce."
    }
    Write-Host "PiTV Flasher potřebuje oprávnění správce pro zápis na SD kartu."
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $args
    exit
}

function Find-Imager {
    $cmd = Get-Command "rpi-imager.exe" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        "$env:ProgramFiles\Raspberry Pi Imager\rpi-imager.exe",
        "${env:ProgramFiles(x86)}\Raspberry Pi Imager\rpi-imager.exe",
        "$env:LOCALAPPDATA\Programs\Raspberry Pi Imager\rpi-imager.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }

    if ($candidates.Count -gt 0) { return $candidates[0] }

    $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Step "Instaluji oficiální Raspberry Pi Imager"
        & $winget.Source install --id RaspberryPiFoundation.RaspberryPiImager --exact --silent --accept-package-agreements --accept-source-agreements
        Start-Sleep -Seconds 2

        $candidates = @(
            "$env:ProgramFiles\Raspberry Pi Imager\rpi-imager.exe",
            "${env:ProgramFiles(x86)}\Raspberry Pi Imager\rpi-imager.exe",
            "$env:LOCALAPPDATA\Programs\Raspberry Pi Imager\rpi-imager.exe"
        ) | Where-Object { $_ -and (Test-Path $_) }
        if ($candidates.Count -gt 0) { return $candidates[0] }
    }

    Fail "Raspberry Pi Imager nebyl nalezen. Nainstaluj ho z https://www.raspberrypi.com/software/ a spusť skript znovu."
}

function Ensure-SshKey {
    $sshKeygen = Get-Command "ssh-keygen.exe" -ErrorAction SilentlyContinue
    if (-not $sshKeygen) {
        Write-Step "Instaluji Windows OpenSSH Client"
        Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0 | Out-Null
        $sshKeygen = Get-Command "ssh-keygen.exe" -ErrorAction SilentlyContinue
    }
    if (-not $sshKeygen) {
        Fail "Nelze najít ssh-keygen. OpenSSH Client je potřeba pro bezpečný recovery přístup bez hesla."
    }

    $sshDir = Join-Path $HOME ".ssh"
    if (-not (Test-Path $sshDir)) {
        New-Item -ItemType Directory -Path $sshDir | Out-Null
    }
    $keyPath = Join-Path $sshDir "pitv_ed25519"
    if (-not (Test-Path $keyPath)) {
        Write-Step "Vytvářím recovery SSH klíč"
        & $sshKeygen.Source -q -t ed25519 -f $keyPath -N "" -C "pitv-flasher"
        if ($LASTEXITCODE -ne 0) { Fail "Vytvoření SSH klíče selhalo." }
    }
    $pub = Get-Content "$keyPath.pub" -Raw
    return @{
        Private = $keyPath
        Public = $pub.Trim()
    }
}

function Get-UbuntuImage {
    Write-Step "Hledám aktuální Ubuntu Server 24.04 LTS ARM64 image"
    $base = "https://cdimage.ubuntu.com/releases/24.04/release"
    $sums = (Invoke-WebRequest -UseBasicParsing "$base/SHA256SUMS").Content
    $line = ($sums -split "`n" | Where-Object {
        $_ -match 'preinstalled-server-arm64\+raspi\.img\.xz\s*$'
    } | Select-Object -First 1)

    if (-not $line) {
        Fail "V oficiálním Ubuntu SHA256SUMS nebyl nalezen Raspberry Pi Server ARM64 image."
    }

    if ($line.Trim() -notmatch '^([a-fA-F0-9]{64})\s+\*?(.+)$') {
        Fail "Neznámý formát Ubuntu SHA256SUMS."
    }

    return @{
        Sha256 = $matches[1].ToLowerInvariant()
        File = $matches[2].Trim()
        Url = "$base/$($matches[2].Trim())"
    }
}

function Select-SdDisk {
    Write-Step "Dostupné výměnné disky"
    $disks = @(Get-Disk | Where-Object {
        $_.Size -gt 0 -and (
            $_.BusType -eq "USB" -or
            $_.BusType -eq "SD" -or
            $_.BusType -eq "MMC"
        )
    } | Sort-Object Number)

    if ($disks.Count -eq 0) {
        Fail "Nebyla nalezena SD karta ani výměnný USB disk. Zasuň čtečku s kartou a spusť skript znovu."
    }

    foreach ($d in $disks) {
        $gb = [Math]::Round($d.Size / 1GB, 1)
        Write-Host ("  [{0}] {1}  {2} GB  ({3})" -f $d.Number, $d.FriendlyName, $gb, $d.BusType)
    }

    $number = Read-Host "Zadej číslo disku SD karty"
    if ($number -notmatch '^\d+$') { Fail "Neplatné číslo disku." }

    $disk = $disks | Where-Object { $_.Number -eq [int]$number } | Select-Object -First 1
    if (-not $disk) { Fail "Vybraný disk není v seznamu výměnných disků." }

    $gb = [Math]::Round($disk.Size / 1GB, 1)
    Write-Host ""
    Write-Host "POZOR: CELÝ DISK BUDE SMAZÁN:" -ForegroundColor Yellow
    Write-Host ("Disk {0}: {1}, {2} GB" -f $disk.Number, $disk.FriendlyName, $gb) -ForegroundColor Yellow
    $expected = "SMAZAT DISK $($disk.Number)"
    $confirm = Read-Host "Pro potvrzení napiš přesně: $expected"
    if ($confirm -cne $expected) { Fail "Zápis zrušen." }

    return $disk
}

function Yaml-Quote([string]$Value) {
    return "'" + ($Value -replace "'", "''") + "'"
}

function SecureString-ToPlain([Security.SecureString]$Secure) {
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

function Get-BootVolume([int]$DiskNumber) {
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        try { Update-HostStorageCache } catch {}

        $parts = @(Get-Partition -DiskNumber $DiskNumber -ErrorAction SilentlyContinue)
        foreach ($p in $parts) {
            $v = $p | Get-Volume -ErrorAction SilentlyContinue
            if ($v -and ($v.FileSystemLabel -eq "system-boot" -or $v.FileSystem -eq "FAT32")) {
                if (-not $p.DriveLetter) {
                    $used = @(Get-Volume | Where-Object DriveLetter | ForEach-Object { [string]$_.DriveLetter })
                    $letter = @("P","Q","R","S","T","U","V","W","X","Y","Z") | Where-Object { $_ -notin $used } | Select-Object -First 1
                    if (-not $letter) { Fail "Není volné písmeno jednotky pro boot partition." }
                    Set-Partition -DiskNumber $DiskNumber -PartitionNumber $p.PartitionNumber -NewDriveLetter $letter | Out-Null
                    return "$letter`:"
                }
                return "$($p.DriveLetter):"
            }
        }
    }
    Fail "Po zápisu se nepodařilo připojit Ubuntu system-boot partition."
}

Ensure-Admin

Write-Host ""
Write-Host "PiTV Flasher 0.1 (Windows)" -ForegroundColor Cyan
Write-Host "Ubuntu Server 24.04 LTS ARM64 + automatická instalace PiTV"
Write-Host ""

if ($DryRun) {
    Write-Host "DRY RUN OK"
    exit 0
}

$imager = Find-Imager
$key = Ensure-SshKey
$image = Get-UbuntuImage
$disk = Select-SdDisk

Write-Step "Nastavení první instalace"
$ssid = Read-Host "Wi-Fi SSID"
if ([string]::IsNullOrWhiteSpace($ssid)) { Fail "Wi-Fi SSID nesmí být prázdné." }
$secureWifi = Read-Host "Wi-Fi heslo" -AsSecureString
$wifiPassword = SecureString-ToPlain $secureWifi
$hostname = Read-Host "Hostname [pitv]"
if ([string]::IsNullOrWhiteSpace($hostname)) { $hostname = "pitv" }
if ($hostname -notmatch '^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$') { Fail "Neplatný hostname." }
$adminUser = Read-Host "Recovery SSH uživatel [pitvadmin]"
if ([string]::IsNullOrWhiteSpace($adminUser)) { $adminUser = "pitvadmin" }
if ($adminUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { Fail "Neplatné Linux uživatelské jméno." }

Write-Step "Zapisuji oficiální Ubuntu image"
Write-Host $image.Url
Write-Host "SHA256: $($image.Sha256)"
$target = "\\.\PhysicalDrive$($disk.Number)"
& $imager --cli --sha256 $image.Sha256 $image.Url $target
if ($LASTEXITCODE -ne 0) { Fail "Raspberry Pi Imager zápis selhal." }

Write-Step "Připravuji Wi-Fi, SSH a automatickou instalaci PiTV"
$boot = Get-BootVolume -DiskNumber $disk.Number

$network = @"
version: 2
wifis:
  wlan0:
    dhcp4: true
    optional: true
    access-points:
      $(Yaml-Quote $ssid):
        password: $(Yaml-Quote $wifiPassword)
"@

$userDataTemplate = @'
#cloud-config
hostname: __HOSTNAME__
manage_etc_hosts: true
ssh_pwauth: false
disable_root: true

users:
  - default
  - name: __ADMINUSER__
    gecos: PiTV recovery administrator
    groups: [adm, sudo]
    shell: /bin/bash
    lock_passwd: true
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    ssh_authorized_keys:
      - __SSHKEY__

package_update: true
packages:
  - git
  - ca-certificates

write_files:
  - path: /usr/local/sbin/pitv-firstboot.sh
    owner: root:root
    permissions: '0755'
    content: |
      #!/usr/bin/env bash
      set -euo pipefail
      exec > >(tee -a /var/log/pitv-firstboot.log) 2>&1
      echo "== PiTV first boot installer =="
      rm -rf /opt/PiTV-src
      git clone --depth 1 https://github.com/CaseyCZ/PiTV.git /opt/PiTV-src
      cd /opt/PiTV-src
      ./install.sh
      mkdir -p /var/lib/pitv
      touch /var/lib/pitv/firstboot-complete
      rm -f /boot/firmware/user-data /boot/firmware/network-config || true
      echo "== PiTV first boot complete =="

runcmd:
  - [bash, /usr/local/sbin/pitv-firstboot.sh]

power_state:
  delay: now
  mode: reboot
  message: "PiTV installation complete - rebooting"
  condition: true
'@

$userData = $userDataTemplate.
    Replace("__HOSTNAME__", $hostname).
    Replace("__ADMINUSER__", $adminUser).
    Replace("__SSHKEY__", $key.Public)

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path "$boot\" "user-data"), $userData, $utf8NoBom)
[IO.File]::WriteAllText((Join-Path "$boot\" "network-config"), $network, $utf8NoBom)

$wifiPassword = $null
$secureWifi.Dispose()

Write-Step "Hotovo"
Write-Host "SD karta je připravena." -ForegroundColor Green
Write-Host ""
Write-Host "1. BezpečnĘ vysuň SD kartu a vlož ji do Raspberry Pi 4."
Write-Host "2. Připoj HDMI a napájení."
Write-Host "3. První boot může trvat přibližně 10-30 minut."
Write-Host "4. Ubuntu se připojí na Wi-Fi, samo nainstaluje PiTV a jednou se restartuje."
Write-Host "5. Potom se má PiTV automaticky zobrazit na TV."
Write-Host ""
Write-Host "Recovery SSH:"
Write-Host "  ssh -i `"$($key.Private)`" $adminUser@$hostname.local"
Write-Host ""
Write-Host "Pokud první instalace selže, log je na Pi v /var/log/pitv-firstboot.log"
