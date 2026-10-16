# Three-PC GPU annotation

The main PC owns the project, data, SQLite scheduler, outputs and reports. Each Windows RTX A4000 PC owns its Python environment, CUDA driver, model cache and GPU lock. No repository copy is installed remotely. Gemini remains a separate API workflow.

The active remote deployment uses Scheduled Tasks with interactive SSH triggers
and existing environments under `D:\ALI\AtaraxiaWorker`. Follow the exact
[PC 2, PC 3 and main-PC setup commands](distributed_smb_task_setup.md) for this
deployment. The generic first-install examples below are optional alternatives;
do not reinstall the existing environments.

The controller gives each free worker a small batch (default two videos, **inference batch size remains one**). The existing Qwen/InternVL backend runs unchanged in one isolated process per assigned batch. This deliberately reloads model weights between batches; increasing scheduler batch size can amortize loading, at the cost of less responsive balancing. This is not a persistent-model service.

## Preserved inference

The frozen held-out checkpoint revisions and package versions are read from the existing config. Qwen uses NF4, 1 FPS, maximum 32 full-clip frames, 262144 pixels, 1200 output tokens and greedy generation. InternVL uses its existing native processor, NF4 language/BF16 vision, maximum 16 full-clip frames and vision microbatch one. Existing schema repair/InternVL normalization remain intact. Both keep the 15.8 GiB memory gate. Calibration is not performed by the scheduler; all saved predictions are raw. Gemini and historical evaluation are untouched.

## One-time main-PC setup

Run from `E:\ALI\Ataraxia\annotation` (replace with your checkout). Use the existing validated local CUDA environment; no reinstallation is needed on the main PC.

```powershell
Copy-Item .\configs\distributed.example.json .\configs\distributed.local.json
# In elevated PowerShell, using an existing dedicated SMB account/group:
.\commands\setup_distributed_share.ps1 -WorkerIdentity 'MAIN-PC\AtaraxiaWorker'
```

The share name is `AtaraxiaAnnotation`, so remote `root` is `\\MAIN-PC\AtaraxiaAnnotation`. The script grants project read and runs modify access, denies that identity access to the root `.env`, requires SMB encryption and opens a LAN-only firewall rule. Audit other inherited permissions and keep any other secrets outside this share. It does not create users or store passwords. Do not forward SSH/SMB ports to the internet.

Raw files referenced on other local drives are copied **on the main PC only** into each run's evidence directory. This gives the unchanged native-video backends a consistent `videos/<id>.mp4` plus `context/<id>.json` layout reachable from one share. Context bytes are copied unchanged. Original paths and SHA-256 hashes are recorded. Smoke staging is only 3–6 files; a later full run needs enough central disk space for staged videos.

## One-time remote-PC setup

Install Python 3.12 and the NVIDIA driver on each remote PC. From an authenticated local PowerShell session on each remote, use the shared scripts:

```powershell
# Elevated PowerShell for SSH setup:
& '\\MAIN-PC\AtaraxiaAnnotation\commands\setup_distributed_ssh.ps1'
# Normal worker account session with SMB access:
& '\\MAIN-PC\AtaraxiaAnnotation\commands\setup_distributed_worker.ps1' `
    -ProjectRoot '\\MAIN-PC\AtaraxiaAnnotation' -LocalRoot 'D:\AtaraxiaWorker' -InstallDependencies -DownloadModels
