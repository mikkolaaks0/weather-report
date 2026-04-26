param(
    [string]$Version,
    [switch]$SkipInstaller,
    [switch]$Draft,
    [switch]$Prerelease
)

$ErrorActionPreference = 'Stop'

function Invoke-RequiredCommand {
    param(
        [string]$Command,
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Command $($Arguments -join ' ')"
    }
}

function Get-NextPatchVersion {
    Invoke-RequiredCommand -Command 'git' -Arguments @('fetch', '--tags', 'origin')

    $latestTag = git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname |
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
    $changes = git status --porcelain
    if ($changes) {
        throw "Working tree is not clean. Commit or stash changes before publishing a release."
    }
}

function Sync-CurrentBranch {
    $branch = git branch --show-current
    if (-not $branch) {
        throw 'Current checkout is not on a branch.'
    }

    Invoke-RequiredCommand -Command 'git' -Arguments @('fetch', 'origin', $branch)

    $behind = [int](git rev-list --count "HEAD..origin/$branch")
    if ($behind -gt 0) {
        throw "Local branch is behind origin/$branch. Pull first, then publish."
    }

    $ahead = [int](git rev-list --count "origin/$branch..HEAD")
    if ($ahead -gt 0) {
        Invoke-RequiredCommand -Command 'git' -Arguments @('push', 'origin', $branch)
    }

    return $branch
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
$branch = Sync-CurrentBranch

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

$buildArgs = @('-ExecutionPolicy', 'Bypass', '-File', '.\build_release.ps1')
if ($SkipInstaller) {
    $buildArgs += '-SkipInstaller'
}
Invoke-RequiredCommand -Command 'powershell' -Arguments $buildArgs

$portableZip = Join-Path $root 'release\WeatherReport-portable.zip'
$checksums = Join-Path $root 'release\SHA256SUMS.txt'
if (-not (Test-Path $portableZip)) {
    throw "Release artifact was not found: $portableZip"
}
if (-not (Test-Path $checksums)) {
    throw "Release checksum file was not found: $checksums"
}

Invoke-RequiredCommand -Command 'git' -Arguments @('tag', '-a', $Version, '-m', "Weather Report $Version")
Invoke-RequiredCommand -Command 'git' -Arguments @('push', 'origin', $Version)

$notes = @"
Weather Report $Version

Windows tray weather app release.
"@

$releaseArgs = @(
    'release', 'create', $Version,
    $portableZip,
    $checksums,
    '--title', "Weather Report $Version",
    '--notes', $notes,
    '--target', $branch
)
if ($Draft) {
    $releaseArgs += '--draft'
}
if ($Prerelease) {
    $releaseArgs += '--prerelease'
}

Invoke-RequiredCommand -Command 'gh' -Arguments $releaseArgs
Write-Host "Published $Version from $branch."
