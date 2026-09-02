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
        try { Assert-PortablePackage $package } catch { $rejected = $true }
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
        try { Assert-PortablePackage $package } catch { $rejected = $true }
        Assert-True $rejected 'A package without Python was accepted'
        [System.IO.File]::WriteAllText((Join-Path $package '_internal\python313.dll'), 'placeholder')
        # Released v0.1.1 lacks the later weather icon library but must remain installable.
        Assert-PortablePackage $package

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
        . (Get-ScriptFunctions 'publish_release.ps1')
        function Invoke-RequiredCommand { param($Command, $Arguments) }
        function Get-RequiredCommandOutput {
            param($Command, $Arguments)
            return @('v2.0.0-rc1', 'v1.2.10', 'v1.2.9')
        }
        Assert-True ((Get-NextPatchVersion) -eq 'v1.2.11') 'Prerelease tag broke patch version selection'
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
    Write-Output 'Installer and release safety checks passed.'
}
finally {
    $resolvedTestDir = [System.IO.Path]::GetFullPath($testDir)
    if (-not $resolvedTestDir.StartsWith("$tempRoot\WeatherReportTests-", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean an unexpected test directory: $resolvedTestDir"
    }
    Remove-Item -LiteralPath $resolvedTestDir -Recurse -Force
}
