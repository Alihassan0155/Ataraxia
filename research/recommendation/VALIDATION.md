# Stage 1 validation — 2026-11-16

Source: the retained local November 10 database restore, not today's live database.
No production/Supabase/S3 reads, inference, annotation or media collection occurred.
The original backup and production backend were not modified.

| Source table | Rows |
| --- | ---: |
| videos | 4,226 |
| video_context | 4,226 |
| affect_annotations | 2,486 |
| video_semantics | 2,327 |
| video_embeddings | 2,327 |
| processing_runs | 37 |
| interest_categories | 19 |

**Eligible: 2,317 videos.** Embeddings: **(2317, 1024), float32**, finite,
with observed norms 0.9999998808–1.0000001192. All eligible videos have validated
linked Gemini affect, Qwen semantics, context and BGE-M3 embeddings.

Affect presence: 2,486 / 4,226 canonical videos (presence alone is not validity).
Eligible affect coverage: 2,317 / 2,317. Of the 2,327 complete semantic/embedding
bundles, eight fail the existing emotion-probability sum rule and two have
unresolved `unknown` categories. Another 1,899 canonical videos have no semantic
record. Total exclusions: 1,909. No silent normalization or repairs were applied.
The eight sums were checked as probabilities, not relabeled as missing affect.

`validation_summary.json` records the complete category distribution and aggregate
results. Detailed excluded IDs/reasons are preserved locally at
`local/stage1_validation_20261116.json` (Git ignored).

Verification performed:

- Original native archive SHA-256 matches the recorded backup digest:
  `64c81b38e19449218e041aacdcdf027873c8cb013736aa63b45c839d970a1a54`.
- A local transaction explicitly reported `transaction_read_only = on`.
- Existing whole-snapshot validator passed hashes, provenance, projections,
  video/run/context/affect references and all 2,327 semantic/embedding links.
  Every source embedding passed dimension, finiteness and norm checks.
- All 2,317 selected matrix rows were independently compared element-for-element
  against source embeddings by embedding ID, with canonical video, semantic and
  run IDs checked. No ID-to-vector misalignment was found.
- 14 automated tests passed, including shuffled row order, duplicates, missing
  embeddings, cross-video joins, provenance corruption, nonfinite/wrong-size/
  unnormalized vectors, affect validity, unknown categories, latest-version ties,
  refusal to substitute older embeddings, package checksum tampering, empty input
  and rejection of remote connection strings/environment routing.

Stage 1 is complete. No simulator, recommendation strategy or DQN was implemented.

Exact files created:

- `research/__init__.py`
- `research/recommendation/__init__.py`
- `research/recommendation/catalogue.py`
- `research/recommendation/demo.py`
- `research/recommendation/tests/__init__.py`
- `research/recommendation/tests/test_catalogue.py`
- `research/recommendation/README.md`
- `research/recommendation/VALIDATION.md`
- `research/recommendation/validation_summary.json`
- `research/recommendation/local/stage1_validation_20261116.json` (private, ignored)

Modified: `.gitignore`, adding only the research package's private `local/`
directory exclusion. Pre-existing unrelated work in that file was preserved.
