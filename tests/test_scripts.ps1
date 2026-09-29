$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Get-ScriptAst {
    param([string]$Name)

    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $root $Name), [ref]$tokens, [ref]$parseErrors
    )
    if ($parseErrors.Count) {
        throw "$Name contains syntax errors: $($parseErrors.Message -join '; ')"
    }
    return $ast
}

function Get-ScriptFunctions {
    param([string]$Name)

    $ast = Get-ScriptAst $Name
    # Load only definitions: never execute installer downloads or process termination.
    $definitions = $ast.FindAll({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
    }, $false) | ForEach-Object { $_.Extent.Text }
    return [scriptblock]::Create($definitions -join "`n")
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\')
$testDir = Join-Path $tempRoot "WeatherReportTests-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $testDir | Out-Null
try {
    foreach ($scriptName in @('install.ps1', 'uninstall.ps1')) {
        & {
            . (Get-ScriptFunctions $scriptName)
            $target = Join-Path $testDir 'WeatherReport\WeatherReport.exe'
            $other = Join-Path $testDir 'other\WeatherReport.exe'
            $script:stopped = @()
            $matching = [pscustomobject]@{ Path = $target.ToUpperInvariant(); HasExited = $false }
            $matching | Add-Member ScriptMethod WaitForExit { param($timeout) return $true }
            $otherProcess = [pscustomobject]@{ Path = $other; HasExited = $false }
            $unknown = [pscustomobject]@{ Path = $null; HasExited = $false }
            function Get-Process { param($Name, $ErrorAction) return @($matching, $otherProcess, $unknown) }
            function Stop-Process { param($InputObject, [switch]$Force) $script:stopped += $InputObject }
            Stop-InstalledApplication -ExecutablePath $target
            Assert-True ($script:stopped.Count -eq 1) "$scriptName stopped an unrelated process"
            Assert-True ([object]::ReferenceEquals($script:stopped[0], $matching)) 'Wrong process stopped'

            foreach ($case in @(
                @{ Name = 'already exited'; Exited = $true; Reject = $false; Stops = 0 },
                @{ Name = 'exits during stop'; ExitDuringStop = $true; Reject = $false; Stops = 1 },
                @{ Name = 'access denied'; StopError = $true; Reject = $true; Stops = 1 },
                @{ Name = 'exit timeout'; Timeout = $true; Reject = $true; Stops = 1 }
            )) {
                & {
                    $process = [pscustomobject]@{
                        Path = $target; HasExited = [bool]$case.Exited; StopCount = 0
                        WaitCount = 0; WaitResult = -not $case.Timeout
                    }
                    $process | Add-Member ScriptMethod WaitForExit {
                        param($timeout)
                        Assert-True ($timeout -eq 10000) 'Process exit wait is not bounded'
                        $this.WaitCount += 1
                        return $this.WaitResult
                    }
                    function Get-Process { param($Name, $ErrorAction) return @($process) }
                    function Stop-Process {
                        param($InputObject, [switch]$Force)
                        $InputObject.StopCount += 1
                        if ($case.ExitDuringStop) { $InputObject.HasExited = $true }
                        if ($case.ExitDuringStop -or $case.StopError) { throw 'simulated process stop failure' }
                    }
                    $rejected = $false
                    try { Stop-InstalledApplication -ExecutablePath $target }
                    catch { $rejected = $true }
                    Assert-True ($rejected -eq $case.Reject) "$scriptName mishandled process state: $($case.Name)"
                    Assert-True ($process.StopCount -eq $case.Stops) 'Unexpected process termination attempt'
                    if ($case.Exited -or $case.StopError) {
                        Assert-True ($process.WaitCount -eq 0) 'Waited after a stop failure or an already exited process'
                    }
                    else {
                        Assert-True ($process.WaitCount -eq 1) 'Did not confirm process termination'
                    }
                }
            }

            Assert-SafeInstallDirectory (Split-Path -Parent $target)
            foreach ($unsafePath in @([System.IO.Path]::GetPathRoot($testDir), $env:USERPROFILE, $testDir)) {
                $rejected = $false
                try { Assert-SafeInstallDirectory $unsafePath } catch { $rejected = $true }
                Assert-True $rejected "$scriptName accepted an unsafe install path"
            }
        }
    }

    & {
        . (Get-ScriptFunctions 'install.ps1')
        $target = Join-Path $testDir 'WeatherReport\WeatherReport.exe'
        $shortcutPath = Join-Path $testDir 'shortcut.lnk'
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = Join-Path $testDir 'pythonw.exe'
        $shortcut.Arguments = 'old-main.py'
        $shortcut.Save()
        New-Shortcut -Path $shortcutPath -Target $target -WorkingDirectory $testDir -Icon $target
        $updated = $shell.CreateShortcut($shortcutPath)
        Assert-True ($updated.TargetPath -eq $target) 'Shortcut target was not updated'
        Assert-True ($updated.Arguments -eq '') 'Shortcut retained stale launcher arguments'

        . (Get-ScriptFunctions 'uninstall.ps1')
        $foreignPath = Join-Path $testDir 'foreign.lnk'
        $foreign = $shell.CreateShortcut($foreignPath)
        $foreign.TargetPath = Join-Path $testDir 'other\WeatherReport.exe'
        $foreign.Save()
        Remove-InstalledShortcut -Path $foreignPath -ExecutablePath $target
        Assert-True (Test-Path -LiteralPath $foreignPath) 'Removed a shortcut belonging to another install'
        Remove-InstalledShortcut -Path $shortcutPath -ExecutablePath $target
        Assert-True (-not (Test-Path -LiteralPath $shortcutPath)) 'Owned shortcut was not removed'
        Remove-InstalledShortcut -Path $shortcutPath -ExecutablePath $target
    }

    & {
        . (Get-ScriptFunctions 'install.ps1')
        $package = Join-Path $testDir 'package'
        New-Item -ItemType Directory -Path $package | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $package 'WeatherReport.exe'), 'placeholder')
        $rejected = $false
        try { Assert-PortablePackage $package 'v0.1.1' } catch { $rejected = $true }
        Assert-True $rejected 'An executable without its Tk runtime was accepted'
        foreach ($relativePath in @(
            '_internal\_tkinter.pyd',
            '_internal\_tcl_data\init.tcl',
            '_internal\_tk_data\tk.tcl'
        )) {
            $path = Join-Path $package $relativePath
            New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
            [System.IO.File]::WriteAllText($path, 'placeholder')
        }
        $rejected = $false
        try { Assert-PortablePackage $package 'v0.1.1' } catch { $rejected = $true }
        Assert-True $rejected 'A package without Python was accepted'
        [System.IO.File]::WriteAllText((Join-Path $package '_internal\python313.dll'), 'placeholder')
        # Released v0.1.1 lacks the later weather icon library but must remain installable.
        Assert-PortablePackage $package 'v0.1.1'
        $rejected = $false
        try { Assert-PortablePackage $package 'v0.1.2' } catch { $rejected = $true }
        Assert-True $rejected 'A modern package without its required metadata was accepted'
        $packageMetadata = Join-Path $package '_internal\app_metadata.json'
        [System.IO.File]::WriteAllText($packageMetadata, '{"version":"0.1.2","date":"07.09.2026"}')
        $rejected = $false
        try { Assert-PortablePackage $package 'v0.1.2' } catch { $rejected = $true }
        Assert-True $rejected 'A modern package without its assets was accepted'
        foreach ($asset in @('weather-icons\unknown.png', 'weather-icons\cloud.png', 'metric-icons\wind.png', 'fonts\Exo2-Regular.ttf')) {
            $assetPath = Join-Path $package "_internal\assets\$asset"
            New-Item -ItemType Directory -Path (Split-Path -Parent $assetPath) -Force | Out-Null
            [System.IO.File]::WriteAllText($assetPath, 'placeholder')
        }
        Assert-PortablePackage $package 'v0.1.2'
        foreach ($expected in @('', 'v0.1.3', 'bad', 'v1.2.3-rc1')) {
            $rejected = $false
            try { Assert-PortablePackage $package $expected } catch { $rejected = $true }
            Assert-True $rejected 'Package version mismatch was not rejected'
        }
        foreach ($invalid in @('{"version":"0.1.2","date":"31.02.2026"}', '{broken')) {
            [System.IO.File]::WriteAllText($packageMetadata, $invalid)
            $rejected = $false
            try { Assert-PortablePackage $package 'v0.1.2' } catch { $rejected = $true }
            Assert-True $rejected 'Invalid package metadata was not rejected'
        }

        # Exercise the installer's actual failure handler, without running downloads or launchers.
        $ast = Get-ScriptAst 'install.ps1'
        $transaction = $ast.EndBlock.Statements | Where-Object {
            $_ -is [System.Management.Automation.Language.TryStatementAst]
        } | Select-Object -Last 1
        Assert-True ($null -ne $transaction) 'Installer transaction was not found'
        $rollback = [scriptblock]::Create(($transaction.CatchClauses[0].Body.Statements |
            ForEach-Object { $_.Extent.Text }) -join "`n")

        foreach ($hadExistingInstall in @($false, $true)) {
            $caseDir = Join-Path $testDir "rollback-$hadExistingInstall"
            $InstallDir = [System.IO.Path]::GetFullPath((Join-Path $caseDir 'WeatherReport'))
            $backupDir = "$InstallDir.backup-test"
            foreach ($target in @($InstallDir, $backupDir)) {
                Assert-True ($target.StartsWith("$testDir\", [System.StringComparison]::OrdinalIgnoreCase)) 'Unsafe rollback test path'
            }
            Assert-SafeInstallDirectory $InstallDir
            New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
            [System.IO.File]::WriteAllText((Join-Path $InstallDir 'new.txt'), 'new version')
            if ($hadExistingInstall) {
                New-Item -ItemType Directory -Path $backupDir | Out-Null
                [System.IO.File]::WriteAllText((Join-Path $backupDir 'old.txt'), 'old version')
            }
            $changed = Join-Path $caseDir 'desktop.lnk'
            $removed = Join-Path $caseDir 'legacy-startup.lnk'
            $created = Join-Path $caseDir 'new-start-menu.lnk'
            [System.IO.File]::WriteAllText($changed, 'original desktop shortcut')
            [System.IO.File]::WriteAllText($removed, 'original startup shortcut')
            $shortcutSnapshot = @(Get-ShortcutSnapshot @($changed, $removed, $created))
            [System.IO.File]::WriteAllText($changed, 'replacement shortcut')
            Remove-Item -LiteralPath $removed
            [System.IO.File]::WriteAllText($created, 'new shortcut')
            $newInstallActivated = $true
            $caught = $false
            try {
                try { throw 'simulated launch failure' }
                catch { & $rollback }
            }
            catch { $caught = $_.Exception.Message -eq 'simulated launch failure' }
            Assert-True $caught 'Rollback did not preserve the original failure'
            Assert-True ([System.IO.File]::ReadAllText($changed) -eq 'original desktop shortcut') 'Desktop shortcut was not restored'
            Assert-True ([System.IO.File]::ReadAllText($removed) -eq 'original startup shortcut') 'Legacy startup shortcut was not restored'
            Assert-True (-not (Test-Path -LiteralPath $created)) 'Failed first install left a new shortcut behind'
            Assert-True (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'new.txt'))) 'Failed installation was not removed'
            if ($hadExistingInstall) {
                Assert-True ([System.IO.File]::ReadAllText((Join-Path $InstallDir 'old.txt')) -eq 'old version') 'Previous application was not restored'
            }
            else {
                Assert-True (-not (Test-Path -LiteralPath $InstallDir)) 'Failed first install left its directory behind'
            }
        }
    }

    & {
        . (Get-ScriptFunctions 'install.ps1')
        foreach ($exitCode in @($null, 0, 1)) {
            $process = [pscustomobject]@{ ExitCode = $exitCode; Disposed = $false }
            $process | Add-Member ScriptMethod WaitForExit {
                param($timeout)
                Assert-True ($timeout -eq 1500) 'Startup probe must be bounded'
                return $null -ne $this.ExitCode
            }
            $process | Add-Member ScriptMethod Dispose { $this.Disposed = $true }
            function Start-Process {
                param($FilePath, $WorkingDirectory, $WindowStyle, [switch]$PassThru)
                Assert-True ($WindowStyle -eq 'Hidden' -and $PassThru) 'Incorrect app launch options'
                return $process
            }
            $rejected = $false
            try { Start-InstalledApplication -ExecutablePath 'app.exe' -WorkingDirectory $testDir }
            catch { $rejected = $true }
            Assert-True ($rejected -eq ($null -ne $exitCode)) 'Early app exit was not detected'
            Assert-True $process.Disposed 'Startup probe leaked the process handle'
        }
    }

    & {
        . (Get-ScriptFunctions 'install.ps1')
        $apiUrl = 'https://example.invalid/releases/latest'
        function Invoke-RestMethod {
            param($Uri, $Headers, $TimeoutSec)
            Assert-True ($TimeoutSec -gt 0 -and $TimeoutSec -le 60) 'Release lookup has no bounded timeout'
            return @{ tag_name = 'v1.0.0' }
        }
        function Invoke-WebRequest {
            param($Uri, $OutFile, [switch]$UseBasicParsing, $TimeoutSec)
            Assert-True ($TimeoutSec -gt 0 -and $TimeoutSec -le 300) 'Download has no bounded timeout'
        }
        $null = Get-LatestRelease
        Invoke-Download -Uri 'https://example.invalid/app.zip' -OutFile (Join-Path $testDir 'app.zip')
    }

    & {
        . (Get-ScriptFunctions 'build_release.ps1')
        $metadataPath = Join-Path $testDir 'app_metadata.json'
        [System.IO.File]::WriteAllText($metadataPath, '{"version":"1.2.3","date":"07.09.2026"}')
        foreach ($requested in @('', '1.2.3', 'v1.2.3')) {
            Assert-True ((Resolve-BuildVersion $metadataPath $requested) -eq '1.2.3') 'Build did not use application metadata'
        }
        foreach ($requested in @('v9.9.9', 'vv1.2.3', 'v1.2.3-rc1')) {
            $rejected = $false
            try { Resolve-BuildVersion $metadataPath $requested } catch { $rejected = $true }
            Assert-True $rejected 'Build accepted a version that differs from the application'
        }
        foreach ($invalid in @('{"version":"bad","date":"07.09.2026"}', '{"version":"1.2.3","date":"31.02.2026"}')) {
            [System.IO.File]::WriteAllText($metadataPath, $invalid)
            $rejected = $false
            try { Resolve-BuildVersion $metadataPath } catch { $rejected = $true }
            Assert-True $rejected 'Build accepted invalid release metadata'
        }
    }

    & {
        . (Get-ScriptFunctions 'install.ps1')
        $downloadDir = Join-Path $testDir 'checksums [literal]'
        New-Item -ItemType Directory -Path $downloadDir | Out-Null
        $assetName = 'WeatherReport-portable.zip'
        $assetPath = Join-Path $downloadDir $assetName
        [System.IO.File]::WriteAllText($assetPath, 'original package')
        $hash = (Get-FileHash -LiteralPath $assetPath -Algorithm SHA256).Hash
        $release = @{ assets = @(@{ name = 'SHA256SUMS.txt'; browser_download_url = 'https://example.invalid/checksums' }) }
        $downloads = New-Object 'System.Collections.Generic.List[string]'
        function Invoke-Download {
            param($Uri, $OutFile)
            $downloads.Add($Uri)
            [System.IO.File]::WriteAllText($OutFile, $manifest)
        }
        $manifest = "$hash  $assetName`n"
        Test-AssetChecksum -Release $release -AssetName $assetName -AssetPath $assetPath
        Assert-True ($downloads.Count -eq 1) 'The published checksum was not fetched'
        foreach ($invalidManifest in @("$hash  other.zip`n", "invalid  $assetName`n", "$hash  $assetName`n")) {
            $manifest = $invalidManifest
            [System.IO.File]::WriteAllText($assetPath, 'corrupted package')
            $rejected = $false
            try { Test-AssetChecksum -Release $release -AssetName $assetName -AssetPath $assetPath }
            catch { $rejected = $true }
            Assert-True $rejected 'Missing, malformed or mismatching package checksum was accepted'
        }
        $downloads.Clear()
        Test-AssetChecksum -Release @{ assets = @() } -AssetName $assetName -AssetPath $assetPath
        Assert-True ($downloads.Count -eq 0) 'Legacy releases without a checksum attempted a download'
    }

    & {
        $distDir = Join-Path $testDir 'build [literal]'
        $internal = Join-Path $distDir '_internal'
        New-Item -ItemType Directory -Path $internal -Force | Out-Null
        [System.IO.File]::WriteAllText((Join-Path $distDir 'WeatherReport.exe'), 'test exe')
        [System.IO.File]::WriteAllText((Join-Path $internal 'app_metadata.json'), 'test metadata')
        $zipPath = Join-Path $testDir 'WeatherReport-portable [literal].zip'
        $extractDir = Join-Path $testDir 'expanded [literal]'
        foreach ($item in @(
            @{ Script = 'build_release.ps1'; Command = 'Compress-Archive' },
            @{ Script = 'install.ps1'; Command = 'Expand-Archive' }
        )) {
            # Run the actual archive commands only, never the build/install entrypoints.
            $command = (Get-ScriptAst $item.Script).Find({
                param($node)
                $node -is [System.Management.Automation.Language.CommandAst] -and
                    $node.GetCommandName() -eq $item.Command
            }, $true)
            Assert-True ($null -ne $command) "Archive command not found: $($item.Script)"
            & ([scriptblock]::Create($command.Extent.Text))
        }
        Assert-True ([System.IO.File]::ReadAllText((Join-Path $extractDir 'WeatherReport.exe')) -eq 'test exe') 'Package root layout changed'
        Assert-True ([System.IO.File]::ReadAllText((Join-Path $extractDir '_internal\app_metadata.json')) -eq 'test metadata') 'Nested package content changed'
    }

    & {
        . (Get-ScriptFunctions 'publish_release.ps1')
        $state = @{ Dirty = $false; Commit = 'built-commit'; Branch = 'main' }
        function Get-RequiredCommandOutput {
            param($Command, $Arguments)
            switch ($Arguments[0]) {
                'status' { if ($state.Dirty) { return ' M main.py' } }
                'rev-parse' { return $state.Commit }
                'branch' { return $state.Branch }
                default { throw "Unexpected command: $Arguments" }
            }
        }
        Assert-ReleaseSourceUnchanged -Commit 'built-commit' -Branch 'main'
        foreach ($change in @('Dirty', 'Commit', 'Branch')) {
            $state = @{ Dirty = $false; Commit = 'built-commit'; Branch = 'main' }
            $state[$change] = if ($change -eq 'Dirty') { $true } else { 'changed' }
            $rejected = $false
            try { Assert-ReleaseSourceUnchanged -Commit 'built-commit' -Branch 'main' }
            catch { $rejected = $true }
            Assert-True $rejected "Publishing accepted changed build input: $change"
        }
    }
    & {
        . (Get-ScriptFunctions 'publish_release.ps1')
        $repository = Join-Path $testDir ('publish-' + [char]0x00e4 + [char]0x6771 + [char]0x4eac)
        $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('init', '-b', 'main', $repository)
        Push-Location -LiteralPath $repository
        try {
            $previousEncoding = [Console]::OutputEncoding
            Assert-ReleaseRepository -Directory $repository
            Assert-True ([Console]::OutputEncoding.CodePage -eq $previousEncoding.CodePage) 'Native command parsing changed console encoding'
            $rejected = $false
            try { Assert-ReleaseRepository -Directory $testDir } catch { $rejected = $true }
            Assert-True $rejected 'Publishing accepted the wrong repository root'
            $previousIndex = $env:GIT_INDEX_FILE
            try {
                $env:GIT_INDEX_FILE = Join-Path $testDir 'foreign-index'
                $rejected = $false
                try { Assert-ReleaseRepository -Directory $repository } catch { $rejected = $true }
                Assert-True $rejected 'Publishing accepted an inherited foreign index'
            }
            finally { $env:GIT_INDEX_FILE = $previousIndex }
            $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('config', 'status.showUntrackedFiles', 'no')
            [System.IO.File]::WriteAllText((Join-Path $repository 'notes.txt'), 'uncommitted notes')
            $rejected = $false
            try { Assert-CleanWorkingTree } catch { $rejected = $true }
            Assert-True $rejected 'Publishing ignored untracked files hidden by Git configuration'
        }
        finally { Pop-Location }
    }
    & {
        . (Get-ScriptFunctions '.github/scripts/publish-release.ps1')
        $artifacts = @((Join-Path $testDir 'app.zip'), (Join-Path $testDir 'SHA256SUMS.txt'))
        foreach ($artifact in $artifacts) { [System.IO.File]::WriteAllText($artifact, 'test artifact') }
        $draftJson = '{"tagName":"v1.2.3","isDraft":true}'
        foreach ($case in @(
            @{ Name = 'new'; Json = ''; Fail = 'view'; Calls = 'view,create,upload,edit'; Reject = $false },
            @{ Name = 'retry draft'; Json = $draftJson; Calls = 'view,upload,edit'; Reject = $false },
            @{ Name = 'published'; Json = '{"tagName":"v1.2.3","isDraft":false}'; Calls = 'view'; Reject = $true },
            @{ Name = 'wrong tag'; Json = '{"tagName":"v1.2.4","isDraft":true}'; Calls = 'view'; Reject = $true },
            @{ Name = 'invalid state'; Json = '{"tagName":"v1.2.3","isDraft":"false"}'; Calls = 'view'; Reject = $true },
            @{ Name = 'invalid JSON'; Json = 'invalid'; Calls = 'view'; Reject = $true },
            @{ Name = 'create failure'; Json = ''; Fail = @('view', 'create'); Calls = 'view,create'; Reject = $true },
            @{ Name = 'upload failure'; Json = $draftJson; Fail = 'upload'; Calls = 'view,upload'; Reject = $true },
            @{ Name = 'publish failure'; Json = $draftJson; Fail = 'edit'; Calls = 'view,upload,edit'; Reject = $true }
        )) {
            $calls = New-Object 'System.Collections.Generic.List[string]'
            function gh {
                Assert-True ($args[0] -eq 'release' -and $args[2] -ceq 'v1.2.3') 'Unexpected release command'
                $command = $args[1]
                $calls.Add($command)
                $global:LASTEXITCODE = if (@($case.Fail) -contains $command) { 1 } else { 0 }
                switch ($command) {
                    'view' { return $case.Json }
                    'create' {
                        Assert-True ($args -contains '--draft' -and $args -contains '--verify-tag') 'Release was not created as a verified draft'
                    }
                    'upload' {
                        Assert-True ($args -contains '--clobber') 'Draft retry cannot replace incomplete assets'
                        foreach ($artifact in $artifacts) {
                            Assert-True ($args -contains $artifact) 'Release upload omitted an artifact'
                        }
                    }
                    'edit' {
                        Assert-True ($args -contains '--draft=false' -and $args -contains '--latest') 'Release was not published as latest'
                    }
                    default { throw "Unexpected release command: $command" }
                }
            }
            $rejected = $false
            try { Publish-ReleaseAssets -Tag 'v1.2.3' -Artifacts $artifacts }
            catch { $rejected = $true }
            Assert-True ($rejected -eq $case.Reject) "Wrong release result: $($case.Name)"
            Assert-True (($calls -join ',') -ceq $case.Calls) "Unsafe release command sequence: $($case.Name): $calls"
        }
        $calls.Clear()
        foreach ($invalid in @(
            @{ Tag = 'bad'; Artifacts = $artifacts },
            @{ Tag = 'v1.2.3'; Artifacts = @() },
            @{ Tag = 'v1.2.3'; Artifacts = @((Join-Path $testDir 'missing.zip')) }
        )) {
            $rejected = $false
            try { Publish-ReleaseAssets @invalid }
            catch { $rejected = $true }
            Assert-True $rejected 'Publishing accepted invalid tag or missing artifacts'
        }
        Assert-True ($calls.Count -eq 0) 'Invalid input reached GitHub'
    }
    Write-Output 'Installer and release safety checks passed.'
}
finally {
    $resolvedTestDir = [System.IO.Path]::GetFullPath($testDir)
    if (-not $resolvedTestDir.StartsWith("$tempRoot\WeatherReportTests-", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean an unexpected test directory: $resolvedTestDir"
    }
    Remove-Item -LiteralPath $resolvedTestDir -Recurse -Force
}
