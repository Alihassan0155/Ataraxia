# Ataraxia normalization, preprocessing, and annotation plan

Created: 2026-10-05. Status: implementation plan; the new collections have not yet been processed or annotated.

## Objective

Study-design update (2026-10-06): evaluate **Gemini, Qwen3-VL-8B-Instruct, and InternVL3.5-8B** on the same blind human-labeled 50-video pilot, select two using predefined criteria, then run the selected pair on the eligible full dataset. Molmo remains excluded. The approximately 4,000-video total is a target, not a verified eligible/local count.

Bring FineVideo, the new TikTok collection, and the new YouTube collection into one consistent dataset interface. Apply the same evidence preparation and annotation rubric to eligible videos while preserving source metadata, audit history, and completed FineVideo artifacts.

Normalization means consistent IDs, metadata fields, paths, eligibility decisions, evidence bundles, and annotation records. It does not require resizing every video, renaming original files, changing frame rates, or making category proportions equal across sources. Keep native videos for model input and derive a standard audio representation for preprocessing.

## Starting point

| Collection | Metadata | Local video availability | Evidence/annotation state |
|---|---:|---|---|
| FineVideo | 858 | Source media absent in this Windows copy | 858 transcripts and contexts; 50 pilot annotations from each model |
| TikTok `fyp_videos_1250` | 1,250 | All 1,250 present under `videos/videos/` | No language audit or shared contexts |
| YouTube `yt_shorts_master` | 760 | 136 present; 624 missing | No language audit or shared contexts |

FineVideo's saved final preprocessing run reports zero failures. Its original audio is also absent locally. Preserve existing artifacts; restoration is needed for playback, human labeling, or new inference, rather than automatic reprocessing.

The two new folders contain 1,386 local candidate videos. The final eligible count will be lower or equal after language, media, and duplicate checks. Do not count all 2,010 metadata rows as available study videos.

YouTube has 307 records without category/split labels, including 83 of its local videos. Four YouTube source IDs overlap the existing YouTube metadata. TikTok country labels do not verify spoken language, and its country/source/category composition is confounded. See `data/new_dataset_analysis.md` for the inventory.

## 1. Normalize metadata and establish stable identities

Implement a source adapter for each CSV and write derived manifests under `data/normalized/`. Keep originals in place.

| Canonical field | Rule |
|---|---|
| `assigned_id` | Keep existing `FV...` IDs; use `TT_<original_id>` for TikTok and `YT_<video_id>` for YouTube |
| `source_id`, `platform`, `source_dataset` | Preserve original identity, platform, and dataset provenance |
| `source_manifest`, `source_file_path` | Preserve original CSV location and path value |
| `file_path` | Project-relative path to the actual native video; resolve against project root |
| `source_url` | Preserve the original URL; use parsed platform ID for identity matching |
| `category_original`, `category` | Retain source label; map to a documented common taxonomy |
| `title`, `description`, `metadata_caption` | UTF-8 strings; TikTok `desc` maps to description/caption; YouTube title is auxiliary caption evidence |
| `country`, `creator_id`, `creator_name` | Optional metadata; never convert country into a speech-language label |
| `duration`, `display_width`, `display_height`, `orientation` | Measured values after media probing; keep reported metadata values separately |
| `language`, `language_status` | Unknown until audio audit; never populate from country or metadata guesses |
| `split_original`, `split` | Preserve source split; record the derived study split separately |
| `media_status`, `selection_status`, `exclusion_reason` | Explicit states, including missing, pending, eligible, excluded, and review |
| `media_sha256`, `duplicate_group` | Track identical content and canonical representatives |

Read platform IDs as strings to avoid numeric precision loss for long TikTok IDs. Namespaced IDs must be deterministic and must not change when rows are reordered. Existing historical `YT...` assigned IDs need an alias mapping to platform identities rather than wholesale renaming.

Resolve TikTok paths to `data/fyp_videos_1250/videos/videos/<id>.mp4` and YouTube paths to `data/yt_shorts_master/videos/<id>.mp4`. Preserve YouTube's old `raw/` paths in provenance. Missing files remain inventory rows and cannot enter the processing queue.

Use `unmapped` for unresolved categories. A first mapping should be conservative: do not silently equate source-specific categories with broad affective labels. Category/country/view count/split metadata should stay outside the model evidence block unless explicitly part of a versioned study design.

Outputs: `inventory.csv`, `id_aliases.csv`, `category_mapping.csv`, and a validation summary. Done when all 2,010 new rows have stable identities and availability states, and all 1,386 local candidates resolve correctly. Add FineVideo and existing YouTube provenance through adapters without changing historical records.

## 2. Audit media and duplicate content

