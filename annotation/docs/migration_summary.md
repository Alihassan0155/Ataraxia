# Migration summary

Implemented on 2026-10-11. Existing Git history is preserved on branch `refactor/modular-annotation-20261011`. The starting worktree contained uncommitted and untracked research work; it was not reset.

## Source locations

| Previous entry point | Implementation | Compatibility |
| --- | --- | --- |
| `src/analyze_model_calibration.py` | `src/ataraxia/evaluation/development/calibration.py` | old path retained |
| `src/analyze_three_human_calibration.py` | `src/ataraxia/evaluation/development/three_human_calibration.py` | old path retained |
| `src/annotate_gemini.py` | `src/ataraxia/research/pipelines/gemini.py` | old path retained |
| `src/annotate_internvl_cuda.py` | `src/ataraxia/research/pipelines/internvl_cuda.py` | old path retained |
| `src/annotate_qwen.py` | `src/ataraxia/research/pipelines/qwen_mlx.py` | old path retained |
| `src/annotate_qwen_cuda.py` | `src/ataraxia/research/pipelines/qwen_cuda.py` | old path retained |
| `src/apply_language_filter.py` | `src/ataraxia/research/collection/apply_language_filter.py` | old path retained |
| `src/apply_orientation_filter.py` | `src/ataraxia/research/collection/apply_orientation_filter.py` | old path retained |
| `src/audit_drive_dataset.py` | `src/ataraxia/research/collection/audit_drive_dataset.py` | old path retained |
| `src/audit_languages.py` | `src/ataraxia/research/collection/audit_languages.py` | old path retained |
| `src/audit_youtube_languages.py` | `src/ataraxia/research/collection/audit_youtube_languages.py` | old path retained |
| `src/build_human_fieldwise_consensus.py` | `src/ataraxia/evaluation/development/fieldwise.py` | old path retained |
| `src/build_human_soft_reference.py` | `src/ataraxia/evaluation/development/soft_reference.py` | old path retained |
| `src/build_normalized_dataset.py` | `src/ataraxia/datasets/normalization.py` | old path retained |
| `src/build_reels_pilot.py` | `src/ataraxia/research/selection/reels.py` | old path retained |
| `src/build_three_human_reference.py` | `src/ataraxia/evaluation/development/three_human_reference.py` | old path retained |
| `src/build_youtube_language_sample.py` | `src/ataraxia/research/collection/build_youtube_language_sample.py` | old path retained |
| `src/check_vlm_cuda.py` | `src/ataraxia/annotation/diagnostics.py` | old path retained |
| `src/common_annotation.py` | `src/ataraxia/annotation/common.py` | old path retained |
| `src/compare_human_annotations.py` | `src/ataraxia/evaluation/development/two_human_comparison.py` | old path retained |
| `src/compare_pilot_models.py` | `src/ataraxia/evaluation/development/model_comparison.py` | old path retained |
| `src/download_youtube_english_500.py` | `src/ataraxia/research/collection/download_youtube_english_500.py` | old path retained |
| `src/download_youtube_metadata_shortlist.py` | `src/ataraxia/research/collection/download_youtube_metadata_shortlist.py` | old path retained |
| `src/drive_download_worker.py` | `src/ataraxia/research/collection/drive_download_worker.py` | old path retained |
| `src/extract_youtube_video_info.py` | `src/ataraxia/research/collection/extract_youtube_video_info.py` | old path retained |
| `src/filter_youtube_english_500.py` | `src/ataraxia/research/collection/filter_youtube_english_500.py` | old path retained |
| `src/filter_youtube_metadata_candidates.py` | `src/ataraxia/research/collection/filter_youtube_metadata_candidates.py` | old path retained |
| `src/load_youtube_english_500_streaming.py` | `src/ataraxia/research/collection/load_youtube_english_500_streaming.py` | old path retained |
| `src/load_youtube_shorts.py` | `src/ataraxia/research/collection/load_youtube_shorts.py` | old path retained |
| `src/materialize_drive_downloads.py` | `src/ataraxia/research/collection/materialize_drive_downloads.py` | old path retained |
| `src/merge_normalized_audits.py` | `src/ataraxia/datasets/audit_merge.py` | old path retained |
| `src/normalized_paths.py` | `src/ataraxia/datasets/paths.py` | old path retained |
| `src/prefilter_youtube_languages.py` | `src/ataraxia/research/collection/prefilter_youtube_languages.py` | old path retained |
| `src/prepare_normalized_dataset.py` | `src/ataraxia/datasets/selection.py` | old path retained |
| `src/preprocess_full_dataset.py` | `src/ataraxia/research/preprocessing/finevideo_mlx.py` | old path retained |
| `src/preprocess_normalized_dataset.py` | `src/ataraxia/datasets/preprocessing.py` | old path retained |
| `src/preprocess_pilot.py` | `src/ataraxia/research/preprocessing/pilot_mlx.py` | old path retained |
| `src/prompts.py` | `src/ataraxia/annotation/prompts.py` | old path retained |
| `src/quarantine_resolved_language.py` | `src/ataraxia/research/collection/quarantine_resolved_language.py` | old path retained |
| `src/run_all_parallel.py` | `src/ataraxia/research/pipelines/parallel_legacy.py` | old path retained |
| `src/schema.py` | `src/ataraxia/annotation/legacy_schema.py` | old path retained |
| `src/select_held_out.py` | `src/ataraxia/research/selection/heldout.py` | old path retained |
| `src/select_pilot_50.py` | `src/ataraxia/research/selection/pilot.py` | old path retained |
| `src/summarize_human_model_means.py` | `src/ataraxia/evaluation/development/field_means.py` | old path retained |
| `src/validate_normalized_dataset.py` | `src/ataraxia/datasets/validation.py` | old path retained |

