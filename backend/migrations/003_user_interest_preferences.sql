-- PREPARED ONLY. Do not apply to production without explicit approval.
-- Requires the existing Supabase Auth and interest_categories tables.
BEGIN;
SET LOCAL lock_timeout='5s';
CREATE TABLE public.user_interest_preferences (
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  category_id text NOT NULL REFERENCES public.interest_categories(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(user_id,category_id)
);
ALTER TABLE public.user_interest_preferences ENABLE ROW LEVEL SECURITY;
-- GRANT does not replace Supabase's default ACL. Clear inherited table grants
-- explicitly, including TRUNCATE (which is not restricted by RLS).
REVOKE ALL ON TABLE public.user_interest_preferences FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.user_interest_preferences TO authenticated;
GRANT SELECT,INSERT,DELETE ON public.user_interest_preferences TO service_role;
-- PostgreSQL requires UPDATE on at least one column for SELECT ... FOR UPDATE.
-- The repository uses that lock during replacement; it does not UPDATE rows.
GRANT UPDATE(category_id) ON public.user_interest_preferences TO service_role;
CREATE POLICY preferences_read_own ON public.user_interest_preferences
  FOR SELECT TO authenticated USING(user_id=(SELECT auth.uid()));
-- No direct client writes: taxonomy validation and atomic replacement occur in
-- FastAPI after verification of the real Supabase access token.
-- Taxonomy is backend-only under existing RLS. Preference writes are intended
-- through the authenticated FastAPI service; no taxonomy grant is broadened.
-- Fail closed if role memberships or other grants still provide excess access.
DO $$
DECLARE role_name text; privilege_name text; column_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
    FOREACH privilege_name IN ARRAY ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN'] LOOP
      IF has_table_privilege(role_name,'public.user_interest_preferences',privilege_name)
         IS DISTINCT FROM (
           (role_name='authenticated' AND privilege_name='SELECT') OR
           (role_name='service_role' AND privilege_name IN ('SELECT','INSERT','DELETE'))
         ) THEN
        RAISE EXCEPTION 'Unexpected preference privilege: role %, privilege %',role_name,privilege_name;
      END IF;
    END LOOP;
    FOREACH column_name IN ARRAY ARRAY['user_id','category_id','created_at'] LOOP
      FOREACH privilege_name IN ARRAY ARRAY['SELECT','INSERT','UPDATE','REFERENCES'] LOOP
        IF has_column_privilege(role_name,'public.user_interest_preferences',column_name,privilege_name)
           IS DISTINCT FROM (
             (role_name IN ('authenticated','service_role') AND privilege_name='SELECT') OR
             (role_name='service_role' AND privilege_name='INSERT') OR
             (role_name='service_role' AND privilege_name='UPDATE' AND column_name='category_id')
           ) THEN
          RAISE EXCEPTION 'Unexpected preference column privilege: role %, column %, privilege %',role_name,column_name,privilege_name;
        END IF;
      END LOOP;
    END LOOP;
  END LOOP;
END $$;
COMMIT;
