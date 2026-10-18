# Canonical Qwen category IDs — 2026-10-17

Implemented locally. No model inference, database writes, historical artifact
updates, embedding regeneration or catalogue replacement was performed.

## Inspected database and historical labels

Read `interest_categories` in an explicit READ ONLY transaction. All 19 IDs/names
match the existing taxonomy identity (18 onboarding categories plus `unknown`).
The complete ID/name registry is committed in
`annotation/semantic_pipeline/configs/taxonomy_category_ids_v1.json`.

All **910 stored semantic primary categories** are exact canonical names.
A local snapshot inspected **1,019 completed historical records**: all have exact
canonical names. No existing record needs relabeling or review. Local processing
counts can advance independently; this audit is not a new import or rebuild.
See `category_id_audit_20261017.json` for the registry and local label distribution.

`map_legacy` provides an explicit read-only mapping for future legacy audits:
canonical names/IDs, known exact aliases and uniquely owned subcategories map to
canonical IDs. Ambiguous labels (e.g. `Other`, `Tutorials`) and unmapped labels
are flagged for review. No fuzzy matching and no payload mutation occurs.

## Future extraction contract

New default CLI configuration: `pipeline_v13.json`; new default run name:
`semantic_category_ids_v13`. It uses the existing v2 semantic/record schema,
retrieval template, checkpoint revision, quantization, generation budgets and
evidence policy. Only category classification changes.

- The request lists all 19 ID/name choices explicitly. JSON output
  `primary_category` must be **one canonical ID string**, not a display name.
- The request's wire JSON Schema enumerates the 19 IDs and requires
  `secondary_categories: []`. No second Qwen classification is accepted.
- When evidence is insufficient, Qwen must select the canonical `unknown` ID.
- The worker checks this contract **before** the existing practical normalizer.
  Labels, aliases, near spellings, invented IDs, lists and extra categories fail
  instead of being normalized or silently converted to `unknown`.
- The adapter translates the validated ID to its canonical name for the existing
  semantic schema and retrieval renderer. It retains `category_selection` with
  ID, canonical name, taxonomy version and policy in the completed record.
- Cached metadata and completed-record readers verify the ID/name provenance.
  The importer keeps that full payload, so category provenance survives import.
- Topics, tags, activities, subjects, summaries and existing non-category
  extraction/normalization behavior remain unchanged. The raw Qwen response is
  still preserved by the existing attempt archive.

The new prompt is `extraction_prompt_v6_category_ids.txt`. Legacy prompt/config
files and all frozen run definitions remain unchanged for historical reading and
reproducibility. Use the new configuration for future extraction. Do not resume
an old frozen run with changed code/config: existing freeze checks require a new
run identity. No new processing run was started by this change.

## Catalogue category resolution

Original metadata remains authoritative: preserve the exact source label and
its existing taxonomy mapping. Equal source/Qwen categories deduplicate.
The optional `secondary_review` interface accepts at most one differing canonical
Qwen category only with a **trusted backend-supplied human evidence review**:
reviewer, matching semantic ID/category, explicit support decision, and an exact
passage from visual/audio/speech/motion evidence or transcript. Captions alone,
model self-approval, stale semantic IDs and fabricated passages do not qualify.

The caller must authenticate/trust review records; arbitrary model output is
never passed as a review. Literal quote matching alone does not prove entailment;
the independent reviewer supplies that judgment. No review records were created
or auto-accepted here. Without a review, disagreements remain withheld exactly
as in the existing staged catalogue. Effective categories never exceed original
mapped category plus one supported Qwen category. Database category views remain
conservative; no live view definitions were changed.

## Validation

38 backend/category tests pass, including cached-output worker validation with
model construction disabled and strict completed-record compatibility with the
existing semantic/embedding importer. Tests cover all 19 IDs, invalid names/IDs,
unknown, registry drift, immutable descriptions, legacy ambiguity, source
preservation, deduplication and evidence-gated secondaries.

All **58 existing CPU semantic tests also pass** in the existing Qwen environment.
The backend import environment initially lacked `huggingface_hub` for one mocked
download-helper test; using the already provisioned environment resolved that
without installing dependencies or downloading/running any model.
