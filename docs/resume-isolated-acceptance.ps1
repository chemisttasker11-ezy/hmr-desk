# Specific PR5 engineering acceptance launcher. Process-only path isolation, NOT an OS sandbox.
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ProfileLeaf,
  [switch]$PrepareFixtures
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$launched = $null
try {
  if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) { throw 'Save and run this script as a file in Downloads' }
  $appRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'acc1\app'))
  $manifestPath = Join-Path $PSScriptRoot 'acc-outer\hmr-isolated-acceptance.manifest.json'
  $verifier = Join-Path $PSScriptRoot 'verify-acceptance.ps1'
  if ((Get-FileHash -LiteralPath $verifier -Algorithm SHA256).Hash -ine '5db045ed7be621bfbc0e7c040da5a46cda555f2eae3f07c1198500be9b474f3a') { throw 'Wrong verifier script' }
  # Separate PowerShell process: verifier exit must not terminate this launcher.
  $powerShell = Join-Path $PSHOME 'powershell.exe'
  & $powerShell -NoProfile -ExecutionPolicy Bypass -File $verifier -AppRoot $appRoot -ExternalManifest $manifestPath
  if ($LASTEXITCODE -ne 0) { throw 'Full archive verification failed; nothing launched' }
  $existing = @(Get-CimInstance Win32_Process -Filter "Name='HMR Desk.exe' OR Name='hmr-engine.exe'")
  if ($existing.Count -ne 0) { throw 'An HMR Desk or engine process already exists. Do not terminate it automatically; coordinate with operator.' }
  $exe = Join-Path $appRoot 'HMR Desk.exe'
  $engineExe = Join-Path $appRoot 'resources\engine\hmr-engine\hmr-engine.exe'
  # Resume only a strictly named acceptance root beside this script, never a normal profile.
  if ($ProfileLeaf -cnotmatch '^hmr-acceptance-[0-9a-f]{32}$') { throw 'Invalid acceptance profile leaf' }
  $profile = Join-Path $PSScriptRoot $ProfileLeaf
  $data = Join-Path $profile 'HMR-Desk-data'
  $workspace = Join-Path $data 'workspace'
  $roaming = Join-Path $profile 'AppData\Roaming'
  $local = Join-Path $profile 'AppData\Local'
  $temp = Join-Path $profile 'Temp'
  foreach ($dir in @($profile,$data,$workspace,$roaming,$local,$temp)) {
    $item = Get-Item -LiteralPath $dir -Force
    while ($null -ne $item) {
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Existing isolation directory link refused' }
      $item = $item.Parent
    }
  }
  $priorConfig = [IO.File]::ReadAllText((Join-Path $data 'app-config.json')) | ConvertFrom-Json
  if ($priorConfig.base -ine $workspace) { throw 'Existing acceptance workspace does not match' }
  if ($PrepareFixtures) {
    $fixtureRoot = Join-Path $profile 'fixtures'
    if (Test-Path -LiteralPath $fixtureRoot) { throw 'Fixtures already exist; omit -preparefixtures to resume' }
    $legacy = Join-Path $workspace 'TO SORT\intake_corrections.json'
    if (Test-Path -LiteralPath $legacy) { throw 'Legacy fixture target already exists; refusing overwrite' }
    $legacyParent = Split-Path -Parent $legacy
    if (Test-Path -LiteralPath $legacyParent) {
      if (((Get-Item -LiteralPath $legacyParent -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Legacy fixture parent link refused' }
    }
    foreach ($leaf in @('exports','backups','restores')) {
      if (Test-Path -LiteralPath (Join-Path $profile $leaf)) { throw 'Fixture output folder already exists; refusing ambiguous reuse' }
    }
    [void][IO.Directory]::CreateDirectory($fixtureRoot)
    foreach ($leaf in @('exports','backups','restores')) { [void][IO.Directory]::CreateDirectory((Join-Path $profile $leaf)) }
    [void][IO.Directory]::CreateDirectory((Split-Path -Parent $legacy))
    # Ordinary source-compatible empty corrections map, byte-exact three bytes: {} and LF.
    [IO.File]::WriteAllBytes($legacy, [byte[]]@(123,125,10))
    $pdf = Join-Path $fixtureRoot 'synthetic-referral.pdf'
    [IO.File]::WriteAllBytes($pdf, [Convert]::FromBase64String('JVBERi0xLjMKJZOMi54gUmVwb3J0TGFiIEdlbmVyYXRlZCBQREYgZG9jdW1lbnQgaHR0cDovL3d3dy5yZXBvcnRsYWIuY29tCjEgMCBvYmoKPDwKL0YxIDIgMCBSCj4+CmVuZG9iagoyIDAgb2JqCjw8Ci9CYXNlRm9udCAvSGVsdmV0aWNhIC9FbmNvZGluZyAvV2luQW5zaUVuY29kaW5nIC9OYW1lIC9GMSAvU3VidHlwZSAvVHlwZTEgL1R5cGUgL0ZvbnQKPj4KZW5kb2JqCjMgMCBvYmoKPDwKL0NvbnRlbnRzIDcgMCBSIC9NZWRpYUJveCBbIDAgMCA1OTUgODQyIF0gL1BhcmVudCA2IDAgUiAvUmVzb3VyY2VzIDw8Ci9Gb250IDEgMCBSIC9Qcm9jU2V0IFsgL1BERiAvVGV4dCAvSW1hZ2VCIC9JbWFnZUMgL0ltYWdlSSBdCj4+IC9Sb3RhdGUgMCAvVHJhbnMgPDwKCj4+IAogIC9UeXBlIC9QYWdlCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9QYWdlTW9kZSAvVXNlTm9uZSAvUGFnZXMgNiAwIFIgL1R5cGUgL0NhdGFsb2cKPj4KZW5kb2JqCjUgMCBvYmoKPDwKL0F1dGhvciAoYW5vbnltb3VzKSAvQ3JlYXRpb25EYXRlIChEOjIwMDAwMTAxMDAwMDAwKzAwJzAwJykgL0NyZWF0b3IgKFJlcG9ydExhYiBQREYgTGlicmFyeSAtIHd3dy5yZXBvcnRsYWIuY29tKSAvS2V5d29yZHMgKCkgL01vZERhdGUgKEQ6MjAwMDAxMDEwMDAwMDArMDAnMDAnKSAvUHJvZHVjZXIgKFJlcG9ydExhYiBQREYgTGlicmFyeSAtIHd3dy5yZXBvcnRsYWIuY29tKSAKICAvU3ViamVjdCAodW5zcGVjaWZpZWQpIC9UaXRsZSAodW50aXRsZWQpIC9UcmFwcGVkIC9GYWxzZQo+PgplbmRvYmoKNiAwIG9iago8PAovQ291bnQgMSAvS2lkcyBbIDMgMCBSIF0gL1R5cGUgL1BhZ2VzCj4+CmVuZG9iago3IDAgb2JqCjw8Ci9GaWx0ZXIgWyAvQVNDSUk4NURlY29kZSAvRmxhdGVEZWNvZGUgXSAvTGVuZ3RoIDQ0Mgo+PgpzdHJlYW0KR2Fybz47L2E7bydTWUhDKCRCUkAxK2dkZlpZc2ApQz8hU2cwNy0qNVNMZyFgNVtGPF5VWCQ5XS8uYClSTzJKTEUobTxQKEd1T3Q6K3UiN08/cGZgNWZWaCNkPTxcRWwoaFhZLG9TZlxmIWBBbFlscUJWOExDSk84clNWLlZNOF51IzUkUk0tZ0ZXKy4sMjNJK3Ehbk9daSUnP2IyVkRWdG9nQz5kL29EaUgrUlgyKTArNVdZal1aQGsqWkkuVHFNcyRyUzxLaGhlaFVwRSFFMD4nKXJKWkcvMT8zOmZsM1VXJ3I0YCwiX2VeRiwzTVZSUDEuclNNTSlGSkJCLiUuTkRLLSNPbldTNlpCSzopYlplT1xtcVQ9KSZdZmEmMk1UcVYpLU1oTFokJyJLKkhXMGNzJmRNJFEkZj5wWHNJQ2lrRjFJaFZAOWJta3RaR1hNRycnUzltKVAqJCZWTF1cTUZxL005QDctNEMzRiMxNWYyaFZsITU1UTMiXURWPiRHTENDXEwjKXQsW0U4bE5jU09ILVFzV3BwXlNORi1AJ2VcViFyYkRyX2dwJkItbk8kVzQ+NjtHITl+PmVuZHN0cmVhbQplbmRvYmoKeHJlZgowIDgKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDczIDAwMDAwIG4gCjAwMDAwMDAxMDQgMDAwMDAgbiAKMDAwMDAwMDIxMSAwMDAwMCBuIAowMDAwMDAwNDA0IDAwMDAwIG4gCjAwMDAwMDA0NzIgMDAwMDAgbiAKMDAwMDAwMDc2OCAwMDAwMCBuIAowMDAwMDAwODI3IDAwMDAwIG4gCnRyYWlsZXIKPDwKL0lEIApbPDFjMTc4MTk4ZmJkZmE1MWIyNTk5NWQ4OWQ0MTAyMDQzPjwxYzE3ODE5OGZiZGZhNTFiMjU5OTVkODlkNDEwMjA0Mz5dCiUgUmVwb3J0TGFiIGdlbmVyYXRlZCBQREYgZG9jdW1lbnQgLS0gZGlnZXN0IChodHRwOi8vd3d3LnJlcG9ydGxhYi5jb20pCgovSW5mbyA1IDAgUgovUm9vdCA0IDAgUgovU2l6ZSA4Cj4+CnN0YXJ0eHJlZgoxMzU5CiUlRU9GCg=='))
    if ((Get-FileHash -LiteralPath $pdf -Algorithm SHA256).Hash -ine '5304393c7276786de821805faaff66b207c3b503828ee194571e9cbb5b103c00') { throw 'Synthetic PDF hash mismatch' }
    Write-Host 'Synthetic fixtures created only in this acceptance root; no database edits or dev-tools flag.'
    Write-Host ('Referral PDF: ' + $pdf)
    Write-Host ('Legacy shared map SHA256: ' + (Get-FileHash -LiteralPath $legacy -Algorithm SHA256).Hash)
  }
  $start = New-Object System.Diagnostics.ProcessStartInfo
  $start.FileName = $exe
  $start.WorkingDirectory = $appRoot
  $start.UseShellExecute = $false
  # Modify ONLY this child's copied environment. Never user/machine environment or registry.
  foreach ($key in @($start.EnvironmentVariables.Keys)) {
    if ($key -match '^(HMR_|ELECTRON_|PYTHON|NODE_OPTIONS$|NODE_PATH$|CLAUDE_CONFIG_DIR$)') { $start.EnvironmentVariables.Remove($key) }
  }
  $start.EnvironmentVariables['USERPROFILE'] = $profile
  $start.EnvironmentVariables['HOME'] = $profile
  $start.EnvironmentVariables['APPDATA'] = $roaming
  $start.EnvironmentVariables['LOCALAPPDATA'] = $local
  $start.EnvironmentVariables['TEMP'] = $temp
  $start.EnvironmentVariables['TMP'] = $temp
  $start.EnvironmentVariables['CLAUDE_CONFIG_DIR'] = Join-Path $profile '.claude'
  $start.EnvironmentVariables['HOMEDRIVE'] = [IO.Path]::GetPathRoot($profile).TrimEnd('\')
  $start.EnvironmentVariables['HOMEPATH'] = $profile.Substring([IO.Path]::GetPathRoot($profile).Length - 1)
  Write-Host ('Synthetic profile: ' + $profile)
  Write-Host ('Expected data: ' + $data)
  Write-Host ('Expected workspace: ' + $workspace)
  Write-Host 'Resuming the verified synthetic profile. No first-run folder choice is expected; stop if one appears.'
  Write-Host 'Do not use clinical functions until ENGINE PATH GATE PASS. No real patient files, sign-ins, external helper actions or real-record removal.'
  Write-Host 'Native Windows file dialogs are NOT isolated. This is process path isolation, not an OS sandbox.'
  $launched = [Diagnostics.Process]::Start($start)
  if ($null -eq $launched) { throw 'No launched process returned' }
  Write-Host ('Launched isolated app PID ' + $launched.Id + '; waiting up to 180 seconds for recommended-folder choice and engine.')
  $deadline = [DateTime]::UtcNow.AddSeconds(180)
  $gated = $false
  while ([DateTime]::UtcNow -lt $deadline) {
    $launched.Refresh()
    if ($launched.HasExited) { throw 'Isolated app exited before engine path gate' }
    $appProcess = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $launched.Id)
    if ($null -eq $appProcess -or $appProcess.ExecutablePath -ine $exe) { throw 'App executable path cannot be verified' }
    $engines = @(Get-CimInstance Win32_Process -Filter "Name='hmr-engine.exe'")
    if ($engines.Count -gt 0) {
      # PyInstaller may have a same-executable child. Every engine must descend from this launch.
      $allowed = @{}; $allowed[[int]$launched.Id] = $true
      for ($round = 0; $round -lt 4; $round++) {
        foreach ($engine in $engines) {
          if ($allowed.ContainsKey([int]$engine.ParentProcessId)) { $allowed[[int]$engine.ProcessId] = $true }
        }
      }
      foreach ($engine in $engines) {
        if (-not $allowed.ContainsKey([int]$engine.ProcessId) -or $engine.ExecutablePath -ine $engineExe) { throw 'Engine executable/ancestry gate failed' }
        $cmd = [string]$engine.CommandLine
        # Require exact path arguments and one occurrence of each switch, not substring matches.
        # Node quotes paths containing spaces, and may leave simple paths unquoted.
        $dataArg = '"' + [regex]::Escape($data) + '"'
        $workspaceArg = '"' + [regex]::Escape($workspace) + '"'
        if ($data -notmatch '\s') { $dataArg = '(?:' + $dataArg + '|' + [regex]::Escape($data) + ')' }
        if ($workspace -notmatch '\s') { $workspaceArg = '(?:' + $workspaceArg + '|' + [regex]::Escape($workspace) + ')' }
        $dataPattern = '(?:^|\s)--data-dir\s+' + $dataArg + '(?=\s|$)'
        $workspacePattern = '(?:^|\s)--workspace\s+' + $workspaceArg + '(?=\s|$)'
        if ([regex]::Matches($cmd, '(?:^|\s)--data-dir(?=\s|=|$)').Count -ne 1 -or
            [regex]::Matches($cmd, '(?:^|\s)--workspace(?=\s|=|$)').Count -ne 1 -or
            $cmd -notmatch $dataPattern -or $cmd -notmatch $workspacePattern) { throw 'Engine command-line path gate failed (contents withheld)' }
      }
      $configPath = Join-Path $data 'app-config.json'
      $config = [IO.File]::ReadAllText($configPath) | ConvertFrom-Json
      if ($config.base -ine $workspace) { throw 'Saved workspace gate failed' }
      foreach ($dir in @($data,$workspace,(Join-Path $data 'app-profile'))) {
        $item = Get-Item -LiteralPath $dir -Force
        while ($null -ne $item) {
          if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Isolation directory link refused' }
          $item = $item.Parent
        }
      }
      $gated = $true
      Write-Host 'ENGINE PATH GATE PASS: bundled executable, launch ancestry, exact data/workspace arguments, saved workspace and profile directories verified.'
      Write-Host 'App remains open for synthetic interactive acceptance only. This gate does not establish app readiness, clean-machine behavior or clinical acceptance.'
      break
    }
    Start-Sleep -Milliseconds 500
  }
  if (-not $gated) { throw 'Timed out before engine path gate' }
} catch {
  if ($null -ne $launched) {
    $launched.Refresh()
    if (-not $launched.HasExited) {
      # Only the still-live process handle from THIS launch and its descendants; never by image name.
      & (Join-Path $env:SystemRoot 'System32\taskkill.exe') /PID $launched.Id /T /F
    }
  }
  Write-Error ('FAIL CLOSED: ' + $_.Exception.Message + '. No acceptance permitted. Synthetic root retained; do not launch manually.')
  exit 1
}
