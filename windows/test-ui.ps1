param([string] $AssemblyPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'build\windows\CodexUsageTray.exe'))
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
. (Join-Path $PSScriptRoot 'tests\TrayRegistrations.ps1')
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('credit-ui-tests-' + [Guid]::NewGuid().ToString('N'))
[void][System.IO.Directory]::CreateDirectory($testRoot)
$fixtureBackend = Join-Path $testRoot 'FixtureBackend.exe'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:exe /codepage:65001 "/out:$fixtureBackend" /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'tests\FixtureBackend.cs')
if ($LASTEXITCODE -ne 0) { throw 'Fixture backend compilation failed' }
. (Join-Path $PSScriptRoot 'tests\PublicUiTest.ps1')

. (Join-Path $PSScriptRoot 'tests\UiTestHelpers.ps1')

$window = $null
$aliasWindow = $null
$native = $null
$second = $null
$third = $null
try {
    $data = Join-Path $testRoot 'profile with spaces 日本語'
    Write-Fixture $data @{ remaining = 98 }
    $window = [PublicUiTest]::Start([System.IO.Path]::GetFullPath($AssemblyPath), $fixtureBackend, $data, 150)
    Wait-Idle $window
    if ($window.Text -ne 'Codex Usage Tray' -or $window.Controls['StatusTitle'].Text -ne '追加対策は未設定です' -or $window.Controls['UsageToggle'].Enabled) { throw "Public first-run state: $($window.Text); $($window.Controls['StatusTitle'].Text); $($window.Controls['StatusDetail'].Text)" }
    if (-not $window.Controls['ReviewWithAi'].Visible -or -not $window.Controls['ReviewWithAi'].Enabled) { throw 'Manual review must be available for a detected matching client' }
    if ([PublicUiTest]::Field($window, 'reviewPrompt')) { throw 'Matching baseline automatically asked for AI' }
    foreach ($percent in @(98, 21, 4, 0, 100)) {
        Write-Fixture $data @{ remaining = $percent }
        Refresh-Quota $window
        if ($window.Controls['UsageRemaining'].Text -ne "$percent%") { throw "Wrong quota at $percent%" }
        [PublicUiTest]::SaveIcon($window, (Join-Path $testRoot "icon-$percent.png"))
    }
    Write-Fixture $data @{ remaining = 98; stale = $true }
    Refresh-Quota $window
    if ($window.Controls['UsageRemaining'].Text -ne '?' -or -not $window.Controls['UsageDetail'].Text.Contains('前回')) { throw 'Stale quota displayed as current' }
    Write-Fixture $data @{ remaining = $null }
    Refresh-Quota $window
    if ($window.Controls['UsageRemaining'].Text -ne '?') { throw 'Unknown quota displayed as a number' }
    if ([PublicUiTest]::Field($window, 'usageTimer').Interval -ne 300000 -or [PublicUiTest]::Field($window, 'monitorTimer').Interval -ne 900000) { throw 'Polling intervals changed' }
    Write-Fixture $data @{ remaining = 98 }
    Refresh-Quota $window
    [PublicUiTest]::Screenshot($window, (Join-Path $testRoot 'public-first-run.png'))
    Write-Output 'PASS: packaged EXE backend, Unicode/space data path, unconfigured policy, manual review, quota states, and timers.'

    $gray = [System.Drawing.Color]::FromArgb(94, 106, 115).ToArgb()
    $red = [System.Drawing.Color]::FromArgb(174, 43, 39).ToArgb()
    if ($window.Controls['UsageRemaining'].ForeColor.ToArgb() -ne $gray) { throw 'Missing forecast must keep a fresh quota gray' }
    $forecastColors = @{ comfortable = [System.Drawing.Color]::FromArgb(28, 111, 85).ToArgb(); tight = [System.Drawing.Color]::FromArgb(157, 104, 0).ToArgb(); at_risk = $red; collecting = $gray; unavailable = $gray }
    foreach ($status in @('comfortable', 'tight', 'at_risk', 'collecting', 'unavailable')) {
        Write-Fixture $data @{ remaining = 98; forecast = (Forecast-Fixture $status) }
        Refresh-Quota $window
        if ($window.Controls['UsageRemaining'].Text -ne '98%' -or $window.Controls['UsageRemaining'].ForeColor.ToArgb() -ne $forecastColors[$status]) { throw "Forecast $status changed the actual value or used the wrong color" }
        if (-not $window.Controls['UsageForecast'].Text.Contains($status) -or -not $window.Controls['UsageForecast'].Text.Contains('Weekly') -or $window.Controls['UsageForecast'].ForeColor.ToArgb() -ne $forecastColors[$status]) { throw "Forecast $status lacks an accessible textual/window explanation" }
        if ([PublicUiTest]::IconBackground($window) -ne $forecastColors[$status]) { throw "Forecast $status did not color the tray icon" }
        [PublicUiTest]::SaveIcon($window, (Join-Path $testRoot "forecast-$status.png"))
    }
    $invalidForecasts = @('malformed', (Forecast-Fixture 'unknown_future_status'))
    $invalidProjection = Forecast-Fixture 'comfortable'
    $invalidProjection.projected_remaining_percent = 101
    $invalidForecasts += $invalidProjection
    foreach ($forecast in $invalidForecasts) {
        Write-Fixture $data @{ remaining = 98; forecast = $forecast }
        Refresh-Quota $window
        if ($window.Controls['UsageRemaining'].Text -ne '98%' -or [PublicUiTest]::IconBackground($window) -ne $gray) { throw 'Malformed forecast discarded a valid quota or implied a safe prediction' }
    }
    foreach ($override in @('stale', 'blocked', 'zero')) {
        $case = @{ remaining = 98; forecast = (Forecast-Fixture 'comfortable') }
        if ($override -eq 'zero') { $case.remaining = 0 } else { $case[$override] = $true }
        Write-Fixture $data $case
        Refresh-Quota $window
        $expectedValue = if ($override -eq 'zero') { '0%' } else { '?' }
        $expectedColor = if ($override -eq 'zero') { $red } else { $gray }
        if ($window.Controls['UsageRemaining'].Text -ne $expectedValue -or [PublicUiTest]::IconBackground($window) -ne $expectedColor -or $window.Controls['UsageForecast'].Text.Contains('comfortable')) { throw "Forecast failed the $override override" }
    }
    Write-Fixture $data @{ remaining = 4; forecast = (Forecast-Fixture 'comfortable') }
    Refresh-Quota $window
    if ($window.Controls['UsageRemaining'].ForeColor.ToArgb() -ne $forecastColors.comfortable) { throw 'Old remaining-percentage thresholds overrode the trend status' }
    Write-Fixture $data @{ remaining = 98 }
    Refresh-Quota $window
    Write-Output 'PASS: forecast colors preserve actual quota, name the window, handle missing/invalid history, and respect stale/blocked/zero overrides.'

    $purple = [Drawing.Color]::FromArgb(106, 76, 196).ToArgb()
    if ($forecastColors.Values -contains $purple) { throw 'Credit color equals a normal color' }
    foreach ($text in @('61k', '$688', '∞', '¤', '$1.2k')) {
        $credit = @{kind='codex_credits';tray_text=$text;amount_known=$true;title='Credit 利用中';summary='残り61,794クレジット'}
        Write-Fixture $data @{remaining=0;credit=$credit}
        Refresh-Quota $window
        if ($window.Controls['UsageRemaining'].Text -ne $credit.title -or [PublicUiTest]::IconBackground($window) -ne $purple -or $window.Controls['UsageRemaining'].ForeColor.ToArgb() -ne $purple) { throw 'Credit title/color missing' }
        if (-not $window.Controls['UsageDetail'].Text.StartsWith($credit.summary) -or -not ([string][PublicUiTest]::Field($window,'usageTooltip')).Contains($credit.title) -or $window.Controls['UsageForecast'].Text -ne 'Credit 利用中は見通しを表示しません。') { throw 'Credit explanation missing' }
    }
    Write-Output 'PASS: Credit title, summary, tooltip, forecast explanation, and distinct purple icon background.'
    $invalidCredits = @('bad', @{}, @{kind='unknown';tray_text='61k';amount_known=$true;title='Credit 利用中';summary='credit'})
    foreach ($badText in @('', '123456', 812, $null, "a`nb")) {
        $invalidCredits += @{kind='codex_credits';tray_text=$badText;amount_known=$true;title='Credit 利用中';summary='credit'}
    }
    $invalidCredits += @{kind='codex_credits';tray_text='61k';amount_known='true';title='Credit 利用中';summary='credit'}
    foreach ($field in @('kind', 'tray_text', 'amount_known', 'title', 'summary')) {
        $bad = @{kind='codex_credits';tray_text='61k';amount_known=$true;title='Credit 利用中';summary='credit'}
        $bad.Remove($field)
        $invalidCredits += $bad
    }
    foreach ($bad in $invalidCredits) {
        Write-Fixture $data @{remaining=0;credit=$bad}
        Refresh-Quota $window
        if ($window.Controls['UsageRemaining'].Text -ne '?' -or -not $window.Controls['UsageDetail'].Text.Contains('使用枠の応答を読み取れませんでした。')) { throw 'Malformed credit was accepted' }
    }
    Write-Fixture $data @{remaining=98;credit=$null}
    Refresh-Quota $window
    if ($window.Controls['UsageRemaining'].Text -ne '98%' -or [PublicUiTest]::IconBackground($window) -ne $gray) { throw 'Null credit changed normal quota display' }
    Write-Output 'PASS: malformed Credit rejected; null Credit restores normal percentage and color.'

    Write-Fixture $data @{ remaining = 98; configured = $true }
    Wait-Task ([PublicUiTest]::Call($window, 'RunCommandAsync', @('ui-status')))
    Wait-Idle $window
    $switch = $window.Controls['UsageToggle']
    if ($switch.GetType().Name -ne 'ToggleSwitch' -or $switch.AutoCheck -or $switch.AccessibilityObject.Role -ne [System.Windows.Forms.AccessibleRole]::CheckButton) { throw 'Toggle bar lost its confirmed-state checkbox semantics' }
    [PublicUiTest]::CaptureControl($switch, (Join-Path $testRoot 'switch-off.png'))
    if ([PublicUiTest]::Space($switch)) { throw 'Space visually committed ON before the backend reply' }
    Wait-Idle $window
    if (-not $switch.Checked -or $switch.Text -ne 'ON') { throw 'Space did not activate the confirmed toggle state' }
    [PublicUiTest]::CaptureControl($switch, (Join-Path $testRoot 'switch-on.png'))
    if (-not [PublicUiTest]::Space($switch)) { throw 'Space visually committed OFF before the backend reply' }
    Wait-Idle $window
    if ($switch.Checked -or $switch.Text -ne 'OFF') { throw 'Space did not deactivate the confirmed toggle state' }
    $switchCommands = @(Get-ChildItem -LiteralPath $data -Filter 'command-*.txt' | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw })
    if (@($switchCommands | Where-Object { $_ -eq 'ui-enable' }).Count -ne 1 -or @($switchCommands | Where-Object { $_ -eq 'ui-disable' }).Count -ne 1) { throw 'A keyboard toggle sent duplicate backend commands' }
    [PublicUiTest]::SetField($window, 'backend', (Join-Path $testRoot 'missing-fixture.exe'))
    Wait-Task ([PublicUiTest]::Call($window, 'RunCommandAsync', @('ui-status')))
    if ($switch.Enabled -or $switch.Text -ne '未確認') { throw 'An unknown state looked like confirmed OFF' }
    [PublicUiTest]::CaptureControl($switch, (Join-Path $testRoot 'switch-unknown.png'))
    [PublicUiTest]::SetField($window, 'backend', $fixtureBackend)
    Write-Fixture $data @{ remaining = 98 }
    Wait-Task ([PublicUiTest]::Call($window, 'RunCommandAsync', @('ui-status')))
    Write-Output 'PASS: rounded checkbox switch supports Space exactly once, exposes ON/OFF, and preserves unknown and pending states.'
    [PublicUiTest]::CheckDynamicSwitchPaint($window)
    Write-Output 'PASS: repeated long/short text updates preserve layout separation and repaint opaque switch corners.'

    . (Join-Path $PSScriptRoot 'tests\ReviewAndStartupTests.ps1')

    $data = Join-Path $testRoot 'ambiguous profile'
    Write-Fixture $data @{ remaining = $null; ambiguous = $true }
    $window = [PublicUiTest]::Start([System.IO.Path]::GetFullPath($AssemblyPath), $fixtureBackend, $data, 150)
    Wait-Idle $window
    $picker = [PublicUiTest]::Field($window, 'clientPicker')
    if (-not $picker) { throw "Ambiguous client picker missing: $($window.Controls['ReviewStatus'].Text); $($window.Controls['MonitorStatus'].Text)" }
    if ($picker.Controls['SelectCodexClient'].Enabled -or $picker.Controls['CodexClientChoices'].SelectedIndex -ne -1) { throw 'Ambiguous clients must require an explicit choice' }
    [PublicUiTest]::Screenshot($picker, (Join-Path $testRoot 'client-selection.png'))
    [PublicUiTest]::Select($picker.Controls['CodexClientChoices'], 1)
    [PublicUiTest]::Click($picker.Controls['SelectCodexClient'])
    Wait-Closed $picker
    $state = Get-Content -LiteralPath (Join-Path $data 'fixture-state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.selected_id -ne 'insiders sample' -or -not $window.Controls['ReviewWithAi'].Enabled) { throw 'Client choice was not persisted/refreshed' }
    if ([PublicUiTest]::Attempts -ne 1) { throw 'Client selection launched AI' }
    Write-Output 'PASS: ambiguous detection opens an offscreen nonmodal picker; explicit client ID survives spaces and refreshes status without AI.'

    Write-Fixture $data @{ remaining = 98; configured = $true; slow = $true }
    Wait-Task ([PublicUiTest]::Call($window, 'RunCommandAsync', @('ui-status')))
    $slowTask = [PublicUiTest]::Call($window, 'CheckUsageAsync', @())
    Wait-File (Join-Path $data 'parent.pid')
    Wait-File (Join-Path $data 'child.pid')
    $parentId = [int](Get-Content -LiteralPath (Join-Path $data 'parent.pid') -Raw)
    $childId = [int](Get-Content -LiteralPath (Join-Path $data 'child.pid') -Raw)
    $watch = [Diagnostics.Stopwatch]::StartNew()
    [PublicUiTest]::Click($window.Controls['UsageToggle'])
    while ($window.Controls['StatusTitle'].Text -ne '追加対策は有効です' -and $watch.ElapsedMilliseconds -lt 3000) { Start-Sleep -Milliseconds 20 }
    if ($window.Controls['StatusTitle'].Text -ne '追加対策は有効です' -or $slowTask.IsCompleted) { throw 'Slow quota request blocks the toggle' }
    [PublicUiTest]::Dispose($window)
    Assert-Ended $parentId
    Assert-Ended $childId
    Write-Output 'PASS: slow quota does not block toggles; disposal kills the fixture backend and its descendant.'

    $install = Join-Path $testRoot 'native package'
    [void][System.IO.Directory]::CreateDirectory((Join-Path $install 'backend'))
    Copy-Item -LiteralPath $AssemblyPath -Destination (Join-Path $install 'CodexUsageTray.exe')
    Copy-Item -LiteralPath $fixtureBackend -Destination (Join-Path $install 'backend\CodexUsageBackend.exe')
    $data = Join-Path $testRoot 'native profile'
    Write-Fixture $data @{ remaining = $null }
    $nativeDataAlias = Join-Path $testRoot 'native profile junction'
    [void](New-Item -ItemType Junction -Path $nativeDataAlias -Target $data)
    $nativeExe = Join-Path $install 'CodexUsageTray.exe'
    $native = Start-Process -FilePath $nativeExe -ArgumentList ('--tray --data-dir "' + $data + '"') -WindowStyle Hidden -PassThru
    $watch = [Diagnostics.Stopwatch]::StartNew()
    do { Start-Sleep -Milliseconds 50; $handle = [PublicUiTest]::Window($native.Id) } while ($handle -eq [IntPtr]::Zero -and $watch.ElapsedMilliseconds -lt 10000)
    if ($handle -eq [IntPtr]::Zero -or [PublicUiTest]::IsWindowVisible($handle)) { throw '--tray did not start hidden' }
    [PublicUiTest]::MoveOffscreen($handle)
    $second = Start-Process -FilePath $nativeExe -ArgumentList ('--data-dir "' + $nativeDataAlias + '"') -WindowStyle Hidden -PassThru
    if (-not $second.WaitForExit(5000)) { throw 'Second instance remained running' }
    $watch.Restart()
    do {
        Start-Sleep -Milliseconds 20
        $handle = [PublicUiTest]::Window($native.Id)
    } while (($handle -eq [IntPtr]::Zero -or -not [PublicUiTest]::IsWindowVisible($handle)) -and $watch.ElapsedMilliseconds -lt 5000)
    if (-not [PublicUiTest]::IsWindowVisible($handle)) { throw 'First normal handoff did not restore the hidden native window' }
    [PublicUiTest]::Hide($handle)
    $third = Start-Process -FilePath $nativeExe -ArgumentList ('--tray --data-dir "' + $nativeDataAlias + '"') -WindowStyle Hidden -PassThru
    if (-not $third.WaitForExit(5000) -or [PublicUiTest]::IsWindowVisible($handle)) { throw 'Duplicate --tray should exit without showing the resident' }
    Write-Output 'PASS: a real packaged-style --tray process starts hidden; normal and --tray instances using a junction alias hand off to the same resident.'
} finally {
    if ($window -and -not $window.IsDisposed) { [PublicUiTest]::Dispose($window) }
    if ($aliasWindow -and -not $aliasWindow.IsDisposed) { [PublicUiTest]::Dispose($aliasWindow) }
    foreach ($process in @($native, $second, $third)) {
        if ($process -and -not $process.HasExited) {
            if ($process.MainModule.FileName -ne $nativeExe) { throw 'Refusing to stop a non-fixture process' }
            Stop-Process -Id $process.Id
        }
    }
    Remove-TestTrayRegistrations @($nativeExe)
}
Write-Output "Artifacts: $testRoot"