Probe each local video for decodability, actual duration, rotation-aware display dimensions, frame rate, and audio streams. Record failures and mismatches rather than overwriting source metadata. Run a decode check where the probe alone cannot establish integrity.

Classify vertical, horizontal, square, and unknown separately. Do not assume every TikTok is vertical. The YouTube metadata reports 758 vertical and two square videos, but this must be checked against available media.

Deduplicate platform IDs across manifests first, then compute file hashes for local content. Identical bytes are duplicates; different hashes do not rule out re-encoded or reposted content. Flag likely reposts for later review and keep duplicate groups together in study splits. Preserve every source record and select one representative in the derived dataset.

Outputs: `audit/media_manifest.csv`, `audit/duplicate_manifest.csv`, resumable status, and failure records. Done when every local candidate has a measured media state and an explicit duplicate decision.

## 3. Prepare reusable audio and verify spoken language

Reuse the existing audio recipe: complete-video mono, 16 kHz, PCM signed 16-bit WAV. Extract once and reuse the same audio for language auditing, transcription, and acoustic analysis.

Audit speech using the audio, not captions, countries, hashtags, or uploader identity. The current FineVideo language auditor examines an initial Whisper window; extend it for the new collection to inspect speech across the clip, especially where an opening contains only music or another language.

Store detected language, supporting speech intervals, detector scores, model/backend version, and review decision. Treat detector scores as model outputs, not established correctness probabilities. Explicitly distinguish:

- Confirmed target speech: English, Urdu, or Hindi.
- Confirmed non-target speech: exclude from the selected study manifest, retaining originals and audit records.
- Mixed language, uncertain detection, or ambiguous Hindi/Urdu: review; do not silently force a label.
- No speech, no audio stream, silence, and extraction/detection failure: separate states.

For the first expansion, leave genuinely speechless clips pending a documented eligibility decision. They may be useful affective examples, but cannot be called English/Urdu/Hindi-verified. Silence must not be treated as failed transcription, and failed transcription must not be accepted as silence.

Output: `audit/language_manifest.csv` and review queue. Done when every processable candidate is target-language eligible, explicitly excluded, or held for review. Reuse ASR results if this stage produces full transcripts, rather than transcribing twice.

## 4. Freeze a selected dataset manifest

Combine media, identity, language, and category decisions into `selected_metadata.csv`. Keep unavailable and excluded rows in the inventory/audits.

Enforce horizontal fraction <= 30% on the final eligible combined dataset, preserving category proportions as closely as practical. This is a maximum, not a requirement to manufacture 30% horizontal content. Report counts for all orientations and use the selected dataset as the documented denominator. Never resize or crop content merely to satisfy this constraint.

Record a selection version, seed, source composition, language composition, category composition, inclusion/exclusion reasons, and duplicate handling. Report the 136-video YouTube subset's uneven category coverage; do not describe it as representative of all 760 rows. Missing videos can be restored/downloaded in a later batch without blocking eligible local videos.

Preserve the original 50-video pilot as a fixed evaluation cohort. Retain existing YouTube splits where suitable, inspect creator/duplicate overlap across the combined dataset, and group related items when assigning new splits. Keep development and evaluation sets independent.

Done when every selected video is locally available, decodable, language-approved, uniquely represented, and has a traceable selection decision.

## 5. Generate the same shared evidence bundles

Generalize `src/preprocess_full_dataset.py` into a source-independent, resumable processor. It already accepts metadata/video/output paths and supplies the essential recipe; adapt it rather than creating separate pipelines with different behavior for each source.

For each selected video:

1. Reuse/extract canonical audio.
2. Produce original-language Whisper speech text; retain segment timestamps and language results in a sidecar. Do not translate Hindi/Urdu into English by default.
3. Calculate openSMILE eGeMAPSv02 Functionals and the same six summary fields: `mean_loudness`, `loudness_variability`, `mean_pitch`, `pitch_variability`, `spectral_flux`, and `sound_level_db`.
4. Write the compatible context fields: `video_id`, `transcript`, `acoustic_features`, `metadata_caption`, and `caption_priority: low`.
5. Add explicit extraction/ASR/acoustic status and provenance, including media hash, context schema version, preprocessing configuration, tool/model versions, and creation time.

Keep feature definitions and units consistent: mean pitch is derived from the existing semitone feature, not automatically Hz. Missing acoustic values must be null with a reason, not invented zeros. Retain native summary units; statistical scaling is unnecessary for model context. If a later downstream model needs scaling, fit it on its training split and preserve raw features.

The current caption detector does not recognize TikTok `desc`; normalized `metadata_caption` must be read explicitly or mapped into a recognized field. Prefer an explicit caption choice per row over a global first-matching column, and handle missing values as empty strings.

