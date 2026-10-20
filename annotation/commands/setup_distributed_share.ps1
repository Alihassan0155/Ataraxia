# Run once in elevated PowerShell on MAIN; never executed automatically.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$WorkerIdentity,
    [string]$ShareName = 'AtaraxiaAnnotation'
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$runsRoot = Join-Path $projectRoot 'runs'
New-Item -ItemType Directory -Force -Path $runsRoot | Out-Null
# Use a dedicated account/group, not Everyone or an administrator identity.
if ($WorkerIdentity -match '^(Everyone|Authenticated Users|BUILTIN\\Administrators)$') { throw 'Use a dedicated worker account/group.' }
& icacls.exe $projectRoot /grant ('{0}:(OI)(CI)RX' -f $WorkerIdentity)
if ($LASTEXITCODE -ne 0) { throw 'Read ACL failed' }
& icacls.exe $runsRoot /grant ('{0}:(OI)(CI)M' -f $WorkerIdentity)
if ($LASTEXITCODE -ne 0) { throw 'Runs ACL failed' }
Get-ChildItem -LiteralPath $projectRoot -Force -File | Where-Object { $_.Name -like '.env*' -and $_.Name -ne '.env.example' } | ForEach-Object {
    & icacls.exe $_.FullName /deny ('{0}:R' -f $WorkerIdentity)
    if ($LASTEXITCODE -ne 0) { throw 'Secret ACL failed' }
}
if (Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue) { throw 'Share already exists: inspect existing ACLs rather than replacing them.' }
New-SmbShare -Name $ShareName -Path $projectRoot -ChangeAccess $WorkerIdentity -EncryptData $true -FolderEnumerationMode AccessBased | Out-Null
New-NetFirewallRule -Name 'Ataraxia-SMB-LAN' -DisplayName 'Ataraxia SMB LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 445 -RemoteAddress LocalSubnet -Profile Private,Domain | Out-Null
Write-Output "Shared annotation as $ShareName. Check inherited/group ACLs and keep other credentials outside the share."
