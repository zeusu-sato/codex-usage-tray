param([string] $OutputDirectory = (Join-Path (Split-Path $PSScriptRoot -Parent) 'build\windows'))
$ErrorActionPreference = 'Stop'
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
[void][System.IO.Directory]::CreateDirectory($OutputDirectory)
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '.NET Framework C# compiler was not found.' }
$iconPath = Join-Path $OutputDirectory 'CodexUsageTray.ico'
$exePath = Join-Path $OutputDirectory 'CodexUsageTray.exe'
Add-Type -AssemblyName System.Drawing
if (-not ('CodexUsageIconHandle' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CodexUsageIconHandle {
    [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr handle);
}
'@
}
$bitmap = [System.Drawing.Bitmap]::new(64, 64)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$background = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(28, 111, 85))
$font = [System.Drawing.Font]::new('Segoe UI', 38, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$format = [System.Drawing.StringFormat]::new()
$format.Alignment = [System.Drawing.StringAlignment]::Center
$format.LineAlignment = [System.Drawing.StringAlignment]::Center
$handle = [IntPtr]::Zero
$borrowedIcon = $null
$stream = $null
try {
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.Clear([System.Drawing.Color]::Transparent)
    $graphics.FillEllipse($background, 1, 1, 62, 62)
    $graphics.DrawString('C', $font, [System.Drawing.Brushes]::White, [System.Drawing.RectangleF]::new(0, -1, 64, 64), $format)
    $handle = $bitmap.GetHicon()
    $borrowedIcon = [System.Drawing.Icon]::FromHandle($handle)
    $stream = [System.IO.File]::Create($iconPath)
    $borrowedIcon.Save($stream)
} finally {
    if ($stream) { $stream.Dispose() }
    if ($borrowedIcon) { $borrowedIcon.Dispose() }
    if ($handle -ne [IntPtr]::Zero) { [void][CodexUsageIconHandle]::DestroyIcon($handle) }
    $format.Dispose(); $font.Dispose(); $background.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
}
& $compiler /nologo /target:winexe /optimize+ /codepage:65001 "/out:$exePath" "/win32icon:$iconPath" "/win32manifest:$(Join-Path $PSScriptRoot 'app.manifest')" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll (Join-Path $PSScriptRoot 'UsageToggle.cs') (Join-Path $PSScriptRoot 'UsageTrayHost.cs') (Join-Path $PSScriptRoot 'TraySymbols.cs')
if ($LASTEXITCODE -ne 0) { throw "C# build failed with exit code $LASTEXITCODE" }
Get-Item -LiteralPath $exePath, $iconPath | Select-Object FullName, Length
