# Interactive SSH transport validation

Validated 2026-10-12 without network connections, downloads or real model inference.

- All 15 distributed automated tests pass, including existing scheduler/lease/result tests.
- New tests check key-mode compatibility, interactive authentication arguments for both SSH transports, strict host-key checking, isolated-console launch options, uncaptured password-prompt streams, health JSON parsing and authentication-error reporting.
- Remote entries in example/local configuration use `ssh_auth: interactive` for saad@10.104.112.18 and lab@10.104.112.9. Installed environment/cache/state paths are preserved in local configuration.
- No passwords are collected by Python, passed as arguments, or persisted. Native Windows OpenSSH handles interactive input. Backend stdout is still captured; interactive SSH stderr is visible only in its console.
- Inference, calibration, batch/lease/retry rules and research outputs are unchanged.

Live password entry and successful three-GPU inference remain unverified. Run health and a fresh six-video smoke from a Windows desktop after SMB/SSH setup. Every new remote connection may require password entry; unattended completion requires key authentication. Existing runs reject changed source hashes, so use a new smoke run rather than modifying a frozen run.
