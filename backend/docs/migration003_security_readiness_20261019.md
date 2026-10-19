# Migration 003 security readiness — 2026-10-19

Verdict: GO for a separately approved production deployment after fresh preflight/backup checks. NOT deployed by this task. This report supersedes the security-blocked deployment readiness of the original Migration 003. Existing production permissions, default privileges and data were not modified.

## Fix

Migration 003 now revokes ALL table privileges from PUBLIC, anon, authenticated AND service_role inside the creation transaction, before applying a precise allowlist. Re-granting SELECT alone did not remove production's default TRUNCATE grant; the explicit revoke does. No global ALTER DEFAULT PRIVILEGES statement is included in the migration.

A transaction-local DO assertion checks effective table AND column privileges for all three application roles. If unexpected rights remain through role membership or other grants, it raises an exception and rolls back creation, constraints, RLS, policy and ACL changes. There is no period of committed broad access. The assertion creates no persistent function.

| Role | Old migration under observed production defaults | Fixed migration |
|---|---|---|
| PUBLIC | None | None |
| anon | None after its existing revoke | None |
| authenticated | SELECT, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN | SELECT only, restricted to own rows by RLS |
| service_role | SELECT, INSERT, DELETE, TRUNCATE, REFERENCES, TRIGGER, MAINTAIN | SELECT, INSERT, DELETE; column UPDATE(category_id) only |

PostgreSQL requires UPDATE privilege on at least one column for SELECT ... FOR UPDATE. The existing repository uses this lock to serialize preference replacement alongside its per-user advisory lock. The new narrow UPDATE(category_id) grant supports this existing operation without granting table-wide UPDATE or identity/timestamp updates. No repository or API behavior was changed. Service_role remains a trusted server-only BYPASSRLS role, as it already is in Supabase; user identity remains verified by the existing Supabase Auth dependency and bound in every preference query. Authenticated/anon have no INSERT, UPDATE, DELETE or TRUNCATE rights, including column-level variants.

## Related-object review

A read-only production review confirmed authenticated does not inherit service_role, neither client role is superuser/BYPASSRLS, and service_role is BYPASSRLS as expected. The existing auth.uid() is STABLE and SECURITY INVOKER, is executable by authenticated, and auth schema USAGE is present. It returns the request identity used by the own-row SELECT policy. No auth functions or schema permissions were changed.

The preference table uses supplied UUID/category IDs and now() for created_at. No sequence, identity generator, standalone SQL function, SECURITY DEFINER function, RPC, new role or executable routine is introduced. The migration adds one table, its automatic row/array types, one composite primary-key index, two foreign keys with PostgreSQL's required internal referential-integrity triggers, and one SELECT RLS policy. The internal FK triggers on parent tables are expected dependency machinery, not application behavior changes. No unrelated table ACL, data, default privilege, function definition or existing category changes were observed in rehearsal.

## Security regression tests

backend/tests/test_migration003_security.py creates unique databases on 127.0.0.1:55439 only and never reads production connection settings. It reconstructs the exact recorded production table default ACL in each disposable database AFTER fixture creation. These ALTER DEFAULT PRIVILEGES statements are confined to those isolated databases; production and cluster roles are not altered.

Seven tests verify:

1. Legacy-equivalent migration grants reproduce the flaw: authenticated successfully truncates the entire isolated preference table despite RLS.
2. Fixed effective table/column permissions match the allowlist; actual TRUNCATE attempts by anon, authenticated and service_role are denied and all rows remain.
3. Users A/B see only their own rows; a session without a user claim sees none; anon cannot SELECT; clients cannot INSERT, UPDATE or DELETE another user's records.
4. The actual service-role repository can persist and retrieve multiple choices, repeat requests without changing timestamps, reject invalid/unknown/duplicate choices and clear one user's choices without affecting another.
5. Injected failure before COMMIT rolls back every new object, grant and internal FK trigger.
6. Reintroducing an excess grant causes the effective-permission guard to abort the whole migration.
7. Only expected objects appear; no sequence/function is created; existing taxonomy/auth data, auth.uid() definition/ACL and database defaults stay unchanged.

Full backend run with the opt-in security tests enabled: 121 tests PASSED, comprising all original 114 tests plus the seven new real-PostgreSQL regressions. The separate full eight-table onboarding integration rehearsal also PASSED with this exact migration, including concurrent updates and injected persistence failure rollback. Full fingerprints of all eight restored original tables remained unchanged. Production has no preference table yet.

The underlying TestClient currently emits a dependency deprecation warning for httpx; this does not affect results and no HTTP client stack migration was introduced here.

## Evidence and repeat commands

Machine-readable readiness, exact migration SHA-256, effective privilege evidence, production read-only related-permission review and checksums: backend/reports/migration003_security_20261019/. Full-data rehearsal: backend/reports/onboarding_20261019/integration_results.json. Earlier production-default evidence: backend/reports/migration003_production_20261019/default_privileges.json.

With the existing localhost PostgreSQL test server running:

```powershell
$env:ATARAXIA_LOCAL_SECURITY_TESTS='1'
backend/.venv-onboarding/Scripts/python.exe -B -m unittest discover -s backend/tests -p 'test_*.py'
Remove-Item Env:ATARAXIA_LOCAL_SECURITY_TESTS
backend/.venv-onboarding/Scripts/python.exe -B -m backend.tests.integration_onboarding
```

Without the opt-in flag, the seven database security tests are explicitly skipped, not silently reported as passed. The local server was stopped after final testing; evidence databases remain preserved locally.

## Remaining production steps

Revalidate the NEW migration checksum and production dependencies/default ACL/role memberships, confirm no conflicting preference table exists, take and restore-check a fresh backup, and apply only after separate authorization. The migration itself now fails closed on excess effective privileges. Do not reuse the original migration checksum or label the original 114-test rehearsal as a test of this new SQL. Production-authenticated endpoint verification still requires authorized test accounts; this security task creates no production accounts and bypasses no production authentication.

Files changed in this task: backend/migrations/003_user_interest_preferences.sql; new backend/tests/test_migration003_security.py; backend/docs/migration003_security_readiness_20261019.md; updated backend/docs/preference_onboarding.md. Runtime API/repository/sampler code, frontend, S3, video records and AI artifacts were not changed.
