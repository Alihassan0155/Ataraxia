# Ataraxia project handoff

## Goal

Build and compare a multimodal affective-video annotation pipeline using the
same evidence bundle for Gemini, Qwen3-VL, and InternVL3.5-8B on the human-labeled
50-video pilot. Select two deployments using predefined development-set criteria,
evaluate the frozen choice on held-out pilot videos, and use that pair for the
full dataset. Molmo is intentionally excluded.

## Active structure

- `data/FineVideo/metadata.csv`: filtered 858-video dataset metadata
- `data/FineVideo/videos/`: 601 vertical and 257 horizontal videos
- `data/FineVideo/audit/`: preserved language/orientation filtering records
- `pilot_50_reels_30h/`: active 50-video pilot
- `pilot_50_reels_30h/context/`: shared transcript, acoustic, and caption context
- `outputs/reels_30h/gemini/`: 50 Gemini annotations
- `outputs/reels_30h/qwen/`: 50 Qwen annotations
- `annotation_rules.txt`: human-annotation guide

## Constraints

- Keep only English, Urdu, and Hindi content. The current detected-language
  distribution is 857 English and one Urdu video.
- Keep the full dataset at no more than 30% horizontal content while preserving
  category proportions as closely as possible.
- The pilot contains 35 vertical and 15 horizontal videos.
- Qwen must consume the native local video rather than isolated frames.
- Direct audiovisual evidence has highest priority.
- Treat transcripts as potentially imperfect and metadata captions as
  low-priority auxiliary evidence. Never infer affect from a caption alone.

## Shared evidence

Both model annotators load the matching context JSON through
`src/common_annotation.py`. The prompt appends the same transcript, acoustic
features, metadata caption, and evidence-priority rules for both models.

## Next study step

Collect independent human labels for all 50 pilot videos without exposing
annotators to model predictions. Compare all three candidates under the protocol
in `plan_annotation.md` section 9, then select the full-dataset pair.
Qwen's user-selected CUDA configuration is NF4, 1 FPS, batch size 1,
1,200 output tokens, greedy generation, full-clip timeline coverage, and the
original transcript/eGeMAPS/caption. Do not reduce FPS to 0.5 silently.
The 1 FPS uncapped benchmark exceeded the headroom target; deployment feasibility
must be resolved before bulk inference. The InternVL smoke adapter uses
`OpenGVLab/InternVL3_5-8B-HF`; full GPU inference has not yet been validated.
See `vlm_cuda_setup.md` for setup and sequential two-video smoke-test scripts.
Approximately 4,000 videos is a target, not a verified eligible count. Agreement
from the selected pair yields provisional silver labels; disagreement enters
reason-coded human review.

## Verified repository state (2026-10-04)

- Full FineVideo preprocessing is complete: 858 audio files, transcripts, and
  context JSONs under `data/FineVideo/preprocessed/`; status reports zero failures
  in its final run. The human-label comparison remains pending.
- YouTube source metadata has 58,868 rows. The metadata Hindi/Urdu shortlist has
  1,316 manifest rows, 952 downloaded status records, and 953 local video files.
  Reconcile the discrepancy; do not call metadata-derived language speech-verified.
- `data/youtube_shorts/english_500/` has 633 candidates and 500 downloaded videos,
  all vertical. This additional sample is separate from the completed FineVideo pilot.
- Qwen receives native video through the MLX-VLM CLI and uses shared context for
  audio evidence; `raw_audio_access=False`. Gemini has direct audiovisual access.
  Shared context does not imply identical native modality access.

## Portability and version control

The project folder currently has no `.git`. Do not push without a user request.
Keep metadata, audits, contexts, transcripts, and annotations in version control.
`.gitignore` excludes media, secrets/cookies, environments, weights, caches, and logs.
Restore ignored media separately using the same directory layout; never transfer
virtual environments as a substitute for reinstalling dependencies.

`requirements.txt` is the complete installed main-environment snapshot;
`requirements-qwen-mlx.txt` preserves the distinct Qwen environment. Both use
Python 3.11 on Apple Silicon; MLX Qwen/Whisper scripts require a backend port for
Windows/Linux. Use `.env.example` for setup without exposing real credentials.
Some historical YouTube `local_path` fields are machine-specific absolute paths.
See `guide.md` for restoration and Git setup commands. Do not erase historical
study evidence merely to make paths look portable.
