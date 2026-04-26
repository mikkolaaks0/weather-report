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
$downloadDir = Join-Path $env:TEMP 'WeatherReportInstall'
$appName = 'Weather Report'
$exeName = 'WeatherReport.exe'

function Invoke-Download {
    param(
        [string]$Uri,
        [string]$OutFile
    )

    Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing
}

function Normalize-PathForSafety {
    param([string]$Path)

    if (-not $Path) {
        return $null
    }

    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-SafeInstallDirectory {
    param([string]$Path)

    $resolvedParent = Resolve-Path -LiteralPath (Split-Path -Parent $Path) -ErrorAction SilentlyContinue
    if (-not $resolvedParent) {
        return
    }

    $fullPath = Normalize-PathForSafety $Path
    $programsPath = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Programs' } else { $null }
    $blockedPaths = @(
        (Normalize-PathForSafety ([System.IO.Path]::GetPathRoot($fullPath))),
        (Normalize-PathForSafety $env:USERPROFILE),
        (Normalize-PathForSafety $env:LOCALAPPDATA),
        (Normalize-PathForSafety $env:APPDATA),
        (Normalize-PathForSafety $programsPath)
    ) | Where-Object { $_ }

    if ($blockedPaths -contains $fullPath) {
        throw "Refusing to install directly into unsafe path: $fullPath"
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
    $shortcut.WorkingDirectory = $WorkingDirectory
    if ($Icon) {
        $shortcut.IconLocation = $Icon
    }
    $shortcut.Save()
}

function Get-LatestRelease {
    $release = Invoke-RestMethod -Uri $apiUrl -Headers @{ 'User-Agent' = 'WeatherReport-Installer' }
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
Assert-SafeInstallDirectory -Path $InstallDir
$release = Get-LatestRelease
$asset = Get-PortableAsset -Release $release
$zipPath = Join-Path $downloadDir $asset.name

Write-Host "Downloading $($asset.name)..."
Invoke-Download -Uri $asset.browser_download_url -OutFile $zipPath
Test-AssetChecksum -Release $release -AssetName $asset.name -AssetPath $zipPath

Get-Process -Name 'WeatherReport' -ErrorAction SilentlyContinue | Stop-Process -Force

if (Test-Path $InstallDir) {
    Remove-Item -Path $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

Write-Host "Extracting to $InstallDir..."
Expand-Archive -Path $zipPath -DestinationPath $InstallDir -Force

$exePath = Get-ChildItem -Path $InstallDir -Filter $exeName -Recurse |
    Select-Object -First 1 -ExpandProperty FullName

if (-not $exePath) {
    throw "$exeName was not found after extracting the package."
}

$appDir = Split-Path -Parent $exePath
$iconPath = Join-Path $appDir 'assets\app.ico'
if (-not (Test-Path $iconPath)) {
    $iconPath = $exePath
}

if (-not $NoStartMenuShortcut) {
    $programs = [Environment]::GetFolderPath('Programs')
    New-Shortcut `
        -Path (Join-Path $programs "$appName.lnk") `
        -Target $exePath `
        -WorkingDirectory $appDir `
        -Icon $iconPath
}

if (-not $NoDesktopShortcut) {
    $desktop = [Environment]::GetFolderPath('DesktopDirectory')
    New-Shortcut `
        -Path (Join-Path $desktop "$appName.lnk") `
        -Target $exePath `
        -WorkingDirectory $appDir `
        -Icon $iconPath
}

if ($Startup) {
    $startup = [Environment]::GetFolderPath('Startup')
    New-Shortcut `
        -Path (Join-Path $startup "$appName.lnk") `
        -Target $exePath `
        -WorkingDirectory $appDir `
        -Icon $iconPath
}

if (-not $NoLaunch) {
    Start-Process -FilePath $exePath -WorkingDirectory $appDir
}

Write-Host "$appName installed successfully."
Write-Host "Install location: $appDir"
