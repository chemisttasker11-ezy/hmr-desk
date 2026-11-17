# Specific PR5 engineering acceptance launcher. Process-only path isolation, NOT an OS sandbox.
[CmdletBinding()]
param()
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
  # A unique fresh root, not an existing profile. Keep all synthetic output for inspection.
  $profile = Join-Path $PSScriptRoot ('hmr-acceptance-' + [Guid]::NewGuid().ToString('N'))
  if (Test-Path -LiteralPath $profile) { throw 'Fresh isolation root unexpectedly exists' }
  [void][IO.Directory]::CreateDirectory($profile)
  $data = Join-Path $profile 'HMR-Desk-data'
  $workspace = Join-Path $data 'workspace'
  $roaming = Join-Path $profile 'AppData\Roaming'
  $local = Join-Path $profile 'AppData\Local'
  $temp = Join-Path $profile 'Temp'
  foreach ($dir in @($roaming,$local,$temp)) { [void][IO.Directory]::CreateDirectory($dir) }
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
  Write-Host 'Select Use recommended folder in the first-run dialog. Do not choose any existing workspace.'
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
