param(
    [switch]$SkipInstaller,
    [string]$Version
)

$ErrorActionPreference = 'Stop'

function Resolve-BuildVersion {
    param([string]$MetadataPath, [string]$RequestedVersion)

    $metadata = Get-Content -LiteralPath $MetadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($metadata.version -notmatch '^\d+\.\d+\.\d+$') {
        throw 'app_metadata.json must contain a semantic version like 0.1.2.'
    }
    $null = [datetime]::ParseExact($metadata.date, 'dd.MM.yyyy', [Globalization.CultureInfo]::InvariantCulture)
    if ($RequestedVersion -and $RequestedVersion -cnotmatch ('^v?' + [regex]::Escape($metadata.version) + '$')) {
        throw "Requested version $RequestedVersion does not match app_metadata.json ($($metadata.version)). Update the metadata before building."
    }
    return $metadata.version
}

function Test-BuildPython {
    param([hashtable]$Python)

    try {
        & $Python.Command @($Python.Args + @(
            '-c',
            'import sys, tkinter; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
        )) 2>$null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Resolve-PythonCommand {
    param([Parameter(Mandatory = $true)][string]$ProjectDirectory)

    $venvDirectory = Join-Path $ProjectDirectory '.venv'
    if (Test-Path -LiteralPath $venvDirectory) {
        $venvPython = Join-Path $venvDirectory 'Scripts\python.exe'
        $candidate = @{ Command = $venvPython; Args = @() }
        if (
            -not (Test-Path -LiteralPath $venvPython -PathType Leaf) -or
            -not (Test-BuildPython -Python $candidate)
        ) {
            throw 'The project .venv is unusable. Recreate it with Python 3.10+ and Tkinter before building.'
        }
        return $candidate
    }

    $candidates = @(
        @{ Command = 'py'; Args = @('-3') },
        @{ Command = 'python'; Args = @() },
        @{ Command = 'python3'; Args = @() }
    )

    foreach ($candidate in $candidates) {
        $commandInfo = Get-Command $candidate.Command -ErrorAction SilentlyContinue
        if ($commandInfo -and (Test-BuildPython -Python $candidate)) {
            return $candidate
        }
    }

    throw 'Python 3.10+ with Tkinter was not found. Create a project .venv or make sure py or python works from the command line.'
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

$normalizedVersion = Resolve-BuildVersion -MetadataPath (Join-Path $root 'app_metadata.json') -RequestedVersion $Version

$python = Resolve-PythonCommand -ProjectDirectory $root
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
    (Join-Path $distDir '_internal\app_metadata.json'),
    (Join-Path $distDir '_internal\certifi\cacert.pem'),
    (Join-Path $distDir '_internal\assets\weather-icons\unknown.png'),
    (Join-Path $distDir '_internal\assets\metric-icons\wind.png'),
    (Join-Path $distDir '_internal\assets\fonts\Exo2-Regular.ttf')
)
foreach ($requiredPath in $requiredBuildPaths) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Portable build is missing a required file: $requiredPath"
    }
}
$releaseDir = Join-Path $root 'release'
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

$zipPath = Join-Path $releaseDir 'WeatherReport-portable.zip'
$installerPath = Join-Path $releaseDir 'WeatherReport-Setup.exe'
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
if (Test-Path -LiteralPath $installerPath) {
    Remove-Item -LiteralPath $installerPath -Force
}
Compress-Archive -LiteralPath @(Get-ChildItem -LiteralPath $distDir | Select-Object -ExpandProperty FullName) -DestinationPath $zipPath
Write-Host "Portable package ready: $zipPath"
$releaseArtifacts = @($zipPath)

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $SkipInstaller -and $iscc) {
    Write-Host 'Building installer...'
    & $iscc.Source "/DAppVersion=$normalizedVersion" (Join-Path $root 'installer.iss')
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup build failed with exit code $LASTEXITCODE."
    }
    if (-not (Test-Path -LiteralPath $installerPath)) {
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
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
        "$($hash.Hash.ToLowerInvariant())  $(Split-Path -Leaf $_)"
    } |
    Set-Content -LiteralPath $checksumPath -Encoding ascii

Write-Host "Checksums ready: $checksumPath"
