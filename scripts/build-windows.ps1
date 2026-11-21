# Reproducible dependency-bundled build; run on Windows 11 x64 with Python and Node only on BUILD HOST.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
# Native commands: Windows PowerShell 5.1 turns any stderr text (pip and npm notices) into a terminating error under
# $ErrorActionPreference = 'Stop', even when the command succeeded. So each native call relaxes the preference only around
# that one call, shows its output, and then the exit code decides. Nothing else in the script is relaxed.
function Invoke-Native([string]$What, [string]$Exe, [string[]]$Arguments) {
  $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try { & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }; $code = $LASTEXITCODE } finally { $ErrorActionPreference = $old }
  if ($code -ne 0) { throw "$What failed (exit code $code)" }
}
# Same, but returns stdout lines and reports failure as $null so a probe can try the next candidate.
function Get-NativeOutput([string]$Exe, [string[]]$Arguments) {
  $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try {
    $all = @(& $Exe @Arguments 2>&1); $code = $LASTEXITCODE
    if ($code -ne 0) { return $null }
    return @($all | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } | ForEach-Object { "$_" })
  } catch { return $null } finally { $ErrorActionPreference = $old }
}
# Build Python: set HMR_PYTHON to a python.exe to choose one, otherwise the py launcher, then python3.12 or python on PATH.
# The build needs Python 3.12; any other version stops here with the reason instead of failing later.
function Find-BuildPython {
  $candidates = @()
  if ($env:HMR_PYTHON) { $candidates += ,@($env:HMR_PYTHON) }
  else {
    if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += ,@('py', '-3.12') }
    foreach ($name in @('python3.12', 'python')) { if (Get-Command $name -ErrorAction SilentlyContinue) { $candidates += ,@($name) } }
  }
  foreach ($candidate in $candidates) {
    $exe = $candidate[0]; $extra = @($candidate | Select-Object -Skip 1)
    # The probe code has no double quotes: Windows PowerShell 5.1 drops embedded quotes when it passes arguments to a native command.
    $lines = Get-NativeOutput $exe (@($extra) + @('-c', 'import sys; print(sys.version_info[0], sys.version_info[1])'))
    if ($lines -and (($lines | Select-Object -Last 1) -eq '3 12')) { return ,$candidate }
  }
  throw 'Python 3.12 was not found. Install it, or set the HMR_PYTHON environment variable to the full path of a Python 3.12 python.exe.'
}
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
  $found = Find-BuildPython
  $exe = $found[0]; $extra = @($found | Select-Object -Skip 1)
  Invoke-Native 'Creating the build virtual environment' $exe (@($extra) + @('-m', 'venv', (Join-Path $root '.venv')))
  if (-not (Test-Path $venvPython)) { throw 'Creating the build virtual environment failed' }
}
# Optional licensed portal generators are not in the repository. A missing one is reported here and the build continues:
# the packaged app then says so in the eMIMS and claims views, and the manual workflow stays available.
foreach ($helper in @('MIMS Interaction Helper\make-lists.py', 'PPA Claim Helper\make-claims.py', 'PPA Claim Helper\record_report.py')) {
  if (-not (Test-Path (Join-Path $root $helper))) { Write-Warning "Optional helper not found, this build has no automated portal list for it: $helper" }
}

Invoke-Native 'Python dependencies' $venvPython @('-m', 'pip', 'install', '-r', 'requirements-build.txt')
Set-Location (Join-Path $root 'HMR Desk\engine')
Invoke-Native 'Engine packaging' $venvPython @('-m', 'PyInstaller', '--noconfirm', '--clean', 'hmr-engine.spec')
Set-Location (Join-Path $root 'desktop')
Invoke-Native 'npm ci' 'npm' @('ci')
Invoke-Native 'Desktop tests' 'npm' @('test')
& (Join-Path $root 'scripts\bundle-libreoffice.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Portable PDF converter bundling failed' }
Invoke-Native 'NSIS build' 'npm' @('run', 'dist')
Write-Host 'Build complete. Windows clean-machine E2E and clinical template sign-off are still required.'
