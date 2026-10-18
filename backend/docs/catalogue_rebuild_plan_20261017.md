# Clean video catalogue: prepared, NOT applied

Approved planning scope: retain exactly the **1,140 currently imported video IDs**.
The user selected this scope during preparation. No production replacement has
been approved. No database writes or model calls were performed. Pilot/held-out
processing stays excluded. No frontend, user data, or model pipeline changed.

## Frozen audit and staging result

Production snapshot: `backend/reports/catalogue_rebuild_20261017/production_snapshot/`.
Snapshot manifest timestamp: **2026-10-17 18:08:04 UTC / 23:08:04 Asia/Karachi**.
Local record discovery is a fixed file list; later completions are not silently
added. Counts below describe this stage, not an indefinitely live worker status.

| Table | Production rows | Production unique videos | Clean staged rows |
|---|---:|---:|---:|
| videos | 1,140 | 1,140 | 1,140 |
| video_context | 1,166 | 1,140 | 1,140 |
| affect_annotations | 1,144 | 1,140 | 1,140 |
| video_semantics | 910 | 818 | 924 |
| video_embeddings | 910 | 818 | 924 |
| processing_runs | 19 | N/A | 3 |
| processing_jobs | 1,168 | 872 | 924 |
| interest_categories | 19 | N/A | 19 |

19 taxonomy rows means **18 onboarding categories plus non-onboarding unknown**.

- 924 retrieval-ready videos: **792 FineVideo + 132 TikTok**; no YouTube embeddings.
- 894 retrieval-ready videos have a nonempty transcript. Empty transcript does
  not itself invalidate an otherwise complete audiovisual-evidence annotation.
- 216 videos have affect/context but no complete semantic record. None is
  metadata-only in the chosen scope. Zero selected semantics lack a compatible
  embedding. No video metadata row is removed or refreshed.
- The local ready manifest has 4,226 videos; **3,086 additional IDs are outside
  this rebuild**. The scanned local completion files all belong to imported IDs.
- 1,016 valid historical semantic candidates reduce to 924 current selections:
  **92 historical versions excluded**, retained in the history archive.
- 106 newly completed local semantics/embeddings are selected. All 818 existing
  current semantic/embedding identities remain selected.
- Three required runs remain: `semantic_full_v12`, `semantic_full_v8_r2`, and the
  corresponding Gemini predictions run. Original IDs and frozen payloads remain.
- Jobs retain one matching successful state for the selected semantic version.
  Old failures, retries, in-progress states, and superseded successes remain in
  the archives. They are not represented as fresh failures or fabricated jobs.

## Selection and data preservation

`catalogue.py` calls the existing `Reader.semantic_bundle`: validates completion
schema, frozen configuration, source hashes, exact referenced Gemini annotation,
semantic evidence/provenance, embedding input, .npy hash, shape, dtype and norm.
No model classes are instantiated. Invalid candidates are reported, not retried.
This stage had **zero artifact-validation failures**.

Completion timestamps are parsed into UTC. Run names and database insertion
times never determine recency. Equal newest completion timestamps block staging
for review. Older records cannot supply the latest record's embedding. Embedding
identity must match semantic ID, video ID, run, checkpoint/revision, template,
input hash, and original embedding configuration. Missing embeddings are reported
without falling back to an older semantic version.

All original payloads/content hashes and existing row IDs are retained. New
local entities use the existing importer's identities. Catalogue categories live
in a verified sidecar and proposed backend-only view, not in rewritten metadata
or semantic payloads. New rows' DB `created_at` is insertion time only.

## Category policy

All 1,140 source labels are preserved exactly; all map via the existing dataset
`MAPPING` to supported taxonomy categories. Original `category_original` and
existing metadata `category` remain unchanged. No source-category conflicts occur
in this scope. Zero category-generation calls are needed or authorized.

