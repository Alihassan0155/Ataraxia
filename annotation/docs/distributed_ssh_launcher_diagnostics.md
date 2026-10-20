# SSH launcher diagnostics validation

The previous interactive launcher intentionally left SSH stderr uncaptured to
protect console password entry. This also hid remote Python diagnostics when
the SSH window closed. The updated encoded remote PowerShell wrapper captures
remote errors through stdout while leaving local OpenSSH prompts on its console.
It validates the configured Python, UNC project root and entry script, reports
PowerShell exceptions and native exit codes, and preserves inference arguments.

Health probes persist return codes and captured remote diagnostics under
`runs/distributed_health_logs/`, including timeout/transport errors. Passwords
are never read by the controller or passed through these captured streams.
Failed SSH authentication diagnostics remain console-only.

All 17 distributed tests pass, including new quoted/apostrophe-path checks and
exit-2 diagnostic persistence. No remote connections, inference or downloads
were started. The specific cause of the users' remote exit 2 cannot be established
from the exit code alone; the next health probe now reports missing paths,
Python argparse errors or share-access errors rather than hiding them. Live
three-PC validation remains pending.

From the project root, retry only the health probe:

```powershell
& .\annotation\.venv-qwen-cuda\Scripts\python.exe .\annotation\commands\distributed_entry.py health --config .\annotation\configs\distributed.local.json
```

This Python entry point avoids the local PowerShell script execution-policy
restriction. It opens interactive SSH consoles when authentication is needed.
