param([string]$AssemblyPath=(Join-Path (Split-Path $PSScriptRoot -Parent) 'build\windows\CodexUsageTray.exe'))
$ErrorActionPreference='Stop'
$previousCapture=$env:CODEX_USAGE_CAPTURE_DEMO
try{
 $env:CODEX_USAGE_CAPTURE_DEMO='1'
 $output = & powershell.exe -NoProfile -STA -File (Join-Path $PSScriptRoot 'test-dual-ui.ps1') -AssemblyPath $AssemblyPath
 if($LASTEXITCODE -ne 0){throw 'Synthetic demo capture failed'}
}finally{$env:CODEX_USAGE_CAPTURE_DEMO=$previousCapture}
$artifactLine=$output | Where-Object {$_ -like 'Artifacts: *'} | Select-Object -Last 1
if(-not $artifactLine){throw 'Demo artifact directory missing'}
$artifacts=$artifactLine.Substring(11)
Add-Type -AssemblyName System.Drawing
$destination=Join-Path (Split-Path $PSScriptRoot -Parent) 'docs\images\demo.png'
$left=[Drawing.Bitmap]::FromFile((Join-Path $artifacts 'provider-0.png'))
$right=[Drawing.Bitmap]::FromFile((Join-Path $artifacts 'provider-1.png'))
$codex=[Drawing.Bitmap]::FromFile((Join-Path $artifacts 'codex-icon-32.png'))
$claude=[Drawing.Bitmap]::FromFile((Join-Path $artifacts 'claude-icon-32.png'))
$canvas=[Drawing.Bitmap]::new($left.Width+$right.Width+60,[Math]::Max($left.Height,$right.Height)+180)
$g=[Drawing.Graphics]::FromImage($canvas)
$title=[Drawing.Font]::new('Segoe UI',25,[Drawing.FontStyle]::Bold)
$label=[Drawing.Font]::new('Segoe UI',12)
$brush=[Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(32,41,48))
try{
 $g.Clear([Drawing.Color]::FromArgb(238,242,245))
 $g.TextRenderingHint=[Drawing.Text.TextRenderingHint]::AntiAliasGridFit
 $g.DrawString('Codex + Claude Usage',$title,$brush,20,14)
 $g.DrawString('v0.3.0  |  Demo / Synthetic data  |  No real accounts',$label,$brush,22,63)
 $g.DrawImageUnscaled($codex,22,103);$g.DrawString('Codex / GPT',$label,$brush,64,106)
 $g.DrawImageUnscaled($claude,258,103);$g.DrawString('Claude Code',$label,$brush,300,106)
 $g.DrawImageUnscaled($left,20,158);$g.DrawImageUnscaled($right,$left.Width+40,158)
 $canvas.Save($destination,[Drawing.Imaging.ImageFormat]::Png)
}finally{foreach($item in @($brush,$label,$title,$g,$canvas,$claude,$codex,$right,$left)){$item.Dispose()}}
Write-Output $destination
