# Migration 003 deployment — STOPPED before production changes

Date: 2026-10-19 (Asia/Karachi).

Migration 003 was NOT applied. No production schema objects or preference records were created. The existing migration file remains unchanged, SHA-256 4ca8737c24e2da1d5819048c07a84ce09ad7337b95d8052b9bcb52f90e666d6d.

## Critical pre-deployment finding

The actual production creator role postgres has default privileges on newly created public tables granting authenticated TRUNCATE, REFERENCES, TRIGGER and MAINTAIN. Migration 003 revokes privileges from PUBLIC and anon, but never revokes authenticated or service_role's inherited default privileges. GRANT SELECT adds SELECT; it does not remove an existing TRUNCATE grant. PostgreSQL row-level security does not govern TRUNCATE. Thus the proposed table would retain a table-wide deletion privilege for authenticated rather than only its intended own-row read access.

Earlier isolated tests did not reproduce the production default ACL and missed this issue. Production privileges were read from pg_default_acl/aclexplode without creating a test table. Evidence: backend/reports/migration003_production_20261019/default_privileges.json. Official PostgreSQL reference: https://www.postgresql.org/docs/17/ddl-rowsecurity.html .

Required correction BEFORE any future deployment: revoke ALL on the NEW preference table from PUBLIC, anon, authenticated and service_role, then grant authenticated SELECT and service_role SELECT/INSERT/DELETE as intended. Do not alter global default privileges or existing tables. Add a regression rehearsal using the production-equivalent default ACL and explicitly prove authenticated/anon cannot TRUNCATE or perform any other unintended operation. This correction was not implemented/applied because the deployment request explicitly required stopping on a critical issue.

## Checks completed

- Exact tested migration checksum passed; dependencies auth.users, auth.uid(), interest_categories and required Supabase roles exist.
- No conflicting production preference table; no active video-table writers at preflight.
- Two automatic watcher processes paused and startup temporarily disabled during backup/integrity checks; exact prior settings/processes restored afterward.
- Fresh native backup of all eight existing public video/taxonomy tables, plus separate native auth-schema backup of 27 Auth tables and schema dependencies. Both archive listings readable; both restored into isolated localhost PostgreSQL database ataraxia_m003_backup_f1bdb05b. Every video-table fingerprint, stored location/hash, and all 27 Auth table fingerprints matched.
- Backup scope is these public application tables plus Auth, not a full Supabase infrastructure/storage/vault/cluster-role backup. No production restoration was performed.
- Final repeatable-read verification: all original eight tables unchanged, all 1,140 video rows/S3 references unchanged, baseline 927 semantic/embedding-covered videos and 213 incomplete videos preserved, preference table still absent.
- No S3, frontend, playback, recommendation algorithm, AI pipeline or catalogue migration changes.

## API verification status

No authorized test-account email/password/token configuration was found. No production user was invented, created or impersonated. Production authenticated preference replacement/retrieval, user isolation and cold-start API tests were NOT executed. Deployment stopped before those phases. Existing isolated tests remain available but do not substitute for production authentication tests.

## Backups, recovery and artifacts

All artifacts are under backend/reports/migration003_production_20261019/ (ignored local evidence): preflight.json, default_privileges.json, auth_before.json, backup_manifest.json, restore_result.json, execution_report.json and maintenance.json.

- video_backup/video_tables.dump SHA-256: 51d2b5e10ae7276c121b4516ad7d52e2699bea8091b06a4b93b72759c16953e1.
- auth_backup.dump SHA-256: 62b9013871453329f6f6b0f5c7fd757da4a7e312798daeaaaaf748fa11145247.

No production rollback is needed because nothing was applied. The isolated restore server was stopped and restored evidence preserved. Existing watcher processes and sign-in startup entry are active again.

Only local backup/report artifacts and this deployment report were created; the preference feature source, migration and production objects were not changed in this deployment attempt.
