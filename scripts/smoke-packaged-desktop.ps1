# Synthetic Windows runner smoke of unpacked packaged desktop without Node/Python in PATH.
# This is NOT a clean Windows 11 VM acceptance test.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root 'desktop\\dist\\win-unpacked\\HMR Desk.exe'
if (-not (Test-Path $exe)) { throw 'Unpacked HMR Desktop executable not found' }
$originalHome = $env:USERPROFILE
$originalPath = $env:PATH
$isolated = Join-Path $env:TEMP ('hmr-desktop-smoke-' + [guid]::NewGuid().ToString('N'))
$data = Join-Path $isolated 'HMR-Desk-data'
$workspace = Join-Path $data 'workspace'
New-Item -ItemType Directory -Force -Path $data, $workspace | Out-Null
@{ base = $workspace } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $data 'app-config.json')
$process = $null
try {
  $env:USERPROFILE = $isolated
  $env:PATH = "$env:SystemRoot\\System32;$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0;$env:SystemRoot"
  $process = Start-Process -FilePath $exe -PassThru
  $engine = $null
  $mainWindow = [IntPtr]::Zero
  $deadline = (Get-Date).AddSeconds(90)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    $process.Refresh()
    if ($process.HasExited) { throw 'Packaged Electron quit before engine ready' }
    $mainWindow = $process.MainWindowHandle
    $engines = @(Get-CimInstance Win32_Process -Filter "Name='hmr-engine.exe'" |
      Where-Object { $_.CommandLine -like "*$isolated*" })
    if ($engines.Count -gt 1) { throw 'More than one bundled engine started' }
    if ($engines.Count -eq 1 -and (Test-Path (Join-Path $data 'api_token')) -and
        (Test-Path (Join-Path $data 'hmr.db')) -and $mainWindow -ne [IntPtr]::Zero) {
      $engine = $engines[0]
      break
    }
  }
  if (-not $engine) { throw 'Packaged UI/engine did not become ready from isolated workspace' }
  if ($engine.CommandLine -notmatch '--port\\s+(\\d+)') { throw 'Engine did not select a loopback API port' }
  $port = [int]$Matches[1]
  $token = (Get-Content -Raw (Join-Path $data 'api_token')).Trim()
  $result = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -Headers @{ 'X-HMR-Token' = $token } -TimeoutSec 5
  if (-not $result.ready -or -not $result.capabilities.manual_hmr) { throw 'Packaged engine health rejected' }
  if (-not (Test-Path (Join-Path $data 'workspace'))) { throw 'Patient workspace not created' }
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class HmrWin32 {
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
}
'@
  [HmrWin32]::PostMessage($mainWindow, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
  $process.WaitForExit(15000) | Out-Null
  if (-not $process.HasExited) { throw 'Desktop UI failed to exit on window close' }
  Start-Sleep -Seconds 2
  $orphan = @(Get-CimInstance Win32_Process -Filter "Name='hmr-engine.exe'" |
    Where-Object { $_.CommandLine -like "*$isolated*" })
  if ($orphan.Count) { throw 'Bundled clinical engine remained running after UI close' }
  Write-Host 'PASS: packaged UI and owned engine launch without Node/Python on PATH; authenticated health; graceful shutdown; isolated synthetic patient workspace'
}
finally {
  $env:USERPROFILE = $originalHome
  $env:PATH = $originalPath
  if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
  if ($engine) { Stop-Process -Id $engine.ProcessId -Force -ErrorAction SilentlyContinue }
  if (Test-Path $isolated) { Remove-Item -Path $isolated -Recurse -Force -ErrorAction SilentlyContinue }
}
