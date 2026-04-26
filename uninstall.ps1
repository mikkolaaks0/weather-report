param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\WeatherReport'),
    [switch]$RemoveSettings
)

$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw 'Weather Report is a Windows application. Run this uninstaller on Windows.'
}

$appName = 'Weather Report'
$settingDir = Join-Path $env:APPDATA 'weather-report'
$shortcutPaths = @(
    (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) "$appName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$appName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Startup')) "$appName.lnk")
)

Write-Host "Uninstalling $appName..."

Get-Process -Name 'WeatherReport' -ErrorAction SilentlyContinue | Stop-Process -Force

foreach ($shortcutPath in $shortcutPaths) {
    if (Test-Path $shortcutPath) {
        Remove-Item -Path $shortcutPath -Force
    }
}

if (Test-Path $InstallDir) {
    Remove-Item -Path $InstallDir -Recurse -Force
}

if ($RemoveSettings -and (Test-Path $settingDir)) {
    Remove-Item -Path $settingDir -Recurse -Force
}

Write-Host "$appName uninstalled successfully."
