$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $root '.github/scripts/windows-signing.ps1')

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Assert-Rejected {
    param([scriptblock]$Action, [string]$Message)
    $rejected = $false
    try { $null = & $Action } catch { $rejected = $true }
    Assert-True $rejected $Message
}

function New-TestFile {
    param([string]$Path, [string]$Content = 'fixture')
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        $null = New-Item -ItemType Directory -Path $parent -Force
    }
    [System.IO.File]::WriteAllText($Path, $Content)
    return $Path
}

function New-TestSignature {
    param([string]$Status = 'Valid', [bool]$Timestamp = $true, [bool]$Signer = $true)
    return [pscustomobject]@{
        Status = $Status
        SignerCertificate = $(if ($Signer) { [pscustomobject]@{ Subject = 'CN=Fixture publisher' } } else { $null })
        TimeStamperCertificate = $(if ($Timestamp) { [pscustomobject]@{ Subject = 'CN=Fixture timestamp' } } else { $null })
    }
}

$testDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ('WeatherReportSigning-' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $testDirectory
$environmentNames = @('WEATHERREPORT_SIGNING_SCRIPT', 'WEATHERREPORT_SIGNING_CERTIFICATE', 'WEATHERREPORT_TIMESTAMP_URL')
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name)
    [Environment]::SetEnvironmentVariable($name, $null)
}

