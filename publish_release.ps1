param(
    [string]$Version,
    [switch]$SkipInstaller,
    [switch]$Draft,
    [switch]$Prerelease
)

$ErrorActionPreference = 'Stop'
$releaseBranch = 'main'

function Invoke-RequiredCommand {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    & $Command @Arguments | Out-Host
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Command failed: $Command $($Arguments -join ' ')"
    }
}

function Get-RequiredCommandOutput {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    $previousEncoding = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
        $output = & $Command @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        [Console]::OutputEncoding = $previousEncoding
    }
    if ($exitCode -ne 0) {
        throw "Command failed: $Command $($Arguments -join ' ')"
    }
    return $output
}

function Assert-CleanWorkingTree {
    $changes = Get-RequiredCommandOutput -Command 'git' -Arguments @('status', '--porcelain', '--untracked-files=normal')
    if ($changes) {
        throw "Working tree is not clean. Commit or stash changes before publishing a release."
    }
}

function Sync-CurrentBranch {
    param([string]$ExpectedBranch)

    $branch = Get-RequiredCommandOutput -Command 'git' -Arguments @('branch', '--show-current')
    if (-not $branch) {
        throw 'Current checkout is not on a branch.'
    }
    if ($branch -ne $ExpectedBranch) {
        throw "Releases must be published from $ExpectedBranch. Current branch: $branch"
    }

    Invoke-RequiredCommand -Command 'git' -Arguments @('fetch', 'origin', $branch)

    $behind = [int](Get-RequiredCommandOutput -Command 'git' -Arguments @(
        'rev-list', '--count', "HEAD..origin/$branch"
    ))
    if ($behind -gt 0) {
        throw "Local branch is behind origin/$branch. Pull first, then publish."
    }

    $ahead = [int](Get-RequiredCommandOutput -Command 'git' -Arguments @(
        'rev-list', '--count', "origin/$branch..HEAD"
    ))
    if ($ahead -gt 0) {
        Invoke-RequiredCommand -Command 'git' -Arguments @('push', 'origin', $branch)
    }

    return $branch
}

function Assert-ReleaseRepository {
    param([string]$Directory)

    $localVariables = @(Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', '--local-env-vars')) + @('GIT_NAMESPACE')
    foreach ($name in $localVariables) {
        if ([Environment]::GetEnvironmentVariable($name)) {
            throw "Clear inherited Git repository override $name before publishing."
        }
    }
    $repository = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', '--show-toplevel')
    if ([System.IO.Path]::GetFullPath($repository).TrimEnd('\') -ne [System.IO.Path]::GetFullPath($Directory).TrimEnd('\')) {
        throw 'Git is targeting another working tree. Clear inherited Git repository overrides before publishing.'
    }
}

function Assert-ReleaseSourceUnchanged {
    param([string]$Commit, [string]$Branch)

    Assert-CleanWorkingTree
    $currentCommit = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', 'HEAD')
    $currentBranch = Get-RequiredCommandOutput -Command 'git' -Arguments @('branch', '--show-current')
    if ($currentCommit -ne $Commit -or $currentBranch -ne $Branch) {
        throw 'The checkout changed during the build. Rebuild before publishing a release.'
    }
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$metadata = Get-Content -LiteralPath (Join-Path $root 'app_metadata.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($metadata.version -notmatch '^\d+\.\d+\.\d+$') {
    throw 'app_metadata.json must contain a semantic version like 0.1.2.'
}
if ($Version -and $Version -cnotmatch ('^v?' + [regex]::Escape($metadata.version) + '$')) {
    throw "Requested version $Version does not match app_metadata.json ($($metadata.version)). Update the metadata before publishing."
}
$Version = "v$($metadata.version)"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git was not found in PATH.'
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI was not found. Install it with: winget install --id GitHub.cli'
}

Assert-ReleaseRepository -Directory $root
Invoke-RequiredCommand -Command 'gh' -Arguments @('auth', 'status')
Assert-CleanWorkingTree
$branch = Sync-CurrentBranch -ExpectedBranch $releaseBranch
$releaseCommit = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', 'HEAD')

if (git rev-parse -q --verify "refs/tags/$Version") {
    throw "Tag already exists: $Version"
}
$remoteTag = git ls-remote --tags origin "refs/tags/$Version"
if ($LASTEXITCODE -ne 0) {
    throw "Could not check remote tag: $Version"
}
if ($remoteTag) {
    throw "Tag already exists on origin: $Version"
}

$buildArgs = @('-ExecutionPolicy', 'Bypass', '-File', '.\build_release.ps1', '-Version', $Version)
if ($SkipInstaller) {
    $buildArgs += '-SkipInstaller'
}
Invoke-RequiredCommand -Command 'powershell' -Arguments $buildArgs

$portableZip = Join-Path $root 'release\WeatherReport-portable.zip'
$installer = Join-Path $root 'release\WeatherReport-Setup.exe'
$checksums = Join-Path $root 'release\SHA256SUMS.txt'
if (-not (Test-Path $portableZip)) {
    throw "Release artifact was not found: $portableZip"
}
if (-not (Test-Path $checksums)) {
    throw "Release checksum file was not found: $checksums"
}

Assert-ReleaseSourceUnchanged -Commit $releaseCommit -Branch $branch
Invoke-RequiredCommand -Command 'git' -Arguments @('tag', '-a', $Version, $releaseCommit, '-m', "Weather Report $Version [local-release]")
Invoke-RequiredCommand -Command 'git' -Arguments @('push', 'origin', $Version)

$notes = @"
Weather Report $Version

Windows tray weather app release.
"@

$releaseArgs = @(
    'release', 'create', $Version,
    $portableZip
)
if (Test-Path $installer) {
    $releaseArgs += $installer
}
$releaseArgs += @(
    $checksums,
    '--title', "Weather Report $Version",
    '--notes', $notes,
    '--target', $releaseCommit
)
if ($Draft) {
    $releaseArgs += '--draft'
}
if ($Prerelease) {
    $releaseArgs += '--prerelease'
}

Invoke-RequiredCommand -Command 'gh' -Arguments $releaseArgs
Write-Host "Published $Version from $branch."