For silent/audio-absent clips approved by a later policy, contexts must express missing modalities honestly. Update `common_annotation.py` to consume explicit evidence status; its current boolean presence checks cannot distinguish a populated null-feature dictionary from successful acoustic extraction.

Cache validity must include video hash, schema/configuration, and backend/model version. Existing code checks only a few structural fields and counts JSON files, so it can reuse stale contexts or overstate valid completion. Record pending/running/succeeded/review/failed per stage; write atomically and retry only failed stages. Never use `--force` for a routine resume.

Outputs: `preprocessed/audio/`, `transcripts/`, `asr/`, `context/`, stage status, and failure log. Done when every selected video has a validated context, or an explicit unresolved failure that keeps it out of annotation.

## 6. Validate a small batch before processing everything

First run a deliberately varied batch of about 10–20 local candidates across both sources, including target languages, music/no-speech examples, short/long durations, missing captions, and available orientation variants. Eligibility checks still apply before annotation.

Check ID/path matching, actual playback, audio extraction, transcript fidelity with language-competent review, feature availability, caption priority, context completeness, and failure handling. Interrupt/resume the batch to verify that valid work is reused and failed work is visible.

Once the batch passes, preprocess the eligible local dataset. Report valid completed contexts rather than files present. Do not regenerate the completed FineVideo evidence merely to standardize its directory layout; index it as legacy provenance and backfill missing status only when supported by evidence.

## 7. Connect normalized inputs to Gemini and Qwen

Update both annotators to accept the selected manifest and configurable context/output directories. Use `assigned_id` for identity and resolve `file_path` against project root. Currently both annotators derive IDs from video filename stems and expect `pilot_metadata.csv`/`pilot_video_path`; that would mismatch namespaced context IDs.

Preserve the old pilot defaults for compatibility. Add explicit metadata/context options instead of making new data imitate the pilot folder structure. Update the launcher, which currently hardcodes the pilot, output directory, two-video limit, and macOS Qwen interpreter.

Both models must receive identical native video content and the same transcript, acoustic summary, caption, and evidence-priority block. Qwen must consume native video through a supported video path, never an isolated-frame substitute. Record Gemini's direct raw-audio access and Qwen's `raw_audio_access=False`; common context does not equal identical modality access.

Record media hash, shared-context hash, prompt/rubric version, model/backend version, inference settings, and run ID. Model-access notes may differ, so compare the shared evidence block rather than requiring the complete prompts' hashes to match.

Run a two-video annotation smoke test for each model in a separate output directory after backend setup. Validate schema, identity, provenance, modality claims, and resume behavior. Bulk annotation should follow the human validation milestone below.

## 8. Human validation and annotation routing

Collect blind independent human labels for the existing 50-video pilot using `annotation_rules.txt`. Use the policy's proposed 25 development / 25 held-out evaluation split, with two independent raters per video; keep original ratings before adjudication. Restore pilot media first.

Normalize human scores for comparison: valence = score / 5 - 1; arousal/recovery/confidence = score / 10; emotion weights = weight / 10. Preserve original scores. Analyze rater agreement alongside model errors, not only model-to-model agreement.

Implement `annotation_disagreement_policy.md` as a versioned comparator: output validity and input comparability first, then its proposed scalar/distribution/dominant-emotion checks. Thresholds remain provisional until evaluated. Separate invalid outputs, incomparable inputs, evidence problems, and high disagreement. Never average high-disagreement results into usable labels.

After development tuning, freeze the prompt/models/policy for held-out evaluation. Report human-reference errors, inter-rater agreement, acceptance coverage, uncertainty, and retained/excluded source/category/language composition. Define the primary/verifier workflow from those results rather than assuming either model is better.

For the initial expanded annotation run, use both models independently on a fixed eligible batch. Route low-disagreement items to provisional silver labels and uncertain items to a preserved review pool. Audit 25 additional randomly sampled accepted items with independent raters as proposed in the policy, and include new source/language/category groups in subsequent validation. Agreement is not proof of correctness, and FineVideo-only validation does not establish reliability for all new groups.

## 9. Three-model suitability evaluation and selection

Output-scale update: the new Qwen/InternVL CUDA runners use `v1.1-points10`, requiring each of eight emotion values in [0, 10] and an exact decimal total of 10.00. They save original `emotion_points` and probabilities obtained by dividing by 10; no bad total is silently renormalized. At most one schema-repair call is logged. This is strict validation, not a guarantee of first-response arithmetic correctness. Use fresh run directories and align Gemini's future comparison prompt to the versioned point-scale rubric before claiming identical prompts; historical probability-scale annotations remain preserved as baselines.

