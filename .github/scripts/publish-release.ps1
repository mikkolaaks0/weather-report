param(
    [Parameter(Mandatory = $true)]
    [string]$Tag
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'release-assets.ps1')

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Publish-ReleaseAssets -Tag $Tag -Artifacts @(
    (Join-Path $root 'release/WeatherReport-portable.zip'),
    (Join-Path $root 'release/SHA256SUMS.txt')
)
