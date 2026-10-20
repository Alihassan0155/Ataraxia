-- PROPOSAL ONLY. Inspect the EXISTING project and obtain approval before applying.
-- Never creates a Supabase project, Storage bucket, user/session/interaction table.
-- If equivalent video tables exist, STOP and adapt this migration to those tables.
BEGIN;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public'
             AND table_name IN ('videos','video_semantics','video_embeddings','affect_annotations',
                                'video_context','processing_runs','processing_jobs','interest_categories')) THEN
    RAISE EXCEPTION 'Existing video-data tables detected. Review/reuse them; do not create duplicates or run this proposal unchanged.';
  END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
-- Reuse an existing vector extension in ANY schema; do not move/reinstall it.
DO $$
DECLARE ns text;
BEGIN
  SELECT n.nspname INTO ns FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector';
  PERFORM set_config('search_path',format('pg_catalog,public,%I',ns),true);
END $$;

CREATE TABLE public.videos (
  video_id text PRIMARY KEY CHECK (video_id ~ '^[A-Za-z0-9_-]+$'),
  content_hash text NOT NULL CHECK (length(content_hash)=64), payload jsonb NOT NULL,
  title text, language text, source_dataset text, source_id text,
  duration_seconds double precision CHECK (duration_seconds>=0), orientation text,
  media_uri text, media_sha256 text,
  availability text NOT NULL DEFAULT 'local_reference_only',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.processing_runs (
  id text PRIMARY KEY, content_hash text NOT NULL, payload jsonb NOT NULL,
  kind text NOT NULL, name text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.video_context (
  id text PRIMARY KEY, video_id text NOT NULL REFERENCES public.videos(video_id),
  content_hash text NOT NULL, payload jsonb NOT NULL, transcript text,
  acoustic_features jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.affect_annotations (
  id text PRIMARY KEY, video_id text NOT NULL REFERENCES public.videos(video_id),
  run_id text NOT NULL REFERENCES public.processing_runs(id),
  content_hash text NOT NULL, payload jsonb NOT NULL, model text NOT NULL,
  valence double precision NOT NULL CHECK (valence BETWEEN -1 AND 1),
  arousal double precision NOT NULL CHECK (arousal BETWEEN 0 AND 1),
  recovery_suitability double precision NOT NULL CHECK (recovery_suitability BETWEEN 0 AND 1),
  emotions jsonb NOT NULL, dominant_emotion text NOT NULL,
  confidence double precision NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.video_semantics (
  id text PRIMARY KEY, video_id text NOT NULL REFERENCES public.videos(video_id),
  run_id text NOT NULL REFERENCES public.processing_runs(id),
  context_id text NOT NULL REFERENCES public.video_context(id),
  affect_id text NOT NULL REFERENCES public.affect_annotations(id),
  content_hash text NOT NULL, payload jsonb NOT NULL,
  primary_category text NOT NULL, semantic_summary text NOT NULL,
  topics jsonb NOT NULL DEFAULT '[]', tags jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.video_embeddings (
  id text PRIMARY KEY, video_id text NOT NULL REFERENCES public.videos(video_id),
  run_id text NOT NULL REFERENCES public.processing_runs(id),
  semantic_id text NOT NULL UNIQUE REFERENCES public.video_semantics(id),
  content_hash text NOT NULL, payload jsonb NOT NULL,
  model text NOT NULL, revision text NOT NULL, template_version text NOT NULL,
  input_hash text NOT NULL, embedding vector(1024) NOT NULL,
  CHECK (abs(vector_norm(embedding)-1)<0.0001),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.processing_jobs (
  id text PRIMARY KEY, video_id text NOT NULL REFERENCES public.videos(video_id),
  run_id text NOT NULL REFERENCES public.processing_runs(id),
  content_hash text NOT NULL, payload jsonb NOT NULL,
  stage text NOT NULL, status text NOT NULL, attempts integer NOT NULL CHECK (attempts>=0),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.interest_categories (
  id text PRIMARY KEY, taxonomy_version text NOT NULL, name text NOT NULL,
  content_hash text NOT NULL, payload jsonb NOT NULL,
  aliases jsonb NOT NULL DEFAULT '[]', subcategories jsonb NOT NULL DEFAULT '[]',
  is_onboarding boolean NOT NULL, UNIQUE(taxonomy_version,name),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON public.video_semantics(video_id,run_id);
CREATE INDEX ON public.affect_annotations(video_id,model);
CREATE INDEX ON public.processing_jobs(run_id,video_id);
-- No ANN/search/recommendation algorithm is introduced by this storage migration.
DO $$
DECLARE t text; vector_ns text;
BEGIN
  SELECT n.nspname INTO vector_ns FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector';
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO service_role',vector_ns);
    GRANT USAGE ON SCHEMA public TO service_role;
  END IF;
  FOREACH t IN ARRAY ARRAY['videos','processing_runs','video_context','affect_annotations',
    'video_semantics','video_embeddings','processing_jobs','interest_categories'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',t);
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon') THEN
      EXECUTE format('REVOKE ALL ON public.%I FROM anon',t);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN
      EXECUTE format('REVOKE ALL ON public.%I FROM authenticated',t);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
      EXECUTE format('GRANT SELECT,INSERT,UPDATE ON public.%I TO service_role',t);
    END IF;
  END LOOP;
END $$;
COMMIT;
