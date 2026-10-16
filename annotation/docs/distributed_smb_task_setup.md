# Scheduled-task SMB setup for the three PCs

The remote entries now use `transport: ssh-task`, `ssh_auth: interactive` and
task name `AtaraxiaGPUWorker`. SSH starts only `schtasks /Run`; it never checks
or opens the project share. The task runs a tiny local launcher under a password
logon with network access, imports authoritative code from the share and reads
the controller's inbox. The GPU settings, batching, leases, retries, checkpoints,
and inference are unchanged. Gemini stays separate.

No setup, downloads or annotation have been executed by this change.

**Live setup finding:** PC 3 authenticated successfully through SSH, but Windows
returned `CMDKEY: Credentials cannot be saved from this logon session.` Do not
run credential storage over SSH on these PCs. Open a local desktop or RDP session
as the actual task account (`saad` on PC 2, `lab` on PC 3), and run the credential
and registration commands below there. Merely running `net use` in one SSH
session does not create the persistent task-account credential needed here.
Do not weaken Windows policy or put the password in command arguments to bypass
this restriction. After local registration, the controller can trigger the tasks
through SSH normally.

## PC 2: DESKTOP-RM0MQ8B, account saad

Log in locally as `DESKTOP-RM0MQ8B\saad`. Store the MAIN PC's existing SMB account
credential in this same user's Windows Credential Manager. Use the account that
already worked with manual `net use`; do not substitute the remote PC's account
unless the main PC recognizes it.

```powershell
$smbAccount = Read-Host 'Main-PC SMB username used in the successful net use (LAB12-PC47\username)'
cmdkey.exe /add:LAB12-PC47 /user:$smbAccount
# Enter the SMB password at cmdkey's prompt; never add /pass:password.
Get-Item '\\LAB12-PC47\AtaraxiaAnnotation\commands\register_distributed_task.ps1'
Test-Path 'D:\ALI\AtaraxiaWorker\venv\Scripts\python.exe'
```

Then in PowerShell elevated as the SAME saad account, register the task. The
credential dialog asks for **saad's local Windows login password**, separately
from the saved MAIN PC SMB password. Do not use a Windows Hello PIN.

```powershell
& '\\LAB12-PC47\AtaraxiaAnnotation\commands\register_distributed_task.ps1' `
  -ProjectRoot '\\LAB12-PC47\AtaraxiaAnnotation' -WorkerId gpu2 `
  -LocalRoot 'D:\ALI\AtaraxiaWorker' -StateRoot 'D:\ALI\AtaraxiaWorker' `
  -CacheRoot 'D:\ALI\AtaraxiaWorker\cache\hub' `
  -UserName 'DESKTOP-RM0MQ8B\saad'
Get-ScheduledTask -TaskName AtaraxiaGPUWorker | Select-Object TaskName,State,Principal
```

## PC 3: LAB12-PC08, account lab

Log in locally as `LAB12-PC08\lab` and store the main-PC credential for that user:

```powershell
$smbAccount = Read-Host 'Main-PC SMB username used in the successful net use (LAB12-PC47\username)'
cmdkey.exe /add:LAB12-PC47 /user:$smbAccount
Get-Item '\\LAB12-PC47\AtaraxiaAnnotation\commands\register_distributed_task.ps1'
Test-Path 'D:\ALI\AtaraxiaWorker\venv\Scripts\python.exe'
```

In PowerShell elevated as the SAME lab account:

```powershell
& '\\LAB12-PC47\AtaraxiaAnnotation\commands\register_distributed_task.ps1' `
  -ProjectRoot '\\LAB12-PC47\AtaraxiaAnnotation' -WorkerId gpu3 `
  -LocalRoot 'D:\ALI\AtaraxiaWorker' -StateRoot 'D:\ALI\AtaraxiaWorker' `
  -CacheRoot 'D:\ALI\AtaraxiaWorker\cache\hub' `
  -UserName 'LAB12-PC08\lab'
Get-ScheduledTask -TaskName AtaraxiaGPUWorker | Select-Object TaskName,State,Principal
```

