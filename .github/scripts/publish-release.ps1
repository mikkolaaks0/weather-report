param(
    [Parameter(Mandatory = $true)]
    [string]$Tag
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'release-assets.ps1')
. (Join-Path $PSScriptRoot 'windows-signing.ps1')

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$portableZip = Join-Path $root 'release/WeatherReport-portable.zip'
$checksums = Join-Path $root 'release/SHA256SUMS.txt'
Assert-WindowsReleaseArtifacts -PortableZip $portableZip
Assert-ReleaseArtifactChecksums -Artifacts @($portableZip) -ChecksumPath $checksums
Publish-ReleaseAssets -Tag $Tag -Artifacts @($portableZip, $checksums)
