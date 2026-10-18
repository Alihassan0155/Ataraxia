# Persistent automatic batch synchronization

Status: **activated after explicit approval of live syncing and Windows sign-in startup.** The queue, transactional writer and hidden watcher are implemented and tested. The initial activation request was rejected by automatic approval review; the user subsequently explicitly approved both actions, and activation succeeded. The initial 109-video backlog is being delivered in batches. Current progress is in `watcher.log`; verified activation/results are recorded under the report directory.

## Existing architecture inspected

- `Reader.semantic_bundle` verifies completed record schemas, frozen run definitions, source/Gemini hashes, context, rendered embedding input, BGE-M3 model/revision, vector file hash, float32 dimensions and normalization. It imports validators, not models.
- Finalized `record.json` is the discovery signal. `semantic_metadata.json`, a job's `metadata_ready`/`processing` state, or an embedding file alone cannot establish a complete bundle.
- `sync --current-only` is currently a read-only whole-catalogue snapshot/stage/delta planner, not a per-batch automatic writer.
- The legacy `Repository` deliberately refuses historical imports once `video_catalogue_current` exists. That guard remains unchanged.
- The separately approved clean replacement executor requires verified backup/rehearsal and a writer-pause acknowledgement. It is not suitable for silently executing arbitrary automatic batches.
- The 927-video clean catalogue remains prepared but unapproved/unapplied. This queue work does not apply it.

## Implemented components

`backend/video_data/batch_sync.py` uses SQLite with WAL and `synchronous=FULL` on a local filesystem. Each validated discovery commits immediately, including video/version identity, completion timestamp, original discovery timestamp, source path, a complete immutable bundle snapshot, bundle hash, status, attempts, retry timestamp and acknowledgement metadata. Copying the bundle into the queue avoids relying solely on a path or in-memory list. Source artifacts are unchanged.

The queue pins the exact approved video-ID set. Changing scope or an existing immutable identity's content is rejected. Every startup rescans finalized artifacts, deduplicates identities and retains pending/error records. Failed or partial artifacts are retried on later scans. A failed database reconciliation never removes pending records.

Scheduling defaults: **10 distinct pending videos OR oldest persisted waiting time >= 1,800 seconds**. Multiple versions of one video count as one video. Completion timestamps, not run names, determine the selected version. Equal newest timestamps are withheld. Newer versions retain their video's original pending deadline. Batch size, maximum waiting time and polling interval are configurable.

Claims use SQLite transactions. An exclusive OS watcher lock prevents concurrent CLI workers. Interrupted in-flight items return to pending at startup while that lock is held. Confirmed successful versions and superseded versions remain recorded; queue history is not deleted. Network failures retain pending rows and persist bounded exponential retry delays (30 seconds to 30 minutes by default), without resetting original waiting time.

The delivery API is at-least-once: if remote COMMIT succeeds but local acknowledgement is interrupted, the same identity is retried. The transactional writer verifies already-committed immutable columns and exact vector values, then acknowledges without inserting duplicates. Missing or partial delivery outcomes do not acknowledge any claimed rows. Corrupted local bundle snapshots never reach the writer callback.

Optional `--reconcile-live` reads all eight existing tables in an explicit repeatable-read READ ONLY transaction, validates hashes/relationships/vectors, checks the exact approved scope, selects current versions by completion timestamp and acknowledges only matching compatible stored versions locally. Older pending versions become superseded. No remote records are written.

## Commands

One-shot local scan (no database connection):

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.batch_sync --queue backend/reports/automatic_batch_sync_20261018/queue.sqlite --approved-snapshot backend/reports/catalogue_final_20261018/production_snapshot
```

Optional read-only remote reconciliation:

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.batch_sync --queue backend/reports/automatic_batch_sync_20261018/queue.sqlite --approved-snapshot backend/reports/catalogue_final_20261018/production_snapshot --reconcile-live
```

`--watch` enables foreground polling. Both `--apply` and `--allow-live-writes` are required to enable delivery; commands above remain read-only remotely. The approved hidden watcher is now running; a concurrent CLI scan will be refused by its worker lock. Do not delete the SQLite database, WAL or shared-memory files to clear a backlog; keep the queue on a local durable disk and use SQLite backup facilities for copies while open.

