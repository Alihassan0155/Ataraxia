# Processing shortcuts — resume the original local runs

Load once in each VS Code PowerShell terminal:

```powershell
cd E:\ALI\Ataraxia
Set-ExecutionPolicy -Scope Process Bypass
. .\run.ps1
```

Terminal 1: `run gemini`. Terminal 2: `run embedder`.

There is no 1,140-video database-subset filter in either local processing command. Gemini uses all 4,126 IDs in the original frozen selection of gemini_full_remaining_20261012; the original research-split/completion exclusions are preserved. The embedder uses all 4,226 metadata IDs frozen in semantic_full_v12. These are existing run inventories, not arbitrary batch limits. No new run is created and no checkpoint is reset.

Gemini writes/resumes the ORIGINAL checkpoint at annotation/runs/gemini_full_remaining_20261012/predictions/gemini/annotations.jsonl and uses its original controller lock. Existing schema-valid saved annotations are skipped. If a prior Gemini worker is already running, the duplicate launcher refuses the lock; it does not kill the existing process. Status is saved at annotation/runs/gemini_full_remaining_20261012/status.json.

The embedder resumes the original semantic_full_v12 state, validates and skips completed bundles, and runs missing Qwen semantic extraction followed by BGE-M3 embeddings. Valid cached semantics are reused without Qwen regeneration. Both models use the frozen staged configuration sequentially under the shared GPU lock. Videos without finalized Gemini evidence remain waiting. Existing retry/backoff, worker/GPU locks, checkpoints, hashes and immutable definitions remain enforced. Status: backend/reports/processing_launcher/embedder_status.json; stage events: annotation/semantic_pipeline/runs/semantic_full_v12/logs/events.jsonl.

The embedding runtime recovers exact frozen historical source from Git commit 03523a3 into an ignored isolated directory. Historical run fingerprints and current source pipeline files are not rewritten. Gemini prediction snapshots are refreshed atomically on each embedding poll so the reader sees new finalized annotation lines while safely ignoring partial trailing lines. Existing contexts, transcripts and model cache are reused.

Use `run gemini -Check` or `run embedder -Check` for scope/import/frozen checks without inference. `-Once` drains currently eligible work then exits. Ctrl+C preserves validated completions; rerun the same command to resume. The existing environment annotation/.venv-qwen-cuda is selected explicitly even when the terminal displays (venv). No permanent profile/PATH changes are made.

IMPORTANT: widening these LOCAL processing queues does not widen Supabase or S3 authorization. The existing database synchronization watcher remains restricted to its previously approved 1,140 IDs. No changes to database delivery, S3 delivery or remote scope were made. Any synchronization of additional IDs requires separate authorization.

Validation after removing the artificial local scope limit: both no-inference checks passed (Gemini 4,126; embedder 4,226), frozen compatibility passed, and five launcher/runtime tests passed. No model inference was started while making this scope correction.

Update: `run embedder` now authorizes both frozen Qwen semantics and BGE-M3 stages. Stop an older launcher with Ctrl+C before restarting it. `run embedder -Once` drains eligible semantic/embedding work, then exits; it can take a long time. Failed/backoff jobs retain their original retry policy. No inference was launched while implementing this change.
