param([Parameter(Mandatory = $true)][string] $InstallerPath, [string] $ZipPath = '')
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$installer = (Resolve-Path -LiteralPath $InstallerPath).Path
if ($ZipPath) { $ZipPath = (Resolve-Path -LiteralPath $ZipPath).Path }
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{76F70EFD-4C9D-472F-A3B9-577C640E8424}_is1'
if (Test-Path -LiteralPath $key) { throw 'Existing installation detected; refusing to run.' }
$fixture = Join-Path $root ('build\installer smoke ' + [guid]::NewGuid().ToString('N'))
$app = Join-Path $fixture 'installed app'
$data = Join-Path $fixture 'test data 日本語'
$profile = Join-Path $fixture 'profile'
$outside = Join-Path $fixture 'outside app'
$link = Join-Path ([Environment]::GetFolderPath('Startup')) 'CodexUsageTray-managed.lnk'
$testShortcut = -not (Test-Path -LiteralPath $link)
$backup = $null
if ($testShortcut -and (Test-Path -LiteralPath $link)) { $backup = [IO.File]::ReadAllBytes($link) }
[void][IO.Directory]::CreateDirectory($data)
[IO.File]::WriteAllText((Join-Path $data 'sentinel.txt'), 'keep')
function Start-Isolated([string] $File, [string] $Arguments) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $File
    $info.Arguments = $Arguments
    $info.UseShellExecute = $false
    $info.EnvironmentVariables['USERPROFILE'] = $profile
    $info.EnvironmentVariables['CODEX_HOME'] = Join-Path $profile '.codex'
    $info.EnvironmentVariables['CLAUDE_CONFIG_DIR'] = Join-Path $profile '.claude'
    $info.EnvironmentVariables['CODEX_USAGE_TRAY_UPDATE_CHECK'] = '0'
    $info.EnvironmentVariables['PATH'] = Join-Path $env:WINDIR 'System32'
    foreach ($name in @('ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','CLAUDE_CODE_OAUTH_TOKEN','CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR')) { $info.EnvironmentVariables.Remove($name) }
    return [Diagnostics.Process]::Start($info)
}
function Invoke-Setup([string] $Extra = '') {
    $process = Start-Isolated $installer "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$fixture\setup.log`" /DIR=`"$app`" /DATADIR=`"$data`" $Extra"
    if (-not $process.WaitForExit(120000)) { $process.Kill(); throw 'Installer timed out' }
    if ($process.ExitCode -ne 0) { throw "Installer failed: $($process.ExitCode)" }
}
function Get-AppProcesses([string] $Folder) {
    $prefix = [IO.Path]::GetFullPath($Folder).TrimEnd('\') + '\'
    @(Get-Process -Name CodexUsageTray,CodexUsageBackend -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -and $_.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) } catch { $false }
    })
}
function Wait-App {
    for ($i = 0; $i -lt 60; $i++) {
        $procs = @(Get-AppProcesses $app | Where-Object { $_.ProcessName -eq 'CodexUsageTray' })
        if ($procs.Count) { return $procs[0] }
        Start-Sleep -Milliseconds 500
    }
    throw 'Installed app did not start'
}
function Set-Shortcut([string] $Target, [string] $Description) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($link)
    $shortcut.TargetPath = $Target
    $shortcut.Description = $Description
    $shortcut.Save()
}
function Uninstall-App {
    $process = Start-Isolated (Join-Path $app 'unins000.exe') "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$fixture\uninstall.log`""
    if (-not $process.WaitForExit(120000)) { $process.Kill(); throw 'Uninstaller timed out' }
    if ($process.ExitCode -ne 0) { Get-Content -LiteralPath "$fixture\uninstall.log"; throw "Uninstaller failed: $($process.ExitCode)" }
    if (@(Get-AppProcesses $app).Count) { throw 'Installed app process survived uninstall' }
    if (Test-Path -LiteralPath $key) { throw 'Uninstall registry key remains' }
    if (-not (Test-Path -LiteralPath (Join-Path $data 'sentinel.txt'))) { throw 'Data deleted' }
}
try {
    Invoke-Setup
    if (-not (Test-Path -LiteralPath (Join-Path $app 'backend\CodexUsageBackend.exe')) -or -not (Test-Path -LiteralPath $key)) { throw 'Installation incomplete' }
    $first = Wait-App
    $cmdline = (Get-CimInstance Win32_Process -Filter "ProcessId=$($first.Id)").CommandLine
    if (-not $cmdline.Contains($data)) { throw 'App did not receive data directory' }
    Write-Output 'PASS: fresh installation, data directory, and HKCU registration.'
    Uninstall-App
    if ($ZipPath) {
        Expand-Archive -LiteralPath $ZipPath -DestinationPath (Join-Path $fixture 'zip')
        [void][IO.Directory]::CreateDirectory($app)
        Copy-Item -Path (Join-Path $fixture 'zip\CodexUsageTray\*') -Destination $app -Recurse
        $old = Start-Isolated (Join-Path $app 'CodexUsageTray.exe') "--tray --data-dir `"$data`""
        [void](Wait-App)
    } else {
        Invoke-Setup
        $old = Wait-App
        Write-Output 'SKIP: ZIP upgrade fixture not supplied.'
    }
    Copy-Item -LiteralPath $app -Destination $outside -Recurse
    $external = Start-Isolated (Join-Path $outside 'CodexUsageTray.exe') "--tray --data-dir `"$(Join-Path $fixture 'outside data')`""
    Start-Sleep -Seconds 2
    if ($external.HasExited) { throw 'Outside app did not stay running' }
    if ($testShortcut) { Set-Shortcut (Join-Path $app 'CodexUsageTray.exe') 'Codex Usage Tray managed startup' }
    [IO.File]::WriteAllText((Join-Path $app 'backend\obsolete-test.txt'), 'old')
    Invoke-Setup
    if (-not $old.WaitForExit(10000)) { throw 'Old app survived upgrade' }
    if ($external.HasExited) { throw 'Outside app was stopped' }
    if (Test-Path -LiteralPath (Join-Path $app 'backend\obsolete-test.txt')) { throw 'Old backend file remains' }
    [void](Wait-App)
    if (-not (Test-Path -LiteralPath (Join-Path $data 'sentinel.txt'))) { throw 'Data deleted on upgrade' }
    if ($testShortcut -and -not (Test-Path -LiteralPath $link)) { throw 'Upgrade removed startup shortcut' }
    Write-Output 'PASS: upgrade, external process, backend replacement, relaunch, and data preservation.'
    Uninstall-App
    if ($testShortcut) {
        if (Test-Path -LiteralPath $link) { throw 'Managed startup shortcut remains' }
        foreach ($case in @(@((Join-Path $outside 'CodexUsageTray.exe'), 'Codex Usage Tray managed startup'), @((Join-Path $app 'CodexUsageTray.exe'), 'different description'))) {
            Invoke-Setup '/NOLAUNCH=1'
            Set-Shortcut $case[0] $case[1]
            Uninstall-App
            if (-not (Test-Path -LiteralPath $link)) { throw 'Unrelated startup shortcut deleted' }
            Remove-Item -LiteralPath $link -Force
        }
        Write-Output 'PASS: startup shortcut upgrade and uninstall cases.'
    } else { Write-Output 'SKIP: existing startup shortcut belongs to the user.' }
    Write-Output 'PASS: uninstall and data preservation.'
} catch {
    Write-Output "Startup shortcut path: [$link]"
    if (Test-Path -LiteralPath "$fixture\uninstall.log") { Get-Content -LiteralPath "$fixture\uninstall.log" }
    Write-Output $_.ScriptStackTrace
    throw
} finally {
    foreach ($folder in @($app, $outside)) { Get-AppProcesses $folder | Stop-Process -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $key) {
        $uninstaller = Join-Path $app 'unins000.exe'
        if (Test-Path -LiteralPath $uninstaller) { $p = Start-Isolated $uninstaller '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'; [void]$p.WaitForExit(120000) }
    }
    if ($testShortcut) {
        if ($backup) { [IO.File]::WriteAllBytes($link, $backup) }
        elseif (Test-Path -LiteralPath $link) { Remove-Item -LiteralPath $link -Force }
    }
    if (Test-Path -LiteralPath $fixture) { Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue }
}
