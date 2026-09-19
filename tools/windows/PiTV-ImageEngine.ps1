# PiTV SD Installer image/cache/raw-write engine.
# Loaded by PiTV-SD-Installer.ps1. Windows PowerShell 5.1 compatible.

function Get-PiTVInt64Prop($obj,[string[]]$names) {
    foreach ($name in $names) {
        $v = Get-Prop $obj $name
        if ($null -ne $v -and [string]$v) {
            try { return [Int64]$v } catch {}
        }
    }
    return [Int64]0
}

function Get-PiTVStringProp($obj,[string[]]$names) {
    foreach ($name in $names) {
        $v = [string](Get-Prop $obj $name)
        if (-not [string]::IsNullOrWhiteSpace($v)) { return $v.Trim() }
    }
    return ""
}

function Get-PiTVImageCachePath($image) {
    $url = [string](Get-Prop $image "url")
    if ([string]::IsNullOrWhiteSpace($url)) {
        throw "Online image nemá platnou URL."
    }

    try {
        $name = [IO.Path]::GetFileName(([Uri]$url).AbsolutePath)
    }
    catch {
        throw ("URL image není platná: " + $_.Exception.Message)
    }

    if ([string]::IsNullOrWhiteSpace($name)) {
        $name = "pitv-image-" + [guid]::NewGuid().ToString("N") + ".img.xz"
    }

    $name = $name -replace '[<>:"/\\|?*]', '_'
    return (Join-Path $ImageCacheDir $name)
}

function Get-PiTVFileSha256([string]$path) {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
}

function Test-PiTVCachedOnlineImage($image,[string]$path) {
    if (-not (Test-Path $path -PathType Leaf)) { return $false }

    $file = Get-Item $path
    $expectedSize = Get-PiTVInt64Prop $image @("image_download_size","download_size")
    if ($expectedSize -gt 0 -and [Int64]$file.Length -ne $expectedSize) {
        Log ("CACHE: uložená image má jinou velikost (" + $file.Length + " B místo " + $expectedSize + " B). Stáhnu ji znovu.")
        Remove-Item $path -Force -ErrorAction SilentlyContinue
        return $false
    }

    $expectedSha = Get-PiTVStringProp $image @("image_download_sha256","download_sha256")
    if ($expectedSha) {
        Set-InstallerProgress "Ověřuji uloženou image" 0
        $actualSha = Get-PiTVFileSha256 $path
        if ($actualSha -ne $expectedSha.ToLowerInvariant()) {
            Log "CACHE: SHA-256 uložené image nesouhlasí. Poškozená cache bude nahrazena."
            Remove-Item $path -Force -ErrorAction SilentlyContinue
            return $false
        }
    }

    Log ("CACHE HIT: používám už staženou image " + $file.Name + " · " + (Size-Text ([UInt64]$file.Length)))
    Set-InstallerProgress "Image je už uložená v počítači" 100
    return $true
}

