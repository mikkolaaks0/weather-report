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

function Assert-ReusableReleaseTag {
    param([string]$Tag, [string]$Commit)

    $reference = "refs/tags/$Tag"
    $type = Get-RequiredCommandOutput -Command 'git' -Arguments @('cat-file', '-t', $reference)
    $target = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', "$reference^{commit}")
    $annotation = @(Get-RequiredCommandOutput -Command 'git' -Arguments @('for-each-ref', '--format=%(contents)', $reference)) -join "`n"
    if ($type -cne 'tag' -or $target -ne $Commit -or $annotation -notmatch '\[local-release\]') {
        throw "Refusing to reuse a foreign tag or a tag for another commit: $Tag"
    }
    return Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', $reference)
}

function Publish-LocalReleaseTag {
    param([string]$Tag, [string]$Commit)

    if ($Tag -cnotmatch '^v\d+\.\d+\.\d+$') {
        throw "Invalid release tag: $Tag"
    }
    $reference = "refs/tags/$Tag"
    $remoteTag = @(Get-RequiredCommandOutput -Command 'git' -Arguments @('ls-remote', '--tags', 'origin', $reference))
    $remoteObject = $null
    if ($remoteTag.Count) {
        if ($remoteTag.Count -ne 1 -or $remoteTag[0] -notmatch ('^([0-9a-fA-F]{40,64})\s+' + [regex]::Escape($reference) + '$')) {
            throw "Unrecognized remote tag: $Tag"
        }
        $remoteObject = $Matches[1]
    }
    $localTags = @(Get-RequiredCommandOutput -Command 'git' -Arguments @('for-each-ref', '--format=%(refname)', $reference))
    $existsLocally = $localTags -ccontains $reference
    if (-not $existsLocally -and $remoteObject) {
        Invoke-RequiredCommand -Command 'git' -Arguments @('fetch', 'origin', "$($reference):$reference")
        $existsLocally = $true
    }
    if ($existsLocally) {
        $localObject = Assert-ReusableReleaseTag -Tag $Tag -Commit $Commit
    }
    else {
        Invoke-RequiredCommand -Command 'git' -Arguments @('tag', '-a', $Tag, $Commit, '-m', "Weather Report $Tag [local-release]")
        $localObject = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', $reference)
    }
    if ($remoteObject -and $remoteObject -ne $localObject) {
        throw "Local and remote release tags do not match: $Tag"
    }
    if (-not $remoteObject) {
        Invoke-RequiredCommand -Command 'git' -Arguments @('push', 'origin', $reference)
    }
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
. (Join-Path $root '.github/scripts/release-assets.ps1')
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

$buildArgs = @('-ExecutionPolicy', 'Bypass', '-File', '.\build_release.ps1', '-Version', $Version)
if ($SkipInstaller) {
    $buildArgs += '-SkipInstaller'
}
Invoke-RequiredCommand -Command 'powershell' -Arguments $buildArgs

$portableZip = Join-Path $root 'release\WeatherReport-portable.zip'
$installer = Join-Path $root 'release\WeatherReport-Setup.exe'
$checksums = Join-Path $root 'release\SHA256SUMS.txt'
if (-not (Test-Path -LiteralPath $portableZip)) {
    throw "Release artifact was not found: $portableZip"
}
if (-not (Test-Path -LiteralPath $checksums)) {
    throw "Release checksum file was not found: $checksums"
}

Assert-ReleaseSourceUnchanged -Commit $releaseCommit -Branch $branch
Publish-LocalReleaseTag -Tag $Version -Commit $releaseCommit

$releaseArtifacts = @($portableZip, $checksums)
if (Test-Path -LiteralPath $installer) {
    $releaseArtifacts += $installer
}

Publish-ReleaseAssets -Tag $Version -Artifacts $releaseArtifacts -Draft:$Draft -Prerelease:$Prerelease
if ($Draft) { Write-Host "Prepared draft $Version from $branch." }
else { Write-Host "Published $Version from $branch." }
