# Final clean catalogue preparation — production NOT changed

**Verdict: GO for review; NO-GO for production execution until all writers are positively paused and separate explicit production approval is given.** Native backup, isolated restoration, replacement, transaction rollback, post-commit rollback, data validation and view permission checks have passed. No models, frontend or user tables were involved.

The immutable preparation package is `backend/reports/catalogue_final_20261018/`. The older 924-video stage is superseded for this proposal and remains preserved.

## Verified dataset and exact delta

| Table | Original production | Final staged | Insert | Remove from production after archive |
|---|---:|---:|---:|---:|
| videos | 1,140 | 1,140 | 0 | 0 |
| video_context | 1,166 | 1,140 | 109 | 135 |
| affect_annotations | 1,144 | 1,140 | 0 | 4 |
| video_semantics | 910 | 927 | 109 | 92 |
| video_embeddings | 910 | 927 | 109 | 92 |
| processing_runs | 19 | 3 | 0 | 16 |
| processing_jobs | 1,168 | 927 | 58 | 299 |
| interest_categories | 19 | 19 | 0 | 0 |
| **Total** | **6,476** | **6,223** | **385** | **638** |

The 638 removals are superseded/unused versions and job snapshots, not video deletions. Every existing video ID remains. All 1,140 original metadata payloads, category labels and mapped categories remain unchanged. There are 18 onboarding categories plus `unknown`; no category is created or removed.

The 1,019 validated completed semantic/embedding pairs reduce to **927 latest valid selections**, using timezone-aware completion timestamps, frozen run provenance and source hashes. There are no timestamp ties, invalid selected artifacts, FK problems or missing/incompatible selected embeddings. All selected vectors are finite, normalized float32 BGE-M3 vectors of dimension 1,024. The latest selected semantic record supplies its own affect, context and embedding identities; older embeddings are never substituted.

All 213 incomplete videos retain their real metadata, affect and context without fabricated outputs. Of the 927 complete selections, 895 have nonempty transcripts. Empty transcript alone does not invalidate a complete audiovisual-evidence bundle.

All categories retain source-metadata provenance. Qwen categories agreeing with the source are deduplicated for 722 videos; 204 differing suggestions remain withheld. There are 214 without a usable Qwen candidate. No evidence-review category proposals from outside this scope are imported.

## Archive and native recovery verification

- `production_snapshot/`: checksummed eight-table snapshot and schema/security inventory, including every original timestamp, vector and payload.
- `current_stage/`: verified latest-only stage, selection list, category provenance and source hashes.
- `current_stage-history/`: verified archive with all 1,019 semantic records/embeddings, 1,275 context versions, 1,144 affect annotations, 1,236 job snapshots, 19 processing runs, original metadata and taxonomy.
- `native_backup/video_tables.dump`: PostgreSQL custom-format native backup of the original eight tables with table DDL, data, constraints, indexes, ownership, grants and RLS. SHA-256: `a8c984949254e8723a62a5bfd4ad306aa5d1714276c32d9a0074035b82f73b1c`.
- `native_backup/contents.txt`: readable, verified table-of-contents inventory. Extension packages/role definitions are dependencies, not included by a table-filtered dump. They are separately recorded in the snapshot inventory. The native backup manifest describes the state when captured; subsequent restore proof is in the rehearsal reports.

