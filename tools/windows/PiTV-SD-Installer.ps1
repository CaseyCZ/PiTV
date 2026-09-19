#requires -Version 5.1
param(
    [switch]$SelfTestCatalog
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$RepoListUrl = "https://downloads.raspberrypi.com/os_list_imagingutility_v4.json"
$PiTVRepoUrl = "https://github.com/CaseyCZ/PiTV.git"

$LogDir = Join-Path $env:LOCALAPPDATA "PiTV\SD-Installer\logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$SessionLog = Join-Path $LogDir ("pitv-sd-installer-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
$script:WifiInternalUpdate = $false
$script:WifiPasswordSsid = ""
$script:LocalImagePath = ""

# Keep only the five most recent completed/current sessions.
Get-ChildItem $LogDir -Filter "pitv-sd-installer-*.log" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 4 |
    Remove-Item -Force -ErrorAction SilentlyContinue

function Is-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $SelfTestCatalog -and -not (Is-Admin)) {
    $ps = (Get-Process -Id $PID).Path
    $arg = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    Start-Process -FilePath $ps -ArgumentList $arg -Verb RunAs
    exit
}

function Get-ImagerPath {
    $pf86 = [Environment]::GetFolderPath("ProgramFilesX86")
    $paths = @(
        # Raspberry Pi Imager 2.x
        (Join-Path $env:ProgramFiles "Raspberry Pi Ltd\Imager\rpi-imager.exe"),
        (Join-Path $pf86 "Raspberry Pi Ltd\Imager\rpi-imager.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Raspberry Pi Ltd\Imager\rpi-imager.exe"),

        # Older Raspberry Pi Imager layouts
        (Join-Path $env:ProgramFiles "Raspberry Pi Imager\rpi-imager.exe"),
        (Join-Path $pf86 "Raspberry Pi Imager\rpi-imager.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Raspberry Pi Imager\rpi-imager.exe")
    )
    foreach ($p in $paths) {
        if ($p -and (Test-Path $p)) { return $p }
    }
    $cmd = Get-Command rpi-imager.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Ensure-Imager {
    $path = Get-ImagerPath
    if ($path) { return $path }

    $wingetExit = $null
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        try {
            Log "Raspberry Pi Imager nebyl nalezen. Zkouším instalaci přes winget..."
            $p = Start-Process -FilePath $winget.Source -ArgumentList @(
                "install",
                "--id","RaspberryPiFoundation.RaspberryPiImager",
                "-e",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--silent"
            ) -Wait -PassThru
            $wingetExit = $p.ExitCode
            $path = Get-ImagerPath
            if ($path) { return $path }
            Log ("winget nedokončil použitelnou instalaci (kód " + $p.ExitCode + ").")
        }
        catch {
            Log ("winget instalace selhala: " + $_.Exception.Message)
        }
    }

    $installer = Join-Path $env:TEMP ("rpi-imager-" + [guid]::NewGuid().ToString("N") + ".exe")
    try {
        Log "Zkouším přímou instalaci z oficiálního Raspberry Pi serveru..."
        Invoke-WebRequest -UseBasicParsing -Uri "https://downloads.raspberrypi.com/imager/imager_latest.exe" -OutFile $installer

        if (-not (Test-Path $installer) -or (Get-Item $installer).Length -lt 1MB) {
            throw "Stažený instalátor Raspberry Pi Imageru není platný."
        }

        $p = Start-Process -FilePath $installer -ArgumentList @(
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-"
        ) -Wait -PassThru

        if ($p.ExitCode -ne 0) {
            throw ("Oficiální instalátor skončil s kódem " + $p.ExitCode + ".")
        }

        Start-Sleep -Milliseconds 500
        $path = Get-ImagerPath
        if ($path) { return $path }

        throw "Raspberry Pi Imager se nainstaloval, ale rpi-imager.exe nebyl nalezen."
    }
    catch {
        $detail = $_.Exception.Message
        if ($null -ne $wingetExit) {
            $detail += " Winget kód: $wingetExit."
        }
        throw ("Automatická instalace Raspberry Pi Imageru selhala. " + $detail)
    }
    finally {
        Remove-Item $installer -Force -ErrorAction SilentlyContinue
    }
}
function Get-SafeDisks {
    try {
        $protected = @(Get-Partition | Where-Object { $_.IsBoot -or $_.IsSystem } |
            Select-Object -ExpandProperty DiskNumber -Unique)
        $disks = @(Get-Disk)
    }
    catch {
        throw "Windows neposkytl bezpečné informace o discích. Installer raději zápis zablokoval."
    }

    return @($disks | Where-Object {
        $_.Number -ne 0 -and
        $_.Number -notin $protected -and
        -not $_.IsBoot -and
        -not $_.IsSystem -and
        $_.OperationalStatus -ne "Offline" -and
        $_.Size -gt 1GB -and
        $_.BusType -in @("USB","SD","MMC")
    } | Sort-Object Number)
}

function Size-Text([UInt64]$n) {
    if ($n -ge 1TB) { return ("{0:N1} TB" -f ($n / 1TB)) }
    return ("{0:N1} GB" -f ($n / 1GB))
}

