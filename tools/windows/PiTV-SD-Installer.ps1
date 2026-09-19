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

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        [Windows.Forms.MessageBox]::Show(
            "Raspberry Pi Imager není nainstalovaný. Otevřu oficiální stránku pro instalaci.",
            "PiTV SD Installer",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
        Start-Process "https://www.raspberrypi.com/software/"
        throw "Nainstaluj Raspberry Pi Imager a spusť PiTV SD Installer znovu."
    }

    $p = Start-Process -FilePath $winget.Source -ArgumentList @(
        "install",
        "--id","RaspberryPiFoundation.RaspberryPiImager",
        "-e",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--silent"
    ) -Wait -PassThru

    if ($p.ExitCode -ne 0) { throw "Automatická instalace Raspberry Pi Imageru selhala." }
    $path = Get-ImagerPath
    if (-not $path) { throw "Raspberry Pi Imager byl nainstalován, ale jeho program nebyl nalezen." }
    return $path
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

function Get-CurrentWifi {
    $raw = (& netsh wlan show interfaces) -join [Environment]::NewLine
    $m = [regex]::Match($raw, "(?im)^\s*SSID\s*:\s*(.+?)\s*$")
    if (-not $m.Success) { return $null }
    $ssid = $m.Groups[1].Value.Trim()
    if (-not $ssid) { return $null }

    $dir = Join-Path $env:TEMP ("pitv-wifi-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $dir | Out-Null
    try {
        & netsh wlan export profile name="$ssid" key=clear folder="$dir" | Out-Null
        $file = Get-ChildItem $dir -Filter "*.xml" | Select-Object -First 1
        if (-not $file) { return $null }
        [xml]$xml = Get-Content $file.FullName -Raw
        $nodes = $xml.GetElementsByTagName("keyMaterial")
        if ($nodes.Count -lt 1) { return $null }
        return [pscustomobject]@{ SSID=$ssid; Password=$nodes[0].InnerText }
    }
    finally {
        Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
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
  - [ bash, -lc, "set -e; rm -rf /opt/pitv-bootstrap; git clone --depth 1 $PiTVRepoUrl /opt/pitv-bootstrap; cd /opt/pitv-bootstrap; ./install.sh > /var/log/pitv-bootstrap.log 2>&1; touch /var/lib/pitv-firstboot-complete; systemctl reboot" ]
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

$form = New-Object Windows.Forms.Form
$form.Text = "PiTV SD Installer"
$form.Size = New-Object Drawing.Size(720,590)
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

Add-Label "Wi-Fi" 212
$wifiLabel = New-Object Windows.Forms.Label
$wifiLabel.Location = New-Object Drawing.Point(190,212)
$wifiLabel.Size = New-Object Drawing.Size(470,40)
$wifiLabel.Text = "Zjišťuji aktuální Wi-Fi..."
$form.Controls.Add($wifiLabel)

$info = New-Object Windows.Forms.Label
$info.Location = New-Object Drawing.Point(32,260)
$info.Size = New-Object Drawing.Size(628,54)
$info.Text = "BEZPEČNOST: systémový disk se nikdy nenabízí. Před zápisem znovu uvidíš model a kapacitu vybrané karty."
$info.ForeColor = [Drawing.Color]::FromArgb(186,230,253)
$form.Controls.Add($info)

$log = New-Object Windows.Forms.TextBox
$log.Location = New-Object Drawing.Point(32,320)
$log.Size = New-Object Drawing.Size(628,150)
$log.Multiline = $true
$log.ReadOnly = $true
$log.ScrollBars = "Vertical"
$log.BackColor = [Drawing.Color]::FromArgb(11,18,32)
$log.ForeColor = [Drawing.Color]::FromArgb(203,213,225)
$form.Controls.Add($log)

$create = New-Object Windows.Forms.Button
$create.Text = "VYTVOŘIT PiTV SD"
$create.Location = New-Object Drawing.Point(32,490)
$create.Size = New-Object Drawing.Size(628,48)
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

$refresh.Add_Click({ Refresh-Drives })

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

        $create.Enabled = $false
        $refresh.Enabled = $false

        Log "Kontroluji Raspberry Pi Imager..."
        $imager = Ensure-Imager
        Log ("Imager: " + $imager)

        Log "Načítám oficiální Ubuntu image..."
        $image = Get-Ubuntu2404
        Log ("Vybráno: " + $image.name)

        Log "Načítám aktuální Wi-Fi z Windows..."
        $wifi = Get-CurrentWifi
        if (-not $wifi -or -not $wifi.Password) {
            throw "Nepodařilo se automaticky načíst aktuální Wi-Fi a její heslo. Připoj PC k cílové Wi-Fi a spusť aplikaci znovu."
        }
        Log ("Wi-Fi: " + $wifi.SSID)

        $cloud = New-CloudInit $wifi.SSID $wifi.Password
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
        $create.Enabled = $true
        $refresh.Enabled = $true
    }
})

$form.Add_Shown({
    Log "PiTV SD Installer v0.1 · Windows"
    Log "Zápis provádí oficiální Raspberry Pi Imager CLI."
    Refresh-Drives
    try {
        $w = Get-CurrentWifi
        if ($w -and $w.SSID) {
            $wifiLabel.Text = $w.SSID + " · nastavení se převezme automaticky"
        } else {
            $wifiLabel.Text = "Wi-Fi nebyla nalezena"
        }
    } catch {
        $wifiLabel.Text = "Wi-Fi nebyla nalezena"
    }
})

[void]$form.ShowDialog()
