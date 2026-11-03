param([Parameter(Mandatory = $true)][string]$Path)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-signing.ps1')
$configuration = Resolve-WindowsSigningConfiguration
Invoke-WindowsFileSigning -Path $Path -Configuration $configuration
