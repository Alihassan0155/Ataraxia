# Automatic batch synchronization — activated

Activated after the user's explicit approval of live synchronization and Windows sign-in startup. Verified at **2026-10-17 23:14:26 UTC / 2026-10-18 04:14:26 PKT**.

- Hidden watcher running; application PID at verification: `23256`.
- Current-user startup entry `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\AtaraxiaBatchSync` matches the prepared Python watcher command.
- Exact approved scope remains **1,140 existing video IDs**.
- Trigger remains **10 distinct pending videos OR 30 minutes from original persisted discovery**.
- **100 backlog videos synchronized**, with 349 inserted rows: 100 contexts, 100 semantics, 100 embeddings and 49 completed-job records.
- **918 unique videos verified retrieval-ready in live Supabase**.
- **9 pending videos remain**, with no recorded queue errors. Their earliest original deadline is **2026-10-17 23:24:37 UTC / 2026-10-18 04:24:37 PKT**. The watcher will deliver this partial batch after the deadline when connected; this is not a lost backlog.
- All original rows, timestamps, payloads and vectors were compared against the pre-synchronization snapshot and are preserved exactly.
- No metadata/category overwrites, history deletions, new video imports, model inference, migrations or catalogue-view creation occurred. The separate clean rebuild remains unapplied.

Verified live counts at this checkpoint:

| Table | Rows |
|---|---:|
| videos | 1,140 |
| video_context | 1,266 |
| affect_annotations | 1,144 |
| video_semantics | 1,010 across 918 videos |
| video_embeddings | 1,010 across 918 videos |
| processing_runs | 19 |
| processing_jobs | 1,217 |
| interest_categories | 19 |

These are timestamped verification counts, not a continuously updated report. Current activity is in `backend/reports/automatic_batch_sync_20261018/watcher.log`; durable status is in `queue.sqlite`. `activation_results.json` preserves this verification, including process/startup checks. The queue also retains 92 superseded version identities. Runtime recovery and operator controls are documented in [the implementation report](automatic_batch_sync_20261018.md).

The watcher resumes at this user's Windows sign-in. It retries recoverable errors, keeps pending work on disk and does not run annotation or embedding models. All **80 backend tests** passed before activation; isolated PostgreSQL delivery, idempotency and rollback checks passed.
