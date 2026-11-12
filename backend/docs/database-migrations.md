# Database migrations: Ataraxia

## Current migration policy

Migrations in `backend/migrations` are versioned SQL artifacts. Their
application status is recorded individually below. A prepared migration must
not be assumed to have been applied to any Supabase project.

The current development work continues on the existing Supabase project.
The team intends to migrate to a new Supabase project before final evaluation.
Do not apply a migration, change dashboard configuration, or migrate/delete
project data without explicit team approval.

The live database schema inspected for the interaction-tracking work contained
`public.videos` and the existing video-processing tables. At that inspection,
`public.sessions` and `public.interactions` did not exist. The live database,
not an older draft migration, is authoritative.

## Migration 004: sessions and interactions

File: `backend/migrations/004_sessions_and_interactions.sql`

Status: **APPLIED TO CURRENT DEVELOPMENT PROJECT - 2026-11-12**

### Application record

- Target: the team's existing development Supabase project.
- Applied: 2026-11-12, with explicit team approval.
- Execution role: `postgres` (the existing backend database role).
- Verification: both tables, columns, constraints, indexes, RLS, and
  effective table privileges were inspected after application.
- Repository integration: session registration, event insertion,
  idempotent retry, session closure, late upload, persistence, and cleanup
  were successfully verified against the development database.
- Migration-history ledger: no matching migration-history table or entry
  was found during inspection. Application is documented here instead.
- Important: do not rerun this migration against the current development
  project. Apply it separately to a future project only after approval.

### Purpose

- Register authenticated feed-viewing sessions.
- Store individual feed interaction events.
- Make event ingestion idempotent using the client-generated event UUID.
- Preserve both client event time (`occurred_at`) and server receipt time
  (`received_at`).

### Schema

`public.sessions` stores:

- `session_id`: client-generated UUID primary key.
- `user_id`: Supabase Auth user UUID, assigned by the backend.
- `started_at`: session start timestamp.
- `ended_at`: nullable session end timestamp.

`public.interactions` stores:

- `interaction_id`: mobile event UUID primary key.
- `session_id`: viewing-session foreign key.
- `video_id`: foreign key to `public.videos(video_id)`.
- `event_type`: impression, watch, completion, skip, or rewatch.
- `occurred_at`: client event timestamp.
- `watch_duration_ms`: optional playback duration.
- `metadata`: event-specific JSON object.
- `received_at`: database receipt timestamp.

A skip event's metadata may contain `video_duration_ms`,
`watch_percentage`, and `skip_classification`. The backend must validate
metadata and request size before insertion. The database constraints are
additional safeguards, not a replacement for API validation.

### Security model

The backend currently connects as PostgreSQL role `postgres`. A read-only
inspection reported `rolsuper = false`, `rolcreaterole = true`,
`rolcreatedb = true`, and `rolbypassrls = true`.

The migration enables RLS and grants no direct table privileges to `PUBLIC`,
`anon`, `authenticated`, or `service_role`. The existing backend connection
owns the tables and performs writes. Since that connection bypasses RLS,
application-level authentication and ownership checks are mandatory:

1. Validate the Supabase bearer token using the existing FastAPI dependency.
2. Derive the user UUID from the verified token; never accept a user UUID as
   authoritative mobile input.
3. On session registration, bind the client-generated session UUID to that
   authenticated user. A repeated registration is successful only when the
   existing session belongs to the same user.
4. Before inserting a batch, verify every referenced session belongs to the
   authenticated user and every referenced video exists.
5. Use one database transaction for a batch. Insert with conflict handling on
   `interaction_id`; acknowledge both newly inserted and already-existing
   IDs only after the transaction succeeds.
6. Permit queued events to arrive after `ended_at` is set, while continuing
   to enforce session ownership.

The migration deliberately does not create direct client RLS policies.

### Preconditions

Before applying this migration, perform a fresh read-only inspection and
confirm:

- `auth.users(id)` exists.
- `public.videos(video_id)` exists and is the intended video catalogue table.
- `public.sessions` and `public.interactions` do not already exist.
- The execution role is the intended trusted backend database role.
- Supabase roles `anon`, `authenticated`, and `service_role` exist.
- The team has explicitly approved applying the migration to the target project.

Do not paste database URLs, passwords, service-role keys, or access tokens into
source control or chat.

### Application procedure (only after approval)

1. Back up/export the target project's database schema and any relevant data.
2. Confirm the target project and execution role.
3. Review the complete SQL file.
4. Apply the migration once using the approved database migration process.
5. If any statement fails, confirm the transaction rolled back before retrying.
6. Run the read-only verification queries at the bottom of the SQL file.
7. Confirm both tables exist, RLS is enabled, expected indexes exist, and no
   direct grants exist for `anon`, `authenticated`, or `service_role`.
8. Record the target project identifier (not credentials), date, operator,
   migration filename, and verification outcome in the team's migration log.

### Rollback

Do not automatically roll back after events have been collected.

If the migration was applied but no production/test data needs preserving,
and the team explicitly approves rollback, the dependency order is:

1. Drop `public.interactions`.
2. Drop `public.sessions`.

If either table contains useful events, export and verify that data before any
rollback. Dropping these tables is destructive and removes the interaction
history. Do not use `CASCADE` casually; investigate dependent objects first.

## Future Supabase project migration

Before final evaluation, document and verify migration of:

- Auth users and supported identity-provider configuration.
- Database schema and migration history.
- Required database extensions, roles, grants, and RLS policies.
- Storage buckets, objects, policies, and object metadata.
- Environment variables and secret rotation.
- Auth redirect URLs and application configuration.
- Backend database connectivity and API authentication.
- User preferences, sessions, and interaction data where required.

Never copy secrets into repository documentation. Verify the new project with
read-only schema checks and controlled test accounts before switching the
mobile and backend environment configuration.
