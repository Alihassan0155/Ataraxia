# Open category discovery — prepared, inference not authorized

All 118 prior unresolved inputs and their cached raw responses were inspected offline. Their recorded content sources are transcripts only; no native audiovisual content was inspected in this preparation. Exact quotations alone cannot establish contextual support. Sixteen cached raw responses fail the existing output/evidence validator; this differs from the three terminal invalid outputs because the prior runner converted some invalid proposals into abstentions.

There are **zero reusable valid new-category proposals** in the cached outputs. Consequently there are no Qwen-proposed new names, descriptions, supporting-video lists or frequencies to report yet. No new labels have been invented to fill this gap. Cached existing-label suggestions remain historical proposals, not accepted discovery results. All previously accepted 54 classifications are preserved.

The previous prompt favored existing labels and called them “Allowed onboarding categories.” The new isolated runner removes both biases. Existing categories are non-exhaustive references with no preference. A category must describe the defining content theme; an overly broad existing label need not be forced. Novelty is not required when an existing category genuinely fits.

New outputs require one short reusable English name, a category description, an explanation of existing-category adequacy/inadequacy and one exact content-source quotation. Unsupported content, generic utterances and ambiguous fragments require abstention. Captions/titles cannot fill missing content evidence. The pinned model and category-only scope remain unchanged.

`backend/video_data/category_discovery.py` prepares and audits without inference or database access. `validate_candidate` checks the open schema, evidence quotes and original-category protection. Every non-null result requires subsequent content review. `group_reviewed` accepts a new category only after an explicit review tied to its candidate hash, a reviewer, evidence rationale and existing-category inadequacy. Explicit synonym merges require justification. It groups approved equivalent labels and reports canonical name, description, original labels, supporting video IDs/evidence and distinct-video frequency. Unreviewed and unsupported candidates remain separate. Acceptance here is local evidence review, never production taxonomy approval or a database update.

`backend/video_data/run_category_discovery.py` reuses the existing pinned model loader, 118-video scope selection, checkpointing and five-video smoke gate. It writes to a fresh directory and cannot reuse old-policy checkpoints as new-policy results. The runner hash and supporting policy hashes are frozen. The CLI requires `--approved-inference`; it has **not** been executed. Frozen prior runners and artifacts are unchanged.

Prepared outputs: `backend/reports/category_discovery_prepared_20261018/`:

- `plan.json`: scope, cached reuse, approval status and proposed maximum 118 calls.
- `requests.jsonl`: unchanged content inputs and provenance.
- `contract.json`: neutral discovery prompt and output schema.
- `cache_audit.json`: one audit entry for each video, cached labels and validation issues.
- `cached_new_candidates.json`: empty.
- `category_report.json`: separate accepted local new-category groups and unsupported/unreviewed proposals; currently empty.

Validation: all 54 backend tests pass. Discovery tests cover open labels, mandatory review, synonym grouping, distinct-video frequency and rejection of stale review identities. No Qwen, Gemini, Whisper, BGE-M3 or semantic extraction was run; no Supabase access or writes occurred.

Approval requested: run the pinned Qwen category-only discovery on at most these 118 videos, first five as a smoke test, then continue only after validation and evidence review. Outputs remain local proposals; no production or accepted-classification changes are included.
