# Bundle a pinned, checksum-verified LibreOffice runtime for local DOCX -> PDF.
# Build-host only; the installed pharmacist workstation requires no LibreOffice.
# LibreOffice MPL 2.0 and third-party license notices travel with the extracted tree.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$vendor = Join-Path $root 'vendor'
$final = Join-Path $vendor 'libreoffice'
$soffice = Join-Path $final 'program\\soffice.exe'
$version = '25.8.7'
$expected = 'ecdb65e76f5e91dc198b8c8dce5b5d6e1eb12fea6023553e52b591afd10b619d'
if (Test-Path $soffice) {
  $manifestFile = Join-Path $final 'HMR-BUNDLE-MANIFEST.json'
  if (-not (Test-Path $manifestFile)) { throw 'Cached LibreOffice lacks verified provenance manifest' }
  $cached = Get-Content $manifestFile -Raw | ConvertFrom-Json
  $actualExe = (Get-FileHash $soffice -Algorithm SHA256).Hash.ToLowerInvariant()
  $license = Get-ChildItem $final -Filter 'LICENSE*' -File -Recurse | Select-Object -First 1
  if (-not $license -or $cached.version -ne $version -or
      $cached.source_sha256 -ne $expected -or $cached.executable_sha256 -ne $actualExe) {
    throw 'Cached LibreOffice version, hash or licence invalid; refusing unverified redistribution'
  }
  Write-Host 'Cached LibreOffice runtime and licence revalidated'
  exit 0
}
New-Item -ItemType Directory -Path $vendor -Force | Out-Null
$work = Join-Path $env:TEMP ('hmr-libreoffice-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
$url = 'https://download.documentfoundation.org/libreoffice/stable/25.8.7/win/x86_64/LibreOffice_25.8.7_Win_x86-64.msi'
$download = Join-Path $work 'libreoffice.msi'
$stage = Join-Path $work 'msi-content'
try {
  # Optional build cache of the already verified MSI (keyed by the pinned SHA256 in CI).
  $cacheDir = $env:HMR_LIBREOFFICE_MSI_CACHE
  $cachedMsi = if ($cacheDir) { Join-Path $cacheDir ($expected + '.msi') } else { $null }
  $have = $false
  if ($cachedMsi -and (Test-Path $cachedMsi)) {
    $cachedHash = (Get-FileHash $cachedMsi -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($cachedHash -eq $expected) { Copy-Item $cachedMsi $download; $have = $true; Write-Host 'Using cached, hash-verified LibreOffice MSI' }
    else { Remove-Item $cachedMsi -Force; Write-Host 'Discarded cached MSI with wrong hash' }
  }
  if (-not $have) {
    # Transient upstream errors (for example HTTP 502) are retried with backoff. Every
    # attempt is checked against the one pinned SHA256; a different file is never accepted.
    $attempts = 6
    for ($i = 1; $i -le $attempts -and -not $have; $i++) {
      try {
        Invoke-WebRequest -Uri $url -OutFile $download -MaximumRedirection 8 -TimeoutSec 600
        $actual = (Get-FileHash $download -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw "LibreOffice download checksum mismatch ($actual)" }
        $have = $true
      } catch {
        Write-Host "LibreOffice download attempt $i of $attempts failed: $($_.Exception.Message)"
        if (Test-Path $download) { Remove-Item $download -Force -ErrorAction SilentlyContinue }
        if ($i -lt $attempts) { Start-Sleep -Seconds ([Math]::Min(120, 10 * [Math]::Pow(2, $i - 1))) }
      }
    }
    if (-not $have) { throw 'LibreOffice download failed or checksum mismatch after retries; refusing to package' }
    if ($cachedMsi) {
      New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null
      Copy-Item $download $cachedMsi -Force
    }
  }
  New-Item -ItemType Directory -Path $stage | Out-Null
  $process = Start-Process -FilePath 'msiexec.exe' -ArgumentList @('/a', ('"' + $download + '"'), '/qn',
    ('TARGETDIR="' + $stage + '"'), '/norestart') -Wait -PassThru -NoNewWindow
  if ($process.ExitCode -ne 0) { throw "Portable LibreOffice MSI administrative extraction failed ($($process.ExitCode))" }
  $exe = Get-ChildItem -Path $stage -Filter soffice.exe -File -Recurse |
    Where-Object { $_.Directory.Name -eq 'program' } | Select-Object -First 1
  if (-not $exe) { throw 'Extracted LibreOffice missing soffice.exe' }
  $src = Split-Path -Parent $exe.Directory.FullName
  New-Item -ItemType Directory -Path $final -Force | Out-Null
  Copy-Item -Path (Join-Path $src '*') -Destination $final -Recurse -Force
  if (-not (Test-Path $soffice)) { throw 'Portable LibreOffice layout incomplete' }
  $license = Get-ChildItem $final -Filter 'LICENSE*' -File -Recurse | Select-Object -First 1
  if (-not $license) { throw 'LibreOffice licence notice missing; refuse redistribution' }
  $manifest = [ordered]@{
    version=$version; source_url=$url; source_sha256=$expected;
    executable_sha256=(Get-FileHash $soffice -Algorithm SHA256).Hash.ToLowerInvariant()
  } | ConvertTo-Json
  $manifest | Set-Content -Path (Join-Path $final 'HMR-BUNDLE-MANIFEST.json') -Encoding UTF8
  Write-Host "Bundled verified LibreOffice $version at $soffice"
} finally {
  if (Test-Path $work) { Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue }
}
