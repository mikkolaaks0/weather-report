param(
    [Parameter(Mandatory = $true)]
    [string]$Tag
)

$ErrorActionPreference = 'Stop'

function Publish-ReleaseAssets {
    param([string]$Tag, [string[]]$Artifacts)

    if ($Tag -cnotmatch '^v\d+\.\d+\.\d+$' -or -not $Artifacts) {
        throw 'A version tag and release artifacts are required.'
    }
    foreach ($artifact in $Artifacts) {
        if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
            throw "Release artifact was not found: $artifact"
        }
    }

    $existingJson = gh release view $Tag --json 'tagName,isDraft' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $existing = $existingJson | ConvertFrom-Json
        if ($existing.tagName -cne $Tag -or $existing.isDraft -isnot [bool] -or -not $existing.isDraft) {
            throw 'Refusing to replace assets of an already published or unrecognized release.'
        }
    }
    else {
        gh release create $Tag --verify-tag --draft --title "Weather Report $Tag" --generate-notes
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the draft release.' }
    }

    # Retry replaces the ZIP and checksum while the release is still a draft.
    gh release upload $Tag @Artifacts --clobber
    if ($LASTEXITCODE -ne 0) { throw 'Upload failed; release remains a draft.' }

    # A retry of an older draft must not roll back the installer's latest release.
    $publishedTags = @(gh api 'repos/{owner}/{repo}/releases?per_page=100' --paginate --jq '.[] | select(.draft == false and .prerelease == false) | .tag_name')
    if ($LASTEXITCODE -ne 0) { throw 'Could not check published versions; release remains a draft.' }
    $version = [version]$Tag.Substring(1)
    $latest = $true
    foreach ($publishedTag in $publishedTags) {
        if ($publishedTag -cnotmatch '^v?\d+\.\d+\.\d+$') {
            throw "Unrecognized published version: $publishedTag. Release remains a draft."
        }
        if ([version]$publishedTag.TrimStart('v') -ge $version) { $latest = $false }
    }
    gh release edit $Tag --draft=false "--latest=$($latest.ToString().ToLowerInvariant())"
    if ($LASTEXITCODE -ne 0) { throw 'Could not publish the completed release.' }
}

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Publish-ReleaseAssets -Tag $Tag -Artifacts @(
    (Join-Path $root 'release/WeatherReport-portable.zip'),
    (Join-Path $root 'release/SHA256SUMS.txt')
)