This section supersedes the earlier assumption that Gemini and Qwen are automatically the final annotator pair. Human ratings are the independent reference for this subjective task; they are not error-free objective truth. Model-to-model agreement is assessed separately from human-reference performance.

### Candidate deployments

| Candidate | Pilot deployment | Evidence and access |
|---|---|---|
| Gemini | Freeze the exact model ID/revision and rubric used for the comparison | Native audiovisual input plus the same shared context |
| Qwen3-VL-8B-Instruct | CUDA NF4; 1 FPS; batch 1; 1,200 output tokens; greedy generation | Native video pipeline; original shared context; no direct raw audio |
| InternVL3.5-8B | Smoke adapter explicitly uses official HF-format `OpenGVLab/InternVL3_5-8B-HF`; NF4 with BF16 vision tower/projector; freeze revision after smoke tests | Native MP4 decoded into an ordered temporal sequence in one video-level request, plus the same shared context; direct raw-audio access is not assumed |

InternVL's [official model card](https://huggingface.co/OpenGVLab/InternVL3_5-8B) documents video inference by loading a local video, sampling ordered frames, and passing them together with frame labels and patch counts to its chat interface. This is a different visual interface from Qwen's supported video processor. Preserve the native source and sequence order; do not make independent still-image predictions and combine them as video annotations. The model card also exposes multiple checkpoints/formats; do not silently substitute the Pretrained, Instruct, HF, or Flash variant for the chosen candidate.

Implement and benchmark an InternVL adapter before claiming it fits the A4000. Its 4-bit deployment is a feasibility target, not a validated setup. Run local models sequentially on the GPU. Match full-timeline sampling at approximately 1 FPS where supported; log exact sampled indices/timestamps, frame/patch counts, dimensions, prompt/context hashes, and missing modalities. If an interface needs a different temporal budget, disclose it and evaluate that deployment rather than claiming identical native inputs. Keep thinking disabled where supported and record the mode.

Setup/smoke scripts added on 2026-10-06: `setup_vlm_cuda.ps1`, `test_vlm_two_videos.ps1`, and `src/annotate_internvl_cuda.py`; Qwen supports `--phase smoke --video-ids ID1 ID2`. See `vlm_cuda_setup.md` for commands. Both models use the same two short pilot clips, 1 FPS, batch 1, deterministic generation, and 1,200 output tokens. Input preflight is separate from actual GPU inference and does not establish model fit or annotation accuracy. Existing environments and pilot outputs are preserved.

Use identical affective constructs, output schema, shared evidence, evidence-priority rules, and bounded technical/schema-repair policy for all three. Keep each model independent of the others' predictions. Preserve raw answers, repaired answers, failures, and provenance. Historical MLX Qwen is a backend baseline, not a fourth candidate or a substitute for the selected CUDA deployment. Reuse existing Gemini outputs only after validating rubric, context, source identity, output schema, and any historical postprocessing against this protocol.

### Define the protocol before inspecting human-model comparison results

1. Freeze a reproducible 25-video development / 25-video held-out split of the original pilot before tuning. Record IDs and source/category/orientation composition. Preserve the original cohort; its predominantly English language mix limits multilingual claims.
2. Obtain two independent, model-blind human ratings for all 50 videos using `annotation_rules.txt`. Store original ratings and any later adjudication separately. Use the mean of the two original raters' normalized scalars/distributions as the predefined primary reference; ties in reference dominant emotion use the fixed eight-emotion key order. Report tie counts and sensitivity to either rater separately.
3. Freeze checkpoint, prompt, inference settings, repair limits, metrics, ranking formula, tie-breaks, and routing policy in a protocol file. Hardware smoke-test answers have already been inspected; document that fact. Do not claim a fully prospective preregistration of model outputs. Human-comparison rankings have not yet been examined.
4. Tune prompts/routing thresholds only on development data. Select the top two on development data, then freeze the selection and report their held-out results. Report all three candidates' held-out metrics for transparency without changing the chosen pair in response to those results. Selecting on all 50 would make those 50 selection data, requiring a separate independent evaluation set.

### Predefined metrics and ranking

Report every metric separately; the composite below is a proposed project decision rule and must be frozen before comparing human-model results.

