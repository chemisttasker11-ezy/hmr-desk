# Read-only provenance listing for HMR Desk processes. Changes nothing, kills nothing, reads no token, no patient data.
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File hmr-provenance.ps1 [-Port 53573] [-DataDir C:\path\HMR-Desk-data]
param([int]$Port = 53573, [string[]]$DataDir = @())
$ErrorActionPreference = 'Continue'
if ($DataDir.Count -eq 0) { $DataDir = @((Join-Path $env:USERPROFILE 'HMR-Desk-data')) }
function Describe($procId) {
  $p = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $procId) -ErrorAction SilentlyContinue
  if (-not $p) { return $null }
  $hash = ''; $ver = ''
  if ($p.ExecutablePath -and (Test-Path -LiteralPath $p.ExecutablePath)) {
    $hash = (Get-FileHash -LiteralPath $p.ExecutablePath -Algorithm SHA256).Hash
    $ver = (Get-Item -LiteralPath $p.ExecutablePath).VersionInfo.FileVersion
  }
  $cmd = [string]$p.CommandLine
  $cmd = [regex]::Replace($cmd, '(?i)(token|secret|password)[=: ]+\S+', '$1=<hidden>')
  $win = Get-Process -Id $procId -ErrorAction SilentlyContinue
  [pscustomobject]@{ PID = $procId; Parent = $p.ParentProcessId; Name = $p.Name; Started = $p.CreationDate; HWND = $(if ($win) { $win.MainWindowHandle } else { '' });
    Title = $(if ($win) { $win.MainWindowTitle } else { '' }); Exe = $p.ExecutablePath; Sha256 = $hash; FileVersion = $ver; CommandLine = $cmd }
}
Write-Output ("== Listeners on port " + $Port)
$listen = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if (-not $listen) { Write-Output "none" }
foreach ($l in $listen) { Write-Output ("listener " + $l.LocalAddress + ":" + $l.LocalPort + " owner PID " + $l.OwningProcess); Describe $l.OwningProcess | Format-List }
Write-Output "== All HMR-related listeners (engine and electron)"
$names = @('hmr-engine', 'HMR Desk', 'electron')
foreach ($p in (Get-Process -ErrorAction SilentlyContinue | Where-Object { $n = $_.ProcessName; $names | Where-Object { $n -like ($_ + '*') } })) {
  $conns = Get-NetTCPConnection -State Listen -OwningProcess $p.Id -ErrorAction SilentlyContinue | ForEach-Object { $_.LocalAddress + ':' + $_.LocalPort }
  Describe $p.Id | Format-List
  Write-Output ("  listening: " + ($conns -join ', '))
}
Write-Output "== Engine endpoint files (url/pids only, token file is never read)"
foreach ($d in $DataDir) {
  $f = Join-Path $d 'engine_endpoint.json'
  Write-Output ("-- " + $f)
  if (Test-Path -LiteralPath $f) { Get-Content -LiteralPath $f -Raw } else { Write-Output "missing" }
  $c = Join-Path $d 'app-config.json'
  if (Test-Path -LiteralPath $c) { try { $j = Get-Content -LiteralPath $c -Raw | ConvertFrom-Json; Write-Output ("app-config api: " + $j.api) } catch { Write-Output "app-config unreadable" } }
}
Write-Output "== Environment of this shell (not of other processes)"
Write-Output ("HMR_API=" + $env:HMR_API + "  USERPROFILE=" + $env:USERPROFILE)
