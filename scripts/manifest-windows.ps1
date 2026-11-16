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
  files = $records
}
$checksums | Set-Content -Encoding ascii (Join-Path $dist 'SHA256SUMS.txt')
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $dist 'installer-manifest.json')
Write-Host ('Engineering installer SHA256 generated for ' + $sha)
Write-Host 'This manifest is not clinical acceptance evidence.'
