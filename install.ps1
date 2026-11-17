param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\WeatherReport'),
    [switch]$NoDesktopShortcut,
    [switch]$NoStartMenuShortcut,
    [switch]$Startup,
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw 'Weather Report is a Windows application. Run this installer on Windows.'
}

$repo = 'mikkolaaks0/weather-report'
$apiUrl = "https://api.github.com/repos/$repo/releases/latest"
$downloadDir = Join-Path ([System.IO.Path]::GetTempPath()) ("WeatherReportInstall-$([guid]::NewGuid().ToString('N'))")
$appName = 'Weather Report'
$exeName = 'WeatherReport.exe'
$startupDirectory = [Environment]::GetFolderPath('Startup')
$startupShortcutPath = Join-Path $startupDirectory 'weather-report.lnk'
$legacyStartupShortcutPath = Join-Path $startupDirectory "$appName.lnk"
$startupWasEnabled =
    (Test-Path -LiteralPath $startupShortcutPath) -or
    (Test-Path -LiteralPath $legacyStartupShortcutPath)

function Invoke-Download {
    param(
        [string]$Uri,
        [string]$OutFile
    )

    Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -TimeoutSec 300
}

function Normalize-PathForSafety {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath.Length -gt 3) {
        return $fullPath.TrimEnd('\')
    }

    return $fullPath
}

