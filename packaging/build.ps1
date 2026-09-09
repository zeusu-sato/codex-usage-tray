param(
    [string] $Python = 'python',
    [string] $Version = '0.2.0',
    [string] $OutputDirectory = '',
    [switch] $SkipDependencyInstall
)
$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
if ($Version -notmatch '^\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?$') { throw 'Invalid version' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $root 'dist' }
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$buildRoot = Join-Path $root ('build\package-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6))
[void][System.IO.Directory]::CreateDirectory($buildRoot)
[void][System.IO.Directory]::CreateDirectory($OutputDirectory)
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $root 'src'
    & $Python -X utf8 -m unittest discover -s (Join-Path $root 'tests') -q
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
    if (-not $SkipDependencyInstall) {
        & $Python -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements-build.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed' }
    }
    & $Python -m PyInstaller --noconfirm --onedir --console --name CodexUsageBackend --paths (Join-Path $root 'src') --distpath (Join-Path $buildRoot 'backend-dist') --workpath (Join-Path $buildRoot 'work') --specpath $buildRoot (Join-Path $root 'src\backend.py')
    if ($LASTEXITCODE -ne 0) { throw 'Backend packaging failed' }
    $package = Join-Path $buildRoot 'CodexUsageTray'
    [void][System.IO.Directory]::CreateDirectory($package)
    Copy-Item -LiteralPath (Join-Path $buildRoot 'backend-dist\CodexUsageBackend') -Destination (Join-Path $package 'backend') -Recurse
    & (Join-Path $root 'windows\build.ps1') -OutputDirectory $package
    Copy-Item -LiteralPath (Join-Path $root 'README.md'), (Join-Path $root 'README.ja.md'), (Join-Path $root 'LICENSE') -Destination $package
    [void][System.IO.Directory]::CreateDirectory((Join-Path $package 'docs'))
    foreach ($name in @('PRIVACY.md', 'RELEASE_NOTES.md')) {
        Copy-Item -LiteralPath (Join-Path $root "docs\$name") -Destination (Join-Path $package 'docs')
    }
    [void][System.IO.Directory]::CreateDirectory((Join-Path $package 'docs\images'))
    Copy-Item -LiteralPath (Join-Path $root 'docs\images\demo.png') -Destination (Join-Path $package 'docs\images')
    & $Python (Join-Path $PSScriptRoot 'collect_notices.py') (Join-Path $package 'licenses')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency notices missing' }
    $zip = Join-Path $OutputDirectory "CodexUsageTray-$Version-windows-x64.zip"
    if (Test-Path -LiteralPath $zip) { throw 'Output ZIP already exists; choose a new output directory.' }
    Compress-Archive -LiteralPath $package -DestinationPath $zip -CompressionLevel Optimal
    $hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    [System.IO.File]::WriteAllText((Join-Path $OutputDirectory 'SHA256SUMS.txt'), "$hash  $([System.IO.Path]::GetFileName($zip))`n", [System.Text.UTF8Encoding]::new($false))
    Write-Output "Package: $package"
    Get-Item -LiteralPath $zip | Select-Object Name, Length
    Write-Output "SHA256: $hash"
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
