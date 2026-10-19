# Security-fixed Migration 003 — production deployment results

Date: 2026-10-19, Asia/Karachi. Status: COMMITTED AND INDEPENDENTLY VERIFIED. Production HTTP verification remains pending runtime configuration and authorized test credentials. No backend application service was deployed.

## Applied SQL and created objects

Applied the exact tested backend/migrations/003_user_interest_preferences.sql, SHA-256 ae94ec6e8ef9f3bc5929c81acbcebbcc0ba608c49a2c83e5cc0059c7d1526b05. Commit: 2026-10-18 21:21:28 UTC / 2026-10-19 02:21:28 PKT. The existing BEGIN/COMMIT body was executed inside one guarded psycopg transaction; table/default/data verification ran before COMMIT. No SQL source edits occurred.

Created public.user_interest_preferences with user_id UUID, category_id text, created_at timestamptz NOT NULL DEFAULT now(); primary key (user_id,category_id), its unique index, two validated foreign keys (auth.users with ON DELETE CASCADE; existing interest_categories), required internal RI triggers, automatic row/array types, and preferences_read_own SELECT RLS policy. RLS is enabled. No sequence, persistent function, public RPC, role, catalogue view or unrelated application table was created.

Effective production table AND column privileges were checked inside the transaction and again independently after commit:

| Role | Access |
|---|---|
| PUBLIC / anon | None |
| authenticated | SELECT only; own rows through auth.uid() policy |
| service_role | SELECT, INSERT, DELETE; UPDATE(category_id) only for repository row locks |

TRUNCATE, REFERENCES, TRIGGER and MAINTAIN are denied to all three application roles; authenticated/anon cannot write preferences directly. Service-role table-wide UPDATE is denied; only its required category_id column grant exists. The existing service-role BYPASSRLS attribute was not changed. No production TRUNCATE probe, fake user, JWT claim impersonation or authentication bypass was performed; actual destructive denial probes were previously tested in isolation.

## Preflight, backups and integrity

The exact migration checksum and production default privileges matched the seven-regression security rehearsal. Dependencies, roles, foreign-key privileges and absence of a conflicting table passed. Automatic sync processes were suspended with PID/creation-time verification and their startup entry temporarily removed. No active video writers were present. The transaction acquired the existing advisory lock and locked all eight original tables against concurrent writes; it rejected any baseline drift before DDL.

The first count comparison used the earlier 927 baseline and detected 929. This was investigated before proceeding: the only differences were the two previously authorized/synchronized completions TT_7226324795363822890 and TT_7226754405708746027, adding exactly two context, semantic, embedding and success-job rows. Their immutable bundle hashes matched the durable queue/local artifacts. Every older row and hash was preserved; there were no unexpected changes. Therefore the fresh deployment baseline was 929 retrieval-ready and 211 incomplete, not stale 927/213.

Fresh native archives were created for the eight public video/taxonomy tables and the complete Auth schema. Both were restored into localhost database ataraxia_m003_fixed_*, with all original table fingerprints, S3 values and 27 Auth table fingerprints verified. The exact fixed migration was additionally rehearsed on this fresh restored copy with production-equivalent default table ACLs. Backup scope does not include Supabase storage/vault infrastructure or cluster roles.

- Video backup SHA-256: 6b772baeb00bda80860068e4fd3c6c64edd5fc50449239c2901f73d36f78bac6.
- Auth backup SHA-256: b402b8663426f1890cb848f76c5a0a20e28dcc2dfe3661de5a5af0528c963b01.

Post-commit repeatable-read validation verified all 1,140 video records and their exact audited S3 URIs/media hashes. All eight existing tables, original metadata/payloads, categories, affect/context records, historical semantics, vectors, run/job provenance, Auth data, existing functions and global default privileges were unchanged by this migration. Catalogue validation confirms 929 retrieval-ready and 211 incomplete videos. The original 927 bundles are all preserved, with the two prior authorized additions. The new preference table contains zero rows.

## Actual API and cold-start checks

Attempting to import the real FastAPI application for in-process HTTP tests stopped at its existing configuration guard. backend/.env contains SUPABASE_DB_URL but lacks SUPABASE_URL, SUPABASE_KEY, AWS_REGION and S3_BUCKET_NAME. There are also no configured authorized test-account credentials/tokens. Configuration was not invented, changed or printed; no server was started.

| Endpoint | Actual result |
|---|---|
| GET /onboarding/interests | HTTP pending due to missing application settings. Its real production service/repository query succeeded: 18 existing interests, unknown excluded, response schema valid. |
| GET /users/me/interests | Pending configured runtime and authorized Supabase access token. |
| PUT /users/me/interests | Pending configured runtime and authorized Supabase access token. No production preference writes attempted. |
| GET /recommendations/cold-start | Authenticated HTTP test pending configured runtime and authorized token. |

A separately labelled read-only data/algorithm probe found 1,140 eligible canonical-metadata videos with verified exact-ID S3 references, including 211 without embeddings. The pure sampler selected 50 unique videos from two sufficiently large category pools, balanced 25/25. This probe did not assign a user identity, save interests, bypass an endpoint or constitute an authenticated API test. No semantic/affect ranking was used.

Required next steps: configure the existing FastAPI settings privately, then use existing authorized test accounts to verify authenticated persistence/retrieval, invalid and duplicate IDs, cross-user isolation, and the cold-start HTTP response. Do not treat prior isolated tests or the read-only sampler probe as completed production-authentication tests.

## Evidence, recovery and cleanup

Artifacts: backend/reports/migration003_fixed_deployment_20261019/.

- migration_execution.json / migration_execution.jsonl: guarded commit and fsynced intent/result.
- baseline.json / authorized_catalogue_delta.json: verified current baseline and prior authorized additions.
- backup_manifest.json, video_backup/video_tables.dump, auth_backup.dump, restore_rehearsal.json.
- post_commit_audit.json: independent structure, permission, data and catalogue verification.
- api_configuration_check.json / api_verification.json: actual runtime blocker and read-only results. api_verification_error.json preserves the initial failed application-import attempt.
- recovery_information.json / completion.json / checksums.json / maintenance.json.

Both sync processes and their exact sign-in startup entry were restored after verification. The isolated PostgreSQL restore server was stopped; evidence databases and archives remain local. No production rollback was executed. A later additive rollback should preserve the new preference data and drop only the new table under separate approval; do not restore unrelated video/Auth tables or use CASCADE to bypass new dependencies.

Only local report/backup/helper artifacts and this documentation file were created during deployment. No frontend, source migration, S3 object/settings, AI pipeline, recommendation algorithm, unrelated database object or existing user record was modified.
