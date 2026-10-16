# Setup and run commands

From the repository root:

```powershell
cd annotation
.\commands\setup_vlm_cuda.ps1
.\commands\run_both_cuda_pilot.ps1
.\commands\run_heldout.ps1
.\commands\evaluate_heldout.ps1
```

Run only the workflow you need; setup may install dependencies, and inference commands start model inference.
Other commands: `setup_heldout_gemini.ps1`, `run_qwen_cuda_pilot.ps1`, `run_internvl_cuda_pilot.ps1`, `run_dataset_validation.ps1`, `run_post_language.ps1`, `test_vlm_two_videos.ps1`.
Held-out launchers delegate to the preserved original workflow scripts.

Safe package check:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe -m ataraxia doctor
```

Distributed GPU setup/run commands and Windows SSH/SMB configuration are in
[the distributed guide](../docs/distributed_gpu_annotation.md).
Use `distributed.ps1 health`, `init`, `run`, `status`, `stop`, `abort`, `resume`,
and `verify-smoke`. Initialization and health checks do not start inference.
