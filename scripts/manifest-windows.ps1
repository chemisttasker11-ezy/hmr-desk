# Candidate engineering build inventory (unsigned; do not distribute as a clinical release).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'desktop\dist'
# Works on Windows PowerShell 5.1 (.NET Framework, no [IO.Path]::GetRelativePath) and on PowerShell 7.
function Get-RelativeSlashPath([string]$base, [string]$full) {
  $b = [IO.Path]::GetFullPath($base).TrimEnd('\','/') + '\'
  $f = [IO.Path]::GetFullPath($full)
  if (-not $f.StartsWith($b, [StringComparison]::OrdinalIgnoreCase)) { throw 'Path is outside the base folder: ' + (Split-Path $full -Leaf) }
  return $f.Substring($b.Length).Replace('\','/')
}
# Run a native command; stdout lines and stderr lines are kept apart and the exit code is checked by the caller.
# $ErrorActionPreference is relaxed only around the call so stderr text cannot abort the script in Windows PowerShell 5.1.
function Invoke-NativeCapture([string[]]$cmd) {
  $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try {
    $all = @(& $cmd[0] $cmd[1..($cmd.Count - 1)] 2>&1)
    $code = $LASTEXITCODE
    $out = @($all | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } | ForEach-Object { "$_" })
    $err = @($all | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { "$_" })
    return @{ ok = ($code -eq 0); code = $code; lines = $out; errors = $err }
  } catch { return @{ ok = $false; code = -1; lines = @(); errors = @($_.Exception.Message) } } finally { $ErrorActionPreference = $old }
}
function Get-NativeFailure([string]$what, $r) {
  $d = (@($r.errors) | Select-Object -First 5) -join ' | '
  if ($d.Length -gt 600) { $d = $d.Substring(0, 600) }
  return $what + ' failed (exit ' + $r.code + '): ' + $d
}
# Normal manifest: every dependency capture is mandatory. HMR_MANIFEST_DIAGNOSTIC=1 writes a separate, clearly incomplete
# inventory instead and never the normal SHA256SUMS.txt / installer-manifest.json.
$diagnostic = ($env:HMR_MANIFEST_DIAGNOSTIC -eq '1')
$incomplete = @()
$installer = @(Get-ChildItem -Path $dist -Filter '*.exe' -File | Where-Object {$_.Name -notlike '*unpacked*'})
if ($installer.Count -lt 1) { throw 'No Windows installer EXE produced' }
$engine = Join-Path $dist 'win-unpacked\resources\engine\hmr-engine\hmr-engine.exe'
$lo = Join-Path $dist 'win-unpacked\resources\converter\libreoffice\program\soffice.exe'
foreach ($item in @($engine, $lo)) {
  if (-not (Test-Path $item)) { throw 'Missing standalone resource: ' + (Split-Path $item -Leaf) }
}
$npm = Get-Content (Join-Path $root 'desktop\package.json') -Raw | ConvertFrom-Json
$venvPy = Join-Path $root '.venv\Scripts\python.exe'
$pyExe = if (Test-Path $venvPy) { $venvPy } else { 'python' }
$pv = Invoke-NativeCapture @($pyExe, '--version')
if ($pv.ok -and (@($pv.lines) + @($pv.errors)).Count -gt 0) { $python = ((@($pv.lines) + @($pv.errors)) -join ' ').Trim() }
else {
  $m = Get-NativeFailure 'python --version' $pv
  if (-not $diagnostic) { throw $m }
  $python = 'unavailable'; $incomplete += $m
}
$node = & node --version
$sha = (& git -C $root rev-parse HEAD).Trim()
# On a pull request the checkout is GitHub's synthetic merge commit; the branch head is a different SHA.
# Record both so the artifact can be traced to the reviewed branch commit.
$mergeSha = if ($env:HMR_MERGE_SHA) { $env:HMR_MERGE_SHA } else { $sha }
$headSha = if ($env:HMR_PR_HEAD_SHA) { $env:HMR_PR_HEAD_SHA } else { $sha }
$pf = Invoke-NativeCapture @($pyExe, '-m', 'pip', 'freeze')
$pythonFreeze = @(); $pythonFreezeStatus = ''
if ($pf.ok -and $pf.lines.Count -gt 0) { $pythonFreeze = @($pf.lines); $pythonFreezeStatus = 'pip freeze from ' + $pyExe }
else {
  $pipFailure = Get-NativeFailure 'pip freeze' $pf
  # pip itself can be broken in a build venv. The installed-package list is then read from the interpreter's own
  # package metadata (stdlib, no pip). It is labelled as such and the pip failure is recorded, never hidden.
  $code = "import importlib.metadata as m; print('\n'.join(sorted(d.metadata['Name'] + '==' + d.version for d in m.distributions() if d.metadata['Name'])))"
  $im = Invoke-NativeCapture @($pyExe, '-c', $code)
  if ($im.ok -and $im.lines.Count -gt 0) {
    $pythonFreeze = @($im.lines)
    $pythonFreezeStatus = 'importlib.metadata from ' + $pyExe + ' (pip freeze failed: ' + $pipFailure + ')'
  } else {
    $m = $pipFailure + ' ; ' + (Get-NativeFailure 'importlib.metadata listing' $im)
    if (-not $diagnostic) { throw $m }
    $pythonFreezeStatus = 'unavailable'; $incomplete += $m
  }
}
$pythonRequirements = (Get-FileHash (Join-Path $root 'requirements.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
$pythonBuildRequirements = (Get-FileHash (Join-Path $root 'requirements-build.txt') -Algorithm SHA256).Hash.ToLowerInvariant()
$npmLock = (Get-FileHash (Join-Path $root 'desktop\package-lock.json') -Algorithm SHA256).Hash.ToLowerInvariant()
$vendorFile = Join-Path $root 'vendor\libreoffice\HMR-BUNDLE-MANIFEST.json'
if (-not (Test-Path $vendorFile)) { throw 'Portable converter provenance manifest missing' }
$converterProvenance = Get-Content $vendorFile -Raw | ConvertFrom-Json
$notices = @(Get-ChildItem (Join-Path $root 'vendor\libreoffice') -Recurse -File |
  Where-Object { $_.Name -like 'LICENSE*' -or $_.Name -like 'NOTICE*' } |
  ForEach-Object { Get-RelativeSlashPath (Join-Path $root 'vendor\libreoffice') $_.FullName })
if ($notices.Count -eq 0) { throw 'Converter attribution notice not bundled' }
$files = @($installer) + @((Get-Item $engine),(Get-Item $lo))
$checksums = @()
$records = @()
foreach ($file in $files) {
  $hash = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  $relative = Get-RelativeSlashPath $dist $file.FullName
  $checksums += $hash + '  ' + $relative
  $records += @{ path = $relative; size_bytes = $file.Length; sha256 = $hash }
}
$manifest = @{
  format = 1
  product = 'HMR Desk'
  version = $npm.version
  git_sha = $sha
  checkout_merge_sha = $mergeSha
  pull_request_head_sha = $headSha
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
    runtime_python_freeze_status = $pythonFreezeStatus
    converter_msi_sha256 = $converterProvenance.source_sha256
    converter_version = $converterProvenance.version
    converter_source_url = $converterProvenance.source_url
    converter_notice_files = $notices
  }
  files = $records
}
if ($diagnostic) {
  $manifest.status = 'INCOMPLETE diagnostic inventory; not a candidate manifest'
  $manifest.incomplete_reasons = $incomplete
}
if ($diagnostic) {
  $manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $dist 'installer-manifest.INCOMPLETE-diagnostic.json')
  Write-Host 'Diagnostic inventory written (INCOMPLETE). No normal manifest or SHA256SUMS.txt was produced.'
  exit 0
}
$checksums | Set-Content -Encoding ascii (Join-Path $dist 'SHA256SUMS.txt')
$manifest | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $dist 'installer-manifest.json')
Write-Host ('Engineering installer SHA256 generated for checkout ' + $sha + ' (PR head ' + $headSha + ')')
Write-Host 'This manifest is not clinical acceptance evidence.'