```

`-LocalRoot` selects the installation drive/directory (default: the system drive's `AtaraxiaWorker`). This example uses `D:\AtaraxiaWorker` for all local components:

| Component | Location |
| --- | --- |
| Python/dependencies | `D:\AtaraxiaWorker\venv` |
| Exact checkpoint cache | `D:\AtaraxiaWorker\cache\huggingface` |
| GPU/task locks | `D:\AtaraxiaWorker\state` |
| Setup/health/download logs | `D:\AtaraxiaWorker\logs` |
| Dependency manifest snapshot | `D:\AtaraxiaWorker\dependencies` |
| Optional local launchers | `D:\AtaraxiaWorker` |
| Resolved worker paths | `D:\AtaraxiaWorker\worker_paths.json` |

Package installation/environment creation happens only with `-InstallDependencies`;
model downloads happen only with `-DownloadModels`. Omit both for a checks-only
setup using an existing environment. No packages or models are installed merely
by editing the path. Create a new environment rather than moving an existing
virtual environment between drives.

All accounts on a PC must use the same state/lock directory and have Modify
access to it. Stop existing workers before switching it. To retain the old lock
location during migration, pass `-StateRoot 'C:\ProgramData\AtaraxiaWorker'`.
Task registration reads a saved custom state path from `worker_paths.json` unless
you explicitly override it. Inference stays offline after setup.

On the main PC create a passphrase-protected SSH key if you do not already have one, load it into ssh-agent, and install only its public key in the remote account's `authorized_keys`. Follow [Microsoft's Windows OpenSSH key setup](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement) for the special administrators-authorized-keys location/ACL when applicable. Verify the remote host fingerprint in an interactive connection before unattended use:

```powershell
ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\ataraxia_lan"
# Elevated PowerShell once on the controller:
Set-Service ssh-agent -StartupType Automatic
Start-Service ssh-agent
# Back in your normal account:
ssh-add "$env:USERPROFILE\.ssh\ataraxia_lan"
Get-Content "$env:USERPROFILE\.ssh\ataraxia_lan.pub"
# Install that public line on each remote before these checks:
ssh USER@GPU2 hostname
ssh USER@GPU3 hostname
```

The controller supports both key and interactive SSH authentication, with strict known-host checking in both modes. Passwords are never placed in JSON or SSH command lines.

### Interactive SSH passwords

The example and local configuration use `"ssh_auth": "interactive"` for
`saad@10.104.112.18` (gpu2) and `lab@10.104.112.9` (gpu3). Keep the installed
Python/cache/state paths accurate for each PC. Set `"ssh_auth": "key"` to restore
passwordless operation; omitted `ssh_auth` also defaults to key mode.

Interactive mode uses `BatchMode=no` and permits keys, keyboard-interactive and
password authentication. OpenSSH prompts only when authentication needs it.
Run the controller in a logged-in Windows desktop session: each remote health
check or batch opens its own SSH console window for echo-free password entry.
Enter passwords there, never in the controller/configuration. The controller
neither collects nor retains them. SSH authentication stderr stays in that
console rather than being captured in logs; backend stdout and central attempt
artifacts remain logged. On authentication failure, inspect the window as well
as the recorded transport exit code. A window may close when SSH exits.

Remote Python/PowerShell errors are redirected into captured stdout, separately
from the local OpenSSH password prompt. Health diagnostics are saved locally in
`runs/distributed_health_logs/<worker>/<probe>.json`; the health result prints
the exact `diagnostic_log` path. Missing Python, inaccessible UNC project share,
and missing worker entry script are checked before launching Python. Native
nonzero exits include `ATARAXIA_REMOTE_EXIT`; PowerShell exceptions include
`ATARAXIA_REMOTE_ERROR`. Attempt diagnostics remain in `attempts/<id>/worker.log`.
If Python exits 2, inspect its message: it can indicate a missing script or
argument parsing failure, and does not by itself establish an SSH login failure.
Ensure configured paths match the successful manual command and remote
`worker_paths.json`. The active local configuration retains the user-configured
`D:\ALI\AtaraxiaWorker` environment/state/cache paths.

Health checks, `run` and `resume` all use this option, including `ssh-task` task
triggers. Windows public-key SSH-to-SMB limitations described below still require
an actual share health check; password authentication alone does not guarantee
share access. Remote SSH must allow password authentication.

Each new SSH connection can prompt again: health, every scheduler batch, retries
and resume. Parallel windows can appear. There is no stored-password reuse or
session pooling. Answer health prompts within its 90-second timeout; job prompts
consume their existing transport/lease time budget. Never leave an interactive
run unattended expecting it to finish. Keys plus ssh-agent remain the recommended
unattended option. No timeout, inference setting or retry rule is changed.

First verify host fingerprints interactively, then run the existing six-video
smoke commands from the annotation directory:

```powershell
ssh saad@10.104.112.18 hostname
ssh lab@10.104.112.9 hostname
.\commands\distributed.ps1 health
.\commands\distributed.ps1 init -Run smoke_password_6 -Limit 6
.\commands\distributed.ps1 run -Run smoke_password_6
.\commands\distributed.ps1 status -Run smoke_password_6
.\commands\distributed.ps1 verify-smoke -Run smoke_password_6
```

These are user-run commands; changing configuration does not start inference.
Use a fresh smoke run after code changes because existing runs freeze code hashes.
Three-PC password authentication/inference still needs live validation; automated
transport tests do not establish successful remote GPU execution.

Public keys can be installed without copying the private key: on each remote
standard-user account create `$HOME\.ssh`, paste the controller's `.pub` line
into `authorized_keys`, and restrict that directory/file to the user and SYSTEM
as described in the Microsoft guide. Keep the private key only on the controller.

### Windows SSH-to-SMB authentication

An SSH public-key login does not automatically provide outbound Windows authentication to SMB. A successful interactive desktop share test alone is insufficient. Use direct `transport: "ssh"` only after its health test succeeds under the actual SSH account.

For the reliable alternative, register a task **locally on each remote PC** under an account that can access the share:

```powershell
& '\\MAIN-PC\AtaraxiaAnnotation\commands\register_distributed_task.ps1' `
    -ProjectRoot '\\MAIN-PC\AtaraxiaAnnotation' -WorkerId gpu2 -LocalRoot 'D:\AtaraxiaWorker'
# On GPU3 use -WorkerId gpu3.
```

