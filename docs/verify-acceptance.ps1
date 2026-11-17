# Read-only verifier for the specific isolated PR5 engineering archive. Never launches the app.
[CmdletBinding()]
param(
  [string]$AppRoot = '',
  [string]$ExternalManifest = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
try {
  $scriptFolder = $PSScriptRoot
  if ([string]::IsNullOrWhiteSpace($scriptFolder)) {
    if ([string]::IsNullOrWhiteSpace($MyInvocation.MyCommand.Path)) { throw 'Save and run this script as a file, or supply explicit paths' }
    $scriptFolder = Split-Path -Parent $MyInvocation.MyCommand.Path
  }
  if ([string]::IsNullOrWhiteSpace($AppRoot)) { $AppRoot = Join-Path $scriptFolder 'acc1\app' }
  if ([string]::IsNullOrWhiteSpace($ExternalManifest)) { $ExternalManifest = Join-Path $scriptFolder 'acc-outer\hmr-isolated-acceptance.manifest.json' }
  $AppRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($AppRoot)
  $ExternalManifest = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ExternalManifest)
  function Assert-NoReparse([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    while ($null -ne $item) {
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse point refused' }
      if ($item -is [IO.DirectoryInfo]) { $item = $item.Parent } else { $item = $item.Directory }
    }
  }
  $root = [IO.Path]::GetFullPath($AppRoot).TrimEnd('\')
  if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'App folder absent or extraction incomplete' }
  Assert-NoReparse $root
  Assert-NoReparse $ExternalManifest
  $inside = Join-Path $root 'acceptance-manifest.json'
  Assert-NoReparse $inside
  $externalHash = (Get-FileHash -LiteralPath $ExternalManifest -Algorithm SHA256).Hash
  $insideHash = (Get-FileHash -LiteralPath $inside -Algorithm SHA256).Hash
  $externalBytes = [IO.File]::ReadAllBytes($ExternalManifest)
  $insideBytes = [IO.File]::ReadAllBytes($inside)
  Write-Host ('External manifest bytes=' + $externalBytes.Length + ' SHA256=' + $externalHash)
  Write-Host ('Internal manifest bytes=' + $insideBytes.Length + ' SHA256=' + $insideHash)
  $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
  $externalText = $utf8.GetString($externalBytes)
  $insideText = $utf8.GetString($insideBytes)
  $manifest = $externalText | ConvertFrom-Json
  $internalManifest = $insideText | ConvertFrom-Json
  # The Windows packer writes the external text file using CRLF, while ZipFile.writestr
  # retains LF. Permit ONLY CRLF -> LF normalization, never arbitrary JSON differences.
  if ($externalText.Replace("`r`n", "`n") -cne $insideText.Replace("`r`n", "`n")) {
    $first = 'serialization or property order'
    foreach ($key in @('format','product','purpose','signing','pull_request_head_sha','checkout_merge_sha','files')) {
      $a = $manifest.PSObject.Properties[$key]
      $b = $internalManifest.PSObject.Properties[$key]
      if ($null -eq $a -or $null -eq $b) { $first = $key + ' missing'; break }
      $aj = ConvertTo-Json -InputObject $a.Value -Depth 100 -Compress
      $bj = ConvertTo-Json -InputObject $b.Value -Depth 100 -Compress
      if ($aj -cne $bj) { $first = $key; break }
    }
    Write-Host ('First differing structural key: ' + $first + ' (values withheld)')
    throw 'Manifest difference is not solely CRLF/LF; stop and investigate'
  }
  if ($externalHash -ne $insideHash) { Write-Host 'Manifest difference verified: CRLF/LF only; content and property order identical.' }

  if ($manifest.format -ne 1 -or $manifest.product -cne 'HMR Desk' -or $manifest.signing -cne 'unsigned') { throw 'Unexpected manifest format/product/signing' }
  if ($manifest.pull_request_head_sha -cne 'f25efc81c83ed9aff215b62dc0b3de721e6a53a0') { throw 'Wrong PR head identity' }
  if ($manifest.checkout_merge_sha -cne '69a53f247bf9a2edd854f7023dd56b366120e612') { throw 'Wrong checkout merge identity' }
  $entries = @($manifest.files)
  if ($entries.Count -lt 4) { throw 'Empty or incomplete manifest' }
  $expected = @{}
  foreach ($entry in $entries) {
    $rel = [string]$entry.path
    if ([string]::IsNullOrWhiteSpace($rel) -or $rel -match '[\\:]' -or $rel.StartsWith('/') -or $rel -match '(^|/)(\.|\.\.)(/|$)' -or $rel.Contains('//')) { throw 'Unsafe manifest relative path' }
    foreach ($part in $rel.Split('/')) {
      if ($part -match '[<>"|?*\x00-\x1f]' -or $part.EndsWith('.') -or $part.EndsWith(' ') -or $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)') { throw 'Unsafe Windows path component' }
    }
    if ($rel -ieq 'acceptance-manifest.json' -or $expected.ContainsKey($rel)) { throw 'Duplicate/reserved manifest entry' }
    if ([string]$entry.sha256 -notmatch '^[0-9a-f]{64}$' -or [long]$entry.size_bytes -lt 0) { throw 'Invalid file hash/size' }
    $full = [IO.Path]::GetFullPath((Join-Path $root $rel.Replace('/', '\')))
    if (-not $full.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'File escapes app folder' }
    Assert-NoReparse $full
    $file = Get-Item -LiteralPath $full -Force
    if ($file.PSIsContainer -or $file.Length -ne [long]$entry.size_bytes) { throw ('Missing/wrong size: ' + $rel) }
    if ((Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash -ine [string]$entry.sha256) { throw ('Hash mismatch: ' + $rel) }
    $expected[$rel] = $true
  }
  $pending = New-Object 'System.Collections.Generic.Queue[string]'
  $pending.Enqueue($root)
  $count = 0
  while ($pending.Count -gt 0) {
    $dir = $pending.Dequeue()
    foreach ($item in Get-ChildItem -LiteralPath $dir -Force) {
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Unexpected link in extracted tree' }
      if ($item.PSIsContainer) { $pending.Enqueue($item.FullName); continue }
      $rel = $item.FullName.Substring($root.Length + 1).Replace('\', '/')
      if ($rel -ceq 'acceptance-manifest.json') { continue }
      if (-not $expected.ContainsKey($rel)) { throw ('Unlisted file: ' + $rel) }
      $count++
    }
  }
  if ($count -ne $entries.Count) { throw 'Extracted file count differs' }
  foreach ($required in @('HMR Desk.exe', 'resources/app.asar', 'resources/engine/hmr-engine/hmr-engine.exe', 'resources/converter/libreoffice/program/soffice.exe')) {
    if (-not $expected.ContainsKey($required)) { throw 'Required app resource missing' }
  }
  if ((Get-FileHash -LiteralPath $ExternalManifest -Algorithm SHA256).Hash -ne $externalHash -or (Get-FileHash -LiteralPath $inside -Algorithm SHA256).Hash -ne $insideHash) { throw 'Manifest changed during verification' }
  Write-Host ('PASS: ' + $count + ' app files verified; internal/external manifests match after CRLF-only normalization; exact PR and merge identities match.')
  Write-Host 'Read-only verification only. Nothing launched or installed. No clinical acceptance or signature claim.'
  exit 0
} catch {
  Write-Error ('FAIL CLOSED: ' + $_.Exception.Message)
  exit 1
}