try {
    & {
        Assert-True ($null -eq (Resolve-WindowsSigningConfiguration -AllowUnsigned)) 'Explicit unsigned local development was rejected'
        Assert-Rejected { Resolve-WindowsSigningConfiguration } 'Unconfigured release signing was accepted'

        $scriptPath = New-TestFile (Join-Path $testDirectory ('sign [local] ' + [char]0x00e4 + '.ps1')) 'param([string]$Path)'
        $env:WEATHERREPORT_SIGNING_SCRIPT = $scriptPath
        $configuration = Resolve-WindowsSigningConfiguration
        Assert-True ($configuration.Script -eq $scriptPath) 'Signing hook path did not preserve literal characters'
        Assert-True ($configuration.TimestampUrl -eq 'https://timestamp.digicert.com') 'Signing timestamp did not default to the documented service'
        foreach ($url in @('https://example.test/timestamp', 'http://example.test/timestamp')) {
            $env:WEATHERREPORT_TIMESTAMP_URL = $url
            $configuration = Resolve-WindowsSigningConfiguration
            Assert-True ($configuration.TimestampUrl -eq $url) 'A valid explicit timestamp endpoint was changed'
        }
        foreach ($url in @('file:///C:/timestamp', 'ftp://example.test/timestamp', 'relative/path', 'https://')) {
            $env:WEATHERREPORT_TIMESTAMP_URL = $url
            Assert-Rejected { Resolve-WindowsSigningConfiguration } 'Invalid timestamp configuration was accepted'
        }
        Remove-Item Env:\WEATHERREPORT_TIMESTAMP_URL
        $env:WEATHERREPORT_SIGNING_CERTIFICATE = '0123456789ABCDEF0123456789ABCDEF01234567'
        Assert-Rejected { Resolve-WindowsSigningConfiguration } 'Ambiguous signing identities were accepted'
        Remove-Item Env:\WEATHERREPORT_SIGNING_CERTIFICATE

        foreach ($path in @((Join-Path $testDirectory 'missing.ps1'), $testDirectory, (New-TestFile (Join-Path $testDirectory 'sign.cmd')))) {
            $env:WEATHERREPORT_SIGNING_SCRIPT = $path
            Assert-Rejected { Resolve-WindowsSigningConfiguration -AllowUnsigned } 'A broken configured signer silently fell back to unsigned output'
        }
        Remove-Item Env:\WEATHERREPORT_SIGNING_SCRIPT
    }

    & {
        $env:WEATHERREPORT_SIGNING_CERTIFICATE = 'not-a-thumbprint'
        Assert-Rejected { Resolve-WindowsSigningConfiguration } 'Malformed certificate thumbprint was accepted'
        $thumbprint = '0123456789ABCDEF0123456789ABCDEF01234567'
        $env:WEATHERREPORT_SIGNING_CERTIFICATE = $thumbprint
        $fixtureCertificate = [pscustomobject]@{
            HasPrivateKey = $true
            NotBefore = [datetime]::UtcNow.AddDays(-1)
            NotAfter = [datetime]::UtcNow.AddDays(1)
            Thumbprint = $thumbprint
            Extensions = @([pscustomobject]@{
                Oid = [pscustomobject]@{ Value = '2.5.29.37' }
                EnhancedKeyUsages = @([pscustomobject]@{ Value = '1.3.6.1.5.5.7.3.3' })
            })
        }
        $script:certificateLookups = @()
        function Get-Item {
            param($LiteralPath, $ErrorAction)
            $script:certificateLookups += $LiteralPath
            if ($LiteralPath -eq "Cert:\CurrentUser\My\$thumbprint") { return $fixtureCertificate }
            return Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath -ErrorAction Stop
        }
        function Get-Command {
            param($Name, $ErrorAction)
            if ($Name -like 'signtool*') { return [pscustomobject]@{ Source = 'C:\fixture\signtool.exe'; Path = 'C:\fixture\signtool.exe' } }
            return Microsoft.PowerShell.Core\Get-Command -Name $Name -ErrorAction $ErrorAction
        }
        $configuration = Resolve-WindowsSigningConfiguration
        Assert-True ($configuration.Certificate -eq $thumbprint) 'Certificate selection was changed'
        Assert-True ($script:certificateLookups -contains "Cert:\CurrentUser\My\$thumbprint") 'Signer certificate was not read from the current user store'
        $fixtureCertificate.HasPrivateKey = $false
        Assert-Rejected { Resolve-WindowsSigningConfiguration } 'A public certificate without its private key was accepted'
        $fixtureCertificate.HasPrivateKey = $true
        $fixtureCertificate.NotAfter = [datetime]::UtcNow.AddDays(-1)
        Assert-Rejected { Resolve-WindowsSigningConfiguration } 'An expired signing certificate was accepted'
        $fixtureCertificate.NotAfter = [datetime]::UtcNow.AddDays(1)
        $fixtureCertificate.NotBefore = [datetime]::UtcNow.AddDays(1)
        Assert-Rejected { Resolve-WindowsSigningConfiguration } 'A future-dated signing certificate was accepted'
        $fixtureCertificate.NotBefore = [datetime]::UtcNow.AddDays(-1)
        $fixtureCertificate.Extensions[0].EnhancedKeyUsages = @([pscustomobject]@{ Value = '1.3.6.1.5.5.7.3.1' })
        Assert-Rejected { Resolve-WindowsSigningConfiguration } 'A certificate without code-signing usage was accepted'
        Remove-Item Env:\WEATHERREPORT_SIGNING_CERTIFICATE
    }

    & {
        $packageDirectory = Join-Path $testDirectory ('package [x] ' + [char]0x00e4)
        $exe = New-TestFile (Join-Path $packageDirectory 'WeatherReport.exe')
        $dll = New-TestFile (Join-Path $packageDirectory '_internal\runtime.DLL')
        $pyd = New-TestFile (Join-Path $packageDirectory '_internal\PIL\image.pyd')
        $null = New-TestFile (Join-Path $packageDirectory '_internal\README.md')
        $files = @(Get-WindowsNativeFiles -Directory $packageDirectory)
        $paths = @($files | ForEach-Object { if ($_ -is [string]) { $_ } else { $_.FullName } })
        Assert-True ($paths.Count -eq 3) 'Native signing did not select exactly EXE, DLL and PYD files'
        foreach ($path in @($exe, $dll, $pyd)) {
            Assert-True ($paths -contains $path) 'Native signing omitted a runtime dependency'
        }
        $emptyDirectory = Join-Path $testDirectory 'empty-package'
        $null = New-Item -ItemType Directory -Path $emptyDirectory
        Assert-Rejected { Get-WindowsNativeFiles -Directory $emptyDirectory } 'A package without native files was accepted'
        Assert-Rejected { Get-WindowsNativeFiles -Directory $exe } 'A file was accepted as the package directory'
        Assert-Rejected { Get-WindowsNativeFiles -Directory (Join-Path $testDirectory 'missing-package') } 'A missing package was accepted'

        # A junction must not pull files outside the package into the signer.
        $junctionTarget = Join-Path $testDirectory 'junction-target'
        $null = New-TestFile (Join-Path $junctionTarget 'foreign.dll')
        $junction = Join-Path $packageDirectory 'linked-runtime'
        $null = New-Item -ItemType Junction -Path $junction -Target $junctionTarget
        Assert-Rejected { Get-WindowsNativeFiles -Directory $packageDirectory } 'A linked runtime directory was accepted'
        Assert-Rejected { Get-WindowsNativeFiles -Directory $junction } 'A linked package root was accepted'
        # Remove the junction itself, never recursively remove its target.
        [System.IO.Directory]::Delete($junction)
        Assert-True (Test-Path -LiteralPath (Join-Path $junctionTarget 'foreign.dll')) 'Junction validation changed its external target'
    }

    & {
        $path = New-TestFile (Join-Path $testDirectory ('signature [1] ' + [char]0x00e4 + '.exe'))
        $signature = New-TestSignature
        function Get-AuthenticodeSignature {
            param($LiteralPath, $FilePath, $ErrorAction)
            $actualPath = if ($LiteralPath) { $LiteralPath } else { $FilePath }
            Assert-True ($actualPath -eq $path) 'Signature verification changed a literal file path'
            return $signature
        }
        Assert-WindowsFileSignature -Path $path -RequireTimestamp
        foreach ($status in @('NotSigned', 'HashMismatch', 'NotTrusted', 'UnknownError')) {
            $signature = New-TestSignature -Status $status
            Assert-Rejected { Assert-WindowsFileSignature -Path $path } 'An untrusted or broken signature was accepted'
        }
        $signature = New-TestSignature -Signer $false
        Assert-Rejected { Assert-WindowsFileSignature -Path $path } 'A Valid status without a signing certificate was accepted'
        $signature = New-TestSignature -Timestamp $false
        Assert-WindowsFileSignature -Path $path
        Assert-Rejected { Assert-WindowsFileSignature -Path $path -RequireTimestamp } 'A new signature without its timestamp was accepted'
    }

    & {
        $signerPath = New-TestFile (Join-Path $testDirectory 'fixture signer.ps1') @'
param([string]$Path)
[System.IO.File]::WriteAllText($Path + '.signed', $Path)
'@
        $configuration = @{ Script = $signerPath; Certificate = $null; SignTool = $null; TimestampUrl = 'https://timestamp.digicert.com' }
        $packageDirectory = Join-Path $testDirectory ('signing [payload] ' + [char]0x00e4)
        $vendorPath = New-TestFile (Join-Path $packageDirectory '_internal\vendor.dll')
        $newPaths = @(
            (New-TestFile (Join-Path $packageDirectory 'Weather Report.exe')),
            (New-TestFile (Join-Path $packageDirectory '_internal\image [1].pyd'))
        )
        $ignoredPath = New-TestFile (Join-Path $packageDirectory 'README.md')
        function Get-AuthenticodeSignature {
            param($LiteralPath, $FilePath, $ErrorAction)
            $actualPath = if ($LiteralPath) { $LiteralPath } else { $FilePath }
            if ($actualPath -eq $vendorPath) { return New-TestSignature -Timestamp $false }
            if (Test-Path -LiteralPath ($actualPath + '.signed')) { return New-TestSignature }
            return New-TestSignature -Status 'NotSigned' -Timestamp $false -Signer $false
        }
        Invoke-WindowsPackageSigning -Directory $packageDirectory -Configuration $configuration
        foreach ($path in $newPaths) {
            Assert-True ([System.IO.File]::ReadAllText($path + '.signed') -eq $path) 'Signing hook did not receive the exact literal native file path'
        }
        Assert-True (-not (Test-Path -LiteralPath ($vendorPath + '.signed'))) 'An existing valid vendor signature was overwritten'
        Assert-True (-not (Test-Path -LiteralPath ($ignoredPath + '.signed'))) 'A non-native document was sent to the signer'
    }

    foreach ($case in @('invalid-existing', 'missing-signer', 'no-signature', 'no-timestamp', 'throw', 'exit', 'native-exit')) {
        & {
            $path = New-TestFile (Join-Path $testDirectory ("failure-$case.exe"))
            $signerContent = switch ($case) {
                'throw' { 'param([string]$Path); throw "simulated signer failure"' }
                'exit' { 'param([string]$Path); exit 17' }
                'native-exit' { 'param([string]$Path); [System.IO.File]::WriteAllText($Path + ''.signed'', ''signed''); & $env:COMSPEC /d /c exit 19' }
                default { 'param([string]$Path); [System.IO.File]::WriteAllText($Path + ''.signed'', ''signed'')' }
            }
            $signerPath = New-TestFile (Join-Path $testDirectory ("failure-$case.ps1")) $signerContent
            $configuration = @{ Script = $signerPath; Certificate = $null; SignTool = $null; TimestampUrl = 'https://timestamp.digicert.com' }
            function Get-AuthenticodeSignature {
                param($LiteralPath, $FilePath, $ErrorAction)
                if ($case -eq 'invalid-existing') { return New-TestSignature -Status 'HashMismatch' }
                if ($case -eq 'missing-signer') { return New-TestSignature -Signer $false }
                if (Test-Path -LiteralPath ($path + '.signed')) {
                    if ($case -eq 'no-signature') { return New-TestSignature -Status 'NotSigned' -Signer $false }
                    return New-TestSignature -Timestamp ($case -ne 'no-timestamp')
                }
                return New-TestSignature -Status 'NotSigned' -Timestamp $false -Signer $false
            }
            Assert-Rejected { Invoke-WindowsFileSigning -Path $path -Configuration $configuration } "Signing failure was not rejected: $case"
            if ($case -in @('invalid-existing', 'missing-signer')) {
                Assert-True (-not (Test-Path -LiteralPath ($path + '.signed'))) 'A broken existing signature was silently replaced'
            }
        }
    }

    foreach ($nativeExitCode in @(0, 23)) {
        & {
            $path = New-TestFile (Join-Path $testDirectory ("certificate-$nativeExitCode.exe"))
            $script:certificateSigned = $false
            $script:signToolArguments = @()
            $thumbprint = '0123456789ABCDEF0123456789ABCDEF01234567'
            function Invoke-FixtureSignTool {
                $script:signToolArguments = @($args)
                $script:certificateSigned = $true
                $global:LASTEXITCODE = $nativeExitCode
            }
            function Get-AuthenticodeSignature {
                param($LiteralPath, $FilePath, $ErrorAction)
                if ($script:certificateSigned) { return New-TestSignature }
                return New-TestSignature -Status 'NotSigned' -Signer $false
            }
            $configuration = @{ Certificate = $thumbprint; SignTool = 'Invoke-FixtureSignTool'; TimestampUrl = 'https://example.test/rfc3161' }
            if ($nativeExitCode) {
                Assert-Rejected { Invoke-WindowsFileSigning -Path $path -Configuration $configuration } 'SignTool failure was ignored after a valid-looking signature'
            }
            else { Invoke-WindowsFileSigning -Path $path -Configuration $configuration }
            $expectedArguments = @('sign', '/sha1', $thumbprint, '/s', 'My', '/fd', 'SHA256', '/tr', 'https://example.test/rfc3161', '/td', 'SHA256', '/d', 'Weather Report', $path)
            Assert-True ($script:signToolArguments.Count -eq $expectedArguments.Count) 'Certificate signing changed the SignTool argument boundaries'
            for ($index = 0; $index -lt $expectedArguments.Count; $index++) {
                Assert-True ($script:signToolArguments[$index] -ceq $expectedArguments[$index]) 'Certificate signing omitted the explicit identity, SHA256, timestamp, or literal file path'
            }
        }
    }

    & {
        $packageDirectory = Join-Path $testDirectory 'mutated-payload'
        $first = New-TestFile (Join-Path $packageDirectory 'a.exe')
        $null = New-TestFile (Join-Path $packageDirectory 'b.dll')
        $signerPath = New-TestFile (Join-Path $testDirectory 'mutating-signer.ps1') @'
param([string]$Path)
$markers = Get-ChildItem -LiteralPath (Split-Path -Parent $Path) -Filter '*.signed'
foreach ($marker in $markers) { [System.IO.File]::WriteAllText($marker.FullName, 'tampered') }
[System.IO.File]::WriteAllText($Path + '.signed', 'signed')
'@
        $configuration = @{ Script = $signerPath; Certificate = $null; SignTool = $null; TimestampUrl = 'https://timestamp.digicert.com' }
        function Get-AuthenticodeSignature {
            param($LiteralPath, $FilePath, $ErrorAction)
            $actualPath = if ($LiteralPath) { $LiteralPath } else { $FilePath }
            $marker = $actualPath + '.signed'
            if (-not (Test-Path -LiteralPath $marker)) { return New-TestSignature -Status 'NotSigned' -Signer $false }
            if ([System.IO.File]::ReadAllText($marker) -eq 'tampered') { return New-TestSignature -Status 'HashMismatch' }
            return New-TestSignature
        }
        Assert-Rejected { Invoke-WindowsPackageSigning -Directory $packageDirectory -Configuration $configuration } 'A provider invalidated an earlier payload signature without detection'
        Assert-True ([System.IO.File]::ReadAllText($first + '.signed') -eq 'tampered') 'Mutation fixture did not exercise the final package verification'
    }

    & {
        $packageDirectory = Join-Path $testDirectory ('archive source [x] ' + [char]0x00e4)
        $exe = New-TestFile (Join-Path $packageDirectory 'WeatherReport.exe') 'signed'
        $dll = New-TestFile (Join-Path $packageDirectory '_internal\nested\vendor.dll') 'vendor'
        $null = New-TestFile (Join-Path $packageDirectory '_internal\image.pyd') 'signed'
        $zipPath = Join-Path $testDirectory ('portable [x] ' + [char]0x00e4 + '.zip')
        $installer = New-TestFile (Join-Path $testDirectory 'setup.exe') 'signed'
        $script:archiveInspections = @()
        function Get-AuthenticodeSignature {
            param($LiteralPath, $FilePath, $ErrorAction)
            $actualPath = if ($LiteralPath) { $LiteralPath } else { $FilePath }
            $script:archiveInspections += $actualPath
            switch ([System.IO.File]::ReadAllText($actualPath)) {
                'signed' { return New-TestSignature }
                'vendor' { return New-TestSignature -Timestamp $false }
                'tampered' { return New-TestSignature -Status 'HashMismatch' }
                default { return New-TestSignature -Status 'NotSigned' -Signer $false }
            }
        }
        function New-FixtureZip {
            if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath }
            Compress-Archive -LiteralPath @((Get-ChildItem -LiteralPath $packageDirectory).FullName) -DestinationPath $zipPath
        }
        New-FixtureZip
        Assert-WindowsReleaseArtifacts -PortableZip $zipPath -Installer $installer
        Assert-True (@($script:archiveInspections | Where-Object { $_ -like '*\nested\vendor.dll' }).Count -eq 1) 'Release verification skipped a nested DLL'
        Assert-True (@($script:archiveInspections | Where-Object { $_ -like '*\image.pyd' }).Count -eq 1) 'Release verification skipped a Python native module'
        Assert-True (@($script:archiveInspections | Where-Object { $_.StartsWith($packageDirectory) }).Count -eq 0) 'Release gate verified the build directory instead of the actual archive'

        foreach ($content in @('unsigned', 'tampered')) {
            [System.IO.File]::WriteAllText($dll, $content)
            New-FixtureZip
            Assert-Rejected { Assert-WindowsReleaseArtifacts -PortableZip $zipPath } 'Release gate accepted an unsigned or tampered nested DLL'
        }
        [System.IO.File]::WriteAllText($dll, 'vendor')
        [System.IO.File]::WriteAllText($exe, 'unsigned')
        New-FixtureZip
        Assert-Rejected { Assert-WindowsReleaseArtifacts -PortableZip $zipPath } 'Release gate accepted an unsigned application executable'
        [System.IO.File]::WriteAllText($exe, 'signed')
        New-FixtureZip
        [System.IO.File]::WriteAllText($installer, 'vendor')
        Assert-Rejected { Assert-WindowsReleaseArtifacts -PortableZip $zipPath -Installer $installer } 'Release gate accepted an installer without a timestamp'
        [System.IO.File]::WriteAllText($installer, 'unsigned')
        Assert-Rejected { Assert-WindowsReleaseArtifacts -PortableZip $zipPath -Installer $installer } 'Release gate accepted an unsigned installer'

        Remove-Item -LiteralPath $exe
        New-FixtureZip
        Assert-Rejected { Assert-WindowsReleaseArtifacts -PortableZip $zipPath } 'Release gate accepted an archive without its application at the root'
        [System.IO.File]::WriteAllText($zipPath, 'not a ZIP archive')
        Assert-Rejected { Assert-WindowsReleaseArtifacts -PortableZip $zipPath } 'Release gate accepted a corrupt ZIP archive'
    }

    & {
        $project = Join-Path $testDirectory ('project [x] ' + [char]0x00e4 + ' literal$cash')
        $null = New-TestFile (Join-Path $project '.github\scripts\sign-file.ps1') 'param([string]$Path)'
        $arguments = @(Get-InnoSigningArguments -ProjectDirectory $project)
        Assert-True ($arguments -contains '/DSignWindows') 'Signed Inno Setup mode was not enabled'
        $command = @($arguments | Where-Object { $_ -like '/SWeatherReportSign=*' })
        Assert-True ($command.Count -eq 1) 'Inno Setup did not receive a unique signing tool'
        Assert-True ($command[0].Contains('$f')) 'Inno Setup signing command omitted its literal output path placeholder'
        Assert-True ($command[0].Contains('literal$$cash')) 'A literal dollar in the project path was not escaped for Inno Setup'
        Assert-True ($command[0].Contains('$q')) 'Inno Setup signing paths were not quoted'
        Assert-True ($command[0].Contains('-NonInteractive')) 'Inno Setup signer could prompt during unattended publication'
        Assert-True ($command[0].Contains('sign-file.ps1')) 'Inno Setup bypassed the shared signing verifier'
    }

    Write-Host 'Windows signing configuration, payload, and failure-handling tests passed.'
}
finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name])
    }
    $resolvedTestDirectory = [System.IO.Path]::GetFullPath($testDirectory)
    $resolvedTemporaryDirectory = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolvedTestDirectory.StartsWith($resolvedTemporaryDirectory, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing to clean a signing fixture outside the temporary directory.'
    }
    Remove-Item -LiteralPath $resolvedTestDirectory -Recurse -Force
}
