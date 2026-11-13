-- Ataraxia persistent per-user video Like/Unlike state.
-- Apply only to the confirmed current development Supabase project.
--
-- Mobile clients must access this table through authenticated FastAPI routes.
-- The backend uses its existing trusted PostgreSQL connection.
--
-- Unlike is represented by is_liked = false, not by deleting the row.
-- This preserves explicit feedback history at the current-state level.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TABLE public.user_video_feedback (
    user_id uuid NOT NULL
        REFERENCES auth.users(id) ON DELETE CASCADE,

    video_id text NOT NULL
        REFERENCES public.videos(video_id) ON DELETE CASCADE,

    is_liked boolean NOT NULL DEFAULT true,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT user_video_feedback_pkey
        PRIMARY KEY (user_id, video_id)
);

COMMENT ON TABLE public.user_video_feedback IS
    'Current explicit Like/Unlike state for each authenticated user and video.';

COMMENT ON COLUMN public.user_video_feedback.is_liked IS
    'True for an active Like; false for an explicit Unlike. Unlike is not negative preference evidence.';

COMMENT ON COLUMN public.user_video_feedback.created_at IS
    'Timestamp when the user first expressed feedback for this video.';

COMMENT ON COLUMN public.user_video_feedback.updated_at IS
    'Timestamp when the current feedback state was last changed.';

-- Supports future queries for videos with feedback, independently of user.
CREATE INDEX user_video_feedback_video_idx
    ON public.user_video_feedback (video_id);

-- No direct Supabase client access. FastAPI uses the trusted backend
-- PostgreSQL connection, consistent with migration 004.
ALTER TABLE public.user_video_feedback ENABLE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE public.user_video_feedback
    FROM PUBLIC, anon, authenticated, service_role;

-- Fail closed if inherited/default or column-level grants remain.
DO $$
DECLARE
    role_name text;
    privilege_name text;
    column_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
        'anon', 'authenticated', 'service_role'
    ] LOOP

        FOREACH privilege_name IN ARRAY ARRAY[
            'SELECT', 'INSERT', 'UPDATE', 'DELETE',
            'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN'
        ] LOOP
            IF has_table_privilege(
                role_name,
                'public.user_video_feedback',
                privilege_name
            ) THEN
                RAISE EXCEPTION
                    'Unexpected feedback table privilege: role %, privilege %',
                    role_name, privilege_name;
            END IF;
        END LOOP;

        FOREACH column_name IN ARRAY ARRAY[
            'user_id', 'video_id', 'is_liked', 'created_at', 'updated_at'
        ] LOOP

            FOREACH privilege_name IN ARRAY ARRAY[
                'SELECT', 'INSERT', 'UPDATE', 'REFERENCES'
            ] LOOP
                IF has_column_privilege(
                    role_name,
                    'public.user_video_feedback',
                    column_name,
                    privilege_name
                ) THEN
                    RAISE EXCEPTION
                        'Unexpected feedback column privilege: role %, column %, privilege %',
                        role_name, column_name, privilege_name;
                END IF;
            END LOOP;

        END LOOP;
    END LOOP;
END
$$;

COMMIT;

-- Read-only post-application verification:
--
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_schema = 'public'
--   AND table_name = 'user_video_feedback'
-- ORDER BY ordinal_position;
--
-- SELECT tablename, rowsecurity
-- FROM pg_tables
-- WHERE schemaname = 'public'
--   AND tablename = 'user_video_feedback';
--
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE schemaname = 'public'
--   AND tablename = 'user_video_feedback'
-- ORDER BY indexname;
--
-- SELECT grantee, privilege_type
-- FROM information_schema.role_table_grants
-- WHERE table_schema = 'public'
--   AND table_name = 'user_video_feedback';
