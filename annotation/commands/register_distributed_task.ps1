[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [Parameter(Mandatory=$true)][string]$WorkerId,
    [string]$LocalRoot = (Join-Path $env:SystemDrive 'AtaraxiaWorker'),
    [string]$StateRoot = '',
    [string]$CacheRoot = '',
    [string]$UserName = '',
    [string]$TaskName = 'AtaraxiaGPUWorker'
)
$ErrorActionPreference = 'Stop'
if ($WorkerId -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid worker ID' }
. (Join-Path $PSScriptRoot 'distributed_worker_paths.ps1')
if (-not $StateRoot -and (Test-Path -LiteralPath (Join-Path $LocalRoot 'worker_paths.json'))) {
    $StateRoot = (Get-Content -LiteralPath (Join-Path $LocalRoot 'worker_paths.json') -Raw | ConvertFrom-Json).local_root
}
$paths = Get-AtaraxiaWorkerPaths -LocalRoot $LocalRoot -StateRoot $StateRoot
if ($CacheRoot) {
    if ($CacheRoot -notmatch '^[A-Za-z]:[\\/]' -or $CacheRoot.Contains('"')) { throw 'CacheRoot must be an absolute local drive path.' }
    $paths.cache = [System.IO.Path]::GetFullPath($CacheRoot)
}
$LocalRoot = $paths.installation_root
$taskPython = $paths.python
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run worker setup at this LocalRoot before registering the task.' }
New-Item -ItemType Directory -Force -Path $paths.local_root | Out-Null
New-Item -ItemType Directory -Force -Path $paths.logs | Out-Null
$bootstrap = $paths.task_bootstrap
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'commands/distributed_task_bootstrap.py') -Destination $bootstrap
# Registration is interactive ON THE WORKER. Password is handed to Task Scheduler
# in process memory, never put into a command line, config, or repository.
$credentialMessage = 'LOCAL task account: use its Windows password (not PIN). Save SMB credentials in Credential Manager for this same account first.'
if ($UserName) { $credential = Get-Credential -UserName $UserName -Message $credentialMessage }
else { $credential = Get-Credential -Message $credentialMessage }
$taskArgs = '"{0}" --root "{1}" --worker "{2}" --local-root "{3}" --cache "{4}" --logs "{5}"' -f $bootstrap,$ProjectRoot,$WorkerId,$paths.local_root,$paths.cache,$paths.logs
$action = New-ScheduledTaskAction -Execute $taskPython -Argument $taskArgs -WorkingDirectory $LocalRoot
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 24) -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Settings $settings -User $credential.UserName -Password $credential.GetNetworkCredential().Password -Force | Out-Null
$credential = $null
$registered = Get-ScheduledTask -TaskName $TaskName
if ($registered.Principal.LogonType -ne 'Password') { throw 'Task must use Password logon; S4U has no network access.' }
Write-Output "Registered $TaskName. No inference started. Verify the SSH account can run this task."
