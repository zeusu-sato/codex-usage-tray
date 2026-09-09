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
[System.IO.File]::WriteAllText((Join-Path $extensions 'extensions.json'), '[{"identifier":{"id":"openai.chatgpt"},"version":"fixture","relativeLocation":"openai.chatgpt-fixture"}]')
$capture = Join-Path $fixture 'metadata-methods.txt'
function Invoke-FixtureBackend([string] $Command, [bool] $FailRead = $false) {
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $backend
    $info.Arguments = "--data-dir `"$data`" $Command"
    $info.WorkingDirectory = $package
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $info.EnvironmentVariables['USERPROFILE'] = $profile
    $info.EnvironmentVariables['CODEX_HOME'] = Join-Path $profile '.codex'
    $info.EnvironmentVariables['PATH'] = Join-Path $env:WINDIR 'System32'
    $info.EnvironmentVariables['TRAY_FIXTURE_CAPTURE'] = $capture
    $info.EnvironmentVariables['TRAY_FIXTURE_FAIL'] = $(if ($FailRead) { '1' } else { '0' })
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
$cached = Get-Content -LiteralPath (Join-Path $data 'quota-state.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$cached.attempted_at = [DateTime]::UtcNow.AddMinutes(-1).ToString('o')
[System.IO.File]::WriteAllText((Join-Path $data 'quota-state.json'), ($cached | ConvertTo-Json -Depth 10), [System.Text.UTF8Encoding]::new($false))
$stale = Invoke-FixtureBackend 'usage-check' $true
if ($stale.ok -or -not $stale.stale -or $null -ne $stale.remaining_percent -or $stale.windows[0].remaining_percent -ne 74) { throw 'Failed refresh must show previous data as stale' }
$methods = @(Get-Content -LiteralPath $capture)
if (($methods -join ',') -ne 'initialize,initialized,account/rateLimits/read,initialize,initialized,account/rateLimits/read') { throw 'Unexpected metadata methods' }
if ((Get-Content -LiteralPath (Join-Path $data 'quota-state.json') -Raw) -match 'fixture secret') { throw 'Raw server error leaked' }
if (Test-Path -LiteralPath (Join-Path $profile '.codex\AGENTS.md')) { throw 'Monitoring wrote global policy' }
$components = Get-Content -LiteralPath (Join-Path $package 'licenses\components.json') -Raw | ConvertFrom-Json
if (-not ($components | Where-Object name -eq 'CPython')) { throw 'Missing runtime attribution' }
Write-Output 'PASS: frozen package in a Unicode/spaced path, no Python on PATH, isolated fake Codex metadata, first observation, no automatic policy, stale failure and cleanup. No account or AI used.'