function Assert-SafeInstallDirectory {
    param([string]$Path)

    $fullPath = Normalize-PathForSafety $Path
    if (-not $fullPath) {
        throw 'Install directory is empty.'
    }

    $comparison = [System.StringComparison]::OrdinalIgnoreCase
    $rootPath = Normalize-PathForSafety ([System.IO.Path]::GetPathRoot($fullPath))
    if ([string]::Equals($fullPath, $rootPath, $comparison)) {
        throw "Refusing to install directly into drive root: $fullPath"
    }

    $leafName = Split-Path -Leaf $fullPath
    if ($leafName -notin @('WeatherReport', 'Weather Report')) {
        throw "Install directory must be an app-specific WeatherReport folder. Got: $fullPath"
    }

    $programsPath = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Programs' } else { $null }
    $blockedPaths = @(
        (Normalize-PathForSafety $env:USERPROFILE),
        (Normalize-PathForSafety $env:LOCALAPPDATA),
        (Normalize-PathForSafety $env:APPDATA),
        (Normalize-PathForSafety $programsPath),
        (Normalize-PathForSafety $env:ProgramFiles),
        (Normalize-PathForSafety ${env:ProgramFiles(x86)}),
        (Normalize-PathForSafety ([Environment]::GetFolderPath('DesktopDirectory'))),
        (Normalize-PathForSafety ([Environment]::GetFolderPath('MyDocuments')))
    ) | Where-Object { $_ }

    foreach ($blockedPath in $blockedPaths) {
        if ([string]::Equals($fullPath, $blockedPath, $comparison)) {
            throw "Refusing to install directly into unsafe path: $fullPath"
        }
    }
    if (Test-Path -LiteralPath $fullPath) {
        $existing = Get-Item -LiteralPath $fullPath -Force -ErrorAction Stop
        if (-not $existing.PSIsContainer -or ($existing.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            throw "Install path must be a regular directory, not a file or link: $fullPath"
        }
    }
}

function Stop-InstalledApplication {
    param([string]$ExecutablePath)

    $target = Normalize-PathForSafety $ExecutablePath
    foreach ($process in @(Get-Process -Name 'WeatherReport' -ErrorAction SilentlyContinue)) {
        if ($process.Path -and (Normalize-PathForSafety $process.Path) -eq $target) {
            if (-not $process.HasExited) {
                try {
                    Stop-Process -InputObject $process -Force
                }
                catch {
                    # The app may exit between enumeration and Stop-Process.
                    if (-not $process.HasExited) { throw }
                }
                if (-not $process.WaitForExit(10000)) {
                    throw "The installed application did not exit: $target"
                }
            }
        }
    }
}

function New-Shortcut {
    param(
        [string]$Path,
        [string]$Target,
        [string]$WorkingDirectory,
        [string]$Icon
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Force -Path $parent | Out-Null

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    $shortcut.Arguments = ''
    $shortcut.WorkingDirectory = $WorkingDirectory
    if ($Icon) {
        $shortcut.IconLocation = $Icon
    }
    $shortcut.Save()
}

function Start-InstalledApplication {
    param([string]$ExecutablePath, [string]$WorkingDirectory)

    $process = Start-Process -FilePath $ExecutablePath -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru
    try {
        if ($process.WaitForExit(1500)) {
            throw "The new application exited during startup (code $($process.ExitCode))."
        }
    }
    finally {
        $process.Dispose()
    }
}

function Get-ShortcutSnapshot {
    param([string[]]$Paths)

    foreach ($path in ($Paths | Select-Object -Unique)) {
        $contents = $null
        if (Test-Path -LiteralPath $path) {
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
                throw "Shortcut path is not a file: $path"
            }
            $contents = [System.IO.File]::ReadAllBytes($path)
        }
        [pscustomobject]@{ Path = $path; Contents = $contents }
    }
}

function Restore-ShortcutSnapshot {
    param([object[]]$Snapshot)

    $failures = @()
    foreach ($entry in $Snapshot) {
        try {
            if ($null -ne $entry.Contents) {
                [System.IO.File]::WriteAllBytes($entry.Path, $entry.Contents)
            }
            elseif (Test-Path -LiteralPath $entry.Path -PathType Leaf) {
                Remove-Item -LiteralPath $entry.Path -Force
            }
        }
        catch {
            $failures += "$($entry.Path): $($_.Exception.Message)"
        }
    }
    if ($failures.Count) {
        throw "Could not restore shortcuts: $($failures -join '; ')"
    }
}

function Assert-PortablePackage {
    param([string]$Directory, [string]$ExpectedVersion)

    if (-not $ExpectedVersion -or $ExpectedVersion -cnotmatch '^v?\d+\.\d+\.\d+$') {
        throw "Invalid release version: $ExpectedVersion"
    }

    $requiredFiles = @(
        'WeatherReport.exe',
        '_internal\_tkinter.pyd',
        '_internal\_tcl_data\init.tcl',
        '_internal\_tk_data\tk.tcl'
    )
    foreach ($relativePath in $requiredFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $Directory $relativePath) -PathType Leaf)) {
            throw "The downloaded package is incomplete: $relativePath"
        }
    }
    $pythonRuntime = Get-ChildItem -LiteralPath (Join-Path $Directory '_internal') -Filter 'python3*.dll' -File |
        Where-Object { $_.Name -match '^python3\d+\.dll$' } |
        Select-Object -First 1
    if (-not $pythonRuntime) {
        throw 'The downloaded package is missing the Python runtime.'
    }
    # v0.1.1 predates bundled metadata. New releases must include it and assets.
    $version = $ExpectedVersion.TrimStart('v')
    if ([version]$version -ge [version]'0.1.2') {
        $metadataPath = Join-Path $Directory '_internal\app_metadata.json'
        $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($metadata.version -cne $version) {
            throw 'The package version does not match the selected release.'
        }
        $null = [datetime]::ParseExact($metadata.date, 'dd.MM.yyyy', [Globalization.CultureInfo]::InvariantCulture)
        foreach ($asset in @(
            'weather-icons\unknown.png', 'weather-icons\cloud.png',
            'metric-icons\wind.png', 'fonts\Exo2-Regular.ttf'
        )) {
            if (-not (Test-Path -LiteralPath (Join-Path $Directory "_internal\assets\$asset") -PathType Leaf)) {
                throw "The downloaded package is missing an asset: $asset"
            }
        }
    }
}

