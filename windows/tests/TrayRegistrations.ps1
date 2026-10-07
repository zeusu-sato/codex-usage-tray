# Windows 11 keeps one NotifyIconSettings entry per executable path and icon, even after the
# icon and its folder are gone. Each test run uses a fresh fixture folder (or hosts the form
# inside PowerShell), so without cleanup Settings > Taskbar fills with dead toggles.
function Remove-TestTrayRegistrations([string[]] $ExecutablePath = @()) {
    $key = 'HKCU:\Control Panel\NotifyIconSettings'
    if (-not (Test-Path -LiteralPath $key)) { return }
    $fixtures = @($ExecutablePath | Where-Object { $_ } | ForEach-Object { [System.IO.Path]::GetFullPath($_) })
    # Forms loaded in-process register under the host; only remove entries carrying this app's tooltip.
    $hostName = [System.IO.Path]::GetFileName([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)
    $removed = @()
    foreach ($entry in @(Get-ChildItem -LiteralPath $key)) {
        $values = Get-ItemProperty -LiteralPath $entry.PSPath
        $path = [string]$values.ExecutablePath
        if (-not $path) { continue }
        $fixture = $fixtures | Where-Object { [string]::Equals($_, $path, [System.StringComparison]::OrdinalIgnoreCase) }
        $hosted = [System.IO.Path]::GetFileName($path) -ieq $hostName -and
            [string]$values.InitialTooltip -match '^(Codex|Claude Code) Usage: '
        if ($fixture -or $hosted) {
            Remove-Item -LiteralPath $entry.PSPath -Recurse
            $removed += $entry.PSChildName
        }
    }
    if ($removed.Count -eq 0) { return }
    # Explorer writes icon snapshots back under the same IDs when the test host exits, so a
    # detached helper removes them again after this process is gone.
    $sweep = @"
`$ErrorActionPreference = 'SilentlyContinue'
Wait-Process -Id $PID -Timeout 600
`$watch = [Diagnostics.Stopwatch]::StartNew(); `$last = 0
while (`$watch.ElapsedMilliseconds - `$last -lt 5000 -and `$watch.ElapsedMilliseconds -lt 30000) {
    foreach (`$id in @('$($removed -join "','")')) {
        `$path = Join-Path '$key' `$id
        if (Test-Path -LiteralPath `$path) { Remove-Item -LiteralPath `$path -Recurse; `$last = `$watch.ElapsedMilliseconds }
    }
    Start-Sleep -Milliseconds 250
}
"@
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($sweep))
    Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -WindowStyle Hidden -ArgumentList '-NoProfile', '-EncodedCommand', $encoded
}