## New reusable boundaries

- `ataraxia.api`: explicit annotation jobs and isolated process execution.
- `ataraxia.runtime`: workspace/env resolution and library logging.
- `ataraxia.annotation.backends`: current working native CUDA/SDK workers, sourced from frozen copies without modifying those copies.
- `ataraxia.calibration.apply`: exact existing scalar/distribution application functions; fitting remains in development.
- `ataraxia.evaluation.metrics`: exact existing error/agreement functions shared by development code.

## Preserved locations

Datasets, original human annotations, predictions, calibration coefficients, preprocessing evidence, prior reports and the frozen held-out code remain at their original paths. No historical output was recomputed. The 45 root Python files now contain aliases instead of duplicate implementations. Frozen experiment copies and exact rollback snapshots are intentional versioned evidence, not removable duplicates.

## Actual inventory

The inventory inspected 21,772 non-environment/cache files and 75 original Python modules. It records imports, module responsibilities, file sizes and evidence hashes. Large media is recorded by size/mtime; it was not read into memory or relocated. Secrets are excluded from content inspection/hashing. Nested `Ataraxia/.git` was left untouched.

## Reversibility

Pre-refactor bytes for all 45 changed source files are in `research/migration/source_snapshots/`; hashes and mappings are in `source_migration.json`. This preserves even source edits that were not yet in Git.

```powershell
.\.venv-qwen-cuda\Scripts\python.exe scripts/restore_legacy_sources.py  # dry run
.\.venv-qwen-cuda\Scripts\python.exe scripts/restore_legacy_sources.py --apply
```

Restore writes only those original source paths, removes no files and leaves all research artifacts intact. The package, compatibility entry points, snapshots and docs were staged on the dedicated refactor branch. Commit approval was declined, so no refactor commit was created; the original Git history remains unchanged. Avoid a blanket `git reset`/`git clean`, which could erase unrelated uncommitted work.

## Deliberate limits

Historical metadata still contains external machine paths and is not rewritten as evidence. New jobs accept explicit portable workspace/evidence/metadata/output paths. Historical MLX research remains Apple Silicon-only. The software refactor does not resolve missing Ali held-out fields or Gemini provider provenance, and does not authorize full-dataset inference.
