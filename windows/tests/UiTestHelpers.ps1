function Write-Fixture([string] $directory, [hashtable] $values) {
    [void][System.IO.Directory]::CreateDirectory($directory)
    [System.IO.File]::WriteAllText((Join-Path $directory 'fixture.json'), ($values | ConvertTo-Json -Depth 8), [System.Text.UTF8Encoding]::new($false))
}
function Forecast-Fixture([string] $status) {
    return @{ status = $status; title = ('Fixture ' + $status); detail = 'Weekly: fixture average only; usage can change.'; window_label = 'Weekly'; observed_hours = 12; projected_remaining_percent = 50 }
}
function Wait-Task($task, [int] $milliseconds = 12000) {
    if (-not $task.Wait($milliseconds)) { throw 'UI operation did not finish' }
    if ($task.IsFaulted) { throw $task.Exception }
}
function Wait-Idle($window) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    do {
        Start-Sleep -Milliseconds 25
        $busy = [PublicUiTest]::BusyState($window)
    } while ($busy.Length -gt 0 -and $watch.ElapsedMilliseconds -lt 15000)
    if ($busy.Length -gt 0) { throw "Form remains busy: $busy" }
}
function Refresh-Quota($window) { Wait-Task ([PublicUiTest]::Call($window, 'CheckUsageAsync', @())) }
function Wait-Closed($window) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while (-not $window.IsDisposed -and $watch.ElapsedMilliseconds -lt 10000) { Start-Sleep -Milliseconds 20 }
    if (-not $window.IsDisposed) { throw 'Dialog did not close' }
}
function Wait-File([string] $path) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $path) -and $watch.ElapsedMilliseconds -lt 5000) { Start-Sleep -Milliseconds 20 }
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing fixture marker: $path" }
}
function Assert-Ended([int] $processId) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while ((Get-Process -Id $processId -ErrorAction SilentlyContinue) -and $watch.ElapsedMilliseconds -lt 3000) { Start-Sleep -Milliseconds 20 }
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) { throw "Fixture process remains: $processId" }
}