| Canonical category | Videos |
|---|---:|
| Comedy | 282 |
| Lifestyle, Vlogs & Relationships | 140 |
| Music & Dance | 129 |
| Gaming | 121 |
| Sports & Fitness | 119 |
| Travel & Adventure | 74 |
| Science & Technology | 50 |
| Mental Health & Motivation | 48 |
| Nature, Animals & Conservation | 40 |
| Entertainment & Animation | 34 |
| Beauty & Style | 32 |
| News, Politics & Social Issues | 31 |
| Food & Cooking | 23 |
| DIY, Crafts & Outdoor Hobbies | 11 |
| Religion & Spirituality | 6 |

Latest Qwen suggestions: 719 equal the source category and are deduplicated; 204
different suggestions are retained as candidates but **withheld as secondary
categories**. Existing provenance labels their classification as unverified and
explicitly disclaims entailment. A taxonomy match, model confidence, or caption
alone is not sufficient evidence for automatic secondary-category promotion.
217 videos have no usable Qwen candidate (216 without semantics; one unknown).
No unsupported secondary category is invented. Human evidence-backed review can
be added separately without changing historical semantic records/embeddings.

## Prepared artifacts and commands

These directories are ignored local archives and contain full embedding vectors.
Do not paste their JSONL/SQL contents into chat or commit them as credentials-free
summaries. Preserve/copy the archives to a separate durable location before any
approved replacement. Documentation and code are separate from generated data.

- `production_snapshot/`: all original rows plus columns/defaults, 30 constraints,
  14 indexes, RLS/ownership/ACL, grants, policies, triggers, inbound FKs and vector
  extension version. Twelve inbound FKs are internal; no user triggers/policies.
- `imported_stage/`: eight clean JSONL tables, checksummed manifest,
  `selection.json`, `categories.json`, and input file hashes.
- `imported_stage-history/`: original and newly discovered historical candidates,
  including all 1,016 semantic records/vectors and 1,233 job snapshots.
- `sql_review_ready/`: generated replacement and data-restoration rehearsal SQL,
  view definitions, and exact delta. **Not executed; scripts end in ROLLBACK.**

From repository root, using the existing backend environment:

```powershell
.\backend\.venv-import\Scripts\python.exe -B -m backend.video_data.catalogue verify backend/reports/catalogue_rebuild_20261017/production_snapshot
.\backend\.venv-import\Scripts\python.exe -B -m backend.video_data.catalogue verify backend/reports/catalogue_rebuild_20261017/imported_stage
.\backend\.venv-import\Scripts\python.exe -B -m unittest backend.tests.test_catalogue backend.tests.test_video_data
```

To refresh the planning package, choose a NEW output directory (existing archives
are never overwritten):

```powershell
.\backend\.venv-import\Scripts\python.exe -B -m backend.video_data sync --current-only --report-dir backend/reports/catalogue_refresh_NEW
```

This existing-importer entrypoint only snapshots, stages, and exports a reviewed
current-only delta. It rejects apply/watch flags. Repeating preparation with an
unchanged frozen input produces the same entity rows and an empty row delta.

Once compatible PostgreSQL backup tools are installed, the optional `dump`
command creates a custom-format eight-table schema/data backup and checks its
table of contents. Credentials are passed privately through child-process
environment variables, never arguments or printed driver output:

```powershell
.\backend\.venv-import\Scripts\python.exe -B -m backend.video_data.catalogue dump --out backend/reports/catalogue_native_backup_NEW --pg-dump C:/path/to/pg_dump.exe --pg-restore C:/path/to/pg_restore.exe
```

Listing the dump is not a restore rehearsal; an isolated restore is still required.

## Exact replacement sequence after separate approval

1. **Do not run 001/002 again.** Confirm scope and stage hashes. Identify and
   pause all local/remote database sync jobs. Pause local semantic production at
   a safe boundary or pin its input snapshot. Do not assume a `processing` state
   proves a live process. Record the pause acknowledgements and process identities.
2. Produce a fresh repeatable-read backup and stage after quiescence. Retain both
   the old snapshot and the final pre-replacement snapshot. Export a complete
   eight-table schema/data dump with a compatible PostgreSQL `pg_dump`, including
   ownership, ACL/RLS, constraints and indexes; retain the installed pgvector
   dependency/version. Obtain any Supabase snapshot/PITR recovery reference.
