# Physical 1:1 deduplication — prepared, production execution NOT approved

The user explicitly requires separate approval after backup and exact-plan
validation. No production DELETE, UPDATE, INSERT or DDL has been performed by
this preparation. All destructive/schema/update rehearsals used only the new
dedicated localhost cluster at 127.0.0.1:55441. The original watcher was not
stopped, reconfigured or replaced during preparation.

## Retention and backup

Evidence directory: `backend/reports/physical_dedup_20261103/`.

| Table | Current | Retain | Delete after approval |
|---|---:|---:|---:|
| videos | 4,226 | 4,226 | 0 |
| video_context | 4,573 | 4,226 | 347 |
| affect_annotations | 2,774 | 2,486 | 288 |
| video_semantics | 2,368 | 2,276 | 92 |
| video_embeddings | 2,368 | 2,276 | 92 |
| processing_runs | 35 | 35 | 0 |
| processing_jobs | 2,575 | 2,575 | 0 |
| interest_categories | 19 | 19 | 0 |

All 819 noncanonical rows and their original provenance are in both the
checksum-verified JSONL backup package and a native pg_dump custom archive.
The native archive has been restored locally and compared against every
original row, including IDs, timestamps, payloads and complete vector values.
Supabase roles/grants were not recreated in the local fixture: pg_restore used
--no-owner --no-privileges; the production ownership, policies, grants and schema
inventory are preserved separately in backup/catalog.json. A production restore
requires the original roles and installed pgvector, which were not modified.

- `backup/`: all eight original tables, hashes, schema/security/dependency catalog.
- `native_backup/video_tables.dump`: 32,427,569-byte native recovery archive.
- `native_backup/contents.txt`: verified archive table-of-contents listing.
- `canonical/`: exact retained rows, preserving selected IDs and all values.
- `identities.json`: exhaustive retain/delete IDs for every table.
- `selection.json`: per-video selected IDs, timestamps and selection reason.
- `plan.json`: counts, dependencies, no required remappings, approval status.
- `migration_proposal_rollback.sql`: disabled proposal, ends in ROLLBACK.
- `rehearsal.json`, `watcher_rehearsal.json`: isolated restore/update tests.
- `queue_dependency_audit.json`: original watcher identity impact.
- `production_readonly_recheck.json`: live rows/hashes/constraints unchanged.
- `checksums.json`: integrity hashes; local database files excluded.

## Selection and dependency handling

The existing validators verify payload hashes, score/vector constraints and
cross-table source/run relationships. Selection requires Gemini 3.8 Flash,
Qwen/Qwen3-4B-Instruct-2507, and BAAI/bge-m3 revision
5617a9f61b028005a4858fdac845db406aefb181. Select the latest complete valid bundle
using the original completed_at; retain its exact context and affect references.
For videos without a complete bundle, retain the latest valid production affect
and authentic available context. Current duplicate contexts differ only in six
summary vs 88 eGeMAPS features, so the richer genuine representation wins where
no selected semantic FK fixes the choice. No context recency is inferred from
the bulk import created_at. No annotation placeholder is inserted.

There are no required FK remappings: retained semantics point only to retained
context/affect records; retained embeddings point to retained semantics. All
processing runs and jobs remain. History payloads and original local artifacts
remain authoritative evidence, including references to archived versions.

Watcher audit: all 1,111 synced semantic IDs are retained; its 92 superseded IDs
become archive-only history; zero pending/inflight IDs are affected. Never
rewrite those historical IDs to point at semantically different current rows.
Fresh dependency checks must stop on new inbound references requiring unsafe
remapping. No CASCADE deletion or TRUNCATE is part of this plan.

## Proposed constraints

Four unique indexes, one on video_id in each related table, enforce physical
1:1 correspondence. An additional unique semantic index on (id,video_id,run_id)
supports a composite embedding FK on (semantic_id,video_id,run_id). The FK is
DEFERRABLE INITIALLY DEFERRED so a new complete semantic/embedding version can
be upserted atomically in one transaction without a transient FK failure.
The existing primary keys, FKs, categories, video metadata and S3 URIs stay intact.

## Future writer cutover — staged only

`canonical_update_proposal.py` is NOT imported by the running watcher. It stages
stable-ID canonical upserts and a queue adapter; it has no production connection
factory. Every replaced version is durably archived before the database update.
New complete bundles update all related records in one transaction. Partial
results cannot overwrite a complete bundle. Older versions are ignored;
conflicting equal completion timestamps stop for review. Existing video metadata
is never upserted by this writer. Research outputs stay in source/version
archives rather than competing with production rows under unique(video_id).

Incoming artifact IDs can differ from stable destination IDs. Queue acknowledgments
must use the ORIGINAL source semantic ID; reconciliation compares source version
payload/run identity rather than equating it to the stable destination PK.
The local queue-adapter test covers this distinction with an already-validated
fixture. Actual source files continue to pass the existing Reader validators.

Approval must cover the coordinated importer/watcher deployment as well as the
819 deletions and proposed indexes/FK. Before resuming the watcher, wire the
staged adapter and version-aware reconciliation into batch_sync; preserve its
original 1,140-video scope, queue, startup registration and scheduling. Guard or
retire legacy Repository._put, full_sync.apply and catalogue replacement paths:
their immutable insert-only/history behavior is incompatible with physical 1:1.
The archived full-sync plan must never be replayed to repopulate historical rows.
These running entrypoints are intentionally not switched during preparation.

## Approved execution sequence (future)

1. Verify backup checksums and successful restore rehearsal; confirm approval.
2. Pause the exact watcher process tree and preserve its configuration/state.
3. Hold its OS queue lock and existing PostgreSQL advisory lock. Recheck schema,
   every original row/value and inbound dependencies under transaction locks.
   Any drift requires a refreshed backup/plan; do not bypass stale guards.
4. Delete only listed embedding IDs, then semantic IDs, then affect/context IDs.
   Abort/rollback on any unexpected affected count or dependency.
5. Create the unique indexes and deferred composite FK. Validate exact retained
   rows, all 4,226 untouched videos and final expected counts before COMMIT.
6. Enable tested canonical writers/reconciliation and disable historical replay
   paths before restoring the original watcher running state.
7. Verify live relationships, 1:1 counts, unchanged video/category/S3 data,
   idempotent delivery and watcher logs. Retain immutable backup and all archives.

Reversal must first stop writers and archive any intervening updates. Under
locks, remove only the newly approved indexes/FK and restore missing archived
rows in dependency order, refusing identity collisions. The original dump is
verified recovery evidence; do not blindly restore over a changed live database.
If no migration COMMIT occurs, PostgreSQL transaction rollback restores all rows
and removes the new DDL automatically; that rollback was exercised locally.

## Validation

Passed locally: full native restoration equality, transaction rollback, exact
canonical retention, repeat-delete idempotency, four uniqueness violations,
embedding cross-video FK rejection, future-update failure rollback, complete
update idempotency with stable IDs and a new processing run, partial/older-version
protection, and durable pre-update archival. Live production hash/constraint
recheck passed. Approval is still required; no production apply CLI is supplied.
