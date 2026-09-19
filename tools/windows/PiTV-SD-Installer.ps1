#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$RepoListUrl = "https://downloads.raspberrypi.com/os_list_imagingutility_v4.json"
$PiTVRepoUrl = "https://github.com/CaseyCZ/PiTV.git"

function Is-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Is-Admin)) {
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
    $protected = @()
    try {
        $protected = Get-Partition | Where-Object { $_.IsBoot -or $_.IsSystem } |
            Select-Object -ExpandProperty DiskNumber -Unique
    } catch {}

    return @(Get-Disk | Where-Object {
        $_.Number -ne 0 -and
        $_.Number -notin $protected -and
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
                $nameNodes = $xml.GetElementsByTagName("name")
                if ($nameNodes.Count -lt 1) { continue }
                $ssid = [string]$nameNodes[0].InnerText
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

function Get-Entries([string]$url,[int]$depth=0) {
    if ($depth -gt 5) { return @() }
    $data = Invoke-RestMethod -Uri $url -UseBasicParsing
    $all = @()
    foreach ($item in @($data.os_list)) {
        if ($item.subitems_url) {
            try { $all += Get-Entries ([string]$item.subitems_url) ($depth + 1) } catch {}
        }
        foreach ($sub in @($item.subitems)) {
            if ($sub -and $sub.url -and $sub.name) { $all += $sub }
        }
        if ($item.url -and $item.name) { $all += $item }
    }
    return $all
}

function Get-Ubuntu2404 {
    $entries = Get-Entries $RepoListUrl
    $list = $entries | Where-Object {
        $_.name -match "^Ubuntu Server 24\.04.*LTS \(64-bit\)$" -and
        (-not $_.devices -or $_.devices -contains "pi4" -or $_.devices -contains "pi4-64")
    } | Sort-Object @{ Expression={ try { [datetime]$_.release_date } catch { [datetime]::MinValue } } } -Descending

    $image = $list | Select-Object -First 1
    if (-not $image) { throw "Ubuntu Server 24.04 LTS pro Raspberry Pi 4 nebyl v oficiálním katalogu nalezen." }
    return $image
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
$form.Size = New-Object Drawing.Size(720,680)
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
$sub.ForeColor = [Drawing.Color]::FromArgb(148,163,184)
$sub.Location = New-Object Drawing.Point(31,66)
$sub.AutoSize = $true
$form.Controls.Add($sub)

function Add-Label($text,$y) {
    $l = New-Object Windows.Forms.Label
    $l.Text = $text
    $l.Location = New-Object Drawing.Point(32,$y)
    $l.Size = New-Object Drawing.Size(155,28)
    $form.Controls.Add($l)
}

Add-Label "Systém" 116
$os = New-Object Windows.Forms.ComboBox
$os.Location = New-Object Drawing.Point(190,112)
$os.Size = New-Object Drawing.Size(470,32)
$os.DropDownStyle = "DropDownList"
[void]$os.Items.Add("Ubuntu Server 24.04 LTS (64-bit) — doporučeno")
$os.SelectedIndex = 0
$form.Controls.Add($os)

Add-Label "microSD / USB" 164
$disk = New-Object Windows.Forms.ComboBox
$disk.Location = New-Object Drawing.Point(190,160)
$disk.Size = New-Object Drawing.Size(365,32)
$disk.DropDownStyle = "DropDownList"
$form.Controls.Add($disk)

$refresh = New-Object Windows.Forms.Button
$refresh.Text = "Obnovit"
$refresh.Location = New-Object Drawing.Point(565,159)
$refresh.Size = New-Object Drawing.Size(95,32)
$form.Controls.Add($refresh)

Add-Label "Wi-Fi SSID" 212
$wifiSsid = New-Object Windows.Forms.ComboBox
$wifiSsid.Location = New-Object Drawing.Point(190,208)
$wifiSsid.Size = New-Object Drawing.Size(365,30)
$wifiSsid.DropDownStyle = "DropDown"
$wifiSsid.AutoCompleteMode = "SuggestAppend"
$wifiSsid.AutoCompleteSource = "ListItems"
$form.Controls.Add($wifiSsid)

$wifiLoad = New-Object Windows.Forms.Button
$wifiLoad.Text = "Vyhledat"
$wifiLoad.Location = New-Object Drawing.Point(565,207)
$wifiLoad.Size = New-Object Drawing.Size(95,32)
$form.Controls.Add($wifiLoad)

Add-Label "Wi-Fi heslo" 254
$wifiPass = New-Object Windows.Forms.TextBox
$wifiPass.Location = New-Object Drawing.Point(190,250)
$wifiPass.Size = New-Object Drawing.Size(280,30)
$wifiPass.UseSystemPasswordChar = $true
$form.Controls.Add($wifiPass)

$wifiShow = New-Object Windows.Forms.CheckBox
$wifiShow.Text = "Zobrazit heslo"
$wifiShow.Location = New-Object Drawing.Point(486,251)
$wifiShow.Size = New-Object Drawing.Size(174,28)
$wifiShow.ForeColor = [Drawing.Color]::White
$wifiShow.BackColor = $form.BackColor
$form.Controls.Add($wifiShow)

$wifiStatus = New-Object Windows.Forms.Label
$wifiStatus.Location = New-Object Drawing.Point(190,284)
$wifiStatus.Size = New-Object Drawing.Size(470,24)
$wifiStatus.ForeColor = [Drawing.Color]::FromArgb(148,163,184)
$wifiStatus.Text = "Zkouším načíst aktuální Wi-Fi z Windows..."
$form.Controls.Add($wifiStatus)

$info = New-Object Windows.Forms.Label
$info.Location = New-Object Drawing.Point(32,318)
$info.Size = New-Object Drawing.Size(628,54)
$info.Text = "BEZPEČNOST: systémový disk se nikdy nenabízí. Před zápisem znovu uvidíš model a kapacitu vybrané karty."
$info.ForeColor = [Drawing.Color]::FromArgb(186,230,253)
$form.Controls.Add($info)

$log = New-Object Windows.Forms.TextBox
$log.Location = New-Object Drawing.Point(32,382)
$log.Size = New-Object Drawing.Size(628,170)
$log.Multiline = $true
$log.ReadOnly = $true
$log.ScrollBars = "Vertical"
$log.BackColor = [Drawing.Color]::FromArgb(11,18,32)
$log.ForeColor = [Drawing.Color]::FromArgb(203,213,225)
$form.Controls.Add($log)

$format = New-Object Windows.Forms.Button
$format.Text = "NAFORMÁTOVAT SD"
$format.Location = New-Object Drawing.Point(32,574)
$format.Size = New-Object Drawing.Size(198,48)
$format.BackColor = [Drawing.Color]::FromArgb(23,32,51)
$format.ForeColor = [Drawing.Color]::White
$format.FlatStyle = "Flat"
$format.Font = New-Object Drawing.Font("Segoe UI",10,[Drawing.FontStyle]::Bold)
$form.Controls.Add($format)

$create = New-Object Windows.Forms.Button
$create.Text = "VYTVOŘIT PiTV SD"
$create.Location = New-Object Drawing.Point(240,574)
$create.Size = New-Object Drawing.Size(420,48)
$create.BackColor = [Drawing.Color]::FromArgb(2,132,199)
$create.ForeColor = [Drawing.Color]::White
$create.FlatStyle = "Flat"
$create.Font = New-Object Drawing.Font("Segoe UI",12,[Drawing.FontStyle]::Bold)
$form.Controls.Add($create)

function Log([string]$s) {
    $log.AppendText((Get-Date -Format "HH:mm:ss") + "  " + $s + [Environment]::NewLine)
    $log.SelectionStart = $log.TextLength
    $log.ScrollToCaret()
    [Windows.Forms.Application]::DoEvents()
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
            $wifiStatus.Text = "Uložené heslo bylo načteno z Windows"
            Log ("Uložené heslo načteno pro Wi-Fi: " + $ssid)
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

        if ($current) {
            $wifiSsid.Text = $current
        } elseif ($choices.Count -gt 0 -and [string]::IsNullOrWhiteSpace($wifiSsid.Text)) {
            $wifiSsid.Text = [string]$choices[0]
        }

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

$wifiShow.Add_CheckedChanged({
    $wifiPass.UseSystemPasswordChar = -not $wifiShow.Checked
})

$wifiSsid.Add_SelectedIndexChanged({
    $wifiPass.Clear()
    [void](Load-PasswordForSelectedWifi)
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

        Log "Kontroluji Raspberry Pi Imager..."
        $imager = Ensure-Imager
        Log ("Imager: " + $imager)

        Log "Načítám oficiální Ubuntu image..."
        $image = Get-Ubuntu2404
        Log ("Vybráno: " + $image.name)

        $ssid = $wifiSsid.Text.Trim()
        $password = $wifiPass.Text
        if ([string]::IsNullOrWhiteSpace($ssid)) {
            throw "Zadej název cílové Wi-Fi (SSID). Můžeš ho napsat ručně nebo použít tlačítko Načíst."
        }
        if ([string]::IsNullOrWhiteSpace($password)) {
            throw "Zadej heslo cílové Wi-Fi."
        }
        Log ("Wi-Fi pro Raspberry Pi: " + $ssid)

        $cloud = New-CloudInit $ssid $password
        $target = "\\.\PhysicalDrive" + $d.Number

        $args = @(
            "--cli",
            "--disable-telemetry",
            "--cloudinit-userdata", $cloud.UserData,
            "--cloudinit-networkconfig", $cloud.Network
        )
        if ($image.extract_sha256) {
            $args += @("--sha256",[string]$image.extract_sha256)
        }
        $args += @([string]$image.url,$target)

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
    }
})

$form.Add_Shown({
    Log "PiTV SD Installer v0.5 · Windows"
    Log "Zápis provádí oficiální Raspberry Pi Imager CLI."
    Refresh-Drives
    [void](Load-WifiFromWindows)
})

[void]$form.ShowDialog()