The credential prompt passes the password to Windows Task Scheduler; no plaintext credential file is created. The account needs network access (for example a domain account, or correctly configured workgroup SMB credentials) and batch-logon rights. Verify that the SSH account can run its task with `ssh USER@GPU2 'schtasks /Run /TN AtaraxiaGPUWorker'` only AFTER a health/job inbox has been prepared. Do not select the Task Scheduler "do not store password"/S4U option, which removes network access.

Use elevated PowerShell for task registration when registering another account.

Set those worker entries to `"transport": "ssh-task"` and `"task_name": "AtaraxiaGPUWorker"`. SSH triggers the task; its authenticated Windows logon reads shared code and a central inbox. Only the tiny bootstrap launcher is copied locally, not the repository. This also avoids executing the entry script directly from UNC. If direct SSH authentication already works but a UNC script launch is blocked, `setup_distributed_worker.ps1 -LocalBootstrap` creates a tiny local `distributed_worker.py`; set `bootstrap` in that worker's config to its local path. Shared package imports are still required: application-control policies must permit the authoritative share.

If a scheduled health probe times out, inspect on the remote:

```powershell
Get-ScheduledTaskInfo -TaskName AtaraxiaGPUWorker
```

`LastTaskResult` and Task Scheduler history distinguish a failed account logon,
missing Python, and inaccessible SMB. The controller does not silently fall back
to a different account or copy the project locally.

## Configure and verify connections

Edit `configs/distributed.local.json`: actual main-PC local paths, remote hostnames/users, UNC roots, local Python/cache paths. Configure one worker per PC. Main-PC `controller_root` must be a local path; SQLite must never run over SMB. The default example's machine/account names are placeholders; its remote paths now
show `D:\AtaraxiaWorker`. After setup, copy the `python`, `local_root` and `cache`
values from that remote's `worker_paths.json` into its controller worker entry.
The existing `distributed.local.json` is not silently redirected to an uninstalled
location. If using a local bootstrap, also set `bootstrap` to
`D:/AtaraxiaWorker/distributed_worker.py`. Task registration must use the same
`-LocalRoot`. Central predictions and per-attempt inference logs still remain on
the main PC; local task receipts are additionally recorded under the selected
local `logs` directory.

```powershell
.\commands\distributed.ps1 health
```

All three results must report CUDA, RTX A4000 and distinct hostnames. This is a connection check, not an inference pass. Package/revision/evidence validation also runs inside each attempt. Run health while the controller is stopped; health probes share task inboxes with work dispatch.

Windows clocks must be synchronized (health rejects offsets over 30 seconds).
Workers refuse expired leases and independently terminate before their absolute
lease deadline, including delayed SSH/task starts.

## Smoke first: start, monitor, stop, resume

