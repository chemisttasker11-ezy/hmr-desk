# Reproducible dependency-bundled build; run on Windows 11 x64 with Python and Node only on BUILD HOST.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
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
    try { $version = (& $exe @extra -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null) } catch { continue }
    if ($LASTEXITCODE -eq 0 -and $version -eq '3.12') { return ,$candidate }
  }
  throw 'Python 3.12 was not found. Install it, or set the HMR_PYTHON environment variable to the full path of a Python 3.12 python.exe.'
}
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
  $found = Find-BuildPython
  $exe = $found[0]; $extra = @($found | Select-Object -Skip 1)
  & $exe @extra -m venv (Join-Path $root '.venv')
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) { throw 'Creating the build virtual environment failed' }
}
# Optional licensed portal generators are not in the repository. A missing one is reported here and the build continues:
# the packaged app then says so in the eMIMS and claims views, and the manual workflow stays available.
foreach ($helper in @('MIMS Interaction Helper\make-lists.py', 'PPA Claim Helper\make-claims.py', 'PPA Claim Helper\record_report.py')) {
  if (-not (Test-Path (Join-Path $root $helper))) { Write-Warning "Optional helper not found, this build has no automated portal list for it: $helper" }
}

& $venvPython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed' }
Set-Location (Join-Path $root 'HMR Desk\engine')
& $venvPython -m PyInstaller --noconfirm --clean hmr-engine.spec
if ($LASTEXITCODE -ne 0) { throw 'Engine packaging failed' }
Set-Location (Join-Path $root 'desktop')
npm ci
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
npm test
if ($LASTEXITCODE -ne 0) { throw 'Desktop tests failed' }
& (Join-Path $root 'scripts\bundle-libreoffice.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Portable PDF converter bundling failed' }
npm run dist
if ($LASTEXITCODE -ne 0) { throw 'NSIS build failed' }
Write-Host 'Build complete. Windows clean-machine E2E and clinical template sign-off are still required.'
