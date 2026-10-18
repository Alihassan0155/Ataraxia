# Supabase schema compatibility audit — 2026-10-17

Status: audit and SQL preparation only. No migration or import was executed.
No annotation code, configuration, predictions or environments were changed.

## Evidence and existing schema

Parsed the complete `backend/reports/video_sync/schema_report.json`: 433 column
entries, 373 formatted-type entries, 136 constraints and six extensions.
Compared `video_data/config.py`, `repository.py`, `artifacts.py`, the CLI,
existing SQL proposal and `VideoAnnotation` score definitions. A fresh live
catalog inspection ran in an explicitly READ ONLY transaction and saved
`backend/reports/video_sync/schema_detail_readonly.json` (ignored local report).
No credentials or application/authentication data rows were exported.

- `public` exists, but contains no tables, views, materialized views or foreign
  tables. There are no differently named application relations in other
  non-managed schemas either. Thus there are no existing application tables to
  reuse or rename. Supabase-managed auth/storage/realtime/vault structures remain
  untouched; their constraints and indexes were inventoried, not altered.
- No public primary keys, foreign keys or indexes exist.
- Application row counts: not applicable, because no application tables exist;
  this is not a claim that Supabase-managed tables contain zero rows. Exact
  counts were requested for every discovered non-managed application table;
  there were none. Auth/user row counts were intentionally not queried.
- `vector` **0.8.2** is installed in `extensions`. No installation, upgrade or
  namespace move is needed. The other installed extensions are plpgsql,
  pg_stat_statements, uuid-ossp, pgcrypto and supabase_vault.
- The saved report lists no Storage buckets. Creating media buckets is outside
  this migration.
- `video_embeddings.embedding` does not exist, so there is no current vector
  dimension to correct. The proposed new column is `vector(1024)`.

## Why compatible is false

The checker expects eight actual persistence tables. Every required column and
primary key is reported missing because its entire table is absent. Its
`embedding must be pgvector vector(1024)` message reflects an absent table/column,
not an existing wrong-dimension vector. The extension check already passes.
This is genuinely missing database infrastructure, not evidence of corrupted
records or a reason to weaken the backend contract.

| Table | Current state / rows | Proposed minimum structure |
| --- | --- | --- |
| videos | Absent / N/A | text video_id PK; source/media metadata; content hash and full JSON payload |
| processing_runs | Absent / N/A | text id PK; kind/name; frozen run payload and hash |
| video_context | Absent / N/A | text id PK; video FK; transcript/acoustic JSON and original payload |
| affect_annotations | Absent / N/A | text id PK; video/run FKs; affect scores, emotion JSON, confidence and payload |
| video_semantics | Absent / N/A | text id PK; video/run/context/affect FKs; category, summary, topic/tag JSON and payload |
| video_embeddings | Absent / N/A | text id PK; video/run FKs; non-unique indexed semantic FK; model/revision/template/input hash; vector(1024) |
| processing_jobs | Absent / N/A | text id PK; video/run FKs; stage/status/attempts and snapshot payload |
| interest_categories | Absent / N/A | text id PK; unique taxonomy-version/name; aliases/subcategories/onboarding flag and payload |

The proposed affect ranges match the existing annotation model: valence [-1,1],
arousal/recovery/confidence [0,1]. Embedding dimension and unit-norm check match
the existing importer validation. No embedding transformation is introduced.

## Prepared SQL and approval plan

1. Review `backend/migrations/002_video_data_audited_empty_schema.sql`.
   This is a **standalone alternative replacing the unexecuted 001 proposal**,
   not a migration to run after 001. Do not apply both.
2. Obtain explicit approval before executing it in the existing project's SQL
   editor as an authorized database owner. Nothing auto-applies SQL.
3. The transaction refuses to proceed if ANY public application relation now
   exists or if the vector namespace differs. Re-audit rather than remove the
   guards on failure. Plain CREATE TABLE also rejects name collisions; it does
   not silently accept incompatible structures.
