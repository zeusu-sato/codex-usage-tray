param([string]$AssemblyPath=(Join-Path (Split-Path $PSScriptRoot -Parent) 'build\windows\CodexUsageTray.exe'))
$ErrorActionPreference='Stop'
$env:CODEX_USAGE_TRAY_UPDATE_CHECK='0'
$CaptureDemo=$env:CODEX_USAGE_CAPTURE_DEMO -eq '1'
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
. (Join-Path $PSScriptRoot 'tests\TrayRegistrations.ps1')
$root = Join-Path ([IO.Path]::GetTempPath()) ('credit-dual-ui-' + [Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory((Join-Path $root 'providers\claude'))
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$fixture=Join-Path $root 'FixtureBackend.exe'
& $compiler /nologo /target:exe /codepage:65001 "/out:$fixture" /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'tests\FixtureBackend.cs')
if($LASTEXITCODE -ne 0){throw 'Fixture compilation failed'}
$encoding=[Text.UTF8Encoding]::new($false)
$forecast=@{status='comfortable';title='余裕があります';detail='テスト用の予測です';window_label='Weekly';observed_hours=12;projected_remaining_percent=50}
[IO.File]::WriteAllText((Join-Path $root 'fixture.json'),(@{remaining=68;configured=(-not $CaptureDemo);forecast=$forecast}|ConvertTo-Json -Depth 5),$encoding)
$forecast.status='tight';$forecast.title='ペースに注意'
[IO.File]::WriteAllText((Join-Path $root 'providers\claude\fixture.json'),(@{remaining=24;configured=(-not $CaptureDemo);forecast=$forecast}|ConvertTo-Json -Depth 5),$encoding)
Add-Type -ReferencedAssemblies System.Windows.Forms,System.Drawing -Path (Join-Path $PSScriptRoot 'tests\DualUiTest.cs'),(Join-Path $PSScriptRoot 'tests\DualUiTest.Capture.cs')
function Wait-DualIdle($session) {
    $watch=[Diagnostics.Stopwatch]::StartNew()
    do {
        Start-Sleep -Milliseconds 25
        $busy=[DualUiTest]::BusyState($session)
    } while ($busy.Length -gt 0 -and $watch.ElapsedMilliseconds -lt 20000)
    if ($busy.Length -gt 0) { throw "UI remains busy: $busy" }
}
$session=$null
try{
 $session=[DualUiTest]::Start([IO.Path]::GetFullPath($AssemblyPath),$fixture,$root)
 Wait-DualIdle $session
 [DualUiTest]::VerifyInitial($session)
 [DualUiTest]::VerifyUpdateOnOpen($session)
 if(-not $CaptureDemo){
 $task=[DualUiTest]::EnableClaude($session)
 if(-not $task.Wait(12000)){throw 'Toggle operation timed out'}
 $null=$task.GetAwaiter().GetResult()
 Wait-DualIdle $session
 [DualUiTest]::VerifyToggle($session)
 }
 foreach($index in 1,0){
     [DualUiTest]::OpenProvider($session,$index)
     Wait-DualIdle $session
     [DualUiTest]::Capture($session,$root,$index)
 }
 [DualUiTest]::CapturePreviews($session,$root)
 [DualUiTest]::CaptureCreditPreviews($session,(Join-Path $env:USERPROFILE 'credit-icon-samples\windows'))
 Write-Output 'PASS: eight Credit glyphs fit the padded 32px area, track has no fill, and 32/16px samples contain visible text.'
 foreach($index in 0,1){
     $title=if($index -eq 0){'Credit 利用中'}else{'追加利用中'}
     $summary=if($index -eq 0){'残り61,794クレジット'}else{'追加利用：今月の上限まで残り $688.00（使用 $0.00）'}
     $path=if($index -eq 0){Join-Path $root 'fixture.json'}else{Join-Path $root 'providers\claude\fixture.json'}
     foreach($text in $(if($index -eq 0){@('61k')}else{@('688','∞','¤')})){
         $credit=@{kind=$(if($index -eq 0){'codex_credits'}else{'claude_extra_usage'});tray_text=$text;amount_known=($text -ne '¤');title=$title;summary=$summary}
         [IO.File]::WriteAllText($path,(@{remaining=0;credit=$credit}|ConvertTo-Json -Depth 5),$encoding)
         $task=[DualUiTest]::RefreshCredit($session,$index)
         if(-not $task.Wait(12000)){throw 'Credit refresh timed out'}
         $null=$task.GetAwaiter().GetResult()
         [DualUiTest]::VerifyCredit($session,$index,$title,$summary)
         [DualUiTest]::OpenProvider($session,$index)
         [DualUiTest]::Capture($session,$root,$index)
     }
 }
 Write-Output 'PASS: dual-provider Credit modes (61k/688/∞/¤), titles, summaries, tooltips, and purple tray backgrounds.'

}finally{if($session){[DualUiTest]::Stop($session)};Remove-TestTrayRegistrations}
$commands=Get-ChildItem -LiteralPath $root -Filter 'command-*.txt' -Recurse | ForEach-Object {Get-Content -LiteralPath $_.FullName}
if($commands -contains 'review-run' -or $commands -contains 'review-decide'){throw 'Unexpected AI-related action'}
if($CaptureDemo){Write-Output 'PASS: synthetic dual-provider demo, no configured policies, no inference launch.'}
else{Write-Output 'PASS: isolated provider views, percentages/colors/toggles, tray-to-tab navigation, foreground digits at 32/16px (68/24/100/?), no inference launch, and completed STA cleanup.'}
Write-Output "Artifacts: $root"
