function Get-ReleaseChecksumLines {
    param([string[]]$Artifacts)

    foreach ($artifact in ($Artifacts | Sort-Object { Split-Path -Leaf $_ })) {
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $artifact
        "$($hash.Hash.ToLowerInvariant())  $(Split-Path -Leaf $artifact)"
    }
}

function Assert-ReleaseArtifactChecksums {
    param([string[]]$Artifacts, [string]$ChecksumPath)

    $manifest = @(Get-Content -LiteralPath $ChecksumPath -Encoding ascii -ErrorAction Stop)
    $expected = @(Get-ReleaseChecksumLines -Artifacts $Artifacts)
    if (($manifest -join "`n") -cne ($expected -join "`n")) {
        throw 'SHA256SUMS.txt does not match the release artifacts. Rebuild before publishing.'
    }
}

function Assert-DraftReleaseAssets {
    param($Release, [string]$Tag, [hashtable]$LocalAssets, [switch]$Uploaded)

    if ($Release.tagName -cne $Tag -or $Release.isDraft -isnot [bool] -or -not $Release.isDraft -or
        $Release.assets -isnot [array]) {
        throw 'Refusing to replace assets of an already published or unrecognized release.'
    }
    $seen = @{}
    foreach ($asset in $Release.assets) {
        if ($asset.name -isnot [string] -or -not $LocalAssets.ContainsKey($asset.name)) {
            throw "Draft $Tag contains an asset outside this build: $($asset.name). Review the draft before publishing."
        }
        $local = $LocalAssets[$asset.name]
        if ($asset.name -cne $local.Name -or $seen.ContainsKey($asset.name)) {
            throw "Draft $Tag contains an unexpected duplicate or renamed asset: $($asset.name)."
        }
        $seen[$asset.name] = $true
        if ($Uploaded -and (
            $asset.state -cne 'uploaded' -or $asset.size -ne $local.Length -or
            ($asset.digest -and $asset.digest -ne $local.Digest)
        )) {
            throw "Uploaded asset does not match the local build: $($asset.name). Release remains a draft."
        }
    }
    if ($Uploaded -and $seen.Count -ne $LocalAssets.Count) {
        throw 'One or more uploaded assets are missing. Release remains a draft.'
    }
}

function Publish-ReleaseAssets {
    param(
        [string]$Tag,
        [string[]]$Artifacts,
        [switch]$Draft,
        [switch]$Prerelease
    )

    if ($Tag -cnotmatch '^v\d+\.\d+\.\d+$' -or -not $Artifacts) {
        throw 'A version tag and release artifacts are required.'
    }
    $localAssets = @{}
    foreach ($artifact in $Artifacts) {
        $file = Get-Item -LiteralPath $artifact -ErrorAction SilentlyContinue
        if (-not $file -or $file.PSIsContainer) {
            throw "Release artifact was not found: $artifact"
        }
        if ($localAssets.ContainsKey($file.Name)) {
            throw "Release artifacts must have unique names: $($file.Name)"
        }
        $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName
        $localAssets[$file.Name] = @{
            Name = $file.Name
            Length = $file.Length
            Digest = 'sha256:' + $hash.Hash.ToLowerInvariant()
        }
    }

    # Windows PowerShell treats native stderr as a terminating error with Stop,
    # even when redirected. A missing release is an expected lookup outcome.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $existingJson = gh release view $Tag --json 'tagName,isDraft,assets' 2>$null
        $viewExitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    if ($viewExitCode -eq 0) {
        $existing = $existingJson | ConvertFrom-Json
        Assert-DraftReleaseAssets -Release $existing -Tag $Tag -LocalAssets $localAssets
    }
    else {
        $createArguments = @(
            'release', 'create', $Tag, '--verify-tag', '--draft',
            '--title', "Weather Report $Tag", '--generate-notes'
        )
        if ($Prerelease) { $createArguments += '--prerelease' }
        gh @createArguments
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the draft release.' }
    }

    # Uploads can be retried without exposing a partial public release.
    gh release upload $Tag @Artifacts --clobber
    if ($LASTEXITCODE -ne 0) { throw 'Upload failed; release remains a draft.' }
    $uploadedJson = gh release view $Tag --json 'tagName,isDraft,assets'
    if ($LASTEXITCODE -ne 0) { throw 'Could not confirm uploaded assets; release remains a draft.' }
    Assert-DraftReleaseAssets -Release ($uploadedJson | ConvertFrom-Json) -Tag $Tag -LocalAssets $localAssets -Uploaded

    $editArguments = @(
        'release', 'edit', $Tag,
        "--draft=$($Draft.ToString().ToLowerInvariant())",
        "--prerelease=$($Prerelease.ToString().ToLowerInvariant())"
    )
    if (-not $Draft) {
        $latest = $false
        if (-not $Prerelease) {
            # Retrying an older draft must not roll back the installer's latest version.
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
        }
        $editArguments += "--latest=$($latest.ToString().ToLowerInvariant())"
    }
    gh @editArguments
    if ($LASTEXITCODE -ne 0) { throw 'Could not finalize the release.' }
}
