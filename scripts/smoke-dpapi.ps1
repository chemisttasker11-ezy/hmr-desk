# Exercise real Electron Windows safeStorage across hard process termination.
# Uses synthetic static text only. Not a clean Windows 11 VM acceptance substitute.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$electron = Join-Path $root 'desktop\node_modules\electron\dist\electron.exe'
$probe = Join-Path $root 'desktop\dev\dpapi-probe.js'
if (-not (Test-Path $electron)) { throw 'Electron binary not installed' }
$tempRoot = Join-Path $env:TEMP ('hmr-dpapi-synthetic-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $tempRoot -Force | Out-Null
$env:HMR_DPAPI_SMOKE_DIR = $tempRoot
$writer = $null
try {
  $env:HMR_DPAPI_SMOKE_MODE = 'write'
  $writer = Start-Process -FilePath $electron -ArgumentList ('"' + $probe + '"') -PassThru -WindowStyle Hidden
  $ready = Join-Path $tempRoot 'writer-ready'
  $deadline = (Get-Date).AddSeconds(30)
  while (-not (Test-Path $ready) -and (Get-Date) -lt $deadline) {
    if ($writer.HasExited) { throw 'Protected draft writer exited before persistence' }
    Start-Sleep -Milliseconds 300
    $writer.Refresh()
  }
  if (-not (Test-Path $ready)) { throw 'Timed out waiting for encrypted draft' }
  $ciphertext = Join-Path $tempRoot 'draft-vault.bin'
  if (-not (Test-Path $ciphertext)) { throw 'Encrypted draft file missing' }
  $bytes = [IO.File]::ReadAllBytes($ciphertext)
  $plain = [Text.Encoding]::UTF8.GetBytes('SYNTHETIC_DRAFT_TEST_NO_PHI_2026')
  $asText = [Text.Encoding]::UTF8.GetString($bytes)
  if ($asText.Contains('SYNTHETIC_DRAFT_TEST_NO_PHI_2026')) { throw 'Plaintext marker leaked into protected draft' }
  Stop-Process -Id $writer.Id -Force -ErrorAction Stop
  $writer.WaitForExit()
  $writer = $null
  $env:HMR_DPAPI_SMOKE_MODE = 'read'
  $stdout = Join-Path $tempRoot 'reader-out.txt'
  $stderr = Join-Path $tempRoot 'reader-err.txt'
  $reader = Start-Process -FilePath $electron -ArgumentList ('"' + $probe + '"') -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  if ($reader.ExitCode -ne 0 -or -not ((Get-Content $stdout -Raw) -match 'SYNTHETIC_DPAPI_RECOVERY_PASS')) {
    throw 'Windows protected draft failed cross-process crash recovery'
  }
  Write-Host 'Real Windows Electron protected synthetic draft survived forced termination and restart'
} finally {
  if ($writer -and -not $writer.HasExited) { Stop-Process -Id $writer.Id -Force -ErrorAction SilentlyContinue }
  Remove-Item Env:\HMR_DPAPI_SMOKE_MODE -ErrorAction SilentlyContinue
  Remove-Item Env:\HMR_DPAPI_SMOKE_DIR -ErrorAction SilentlyContinue
  Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