function Get-LatestRelease {
    $release = Invoke-RestMethod -Uri $apiUrl -Headers @{ 'User-Agent' = 'WeatherReport-Installer' } -TimeoutSec 30
    return $release
}

function Get-PortableAsset {
    param($Release)

    $asset = $Release.assets |
        Where-Object { $_.name -match '^WeatherReport-portable.*\.zip$' } |
        Select-Object -First 1

    if (-not $asset) {
        throw 'No WeatherReport portable package was found in the latest GitHub Release.'
    }

    return $asset
}

function Test-AssetChecksum {
    param(
        $Release,
        [string]$AssetName,
        [string]$AssetPath
    )

    $checksumAsset = $Release.assets |
        Where-Object { $_.name -eq 'SHA256SUMS.txt' } |
        Select-Object -First 1

    if (-not $checksumAsset) {
        return
    }

    $checksumPath = Join-Path $downloadDir 'SHA256SUMS.txt'
    Invoke-Download -Uri $checksumAsset.browser_download_url -OutFile $checksumPath

    $expectedLine = Get-Content -LiteralPath $checksumPath |
        Where-Object { $_ -match "\s+$([regex]::Escape($AssetName))$" } |
        Select-Object -First 1

    if (-not $expectedLine) {
        throw "Checksum for $AssetName was not found in SHA256SUMS.txt."
    }

    $expectedHash = ($expectedLine -split '\s+')[0].ToLowerInvariant()
    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $AssetPath).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Checksum verification failed for $AssetName."
    }
}

