# Ataraxia held-out 50-video validation

User-authorized v3 amendment: after an initial InternVL generation plus **two repair attempts**, a remaining incorrect positive emotion total is proportionally normalized to 10.00. Largest-remainder rounding allocates exactly 1,000 hundredths across the eight emotions. Original responses/scores are retained; normalization and any derived dominant-label change are explicitly recorded in `normalization_events.jsonl` and each annotation's `run_metadata.emotion_normalization`. Other invalid fields, all-zero vectors, missing emotions, negative/non-finite/out-of-range scores and mismatched IDs still fail. Existing successful predictions are not rewritten. This is a declared post-failure policy amendment, not the original frozen pilot policy.

Reliability amendment (2026-10-10): Gemini now logs upload/processing/generation/validation stages, gives a heartbeat every 15 seconds, bounds SDK requests (120 seconds; generation 180 seconds), bounds processing polling (180 seconds), and enforces a hard 600-second per-video deadline in a child process. A stalled child is terminated; saved predictions remain available. Detailed progress is in `predictions/gemini/events.jsonl` and `current_video.json`. InternVL permits up to three arithmetic-assisted schema repairs, keeping strict total 10.00 and preserving every raw response. These are recorded in `config/reliability_amendment_v2.json`; earlier predictions and the original freeze manifest are preserved. This is a declared operational protocol change, not unchanged frozen inference. Calibration and original pilot files remain unchanged.

This folder is isolated from the original pilot. It reuses the existing fixed selection under `held out/merged_50/`, copies its 50 videos and normalized preprocessing contexts, and freezes local copies of the working pipelines. Original pilot annotations, scripts and reports are untouched. No full-dataset annotation is started.

From `E:\ALI\Ataraxia`, run:

```powershell
# One-time Gemini SDK setup; recorded package versions, separate environment.
.\heldout_50_evaluation\setup_gemini.ps1

# Resumable inference: Qwen -> InternVL -> Gemini, separate processes.
.\heldout_50_evaluation\run_all.ps1

# After all three independent humans have completed their templates:
.\heldout_50_evaluation\evaluate.ps1
```

Optional decoder/processor preflight without inference:

```powershell
.\heldout_50_evaluation\run_all.ps1 -PreflightOnly
```

Gemini reads the existing project `.env` through the existing key-loader. Credentials are not copied into this folder or the freeze. Setup needs package-download access and the exact historical SDK/package versions to be available; it fails explicitly if they cannot be installed. Qwen and InternVL use the existing `.venv-qwen-cuda` and cached weights. No model/API requests were made while preparing this workflow.

## Frozen development policy

`config/frozen_config.json` records checkpoints, prospective immutable cached HF revisions, original pipeline settings, calibration/evaluation policy, bootstrap seed, and explicit gaps. `config/pilot_calibration_and_selection.json` preserves the original three-human pilot parameters for **all three models**, including Qwen. No held-out fit or calibration-method selection occurs. Candidate scalar calibrators are not re-tested/tuned on held-out labels; only the retained pilot policy is applied.

Qwen: NF4, 1 FPS capped at 32 uniformly spaced full-clip frames, 262144 max pixels, total-pixel argument 0, greedy 1200 tokens, batch 1. InternVL: NF4 language weights, BF16 vision/projector, 1 FPS capped at 16 uniform full-clip frames, native 448x448 processor, vision microbatch 1, greedy 1200 tokens, batch 1. Device-memory gate is 15.8 GiB for both; gate failures remain logged rather than changing resolution/sampling automatically.

Gemini reuses the exact historical checkpoint identifier, prompt v1.0, existing Interactions API/video request and schema. Its immutable provider revision, sampling, and generation defaults were not recorded historically. They remain unknown; this cannot be claimed to exactly reproduce the historical provider state. The full provider response and SDK version are recorded for new successful requests. CUDA prompt version is v1.1-points10. All instantiated held-out prompts are under `prompts/`; shared contexts are under `context/`. Native modality access differs: Gemini has direct audio; CUDA models use transcript/eGeMAPS/caption context.

