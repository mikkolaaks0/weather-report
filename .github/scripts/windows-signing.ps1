# Shared by the build, Inno Setup callback, and release publishers.
function Resolve-WindowsSigningConfiguration {
    param([switch]$AllowUnsigned)

    $signingScript = $env:WEATHERREPORT_SIGNING_SCRIPT
    $thumbprint = $env:WEATHERREPORT_SIGNING_CERTIFICATE
    if ($signingScript -and $thumbprint) {
        throw 'Choose WEATHERREPORT_SIGNING_SCRIPT or WEATHERREPORT_SIGNING_CERTIFICATE, not both.'
    }
    if (-not $signingScript -and -not $thumbprint) {
        if ($AllowUnsigned) { return $null }
        throw 'Windows code signing is not configured. Set WEATHERREPORT_SIGNING_SCRIPT or WEATHERREPORT_SIGNING_CERTIFICATE. Only local test builds may use -AllowUnsigned.'
    }

    $timestampUrl = $env:WEATHERREPORT_TIMESTAMP_URL
    if (-not $timestampUrl) { $timestampUrl = 'https://timestamp.digicert.com' }
    $uri = $null
    if (-not [uri]::TryCreate($timestampUrl, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -notin @('http', 'https') -or -not $uri.Host -or $uri.UserInfo) {
        throw 'WEATHERREPORT_TIMESTAMP_URL must be an absolute HTTP(S) timestamp service URL without credentials.'
    }

    if ($signingScript) {
        $item = Get-Item -LiteralPath $signingScript -ErrorAction Stop
        if ($item.PSIsContainer -or $item.Extension -ine '.ps1' -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'WEATHERREPORT_SIGNING_SCRIPT must name a regular PowerShell .ps1 file.'
        }
        return @{ Script = $item.FullName; TimestampUrl = $timestampUrl }
    }

    $thumbprint = ($thumbprint -replace '\s', '').ToUpperInvariant()
    if ($thumbprint -cnotmatch '^[0-9A-F]{40}$') {
        throw 'WEATHERREPORT_SIGNING_CERTIFICATE must contain a SHA-1 certificate thumbprint.'
    }
    $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$thumbprint" -ErrorAction Stop
    $now = Get-Date
    $codeSigning = @($certificate.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.37' } |
        ForEach-Object { $_.EnhancedKeyUsages } | Where-Object { $_.Value -eq '1.3.6.1.5.5.7.3.3' })
    if (-not $certificate.HasPrivateKey -or $certificate.NotBefore -gt $now -or
        $certificate.NotAfter -le $now -or -not $codeSigning) {
        throw 'The selected certificate must be current, include a private key, and permit code signing.'
    }
    $signTool = Get-Command signtool.exe -CommandType Application -ErrorAction SilentlyContinue
    if (-not $signTool) {
        throw 'signtool.exe was not found. Add the Windows SDK signing tools to PATH, or configure WEATHERREPORT_SIGNING_SCRIPT.'
    }
    return @{ Certificate = $thumbprint; SignTool = $signTool.Source; TimestampUrl = $timestampUrl }
}

function Get-WindowsNativeFiles {
    param([Parameter(Mandatory = $true)][string]$Directory)

    $directoryItem = Get-Item -LiteralPath $Directory -ErrorAction Stop
    if (-not $directoryItem.PSIsContainer -or ($directoryItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Native package must be a regular directory: $Directory"
    }
    # Walk explicitly so junctions are rejected before any recursion can follow them.
    $pending = New-Object 'System.Collections.Generic.Queue[string]'
    $pending.Enqueue($directoryItem.FullName)
    $files = New-Object 'System.Collections.Generic.List[string]'
    while ($pending.Count) {
        foreach ($item in Get-ChildItem -LiteralPath $pending.Dequeue() -Force -ErrorAction Stop) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Linked files and directories cannot be signed as package contents: $($item.FullName)"
            }
            if ($item.PSIsContainer) { $pending.Enqueue($item.FullName) }
            elseif ($item.Extension -in @('.exe', '.dll', '.pyd')) { $files.Add($item.FullName) }
        }
    }
    if (-not $files.Count) { throw "No Windows native files found in package: $Directory" }
    return $files | Sort-Object
}

