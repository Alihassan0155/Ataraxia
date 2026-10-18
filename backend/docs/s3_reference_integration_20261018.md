# S3 storage-reference integration preparation — 2026-10-18

Status: READY FOR SEPARATE PRODUCTION APPROVAL. No production writes performed. No S3 operations, new columns, playback endpoints, presigning APIs, catalogue migrations or model inference were introduced.

## Files

- `backend/video_data/repository.py`: conflict-row SQL preserves verified S3 media_uri, availability and media_sha256 during later metadata imports. A changed media hash is rejected for explicit reconciliation. Other metadata continues to update; original incoming metadata remains in payload with its canonical content hash. Ordinary local imports retain prior behavior. Conflict-time checks protect against concurrent insertion/update races.
- `backend/video_data/s3_references.py`: prepare/check/apply/rollback CLI. Scope is pinned to the original checksummed 1,140-ID manifest and the verified final S3 audit. No AWS SDK calls. Uses existing public schema without migrations.
- `backend/tests/test_s3_references.py`: scope, checksum tampering, remapping and approval-gate tests.
- `backend/tests/integration_s3_references.py`: isolated native restore and real PostgreSQL transaction/importer regressions. It never loads production credentials.

## Preview

Exactly 1,140 existing video records match; all 1,140 would change. Only media_uri and availability are updated. media_uri becomes the exact audited s3:// URI and availability becomes s3_verified. No inserts/deletions. Payloads, original categories, content_hash, media_sha256, original local paths inside payload, created_at and all unrelated fields are preserved. No affect/context/semantic/embedding/job/run/taxonomy updates occur.

Current production counts captured in the plan: videos 1,140; context 1,275; affect 1,144; semantics 1,019; embeddings 1,019; jobs 1,226; runs 19; taxonomy 19. Selected retrieval-ready videos: 927. Other 213 remain stored, without fabricated outputs. No catalogue views are installed by this utility.

## Artifacts and safety

Package: `backend/reports/s3_references_20261018/`.

- plan.json: every video ID, expected media hash, original and target storage values, and fingerprints of every other video column and all seven other tables.
- checksums.json: plan checksum.
- native_backup/video_tables.dump: fresh read-only native backup of all eight tables; readable table of contents and manifest accompany it.
- rehearsal.json: successful isolated restore, commit, idempotence, failure injection, conflict and rollback results; bound to exact plan, utility, importer and backup hashes.
- execution.jsonl: created only by a later apply/rollback invocation; fsynced intent and committed result. A lost acknowledgment can be reconciled through safe replay.

Execution requires explicit approval and an exact expected plan SHA-256, plus a successful rehearsal matching the exact code and backup. The transaction acquires the existing batch-writer advisory lock, locks all eight tables against writes and locks video rows. Full invariant comparison rejects concurrent processing/metadata changes; location changes must equal either saved original or target values. Post-update verification checks all 1,140 target locations and byte-level fingerprints of unrelated database records, including vector serialization, before commit. Timestamp serialization is fixed to UTC and aggregation ordering to C collation for portable fingerprints. Retrying an already applied plan changes zero rows.

The rollback restores only saved original media_uri/availability and uses the same invariant/conflict guards. If processing/metadata changed since preparation, execution or rollback refuses rather than silently overwriting data; review and refresh the plan as needed. Locks time out after five seconds. Existing processing writers are not stopped by preparation; at execution they must yield to the transaction or it safely fails to acquire locks.

## Verified rehearsal

A fresh native production dump was restored into a new localhost-only PostgreSQL database with pgvector 0.8.2. Full baseline fingerprints matched the plan. Real apply updated 1,140 rows; replay updated zero. Injected failure after five updates rolled back all changes. Conflicting storage and metadata edits were rejected atomically; competing row update was blocked. The importer preserved verified S3 fields while updating metadata and rejected changed media bytes. Ordinary local imports still worked. Rollback restored every original row/column; replayed rollback was a no-op. Catalogue validation remained at 927 retrieval-ready videos and 213 incomplete videos. The isolated server was stopped after testing; restored databases and all evidence remain local.

Backend suite: 92 tests passed, plus the separate PostgreSQL integration rehearsal.

## Commands after explicit approval

Run from E:\ALI\Ataraxia. This command has NOT been executed against production:

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.s3_references apply --package backend/reports/s3_references_20261018 --approved-production-write --expected-plan-sha256 81bbd55fd09d5fe0dbe9faaed6ceb904612bd9ff43dc438724f663d8fed02cf7
```

Rollback after a separately approved production update (also NOT executed):

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.s3_references rollback --package backend/reports/s3_references_20261018 --approved-production-write --expected-plan-sha256 81bbd55fd09d5fe0dbe9faaed6ceb904612bd9ff43dc438724f663d8fed02cf7
```

Offline validation, no database connection:

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.s3_references check --package backend/reports/s3_references_20261018
```

Blockers: production approval is pending. A later production drift requires fresh preparation/rehearsal; do not weaken guards or force a stale plan. No schema migration is required. Backup is application-table scoped, not a backup of unrelated Supabase system schemas, cluster roles or service configuration.
