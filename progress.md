# Ataraxia project progress

Last verified: 2026-10-04 (local filesystem and study records)

## Completed FineVideo study preparation

- Metadata: 858 rows; language fields contain 857 English and one Urdu.
- Orientation manifest: 601 vertical and 257 horizontal (29.95% horizontal).
- Pilot: 50 videos, 35 vertical and 15 horizontal; 50 audio files, transcripts,
  and shared context JSONs.
- Full preprocessing: 858 audio files, 858 transcripts, and 858 contexts.
  Final status records 138 completed, 720 skipped, zero failed in that run.
- Gemini and Qwen each have 50 JSONL annotation records.
- Molmo is intentionally excluded. Human annotation and model evaluation remain pending.

## YouTube collection work

- Normalized source metadata: 58,868 rows.
- Hindi/Urdu metadata shortlist manifest: 1,316 rows (947 vertical, five horizontal,
  42 square, 322 unknown orientation).
- Download status: 952 records marked downloaded; corresponding video directory
  contains 953 files. File/status reconciliation is outstanding.
- Separate English sample: 633 candidate rows, 500 downloaded metadata rows and
  500 video files, all vertical.
- Metadata language classification does not verify spoken language. Complete the
  audio language audit before incorporating these samples into the language-filtered study.

## Repository transfer preparation

- Updated guide and agent handoff to reflect full preprocessing and YouTube work.
- Added `.gitignore` for secrets, authentication cookies, media, environments,
  caches, weights, temporary downloads, and run logs.
- Captured every installed runtime package in `requirements.txt` and preserved
  the distinct Qwen environment in `requirements-qwen-mlx.txt`.
- Added `.env.example` and destination setup/media transfer instructions.
- No `.git` repository currently exists; no commit, remote, or push was performed.
- Fresh dependency installation and model inference on the destination are not tested.
- Current MLX Qwen and Whisper backends require Apple Silicon; a non-Mac move
  needs a backend port. Historical YouTube status records include old absolute paths.

## Next work

1. Initialize/review/push the repository; transfer excluded media privately and
   recreate environments on the destination.
2. Reconcile YouTube download status with local files and verify spoken languages.
3. Collect independent human labels for all 50 pilot videos using
   `annotation_rules.txt`, without exposing model predictions.
4. Compare Gemini and Qwen against human labels and define the primary/verifier
   workflow before expanding annotation to the complete dataset.
