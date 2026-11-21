# Launch ONE app build with its OWN empty profile folder. No patient data is copied by this script.
# main.js derives the data folder, app profile (single-instance lock, sign-ins), config and default workspace from
# %USERPROFILE%\HMR-Desk-data, so a different USERPROFILE for this one process gives a separate set. The packaged app starts its
# own bundled engine on its own free loopback port. Real effects: it creates the sandbox folder and starts the app process.
# Run:  powershell -NoProfile -ExecutionPolicy Bypass -File hmr-isolated-launch.ps1 -Exe "C:\path\HMR Desk.exe" -Sandbox C:\hmr-iso\cand
param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string]$Sandbox)
if (-not (Test-Path -LiteralPath $Exe)) { throw 'Exe not found' }
$real = [System.IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')
$box = [System.IO.Path]::GetFullPath($Sandbox).TrimEnd('\')
if ($box -ieq $real -or $box.StartsWith($real + '\HMR-Desk-data', [StringComparison]::OrdinalIgnoreCase)) { throw 'Sandbox must be a different folder from the real profile and its HMR-Desk-data' }
$data = Join-Path $box 'HMR-Desk-data'
$cfg = Join-Path $data 'app-config.json'
if (Test-Path -LiteralPath $cfg) {
  $base = (Get-Content -LiteralPath $cfg -Raw | ConvertFrom-Json).base
  if (-not ([string]$base).StartsWith($box + '\', [StringComparison]::OrdinalIgnoreCase)) { throw ('Sandbox config workspace points outside the sandbox: ' + $base) }
}
New-Item -ItemType Directory -Force -Path $box | Out-Null
$env:USERPROFILE = $box
foreach ($name in 'HMR_API', 'HMR_SMOKE_DATA', 'HMR_SMOKE_URL', 'HMR_SHOTS', 'HMR_DATA_DIR', 'HMR_DB', 'HMR_WORKSPACE') { Remove-Item ("Env:" + $name) -ErrorAction SilentlyContinue }
$p = Start-Process -FilePath $Exe -PassThru
Write-Output ("started PID " + $p.Id + "; USERPROFILE for this process only = " + $box)
Write-Output ("data folder: " + $data + "  (first run asks for a workspace: choose a folder INSIDE " + $box + ")")
Write-Output ("check afterwards: hmr-provenance.ps1 -DataDir '" + $data + "'")