function Remove-InstallerWorkingDirectory {
    param([string]$Directory, [string]$Parent, [string]$NamePrefix = 'WeatherReportInstall-')

    if (-not $Directory -or -not (Test-Path -LiteralPath $Directory)) {
        return
    }
    $resolved = Normalize-PathForSafety $Directory
    $expectedParent = Normalize-PathForSafety $Parent
    if ((Split-Path -Parent $resolved) -ne $expectedParent -or
        (Split-Path -Leaf $resolved) -cnotmatch ('^' + [regex]::Escape($NamePrefix) + '[0-9a-f]{32}$')) {
        Write-Warning "Refusing to clean an unexpected installer directory: $resolved"
        return
    }
    try {
        $item = Get-Item -LiteralPath $resolved -Force
        if (-not $item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            throw 'Installer directory no longer refers to a regular directory.'
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    catch {
        Write-Warning "Installer working directory could not be removed: $resolved"
    }
}

Write-Host "Installing $appName..."

New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
$extractDir = $null
$backupCreated = $false
$newInstallActivated = $false
$shortcutSnapshot = @()
try {
Assert-SafeInstallDirectory -Path $InstallDir
$InstallDir = Normalize-PathForSafety $InstallDir
$release = Get-LatestRelease
$asset = Get-PortableAsset -Release $release
$zipPath = Join-Path $downloadDir $asset.name

Write-Host "Downloading $($asset.name)..."
Invoke-Download -Uri $asset.browser_download_url -OutFile $zipPath
Test-AssetChecksum -Release $release -AssetName $asset.name -AssetPath $zipPath

# A directory can be renamed only within its own volume. Stage beside the
# installation so custom InstallDir values can use a different drive from TEMP.
$installParent = Split-Path -Parent $InstallDir
$extractDir = Join-Path $installParent ".wr-$([guid]::NewGuid().ToString('N'))"
Write-Host 'Validating package contents...'
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir
$stagedExePath = Get-ChildItem -LiteralPath $extractDir -Filter $exeName -File -Recurse |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $stagedExePath) {
    throw "$exeName was not found in the downloaded package."
}
$stagedAppDir = Split-Path -Parent $stagedExePath
Assert-PortablePackage -Directory $stagedAppDir -ExpectedVersion $release.tag_name

$shortcutPaths = @()
if (-not $NoStartMenuShortcut) {
    $startMenuShortcutPath = Join-Path ([Environment]::GetFolderPath('Programs')) "$appName.lnk"
    $shortcutPaths += $startMenuShortcutPath
}
if (-not $NoDesktopShortcut) {
    $desktopShortcutPath = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) "$appName.lnk"
    $shortcutPaths += $desktopShortcutPath
}
if ($Startup -or $startupWasEnabled) {
    $shortcutPaths += @($startupShortcutPath, $legacyStartupShortcutPath)
}
$shortcutSnapshot = @(Get-ShortcutSnapshot -Paths $shortcutPaths)

Assert-SafeInstallDirectory -Path $InstallDir
$hadExistingInstall = Test-Path -LiteralPath $InstallDir
Stop-InstalledApplication -ExecutablePath (Join-Path $InstallDir $exeName)
Write-Host "Installing to $InstallDir..."
$backupDir = "$InstallDir.backup-$([guid]::NewGuid().ToString('N'))"
if ($hadExistingInstall) {
    Assert-SafeInstallDirectory -Path $InstallDir
    [System.IO.Directory]::Move($InstallDir, $backupDir)
    $backupCreated = $true
}
# Exact destination: if it has appeared in the meantime, fail without moving
# the package inside it or removing a directory this installer did not create.
[System.IO.Directory]::Move($stagedAppDir, $InstallDir)
$newInstallActivated = $true

$exePath = Join-Path $InstallDir $exeName

$appDir = Split-Path -Parent $exePath
$iconPath = @(
    (Join-Path $appDir 'assets\app.ico'),
    (Join-Path $appDir '_internal\assets\app.ico')
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $iconPath) {
    $iconPath = $exePath
}

if (-not $NoStartMenuShortcut) {
    New-Shortcut `
        -Path $startMenuShortcutPath `
        -Target $exePath `
        -WorkingDirectory $appDir `
        -Icon $iconPath
}

if (-not $NoDesktopShortcut) {
    New-Shortcut `
        -Path $desktopShortcutPath `
        -Target $exePath `
        -WorkingDirectory $appDir `
        -Icon $iconPath
}

if ($Startup -or $startupWasEnabled) {
    New-Shortcut `
        -Path $startupShortcutPath `
        -Target $exePath `
        -WorkingDirectory $appDir `
        -Icon $iconPath
    if (Test-Path -LiteralPath $legacyStartupShortcutPath -PathType Leaf) {
        Remove-Item -LiteralPath $legacyStartupShortcutPath -Force
    }
}

if (-not $NoLaunch) {
    Start-InstalledApplication -ExecutablePath $exePath -WorkingDirectory $appDir
}

if ($backupCreated) {
    Remove-InstallerWorkingDirectory -Directory $backupDir -Parent $installParent -NamePrefix "$(Split-Path -Leaf $InstallDir).backup-"
}

Write-Host "$appName installed successfully."
Write-Host "Install location: $appDir"
}
catch {
    $installError = $_
    if ($newInstallActivated -or $backupCreated) {
        try {
            if ($newInstallActivated -and (Test-Path -LiteralPath $InstallDir)) {
                [System.IO.Directory]::Move($InstallDir, $stagedAppDir)
            }
            if ($backupCreated) {
                [System.IO.Directory]::Move($backupDir, $InstallDir)
            }
        }
        catch {
            Write-Warning "Installation failed and the previous version could not be fully restored: $($_.Exception.Message)"
        }
    }
    if ($newInstallActivated) {
        try {
            Restore-ShortcutSnapshot -Snapshot $shortcutSnapshot
        }
        catch {
            Write-Warning "Installation failed and shortcuts could not be fully restored: $($_.Exception.Message)"
        }
    }
    throw $installError
}
finally {
    Remove-InstallerWorkingDirectory -Directory $extractDir -Parent $installParent -NamePrefix '.wr-'
    Remove-InstallerWorkingDirectory -Directory $downloadDir -Parent ([System.IO.Path]::GetTempPath())
}
