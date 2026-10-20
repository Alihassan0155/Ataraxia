# Existing-project database audit (2026-10-17)

Scope: tracked/untracked backend, mobile source, annotation package, commands,
configs, migrations/schema filenames and environment-variable NAMES only. The
search excluded dependencies, caches, model weights and bulk media/log outputs.
Secret values were not displayed. This report does not establish what exists in
the user's external Supabase project.

## Findings before implementation

- backend/main.py had only `/` and `/health` FastAPI endpoints; requirements had
  FastAPI and Uvicorn. No database client, model, connection or storage utility.
- No Supabase imports, project reference, PostgreSQL SQL files, migrations,
  pgvector, database insertion/sync/retrieval utility or Storage bucket code was
  found in project source. Mobile was an Expo starter, not a Supabase integration.
- The existing annotation/.env listed Gemini/Hugging Face variables only. No
  inspected env file or process environment provided Supabase/DB variable names.
- The existing SQLite `jobs` and `attempts` in
  annotation/src/ataraxia/distributed/controller.py are a GPU scheduler, not a
  video-content database. They have not been replaced or modified.
- Gemini annotations: annotation/runs/gemini_full_remaining_20261012/predictions/
  gemini/annotations.jsonl; actual typed schema is annotation.common.VideoAnnotation.
- Semantic outputs: annotation/semantic_pipeline/runs/<run>/videos/<id>/<source-hash>/
  record.json, semantic_metadata.json, embedding_input.txt, embedding.npy, state.json.
  Frozen config/schemas/template/taxonomy remain under each run's definitions.
- Shared context/transcripts/acoustics and ready metadata exist in
  annotation/data/normalized/preprocessed_merged_v2. annotation/data is an existing
  junction to the repository data directory; historical absolute paths remain.
- Semantic pipeline uses text Qwen and BGE-M3 dense float32 normalized vectors;
  Gemini/Whisper/openSMILE artifacts are consumed, never recomputed for import.

## Coverage

| Requirement | Existing local state | New backend support |
| --- | --- | --- |
| videos | Files/CSV; no DB table found | Metadata + source/media references; full row retained |
| video_semantics | Completed JSON records | Versioned records, summary/category/topics/tags + full payload |
| video_embeddings | 1024-float NPY | pgvector(1024), model/revision/template/input hash |
| affect_annotations | Gemini/local-model JSONL | Typed scores + full probabilities/evidence/provenance payload |
| video_context | Transcript/context/acoustic files | Versioned text/features/context + original metadata |
| processing_runs | frozen.json/configuration.json | Source run identity and frozen semantic definitions |
| processing_jobs | state.json/local scheduler | Immutable per-stage state snapshots; original files unchanged |
| interest_categories | Existing taxonomy + aliases | Same labels/version; unknown excluded from onboarding |
| Supabase Storage | No local bucket/media integration found | Paths only; no upload or new bucket |
| Existing live tables | Not inspectable without connection config | Read-only catalog/bucket inspector; table mapping and compatibility check |

All eight database requirements were missing locally, not proven absent remotely.
After the code audit, the user identified the existing Supabase pooler endpoint
with a password placeholder. The ignored backend/.env now holds that template;
this does not reveal or verify its live tables. No new project was created.
The SQL file is a conditional proposal, NOT an assertion that new live tables are
necessary. It refuses to run when any named video-data table already exists;
equivalent differently named tables must be reviewed using the inspector. A table
map reuses compatible existing names; incompatible columns require a separate,
reviewed additive migration after the live schema is known. No automatic ALTER,
destructive migration, project creation or database write was performed.

## Minimal implementation boundaries

All new importer/database code lives under backend/video_data. Existing FastAPI
endpoints, mobile files and annotation pipeline source/configs are unchanged by
this database task. The reader reuses actual artifact and model-output validators.
It does not compare old run hashes against current source code or rewrite them;
it verifies records against their own frozen definitions and current source bytes.
An artifact whose sources have changed is rejected, not silently relabeled.

The backend targets the EXISTING Supabase PostgreSQL/pooler endpoint with psycopg
and SSL. There was no existing Supabase client to reuse in this checkout. No second
project is provisioned. Credentials are read privately from backend/.env or the
existing DATABASE_URL environment variable and never printed or put in reports.

## Validation limits

No PostgreSQL server, psql, Docker, configured DB connection, or psycopg driver was
available in the inspected environment. Live schema compatibility, SQL execution,
pgvector insertion/constraints, permissions and network connectivity remain
UNVERIFIED. Do not label mock tests a successful Supabase integration test.
Read-only `inspect` is the next step after the existing project connection is
configured privately; live migrations/writes still require explicit approval.