- Scalar quality: MAE for valence, arousal, and recovery suitability. Divide valence MAE by 2 to normalize its [-1, 1] range to the same full-scale units as the two [0, 1] measures. Primary scalar error is `(MAE_valence / 2 + MAE_arousal + MAE_recovery) / 3`. Also report signed bias and error intervals.
- Emotion quality: dominant-emotion macro-F1 across the fixed eight classes (`zero_division=0`, with class support reported), accuracy, and Cohen's kappa. Report emotion-distribution TVD against the mean human weights, since the current human guide collects a full eight-emotion allocation.
- Ranking: lower is better for `selection_score = 0.5 * normalized_scalar_error + 0.5 * (1 - dominant_emotion_macro_F1)`. Equal weights are a study choice, not an established universal weighting. This combines scalar and categorical suitability without letting valence's wider numeric range dominate.
- Invalid/missing output: retain all 25 development IDs in evaluation. Assign maximum normalized error (1) for each missing/invalid scalar, and an invalid predicted-class sentinel for missing/invalid dominant labels so they count as false negatives for the correct class. Record failure coverage explicitly; do not remove hard videos through complete-case ranking. Also report valid-output-only metrics as secondary analysis. Known incomparable inputs must be repaired or the candidate marked operationally unevaluable, not treated as ordinary model error.
- Tie-break order for equal composite scores within `1e-9`: lower human-reference distribution TVD, higher valid-output coverage, then lower median latency on the same evaluation hardware/deployment. If still tied, report the tie and apply a fixed candidate-name ordering recorded in the protocol. Avoid claiming a statistically clear winner from a tiny numerical difference.
- Practical feasibility: report peak device/allocator VRAM, inference time, schema repair rate, failure rate, and API cost where applicable. A deployment that cannot complete the pilot within the declared operational constraints cannot be selected for full annotation until that deployment is repaired and reassessed.

Report human-human agreement alongside model-human results. Use paired resampling over video IDs for uncertainty intervals, and show per-category/language summaries only with sample sizes and the limitations of this 50-video cohort. Do not treat 25 held-out cases as strong subgroup validation.

### Selected-pair annotation and human review

Run the selected two models independently on every eligible full-dataset item. Generalize the comparator's model names rather than assuming they must be Gemini/Qwen. Preserve the original `v0.1-provisional` policy and create a new version for the selected pair after development validation; its thresholds do not become valid for InternVL by substitution alone.

Agreement means both inputs/outputs pass validity and provenance checks and all frozen scalar/distribution/dominant checks pass. It does not mean dominant labels alone match. Accept these as **provisional silver labels**, retaining both originals and the policy version. Audit a random sample with independent humans; agreement can still share systematic mistakes.

Route disagreement, invalid output, incomparable inputs, and known evidence problems into separately reason-coded human-review queues. Preserve the videos and predictions. Human reviewers first submit their independent label without model suggestions; subsequent adjudication can inspect predictions. Reviewed outcomes are human/adjudicated labels, not model-agreement silver labels. Items remain unresolved and excluded from downstream recommendations until the applicable review is complete. Estimate review volume from development coverage before committing to annotating approximately 4,000 videos.

Completion milestones: 150 terminal pilot inference records (50 per candidate, with valid/invalid/failure states), 100 independent human ratings, a frozen selection report with all three candidates' metrics, held-out evaluation of the frozen selection, then paired full-dataset annotation plus review/audit outcomes. Actual dataset counts come from the normalized selected manifest; existing collection sizes do not yet establish a 4,000-video eligible dataset.

## Proposed derived layout

```text
data/normalized/
  inventory.csv
  id_aliases.csv
  category_mapping.csv
  selected_metadata.csv
  dataset_version.json
  audit/
    media_manifest.csv
    duplicate_manifest.csv
    language_manifest.csv
    selection_manifest.csv
  preprocessed/
    audio/
    transcripts/
    asr/
    context/
    status.json
    failures.jsonl
outputs/normalized/<run_id>/
  gemini/annotations.jsonl
  qwen/annotations.jsonl
  comparison.jsonl
  silver_labels.jsonl
  uncertain.jsonl
evaluation/<study_version>/
  split_manifest.csv
  human_labels.csv
  metrics.json
```

Source videos stay in their current folders; the normalized manifest references them. Existing FineVideo contexts remain in their original location, with the manifest/context resolver mapping to them. The layout is proposed, not yet created.

## Implementation order and platform setup

| Order | Work | Completion evidence |
|---|---|---|
| 1 | Metadata adapters, canonical IDs, path mapping | Inventory reconciliation and collision/path checks |
| 2 | Portable media probe and deduplication | Every local candidate audited |
| 3 | Windows-compatible audio/ASR setup and language audit | Smoke batch plus explicit language decisions |
| 4 | Selected manifest and generalized evidence processor | Resumable validated contexts |
| 5 | Manifest-based annotator inputs and model backend setup | Two-video fresh inference per model |
| 6 | Blind pilot labeling and evaluation comparator | Frozen held-out results and policy version |
| 7 | Expanded annotation and silver-label audit | Paired outputs, routing, coverage/error report |

