# Video database validation — 2026-10-17

## Executed locally

- Nine backend unittest cases passed after the final implementation changes.
- Read-only dry-run using the current semantic_full_v12 outputs validated 713
  completed semantic records/embeddings and 715 explicit Gemini annotations;
  two jobs remained incomplete. Zero failed artifact validations after supporting
  historical data-junction paths and nonfinite acoustic missing values.
- All-run dry-run validated 806 historical semantic/embedding versions covering
  714 unique semantic video IDs, plus 715 unique explicit Gemini video IDs.
  Total video entities: 715. This is a snapshot, not a claimed completed 900 videos.
- The all-run plan preserved 19 processing-run identities, 1011 job-state versions
  and 719 affect versions (some historical inputs have different source-run
  identities), with 205 incomplete state snapshots across all historical runs.
  These are not 205 unique current videos failing preprocessing.
- All-run artifact failures: zero. Database inserted/updated rows: zero.
  Model executions: zero. Media/Storage uploads: zero.
- Tests cover historical import, incremental run versions, unchanged skips,
  immutable conflict rollback, interrupted JSONL tails, corrupt/dimension/dtype/
  nonfinite/nonunit vectors, dry-run network isolation, table compatibility,
  credential redaction, existing data junctions and acoustic NaN missingness.
- Changed-file Git whitespace check passed for backend and .gitignore.

Detailed runtime reports (ignored local artifacts):
backend/reports/video_sync_validation/summary.json and
backend/reports/video_sync_all_runs/summary.json.

## Existing project and unverified checks

The user subsequently supplied the existing Supabase pooler endpoint with a
password placeholder. Its connection template is in ignored backend/.env; the
real password must be entered privately there, never in chat. Placeholder
connections are rejected before attempting network access. No project was created.

The existing LIVE database tables, columns, policies and Storage buckets remain
unknown. The initial checkout contained no Supabase implementation to reuse.
No actual schema migration, PostgreSQL insertion, pgvector round-trip or network
connection was executed. psycopg is not installed in the inspected GPU environment;
install backend/requirements-import.txt into a separate backend environment.
No local PostgreSQL server, psql or Docker was available for disposable SQL tests.
The SQL proposal and driver path therefore remain pending real compatibility
verification; mock/local unit tests do not prove live Supabase success.

Next: configure the existing project's password privately, run read-only inspect,
review equivalent tables, adapt the migration if needed, and obtain explicit
approval before applying a migration or using write flags. Read-only setup and
exact import/sync commands are in video_database.md. No inference changes or
full-dataset annotation were started by this work.
