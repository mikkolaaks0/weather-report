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

    $output = & $Command @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Command failed: $Command $($Arguments -join ' ')"
    }
    return $output
}

function Get-NextPatchVersion {
    Invoke-RequiredCommand -Command 'git' -Arguments @('fetch', '--tags', 'origin')

    $latestTag = Get-RequiredCommandOutput -Command 'git' -Arguments @(
        'tag', '--list', 'v[0-9]*.[0-9]*.[0-9]*', '--sort=-v:refname'
    ) |
        Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } |
        Select-Object -First 1

    if (-not $latestTag) {
        return 'v0.1.0'
    }

    if ($latestTag -notmatch '^v(\d+)\.(\d+)\.(\d+)$') {
        throw "Latest version tag is not semantic: $latestTag"
    }

    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    $patch = [int]$Matches[3] + 1
    return "v$major.$minor.$patch"
}

function Assert-CleanWorkingTree {
    $changes = Get-RequiredCommandOutput -Command 'git' -Arguments @('status', '--porcelain')
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

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git was not found in PATH.'
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI was not found. Install it with: winget install --id GitHub.cli'
}

Invoke-RequiredCommand -Command 'gh' -Arguments @('auth', 'status')
Assert-CleanWorkingTree
$branch = Sync-CurrentBranch -ExpectedBranch $releaseBranch
$releaseCommit = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', 'HEAD')

if (-not $Version) {
    $Version = Get-NextPatchVersion
}
elseif ($Version -notmatch '^v') {
    $Version = "v$Version"
}

if ($Version -notmatch '^v\d+\.\d+\.\d+$') {
    throw "Version must use semantic format like v0.1.1. Got: $Version"
}

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
Invoke-RequiredCommand -Command 'git' -Arguments @('tag', '-a', $Version, $releaseCommit, '-m', "Weather Report $Version")
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