function Download-PiTVOnlineImage($image,[string]$destination) {
    $url = [string](Get-Prop $image "url")
    $part = $destination + ".part"
    Remove-Item $part -Force -ErrorAction SilentlyContinue

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $client = New-Object Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromMinutes(60)
    $response = $null
    $input = $null
    $output = $null

    try {
        Log ("CACHE MISS: stahuji " + [IO.Path]::GetFileName($destination))
        Set-InstallerProgress "Stahuji image" 0

        $response = $client.GetAsync($url,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $response.EnsureSuccessStatusCode() | Out-Null

        $serverLength = if ($response.Content.Headers.ContentLength) { [Int64]$response.Content.Headers.ContentLength } else { [Int64]0 }
        $expectedSize = Get-PiTVInt64Prop $image @("image_download_size","download_size")
        $totalExpected = if ($serverLength -gt 0) { $serverLength } else { $expectedSize }

        $input = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $output = [IO.File]::Open($part,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $buffer = New-Object byte[] 1048576
        [Int64]$done = 0

        while (($read = $input.Read($buffer,0,$buffer.Length)) -gt 0) {
            $output.Write($buffer,0,$read)
            $done += $read

            if ($totalExpected -gt 0) {
                $pct = [Math]::Min(99,[int](($done * 100L) / $totalExpected))
                Set-InstallerProgress ("Stahuji image · " + (Size-Text ([UInt64]$done)) + " / " + (Size-Text ([UInt64]$totalExpected))) $pct
            }
            else {
                Set-InstallerProgress ("Stahuji image · " + (Size-Text ([UInt64]$done))) 0
            }
        }

        $output.Flush()
        $output.Dispose()
        $output = $null
        $input.Dispose()
        $input = $null

        $downloaded = Get-Item $part
        if ($expectedSize -gt 0 -and [Int64]$downloaded.Length -ne $expectedSize) {
            throw ("Stažená image nemá očekávanou velikost. Staženo " + $downloaded.Length + " B, očekáváno " + $expectedSize + " B.")
        }

        $expectedSha = Get-PiTVStringProp $image @("image_download_sha256","download_sha256")
        if ($expectedSha) {
            Set-InstallerProgress "Ověřuji SHA-256 stažené image" 99
            $actualSha = Get-PiTVFileSha256 $part
            if ($actualSha -ne $expectedSha.ToLowerInvariant()) {
                throw "SHA-256 stažené image nesouhlasí s oficiálním katalogem."
            }
            Log "SHA-256 stažené image je v pořádku."
        }
        elseif ($expectedSize -gt 0) {
            Log "Katalog neposkytl SHA-256 komprimovaného souboru; velikost stažené image souhlasí. Finální raw image bude ověřena před i po zápisu."
        }

        Move-Item $part $destination -Force
        Set-InstallerProgress "Image stažena a uložena pro příště" 100
        Log ("Image uložena do trvalé cache: " + $destination)
        return $destination
    }
    finally {
        if ($output) { $output.Dispose() }
        if ($input) { $input.Dispose() }
        if ($response) { $response.Dispose() }
        $client.Dispose()
        if (Test-Path $part) { Remove-Item $part -Force -ErrorAction SilentlyContinue }
    }
}

function Get-PiTVOnlineImageFile($image) {
    $cache = Get-PiTVImageCachePath $image
    if (Test-PiTVCachedOnlineImage $image $cache) { return $cache }
    return (Download-PiTVOnlineImage $image $cache)
}

function Get-PiTVAvailableBytes([string]$path) {
    $resolved = (Resolve-Path $path).Path
    $root = [IO.Path]::GetPathRoot($resolved)
    $drive = New-Object System.IO.DriveInfo -ArgumentList $root
    return $drive.AvailableFreeSpace
}

function New-PiTVRawImageInfo([string]$path,[bool]$temporary,[string]$cleanupDir,[string]$expectedSha="") {
    if (-not (Test-Path $path -PathType Leaf)) { throw "Připravená raw image nebyla nalezena." }
    $file = Get-Item $path
    if ($file.Length -lt 100MB) { throw "Připravená raw image je podezřele malá." }

    Set-InstallerProgress "Kontroluji raw image" 0
    $sha = Get-PiTVFileSha256 $path
    if ($expectedSha -and $sha -ne $expectedSha.ToLowerInvariant()) {
        throw "SHA-256 rozbalené raw image nesouhlasí s oficiálním katalogem."
    }

    Log ("Raw image připravena: " + $file.Name + " · " + (Size-Text ([UInt64]$file.Length)) + " · SHA-256 " + $sha.Substring(0,12) + "…")
    Set-InstallerProgress "Raw image je připravena" 100
    return [pscustomobject]@{
        Path = $file.FullName
        Length = [Int64]$file.Length
        Sha256 = $sha
        Temporary = $temporary
        CleanupDir = $cleanupDir
    }
}

function Format-PiTVProcessExitCode([int]$code) {
    $unsigned = [BitConverter]::ToUInt32([BitConverter]::GetBytes([int]$code),0)
    $hex = ("0x{0:X8}" -f $unsigned)
    switch ($hex) {
        "0xC0000135" { return ($code.ToString() + " / " + $hex + " · chybějící DLL") }
        "0xC0000005" { return ($code.ToString() + " / " + $hex + " · access violation") }
        default { return ($code.ToString() + " / " + $hex) }
    }
}

function Read-PiTVTextSafe([string]$path) {
    if (-not (Test-Path $path -PathType Leaf)) { return "" }
    try {
        $value = Get-Content -LiteralPath $path -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        if ($null -eq $value) { return "" }
        return ([string]$value).Trim()
    }
    catch {
        return ""
    }
}

function Prepare-PiTVRawImage([string]$source,[string]$expectedExtractSha="",[Int64]$expectedExtractSize=0) {
    if (-not (Test-Path $source -PathType Leaf)) { throw "Soubor image nebyl nalezen." }

    $lower = $source.ToLowerInvariant()
    if ($lower.EndsWith(".img")) {
        Log "Image je už v raw .img formátu - rozbalování se přeskočí."
        return (New-PiTVRawImageInfo $source $false "" $expectedExtractSha)
    }

    if ($expectedExtractSize -gt 0) {
        $free = Get-PiTVAvailableBytes $WorkDir
        $reserve = 512MB
        if ($free -lt ($expectedExtractSize + $reserve)) {
            throw ("Pro rozbalení image není na disku dost volného místa. Potřeba přibližně " + (Size-Text ([UInt64]($expectedExtractSize + $reserve))) + ", volno " + (Size-Text ([UInt64]$free)) + ".")
        }
    }

    if ($lower.EndsWith(".xz")) {
        $decoder = Join-Path $PSScriptRoot "PiTV-XZ.exe"
        if (-not (Test-Path $decoder -PathType Leaf)) {
            throw "Chybí PiTV-XZ.exe. Rozbal celý instalační ZIP."
        }

        $raw = Join-Path $WorkDir ("pitv-raw-" + [guid]::NewGuid().ToString("N") + ".img")
        try {
            Log "Rozbaluji XZ image pomocí PiTV-XZ..."
            Set-InstallerProgress "Rozbaluji image" 0

            $dq = [char]34
            $decoderArgs = $dq + $source + $dq + " " + $dq + $raw + $dq

            $psi = New-Object Diagnostics.ProcessStartInfo
            $psi.FileName = $decoder
            $psi.Arguments = $decoderArgs
            $psi.UseShellExecute = $false
            $psi.CreateNoWindow = $true
            $psi.RedirectStandardError = $true

            $p = New-Object Diagnostics.Process
            $p.StartInfo = $psi

            Log ("XZ decoder: " + (Split-Path -Leaf $decoder) + " · vstup " + (Size-Text ([UInt64](Get-Item $source).Length)))
            if (-not $p.Start()) {
                throw "PiTV-XZ se nepodařilo spustit."
            }

            while (-not $p.WaitForExit(250)) {
                [Windows.Forms.Application]::DoEvents()
                if (Test-Path $raw) {
                    $written = [Int64](Get-Item $raw).Length
                    if ($expectedExtractSize -gt 0) {
                        $pct = [Math]::Min(99,[int](($written * 100L) / $expectedExtractSize))
                        Set-InstallerProgress ("Rozbaluji image · " + (Size-Text ([UInt64]$written))) $pct
                    }
                    else {
                        Set-InstallerProgress ("Rozbaluji image · " + (Size-Text ([UInt64]$written))) 0
                    }
                }
            }

            $p.WaitForExit()
            $detail = [string]$p.StandardError.ReadToEnd()
            if ($detail) { $detail = $detail.Trim() }

            if ($p.ExitCode -ne 0) {
                $exitText = Format-PiTVProcessExitCode ([int]$p.ExitCode)
                $rawSize = if (Test-Path $raw) { [Int64](Get-Item $raw).Length } else { [Int64]0 }
                Log ("PiTV-XZ selhal · exit " + $exitText + " · vytvořeno " + (Size-Text ([UInt64]$rawSize)))
                if (-not $detail) { $detail = "Decoder nevrátil žádný text na stderr." }
                throw ("Rozbalení XZ selhalo (PiTV-XZ exit " + $exitText + "). " + $detail)
            }

            if ($expectedExtractSize -gt 0 -and [Int64](Get-Item $raw).Length -ne $expectedExtractSize) {
                throw ("Rozbalená image má jinou velikost než katalog. Výsledek " + (Get-Item $raw).Length + " B, očekáváno " + $expectedExtractSize + " B.")
            }

            return (New-PiTVRawImageInfo $raw $true "" $expectedExtractSha)
        }
        catch {
            Remove-Item $raw -Force -ErrorAction SilentlyContinue
            throw
        }
    }

    if ($lower.EndsWith(".zip")) {
        $dir = Join-Path $WorkDir ("pitv-zip-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        try {
            Log "Rozbaluji ZIP s vlastní image..."
            Set-InstallerProgress "Rozbaluji ZIP" 0
            Expand-Archive -LiteralPath $source -DestinationPath $dir -Force
            $imgs = @(Get-ChildItem $dir -Recurse -File | Where-Object { $_.Name.ToLowerInvariant().EndsWith(".img") })
            if ($imgs.Count -ne 1) {
                throw "ZIP musí obsahovat právě jeden .img soubor."
            }
            return (New-PiTVRawImageInfo $imgs[0].FullName $true $dir $expectedExtractSha)
        }
        catch {
            Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
            throw
        }
    }

    throw "Podporované image jsou .img, .img.xz/.xz a ZIP obsahující jeden .img soubor."
}

function Initialize-PiTVNativeDisk {
    if ("PiTVNativeDisk" -as [type]) { return }

    $nativePath = Join-Path $PSScriptRoot "PiTVNativeDisk.cs"
    if (-not (Test-Path $nativePath -PathType Leaf)) {
        throw "Chybí PiTVNativeDisk.cs. Rozbal celý instalační ZIP."
    }

    Add-Type -Path $nativePath
}

function Set-PiTVTargetDiskOffline($d) {
    $null = Get-VerifiedSafeDisk $d.Number $d.Size $d.Name $d.Identity
    Set-Disk -Number $d.Number -IsReadOnly $false -ErrorAction Stop

    $locks = New-Object System.Collections.ArrayList

    try {
        Set-Disk -Number $d.Number -IsOffline $true -ErrorAction Stop
        Start-Sleep -Milliseconds 500
        Log ("Disk " + $d.Number + " byl odpojen od Windows pro raw zápis.")
        return [pscustomobject]@{
            DiskOffline = $true
            VolumeLocks = @()
        }
    }
    catch {
        Log ("INFO: Windows nepovolil přepnutí celého disku Offline (" + $_.Exception.Message + "). Zamykám jeho svazky přes Windows FSCTL bez jejich dismountu.")

        foreach ($part in @(Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue)) {
            $accesses = @($part.AccessPaths | Where-Object { $_ })
            $lockPath = $null

            foreach ($access in $accesses) {
                $s = [string]$access
                if ($s.StartsWith("\\?\Volume{",[StringComparison]::OrdinalIgnoreCase)) {
                    $lockPath = $s
                    break
                }
            }

            if (-not $lockPath) {
                foreach ($access in $accesses) {
                    $s = [string]$access
                    if ($s.Length -eq 3 -and $s[1] -eq ':' -and [int][char]$s[2] -eq 92) {
                        $lockPath = $s
                        break
                    }
                }
            }

            if (-not $lockPath) {
                try {
                    $vol = $part | Get-Volume -ErrorAction Stop
                    if ($vol.DriveLetter) {
                        $lockPath = ([string]$vol.DriveLetter) + ":\"
                    }
                }
                catch {}
            }

            if ($lockPath) {
                try {
                    $guard = [PiTVNativeDisk]::LockVolume([string]$lockPath)
                    [void]$locks.Add($guard)
                    Log ("Svazek " + $guard.Path + " byl uzamčen pro raw zápis.")
                }
                catch {
                    foreach ($held in @($locks)) {
                        try { $held.Dispose() } catch {}
                    }
                    throw ("Windows nepovolil bezpečné uzamčení svazku " + $lockPath + ": " + $_.Exception.Message)
                }
            }
        }

        Start-Sleep -Milliseconds 300
        return [pscustomobject]@{
            DiskOffline = $false
            VolumeLocks = @($locks)
        }
    }
}

function Set-PiTVTargetDiskOnline([int]$number) {
    try {
        $state = Get-Disk -Number $number -ErrorAction Stop
        if ($state.IsOffline) {
            Set-Disk -Number $number -IsOffline $false -ErrorAction Stop
        }
        Update-Disk -Number $number -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 800
    }
    catch {
        Log ("VAROVÁNÍ: Nepodařilo se automaticky vrátit disk Online: " + $_.Exception.Message)
    }
}

function Get-PiTVStreamSha256($stream,[Int64]$length) {
    if ($null -eq $stream) { throw "Ověření nemá otevřený stream zařízení." }
    if (-not $stream.CanRead) { throw "Otevřený stream zařízení nepodporuje čtení." }
    if (-not $stream.CanSeek) { throw "Otevřený stream zařízení nepodporuje návrat na začátek." }

    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        [void]$stream.Seek(0,[IO.SeekOrigin]::Begin)
        $buffer = New-Object byte[] (4MB)
        [Int64]$remaining = $length
        [Int64]$done = 0

        while ($remaining -gt 0) {
            $want = [int][Math]::Min([Int64]$buffer.Length,$remaining)
            $read = $stream.Read($buffer,0,$want)
            if ($read -le 0) {
                throw "Ověření skončilo dřív než na konci image."
            }

            [void]$sha.TransformBlock($buffer,0,$read,$buffer,0)
            $remaining -= $read
            $done += $read

            $pct = [Math]::Min(99,[int](($done * 100L) / $length))
            Set-InstallerProgress ("Ověřuji zápis · " + $pct + " %") $pct
        }

        [void]$sha.TransformFinalBlock((New-Object byte[] 0),0,0)
        return ([BitConverter]::ToString($sha.Hash)).Replace("-","").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-PiTVDeviceSha256([string]$target,[Int64]$length) {
    Initialize-PiTVNativeDisk
    $stream = $null
    $sha = [Security.Cryptography.SHA256]::Create()

    try {
        $stream = [PiTVNativeDisk]::Open($target,$false)
        $buffer = New-Object byte[] (4MB)
        [Int64]$remaining = $length
        [Int64]$done = 0

        while ($remaining -gt 0) {
            $want = [int][Math]::Min([Int64]$buffer.Length,$remaining)
            $read = $stream.Read($buffer,0,$want)
            if ($read -le 0) { throw "Ověření skončilo dřív než na konci image." }

            [void]$sha.TransformBlock($buffer,0,$read,$buffer,0)
            $remaining -= $read
            $done += $read

            $pct = [Math]::Min(99,[int](($done * 100L) / $length))
            Set-InstallerProgress ("Ověřuji zápis · " + $pct + " %") $pct
        }

        [void]$sha.TransformFinalBlock((New-Object byte[] 0),0,0)
        return ([BitConverter]::ToString($sha.Hash)).Replace("-","").ToLowerInvariant()
    }
    finally {
        if ($stream) { $stream.Dispose() }
        $sha.Dispose()
    }
}

function Write-PiTVRawImageToDisk($raw,$d) {
    Initialize-PiTVNativeDisk
    $null = Get-VerifiedSafeDisk $d.Number $d.Size $d.Name $d.Identity

    if ([Int64]$raw.Length -gt [Int64]$d.Size) {
        throw ("Image " + (Size-Text ([UInt64]$raw.Length)) + " je větší než vybraný disk " + (Size-Text ([UInt64]$d.Size)) + ".")
    }

    $target = "\\.\PhysicalDrive" + $d.Number
    $source = $null
    $dest = $null
    $writeGuard = $null

    try {
        # Prefer opening the physical device before touching mounted volumes.
        # A few USB/SD bridges briefly report "device not ready" after a volume
        # is dismounted or its partition table changes. Holding this handle
        # across the lock/write/verify cycle avoids reopening during that window.
        try {
            $dest = [PiTVNativeDisk]::Open($target,$true)
            Log ("RAW HANDLE: " + $target + " otevřen před uzamčením svazků.")
        }
        catch {
            Log ("INFO: PhysicalDrive se před uzamčením nepodařilo otevřít (" + $_.Exception.Message + "). Zkusím to po uzamčení svazků.")
            $dest = $null
        }

        $writeGuard = Set-PiTVTargetDiskOffline $d
        Log ("RAW WRITE: " + $raw.Path + " -> " + $target)
        Set-InstallerProgress "Zapisuji systém na SD kartu" 0

        $source = [IO.File]::Open($raw.Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        if (-not $dest) {
            $dest = [PiTVNativeDisk]::Open($target,$true)
            Log ("RAW HANDLE: " + $target + " otevřen po uzamčení svazků.")
        }

        [void]$dest.Seek(0,[IO.SeekOrigin]::Begin)
        $buffer = New-Object byte[] (4MB)
        [Int64]$done = 0
        while (($read = $source.Read($buffer,0,$buffer.Length)) -gt 0) {
            $dest.Write($buffer,0,$read)
            $done += $read
            $pct = [Math]::Min(99,[int](($done * 100L) / [Int64]$raw.Length))
            Set-InstallerProgress ("Zapisuji systém na SD kartu · " + $pct + " %") $pct
        }

        try { $dest.Flush($true) } catch { $dest.Flush() }
        $source.Dispose()
        $source = $null

        # Keep the already-open PhysicalDrive handle for verification. Some USB/SD
        # readers briefly re-enumerate after a partition table is written, so
        # closing and immediately reopening \\.\PhysicalDriveN can fail even
        # though the write itself completed successfully.
        Set-InstallerProgress "Ověřuji zápis na SD kartě" 0
        Log "VERIFY: čtu zpět přes stejný otevřený PhysicalDrive handle."
        $deviceSha = Get-PiTVStreamSha256 $dest ([Int64]$raw.Length)

        $dest.Dispose()
        $dest = $null

        if ($deviceSha -ne $raw.Sha256) {
            throw ("Ověření zápisu selhalo. SHA-256 image " + $raw.Sha256 + ", karta " + $deviceSha + ".")
        }

        Log "VERIFY OK: obsah SD karty odpovídá raw image."
        Set-InstallerProgress "Zápis a ověření jsou hotové" 100
    }
    catch {
        throw ("Raw zápis na " + $target + " selhal: " + $_.Exception.Message)
    }
    finally {
        if ($dest) { $dest.Dispose() }
        if ($source) { $source.Dispose() }

        if ($writeGuard -and $writeGuard.VolumeLocks) {
            foreach ($held in @($writeGuard.VolumeLocks)) {
                try { $held.Dispose() } catch {}
            }
        }

        Set-PiTVTargetDiskOnline $d.Number
    }
}

function Install-PiTVCloudInitToBootPartition($d,$cloud) {
    Set-InstallerProgress "Nastavuji Wi-Fi a automatickou instalaci PiTV" 0
    $bootPart = $null
    $bootVol = $null

    for ($attempt = 0; $attempt -lt 20 -and -not $bootPart; $attempt++) {
        try {
            if (Get-Command Update-HostStorageCache -ErrorAction SilentlyContinue) {
                Update-HostStorageCache -ErrorAction SilentlyContinue
            }
        } catch {}
        try { Update-Disk -Number $d.Number -ErrorAction SilentlyContinue } catch {}

        foreach ($part in @(Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue)) {
            $vol = $null
            try { $vol = $part | Get-Volume -ErrorAction Stop } catch {}

            if ($vol -and (($vol.FileSystem -match '^FAT') -or ($vol.FileSystemLabel -match '^(system-boot|bootfs|boot)))) {
                $bootPart = $part
                $bootVol = $vol
                break
            }
        }

        if (-not $bootPart) { Start-Sleep -Milliseconds 500 }
    }

    if (-not $bootPart) {
        throw "Po zápisu se nepodařilo najít FAT boot oddíl pro cloud-init."
    }

    $partNumber = $bootPart.PartitionNumber

    # The card previously contained another partition layout. After a verified
    # whole-disk write Windows can still keep the old FAT mount cached under the
    # same drive letter. Copying cloud-init through that stale mount produces
    # ERROR_FILE_CORRUPT even though the raw image hash is correct. Force one
    # clean post-write dismount and then reacquire the freshly written partition.
    if ($bootPart.DriveLetter) {
        $staleRoot = ([string]$bootPart.DriveLetter) + ":" + [IO.Path]::DirectorySeparatorChar
        Log ("BOOT REFRESH: odpojuji starý mount " + $staleRoot + " a znovu načítám FAT oddíl po raw zápisu.")
        & "$env:SystemRoot\System32\mountvol.exe" $staleRoot "/p" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw ("Windows nedokázal obnovit boot oddíl po zápisu (mountvol exit " + $LASTEXITCODE + ").")
        }

        Start-Sleep -Milliseconds 1200
        try {
            if (Get-Command Update-HostStorageCache -ErrorAction SilentlyContinue) {
                Update-HostStorageCache -ErrorAction SilentlyContinue
            }
        } catch {}
        try { Update-Disk -Number $d.Number -ErrorAction SilentlyContinue } catch {}

        $bootPart = $null
        for ($attempt = 0; $attempt -lt 20 -and -not $bootPart; $attempt++) {
            try {
                $bootPart = Get-Partition -DiskNumber $d.Number -PartitionNumber $partNumber -ErrorAction Stop
            } catch {
                $bootPart = $null
            }
            if (-not $bootPart) { Start-Sleep -Milliseconds 500 }
        }

        if (-not $bootPart) {
            throw "Boot oddíl se po bezpečném odpojení neobjevil zpět ve Windows."
        }
    }

    $assignedByUs = $false
    if (-not $bootPart.DriveLetter) {
        $bootPart | Add-PartitionAccessPath -AssignDriveLetter -ErrorAction Stop
        $assignedByUs = $true
        Start-Sleep -Milliseconds 800
        $bootPart = Get-Partition -DiskNumber $d.Number -PartitionNumber $partNumber -ErrorAction Stop
    }

    if (-not $bootPart.DriveLetter) {
        throw "Boot oddílu se nepodařilo přiřadit písmeno jednotky."
    }

    $root = ([string]$bootPart.DriveLetter) + ":" + [IO.Path]::DirectorySeparatorChar

    $rootReady = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (Test-Path -LiteralPath $root) {
            $rootReady = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $rootReady) {
        throw ("Boot oddíl " + $root + " není po připojení čitelný.")
    }

    Copy-Item -LiteralPath $cloud.UserData -Destination (Join-Path $root "user-data") -Force -ErrorAction Stop
    Copy-Item -LiteralPath $cloud.Network -Destination (Join-Path $root "network-config") -Force -ErrorAction Stop

    $meta = Join-Path $root "meta-data"
    if (-not (Test-Path $meta)) {
        $utf8 = New-Object Text.UTF8Encoding($false)
        $metaText = "instance-id: pitv" + [Environment]::NewLine + "local-hostname: pitv" + [Environment]::NewLine
        [IO.File]::WriteAllText($meta,$metaText,$utf8)
    }

    Log ("Cloud-init zapsán na boot oddíl " + $root)
    Set-InstallerProgress "Wi-Fi a PiTV jsou připravené" 100

    try {
        & "$env:SystemRoot\System32\mountvol.exe" $root "/p" | Out-Null
        Log "Boot oddíl byl bezpečně odpojen. Kartu lze po dokončení vyjmout."
    }
    catch {
        if ($assignedByUs) {
            try { $bootPart | Remove-PartitionAccessPath -AccessPath $root -ErrorAction SilentlyContinue } catch {}
        }
    }
}
