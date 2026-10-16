# Run once in elevated PowerShell on EACH remote PC.
$ErrorActionPreference = 'Stop'
$capability = Get-WindowsCapability -Online -Name 'OpenSSH.Server*'
if ($capability.State -ne 'Installed') {
    Add-WindowsCapability -Online -Name $capability.Name | Out-Null
}
Set-Service sshd -StartupType Automatic
Start-Service sshd
$rule = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
if ($rule) {
    Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -RemoteAddress LocalSubnet -Profile Private,Domain -Enabled True
} else {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH LAN' -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -RemoteAddress LocalSubnet -Profile Private,Domain | Out-Null
}
Write-Output 'SSH enabled for the LAN. Install the controller public key for the dedicated worker account and verify the host fingerprint.'
