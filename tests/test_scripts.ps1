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

            $existingPath = Join-Path $testDir "$scriptName\WeatherReport"
            New-Item -ItemType Directory -Path (Split-Path -Parent $existingPath) | Out-Null
            [System.IO.File]::WriteAllText($existingPath, 'unrelated user file')
            $errorMessage = ''
            try { Assert-SafeInstallDirectory $existingPath } catch { $errorMessage = $_.Exception.Message }
            Assert-True ($errorMessage -like '*must be a regular directory*') "$scriptName accepted a regular file as an installation directory"
            Assert-True ([System.IO.File]::ReadAllText($existingPath) -eq 'unrelated user file') 'Path validation changed a user file'

            $directoryPath = Join-Path $testDir "$scriptName\Weather Report"
            New-Item -ItemType Directory -Path $directoryPath | Out-Null
            Assert-SafeInstallDirectory $directoryPath
            & {
                $inspection = @{ Path = $null }
                function Get-Item {
                    param($LiteralPath, [switch]$Force, $ErrorAction)
                    $inspection.Path = $LiteralPath
                    return [pscustomobject]@{
                        PSIsContainer = $true
                        Attributes = [System.IO.FileAttributes]::Directory -bor [System.IO.FileAttributes]::ReparsePoint
                    }
                }
                $errorMessage = ''
                try { Assert-SafeInstallDirectory $directoryPath } catch { $errorMessage = $_.Exception.Message }
                Assert-True ($inspection.Path -eq $directoryPath) 'Inspected an unexpected directory'
                Assert-True ($errorMessage -like '*must be a regular directory*') "$scriptName accepted a linked installation directory"
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
        $locationCommands = foreach ($scriptName in @('build_release.ps1', 'publish_release.ps1')) {
            $command = (Get-ScriptAst $scriptName).Find({
                param($node)
                $node -is [System.Management.Automation.Language.CommandAst] -and
                    $node.GetCommandName() -eq 'Set-Location'
            }, $true)
            Assert-True ($null -ne $command) "Project directory selection not found: $scriptName"
            [scriptblock]::Create($command.Extent.Text)
        }
        $root = Join-Path $testDir ('source [literal] ' + [char]0x00e4 + [char]0x6771 + [char]0x4eac)
        New-Item -ItemType Directory -Path $root | Out-Null
        Push-Location -LiteralPath $testDir
        try {
            foreach ($command in $locationCommands) {
                & $command
                Assert-True ($PWD.Path -eq $root) 'Build/publish did not enter the literal project directory'
                Set-Location -LiteralPath $testDir
            }
        }
        finally { Pop-Location }
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
        . (Get-ScriptFunctions 'build_release.ps1')
        $projectDirectory = Join-Path $testDir 'build python [literal]'
        New-Item -ItemType Directory -Path $projectDirectory | Out-Null

        # A clean checkout can still use an installed interpreter without creating a venv.
        $fallback = Resolve-PythonCommand -ProjectDirectory $projectDirectory
        Assert-True ($fallback.Command -in @('py', 'python', 'python3')) 'Build fallback selected an unexpected interpreter'
        $venvDirectory = Join-Path $projectDirectory '.venv'
        Assert-True (-not (Test-Path -LiteralPath $venvDirectory)) 'Interpreter discovery created a virtual environment'

        # No dependencies are installed: use a real temporary venv to check selection and Tk imports.
        Invoke-Python -Python $fallback -Arguments @('-m', 'venv', '--without-pip', $venvDirectory)
        $venvPython = Join-Path $venvDirectory 'Scripts\python.exe'
        Push-Location -LiteralPath $projectDirectory
        try {
            & {
                function Get-Command { throw 'Project builds must not inspect global Python when .venv exists' }
                $selected = Resolve-PythonCommand -ProjectDirectory $projectDirectory
                Assert-True ($selected.Command -eq $venvPython -and $selected.Args.Count -eq 0) 'Build did not prefer the project virtual environment'

                [System.IO.File]::WriteAllText((Join-Path $projectDirectory 'tkinter.py'), "raise ImportError('simulated unavailable Tkinter')`n")
                $errorMessage = ''
                try { Resolve-PythonCommand -ProjectDirectory $projectDirectory }
                catch { $errorMessage = $_.Exception.Message }
                Assert-True ($errorMessage -like '*project .venv is unusable*') 'Build accepted a venv without Tkinter or fell back to global Python'

                $brokenProject = Join-Path $testDir 'broken build environment'
                New-Item -ItemType Directory -Path (Join-Path $brokenProject '.venv') | Out-Null
                $errorMessage = ''
                try { Resolve-PythonCommand -ProjectDirectory $brokenProject }
                catch { $errorMessage = $_.Exception.Message }
                Assert-True ($errorMessage -like '*project .venv is unusable*') 'Build fell back to global Python for an incomplete venv'
            }
        }
        finally { Pop-Location }
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
        . (Get-ScriptFunctions 'publish_release.ps1')
        $origin = Join-Path $testDir 'release-origin.git'
        $repository = Join-Path $testDir 'release retry [literal]'
        $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('init', '--bare', $origin)
        $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('init', '-b', 'main', $repository)
        Push-Location -LiteralPath $repository
        try {
            foreach ($entry in @(
                @('user.name', 'Release Test'), @('user.email', 'release@example.invalid'),
                @('commit.gpgsign', 'false'), @('tag.gpgsign', 'false'),
                @('core.hooksPath', (Join-Path $testDir 'no-release-hooks'))
            )) {
                $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('config', $entry[0], $entry[1])
            }
            $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('commit', '--allow-empty', '-m', 'first')
            $firstCommit = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', 'HEAD')
            $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('commit', '--allow-empty', '-m', 'second')
            $secondCommit = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', 'HEAD')
            $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('remote', 'add', 'origin', $origin)

            # Only this temporary repository and its local bare origin receive tags.
            Publish-LocalReleaseTag -Tag 'v1.2.3' -Commit $firstCommit
            $tagObject = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', 'refs/tags/v1.2.3')
            Publish-LocalReleaseTag -Tag 'v1.2.3' -Commit $firstCommit
            Assert-True ((Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', 'refs/tags/v1.2.3')) -eq $tagObject) 'Retry rewrote an existing release tag'
            $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('tag', '-d', 'v1.2.3')
            Publish-LocalReleaseTag -Tag 'v1.2.3' -Commit $firstCommit
            Assert-True ((Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', 'refs/tags/v1.2.3')) -eq $tagObject) 'Remote-only retry did not fetch the original release tag'

            $originalInvoke = (Get-Command Invoke-RequiredCommand).ScriptBlock
            $interruption = @{ Operation = ''; Pending = $false }
            function Invoke-RequiredCommand {
                param([string]$Command, [string[]]$Arguments)
                if ($interruption.Pending -and $Arguments[0] -eq $interruption.Operation) {
                    $interruption.Pending = $false
                    throw 'simulated interrupted tag publication'
                }
                & $originalInvoke -Command $Command -Arguments $Arguments
            }
            foreach ($case in @(
                @{ Operation = 'tag'; Tag = 'v1.2.4' },
                @{ Operation = 'push'; Tag = 'v1.2.5' }
            )) {
                $interruption.Operation = $case.Operation
                $interruption.Pending = $true
                $rejected = $false
                try { Publish-LocalReleaseTag -Tag $case.Tag -Commit $firstCommit }
                catch { $rejected = $_.Exception.Message -eq 'simulated interrupted tag publication' }
                Assert-True $rejected 'Simulated tag/push interruption was not reported'
                Publish-LocalReleaseTag -Tag $case.Tag -Commit $firstCommit
                $localObject = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', "refs/tags/$($case.Tag)")
                $remoteObject = Get-RequiredCommandOutput -Command 'git' -Arguments @('ls-remote', '--tags', 'origin', "refs/tags/$($case.Tag)")
                Assert-True ($remoteObject.StartsWith("$localObject`t")) 'Retry did not publish the original local tag'
            }
            foreach ($case in @(
                @{ Tag = 'v1.2.6'; Target = $firstCommit; Message = 'foreign annotation'; Requested = $firstCommit },
                @{ Tag = 'v1.2.7'; Target = $firstCommit; Message = '[local-release]'; Requested = $secondCommit },
                @{ Tag = 'v1.2.8'; Target = $firstCommit; Message = $null; Requested = $firstCommit }
            )) {
                $arguments = @('tag')
                if ($case.Message) { $arguments += @('-a', '-m', $case.Message) }
                $arguments += @($case.Tag, $case.Target)
                $null = Get-RequiredCommandOutput -Command 'git' -Arguments $arguments
                $before = Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', "refs/tags/$($case.Tag)")
                $rejected = $false
                try { Publish-LocalReleaseTag -Tag $case.Tag -Commit $case.Requested } catch { $rejected = $true }
                Assert-True $rejected 'Publishing reused a foreign, lightweight, or wrong-commit tag'
                Assert-True ((Get-RequiredCommandOutput -Command 'git' -Arguments @('rev-parse', "refs/tags/$($case.Tag)")) -eq $before) 'Rejected publication changed the local tag'
                Assert-True (-not (Get-RequiredCommandOutput -Command 'git' -Arguments @('ls-remote', '--tags', 'origin', "refs/tags/$($case.Tag)"))) 'Rejected tag was pushed'
            }

            Publish-LocalReleaseTag -Tag 'v1.2.9' -Commit $firstCommit
            $remoteBefore = Get-RequiredCommandOutput -Command 'git' -Arguments @('ls-remote', '--tags', 'origin', 'refs/tags/v1.2.9')
            $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('tag', '-d', 'v1.2.9')
            $null = Get-RequiredCommandOutput -Command 'git' -Arguments @('tag', '-a', 'v1.2.9', $firstCommit, '-m', 'different object [local-release]')
            $rejected = $false
            try { Publish-LocalReleaseTag -Tag 'v1.2.9' -Commit $firstCommit } catch { $rejected = $true }
            Assert-True $rejected 'Publishing accepted different local and remote tag objects for the same commit'
            Assert-True ((Get-RequiredCommandOutput -Command 'git' -Arguments @('ls-remote', '--tags', 'origin', 'refs/tags/v1.2.9')) -eq $remoteBefore) 'Rejected publication rewrote the remote tag'
        }
        finally { Pop-Location }
    }

    & {
        . (Get-ScriptFunctions '.github/scripts/release-assets.ps1')
        $artifacts = @((Join-Path $testDir 'app.zip'), (Join-Path $testDir 'SHA256SUMS.txt'))
        foreach ($artifact in $artifacts) { [System.IO.File]::WriteAllText($artifact, 'test artifact') }
        $draftJson = '{"tagName":"v1.2.3","isDraft":true}'
        foreach ($case in @(
            @{ Name = 'new'; Json = ''; Fail = 'view'; Calls = 'view,create,upload,api,edit'; Reject = $false; Latest = 'true' },
            @{ Name = 'retry draft'; Json = $draftJson; Published = @('v1.2.2', 'v1.1.9'); Calls = 'view,upload,api,edit'; Reject = $false; Latest = 'true' },
            @{ Name = 'old draft retry'; Json = $draftJson; Published = @('v1.1.0', 'v1.10.0'); Calls = 'view,upload,api,edit'; Reject = $false; Latest = 'false' },
            @{ Name = 'same version published'; Json = $draftJson; Published = @('1.2.3'); Calls = 'view,upload,api,edit'; Reject = $false; Latest = 'false' },
            @{ Name = 'published'; Json = '{"tagName":"v1.2.3","isDraft":false}'; Calls = 'view'; Reject = $true },
            @{ Name = 'wrong tag'; Json = '{"tagName":"v1.2.4","isDraft":true}'; Calls = 'view'; Reject = $true },
            @{ Name = 'invalid state'; Json = '{"tagName":"v1.2.3","isDraft":"false"}'; Calls = 'view'; Reject = $true },
            @{ Name = 'invalid JSON'; Json = 'invalid'; Calls = 'view'; Reject = $true },
            @{ Name = 'create failure'; Json = ''; Fail = @('view', 'create'); Calls = 'view,create'; Reject = $true },
            @{ Name = 'upload failure'; Json = $draftJson; Fail = 'upload'; Calls = 'view,upload'; Reject = $true },
            @{ Name = 'version lookup failure'; Json = $draftJson; Fail = 'api'; Calls = 'view,upload,api'; Reject = $true },
            @{ Name = 'unrecognized stable tag'; Json = $draftJson; Published = @('stable'); Calls = 'view,upload,api'; Reject = $true },
            @{ Name = 'publish failure'; Json = $draftJson; Fail = 'edit'; Calls = 'view,upload,api,edit'; Reject = $true; Latest = 'true' },
            @{ Name = 'keep draft'; Json = $draftJson; Draft = $true; Calls = 'view,upload,edit'; Reject = $false },
            @{ Name = 'new prerelease'; Json = ''; Fail = 'view'; Prerelease = $true; Calls = 'view,create,upload,edit'; Reject = $false; Latest = 'false' },
            @{ Name = 'retry prerelease'; Json = $draftJson; Prerelease = $true; Calls = 'view,upload,edit'; Reject = $false; Latest = 'false' },
            @{ Name = 'prerelease draft'; Json = $draftJson; Draft = $true; Prerelease = $true; Calls = 'view,upload,edit'; Reject = $false }
        )) {
            $calls = New-Object 'System.Collections.Generic.List[string]'
            function gh {
                $command = if ($args[0] -eq 'api') { 'api' } else { $args[1] }
                if ($command -ne 'api') {
                    Assert-True ($args[0] -eq 'release' -and $args[2] -ceq 'v1.2.3') 'Unexpected release command'
                }
                $calls.Add($command)
                $global:LASTEXITCODE = if (@($case.Fail) -contains $command) { 1 } else { 0 }
                switch ($command) {
                    'view' { return $case.Json }
                    'create' {
                        Assert-True ($args -contains '--draft' -and $args -contains '--verify-tag') 'Release was not created as a verified draft'
                        Assert-True (($args -contains '--prerelease') -eq [bool]$case.Prerelease) 'New release lost its prerelease flag'
                    }
                    'upload' {
                        Assert-True ($args -contains '--clobber') 'Draft retry cannot replace incomplete assets'
                        foreach ($artifact in $artifacts) {
                            Assert-True ($args -contains $artifact) 'Release upload omitted an artifact'
                        }
                    }
                    'edit' {
                        $draftFlag = "--draft=$(([bool]$case.Draft).ToString().ToLowerInvariant())"
                        $prereleaseFlag = "--prerelease=$(([bool]$case.Prerelease).ToString().ToLowerInvariant())"
                        Assert-True ($args -contains $draftFlag -and $args -contains $prereleaseFlag) 'Release lost its draft/prerelease flags'
                        if ($case.Draft) {
                            Assert-True (-not ($args | Where-Object { $_ -like '--latest=*' })) 'Draft changed Latest'
                        }
                        else {
                            Assert-True ($args -contains "--latest=$($case.Latest)") 'Release changed Latest incorrectly'
                        }
                    }
                    'api' {
                        Assert-True ($args[1] -ceq 'repos/{owner}/{repo}/releases?per_page=100') 'Unexpected release endpoint'
                        Assert-True ($args -contains '--paginate') 'Version lookup missed older pages'
                        Assert-True ($args -contains '.[] | select(.draft == false and .prerelease == false) | .tag_name') 'Version comparison included unpublished versions'
                        if ($case.Published) { return $case.Published }
                    }
                    default { throw "Unexpected release command: $command" }
                }
            }
            $rejected = $false
            $errorMessage = ''
            try { Publish-ReleaseAssets -Tag 'v1.2.3' -Artifacts $artifacts -Draft:([bool]$case.Draft) -Prerelease:([bool]$case.Prerelease) }
            catch { $rejected = $true; $errorMessage = $_.Exception.Message }
            Assert-True ($rejected -eq $case.Reject) "Wrong release result: $($case.Name): $errorMessage"
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
    & {
        . (Get-ScriptFunctions '.github/scripts/release-assets.ps1')
        $artifacts = @((Join-Path $testDir 'retry-app.zip'), (Join-Path $testDir 'retry-SHA256SUMS.txt'))
        foreach ($artifact in $artifacts) { [System.IO.File]::WriteAllText($artifact, 'test artifact') }
        foreach ($operation in @('create', 'upload', 'api', 'edit')) {
            $state = @{ Exists = $false; Draft = $true; Pending = $true; Uploaded = 0 }
            function gh {
                $command = if ($args[0] -eq 'api') { 'api' } else { $args[1] }
                $global:LASTEXITCODE = 0
                if ($command -eq 'view') {
                    if (-not $state.Exists) { $global:LASTEXITCODE = 1; return }
                    return (@{ tagName = 'v1.2.3'; isDraft = $state.Draft } | ConvertTo-Json -Compress)
                }
                if ($state.Pending -and $command -eq $operation) {
                    $state.Pending = $false
                    $global:LASTEXITCODE = 1
                    return
                }
                switch ($command) {
                    'create' {
                        Assert-True ($args -contains '--draft') 'Retry exposed a partial public release'
                        $state.Exists = $true
                    }
                    'upload' {
                        Assert-True ($state.Exists -and $state.Draft -and $args -contains '--clobber') 'Retry changed published assets'
                        $state.Uploaded += 1
                    }
                    'api' { return 'v1.2.2' }
                    'edit' { $state.Draft = $false }
                    default { throw "Unexpected release retry command: $command" }
                }
            }
            $rejected = $false
            try { Publish-ReleaseAssets -Tag 'v1.2.3' -Artifacts $artifacts } catch { $rejected = $true }
            Assert-True ($rejected -and -not $state.Pending -and $state.Draft) "Interrupted $operation did not stop before publication"
            Assert-True ($ErrorActionPreference -eq 'Stop') 'Release lookup changed the caller error policy'
            Publish-ReleaseAssets -Tag 'v1.2.3' -Artifacts $artifacts
            Assert-True ($state.Exists -and -not $state.Draft -and $state.Uploaded -gt 0) "Retry after interrupted $operation did not complete publication"
            $uploads = $state.Uploaded
            $rejected = $false
            try { Publish-ReleaseAssets -Tag 'v1.2.3' -Artifacts $artifacts } catch { $rejected = $true }
            Assert-True ($rejected -and $state.Uploaded -eq $uploads) 'Completed release was modified by a retry'
        }
    }
    & {
        . (Get-ScriptFunctions '.github/scripts/release-assets.ps1')
        $artifacts = @((Join-Path $testDir 'native-app.zip'))
        [System.IO.File]::WriteAllText($artifacts[0], 'test artifact')
        $calls = New-Object 'System.Collections.Generic.List[string]'
        function gh {
            $command = if ($args[0] -eq 'api') { 'api' } else { $args[1] }
            $calls.Add($command)
            if ($command -eq 'view') {
                # Exercise real native stderr, including Windows PowerShell 5.1 behavior.
                & $env:COMSPEC /d /c 'echo release not found 1>&2 & exit /b 1'
                return
            }
            $global:LASTEXITCODE = 0
            if ($command -eq 'api') { return 'v1.2.2' }
        }
        Publish-ReleaseAssets -Tag 'v1.2.3' -Artifacts $artifacts
        Assert-True (($calls -join ',') -eq 'view,create,upload,api,edit') 'Native missing-release stderr aborted first-time publication'
        Assert-True ($ErrorActionPreference -eq 'Stop') 'Native release lookup changed the caller error policy'
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
