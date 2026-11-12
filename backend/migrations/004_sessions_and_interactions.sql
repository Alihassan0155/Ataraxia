-- APPLIED TO THE CURRENT DEVELOPMENT SUPABASE PROJECT.
-- Do NOT rerun this migration against the current development project.
--
-- Adds authenticated viewing sessions and event-level feed interactions.
-- Intended execution role: the existing backend PostgreSQL role (currently
-- verified as "postgres"). That role owns the new tables and bypasses RLS.
-- Mobile clients must use FastAPI; they must not write these tables directly.
--
-- The migration was based on a read-only inspection of the live schema:
-- public.videos(video_id) and auth.users(id) existed before application.
--
-- Idempotency:
--   sessions.session_id         = client-generated viewing-session UUID
--   interactions.interaction_id = mobile event_id UUID
--
-- Uploads may arrive after ended_at is set. The backend must still permit
-- uploads for a session owned by the authenticated user.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.sessions (
    session_id uuid PRIMARY KEY,
    user_id uuid NOT NULL
        REFERENCES auth.users(id) ON DELETE CASCADE,
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,

    CONSTRAINT sessions_valid_end_time
        CHECK (ended_at IS NULL OR ended_at >= started_at)
);

COMMENT ON TABLE public.sessions IS
    'Authenticated feed-viewing sessions registered by the Ataraxia backend.';
COMMENT ON COLUMN public.sessions.session_id IS
    'Client-generated UUID; registration retries reuse the same identifier.';
COMMENT ON COLUMN public.sessions.user_id IS
    'Supabase Auth user ID, assigned by the backend and never trusted from mobile input.';

CREATE INDEX sessions_user_started_idx
    ON public.sessions (user_id, started_at DESC);

CREATE TABLE public.interactions (
    interaction_id uuid PRIMARY KEY,
    session_id uuid NOT NULL
        REFERENCES public.sessions(session_id) ON DELETE CASCADE,
    video_id text NOT NULL
        REFERENCES public.videos(video_id),
    event_type text NOT NULL,
    occurred_at timestamptz NOT NULL,
    watch_duration_ms bigint,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    received_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT interactions_valid_event_type
        CHECK (
            event_type IN (
                'impression',
                'watch',
                'completion',
                'skip',
                'rewatch'
            )
        ),

    CONSTRAINT interactions_nonnegative_watch_duration
        CHECK (
            watch_duration_ms IS NULL OR watch_duration_ms >= 0
        ),

    CONSTRAINT interactions_metadata_object
        CHECK (jsonb_typeof(metadata) = 'object')
);

COMMENT ON TABLE public.interactions IS
    'Event-level feed interactions ingested in authenticated batches by the Ataraxia backend.';
COMMENT ON COLUMN public.interactions.interaction_id IS
    'Mobile-generated event UUID; primary key makes repeated batch uploads idempotent.';
COMMENT ON COLUMN public.interactions.occurred_at IS
    'Client event timestamp in UTC; distinct from server-side received_at.';
COMMENT ON COLUMN public.interactions.watch_duration_ms IS
    'Accumulated actual playback duration for skip events; individual playback chunk duration for watch events.';
COMMENT ON COLUMN public.interactions.metadata IS
    'Event-specific metadata, including skip duration, watch percentage, and skip classification where available.';

CREATE INDEX interactions_session_occurred_idx
    ON public.interactions (session_id, occurred_at);

CREATE INDEX interactions_video_occurred_idx
    ON public.interactions (video_id, occurred_at);

-- RLS is enabled, with no direct client policies. The backend accesses these
-- tables through its trusted PostgreSQL connection. RLS is not a security
-- boundary for that connection because the current backend role has BYPASSRLS.
ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.interactions ENABLE ROW LEVEL SECURITY;

-- Clear Supabase/default ACLs explicitly. Table ownership remains with the
-- migration execution role; no direct table privileges are granted to clients
-- or service_role. The FastAPI backend uses the existing owner connection.
REVOKE ALL PRIVILEGES ON TABLE public.sessions
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL PRIVILEGES ON TABLE public.interactions
    FROM PUBLIC, anon, authenticated, service_role;

-- Fail closed if direct table-level or column-level privileges remain for
-- any client-facing Supabase role. This mirrors the privilege-audit approach
-- used by migration 003.
DO $$
DECLARE
    role_name text;
    privilege_name text;
    table_name text;
    column_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
        FOREACH table_name IN ARRAY ARRAY['sessions', 'interactions'] LOOP
            FOREACH privilege_name IN ARRAY ARRAY[
                'SELECT', 'INSERT', 'UPDATE', 'DELETE',
                'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN'
            ] LOOP
                IF has_table_privilege(
                    role_name,
                    format('public.%I', table_name),
                    privilege_name
                ) THEN
                    RAISE EXCEPTION
                        'Unexpected table privilege: role %, table %, privilege %',
                        role_name, table_name, privilege_name;
                END IF;
            END LOOP;

            IF table_name = 'sessions' THEN
                FOREACH column_name IN ARRAY ARRAY[
                    'session_id', 'user_id', 'started_at', 'ended_at'
                ] LOOP
                    FOREACH privilege_name IN ARRAY ARRAY[
                        'SELECT', 'INSERT', 'UPDATE', 'REFERENCES'
                    ] LOOP
                        IF has_column_privilege(
                            role_name,
                            format('public.%I', table_name),
                            column_name,
                            privilege_name
                        ) THEN
                            RAISE EXCEPTION
                                'Unexpected column privilege: role %, table %, column %, privilege %',
                                role_name, table_name, column_name, privilege_name;
                        END IF;
                    END LOOP;
                END LOOP;
            ELSE
                FOREACH column_name IN ARRAY ARRAY[
                    'interaction_id', 'session_id', 'video_id', 'event_type',
                    'occurred_at', 'watch_duration_ms', 'metadata', 'received_at'
                ] LOOP
                    FOREACH privilege_name IN ARRAY ARRAY[
                        'SELECT', 'INSERT', 'UPDATE', 'REFERENCES'
                    ] LOOP
                        IF has_column_privilege(
                            role_name,
                            format('public.%I', table_name),
                            column_name,
                            privilege_name
                        ) THEN
                            RAISE EXCEPTION
                                'Unexpected column privilege: role %, table %, column %, privilege %',
                                role_name, table_name, column_name, privilege_name;
                        END IF;
                    END LOOP;
                END LOOP;
            END IF;
        END LOOP;
    END LOOP;
END
$$;

COMMIT;

-- Post-application verification (run separately, read-only):
--
-- SELECT table_name
-- FROM information_schema.tables
-- WHERE table_schema = 'public'
--   AND table_name IN ('sessions', 'interactions')
-- ORDER BY table_name;
--
-- SELECT tablename, rowsecurity
-- FROM pg_tables
-- WHERE schemaname = 'public'
--   AND tablename IN ('sessions', 'interactions')
-- ORDER BY tablename;
--
-- SELECT tablename, indexname, indexdef
-- FROM pg_indexes
-- WHERE schemaname = 'public'
--   AND tablename IN ('sessions', 'interactions')
-- ORDER BY tablename, indexname;
--
-- SELECT
--     table_name,
--     grantee,
--     privilege_type
-- FROM information_schema.role_table_grants
-- WHERE table_schema = 'public'
--   AND table_name IN ('sessions', 'interactions')
-- ORDER BY table_name, grantee, privilege_type;
