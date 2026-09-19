#requires -Version 5.1
param(
    [switch]$SelfTestCatalog
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Net.Http

$RepoListUrl = "https://downloads.raspberrypi.com/os_list_imagingutility_v4.json"
$PiTVRepoUrl = "https://github.com/CaseyCZ/PiTV.git"

$LogDir = Join-Path $env:LOCALAPPDATA "PiTV\SD-Installer\logs"
$ImageCacheDir = Join-Path $env:LOCALAPPDATA "PiTV\images"
$WorkDir = Join-Path $env:LOCALAPPDATA "PiTV\SD-Installer\work"
New-Item -ItemType Directory -Path $LogDir,$ImageCacheDir,$WorkDir -Force | Out-Null
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

function Get-Ubuntu2404([string]$deviceTag = "pi4-64bit") {
    $supportedTags = @("pi3-64bit","pi4-64bit","pi5-64bit")
    if ($deviceTag -notin $supportedTags) {
        throw ("Nepodporovaný Raspberry Pi device tag: " + $deviceTag)
    }

    $entries = Get-Entries $RepoListUrl
    $list = $entries | Where-Object {
        $name = [string](Get-Prop $_ "name")
        $devices = @(Get-Prop $_ "devices")
        $name -match "^Ubuntu Server 24\.04(?:\.\d+)? LTS \(64-bit\)$" -and
        ($devices -contains $deviceTag)
    } | Sort-Object @{ Expression={
        try {
            $releaseDate = Get-Prop $_ "release_date"
            if ($releaseDate) { [datetime]$releaseDate } else { [datetime]::MinValue }
        } catch { [datetime]::MinValue }
    } } -Descending

    $image = $list | Select-Object -First 1
    if (-not $image) {
        throw ("Ubuntu Server 24.04 LTS pro " + $deviceTag + " nebyl v oficiálním katalogu nalezen.")
    }
    return $image
}

if ($SelfTestCatalog) {
    foreach ($tag in @("pi3-64bit","pi4-64bit","pi5-64bit")) {
        $image = Get-Ubuntu2404 $tag
        $name = [string](Get-Prop $image "name")
        $url = [string](Get-Prop $image "url")
        $devices = @(Get-Prop $image "devices")

        if (-not $name -or -not $url) {
            throw ("Catalog self-test found an incomplete Ubuntu image entry for " + $tag + ".")
        }
        if ($devices -notcontains $tag) {
            throw ("Catalog self-test image is not tagged for " + $tag + ".")
        }

        Write-Host ("CATALOG SELF-TEST OK [" + $tag + "]: " + $name)
        Write-Host ("Image host: " + ([Uri]$url).Host)
    }
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

function Get-VerifiedSafeDisk([int]$Number,[UInt64]$ExpectedSize,[string]$ExpectedName,[string]$ExpectedIdentity="") {
    $candidate = Get-SafeDisks | Where-Object { $_.Number -eq $Number } | Select-Object -First 1
    if (-not $candidate) { throw "Vybraný disk už není dostupný jako bezpečný výměnný disk." }
    if ([UInt64]$candidate.Size -ne $ExpectedSize -or [string]$candidate.FriendlyName -ne $ExpectedName) {
        throw "Vybraný disk se od posledního načtení změnil. Obnov seznam a vyber kartu znovu."
    }

    $candidateIdentity = if ($candidate.UniqueId) { [string]$candidate.UniqueId } elseif ($candidate.SerialNumber) { [string]$candidate.SerialNumber } else { "" }
    if ($ExpectedIdentity -and $candidateIdentity -and $candidateIdentity -ne $ExpectedIdentity) {
        throw "Identita vybraného disku se změnila. Zápis byl z bezpečnostních důvodů zablokován."
    }
    return $candidate
}

function Format-SdDisk([int]$Number,[UInt64]$ExpectedSize,[string]$ExpectedName,[string]$ExpectedIdentity="") {
    $null = Get-VerifiedSafeDisk $Number $ExpectedSize $ExpectedName $ExpectedIdentity

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

$enginePath = Join-Path $PSScriptRoot "PiTV-ImageEngine.ps1"
if (-not (Test-Path $enginePath -PathType Leaf)) {
    throw "Chybí PiTV-ImageEngine.ps1. Rozbal celý instalační ZIP, ne jen hlavní skript."
}
. $enginePath

$form = New-Object Windows.Forms.Form
$form.Text = "PiTV SD Installer"
$form.Size = New-Object Drawing.Size(840,790)
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
$sub.Text = "Vyber Raspberry, systém a kartu. Image PiTV najde online nebo použije uloženou kopii."
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

Add-Label "Raspberry Pi" 116
$piModel = New-Object Windows.Forms.ComboBox
$piModel.Location = New-Object Drawing.Point(205,112)
$piModel.Size = New-Object Drawing.Size(600,34)
$piModel.DropDownStyle = "DropDownList"
[void]$piModel.Items.Add("Raspberry Pi 3 / 3B+ — Alpha · omezený výkon")
[void]$piModel.Items.Add("Raspberry Pi 4 — doporučeno")
[void]$piModel.Items.Add("Raspberry Pi 5 — Alpha · hardware zatím neověřen")
$piModel.SelectedIndex = 1
$form.Controls.Add($piModel)

Add-Label "Systém" 164
$os = New-Object Windows.Forms.ComboBox
$os.Location = New-Object Drawing.Point(205,160)
$os.Size = New-Object Drawing.Size(455,34)
$os.DropDownStyle = "DropDownList"
[void]$os.Items.Add("Ubuntu Server 24.04 LTS ARM64 — online / uložená cache (doporučeno)")
$os.SelectedIndex = 0
$form.Controls.Add($os)

$imageBrowse = New-Object Windows.Forms.Button
$imageBrowse.Text = "Vlastní image..."
$imageBrowse.Location = New-Object Drawing.Point(675,159)
$imageBrowse.Size = New-Object Drawing.Size(130,34)
$imageBrowse.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($imageBrowse)

Add-Label "microSD / USB" 212
$disk = New-Object Windows.Forms.ComboBox
$disk.Location = New-Object Drawing.Point(205,208)
$disk.Size = New-Object Drawing.Size(455,34)
$disk.DropDownStyle = "DropDownList"
$form.Controls.Add($disk)

$refresh = New-Object Windows.Forms.Button
$refresh.Text = "Obnovit"
$refresh.Location = New-Object Drawing.Point(675,207)
$refresh.Size = New-Object Drawing.Size(130,34)
$refresh.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($refresh)

Add-Label "Wi-Fi SSID" 260
$wifiSsid = New-Object Windows.Forms.ComboBox
$wifiSsid.Location = New-Object Drawing.Point(205,256)
$wifiSsid.Size = New-Object Drawing.Size(455,32)
$wifiSsid.DropDownStyle = "DropDown"
$wifiSsid.AutoCompleteMode = "SuggestAppend"
$wifiSsid.AutoCompleteSource = "ListItems"
$form.Controls.Add($wifiSsid)

$wifiLoad = New-Object Windows.Forms.Button
$wifiLoad.Text = "Vyhledat"
$wifiLoad.Location = New-Object Drawing.Point(675,255)
$wifiLoad.Size = New-Object Drawing.Size(130,34)
$wifiLoad.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($wifiLoad)

Add-Label "Wi-Fi heslo" 302
$wifiPass = New-Object Windows.Forms.TextBox
$wifiPass.Location = New-Object Drawing.Point(205,298)
$wifiPass.Size = New-Object Drawing.Size(330,32)
$wifiPass.UseSystemPasswordChar = $true
$form.Controls.Add($wifiPass)

$wifiShow = New-Object Windows.Forms.CheckBox
$wifiShow.Text = "Zobrazit heslo"
$wifiShow.Location = New-Object Drawing.Point(550,299)
$wifiShow.Size = New-Object Drawing.Size(190,28)
$wifiShow.ForeColor = [Drawing.Color]::FromArgb(241,245,249)
$wifiShow.BackColor = $form.BackColor
$form.Controls.Add($wifiShow)

$wifiStatus = New-Object Windows.Forms.Label
$wifiStatus.Location = New-Object Drawing.Point(205,334)
$wifiStatus.Size = New-Object Drawing.Size(570,24)
$wifiStatus.ForeColor = [Drawing.Color]::FromArgb(203,213,225)
$wifiStatus.Text = "Zkouším načíst aktuální Wi-Fi z Windows..."
$form.Controls.Add($wifiStatus)

$info = New-Object Windows.Forms.Label
$info.Location = New-Object Drawing.Point(32,370)
$info.Size = New-Object Drawing.Size(773,54)
$info.Text = "BEZPEČNOST: systémový disk se nikdy nenabízí. Před zápisem znovu uvidíš model a kapacitu vybrané karty."
$info.ForeColor = [Drawing.Color]::FromArgb(226,232,240)
$info.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($info)

$progressLabel = New-Object Windows.Forms.Label
$progressLabel.Location = New-Object Drawing.Point(32,414)
$progressLabel.Size = New-Object Drawing.Size(773,20)
$progressLabel.ForeColor = [Drawing.Color]::FromArgb(125,211,252)
$progressLabel.Text = "Připraveno"
$form.Controls.Add($progressLabel)

$progress = New-Object Windows.Forms.ProgressBar
$progress.Location = New-Object Drawing.Point(32,438)
$progress.Size = New-Object Drawing.Size(773,16)
$progress.Minimum = 0
$progress.Maximum = 100
$progress.Value = 0
$form.Controls.Add($progress)

$log = New-Object Windows.Forms.TextBox
$log.Location = New-Object Drawing.Point(32,466)
$log.Size = New-Object Drawing.Size(773,122)
$log.Multiline = $true
$log.ReadOnly = $true
$log.ScrollBars = "Vertical"
$log.BackColor = [Drawing.Color]::FromArgb(11,18,32)
$log.ForeColor = [Drawing.Color]::FromArgb(203,213,225)
$form.Controls.Add($log)

$copyLog = New-Object Windows.Forms.Button
$copyLog.Text = "Kopírovat log"
$copyLog.Location = New-Object Drawing.Point(32,598)
$copyLog.Size = New-Object Drawing.Size(145,34)
$form.Controls.Add($copyLog)

$openLogs = New-Object Windows.Forms.Button
$openLogs.Text = "Otevřít logy"
$openLogs.Location = New-Object Drawing.Point(187,598)
$openLogs.Size = New-Object Drawing.Size(145,34)
$form.Controls.Add($openLogs)

$reportLog = New-Object Windows.Forms.Button
$reportLog.Text = "ODESLAT CHYBU"
$reportLog.Location = New-Object Drawing.Point(342,598)
$reportLog.Size = New-Object Drawing.Size(170,34)
$form.Controls.Add($reportLog)

$logPathLabel = New-Object Windows.Forms.Label
$logPathLabel.Location = New-Object Drawing.Point(530,603)
$logPathLabel.Size = New-Object Drawing.Size(275,24)
$logPathLabel.ForeColor = [Drawing.Color]::FromArgb(226,232,240)
$logPathLabel.Text = "Ukládá se 5 posledních logů"
$form.Controls.Add($logPathLabel)

$format = New-Object Windows.Forms.Button
$format.Text = "NAFORMÁTOVAT SD"
$format.Location = New-Object Drawing.Point(32,658)
$format.Size = New-Object Drawing.Size(245,52)
$format.BackColor = [Drawing.Color]::FromArgb(23,32,51)
$format.ForeColor = [Drawing.Color]::White
$format.FlatStyle = "Flat"
$format.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($format)

$create = New-Object Windows.Forms.Button
$create.Text = "VYTVOŘIT PiTV SD"
$create.Location = New-Object Drawing.Point(290,658)
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


function Set-InstallerProgress([string]$stage,[int]$percent) {
    if ($percent -lt 0) { $percent = 0 }
    if ($percent -gt 100) { $percent = 100 }

    $progressLabel.Text = $stage
    $progress.Value = $percent
    [Windows.Forms.Application]::DoEvents()
}

function Log-ExceptionDetails($record,[string]$context="") {
    if ($null -eq $record) { return }
    $prefix = if ($context) { "DETAIL[" + $context + "]" } else { "DETAIL" }

    try {
        if ($record.Exception) {
            Log ($prefix + " typ: " + $record.Exception.GetType().FullName)
            Log ($prefix + " zpráva: " + $record.Exception.Message)
            Log ($prefix + " HResult: " + $record.Exception.HResult)

            $inner = $record.Exception.InnerException
            $depth = 0
            while ($inner -and $depth -lt 5) {
                $depth++
                Log ($prefix + " inner " + $depth + ": " + $inner.GetType().FullName + " · " + $inner.Message)
                $inner = $inner.InnerException
            }
        }

        if ($record.FullyQualifiedErrorId) { Log ($prefix + " error id: " + $record.FullyQualifiedErrorId) }
        if ($record.CategoryInfo) { Log ($prefix + " category: " + [string]$record.CategoryInfo) }
        if ($record.ScriptStackTrace) { Log ($prefix + " stack: " + ($record.ScriptStackTrace -replace "[\r\n]+"," | ")) }

        if ($record.InvocationInfo) {
            $inv = $record.InvocationInfo
            if ($inv.MyCommand) { Log ($prefix + " command: " + [string]$inv.MyCommand) }
            if ($inv.ScriptLineNumber) { Log ($prefix + " line: " + $inv.ScriptLineNumber + " · column: " + $inv.OffsetInLine) }
            if ($inv.Line) { Log ($prefix + " source: " + ([string]$inv.Line).Trim()) }
            if ($inv.PositionMessage) { Log ($prefix + " position: " + ($inv.PositionMessage -replace "[\r\n]+"," | ")) }
        }
    }
    catch {
        Log ($prefix + " diagnostika výjimky selhala: " + $_.Exception.Message)
    }
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
        if ($lines.Count -gt 120) {
            $lines = $lines[($lines.Count-120)..($lines.Count-1)]
        }
        $diag = $lines -join [Environment]::NewLine

        $titleText = "[Alpha] PiTV SD Installer – automatický error report"
        $bodyText = @"
### PiTV SD Installer diagnostika

Installer: Alpha / Windows
Windows: $([Environment]::OSVersion.VersionString)
Čas: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

~~~text
$diag
~~~

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
            Identity=$(if ($d.UniqueId) { [string]$d.UniqueId } elseif ($d.SerialNumber) { [string]$d.SerialNumber } else { "" })
            Display=("Disk {0} · {1} · {2} · {3}" -f $d.Number,$d.FriendlyName,(Size-Text $d.Size),$d.BusType)
        }
        [void]$disk.Items.Add($o)
    }
    $disk.DisplayMember = "Display"
    if ($disk.Items.Count -eq 1) { $disk.SelectedIndex = 0 }
    Log ("Nalezeno bezpečných výměnných disků: " + $disk.Items.Count)
    foreach ($item in @($disk.Items)) {
        Log ("DISK: " + $item.Display)
    }
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

function Get-SelectedPiTag {
    switch ($piModel.SelectedIndex) {
        0 { return "pi3-64bit" }
        1 { return "pi4-64bit" }
        2 { return "pi5-64bit" }
        default { throw "Vyber model Raspberry Pi." }
    }
}

function Get-SelectedPiName {
    switch ($piModel.SelectedIndex) {
        0 { return "Raspberry Pi 3 / 3B+" }
        1 { return "Raspberry Pi 4" }
        2 { return "Raspberry Pi 5" }
        default { return "Raspberry Pi" }
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
        ("Vlastní image musí být kompatibilní se zvoleným " + (Get-SelectedPiName) + " a cloud-init, aby se automaticky nastavila Wi-Fi a nainstalovalo PiTV. Doporučená je Ubuntu Server 24.04 ARM64. Pokračovat?"),
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
        $piModel.Enabled = $false

        Log ("Formátuji Disk " + $d.Number + " · " + $d.Name + " · " + (Size-Text $d.Size))
        $vol = Format-SdDisk $d.Number $d.Size $d.Name $d.Identity
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
        Log-ExceptionDetails $_ "FORMÁTOVÁNÍ"
        Set-InstallerProgress "Chyba při formátování" 0
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
        $piModel.Enabled = $true
    }
})

$create.Add_Click({
    $cloud = $null
    $prepared = $null
    try {
        if (-not $disk.SelectedItem) { throw "Vyber microSD kartu." }
        $d = $disk.SelectedItem
        $piName = Get-SelectedPiName
        $piTag = Get-SelectedPiTag
        $nl = [Environment]::NewLine

        $warningText = $piName + $nl + "Disk " + $d.Number + " · " + $d.Name + " · " + (Size-Text $d.Size) + " bude KOMPLETNĚ PŘEPSÁN." + $nl + $nl + "Pokračovat?"
        $answer = [Windows.Forms.MessageBox]::Show(
            $warningText,
            "Vytvořit PiTV SD",
            [Windows.Forms.MessageBoxButtons]::YesNo,
            [Windows.Forms.MessageBoxIcon]::Warning
        )
        if ($answer -ne [Windows.Forms.DialogResult]::Yes) { return }

        $format.Enabled = $false
        $create.Enabled = $false
        $refresh.Enabled = $false
        $wifiLoad.Enabled = $false
        $imageBrowse.Enabled = $false
        $piModel.Enabled = $false
        $os.Enabled = $false

        Set-InstallerProgress "Kontroluji nastavení" 0
        Log ("Cílový model: " + $piName)
        Log ("Cílový disk: Disk " + $d.Number + " · " + $d.Name + " · " + (Size-Text $d.Size))
        $null = Get-VerifiedSafeDisk $d.Number $d.Size $d.Name $d.Identity

        $ssid = $wifiSsid.Text.Trim()
        $password = $wifiPass.Text
        if ([string]::IsNullOrWhiteSpace($ssid)) {
            throw "Zadej název cílové Wi-Fi (SSID). Můžeš ho napsat ručně nebo použít tlačítko Vyhledat."
        }
        if ([string]::IsNullOrWhiteSpace($password)) {
            throw "Zadej heslo cílové Wi-Fi."
        }
        if ($script:WifiPasswordSsid -and $script:WifiPasswordSsid -ne $ssid) {
            throw "Wi-Fi byla změněna, ale heslo patří předchozí síti. Vyber síť znovu nebo zadej správné heslo."
        }
        Log "Cílová Wi-Fi pro Raspberry Pi byla potvrzena."

        $cloud = New-CloudInit $ssid $password

        $imageSource = ""
        $expectedExtractSha = ""
        [Int64]$expectedExtractSize = 0
        $useLocalImage = ($os.SelectedIndex -eq 1 -and $script:LocalImagePath)

        if ($useLocalImage) {
            if (-not (Test-Path $script:LocalImagePath -PathType Leaf)) {
                throw "Vybraná vlastní image už není dostupná. Vyber soubor znovu."
            }

            $imageSource = $script:LocalImagePath
            Log ("RYCHLÝ REŽIM: používám vlastní image " + (Split-Path -Leaf $imageSource) + ". Stahování se přeskočí.")
            Set-InstallerProgress "Používám vlastní image · bez stahování" 100
        }
        else {
            Set-InstallerProgress "Hledám správnou image v online katalogu" 0
            Log ("Online režim: hledám Ubuntu Server 24.04 ARM64 pro " + $piName + "...")

            $image = Get-Ubuntu2404 $piTag
            Log ("Katalog: " + [string](Get-Prop $image "name"))
            $imageSource = Get-PiTVOnlineImageFile $image
            $expectedExtractSha = Get-PiTVStringProp $image @("extract_sha256")
            $expectedExtractSize = Get-PiTVInt64Prop $image @("extract_size")
        }

        $prepared = Prepare-PiTVRawImage $imageSource $expectedExtractSha $expectedExtractSize
        Write-PiTVRawImageToDisk $prepared $d
        Install-PiTVCloudInitToBootPartition $d $cloud

        [Windows.Forms.Clipboard]::SetText($cloud.Password)
        Set-InstallerProgress "HOTOVO · PiTV SD je připravena" 100
        Log "HOTOVO. PiTV SD je připravená."
        Log "Po prvním startu se Raspberry připojí k Wi-Fi, cloud-init stáhne PiTV, spustí install.sh a zařízení restartuje."
        Log "Online image zůstává uložená v cache a při příštím vytvoření SD se nebude stahovat znovu."
        Log "Záložní účet: pitvadmin · heslo bylo zkopírováno do schránky."

        $doneText = "SD karta je připravená pro " + $piName + "." + $nl + $nl + "Můžeš ji vyjmout, vložit do Raspberry Pi a zapnout. Online image zůstala uložená v počítači pro další použití." + $nl + $nl + "Záložní heslo účtu pitvadmin je ve schránce."
        [Windows.Forms.MessageBox]::Show(
            $doneText,
            "PiTV SD Installer",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
    }
    catch {
        Log ("CHYBA: " + $_.Exception.Message)
        Log-ExceptionDetails $_ "VYTVOŘENÍ SD"
        Set-InstallerProgress "CHYBA · podrobnosti jsou v logu" 0

        $errorText = $_.Exception.Message + [Environment]::NewLine + [Environment]::NewLine + "Podrobnosti byly zapsány do diagnostického logu."
        [Windows.Forms.MessageBox]::Show(
            $errorText,
            "PiTV SD Installer",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    finally {
        if ($prepared -and $prepared.Temporary) {
            if ($prepared.CleanupDir) {
                Remove-Item $prepared.CleanupDir -Recurse -Force -ErrorAction SilentlyContinue
            }
            elseif ($prepared.Path) {
                Remove-Item $prepared.Path -Force -ErrorAction SilentlyContinue
            }
        }

        if ($cloud -and $cloud.Dir) {
            Remove-Item $cloud.Dir -Recurse -Force -ErrorAction SilentlyContinue
        }

        $format.Enabled = $true
        $create.Enabled = $true
        $refresh.Enabled = $true
        $wifiLoad.Enabled = $true
        $imageBrowse.Enabled = $true
        $piModel.Enabled = $true
        $os.Enabled = $true
    }
})

$form.Add_Shown({
    Log "PiTV SD Installer v0.16 · Windows"
    Log "Motor: vlastní PiTV raw writer · bez Raspberry Pi Imageru."
    Log ("Trvalá cache image: " + $ImageCacheDir)
    Log "Diagnostika aktivní · ukládá se posledních 5 relací."
    Set-InstallerProgress "Připraveno · vyber systém, kartu a Wi-Fi" 0
    Refresh-Drives
    [void](Load-WifiFromWindows)
})

[void]$form.ShowDialog()
