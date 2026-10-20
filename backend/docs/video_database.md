# Existing Supabase project: video import and incremental sync

Use the existing project only. No frontend, users, sessions, interactions, model
inference, recommendation algorithm or Storage bucket provisioning is included.
The existing FastAPI health endpoints are unchanged; this is an internal backend
repository and CLI, not an unauthenticated HTTP write endpoint.

## Setup without changing frozen annotation environments

From E:\ALI\Ataraxia (repository root):

```powershell
py -3.12 -m venv .\backend\.venv-import
.\backend\.venv-import\Scripts\python.exe -m pip install -r .\backend\requirements-import.txt
if (!(Test-Path .\backend\.env)) { Copy-Item .\backend\.env.example .\backend\.env }
notepad .\backend\.env
```

Enter the EXISTING Supabase project's PostgreSQL/pooler URI into SUPABASE_DB_URL,
or reuse an existing DATABASE_URL. Do not paste it in chat, command arguments,
mobile configuration or source control. Use a server-side database account with
approved privileges. SSL is required. No Supabase SDK or service-key exposure to
mobile is necessary. The default target schema is public. Do not use the GPU
environment for pip installs; shared package changes can break its frozen runs.

## First: inspect and review existing infrastructure

```powershell
.\backend\.venv-import\Scripts\python.exe -m backend.video_data inspect
```

This runs a read-only transaction over catalogs and Storage bucket metadata. It
does not create/change tables or buckets, nor read user/session data rows.
The local report is backend/reports/video_sync/schema_report.json. It lists
tables, columns, constraints, vector types, extensions and bucket names. If the
account cannot inspect storage.buckets, inspection fails explicitly; use approved
read privileges rather than suppressing that error. Reports never contain the DSN.

Review equivalent existing tables first. For compatible tables with different
names, copy video_data/table_map.example.json to a local file and edit the names,
then pass --table-map <file> to inspect and sync. The repository verifies required
columns, primary keys and vector(1024) before writes. Column adaptation is NOT
guessed. Partial compatibility requires a reviewed incremental migration that
extends the actual tables; the proposal must not be used to create duplicates.

backend/migrations/001_video_data_proposal.sql is ONLY for an existing project
whose schema review confirms none of the required/equivalent video tables exist.
It preserves all unrelated tables and enables RLS, denies public/anon/authenticated
access and allows the backend service role. It adds pgvector only if missing and
reuses its existing namespace. The migration is transactional and refuses named
table collisions. No DROP/TRUNCATE or user/session tables are included.

**Do not execute the migration without reviewing schema_report.json and obtaining
explicit approval.** It can then be applied once in the EXISTING project's SQL
editor by an authorized owner. No automatic migration command is provided. Inspect
again afterward to verify the resulting schema before any import.

## Local dry-run: no connection or credentials required

```powershell
.\backend\.venv-import\Scripts\python.exe -m backend.video_data sync --run semantic_full_v12 --report-dir .\backend\reports\dry_run
```

Omit --run to scan all initialized semantic runs, preserving their separate
versions. Repeat --run for an explicit subset. Default affect input is the current
full Gemini annotations JSONL. Additional historical/local-model inputs can be
specified with repeatable --affect paths relative to annotation/; when supplied
they replace the default list. Example:

```powershell
.\backend\.venv-import\Scripts\python.exe -m backend.video_data sync --affect runs/gemini_full_remaining_20261012/predictions/gemini/annotations.jsonl --affect outputs/reels_30h/gemini/annotations.jsonl
```

Metadata-only records with no processed output are not imported by default.
Affect-only videos can be imported before semantics/embeddings finish. Incomplete
semantic jobs are stored as job snapshots, never manufactured as completed records.
No raw media is uploaded. media_uri may be a local Windows path and availability
is local_reference_only; this does NOT mean it is accessible to a mobile client.

## Approved imports (do not run before live-write approval)

After approval and a compatible inspected schema:

```powershell
# Historical import, all initialized runs and default Gemini predictions:
.\backend\.venv-import\Scripts\python.exe -m backend.video_data sync --apply --allow-live-writes

# Foreground incremental sync; Ctrl+C stops polling:
.\backend\.venv-import\Scripts\python.exe -m backend.video_data sync --apply --allow-live-writes --watch --poll-seconds 60
```

Repeat either command to resume. Both write flags are required. An interrupted
bundle is rolled back; a committed bundle is skipped on retry by its database
content hash/primary key. There is no fragile local-only cursor to lose or trust
against a different database. Immutable payload collisions abort that transaction;
they are never overwritten. Remote connectivity failures are reported without
credential-bearing exception text; rerun after recovery. Foreground polling
reopens a connection each pass; it is not a Windows background service.

The mutable videos row describes current ready_metadata.csv metadata. Every
imported context version also preserves its original metadata row. Semantic,
embedding, annotation, run and job-snapshot versions are immutable. Identity
includes frozen run/source/content hashes, so a new legitimate run/version creates
another record rather than replacing earlier research evidence. The schema has
no automatic "latest/best annotation" selection or ranking.

## Data validation and storage

- Existing complete_record validates frozen record/schema, file hashes, taxonomy,
  embedding model/settings and NPY shape/dtype/unit norm. The importer additionally
  verifies Gemini/source fingerprints, semantic references and rendered input.
- V2 unverified_fields/source_provenance stay intact; no claims are promoted to
  verified or summaries regenerated for DB insertion.
- Eight emotion probabilities/scores use the actual shared Pydantic validator.
  Raw predictions, raw local-model points and calibration provenance are retained
  in payload JSON; the importer does not recalibrate anything.
- Embedding uses vector(1024), retains model/revision/template/input hash, and
  rejects nonfinite or non-normalized vectors instead of fixing them.
- Acoustic NaN/Infinity values become JSON null with explicit field-path markers;
  the original source artifact is untouched. Other scalar/content validation is
  not relaxed. This is serialization of missingness, not acoustic recomputation.
- interest_categories reuses taxonomy.json and existing category aliases. unknown
  remains a canonical classification but is_onboarding=false.
- Full JSON payloads preserve fields not promoted to typed columns. Contexts also
  keep original metadata; runs keep frozen semantic definitions and affect source
  path/configuration identity. File paths are references, not stored media bytes.

Supabase supports PostgreSQL vector columns through pgvector:
https://supabase.com/docs/guides/ai/vector-columns
pgvector's vector_norm and vector type constraints:
https://github.com/pgvector/pgvector

## Reports, tests and counts

summary.json reports successful/skipped bundles, incomplete job snapshots, failed
artifacts, entity counts and database changes. These are NOT all unique-video
counts: a video can have several research versions and job snapshots. Models and
Storage upload counters remain zero. Partial JSONL tail records defer until a
complete newline; duplicate unchanged records are skipped. Validation errors
produce exit 1; setup/schema/connection failures produce exit 2.

```powershell
.\backend\.venv-import\Scripts\python.exe -m unittest discover -s backend/tests -t . -v
```

Tests use real artifact validators and a transaction-aware in-memory target; no
network, database writes, model loading or downloads occur. They cover historical
import, duplicate/resume handling, incremental version retention, bad vectors,
source checks, dry-run isolation, schema mapping, credential repr and nonfinite
acoustics. A passing local suite is NOT evidence of live Supabase/pgvector testing.