function Get-SavedWifiProfiles {
    $dir = Join-Path $env:TEMP ("pitv-wifi-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $dir | Out-Null
    $profiles = @()
    try {
        & netsh wlan export profile key=clear folder="$dir" | Out-Null
        foreach ($file in (Get-ChildItem $dir -Filter "*.xml" -ErrorAction SilentlyContinue)) {
            try {
                [xml]$xml = Get-Content $file.FullName -Raw
                $ssid = ""
                $ssidNodes = $xml.GetElementsByTagName("SSID")
                if ($ssidNodes.Count -gt 0) {
                    foreach ($child in $ssidNodes[0].ChildNodes) {
                        if ($child.LocalName -eq "name") {
                            $ssid = [string]$child.InnerText
                            break
                        }
                    }
                }
                if ([string]::IsNullOrWhiteSpace($ssid)) {
                    $nameNodes = $xml.GetElementsByTagName("name")
                    if ($nameNodes.Count -gt 0) { $ssid = [string]$nameNodes[0].InnerText }
                }
                if ([string]::IsNullOrWhiteSpace($ssid)) { continue }

                $password = ""
                $keyNodes = $xml.GetElementsByTagName("keyMaterial")
                if ($keyNodes.Count -gt 0) { $password = [string]$keyNodes[0].InnerText }

                $profiles += [pscustomobject]@{
                    SSID = $ssid.Trim()
                    Password = $password
                }
            } catch {}
        }
    }
    finally {
        Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
    }
    return @($profiles)
}

function Get-SavedWifiPassword([string]$ssid) {
    if ([string]::IsNullOrWhiteSpace($ssid)) { return "" }
    $profile = Get-SavedWifiProfiles | Where-Object { $_.SSID -eq $ssid } | Select-Object -First 1
    if ($profile) { return [string]$profile.Password }
    return ""
}

function Get-NearbyWifiSsids {
    $raw = (& netsh wlan show networks mode=bssid 2>$null) -join [Environment]::NewLine
    $items = New-Object System.Collections.Generic.List[string]
    foreach ($line in ($raw -split "\r?\n")) {
        $m = [regex]::Match($line, "^\s*SSID\s+\d+\s*:\s*(.*)\s*$", "IgnoreCase")
        if ($m.Success) {
            $ssid = $m.Groups[1].Value.Trim()
            if ($ssid -and -not $items.Contains($ssid)) { [void]$items.Add($ssid) }
        }
    }
    return @($items)
}

function Get-CurrentWifiSsid {
    $raw = (& netsh wlan show interfaces 2>$null) -join [Environment]::NewLine
    $m = [regex]::Match($raw, "(?im)^\s*SSID\s*:\s*(.+?)\s*$")
    if ($m.Success) { return $m.Groups[1].Value.Trim() }
    return ""
}

function Get-WifiChoices {
    $result = New-Object System.Collections.Generic.List[string]
    try {
        foreach ($ssid in (Get-NearbyWifiSsids)) {
            if ($ssid -and -not $result.Contains($ssid)) { [void]$result.Add($ssid) }
        }
    } catch {}

    try {
        foreach ($profile in (Get-SavedWifiProfiles)) {
            if ($profile.SSID -and -not $result.Contains($profile.SSID)) {
                [void]$result.Add($profile.SSID)
            }
        }
    } catch {}

    return @($result)
}

function Get-CurrentWifi {
    $ssid = Get-CurrentWifiSsid
    if (-not $ssid) { return $null }
    return [pscustomobject]@{
        SSID = $ssid
        Password = (Get-SavedWifiPassword $ssid)
    }
}

function Get-Prop($obj,[string]$name) {
    if ($null -eq $obj) { return $null }
    $p = $obj.PSObject.Properties[$name]
    if ($null -eq $p) { return $null }
    return $p.Value
}

function Expand-CatalogItem($item,[int]$depth=0) {
    if ($null -eq $item -or $depth -gt 8) { return @() }

    $all = @()
    $itemUrl = Get-Prop $item "url"
    $itemName = Get-Prop $item "name"
    if ($itemUrl -and $itemName) {
        $all += $item
    }

    $subitemsUrl = Get-Prop $item "subitems_url"
    if ($subitemsUrl) {
        try {
            $all += Get-Entries ([string]$subitemsUrl) ($depth + 1)
        } catch {
            Log ("Katalog subitems URL přeskočen: " + $_.Exception.Message)
        }
    }

    $subitems = Get-Prop $item "subitems"
    foreach ($sub in @($subitems)) {
        if ($null -ne $sub) {
            $all += Expand-CatalogItem $sub ($depth + 1)
        }
    }

    return $all
}

function Get-Entries([string]$url,[int]$depth=0) {
    if ($depth -gt 8) { return @() }

    $data = Invoke-RestMethod -Uri $url -UseBasicParsing
    $all = @()
    $osList = Get-Prop $data "os_list"
    if ($null -eq $osList) { return @() }

    foreach ($item in @($osList)) {
        $all += Expand-CatalogItem $item $depth
    }
    return $all
}

function Get-Ubuntu2404 {
    $entries = Get-Entries $RepoListUrl
    $list = $entries | Where-Object {
        $name = [string](Get-Prop $_ "name")
        $devices = Get-Prop $_ "devices"
        $name -match "^Ubuntu Server 24\.04(?:\.\d+)? LTS \(64-bit\)$" -and
        (-not $devices -or $devices -contains "pi4-64bit" -or $devices -contains "pi4-64" -or $devices -contains "pi4")
    } | Sort-Object @{ Expression={
        try {
            $releaseDate = Get-Prop $_ "release_date"
            if ($releaseDate) { [datetime]$releaseDate } else { [datetime]::MinValue }
        } catch { [datetime]::MinValue }
    } } -Descending

    $image = $list | Select-Object -First 1
    if (-not $image) { throw "Ubuntu Server 24.04 LTS pro Raspberry Pi 4 nebyl v oficiálním katalogu nalezen." }
    return $image
}

if ($SelfTestCatalog) {
    $image = Get-Ubuntu2404
    $name = [string](Get-Prop $image "name")
    $url = [string](Get-Prop $image "url")
    $devices = @(Get-Prop $image "devices")

    if (-not $name -or -not $url) {
        throw "Catalog self-test found an incomplete Ubuntu image entry."
    }
    if ($devices.Count -gt 0 -and $devices -notcontains "pi4-64bit") {
        throw "Catalog self-test image is not tagged for pi4-64bit."
    }

    Write-Host ("CATALOG SELF-TEST OK: " + $name)
    Write-Host ("Image host: " + ([Uri]$url).Host)
    exit 0
}

function Yaml-Q([string]$s) {
    return "'" + $s.Replace("'","''") + "'"
}

function New-Password {
    $b = New-Object byte[] 18
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($b) } finally { $rng.Dispose() }
    $v = [Convert]::ToBase64String($b).Replace("+","A").Replace("/","B").Replace("=","")
    return $v.Substring(0,[Math]::Min(20,$v.Length)) + "!9a"
}

