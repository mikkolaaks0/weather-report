param(
    [switch]$SkipInstaller
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
            return $candidate
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

$python = Resolve-PythonCommand
Invoke-Python -Python $python -Arguments @('-m', 'pip', 'install', '-r', 'requirements.txt')
Ensure-Tool -Python $python -ModuleName 'PyInstaller' -PackageName 'pyinstaller'

Write-Host 'Building portable executable...'
Invoke-Python -Python $python -Arguments @('-m', 'PyInstaller', '--noconfirm', 'WeatherReport.spec')

$distDir = Join-Path $root 'dist\WeatherReport'
$releaseDir = Join-Path $root 'release'
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

$zipPath = Join-Path $releaseDir 'WeatherReport-portable.zip'
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}
Compress-Archive -Path (Join-Path $distDir '*') -DestinationPath $zipPath
Write-Host "Portable package ready: $zipPath"

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $SkipInstaller -and $iscc) {
    Write-Host 'Building installer...'
    & $iscc.Source (Join-Path $root 'installer.iss')
}
elseif (-not $SkipInstaller) {
    Write-Host 'Inno Setup was not found. The portable package was built, but the installer was skipped.'
}

$checksumPath = Join-Path $releaseDir 'SHA256SUMS.txt'
Get-ChildItem -Path $releaseDir -File |
    Where-Object { $_.Name -ne 'SHA256SUMS.txt' } |
    Sort-Object Name |
    ForEach-Object {
        $hash = Get-FileHash -Algorithm SHA256 -Path $_.FullName
        "$($hash.Hash.ToLowerInvariant())  $($_.Name)"
    } |
    Set-Content -Path $checksumPath -Encoding ascii

Write-Host "Checksums ready: $checksumPath"
