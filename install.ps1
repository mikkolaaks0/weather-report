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
}

function Stop-InstalledApplication {
    param([string]$ExecutablePath)

    $target = Normalize-PathForSafety $ExecutablePath
    foreach ($process in @(Get-Process -Name 'WeatherReport' -ErrorAction SilentlyContinue)) {
        if ($process.Path -and (Normalize-PathForSafety $process.Path) -eq $target) {
            if (-not $process.HasExited) {
                Stop-Process -InputObject $process -Force
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
    param([string]$Directory)

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

    $expectedLine = Get-Content $checksumPath |
        Where-Object { $_ -match "\s+$([regex]::Escape($AssetName))$" } |
        Select-Object -First 1

    if (-not $expectedLine) {
        throw "Checksum for $AssetName was not found in SHA256SUMS.txt."
    }

    $expectedHash = ($expectedLine -split '\s+')[0].ToLowerInvariant()
    $actualHash = (Get-FileHash -Algorithm SHA256 -Path $AssetPath).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw "Checksum verification failed for $AssetName."
    }
}

Write-Host "Installing $appName..."

New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null
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

$extractDir = Join-Path $downloadDir 'extracted'
Write-Host 'Validating package contents...'
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force
$stagedExePath = Get-ChildItem -LiteralPath $extractDir -Filter $exeName -File -Recurse |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $stagedExePath) {
    throw "$exeName was not found in the downloaded package."
}
$stagedAppDir = Split-Path -Parent $stagedExePath
Assert-PortablePackage -Directory $stagedAppDir

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

Stop-InstalledApplication -ExecutablePath (Join-Path $InstallDir $exeName)
Write-Host "Extracting to $InstallDir..."
$installParent = Split-Path -Parent $InstallDir
New-Item -ItemType Directory -Force -Path $installParent | Out-Null
$backupDir = "$InstallDir.backup-$([guid]::NewGuid().ToString('N'))"
$hadExistingInstall = Test-Path -LiteralPath $InstallDir
if ($hadExistingInstall) {
    Move-Item -LiteralPath $InstallDir -Destination $backupDir
}

try {
    Move-Item -LiteralPath $stagedAppDir -Destination $InstallDir
    $newInstallActivated = $true
}
catch {
    if (Test-Path -LiteralPath $InstallDir) {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force
    }
    if ($hadExistingInstall -and (Test-Path -LiteralPath $backupDir)) {
        Move-Item -LiteralPath $backupDir -Destination $InstallDir
    }
    throw
}

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

if (Test-Path -LiteralPath $backupDir) {
    try {
        Remove-Item -LiteralPath $backupDir -Recurse -Force
    }
    catch {
        Write-Warning "The previous installation backup could not be removed: $backupDir"
    }
}

Write-Host "$appName installed successfully."
Write-Host "Install location: $appDir"
}
catch {
    $installError = $_
    if ($newInstallActivated) {
        try {
            if (Test-Path -LiteralPath $InstallDir) {
                Remove-Item -LiteralPath $InstallDir -Recurse -Force
            }
            if ($hadExistingInstall -and (Test-Path -LiteralPath $backupDir)) {
                Move-Item -LiteralPath $backupDir -Destination $InstallDir
            }
        }
        catch {
            Write-Warning "Installation failed and the previous version could not be fully restored: $($_.Exception.Message)"
        }
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
    $normalizedDownloadDir = Normalize-PathForSafety $downloadDir
    $normalizedTempDir = Normalize-PathForSafety ([System.IO.Path]::GetTempPath())
    $downloadPrefix = "$normalizedTempDir\WeatherReportInstall-"
    if (
        $normalizedDownloadDir.StartsWith($downloadPrefix, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $normalizedDownloadDir)
    ) {
        try {
            Remove-Item -LiteralPath $normalizedDownloadDir -Recurse -Force
        }
        catch {
            Write-Warning "Temporary installer files could not be removed: $normalizedDownloadDir"
        }
    }
}
