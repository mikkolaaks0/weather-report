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
    foreach ($artifact in $Artifacts) {
        if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
            throw "Release artifact was not found: $artifact"
        }
    }

    # Windows PowerShell treats native stderr as a terminating error with Stop,
    # even when redirected. A missing release is an expected lookup outcome.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $existingJson = gh release view $Tag --json 'tagName,isDraft' 2>$null
        $viewExitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    if ($viewExitCode -eq 0) {
        $existing = $existingJson | ConvertFrom-Json
        if ($existing.tagName -cne $Tag -or $existing.isDraft -isnot [bool] -or -not $existing.isDraft) {
            throw 'Refusing to replace assets of an already published or unrecognized release.'
        }
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