function New-CloudInit([string]$ssid,[string]$wifiPass) {
    $dir = Join-Path $env:TEMP ("pitv-cloud-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory $dir | Out-Null
    $adminPass = New-Password

    $userData = @"
#cloud-config
hostname: pitv
manage_etc_hosts: true
ssh_pwauth: true
users:
  - name: pitvadmin
    groups: [adm, sudo]
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: false
package_update: true
packages:
  - git
runcmd:
  - [ bash, -lc, "echo 'pitvadmin:$adminPass' | chpasswd" ]
  - [ bash, -lc, "set -e; rm -rf /opt/pitv-bootstrap; git clone --depth 1 $PiTVRepoUrl /opt/pitv-bootstrap; cd /opt/pitv-bootstrap; ./install.sh > /var/log/pitv-firstboot.log 2>&1; mkdir -p /var/lib/pitv; touch /var/lib/pitv/firstboot-complete; rm -f /boot/firmware/user-data /boot/firmware/network-config || true; systemctl reboot" ]
"@

    $network = @"
version: 2
wifis:
  wlan0:
    dhcp4: true
    optional: true
    access-points:
      $(Yaml-Q $ssid):
        password: $(Yaml-Q $wifiPass)
"@

    $ud = Join-Path $dir "user-data"
    $nw = Join-Path $dir "network-config"
    $utf8 = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($ud,$userData,$utf8)
    [IO.File]::WriteAllText($nw,$network,$utf8)

    return [pscustomobject]@{ Dir=$dir; UserData=$ud; Network=$nw; Password=$adminPass }
}

function Q([string]$s) {
    return '"' + $s.Replace('"','\"') + '"'
}

function Get-VerifiedSafeDisk([int]$Number,[UInt64]$ExpectedSize,[string]$ExpectedName) {
    $candidate = Get-SafeDisks | Where-Object { $_.Number -eq $Number } | Select-Object -First 1
    if (-not $candidate) { throw "Vybraný disk už není dostupný jako bezpečný výměnný disk." }
    if ([UInt64]$candidate.Size -ne $ExpectedSize -or [string]$candidate.FriendlyName -ne $ExpectedName) {
        throw "Vybraný disk se od posledního načtení změnil. Obnov seznam a vyber kartu znovu."
    }
    return $candidate
}

function Format-SdDisk([int]$Number,[UInt64]$ExpectedSize,[string]$ExpectedName) {
    $null = Get-VerifiedSafeDisk $Number $ExpectedSize $ExpectedName

    Set-Disk -Number $Number -IsReadOnly $false
    Clear-Disk -Number $Number -RemoveData -Confirm:$false
    Start-Sleep -Milliseconds 500

    $state = Get-Disk -Number $Number
    if ($state.PartitionStyle -eq "RAW") {
        Initialize-Disk -Number $Number -PartitionStyle MBR | Out-Null
    }

    $part = New-Partition -DiskNumber $Number -UseMaximumSize -AssignDriveLetter
    $vol = $part | Format-Volume -FileSystem exFAT -NewFileSystemLabel "SDCARD" -Confirm:$false -Force
    return $vol
}

$form = New-Object Windows.Forms.Form
$form.Text = "PiTV SD Installer"
$form.Size = New-Object Drawing.Size(840,730)
$form.StartPosition = "CenterScreen"
$form.BackColor = [Drawing.Color]::FromArgb(7,11,20)
$form.ForeColor = [Drawing.Color]::White
$form.Font = New-Object Drawing.Font("Segoe UI",10)
$form.MaximizeBox = $false

$title = New-Object Windows.Forms.Label
$title.Text = "PiTV SD Installer"
$title.Font = New-Object Drawing.Font("Segoe UI",24,[Drawing.FontStyle]::Bold)
$title.Location = New-Object Drawing.Point(28,22)
$title.AutoSize = $true
$form.Controls.Add($title)

$sub = New-Object Windows.Forms.Label
$sub.Text = "Vyber systém a SD kartu. Zbytek připraví PiTV automaticky."
$sub.ForeColor = [Drawing.Color]::FromArgb(203,213,225)
$sub.Font = New-Object Drawing.Font("Segoe UI",11)
$sub.Location = New-Object Drawing.Point(31,66)
$sub.AutoSize = $true
$form.Controls.Add($sub)

function Add-Label($text,$y) {
    $l = New-Object Windows.Forms.Label
    $l.Text = $text
    $l.Location = New-Object Drawing.Point(32,$y)
    $l.Size = New-Object Drawing.Size(170,28)
    $form.Controls.Add($l)
}

Add-Label "Systém" 116
$os = New-Object Windows.Forms.ComboBox
$os.Location = New-Object Drawing.Point(205,112)
$os.Size = New-Object Drawing.Size(455,34)
$os.DropDownStyle = "DropDownList"
[void]$os.Items.Add("Ubuntu Server 24.04 LTS ARM64 — stáhnout online (doporučeno)")
$os.SelectedIndex = 0
$form.Controls.Add($os)

$imageBrowse = New-Object Windows.Forms.Button
$imageBrowse.Text = "Vlastní image..."
$imageBrowse.Location = New-Object Drawing.Point(675,111)
$imageBrowse.Size = New-Object Drawing.Size(130,34)
$imageBrowse.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($imageBrowse)

Add-Label "microSD / USB" 164
$disk = New-Object Windows.Forms.ComboBox
$disk.Location = New-Object Drawing.Point(205,160)
$disk.Size = New-Object Drawing.Size(455,34)
$disk.DropDownStyle = "DropDownList"
$form.Controls.Add($disk)

$refresh = New-Object Windows.Forms.Button
$refresh.Text = "Obnovit"
$refresh.Location = New-Object Drawing.Point(675,159)
$refresh.Size = New-Object Drawing.Size(130,34)
$refresh.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($refresh)

Add-Label "Wi-Fi SSID" 212
$wifiSsid = New-Object Windows.Forms.ComboBox
$wifiSsid.Location = New-Object Drawing.Point(205,208)
$wifiSsid.Size = New-Object Drawing.Size(455,32)
$wifiSsid.DropDownStyle = "DropDown"
$wifiSsid.AutoCompleteMode = "SuggestAppend"
$wifiSsid.AutoCompleteSource = "ListItems"
$form.Controls.Add($wifiSsid)

$wifiLoad = New-Object Windows.Forms.Button
$wifiLoad.Text = "Vyhledat"
$wifiLoad.Location = New-Object Drawing.Point(675,207)
$wifiLoad.Size = New-Object Drawing.Size(130,34)
$wifiLoad.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($wifiLoad)

Add-Label "Wi-Fi heslo" 254
$wifiPass = New-Object Windows.Forms.TextBox
$wifiPass.Location = New-Object Drawing.Point(205,250)
$wifiPass.Size = New-Object Drawing.Size(330,32)
$wifiPass.UseSystemPasswordChar = $true
$form.Controls.Add($wifiPass)

$wifiShow = New-Object Windows.Forms.CheckBox
$wifiShow.Text = "Zobrazit heslo"
$wifiShow.Location = New-Object Drawing.Point(550,251)
$wifiShow.Size = New-Object Drawing.Size(190,28)
$wifiShow.ForeColor = [Drawing.Color]::FromArgb(241,245,249)
$wifiShow.BackColor = $form.BackColor
$form.Controls.Add($wifiShow)

$wifiStatus = New-Object Windows.Forms.Label
$wifiStatus.Location = New-Object Drawing.Point(205,286)
$wifiStatus.Size = New-Object Drawing.Size(570,24)
$wifiStatus.ForeColor = [Drawing.Color]::FromArgb(203,213,225)
$wifiStatus.Text = "Zkouším načíst aktuální Wi-Fi z Windows..."
$form.Controls.Add($wifiStatus)

$info = New-Object Windows.Forms.Label
$info.Location = New-Object Drawing.Point(32,322)
$info.Size = New-Object Drawing.Size(773,54)
$info.Text = "BEZPEČNOST: systémový disk se nikdy nenabízí. Před zápisem znovu uvidíš model a kapacitu vybrané karty."
$info.ForeColor = [Drawing.Color]::FromArgb(226,232,240)
$info.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($info)

$log = New-Object Windows.Forms.TextBox
$log.Location = New-Object Drawing.Point(32,390)
$log.Size = New-Object Drawing.Size(773,150)
$log.Multiline = $true
$log.ReadOnly = $true
$log.ScrollBars = "Vertical"
$log.BackColor = [Drawing.Color]::FromArgb(11,18,32)
$log.ForeColor = [Drawing.Color]::FromArgb(203,213,225)
$form.Controls.Add($log)

$copyLog = New-Object Windows.Forms.Button
$copyLog.Text = "Kopírovat log"
$copyLog.Location = New-Object Drawing.Point(32,550)
$copyLog.Size = New-Object Drawing.Size(145,34)
$form.Controls.Add($copyLog)

$openLogs = New-Object Windows.Forms.Button
$openLogs.Text = "Otevřít logy"
$openLogs.Location = New-Object Drawing.Point(187,550)
$openLogs.Size = New-Object Drawing.Size(145,34)
$form.Controls.Add($openLogs)

$reportLog = New-Object Windows.Forms.Button
$reportLog.Text = "ODESLAT CHYBU"
$reportLog.Location = New-Object Drawing.Point(342,550)
$reportLog.Size = New-Object Drawing.Size(170,34)
$form.Controls.Add($reportLog)

$logPathLabel = New-Object Windows.Forms.Label
$logPathLabel.Location = New-Object Drawing.Point(530,555)
$logPathLabel.Size = New-Object Drawing.Size(275,24)
$logPathLabel.ForeColor = [Drawing.Color]::FromArgb(226,232,240)
$logPathLabel.Text = "Ukládá se 5 posledních logů"
$form.Controls.Add($logPathLabel)

$format = New-Object Windows.Forms.Button
$format.Text = "NAFORMÁTOVAT SD"
$format.Location = New-Object Drawing.Point(32,610)
$format.Size = New-Object Drawing.Size(245,52)
$format.BackColor = [Drawing.Color]::FromArgb(23,32,51)
$format.ForeColor = [Drawing.Color]::White
$format.FlatStyle = "Flat"
$format.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($format)

$create = New-Object Windows.Forms.Button
$create.Text = "VYTVOŘIT PiTV SD"
$create.Location = New-Object Drawing.Point(290,610)
$create.Size = New-Object Drawing.Size(515,52)
$create.BackColor = [Drawing.Color]::FromArgb(2,132,199)
$create.ForeColor = [Drawing.Color]::White
$create.FlatStyle = "Flat"
$create.Font = New-Object Drawing.Font("Segoe UI",12,[Drawing.FontStyle]::Bold)
$form.Controls.Add($create)

function Sanitize-LogText([string]$s) {
    if ($null -eq $s) { return "" }
    $out = [string]$s

    $replacements = @(
        @($env:USERPROFILE, "<USERPROFILE>"),
        @($env:LOCALAPPDATA, "<LOCALAPPDATA>"),
        @($env:TEMP, "<TEMP>"),
        @($env:ProgramFiles, "<PROGRAMFILES>"),
        @([Environment]::GetFolderPath("ProgramFilesX86"), "<PROGRAMFILES_X86>")
    )

    foreach ($pair in $replacements) {
        $from = [string]$pair[0]
        if ($from) {
            $out = $out.Replace($from, [string]$pair[1])
        }
    }

    if ($script:LocalImagePath) {
        $dir = Split-Path -Parent $script:LocalImagePath
        if ($dir) { $out = $out.Replace($dir, "<IMAGE_FOLDER>") }
    }

    return $out
}

function Log([string]$s) {
    $safe = Sanitize-LogText $s
    $line = (Get-Date -Format "HH:mm:ss") + "  " + $safe
    $log.AppendText($line + [Environment]::NewLine)
    $log.SelectionStart = $log.TextLength
    $log.ScrollToCaret()

    try {
        Add-Content -Path $SessionLog -Value $line -Encoding UTF8
    } catch {}

    [Windows.Forms.Application]::DoEvents()
}

function Copy-CurrentLog {
    try {
        $text = if (Test-Path $SessionLog) { Get-Content $SessionLog -Raw } else { $log.Text }
        if ([string]::IsNullOrWhiteSpace($text)) { return }
        [Windows.Forms.Clipboard]::SetText($text)
        Log "Log zkopírován do schránky."
    }
    catch {
        Log ("Kopírování logu selhalo: " + $_.Exception.Message)
    }
}

function Open-LogFolder {
    try {
        Start-Process explorer.exe -ArgumentList ('"' + $LogDir + '"')
    }
    catch {
        Log ("Otevření složky s logy selhalo: " + $_.Exception.Message)
    }
}

function Report-Problem {
    try {
        $raw = if (Test-Path $SessionLog) { Get-Content $SessionLog -Raw } else { $log.Text }
        if ([string]::IsNullOrWhiteSpace($raw)) {
            $raw = "Log zatím neobsahuje žádná data."
        }

        # Never place Wi-Fi network names into a public GitHub issue.
        $knownSsids = New-Object System.Collections.Generic.List[string]
        try {
            foreach ($name in (Get-WifiChoices)) {
                if ($name -and -not $knownSsids.Contains([string]$name)) {
                    [void]$knownSsids.Add([string]$name)
                }
            }
        } catch {}
        $currentSsid = $wifiSsid.Text.Trim()
        if ($currentSsid -and -not $knownSsids.Contains($currentSsid)) {
            [void]$knownSsids.Add($currentSsid)
        }
        foreach ($name in ($knownSsids | Sort-Object Length -Descending)) {
            if ($name) { $raw = $raw.Replace($name, "<SSID>") }
        }

        $lines = @($raw -split "\r?\n" | Where-Object { $_ })
        if ($lines.Count -gt 60) {
            $lines = $lines[($lines.Count-60)..($lines.Count-1)]
        }
        $diag = $lines -join [Environment]::NewLine

        $titleText = "[Alpha] PiTV SD Installer – automatický error report"
        $bodyText = @"
### PiTV SD Installer diagnostika

Installer: Alpha / Windows
Windows: $([Environment]::OSVersion.VersionString)
Čas: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

```text
$diag
```

> Automatický error report z PiTV SD Installeru. Log byl před odesláním zkrácen a všechna nalezená SSID byla skryta.
"@

        $url = "https://github.com/CaseyCZ/PiTV/issues/new?title=" +
            [Uri]::EscapeDataString($titleText) +
            "&body=" + [Uri]::EscapeDataString($bodyText)

        Start-Process $url
        Log "Připraven error report. V GitHubu klikni už jen na Submit new issue."
    }
    catch {
        Log ("Příprava hlášení selhala: " + $_.Exception.Message)
    }
}

function Refresh-Drives {
    $disk.Items.Clear()
    foreach ($d in (Get-SafeDisks)) {
        $o = [pscustomobject]@{
            Number=$d.Number
            Name=$d.FriendlyName
            Size=[UInt64]$d.Size
            Display=("Disk {0} · {1} · {2} · {3}" -f $d.Number,$d.FriendlyName,(Size-Text $d.Size),$d.BusType)
        }
        [void]$disk.Items.Add($o)
    }
    $disk.DisplayMember = "Display"
    if ($disk.Items.Count -eq 1) { $disk.SelectedIndex = 0 }
    Log ("Nalezeno bezpečných výměnných disků: " + $disk.Items.Count)
}

function Load-PasswordForSelectedWifi {
    $ssid = $wifiSsid.Text.Trim()
    if (-not $ssid) { return $false }

    try {
        $saved = Get-SavedWifiPassword $ssid
        if ($saved) {
            $wifiPass.Text = $saved
            $script:WifiPasswordSsid = $ssid
            $wifiStatus.Text = "Uložené heslo bylo načteno z Windows"
            Log "Uložené heslo pro vybranou Wi-Fi bylo načteno z Windows."
            return $true
        }
    } catch {}

    $wifiStatus.Text = "Síť vybrána · heslo zadej ručně"
    return $false
}

function Load-WifiFromWindows {
    try {
        $wifiStatus.Text = "Vyhledávám Wi-Fi sítě a uložené profily..."
        [Windows.Forms.Application]::DoEvents()

        $current = Get-CurrentWifiSsid
        $choices = @(Get-WifiChoices)

        $wifiSsid.Items.Clear()
        foreach ($ssid in $choices) { [void]$wifiSsid.Items.Add($ssid) }

        $script:WifiInternalUpdate = $true
        try {
            if ($current) {
                $wifiSsid.Text = $current
            } elseif ($choices.Count -gt 0 -and [string]::IsNullOrWhiteSpace($wifiSsid.Text)) {
                $wifiSsid.Text = [string]$choices[0]
            }
        }
        finally {
            $script:WifiInternalUpdate = $false
        }

        $wifiPass.Clear()
        $script:WifiPasswordSsid = ""

        if ($choices.Count -gt 0) {
            Log ("Nalezeno Wi-Fi sítí/profilů: " + $choices.Count)
            [void](Load-PasswordForSelectedWifi)
            if (-not $wifiPass.Text) {
                $wifiStatus.Text = ("Nalezeno " + $choices.Count + " sítí/profilů · vyber síť a zadej heslo")
            }
            return $true
        }

        $wifiStatus.Text = "Síť nebyla nalezena · SSID a heslo můžeš zadat ručně"
        return $false
    }
    catch {
        $wifiStatus.Text = "Vyhledání selhalo · SSID a heslo můžeš zadat ručně"
        Log ("Wi-Fi vyhledání: " + $_.Exception.Message)
        return $false
    }
}

function Select-LocalImage {
    $dialog = New-Object Windows.Forms.OpenFileDialog
    $dialog.Title = "Vyber vlastní Ubuntu Server image"
    $dialog.Filter = "Ubuntu / Raspberry Pi image (*.img;*.img.xz;*.xz;*.zip)|*.img;*.img.xz;*.xz;*.zip|Všechny soubory (*.*)|*.*"
    $dialog.CheckFileExists = $true
    $dialog.Multiselect = $false

    if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { return }

    $file = Get-Item $dialog.FileName
    if ($file.Length -lt 10MB) {
        [Windows.Forms.MessageBox]::Show(
            "Vybraný soubor je podezřele malý pro systémovou image.",
            "PiTV SD Installer",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
        return
    }

    $confirm = [Windows.Forms.MessageBox]::Show(
        "Vlastní image musí být kompatibilní s Raspberry Pi 4 a cloud-init, aby se automaticky nastavila Wi-Fi a nainstalovalo PiTV. Doporučená je Ubuntu Server 24.04 ARM64. Pokračovat?",
        "Vlastní Ubuntu image",
        [Windows.Forms.MessageBoxButtons]::YesNo,
        [Windows.Forms.MessageBoxIcon]::Information
    )
    if ($confirm -ne [Windows.Forms.DialogResult]::Yes) { return }

    $script:LocalImagePath = $file.FullName
    $name = $file.Name

    if ($os.Items.Count -gt 1) {
        $os.Items.RemoveAt(1)
    }
    [void]$os.Items.Add(("Vlastní Ubuntu image — " + $name))
    $os.SelectedIndex = 1

    Log ("Vlastní image vybrána: " + $name)
}

function Use-OfficialImage {
    $script:LocalImagePath = ""
    if ($os.Items.Count -gt 1) {
        $os.Items.RemoveAt(1)
    }
    $os.SelectedIndex = 0
    Log "Použití vlastní image bylo zrušeno. Použije se oficiální Ubuntu Server image."
}

$imageBrowse.Add_Click({
    if ($script:LocalImagePath) {
        $choice = [Windows.Forms.MessageBox]::Show(
            "Je vybraná vlastní image. Chceš vybrat jinou? Tlačítkem Ne se vrátíš k oficiální Ubuntu image.",
            "PiTV SD Installer",
            [Windows.Forms.MessageBoxButtons]::YesNoCancel,
            [Windows.Forms.MessageBoxIcon]::Question
        )
        if ($choice -eq [Windows.Forms.DialogResult]::Yes) { Select-LocalImage }
        elseif ($choice -eq [Windows.Forms.DialogResult]::No) { Use-OfficialImage }
    } else {
        Select-LocalImage
    }
})

$copyLog.Add_Click({ Copy-CurrentLog })
$openLogs.Add_Click({ Open-LogFolder })
$reportLog.Add_Click({ Report-Problem })

$wifiShow.Add_CheckedChanged({
    $wifiPass.UseSystemPasswordChar = -not $wifiShow.Checked
})

$wifiPass.Add_TextChanged({
    if ($wifiPass.Text) {
        $script:WifiPasswordSsid = $wifiSsid.Text.Trim()
    }
})

$wifiSsid.Add_TextChanged({
    if (-not $script:WifiInternalUpdate) {
        # Never carry a password from one SSID to another.
        if ($script:WifiPasswordSsid -ne $wifiSsid.Text.Trim()) {
            $wifiPass.Clear()
            $script:WifiPasswordSsid = ""
            $wifiStatus.Text = "Wi-Fi změněna · vyber síť nebo zadej heslo"
        }
    }
})

$wifiSsid.Add_SelectionChangeCommitted({
    $wifiPass.Clear()
    $script:WifiPasswordSsid = ""
    [void](Load-PasswordForSelectedWifi)
})

$wifiSsid.Add_Leave({
    $ssid = $wifiSsid.Text.Trim()
    if ($ssid -and -not $wifiPass.Text) {
        [void](Load-PasswordForSelectedWifi)
    }
})

$wifiLoad.Add_Click({ [void](Load-WifiFromWindows) })
$refresh.Add_Click({ Refresh-Drives })

$format.Add_Click({
    try {
        if (-not $disk.SelectedItem) { throw "Vyber microSD kartu." }
        $d = $disk.SelectedItem

        $answer = [Windows.Forms.MessageBox]::Show(
            ("Disk {0} · {1} · {2} bude KOMPLETNĚ SMAZÁN a vytvoří se jeden exFAT oddíl SDCARD. Pokračovat?" -f $d.Number,$d.Name,(Size-Text $d.Size)),
            "Naformátovat SD kartu",
            [Windows.Forms.MessageBoxButtons]::YesNo,
            [Windows.Forms.MessageBoxIcon]::Warning
        )
        if ($answer -ne [Windows.Forms.DialogResult]::Yes) { return }

        $format.Enabled = $false
        $create.Enabled = $false
        $refresh.Enabled = $false
        $wifiLoad.Enabled = $false
        $imageBrowse.Enabled = $false

        Log ("Formátuji Disk " + $d.Number + " · " + $d.Name + " · " + (Size-Text $d.Size))
        $vol = Format-SdDisk $d.Number $d.Size $d.Name
        Log ("HOTOVO. SDCARD " + (Size-Text ([UInt64]$vol.Size)) + " · exFAT")
        Refresh-Drives

        [Windows.Forms.MessageBox]::Show(
            "SD karta byla obnovena na jeden exFAT oddíl SDCARD přes celou dostupnou kapacitu.",
            "PiTV SD Installer",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    }
    catch {
        Log ("CHYBA: " + $_.Exception.Message)
        if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
            Log ("DETAIL: " + ($_.InvocationInfo.PositionMessage -replace "[\r\n]+"," "))
        }
        [Windows.Forms.MessageBox]::Show(
            $_.Exception.Message,
            "PiTV SD Installer",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    finally {
        $format.Enabled = $true
        $create.Enabled = $true
        $refresh.Enabled = $true
        $wifiLoad.Enabled = $true
        $imageBrowse.Enabled = $true
    }
})

$create.Add_Click({
    $cloud = $null
    try {
        if (-not $disk.SelectedItem) { throw "Vyber microSD kartu." }
        $d = $disk.SelectedItem

        $answer = [Windows.Forms.MessageBox]::Show(
            ("Disk {0} · {1} · {2} bude KOMPLETNĚ SMAZÁN. Pokračovat?" -f $d.Number,$d.Name,(Size-Text $d.Size)),
            "PiTV SD Installer",
            [Windows.Forms.MessageBoxButtons]::YesNo,
            [Windows.Forms.MessageBoxIcon]::Warning
        )
        if ($answer -ne [Windows.Forms.DialogResult]::Yes) { return }

        $format.Enabled = $false
        $create.Enabled = $false
        $refresh.Enabled = $false
        $wifiLoad.Enabled = $false
        $imageBrowse.Enabled = $false

        Log "Kontroluji Raspberry Pi Imager..."
        $imager = Ensure-Imager
        Log "Raspberry Pi Imager nalezen."

        $image = $null
        $imageSource = ""
        $imageSha = $null

        $useLocalImage = ($os.SelectedIndex -eq 1 -and $script:LocalImagePath)
        if ($useLocalImage) {
            if (-not (Test-Path $script:LocalImagePath -PathType Leaf)) {
                throw "Vybraná vlastní image už není dostupná. Vyber soubor znovu."
            }
            $imageSource = $script:LocalImagePath
            Log ("Použita vlastní image: " + (Split-Path -Leaf $script:LocalImagePath))
        }
        else {
            Log "Online režim: načítám oficiální Ubuntu Server 24.04 ARM64 image z katalogu..."
            $image = Get-Ubuntu2404
            Log ("Vybráno z katalogu: " + [string](Get-Prop $image "name"))
            $imageSource = [string](Get-Prop $image "url")
            $imageSha = Get-Prop $image "extract_sha256"
            if (-not $imageSource) { throw "Vybraný Ubuntu záznam neobsahuje URL image." }
        }

        $ssid = $wifiSsid.Text.Trim()
        $password = $wifiPass.Text
        if ([string]::IsNullOrWhiteSpace($ssid)) {
            throw "Zadej název cílové Wi-Fi (SSID). Můžeš ho napsat ručně nebo použít tlačítko Načíst."
        }
        if ([string]::IsNullOrWhiteSpace($password)) {
            throw "Zadej heslo cílové Wi-Fi."
        }
        if ($script:WifiPasswordSsid -and $script:WifiPasswordSsid -ne $ssid) {
            throw "Wi-Fi byla změněna, ale heslo patří předchozí síti. Vyber síť znovu nebo zadej správné heslo."
        }
        Log "Cílová Wi-Fi pro Raspberry Pi byla potvrzena."

        $cloud = New-CloudInit $ssid $password
        $target = "\\.\PhysicalDrive" + $d.Number

        $args = @(
            "--cli",
            "--disable-telemetry",
            "--cloudinit-userdata", $cloud.UserData,
            "--cloudinit-networkconfig", $cloud.Network
        )
        if ($imageSha) {
            $args += @("--sha256",[string]$imageSha)
        }
        $args += @([string]$imageSource,$target)

        $outFile = Join-Path $env:TEMP ("pitv-imager-" + [guid]::NewGuid().ToString("N") + ".log")
        $argText = ($args | ForEach-Object { Q ([string]$_) }) -join " "

        Log ("Zapisuji " + $target + ". Stažení a ověření může několik minut trvat.")
        $p = Start-Process -FilePath $imager -ArgumentList $argText -PassThru -RedirectStandardOutput $outFile -RedirectStandardError ($outFile + ".err")

        while (-not $p.HasExited) {
            [Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 250
        }

        if (Test-Path $outFile) {
            Get-Content $outFile | ForEach-Object { if ($_){ Log $_ } }
        }
        if (Test-Path ($outFile + ".err")) {
            Get-Content ($outFile + ".err") | ForEach-Object { if ($_){ Log $_ } }
        }
        Remove-Item $outFile,($outFile + ".err") -Force -ErrorAction SilentlyContinue

        if ($p.ExitCode -ne 0) { throw "Raspberry Pi Imager skončil s kódem " + $p.ExitCode }

        [Windows.Forms.Clipboard]::SetText($cloud.Password)
        Log "HOTOVO. PiTV SD je připravená."
        Log "Po prvním startu Ubuntu připojí Wi-Fi, stáhne PiTV, nainstaluje ho a restartuje Raspberry."
        Log ("Záložní účet: pitvadmin · heslo zkopírováno do schránky.")

        [Windows.Forms.MessageBox]::Show(
            "SD karta je připravená. Vlož ji do Raspberry Pi 4 a zapni ho. PiTV se nainstaluje samo při prvním startu. Záložní heslo účtu pitvadmin je ve schránce.",
            "PiTV SD Installer",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    }
    catch {
        Log ("CHYBA: " + $_.Exception.Message)
        if ($_.InvocationInfo -and $_.InvocationInfo.PositionMessage) {
            Log ("DETAIL: " + ($_.InvocationInfo.PositionMessage -replace "[\r\n]+"," "))
        }
        [Windows.Forms.MessageBox]::Show(
            $_.Exception.Message,
            "PiTV SD Installer",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    finally {
        if ($cloud -and $cloud.Dir) {
            Remove-Item $cloud.Dir -Recurse -Force -ErrorAction SilentlyContinue
        }
        $format.Enabled = $true
        $create.Enabled = $true
        $refresh.Enabled = $true
        $wifiLoad.Enabled = $true
        $imageBrowse.Enabled = $true
    }
})

$form.Add_Shown({
    Log "PiTV SD Installer v0.12 · Windows"
    Log "Zápis provádí oficiální Raspberry Pi Imager CLI."
    Log "Diagnostika aktivní · ukládá se posledních 5 relací."
    Refresh-Drives
    [void](Load-WifiFromWindows)
})

[void]$form.ShowDialog()
