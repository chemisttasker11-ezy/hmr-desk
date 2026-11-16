<#
Windows 11 standard-user release evidence collector. Does NOT install software,
alter network settings or inspect patient clinical narratives. Run on a fresh
Windows 11 x64 VM with the candidate installed and internet disconnected.
Evidence contains only synthetic file metadata and machine build information.
#>
param(
  [Parameter(Mandatory=$true)][string]$InstallerPath,
  [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
  [string]$InstalledExe = "$env:LOCALAPPDATA\Programs\HMR Desk\HMR Desk.exe",
  [string]$SyntheticWorkspace = "$env:USERPROFILE\HMR-Desk-data\workspace"
)
$ErrorActionPreference = 'Stop'
function Add-Check([string]$id,[bool]$passed,[string]$description) {
  $script:checks += @{id=$id;pass=$passed;description=$description}
}
$checks = @()
$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
$win11 = $os.ProductType -eq 1 -and $build -ge 22000 -and $os.OSArchitecture -match '64'
Add-Check 'E01-windows11-workstation' $win11 'Windows 11 x64 workstation, not Windows Server'
$principal = [Security.Principal.WindowsPrincipal]([Security.Principal.WindowsIdentity]::GetCurrent())
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Add-Check 'E01-standard-user' (-not $isAdmin) 'Current account is not elevated as administrator'
$installer = [IO.Path]::GetFullPath($InstallerPath)
if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {throw 'Installer EXE missing'}
$checksum = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$signature = Get-AuthenticodeSignature -LiteralPath $installer
Add-Check 'E31-installer-hash' ($checksum.Length -eq 64) 'SHA256 computed from actual installer bytes'
Add-Check 'E01-installed-desktop' (Test-Path -LiteralPath $InstalledExe -PathType Leaf) 'HMR Desk installed as the user'
$dependencies = @{}
foreach ($name in @('python.exe','node.exe','git.exe','soffice.exe','winword.exe')) {
  $matches = @(Get-Command $name -ErrorAction SilentlyContinue)
  $dependencies[$name] = $matches.Count -gt 0
}
$runtimeAbsent = -not ($dependencies.Values | Where-Object {$_})
Add-Check 'E01-no-external-developer-runtimes' $runtimeAbsent 'No Python, Node, Git, LibreOffice or Word executable on PATH'
$paths = @(
  "$env:USERPROFILE\HMR-Desk-data",
  $SyntheticWorkspace
)
$acls = @()
foreach ($target in $paths) {
  if (-not (Test-Path -LiteralPath $target)) {continue}
  $acl = Get-Acl -LiteralPath $target
  $entries = @($acl.Access | ForEach-Object {
    @{ identity=$_.IdentityReference.Value;rights=$_.FileSystemRights.ToString();type=$_.AccessControlType.ToString() }
  })
  $acls += @{kind=($(if ($target -eq $paths[0]){'app-data'}else{'synthetic-workspace'}));access=$entries}
}
$defaultRoute = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Where-Object {$_.State -ne 'Invalid'})
Add-Check 'E27-offline-default-route-absent' ($defaultRoute.Count -eq 0) 'No usable IPv4 default route during offline acceptance recording'
Add-Check 'E26-window-acl-collected' ($acls.Count -gt 0) 'Review ACL entries; reject unauthorised broad clinical-file access'
$manifest = @{
  generated_at = (Get-Date).ToUniversalTime().ToString('o')
  purpose = 'Synthetic Windows 11 standard-user Milestone 2 acceptance evidence'
  release_decision = 'NOT APPROVED: must add clinical/visual signoff and complete full HMR E2E'
  windows = @{
    caption = $os.Caption;build=$build;architecture=$os.OSArchitecture
    workstation = ($os.ProductType -eq 1)
    account_elevated_admin = $isAdmin
  }
  installer = @{
    sha256=$checksum;bytes=(Get-Item -LiteralPath $installer).Length
    signature_status=$signature.Status.ToString()
    installed_app_present=(Test-Path -LiteralPath $InstalledExe -PathType Leaf)
  }
  external_runtimes_on_path = $dependencies
  acl_evidence = $acls
  gates = $checks
  full_synthetic_ui_e2e = 'NOT RUN: complete separate evidence checklist'
  approved_template_and_examples = 'NOT VERIFIED'
  owner_and_pharmacist_signoff = 'NOT RECORDED'
}
New-Item -ItemType Directory -Path $EvidenceDirectory -Force | Out-Null
$output = Join-Path $EvidenceDirectory 'windows11-machine-evidence.json'
$manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $output -Encoding utf8
Write-Host ('Synthetic-only Windows 11 environment inventory saved; no patient file contents read')
if (-not $win11 -or $isAdmin) {
  throw 'Acceptance environment is not a standard-user Windows 11 x64 workstation'
}