`config/freeze_manifest.json` hashes the frozen scripts, metadata, calibration, prompts, videos and contexts. A changed/missing frozen file stops resume/evaluation. Prospective cached revisions are pinned; their identity does not recover the previously unlogged pilot revision. Hash checks enforce ID and exact-byte separation, not creator/repost/near-duplicate independence. These limitations are carried into the final report.

## Independent human annotations

Complete these files separately:

- `human_annotations/ghayas/annotations.csv`
- `human_annotations/zara/annotations.csv`
- `human_annotations/ali/annotations.csv`

Each template already has exactly the selected 50 IDs. Their `video_list.csv` files link the matching raw videos. Give each annotator only their own template/list, the videos and `human_annotations/annotation_rules.txt`; keep model predictions and other annotators' labels hidden until submission. Independence/blindness cannot be proven by a CSV and must be documented by the researcher.

Human valence, arousal and recovery use 0–10. All eight emotion scores must be finite 0–10 and sum exactly to 10; dominant emotion must be a canonical maximum-score label. Confidence/notes are optional for evaluation. Do not guess ID corrections or silently normalize invalid totals. Original submitted values are preserved in the reference exports. Invalid/missing affect fields halt final evaluation and produce `reports/input_status.json` with the exact issues.

Once all 150 annotator-video records validate, the soft reference averages the three scalar labels and probability vectors. Scalar uncertainty is mean pairwise absolute difference; emotion uncertainty is mean pairwise TV/JSD. Declared dominant agreement, all ties and the separate pooled-distribution dominant are retained. Overall uncertainty averages three scalar differences divided by 10 and pairwise TV. Low/medium/high cutpoints are frozen from the original pilot; held-out quantiles are not used to choose a policy.

## Resume and outputs

Validated existing prediction IDs are skipped. Fully complete models are skipped before loading weights. Partial trailing JSONL writes are preserved in a recovery log before resuming. Model/schema failures, schema repairs, memory gates and process exits remain recorded. Processes run sequentially so one GPU model is released before the next starts. Individual model failures do not skip later models; a nonzero master exit reports failure and the same command resumes incomplete work. No automatic model/sampling/SDK changes occur.

Raw outputs stay in `predictions/qwen/pilot/`, `predictions/internvl/pilot/` and `predictions/gemini/`. Calibrated copies go to `calibrated/`. Logs and durable master events/status are under `logs/` and `checkpoints/`.

When inputs are complete, `reports/` receives:

- `human_soft_reference.csv/json`, `human_pairwise_agreement.csv`
- `raw_vs_calibrated_metrics.csv`, `uncertainty_stratified_metrics.csv`
- `metric_confidence_intervals.csv`, `paired_bootstrap_differences.csv`
- `per_video_errors.csv`, `model_ranking.csv`
- `final_model_selection.json`, `final_heldout_report.md`

Metrics include scalar MAE/RMSE/Pearson/Spearman/signed bias, emotion TV/JSD, and dominant agreement per human and pooled/tie-aware label. Five thousand paired video-level bootstrap draws provide percentile 95% intervals with identical sampled IDs across models/variants. Calibrators are fixed and never refitted. Degenerate correlation draws are omitted and counted. No multiple-comparison significance claim or equivalence claim is made.

Ranking uses the original pilot's criterion weights and exports individual metrics. If a fixed uncertainty bin has no videos, its unavailable criterion is omitted and the remaining frozen weights are renormalized, explicitly recorded. A nominal best-two recommendation reports paired intervals containing zero as inconclusive. This validates frozen pilot candidates; selecting/reselecting models from these same held-out results still introduces selection optimism. No automatic full-dataset run follows evaluation.

Key failover amendment v4: retry the same video on the next configured key after a quota/authentication error or a hard 180-second key-attempt timeout, within a 600-second overall video budget. Disabled keys are skipped. Schema errors are not treated as quota errors. Completed predictions are preserved. Keys in the same provider project can share quotas; switching keys does not guarantee additional capacity. Restart the runner to activate this change.