4. Creates only the eight missing tables, their PK/unique/FK/check constraints,
   three non-unique workflow indexes, and backend-only access controls. Existing
   pgvector is reused. No ANN index or retrieval algorithm is necessary for
   storage compatibility. No existing-table changes or data inserts occur.
5. All new tables get RLS. PUBLIC/anon/authenticated access is revoked on those
   new tables only; service_role gets SELECT/INSERT/UPDATE. Backend uses its
   configured PostgreSQL account. No mobile read policies are added implicitly.
6. After approval and execution, run the read-only verification below. Import
   still needs separate explicit approval; do not run sync with write flags.

## Risks and limits

- No existing application data can be rewritten by this proposal: none exists,
  and the script contains no data insert/update/delete/drop/truncate. Concurrent
  schema changes can invalidate the audit; the guard rejects public collisions.
- Migration still requires owner/DDL privileges and briefly takes catalog locks.
  Five-second lock and 30-second statement limits cause rollback on contention.
  Execution has not been tested against a writable database; prepared SQL is not
  claimed as successfully applied.
- RLS intentionally provides no public/mobile access. App read policies and
  playable media hosting need a separate design/approval.
- The existing checker verifies names, required columns, PKs, vector extension
  and vector dimension; it does not fully verify every column type, FK, index,
  default, RLS policy or grant. This audit does not equate its eventual `true`
  with a full application security or integration test. The verification SQL
  additionally lists constraints, indexes, RLS flags and exact counts.
- Managed schemas were not counted or sampled. Original file artifacts remain
  authoritative and untouched. No models, downloads or inference were executed.

## Verify after an approved migration

From repository root (no import):

```powershell
.\backend\.venv-import\Scripts\python.exe -m backend.video_data inspect
Get-Content .\backend\reports\video_sync\schema_report.json -Raw | ConvertFrom-Json | Select-Object -ExpandProperty compatibility
```

In the Supabase SQL editor, run
`backend/migrations/verify_video_data_readonly.sql`. It is explicitly READ ONLY.
Expect eight public tables, eight primary keys, the documented foreign keys,
`vector(1024)`, RLS enabled, and zero rows in all eight tables before any import.
Stop on discrepancies. Do not apply 001 afterward or import data automatically.

## Pre-application revision: embedding versions and artifact checks

Removed UNIQUE from video_embeddings.semantic_id, retaining its NOT NULL and FK.
Added non-unique indexes on video_embeddings.semantic_id and
video_semantics.primary_category. Existing id primary keys remain unchanged.

Read-only local artifact snapshot: 4,226 ready metadata rows, 1,010 affect
annotation records across seven JSONL files, and 858 semantic record files.
All 4,226 distinct observed IDs satisfy the SQL ID pattern. No malformed scanned
records, deferred partial lines or score-range violations were found. Observed
valence [-0.72,0.88], arousal [0.15,0.88], recovery [0,0.92], confidence [0.75,0.95]
fit their unchanged SQL bounds. Counts include historical/repeated versions,
not 1,010 unique annotated videos. Local snapshot details are saved in
backend/reports/video_sync/migration_002_artifact_validation.json.

Static extraction of the updated DDL's columns, primary keys and vector type
passes the actual repository.compatibility function with compatible=true.
This is a static contract check, not PostgreSQL execution or live compatibility.
The live database remains incompatible until an approved migration is applied.

Subsequent importer fix: embedding IDs now hash a versioned identity containing
video_id, semantic_id, run_id, model, revision, template_version and input_hash.
The semantic foreign key remains unchanged. Repeated identities skip safely;
different embedding versions have distinct IDs. Eleven local unit tests pass,
including duplicate imports, each version component and the real reader path
using synthetic artifacts. These are not live PostgreSQL tests. No schema
migration or import was executed. Previously imported legacy semantic-only IDs
would require a separately reviewed reconciliation; this change does not rewrite
or delete database rows automatically.
