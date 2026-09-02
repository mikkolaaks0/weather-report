param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\WeatherReport'),
    [switch]$RemoveSettings
)

$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw 'Weather Report is a Windows application. Run this uninstaller on Windows.'
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
        throw "Refusing to uninstall from drive root: $fullPath"
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
            throw "Refusing to uninstall from unsafe path: $fullPath"
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

function Remove-InstalledShortcut {
    param([string]$Path, [string]$ExecutablePath)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return
    }
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($Path)
        $target = Normalize-PathForSafety $shortcut.TargetPath
    }
    catch {
        Write-Warning "Could not inspect shortcut; leaving it unchanged: $Path"
        return
    }
    if ($target -eq (Normalize-PathForSafety $ExecutablePath)) {
        Remove-Item -LiteralPath $Path -Force
    }
}

$appName = 'Weather Report'
$settingsRoot = if ($env:APPDATA) { $env:APPDATA } else { $env:LOCALAPPDATA }
$settingDir = if ($settingsRoot) { Join-Path $settingsRoot 'weather-report' } else { $null }
$shortcutPaths = @(
    (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) "$appName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$appName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Startup')) 'weather-report.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Startup')) "$appName.lnk")
)

Assert-SafeInstallDirectory -Path $InstallDir
$InstallDir = Normalize-PathForSafety $InstallDir

Write-Host "Uninstalling $appName..."

$exePath = Join-Path $InstallDir 'WeatherReport.exe'
Stop-InstalledApplication -ExecutablePath $exePath

foreach ($shortcutPath in $shortcutPaths) {
    Remove-InstalledShortcut -Path $shortcutPath -ExecutablePath $exePath
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}

if ($RemoveSettings -and $settingDir -and (Test-Path -LiteralPath $settingDir)) {
    Remove-Item -LiteralPath $settingDir -Recurse -Force
}

Write-Host "$appName uninstalled successfully."
