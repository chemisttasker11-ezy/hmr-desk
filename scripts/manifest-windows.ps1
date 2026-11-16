# Candidate engineering build inventory (unsigned; do not distribute as a clinical release).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'desktop\dist'
$installer = @(Get-ChildItem -Path $dist -Filter '*.exe' -File | Where-Object {$_.Name -notlike '*unpacked*'})
if ($installer.Count -lt 1) { throw 'No Windows installer EXE produced' }
$engine = Join-Path $dist 'win-unpacked\resources\engine\hmr-engine\hmr-engine.exe'
$lo = Join-Path $dist 'win-unpacked\resources\converter\libreoffice\program\soffice.exe'
foreach ($item in @($engine, $lo)) {
  if (-not (Test-Path $item)) { throw 'Missing standalone resource: ' + (Split-Path $item -Leaf) }
}
$npm = Get-Content (Join-Path $root 'desktop\package.json') -Raw | ConvertFrom-Json
$python = & python --version
$node = & node --version
$sha = (& git -C $root rev-parse HEAD).Trim()
$pythonFreeze = @(& python -m pip freeze)
$pythonRequirements = (Get-FileHash (Join-Path $root 'requirements.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
$pythonBuildRequirements = (Get-FileHash (Join-Path $root 'requirements-build.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
$npmLock = (Get-FileHash (Join-Path $root 'desktop\\package-lock.json') -Algorithm SHA256).Hash.ToLowerInvariant()
$vendorFile = Join-Path $root 'vendor\\libreoffice\\HMR-BUNDLE-MANIFEST.json'
if (-not (Test-Path $vendorFile)) { throw 'Portable converter provenance manifest missing' }
$converterProvenance = Get-Content $vendorFile -Raw | ConvertFrom-Json
$notices = @(Get-ChildItem (Join-Path $root 'vendor\\libreoffice') -Recurse -File |
  Where-Object { $_.Name -like 'LICENSE*' -or $_.Name -like 'NOTICE*' } |
  ForEach-Object { [IO.Path]::GetRelativePath((Join-Path $root 'vendor\\libreoffice'),$_.FullName).Replace('\\','/') })
if ($notices.Count -eq 0) { throw 'Converter attribution notice not bundled' }
$files = @($installer) + @((Get-Item $engine),(Get-Item $lo))
$checksums = @()
$records = @()
foreach ($file in $files) {
  $hash = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  $relative = [IO.Path]::GetRelativePath($dist, $file.FullName).Replace('\','/')
  $checksums += $hash + '  ' + $relative
  $records += @{ path = $relative; size_bytes = $file.Length; sha256 = $hash }
}
$manifest = @{
  format = 1
  product = 'HMR Desk'
  version = $npm.version
  git_sha = $sha
  platform = 'win-x64'
  ci_host = 'windows-2022 (not Windows 11 clean VM)'
  signing = 'unsigned engineering candidate; clinical release not approved'
  node_build_version = $node
  python_build_version = $python
  source_integrity = @{
    python_requirements_sha256 = $pythonRequirements
    python_build_requirements_sha256 = $pythonBuildRequirements
    npm_package_lock_sha256 = $npmLock
    runtime_python_freeze = $pythonFreeze
    converter_msi_sha256 = $converterProvenance.source_sha256
    converter_version = $converterProvenance.version
    converter_source_url = $converterProvenance.source_url
    converter_notice_files = $notices
  }
  files = $records
}
$checksums | Set-Content -Encoding ascii (Join-Path $dist 'SHA256SUMS.txt')
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $dist 'installer-manifest.json')
Write-Host ('Engineering installer SHA256 generated for ' + $sha)
Write-Host 'This manifest is not clinical acceptance evidence.'