## Validation

**80 backend tests pass**, including queue and writer/activation safety tests covering persisted restart deadlines, 10 distinct videos, version deduplication, latest selection, timestamp ties, connection failure/backoff, lost-acknowledgement replay, concurrent claims, scope protection, partial acknowledgements, abrupt subprocess exit without cleanup, incomplete artifact recovery, corrupted queue payloads and default-disabled activation. Actual power-loss/storage hardware behavior cannot be simulated by a process-exit test; durability uses SQLite's FULL transaction settings.

The real scoped local scan validated and durably queued **1,019 semantic versions across 927 videos**, with zero discovery errors. No models ran. A second simultaneous CLI attempt was refused by the OS worker lock. Subsequent restart/rescan/read-only reconciliation results are recorded separately in `backend/reports/automatic_batch_sync_20261018/verification.json`.

## Transactional delivery

`backend/video_data/batch_writer.py` revalidates each queued bundle through the original Reader immediately before delivery. It takes a PostgreSQL transaction advisory lock plus eight-table SHARE ROW EXCLUSIVE locks, verifies actual database scope and existing hashes/provenance/relationships/vectors, and selects latest versions by real completion timestamps. Each batch commits together. An error rolls back the entire batch; SQLite keeps it pending with retry state.

The writer never inserts/updates `videos` or `interest_categories`. It only inserts missing immutable processing-run, context, affect, semantic, embedding and successful-job rows for approved existing videos. Existing metadata/categories and historical records are preserved. It does not perform the separately gated clean replacement, delete historical rows, create catalogue views or run migrations. Only newer completed versions are eligible; old recovered versions are superseded rather than replayed. A newer remote record without its own unique compatible embedding or an equal-timestamp identity conflict is withheld for review rather than silently falling back.

This is a dedicated latest-only writer, not an escape hatch in the legacy importer. The historical `Repository` guard remains intact. Where current views exist, they continue selecting one latest semantic version; legitimate old versions remain retained as history. The physical latest-only rebuild is a separate, still-unapproved action.

An isolated native PostgreSQL copy verified a real ten-video delivery (818 → 828 retrieval-ready), exact repeat delivery with zero additional inserts, rollback after the first injected insert failure, unchanged original metadata, and older-version replay rejection. Evidence: `writer_integration_report.json`. `backend/tests/integration_batch_writer.py` is an explicit localhost-only integration harness, outside ordinary test discovery. No production settings are loaded by that harness.

## Activation and operation

`backend/watch_batch_sync.py` uses absolute paths, hidden Python, a local log (`watcher.log`) and a supervisor retry delay for transient watcher exits. It restores durable pending items and tries already-expired batches before a full artifact rescan. Default batch size/wait remain 10/1,800 seconds. An unexpired tail of fewer than ten remains queued until its persisted deadline.

`backend/video_data/activate_batch_sync.py` defaults to printing an activation plan without writing to the registry or starting processes:

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.activate_batch_sync
```

The following activation command was run after explicit approval of **both live delivery and startup activation**:

```powershell
backend/.venv-import/Scripts/python.exe -B -m backend.video_data.activate_batch_sync --approved-live-sync-and-startup
```

This creates only the current user's `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\AtaraxiaBatchSync` entry, then starts the hidden watcher. It resumes at that user's Windows sign-in, not before sign-in as a system service. The queue and log stay under `backend/reports/automatic_batch_sync_20261018/`. Both the running process and matching startup entry were verified. Do not run activation again while the watcher is active.

After activation, inspect `watcher.log`, `watcher_process.json` and SQLite status to verify liveness and pending retry state. To disable sign-in startup, remove only that named Run value. To stop delivery, stop the verified watcher PID; pending rows remain durable. Record any prior value from `activation.json` when restoring a prior startup configuration.

Approved batch inserts will change production and invalidate the older clean-replacement package's exact source-row guard. Before a later clean rebuild, refresh its read-only snapshot/stage and repeat the required backup/rehearsal checks. Do not force the stale replacement SQL.