```powershell
.\commands\distributed.ps1 init -Run smoke_6 -Limit 6
.\commands\distributed.ps1 run -Run smoke_6
# A second PowerShell window:
.\commands\distributed.ps1 status -Run smoke_6
.\commands\distributed.ps1 stop -Run smoke_6    # drain current batches
.\commands\distributed.ps1 resume -Run smoke_6  # retain accepted results
.\commands\distributed.ps1 abort -Run smoke_6   # stop dispatch + kill active inference
.\commands\distributed.ps1 verify-smoke -Run smoke_6
```

The initializer reads the existing normalized `ready_metadata.csv`, requires available raw/context files, excludes original pilot/held-out IDs and IDs already present in historical or distributed predictions, and chooses the first eligible IDs in manifest order. Provide `-Manifest` for another reviewed manifest. Only `qwen` and `internvl` are accepted. Initialization alone performs no inference.

If local PowerShell script policy blocks `.ps1` launchers, the same entry point is
available without changing that policy:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\commands\distributed_entry.py status --config .\configs\distributed.local.json --run smoke_6
```

IDs reserved by another distributed run are also excluded. Resume that original
run to finish its jobs; do not create overlapping runs to bypass retry failures.

Workers are on-demand processes, not permanent services: `run`/`resume` starts them through SSH, and they exit after their batch. `stop` stops new dispatch; `abort` is checked by active workers. If the network is disconnected, their separate local deadline still exits CUDA. All failed attempts and partial raw output remain preserved. Interrupted jobs are reconciled before new jobs are assigned. Operational scheduler configuration changes (for example fixing an SSH hostname) are recorded in `scheduler_config_history/`; existing leases keep their original deadlines. Inference arguments remain frozen. Code changes within an existing run are rejected; restore its frozen version to resume.

Six videos with scheduler batches of two gives three initial batches per backend. A very uneven queue can leave a worker unrepresented; `verify-smoke` requires accepted real inference from **three distinct machine hostnames for each backend**, all jobs complete and 3–6 distinct videos. If coverage is insufficient, run a fresh smoke with a smaller scheduler batch size in a new config/run. It never labels a simulation or one-GPU test as three-GPU success.

## After successful three-GPU validation only

These commands are provided for later use; they have not been executed:

```powershell
.\commands\distributed.ps1 init -Run full_gpu_v1 -Limit 0 -SmokeRun smoke_6
.\commands\distributed.ps1 run -Run full_gpu_v1
```

`-Limit 0` means all remaining IDs and requires successful three-GPU smoke proof with identical source hashes. Full annotation still requires your research/deployment approval. Existing IDs are excluded conservatively even when only one previous model annotated them; review that exclusion before preparing any later model-specific backfill. The scheduler does not reuse incompatible historical labels as new deployment results.

## Checkpoints, logs and failure handling

Everything is in `runs/distributed/<run>/`:

- `frozen.json`: code hashes, input hashes, model revisions/arguments/package versions.
- `scheduler.sqlite`: sole authoritative job state; one main-PC controller, unique `(model, video_id)` key.
- `progress.json`, `worker_health.json`, `failures.json`: monitoring and failures.
- `attempts/<uuid>/`: request, metadata subset, heartbeats, process logs, raw backend responses, original outputs, receipt and transport exit.
- `results/<model>/annotations.jsonl`: atomic controller-only export of accepted results, with machine/attempt provenance.
- `smoke_validation.json`: verified GPU/machine coverage.

SQLite commits precede dispatch. On restart, existing attempts wait for a receipt or their deadline plus grace; an SSH disconnect alone never requeues a live lease. A per-machine OS lock prevents simultaneous distributed CUDA jobs, including orphan attempts. No worker appends to aggregate JSONL. Partial valid results are accepted individually; only missing/invalid jobs retry, up to the configured attempt count. Memory-gate failures remain failures even if the model produced JSON. Exhausted jobs remain visible; retries are never silently reset. Preserve the SQLite database with its WAL when backing up a live run, or stop the controller before copying it.

Do not start legacy GPU inference manually on a worker while this scheduler owns that GPU. The lock coordinates distributed workers, not unrelated applications. Job deadlines cover model load and the whole assigned batch; batch size affects worst-case recovery latency. Accepted annotations within a batch are published once its receipt or deadline is available.