Portable [PostgreSQL 17.11 binaries](https://www.enterprisedb.com/download-postgresql-binaries) and [pgvector 0.8.2 source](https://github.com/pgvector/pgvector/tree/v0.8.2) were placed inside the ignored local package; pgvector compiled using the existing Visual Studio compiler. Download hashes are in `tools/sources.json`. No system service was installed.

The isolated server listened only on `127.0.0.1:55439`. Native restore into `ataraxia_rehearsal` completed successfully. All original columns, IDs, timestamps, payloads and vectors matched the production snapshot. A second native restore into `ataraxia_recovery`, after the local clean commit, again matched every original row and vector. The disposable server was stopped afterwards; its data and logs remain preserved.

The untouched production SQL correctly rejected the isolated environment's different extension inventory. Only that expected extension-inventory value was substituted in **separately named local rehearsal SQL** because Supabase-only extensions, including Vault, are absent locally. All other schema, security, source-row, FK and result guards ran unchanged. The original production schema/security guard also passed on Supabase inside a READ ONLY transaction. Production SQL was never altered to bypass this check.

## Transaction and catalogue rehearsal results

`sql_final/replacement_rehearsal.sql` ends in `ROLLBACK`. It locks the eight tables, compares the live schema/security and exact source rows, validates temporary staging references, applies the explicit identity delta, verifies resulting rows/vectors/counts, and creates the backend views. It preserves the existing table objects, constraints, indexes and security settings.

The local rollback-only rehearsal left every original row unchanged. A separately named local COMMIT rehearsal produced exactly 1,140 videos and 927 retrieval-ready records, matching every staged column/vector.

| View | Verified rows | Unique videos |
|---|---:|---:|
| video_catalogue_current | 927 | 927 |
| video_catalogue_retrieval_ready | 927 | 927 |
| video_catalogue_categories | 1,140 | 1,140 |
| video_catalogue_all | 1,140 | 1,140 |

All four views use `security_invoker=true`. `PUBLIC`, `anon` and `authenticated` are explicitly denied access; `service_role` has SELECT. Role-based queries confirmed service-role access and anonymous/authenticated rejection. Underlying RLS remains enabled and unchanged.

Additional isolated checks passed:

- Multiple compatible embeddings do not multiply a current-semantic row; retrieval readiness fails closed.
- A newer semantic version without its own embedding does not use an older embedding.
- Equal latest completion timestamps do not produce an arbitrary current selection.
- Repeating the identical current-only plan produces no row delta.
- The existing Repository guard rejects the legacy history importer when the current catalogue exists.

`sql_final/rollback_after_commit_rehearsal.sql` is the exact reverse identity delta and also ends in ROLLBACK. It first verifies the expected clean state and original table schema/security. It restores archived historical rows with their original timestamps and removes only newly synchronized identities. It drops only the four newly introduced views, with RESTRICT rather than CASCADE. Both rollback-only and local COMMIT recovery rehearsals passed; the original eight-table data and original absence of views were restored exactly. Unexpected changes/dependencies cause refusal rather than destructive recovery.

Evidence: `rehearsal_report.json`, `post_commit_recovery_report.json`, `rollback_rehearsal_report.json`, corresponding logs, and checksums. **60 backend unit tests pass**, including approval/writer-pause gating, original-category preservation, latest-version selection, hash/vector validation and legacy-import protection. Live production remained unchanged throughout preparation.

## Remaining execution gate

No active matching video-table SQL writers were observed. Fallback process inspection found no matching historical importer or annotation worker. Windows WMI/task inventory was unavailable, and an idle database does not prove every scheduled/remote synchronizer is disabled. **Positive local and remote writer-pause acknowledgement is still required.** Do not infer it from stale `processing` job rows.

`writers_acknowledgement.template.json` is deliberately unconfirmed. A real acknowledgement must identify the confirming operator, UTC time, paused jobs and the exact stage-manifest hash. Do not mark it confirmed until the pause is established.

## Exact execution sequence — ONLY after separate approval

Run from `E:\ALI\Ataraxia`. Keep all archives and native backup available. Do not rerun migrations 001/002 or any model.

1. Obtain explicit approval for the 385 insertions, 638 archived-version removals and four backend-only views. Confirm/pause all local and remote synchronization jobs and record the confirmation in `backend/reports/catalogue_final_20261018/writers_acknowledgement.json`, based on the template. Keep writers paused through validation. If production or source artifacts changed, refresh and rehearse a new package instead.
2. Run the offline preflight (safe now; already passed):

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.execute_catalogue backend/reports/catalogue_final_20261018
```

3. After approval and confirmed writer pause, execute the hash-verified reviewed plan:

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.execute_catalogue backend/reports/catalogue_final_20261018 --approved-production-commit --writers-ack backend/reports/catalogue_final_20261018/writers_acknowledgement.json
```

The wrapper privately loads the existing database settings, never puts credentials in argv, verifies package bindings/backup/rehearsal hashes and writer acknowledgement, then derives COMMIT from the rehearsed rollback-only source in a new execution directory. It never runs local-fixture SQL against production. Original guards reject intervening schema/security/data changes. Execution logs are local and must not be pasted because SQL can contain full payloads/vectors. A connection loss near COMMIT requires live verification before any retry.

4. Verify all eight final table counts above, all four view counts/unique IDs, original metadata hashes, categories, FK integrity and embedding compatibility. Capture a new read-only snapshot using the existing `catalogue snapshot` command into a fresh directory. Do not resume the legacy importer.
5. On pre-COMMIT error, the transaction rolls back. If post-COMMIT rollback is separately authorized and production still matches the prepared clean state, retain writer pause and use:

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.execute_catalogue backend/reports/catalogue_final_20261018 --approved-production-rollback --writers-ack backend/reports/catalogue_final_20261018/writers_acknowledgement.json
```

This uses the separately rehearsed, guarded reverse delta. If it refuses because new production data/dependencies exist, stop and review recovery from the native backup in isolation; do not force or truncate production.

## Future incremental synchronization and next phase

Use `python -m backend.video_data sync --current-only --report-dir NEW_DIRECTORY` to capture, validate, select latest versions and prepare a fresh delta for these same imported IDs. This is deliberately a read-only planner; each subsequent apply requires its own verified backup/rehearsal and approval. The legacy history-import path is blocked once the catalogue marker view exists. No unattended current-only production writer is enabled by this change. Historical files remain available for reproducibility but cannot be restored by that blocked legacy path.

After successful approved synchronization and post-apply validation, the backend catalogue can support the next requested phase: **Metadata Filtering → Balanced Sampling → Random Top-50 Candidate Retrieval**. No filtering, sampling or recommendation algorithm is implemented in this preparation.