Both tasks use the existing local Python environment, state directory and
`cache\hub` HF_HOME from the current local configuration; nothing is moved or
redownloaded. `CacheRoot` is the HF_HOME base already configured, not necessarily
the Hugging Face cache's nested `hub` directory. Keep it identical to the working
environment. These explicit overrides prevent silently changing a populated
cache or GPU lock directory. Task registration copies only the tiny launcher.

Windows securely stores credentials for Task Scheduler and Credential Manager;
none are stored in the repository/configuration/logs. Registration verifies
Password logon: S4U has no network access. See Microsoft's
[cmdkey documentation](https://learn.microsoft.com/windows-server/administration/windows-commands/cmdkey)
and [task logon types](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskfolder-registertask).
If enterprise policy prevents stored credentials or batch logon, have the
administrator provide an approved network-capable task account; do not weaken
policy. After password changes, refresh the corresponding Windows credential
and task registration. Credential storage must be under the TASK account's
profile, even when setup is elevated. Do not delete other SMB connections or
replace existing share ACLs to hide an account mismatch.

## Main PC: LAB12-PC47

The existing share is retained. In elevated PowerShell inspect it; the stored
SMB identity needs share Change access, project NTFS Read/Execute and `runs`
Modify access. Keep secrets denied as in the original share setup.

```powershell
Get-SmbShare -Name AtaraxiaAnnotation | Select-Object Name,Path,EncryptData
Get-SmbShareAccess -Name AtaraxiaAnnotation
```

In normal PowerShell, from the project root (Python entry point avoids local
PowerShell script execution-policy restrictions):

```powershell
Set-Location 'E:\ALI\Ataraxia'
& .\annotation\.venv-qwen-cuda\Scripts\python.exe .\annotation\commands\distributed_entry.py health --config .\annotation\configs\distributed.local.json
# Only after all three workers report healthy/distinct RTX A4000 PCs:
& .\annotation\.venv-qwen-cuda\Scripts\python.exe .\annotation\commands\distributed_entry.py init --config .\annotation\configs\distributed.local.json --run smoke_task_6 --limit 6
& .\annotation\.venv-qwen-cuda\Scripts\python.exe .\annotation\commands\distributed_entry.py run --config .\annotation\configs\distributed.local.json --run smoke_task_6
& .\annotation\.venv-qwen-cuda\Scripts\python.exe .\annotation\commands\distributed_entry.py verify-smoke --config .\annotation\configs\distributed.local.json --run smoke_task_6
```

Monitor/resume from another main-PC terminal:

```powershell
& .\annotation\.venv-qwen-cuda\Scripts\python.exe .\annotation\commands\distributed_entry.py status --config .\annotation\configs\distributed.local.json --run smoke_task_6
& .\annotation\.venv-qwen-cuda\Scripts\python.exe .\annotation\commands\distributed_entry.py resume --config .\annotation\configs\distributed.local.json --run smoke_task_6
```

Use a new smoke name if it already exists with older frozen code. Verify-smoke
still requires accepted real inference on three distinct PCs for each backend.
No full run should start until this passes.

SSH passwords can still be requested at each task trigger; this removes repeated
SMB authentication, not repeated SSH authentication. Interactive SSH still
requires an attended desktop. Task Scheduler provides network-capable account
logon on every launch rather than keeping an SSH session alive.

If health times out, inspect remotely:

```powershell
Get-ScheduledTaskInfo -TaskName AtaraxiaGPUWorker
Get-Content 'D:\ALI\AtaraxiaWorker\logs\last_dispatch.json'
```

The local file records share/import/health failures even if the task cannot write
back to the main PC. SSH trigger success alone is not a successful worker run.
Central probe diagnostics remain in `annotation/runs/distributed_health_logs/`.

## Validation

20 distributed tests pass, including task-trigger isolation from UNC, diagnostic
logging without share access, key/password compatibility, and scheduler safety
tests. All distributed PowerShell launchers pass static parsing. Actual task
registration, stored-credential access and three-GPU inference require the
user-run commands above; they have not been represented as already passing.