This machine has Python 3.12 available; the historical snapshots describe Python 3.11 on Apple Silicon. FFprobe was not found on PATH during the inventory. Verify FFmpeg/FFprobe, choose a documented runtime, and create fresh platform-specific environments.

Current Whisper/Qwen scripts import or invoke MLX and cannot be used unchanged on Windows. Add explicit backend adapters and select a Windows-compatible Whisper implementation and native-video-capable Qwen implementation after checking the available GPU/RAM and testing a small batch. Record any model/backend change and assess comparability; do not silently mix its outputs with historical MLX runs. Preserve the original dependency snapshots and store new environment/configuration records separately.

Useful future module boundaries are `normalize_dataset.py`, `audit_media.py`, a generalized language auditor, the existing generalized preprocessor, shared manifest/path loading, and `compare_annotations.py`. These are implementation deliverables, not commands available today. The historical language/orientation filter scripts contain FineVideo-specific paths and destructive moves; do not run them directly on the new collections.

## RTX A4000 deployment target

User-supplied hardware: NVIDIA RTX A4000, 16 GB VRAM, compute capability 8.6 (Ampere). Verify device visibility, driver/runtime compatibility, and available memory during setup; no local GPU inference benchmark has been run yet.

The first Windows/CUDA target is `Qwen/Qwen3-VL-8B-Instruct`, using Transformers with bitsandbytes 4-bit NF4 weight loading. Start with batch size 1, double quantization, and BF16 compute if validated on this runtime (FP16 is an alternative). NF4 and AWQ are distinct methods, not interchangeable loader settings: AWQ remains an alternative only after selecting an exact compatible checkpoint and testing its runtime. The unquantized Instruct repository can be loaded with NF4; do not assume it is an AWQ checkpoint.