3. Restore into an **isolated disposable database**, never the live project.
   Verify all eight row counts, original payload hashes/IDs, vector values,
   constraints/indexes/security and FK closure. Rehearse replacement and reverse
   restoration there. Record logs/checksums. No local restore server/tools were
   available during this preparation, so this remains a mandatory blocker.
4. Review the generated `replacement_rehearsal.sql`. It begins a transaction,
   locks all eight original tables in EXCLUSIVE mode with a lock timeout, and
   compares live schema/security and every production row with the source
   snapshot. Drift raises an exception. No automatic cascade is allowed.
5. Inside that transaction, populate TEMP staging tables with complete typed rows
   and original checks/indexes; explicitly check FKs (LIKE does not copy FKs).
   Apply the delta child-first for removals and parent-first for insertions.
   Keep every original production table object, vector configuration, constraint,
   index, RLS flag, owner and grant; do not rename/drop/truncate tables.
6. Exact current delta: videos 0 removed/0 added; runs 16/0; contexts 132/106;
   affects 4/0; semantics 92/106; embeddings 92/106; jobs 299/55; taxonomy 0/0.
   Row identities/content hashes shared by both packages must be unchanged.
7. Check all result counts, compare every non-insertion-time column against the
   validated stage, force immediate constraints, and verify 924 unique current
   semantics/compatible embeddings. Install the two reviewed backend-only views
   using security-invoker access and backend-only grants. Do not enable mobile
   or public access. Recheck original table security/index inventories.
8. The generated script ends in **ROLLBACK**. Do not change that until all
   blockers are resolved and explicit production approval has been received.
   Commit only the separately reviewed final procedure after successful rehearsal.
9. Read back counts/hashes/FKs/views after commit, compare with the frozen stage,
   then resume only the reviewed current-only synchronization workflow. Archive
   any superseded future versions before an authorized delta removes them.

## Rollback and future synchronization

- Before commit: ROLLBACK restores original rows automatically; locks and TEMP
  staging disappear. Any exception must abort the transaction.
- After commit: stop writers; archive the post-change state; restore the verified
  pre-change row package into the preserved schema using the inverse delta or
  the rehearsed schema/data backup. Validate hashes/vector values and original
  security. Restore original view state and application revision as rehearsed.
  Do not execute data-restoration SQL against nonempty production tables; the
  generated empty-target restore script intentionally rejects that situation.
- `video_catalogue_current` activates a repository guard that refuses the old
  history-scanning writer. This prevents a normal legacy `sync --apply` from
  repopulating excluded versions. No marker is currently installed in production.
- The `--current-only` path prepares idempotent, timestamp-selected, archive-backed
  deltas through the existing importer. **Unattended current-only live apply is
  not enabled or claimed tested**. Use separately approved reviewed transactions;
  do not resume automatic legacy apply after replacement. A future automatic
  executor needs the same archive, locks, nonregression and schema guards.

## Blockers and limits

- `pg_dump`/`pg_restore` and an isolated restore target were not available. The
  row archive is complete, checksummed, readable and graph-validated; **a full
  restorable schema/data backup has not been restore-rehearsed**. The catalog
  inventory alone is not a substitute for a verified schema dump.
- No relevant database writer was visible at the snapshot instant. This does
  not prove quiescence. Two Python processes were visible; command-line process
  classification was unavailable through host CIM. Local results advanced during
  the earlier conversation. Writer identities and remote jobs must be checked
  and paused before the final snapshot/replacement.
- No database staging tables, views or replacement SQL were executed. Only
  local staging exists. SQL SELECT bodies/guards are checked read-only; the
  writable transaction still requires isolated rehearsal.
- Validation: **28 tests passed**. Read-only evaluation of all nine generated
  schema/security guards matched production. The proposed latest-current SELECT
  returned 818 distinct/current production rows; the category SELECT returned
  1,140 distinct source-preserved categories. The staged equivalent is 924 current
  rows, verified against its complete historical candidate archive.
- Category correctness means source preservation and provenance-aware mapping,
  not independently verified model labels. Differing Qwen suggestions stay
  withheld. Local media references still do not provide hosted playback.

STOP here. Production replacement and any destructive action require separate
explicit approval after the above preconditions are satisfied.
