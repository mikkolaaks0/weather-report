param(
    [switch]$SkipInstaller,
    [string]$Version = '0.1.1'
)

$ErrorActionPreference = 'Stop'

function Resolve-PythonCommand {
    $candidates = @(
        @{ Command = 'py'; Args = @('-3') },
        @{ Command = 'python'; Args = @() },
        @{ Command = 'python3'; Args = @() }
    )

    foreach ($candidate in $candidates) {
        $commandInfo = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if ($commandInfo) {
            & $candidate.Command @($candidate.Args + @(
                '-c',
                'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
            ))
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
    }

    throw 'Python was not found. Install Python 3.10+ and make sure py or python works from the command line.'
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments
    )

    & $Python.Command @($Python.Args + $Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "Python-komento epaonnistui: $($Python.Command) $($Python.Args + $Arguments -join ' ')"
    }
}

function Ensure-Tool {
    param(
        [hashtable]$Python,
        [string]$ModuleName,
        [string]$PackageName
    )

    try {
        Invoke-Python -Python $Python -Arguments @('-m', $ModuleName, '--version')
    }
    catch {
        Write-Host "Installing missing package: $PackageName"
        Invoke-Python -Python $Python -Arguments @('-m', 'pip', 'install', $PackageName)
    }
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$normalizedVersion = $Version.TrimStart('v')
if ($normalizedVersion -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must use semantic format like 0.1.1 or v0.1.1. Got: $Version"
}

$python = Resolve-PythonCommand
Invoke-Python -Python $python -Arguments @('-m', 'pip', 'install', '-r', 'requirements.txt')

Write-Host 'Running tests...'
Invoke-Python -Python $python -Arguments @('-m', 'unittest', 'discover', '-s', 'tests', '-v')

Ensure-Tool -Python $python -ModuleName 'PyInstaller' -PackageName 'pyinstaller'
Write-Host 'Building portable executable...'
Invoke-Python -Python $python -Arguments @('-m', 'PyInstaller', '--noconfirm', '--clean', 'WeatherReport.spec')

$distDir = Join-Path $root 'dist\WeatherReport'
$distExe = Join-Path $distDir 'WeatherReport.exe'
$requiredBuildPaths = @(
    $distExe,
    (Join-Path $distDir '_internal\assets\weather-icons\unknown.png'),
    (Join-Path $distDir '_internal\assets\metric-icons\wind.png'),
    (Join-Path $distDir '_internal\assets\fonts\Exo2-Regular.ttf')
)
foreach ($requiredPath in $requiredBuildPaths) {
    if (-not (Test-Path $requiredPath)) {
        throw "Portable build is missing a required file: $requiredPath"
    }
}
$releaseDir = Join-Path $root 'release'
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

$zipPath = Join-Path $releaseDir 'WeatherReport-portable.zip'
$installerPath = Join-Path $releaseDir 'WeatherReport-Setup.exe'
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}
if (Test-Path $installerPath) {
    Remove-Item $installerPath -Force
}
Compress-Archive -Path (Join-Path $distDir '*') -DestinationPath $zipPath
Write-Host "Portable package ready: $zipPath"
$releaseArtifacts = @($zipPath)

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $SkipInstaller -and $iscc) {
    Write-Host 'Building installer...'
    & $iscc.Source "/DAppVersion=$normalizedVersion" (Join-Path $root 'installer.iss')
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path $installerPath)) {
        throw "Installer build completed without the expected artifact: $installerPath"
    }
    $releaseArtifacts += $installerPath
}
elseif (-not $SkipInstaller) {
    Write-Host 'Inno Setup was not found. The portable package was built, but the installer was skipped.'
}

$checksumPath = Join-Path $releaseDir 'SHA256SUMS.txt'
$releaseArtifacts |
    Sort-Object { Split-Path -Leaf $_ } |
    ForEach-Object {
        $hash = Get-FileHash -Algorithm SHA256 -Path $_
        "$($hash.Hash.ToLowerInvariant())  $(Split-Path -Leaf $_)"
    } |
    Set-Content -Path $checksumPath -Encoding ascii

Write-Host "Checksums ready: $checksumPath"
