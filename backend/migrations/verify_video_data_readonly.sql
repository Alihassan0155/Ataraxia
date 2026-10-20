-- Read-only verification only. Run AFTER an explicitly approved migration.
BEGIN READ ONLY;
SELECT e.extname,n.nspname AS extension_schema,e.extversion
FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector';
SELECT c.relname AS table_name,c.relrowsecurity AS rls_enabled
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY 1;
SELECT format_type(a.atttypid,a.atttypmod) AS embedding_type
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relname='video_embeddings' AND a.attname='embedding' AND NOT a.attisdropped;
SELECT c.relname AS table_name,con.conname,con.contype,pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' ORDER BY 1,2;
SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1,2;
SELECT 'videos' AS table_name,count(*) AS rows FROM public.videos
UNION ALL
SELECT 'processing_runs' AS table_name,count(*) AS rows FROM public.processing_runs
UNION ALL
SELECT 'video_context' AS table_name,count(*) AS rows FROM public.video_context
UNION ALL
SELECT 'affect_annotations' AS table_name,count(*) AS rows FROM public.affect_annotations
UNION ALL
SELECT 'video_semantics' AS table_name,count(*) AS rows FROM public.video_semantics
UNION ALL
SELECT 'video_embeddings' AS table_name,count(*) AS rows FROM public.video_embeddings
UNION ALL
SELECT 'processing_jobs' AS table_name,count(*) AS rows FROM public.processing_jobs
UNION ALL
SELECT 'interest_categories' AS table_name,count(*) AS rows FROM public.interest_categories;
COMMIT;