Official references: [Qwen model card](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) and [Transformers bitsandbytes documentation](https://huggingface.co/docs/transformers/main/quantization/bitsandbytes). The latter documents Windows support and NF4 configuration. Pin the actual tested versions and model revision rather than copying a model-card installation command blindly.

Important baseline correction: the saved FineVideo pilot already used `mlx-community/Qwen3-VL-8B-Instruct-4bit`, as recorded in both `src/annotate_qwen.py` and its annotation outputs. The planned change is therefore 8B MLX 4-bit on Apple Silicon to 8B CUDA NF4 on NVIDIA, not a demonstrated 3B-to-8B upgrade. Preserve the old run and evaluate the new quantization/backend as a separate configuration.

Treat 8B NF4 as a candidate to benchmark on 16 GB, not a guaranteed comfortable fit or a proven strongest model for this study. Quantized weights are only part of peak memory: the vision encoder, video tokens, activations, KV cache, shared text context, and generated output also matter. Keep full-precision 8B, larger models, and Thinking variants outside the initial implementation scope; revisit only if comparative evidence justifies them.

Implementation and acceptance sequence:

1. Verify CUDA device/runtime and install a separate tested Windows environment. Do not overwrite the historical MLX dependency snapshots.
2. Implement a CUDA Qwen adapter that takes the native local video through the supported video processor. Temporal sampling inside that processor is expected; manually replacing video input with independent still-image calls is not acceptable.
3. Make processor sampling rate, frame/pixel or video-token budgets, maximum generated tokens, and generation settings explicit and record them. Begin with bounded settings covering the complete clip timeline; document sampling limitations rather than claiming every original frame was inspected.
4. Benchmark short, typical, and longest selected clips with realistic shared contexts. Record peak allocated/reserved GPU memory, latency, decode success, and schema validity. Test repeat inference to identify memory accumulation. Leave measured headroom for the display and runtime.
5. Run Whisper preprocessing and Qwen inference sequentially on the GPU initially; do not keep both models resident during the first memory tests. Gemini API work can be scheduled independently when authorized.
6. If memory is insufficient, adjust and revalidate documented video/token budgets before scaling. A smaller model or another runtime is a separately versioned fallback; do not silently truncate clips, switch models, or offload and claim full-GPU performance.
7. After the short/medium/long pilot-video benchmarks pass, rerun all 50 original pilot videos from the beginning with CUDA NF4, batch size 1, and unchanged shared contexts. This fresh Qwen pilot run is authorized by the user and can precede human evaluation; expansion to the new collections remains subject to that evaluation. Compare the complete CUDA pilot against the preserved MLX baseline, existing Gemini results, and independent human labels.

Proceed to bulk inference only after the representative clip tests and annotation validation pass. This update selects a deployment target; it does not install packages, download weights, or execute inference.

### Fresh Qwen pilot run

Pixel-budget experiment (2026-10-05): the 167,772-pixel warning originated in `qwen-vl-utils` enforcing the 4,194,304 aggregate video-pixel budget, not Transformers' per-frame cap. The runner now explicitly sets `cap_pixels_per_frame=False`; `--total-pixels 0` removes the aggregate reduction while retaining the requested per-frame maximum. A new run directory is required for this configuration change. Qwen3-VL uses patch size 16 here, so 313,600 remains a valid area budget but its description as `400 × 28 × 28` is not this model's patch geometry.

The longest-first 262,144-pixel / 1 FPS uncapped benchmark in `outputs/pilot_qwen_cuda_nf4/a4000_20261005_v3_262144_uncapped/` sustained more than 15 GiB total device usage and reached an observed 15,972 MiB (15.60 GiB). It was stopped before its first annotation completed to preserve headroom. This is an observed device-memory sample, not a completed PyTorch peak measurement or proof of an OOM. The full pilot and 313,600-pixel test were not started. The earlier 10.52 GiB allocation measurement was for the short clip and must not be extrapolated to long videos. The runner records both allocator and total-device peaks on completed clips and gates the pilot on successful benchmarks with headroom.

An additional CPU-only processor inspection confirmed that this longest clip produces 88 sampled frames at 512 × 288 = 147,456 pixels per frame, even with the aggregate cap removed. `max_pixels` is a ceiling, not a request to upscale every frame to that area. Increasing it to 313,600 alone would not enlarge this particular clip. Its long temporal sequence is material to memory use.

Current user-selected Qwen configuration (2026-10-06): `Qwen/Qwen3-VL-8B-Instruct`, CUDA NF4, FPS **1.0**, batch size **1**, full-clip timeline coverage, maximum **1,200 new output tokens**, deterministic greedy generation (effective temperature **0**), and the original transcript + eGeMAPS summary + low-priority caption. Do not reduce FPS to 0.5. Full coverage means temporally sampled evidence across the complete clip, not every original frame. Keep `max_pixels=262144` and `cap_pixels_per_frame=False` from the previous explicit pixel choice until a versioned change is selected. This configuration remains unvalidated for headroom: resolve memory pressure at 1 FPS before the official run rather than silently changing temporal sampling or bypassing the benchmark gate.

Execution update (2026-10-05): `.venv-qwen-cuda` is installed and CUDA detects the RTX A4000 (8.6). `requirements-qwen-cuda.txt` records the installed packages; dependency checks passed. All 50 restored videos decoded successfully. The Qwen checkpoint downloaded and loaded as NF4. The first benchmark in `outputs/pilot_qwen_cuda_nf4/a4000_20261005_v1/` failed strict validation because emotion scores totaled 0.70; no full pilot run began. Its raw response and failure are preserved.

The revised `src/annotate_qwen_cuda.py` allows one logged model-generated schema repair, without silently normalizing invalid scores. `run_qwen_cuda_pilot.ps1` targets a fresh `a4000_20261005_v2` run, benchmarks first, and then runs all 50 IDs only on success. The permission request to execute this revised run was rejected; it has not started. Historical annotations remain intact. Resume command after execution is authorized: `powershell -NoProfile -ExecutionPolicy Bypass -File E:\ALI\Ataraxia\run_qwen_cuda_pilot.ps1`. The execution-policy override applies only to that process.

- Pilot media restoration is complete as of 2026-10-05: all 50 pilot IDs match nonempty MP4s under `data/pilot_50_reels_30h/pilot_50_reels_30h/videos/`. Playback/decoding checks remain pending. The restored folder also supplies audio, transcripts, contexts, and pilot metadata. Ignore the sibling `__MACOSX/` resource-fork files during inventory and processing. Full FineVideo media remains absent at its original path.
- Configure the native-video resolver to use this restored directory and keep `pilot_50_reels_30h/context/` as the original shared-context source. The current defaults still expect videos directly under the root pilot folder, so path configuration must be corrected before inference; do not treat file restoration alone as runtime readiness.
- Reuse the original transcripts, acoustic summaries, captions, and rubric so the backend/quantization change can be assessed without changing the evidence at the same time. Audio extraction and ASR do not need to be rerun for this annotation experiment.
- Keep `outputs/reels_30h/qwen/annotations.jsonl` as the historical MLX baseline. Write the fresh run under a new run ID, for example `outputs/pilot_qwen_cuda_nf4/<run_id>/qwen/annotations.jsonl`. Do not use the old output's processed-ID cache, which would skip the pilot.
- Use a separate benchmark directory, then start the official run with an empty output file and an explicit 50-ID manifest. Freeze the tested video processor and generation configuration before this official run. The same original native-video evidence must be supplied; record processor sampling settings and native raw-audio access as false.
- Record checkpoint revision, NF4 configuration, CUDA/backend versions, media/context hashes, timing, peak memory, and validation failures. Resume a partially completed official run only within that same frozen configuration; avoid duplicate video IDs.
- Completion requires exactly one valid annotation for each of the 50 pilot IDs, with no unresolved failures or input mismatches. Existing Gemini predictions can be reused for this comparison; fresh Gemini inference is a separate experiment if later requested.

## What to do first

Start with metadata normalization and media auditing for the 1,386 local videos. In parallel with that workflow, restore the original pilot media so human labeling can proceed. Then test the portable preprocessing backend on a small varied batch before spending time on full transcription or model inference. No paid model calls, downloads, or bulk reprocessing are needed to create the normalized inventory.

Success means a reproducible selected manifest, consistent evidence for every admitted video, preserved historical work, validated paired annotations, and measured human-reference performance. It does not mean every source record must be accepted.

InternVL CUDA processor correction (2026-10-06): use its own tokenizing chat-template video path with arguments nested in `processor_kwargs`, not Qwen tensors. Cached checkpoint geometry requires 448?448 frames (14-pixel patches, 0.5 downsampling, 256 tokens/frame); the bundled 384?384 video default produces an incompatible 27?27 patch grid. Preserve NF4, 1 FPS and the existing headroom gate. Native processor preflight passed both smoke videos; full GPU results are recorded under `outputs/vlm_smoke/internvl_processor_fix/internvl/`.

Corrected-path GPU test: stopped during the first video after observed device memory stayed around 15.65 GiB, exceeding the 15 GiB gate. No completed InternVL annotation was produced; do not mark deployment feasible yet.

Two-video rerun completed for both models at `pilot_50_reels_30h/results/two_video_cuda_20261006/`. InternVL required the authorized 16-frame uniform full-clip cap and ordered vision microbatching; both labels passed schema validation, but device-memory headroom did not pass. `run_both_cuda_pilot.ps1` runs all 50 sequentially per model with these recorded settings, durable logs and resumption. Qwen research pilot explicitly bypasses the unpassed long-video benchmark prerequisite while retaining memory/failure reports. This is not a deployment feasibility sign-off.

Fixed-frame InternVL experiment: `run_internvl_cuda_pilot.ps1` defaults to 32 uniformly sampled frames across each full clip (not FPS sampling), with fresh policy-specific directories; `-NumFrames 24` and `-NumFrames 16` select separate runs. Native InternVL sampling and processing, NF4, original prompt/context, 1,200 output tokens and ordered vision microbatching remain unchanged. This is a new experiment, not a verified speed/memory improvement over the tested 16-frame cap. Repository audit found the long 50-pilot timings belong to Qwen (15 valid labels, 2.42 inference hours, three failed IDs); InternVL had not started in that run. Adjusting InternVL cannot fix those Qwen failures. Preserve all earlier results.

Qwen temporal update: keep Qwen3-VL-8B NF4, 1 FPS target, original spatial limits, prompt and evidence; cap at 48 even-count frames, uniformly distributed from first to last source frame across the full clip. Shorter clips keep their existing sampling. Preserve uncapped outputs as a separate experiment. Updated `run_qwen_cuda_pilot.ps1` benchmarks before bulk inference and writes to `results/pilot50_qwen_nf4_max48_v2/qwen`; updated combined runner writes to `results/pilot50_cuda_nf4_qwen48_intern16_v2`. InternVL sampling is unchanged in the combined runner. Exact frame indices and effective FPS are logged; speed, memory and annotation quality improvements require measurement.

Qwen cap revision: the 48-frame longest-video benchmark completed but exceeded the 15 GiB total-device gate (15.664 GiB; 16.10 GiB allocator peak). Reduce only the temporal cap to 32 frames with full-clip uniform coverage; preserve all other settings. `run_qwen_cuda_pilot.ps1` now uses fresh `results/pilot50_qwen_nf4_max32_v3/qwen`; combined runner uses fresh `results/pilot50_cuda_nf4_qwen32_intern16_v3`. Keep the benchmark gate for the Qwen-only pilot and preserve earlier runs.

User-authorized memory policy: allow up to 16.0 GiB observed device memory for the updated Qwen-only and combined CUDA runners. Preserve Qwen's 32-frame cap and other settings. Fresh full16_v4 result folders distinguish this policy from the prior 15 GiB gate. Completed runs above 15 GiB are no longer rejected by that gate; actual CUDA OOMs still count as failures.

Latest user correction: set the Qwen-only and combined runners' observed device-memory gate to **15.8 GiB**, superseding the preceding 16.0 GiB setting. Keep Qwen at 32 uniformly sampled full-clip frames maximum. Use fresh `limit15p8_v5` output folders; earlier results remain preserved.