function Assert-WindowsFileSignature {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$RequireTimestamp
    )

    $signature = Get-AuthenticodeSignature -LiteralPath $Path -ErrorAction Stop
    if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate) {
        throw "Windows signature verification failed ($($signature.Status)): $Path"
    }
    if ($RequireTimestamp -and -not $signature.TimeStamperCertificate) {
        throw "New Windows signatures must include a trusted timestamp: $Path"
    }
}

function Invoke-WindowsFileSigning {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][hashtable]$Configuration
    )

    $signature = Get-AuthenticodeSignature -LiteralPath $Path -ErrorAction Stop
    if ($signature.Status -eq 'Valid' -and $signature.SignerCertificate) { return }
    if ($signature.Status -ne 'NotSigned') {
        throw "Refusing to overwrite an invalid existing Windows signature ($($signature.Status)): $Path"
    }
    Write-Host "Signing: $Path"
    # PowerShell native commands update the global automatic variable, including
    # commands inside a provider script. A local variable would hide failures.
    $global:LASTEXITCODE = 0
    if ($Configuration.Script) {
        & $Configuration.Script -Path $Path | Out-Host
    }
    elseif ($Configuration.Certificate -and $Configuration.SignTool) {
        & $Configuration.SignTool sign /sha1 $Configuration.Certificate /s My /fd SHA256 `
            /tr $Configuration.TimestampUrl /td SHA256 /d 'Weather Report' $Path | Out-Host
    }
    else { throw 'Invalid Windows signing configuration.' }
    $exitCode = $global:LASTEXITCODE
    if ($exitCode -ne 0) { throw "Windows signing command failed with exit code ${exitCode}: $Path" }
    Assert-WindowsFileSignature -Path $Path -RequireTimestamp
}

function Invoke-WindowsPackageSigning {
    param([string]$Directory, [hashtable]$Configuration)

    foreach ($file in Get-WindowsNativeFiles -Directory $Directory) {
        Invoke-WindowsFileSigning -Path $file -Configuration $Configuration
    }
    # A provider must not modify files it already signed when signing a later file.
    foreach ($file in Get-WindowsNativeFiles -Directory $Directory) {
        Assert-WindowsFileSignature -Path $file
    }
}

function Get-InnoSigningArguments {
    param([Parameter(Mandatory = $true)][string]$ProjectDirectory)

    $shellPath = (Get-Process -Id $PID).Path
    $callbackPath = Join-Path $ProjectDirectory '.github\scripts\sign-file.ps1'
    # Inno expands $q to a quote and $f to the quoted target filename. Escape
    # literal dollar signs in paths before introducing these placeholders.
    $shellPath = $shellPath.Replace('$', '$$')
    $callbackPath = $callbackPath.Replace('$', '$$')
    $command = '$q' + $shellPath + '$q -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $q' +
        $callbackPath + '$q -Path $f'
    return @('/DSignWindows', "/SWeatherReportSign=$command")
}

function Assert-WindowsReleaseArtifacts {
    param([string]$PortableZip, [string]$Installer)

    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
    $tempDirectory = Join-Path $tempRoot "WeatherReportSignatures-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $tempDirectory -ErrorAction Stop | Out-Null
    try {
        Expand-Archive -LiteralPath $PortableZip -DestinationPath $tempDirectory -ErrorAction Stop
        $executable = Join-Path $tempDirectory 'WeatherReport.exe'
        if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
            throw 'The portable archive must contain WeatherReport.exe at its root.'
        }
        Assert-WindowsFileSignature -Path $executable -RequireTimestamp
        foreach ($file in Get-WindowsNativeFiles -Directory $tempDirectory) {
            Assert-WindowsFileSignature -Path $file
        }
        if ($Installer) { Assert-WindowsFileSignature -Path $Installer -RequireTimestamp }
    }
    finally {
        $resolvedDirectory = [IO.Path]::GetFullPath($tempDirectory)
        if (-not $resolvedDirectory.StartsWith("$tempRoot\WeatherReportSignatures-", [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean an unexpected signature-verification directory: $resolvedDirectory"
        }
        Remove-Item -LiteralPath $resolvedDirectory -Recurse -Force -ErrorAction Stop
    }
}
