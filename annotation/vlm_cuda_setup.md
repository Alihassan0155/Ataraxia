# Qwen and InternVL Windows CUDA setup

From `E:\ALI\Ataraxia` in PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_vlm_cuda.ps1 -DownloadWeights
powershell -NoProfile -ExecutionPolicy Bypass -File .\test_vlm_two_videos.ps1 -Offline
```

The execution-policy override is process-only. Setup reuses/creates `.venv-qwen-cuda`, installs the pinned CUDA 12.8 PyTorch stack and inference dependencies, checks CUDA/imports, and optionally downloads checkpoints into `.cache/huggingface`. Downloads are resumable; existing Qwen weights are reused. Change the interpreter if necessary with `-Python 'C:\path\to\python.exe'`. Environment setup alone omits `-DownloadWeights`; an online smoke run can download missing weights when `-Offline` is omitted.

Models are `Qwen/Qwen3-VL-8B-Instruct` and **`OpenGVLab/InternVL3_5-8B-HF`**, the official HF-format InternVL3.5-8B checkpoint. This explicitly uses the HF format rather than the custom-code format or its separate Instruct/Pretrained variants. Source: [official model card](https://huggingface.co/OpenGVLab/InternVL3_5-8B-HF). Native Transformers classes are used without enabling remote Python code execution. The corrected native processor passed both-video preflight. GPU generation was attempted but stopped at about 15.65 GiB total device memory, above the 15 GiB gate; completed InternVL annotation remains unverified.

The smoke script runs Qwen then InternVL in separate subprocesses on the **same two original pilot videos**: `FV000662` (19 seconds) and `FV000012` (23 seconds). Each uses 1 FPS across the full clip, batch 1, greedy generation (effective temperature 0), a 1,200-new-token ceiling, and the original transcript/eGeMAPS/caption context. Qwen retains native-video input with the configured pixel ceiling; InternVL uses its own native-video chat-template processor and uniform 1 FPS sampler, with processor options passed through `processor_kwargs`. The checkpoint video default of 384 pixels conflicts with its 14-pixel patches and 0.5 downsampling; frames therefore use the model-configured 448?448 size, giving a 32?32 patch grid and 256 visual tokens per frame. PyAV provides decoding while InternVL owns sampling, resizing and normalization. Its processor uses its own required image geometry, which is recorded rather than asserted identical to Qwen's.

Both use bitsandbytes NF4. InternVL retains its vision tower/projector at BF16 and quantizes the remaining eligible layers. Checkpoint revisions, packages, frame/token counts, timing, memory, raw answers, validation errors, and at most one schema-repair answer are preserved. Invalid emotion distributions are not silently normalized. Passing includes a 15 GiB observed total-device-memory gate. Two short videos are an integration test, not validation of longest-clip VRAM or affective accuracy.

New CUDA runs use rubric `v1.1-points10`: the model must allocate exactly **10.00 points** across the eight emotion scores, each between 0 and 10 with at most two decimal places. Wrong totals, missing/extra keys, nonnumeric values, and out-of-range scores are rejected. Saved `emotion_points` preserves that allocation; `emotions` stores those valid points divided by 10 for existing probability-based evaluation. Other scalar scales remain unchanged. One schema repair is still permitted when a model violates the rule; prompt instructions are not constrained decoding. Historical annotations/rubric remain unchanged. Use a fresh run directory after this scale/version change.

Each invocation gets a fresh timestamped directory under `outputs/vlm_smoke/`. Inspect `summary.json` and each model's `smoke/status.json`, `annotations.jsonl`, `raw_responses.jsonl`, and optional failure/validation logs. Model loading errors also appear in the terminal and yield a failing summary. Historical outputs are untouched.

Input validation without loading weights or running inference:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\test_vlm_two_videos.ps1 -PreflightOnly -Offline
```

Choose another pair, or resume the same frozen test configuration:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\test_vlm_two_videos.ps1 -VideoIds 'FV000662,FV000012' -RunDir 'outputs/vlm_smoke/my_test' -Offline
```

Changing settings or IDs requires a fresh directory. For reproducibility, `-DownloadWeights` writes checkpoint revisions under `.cache/huggingface/vlm_revisions.json`, and individual runners preserve the resolved revision in their run artifacts. Model downloads/inference are only performed when you execute the corresponding scripts.

InternVL-only rerun after the processor fix (Qwen need not be rerun):

```powershell
$env:HF_HOME = "$PWD/.cache/huggingface"
.\.venv-qwen-cuda\Scripts\python.exe src/annotate_internvl_cuda.py --run-dir outputs/vlm_smoke/internvl_native_fix/internvl --offline
```

Use `--preflight` with that command to validate processed frame geometry and visual token counts without loading weights.

InternVL memory handling: vision encoding uses microbatches of one frame, concatenated in original order before the joint language-model pass. This vision encoder has no cross-frame attention; small batch-dependent numerical differences remain possible. `--max-frames 16` additionally caps uniform full-clip sampling through InternVL's own sampler. The cap changes effective FPS and is recorded separately from the requested 1 FPS. Use a fresh run directory when changing it.

Run both models on the complete 50-video pilot:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_both_cuda_pilot.ps1
```

Results default to `pilot_50_reels_30h/results/pilot50_cuda_nf4_fps1_intern16_v1/`, with separate `qwen/pilot/` and `internvl/pilot/` annotations, console logs and final summary. Repeating the command resumes validated outputs and retries missing IDs. Preflight checks all media and shared evidence before loading weights. The research run explicitly allows Qwen to start before long-video benchmark headroom passes; it does not certify deployment feasibility. Both models continue after individual video errors. InternVL caps at 16 uniform full-clip frames; Qwen retains its original uncapped 1 FPS configuration. Memory failures remain visible even when annotations complete. A two-hour completion time is not guaranteed. Leave the machine awake and terminal open. Use `-PreflightOnly` for checks without inference.
