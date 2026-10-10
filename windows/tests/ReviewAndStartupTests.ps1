    Wait-Task ([PublicUiTest]::Call($window, 'CheckReviewAsync', @($true)))
    $prompt = [PublicUiTest]::Field($window, 'reviewPrompt')
    if (-not $prompt -or $prompt.AcceptButton.Name -ne 'ReviewNo') { throw 'Manual review confirmation must default to No' }
    [PublicUiTest]::Screenshot($prompt, (Join-Path $testRoot 'review-confirmation.png'))
    [PublicUiTest]::Click($prompt.Controls['ReviewNo'])
    Wait-Closed $prompt
    Wait-Task ([PublicUiTest]::Call($window, 'CheckReviewAsync', @($true)))
    $prompt = [PublicUiTest]::Field($window, 'reviewPrompt')
    [PublicUiTest]::Escape($prompt)
    Wait-Closed $prompt
    Wait-Task ([PublicUiTest]::Call($window, 'CheckReviewAsync', @($true)))
    $prompt = [PublicUiTest]::Field($window, 'reviewPrompt')
    [PublicUiTest]::Click($prompt.Controls['ReviewYes'])
    Wait-Closed $prompt
    if ([PublicUiTest]::Requests.Count -ne 1 -or [PublicUiTest]::Attempts -ne 1) { throw 'Explicit Yes did not invoke exactly one runner spy' }
    $visibleStart = [PublicUiTest]::Call($window, 'CreateBackendStart', @([string[]]@('review-run', '--request', [PublicUiTest]::Requests[0]), $true))
    if ($visibleStart.FileName -ne $fixtureBackend -or -not $visibleStart.UseShellExecute -or $visibleStart.Arguments -match '\-X utf8' -or $visibleStart.Arguments -notmatch '\-\-data-dir') { throw 'Visible review does not use the packaged backend contract' }
    $scriptPath = Join-Path $testRoot 'development fixture.py'
    [System.IO.File]::WriteAllText($scriptPath, '# Argument-construction fixture only; never executed.')
    [PublicUiTest]::SetField($window, 'backend', $scriptPath)
    [PublicUiTest]::SetField($window, 'python', $fixtureBackend)
    $scriptStart = [PublicUiTest]::Call($window, 'CreateBackendStart', @([string[]]@('ui-status'), $false))
    if ($scriptStart.FileName -ne $fixtureBackend -or $scriptStart.Arguments -notmatch '^\-X utf8 ' -or $scriptStart.Arguments -notmatch '\-\-data-dir') { throw 'Development script contract changed' }
    [PublicUiTest]::SetField($window, 'backend', $fixtureBackend)
    [PublicUiTest]::SetField($window, 'python', $null)
    Write-Output 'PASS: No/Escape are non-AI choices; explicit Yes calls only a spy; packaged review-run uses a visible console.'

    Wait-Task ([PublicUiTest]::Call($window, 'OpenLatestReviewAsync', @()))
    if ([PublicUiTest]::Reports.Count -ne 1 -or -not [PublicUiTest]::Reports[0].StartsWith((Join-Path $data 'reviews'))) { throw 'Validated review result did not reach the document spy' }
    Write-Fixture $data @{ remaining = 98; outside_report = $true }
    Wait-Task ([PublicUiTest]::Call($window, 'OpenLatestReviewAsync', @()))
    if ([PublicUiTest]::Reports.Count -ne 1 -or -not $window.Controls['ReviewStatus'].Text.Contains('開けません')) { throw 'Report outside the data reviews directory was opened' }
    Write-Fixture $data @{ remaining = 98 }
    Write-Output 'PASS: review-result opening is user initiated and rejects files outside the app review directory.'

    $dataAlias = Join-Path $testRoot 'profile junction alias'
    [void](New-Item -ItemType Junction -Path $dataAlias -Target $data)
    $aliasWindow = [PublicUiTest]::Start([System.IO.Path]::GetFullPath($AssemblyPath), $fixtureBackend, $dataAlias)
    Wait-Idle $aliasWindow
    if ([PublicUiTest]::Field($aliasWindow, 'dataDirectory') -ne [PublicUiTest]::Field($window, 'dataDirectory')) { throw 'A data-directory alias retained a different identity' }
    Wait-Task ([PublicUiTest]::Call($aliasWindow, 'OpenLatestReviewAsync', @()))
    if ([PublicUiTest]::Reports.Count -ne 2 -or [PublicUiTest]::Reports[1] -ne [PublicUiTest]::Reports[0]) { throw 'A resolved report from an aliased data directory was rejected' }
    $reportAlias = Join-Path $dataAlias 'reviews\fixture\result.md'
    $resolvedReport = [PublicUiTest]::Call($aliasWindow, 'ValidateReportPath', @([string]$reportAlias))
    if ($resolvedReport -ne [PublicUiTest]::Reports[0]) { throw 'A report alias was not resolved to its real file' }
    $outside = Join-Path $testRoot 'outside review destination'
    [void][System.IO.Directory]::CreateDirectory($outside)
    [System.IO.File]::WriteAllText((Join-Path $outside 'escape.md'), 'Synthetic report outside the reviews directory.')
    $escapeAlias = Join-Path $data 'reviews\escape junction'
    [void](New-Item -ItemType Junction -Path $escapeAlias -Target $outside)
    $rejected = $false
    try { [void][PublicUiTest]::Call($aliasWindow, 'ValidateReportPath', @([string](Join-Path $escapeAlias 'escape.md'))) } catch { $rejected = $true }
    if (-not $rejected) { throw 'A junction escaped the canonical review directory' }
    [PublicUiTest]::Dispose($aliasWindow)
    Write-Output 'PASS: profile/report junction aliases resolve consistently, and a report junction escaping the real reviews directory is rejected.'

    # Supplementary Unicode is outside both the runner's ANSI code page and CP932.
    $startup = Join-Path $data ('fake Startup ' + [char]0xD83E + [char]0xDDEA)
    [PublicUiTest]::SetField($window, 'startupDirectory', $startup)
    if ([PublicUiTest]::Call($window, 'StartupEnabled', @())) { throw 'Startup must default off' }
    [void][PublicUiTest]::Call($window, 'SetStartupEnabled', @($true))
    if (-not [PublicUiTest]::Call($window, 'StartupEnabled', @())) { throw 'Startup choice was not saved' }
    [void][PublicUiTest]::Call($window, 'SetStartupEnabled', @($false))
    if (Test-Path -LiteralPath (Join-Path $startup 'CodexUsageTray-managed.lnk')) { throw 'Owned startup shortcut was not removed' }
    [System.IO.File]::WriteAllText((Join-Path $startup 'unrelated.txt'), 'keep')
    [void][PublicUiTest]::Call($window, 'SetStartupEnabled', @($false))
    if ((Get-Content -LiteralPath (Join-Path $startup 'unrelated.txt') -Raw) -ne 'keep') { throw 'Startup operation changed an unrelated file' }
    $unrelatedShortcut = Join-Path $startup 'CodexUsageTray-managed.lnk'
    [PublicUiTest]::UnownedShortcut([System.IO.Path]::GetFullPath($AssemblyPath), $unrelatedShortcut, (Join-Path $env:WINDIR 'notepad.exe'))
    $preserved = $false
    try { [void][PublicUiTest]::Call($window, 'SetStartupEnabled', @($false)) } catch { $preserved = $true }
    if (-not $preserved -or -not (Test-Path -LiteralPath $unrelatedShortcut)) { throw 'An unowned same-name shortcut was modified' }
    Write-Output 'PASS: Unicode startup save/read/removal is opt-in and preserves unowned shortcuts, including Japanese and supplementary-Unicode paths.'
    [PublicUiTest]::Dispose($window)
