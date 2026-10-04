param(
    [string]$Python = 'python',
    [string]$NodePath,
    [string]$OutputDirectory,
    [switch]$InstallBuildDependency
)
$ErrorActionPreference = 'Stop'
$patcherRoot = $PSScriptRoot
if (-not $NodePath) {
    $NodePath = (Get-Command node -ErrorAction Stop).Source
}
$NodePath = (Resolve-Path -LiteralPath $NodePath).Path
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $patcherRoot 'dist'
}
$nodeVersion = & $NodePath --version
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v(\d+)\.') {
    throw 'Unable to verify the Node runtime.'
}
if ([int]$Matches[1] -lt 20) {
    throw 'Node.js 20 or newer is required.'
}
if ($InstallBuildDependency) {
    & $Python -m pip install 'pyinstaller==6.20.0'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }
}
& $Python -c 'import tkinter, PyInstaller; print("Build dependencies ready")'
if ($LASTEXITCODE -ne 0) { throw 'Python with Tkinter and PyInstaller is required. Run with -InstallBuildDependency if needed.' }
$nodeLicense = Join-Path $patcherRoot 'resources\NODE-LICENSE.txt'
if (-not (Test-Path -LiteralPath $nodeLicense -PathType Leaf)) {
    throw 'Place the matching Node.js LICENSE at desktop-patcher/resources/NODE-LICENSE.txt before building.'
}
$previousNode = $env:GROK_SWITCH_NODE
try {
    $env:GROK_SWITCH_NODE = $NodePath
    & $Python -m PyInstaller --clean --noconfirm --distpath $OutputDirectory --workpath (Join-Path $patcherRoot 'build') (Join-Path $patcherRoot 'GrokSwitchPatcher.spec')
    if ($LASTEXITCODE -ne 0) { throw 'Portable EXE build failed.' }
} finally {
    $env:GROK_SWITCH_NODE = $previousNode
}
$builtExe = Join-Path $OutputDirectory 'GrokSwitchPatcher.exe'
Get-FileHash -LiteralPath $builtExe -Algorithm SHA256
Write-Output "Built portable application: $builtExe"
