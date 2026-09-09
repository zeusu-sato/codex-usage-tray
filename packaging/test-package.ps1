param([Parameter(Mandatory = $true)][string] $ZipPath)
$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$fixture = Join-Path $root ('build\portable smoke 日本語 ' + [guid]::NewGuid().ToString('N').Substring(0, 8))
[void][System.IO.Directory]::CreateDirectory($fixture)
Expand-Archive -LiteralPath $ZipPath -DestinationPath $fixture
$package = Join-Path $fixture 'CodexUsageTray'
$backend = Join-Path $package 'backend\CodexUsageBackend.exe'
$profile = Join-Path $fixture 'fixture profile'
$data = Join-Path $fixture 'app data'
$extensions = Join-Path $profile '.vscode\extensions'
$binaryFolder = Join-Path $extensions 'openai.chatgpt-fixture\bin\windows-x86_64'
[void][System.IO.Directory]::CreateDirectory($binaryFolder)
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:exe /reference:System.Web.Extensions.dll "/out:$(Join-Path $binaryFolder 'codex.exe')" (Join-Path $root 'windows\tests\FixtureCodex.cs')
if ($LASTEXITCODE -ne 0) { throw 'Fake metadata server compilation failed' }
$claudeBinaryFolder = Join-Path $extensions 'anthropic.claude-code-fixture\resources\native-binary'
[void][System.IO.Directory]::CreateDirectory($claudeBinaryFolder)
& $compiler /nologo /target:exe /reference:System.Web.Extensions.dll "/out:$(Join-Path $claudeBinaryFolder 'claude.exe')" (Join-Path $root 'windows\tests\FixtureClaude.cs')
if ($LASTEXITCODE -ne 0) { throw 'Fake Claude metadata server compilation failed' }
function Write-FixtureIndex([string] $ClaudeVersion = '2.1.263') {
    $entries = @(
        @{ identifier = @{ id = 'openai.chatgpt' }; version = 'fixture'; relativeLocation = 'openai.chatgpt-fixture' },
        @{ identifier = @{ id = 'anthropic.claude-code' }; version = $ClaudeVersion; relativeLocation = 'anthropic.claude-code-fixture' }
    )
    [System.IO.File]::WriteAllText((Join-Path $extensions 'extensions.json'), ($entries | ConvertTo-Json -Depth 4), [System.Text.UTF8Encoding]::new($false))
}
Write-FixtureIndex
$capture = Join-Path $fixture 'metadata-methods.txt'
$claudeCapture = Join-Path $fixture 'claude-metadata-methods.txt'
$claudeLaunches = Join-Path $fixture 'claude-launches.txt'
function Invoke-FixtureBackend([string] $Command, [bool] $FailRead = $false, [string] $Provider = 'codex',
                               [string] $ClaudeVersion = '2.1.263', [bool] $NullClaudeReset = $false) {
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $backend
    $info.Arguments = "--data-dir `"$data`" --provider $Provider $Command"
    $info.WorkingDirectory = $package
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $info.EnvironmentVariables['USERPROFILE'] = $profile
    $info.EnvironmentVariables['CODEX_HOME'] = Join-Path $profile '.codex'
    $info.EnvironmentVariables['CLAUDE_CONFIG_DIR'] = Join-Path $profile '.claude'
    foreach ($name in @('ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','CLAUDE_CODE_OAUTH_TOKEN','CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR')) {
        $info.EnvironmentVariables.Remove($name)
    }
    $info.EnvironmentVariables['PATH'] = Join-Path $env:WINDIR 'System32'
    $info.EnvironmentVariables['TRAY_FIXTURE_CAPTURE'] = $capture
    $info.EnvironmentVariables['TRAY_FIXTURE_FAIL'] = $(if ($FailRead) { '1' } else { '0' })
    $info.EnvironmentVariables['TRAY_CLAUDE_FIXTURE_CAPTURE'] = $claudeCapture
    $info.EnvironmentVariables['TRAY_CLAUDE_FIXTURE_LAUNCHES'] = $claudeLaunches
    $info.EnvironmentVariables['TRAY_CLAUDE_FIXTURE_VERSION'] = $ClaudeVersion
    $info.EnvironmentVariables['TRAY_CLAUDE_FIXTURE_NULL_RESET'] = $(if ($NullClaudeReset) { '1' } else { '0' })
    $process = [System.Diagnostics.Process]::Start($info)
    try {
        $output = $process.StandardOutput.ReadToEndAsync()
        $errors = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(30000)) { $process.Kill(); throw 'Frozen backend timed out' }
        if ($process.ExitCode -ne 0) { throw 'Frozen backend failed' }
        if ($errors.Result) { throw 'Unexpected frozen backend stderr' }
        return ($output.Result | ConvertFrom-Json)
    } finally { $process.Dispose() }
}
$baseline = Invoke-FixtureBackend 'monitor-check'
if (-not $baseline.ok -or $baseline.mismatch -or $baseline.baseline_label -notlike '*監視開始時*') { throw 'Invalid first observation' }
$ui = Invoke-FixtureBackend 'ui-status'
if (-not $ui.ok -or $ui.enabled -or $ui.can_enable) { throw 'First run must have no policy' }
$quota = Invoke-FixtureBackend 'usage-check'
if (-not $quota.ok -or $quota.remaining_percent -ne 74) { throw 'Frozen metadata transport failed' }
if ($quota.forecast.status -ne 'collecting') { throw 'First reading must wait for trend history' }
$cached = Get-Content -LiteralPath (Join-Path $data 'quota-state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (@($cached.history).Count -ne 1 -or @($cached.history[0].samples).Count -ne 1 -or $cached.history[0].samples[0][1] -ne 74) { throw 'Frozen forecast history missing or incorrect' }
$cached.attempted_at = [DateTime]::UtcNow.AddMinutes(-1).ToString('o')
[System.IO.File]::WriteAllText((Join-Path $data 'quota-state.json'), ($cached | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))
$stale = Invoke-FixtureBackend 'usage-check' $true
if ($stale.ok -or -not $stale.stale -or $null -ne $stale.remaining_percent -or $stale.windows[0].remaining_percent -ne 74) { throw 'Failed refresh must show previous data as stale' }
if ($stale.forecast.status -ne 'unavailable') { throw 'Stale readings must not retain a positive forecast' }
$methods = @(Get-Content -LiteralPath $capture)
if (($methods -join ',') -ne 'initialize,initialized,account/rateLimits/read,initialize,initialized,account/rateLimits/read') { throw 'Unexpected metadata methods' }
if ((Get-Content -LiteralPath (Join-Path $data 'quota-state.json') -Raw) -match 'fixture secret') { throw 'Raw server error leaked' }
if (Test-Path -LiteralPath (Join-Path $profile '.codex\AGENTS.md')) { throw 'Monitoring wrote global policy' }
$codexStateHash = (Get-FileHash -LiteralPath (Join-Path $data 'quota-state.json') -Algorithm SHA256).Hash
$claudeBaseline = Invoke-FixtureBackend -Command 'monitor-check' -Provider 'claude'
if (-not $claudeBaseline.ok -or $claudeBaseline.mismatch -or $claudeBaseline.current_label -notlike '*Claude Code*2.1.263*') { throw 'Invalid first Claude observation' }
$claudeUi = Invoke-FixtureBackend -Command 'ui-status' -Provider 'claude'
if (-not $claudeUi.ok -or $claudeUi.enabled -or $claudeUi.can_enable) { throw 'Claude first run must have no policy' }
$claudeQuota = Invoke-FixtureBackend -Command 'usage-check' -Provider 'claude'
if (-not $claudeQuota.ok -or $claudeQuota.remaining_percent -ne 73 -or @($claudeQuota.windows).Count -ne 2) { throw 'Frozen Claude global metadata transport failed' }
if ($claudeQuota.forecast.status -ne 'collecting') { throw 'Claude first reading must wait for history' }
$claudeState = Join-Path $data 'providers\claude\quota-state.json'
$claudeCached = Get-Content -LiteralPath $claudeState -Raw -Encoding UTF8 | ConvertFrom-Json
if ($claudeCached.account_scope -notmatch '^[a-f0-9]{64}$' -or $claudeCached.scope_salt -notmatch '^[a-f0-9]{64}$' -or
    @($claudeCached.history).Count -ne 2 -or @($claudeCached.history[0].samples).Count -ne 1) { throw 'Frozen Claude pseudonymous history missing' }
$originalScope = $claudeCached.account_scope
$originalSalt = $claudeCached.scope_salt
$claudeCached.attempted_at = [DateTime]::UtcNow.AddMinutes(-1).ToString('o')
[System.IO.File]::WriteAllText($claudeState, ($claudeCached | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))
$claudeStale = Invoke-FixtureBackend -Command 'usage-check' -Provider 'claude' -FailRead $true
if ($claudeStale.ok -or -not $claudeStale.stale -or $null -ne $claudeStale.remaining_percent -or
    $claudeStale.windows[1].remaining_percent -ne 73 -or $claudeStale.forecast.status -ne 'unavailable') { throw 'Failed Claude refresh must show previous data as stale' }
$claudeCached = Get-Content -LiteralPath $claudeState -Raw -Encoding UTF8 | ConvertFrom-Json
$claudeCached.attempted_at = [DateTime]::UtcNow.AddMinutes(-1).ToString('o')
[System.IO.File]::WriteAllText($claudeState, ($claudeCached | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))
$claudeNull = Invoke-FixtureBackend -Command 'usage-check' -Provider 'claude' -NullClaudeReset $true
$claudeCached = Get-Content -LiteralPath $claudeState -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $claudeNull.ok -or $claudeNull.remaining_percent -ne 73 -or $claudeNull.forecast.status -eq 'comfortable' -or
    $null -ne $claudeCached.snapshot.windows[0].resets_at) { throw 'Null Claude reset must retain quota without a positive forecast' }
if ($claudeCached.account_scope -ne $originalScope -or $claudeCached.scope_salt -ne $originalSalt) { throw 'Claude account scope changed without an account change' }
$rawClaude = Get-Content -LiteralPath $claudeState -Raw -Encoding UTF8
foreach ($privateValue in @('fixture-private-account@example.invalid','Fixture Private Organization','Fixture Private Name',
                          'fixture-private-behavior','fixture-error-secret-must-not-escape')) {
    if ($rawClaude.Contains($privateValue)) { throw 'Raw Claude fixture metadata leaked into cache' }
}
$claudeMethods = @(Get-Content -LiteralPath $claudeCapture)
if (($claudeMethods -join ',') -ne 'initialize,get_usage,initialize,get_usage,initialize,get_usage') { throw 'Unexpected Claude control messages' }
$launchCount = @(Get-Content -LiteralPath $claudeLaunches).Count
Write-FixtureIndex '2.1.999'
$unsupported = Invoke-FixtureBackend -Command 'usage-check' -Provider 'claude' -ClaudeVersion '2.1.999'
$afterLaunches = @(Get-Content -LiteralPath $claudeLaunches)
if ($unsupported.ok -or $null -ne $unsupported.remaining_percent -or $unsupported.detail -notlike '*停止*') { throw 'Unsupported Claude version was not explained as unavailable' }
if ($afterLaunches.Count -ne $launchCount + 1 -or $afterLaunches[-1] -ne 'version' -or
    ((Get-Content -LiteralPath $claudeCapture) -join ',') -ne ($claudeMethods -join ',')) { throw 'Unsupported Claude version started a metadata process' }
if ((Get-FileHash -LiteralPath (Join-Path $data 'quota-state.json') -Algorithm SHA256).Hash -ne $codexStateHash) { throw 'Claude checks changed Codex state' }
if (Test-Path -LiteralPath (Join-Path $profile '.claude\CLAUDE.md')) { throw 'Claude monitoring wrote global policy' }
$components = Get-Content -LiteralPath (Join-Path $package 'licenses\components.json') -Raw | ConvertFrom-Json
if (-not ($components | Where-Object name -eq 'CPython')) { throw 'Missing runtime attribution' }
$provenance = Get-Content -LiteralPath (Join-Path $package 'licenses\native-runtime-provenance.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($provenance.python_version -ne '3.13.15' -or $provenance.openssl_version -ne '3.0.21' -or
    -not ($components | Where-Object { $_.name -eq 'OpenSSL' -and $_.version -eq '3.0.21' })) { throw 'Unreviewed native runtime attribution' }
foreach ($entry in $provenance.licenses) {
    $licensePath = Join-Path $package ('licenses\' + $entry.file)
    if ((Get-FileHash -LiteralPath $licensePath -Algorithm SHA256).Hash -ne $entry.sha256) { throw 'Native license hash differs' }
    if ($entry.notice_file) {
        $noticePath = Join-Path $package ('licenses\' + $entry.notice_file)
        if ((Get-FileHash -LiteralPath $noticePath -Algorithm SHA256).Hash -ne $entry.notice_sha256) { throw 'Native attribution hash differs' }
    }
}
foreach ($entry in $provenance.bundled_native_files.PSObject.Properties) {
    $binaryPath = Join-Path $package ('backend\_internal\' + $entry.Name)
    if ((Get-FileHash -LiteralPath $binaryPath -Algorithm SHA256).Hash -ne $entry.Value.sha256) { throw 'Packaged native binary hash differs from its provenance' }
}
Write-Output 'PASS: frozen package in a Unicode/spaced path, no Python on PATH, isolated Codex/Claude metadata, pseudonymous Claude history, null resets, stale suppression, unsupported-version metadata refusal, no automatic policy, and verified native license/runtime hashes. No account or AI used.'
