# Reproducible dependency-bundled build; run on Windows 11 x64 with Python and Node only on BUILD HOST.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path '.venv\\Scripts\\python.exe')) { py -3.12 -m venv .venv }
& '.venv\\Scripts\\python.exe' -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed' }
Set-Location (Join-Path $root 'HMR Desk\\engine')
& (Join-Path $root '.venv\\Scripts\\python.exe') -m PyInstaller --noconfirm --clean hmr-engine.spec
if ($LASTEXITCODE -ne 0) { throw 'Engine packaging failed' }
Set-Location (Join-Path $root 'desktop')
npm ci
if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
npm test
if ($LASTEXITCODE -ne 0) { throw 'Desktop tests failed' }
& (Join-Path $root 'scripts\\bundle-libreoffice.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Portable PDF converter bundling failed' }
npm run dist
if ($LASTEXITCODE -ne 0) { throw 'NSIS build failed' }
Write-Host 'Build complete. Windows clean-machine E2E and clinical template sign-off are still required.'
