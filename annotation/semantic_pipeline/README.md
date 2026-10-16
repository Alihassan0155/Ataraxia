# Independent semantic video encoding

Implementation is provided; no tests, package installation, weight downloads,
worker execution or embeddings were performed during implementation. Gemini,
affect prompts, calibration and historical research outputs are unchanged.
Use the commands below yourself. The pipeline has no mandatory pilot, review
gate or video limit. CUDA memory use and semantic extraction quality remain
unmeasured on this machine.

**Evidence-validation fix update:** the subsequent semantic v4–v7 maintenance task
authorized execution of focused tests and ID-scoped retries. All 27 CPU regression
tests passed. See `reports/evidence_validation_fix.md` for live retry outcomes;
the original implementation-only statements below describe the initial delivery.
The schema quote limit remains 250. Quotes are preferably at most 200 characters.
Deterministic repair allows exact-source spacing/typographic-punctuation recovery
and complete-sentence shortening with lexical field anchors. It never paraphrases,
changes sources, invents quotes or silently drops unsupported claims. Ambiguous,
unanchored or fabricated evidence is rejected for the bounded model repair.
All repaired responses must pass the full schema and semantic validator.

Current v7 repair requests one explicit passage decision per content field; list
fields may cite multiple catalog IDs. An omitted field is tolerated only when
the original value was already empty/null/unknown. Asserted omitted fields fail.
Null decisions explicitly retract unsupported claims. A required summary cannot
be retracted or automatically invented: that video remains failed. Confidence and
category-ambiguity values remain unchanged. Cached selector responses can be reused
with `--selection-run`, after checking the source/draft provenance hash.
The actual scoped retry passed FV000005 semantic validation; BGE-M3 weights are
missing locally. FV000002 remains rejected because its summary was retracted.
See the report for details; do not infer whole-dataset readiness from schema tests.

Semantic v5 uses a smaller bounded passage-selector correction for parsed drafts:
Qwen returns field-to-passage IDs and explicit retractions/taxonomy corrections.
Every catalog entry is copied verbatim from its stated source and is at most
200 characters. Unknown IDs or invented replacement descriptions are rejected.
Only explicit model choices can replace evidence sources or retract claims;
deterministic quote repair never switches sources. The entire reconstructed
response passes the unchanged validators. Full-response repair remains the fallback
for unparseable JSON. Catalog matching guarantees source identity, not entailment.

Only failed IDs can be replayed from cached drafts into a new frozen run:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py retry-cached --source-run semantic_cuda_v3 --selection-run semantic_evidence_fix_v6 --run semantic_evidence_retry_1 --video-ids FV000002 FV000005
```

The target run must not already exist; use a different name for a subsequent
explicit attempt. No unrelated IDs are queued. The command preserves historical
attempts, checks cached input fingerprints, loads Qwen only if local validation
needs its one bounded correction, then embeds only valid recovered metadata.
Outcomes are written to `<target-run>/reports/targeted_retry.json`. Cached drafts
do not become valid merely by being reused. Failed repairs stay failed. A previous
worker must have released the shared GPU lock before this command can infer.
The CLI exits nonzero if any requested ID remains incomplete. To explicitly
download only missing BGE weights (the corrected downloader includes `.bin`):

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py download --models embedder
```

No download was automatically executed by the maintenance task.

Semantic v3 explicitly forbids citing taxonomy/schema as evidence for categories
and formats. Repair feedback retains the exact failing instance path, and the
bounded repair asks for real source quotes or unknown classifications, never
an automatic source-key substitution. Use a new run: `--run semantic_cuda_v3`.
These prompt/code changes are untested; they do not guarantee extraction success.

Semantic v2 canonicalizes whitespace-only strings in nullable extraction fields
to null and marks them unsupported, preserving raw responses. A failed JSON/schema
validation gets at most one evidence-bound Qwen repair call, under the same input
and output token limits. The repaired object must pass all original schema,
taxonomy and exact-quote checks. Repairs and canonicalization are recorded.
Stop any old worker with Ctrl+C before switching code. Existing v1 frozen runs
are preserved; start the changed implementation with a new name, for example
`--run semantic_cuda_v2`. Model cache/downloads are reusable; prior run outputs
are not silently migrated across representation versions. Tests are prepared only.

## Existing evidence reused

| Existing component | Use here |
| --- | --- |
| `runs/gemini_full_remaining_20261012/predictions/gemini/annotations.jsonl` | Read-only completed annotations; only newline-terminated, schema-valid Gemini rows are eligible |
| `src/ataraxia/annotation/common.py:VideoAnnotation` | Reuse affect schema validation; no changes to it |
| `data/normalized/preprocessed_merged_v2/ready_metadata.csv` | Strict `assigned_id`/`video_id` mapping; duplicate metadata IDs stop the run |
| `.../context/<id>.json` | Shared Gemini/Whisper evidence, acoustic summaries and caption |
| `.../transcripts/<id>.txt` | Existing ASR text; fallback to context transcript; missing text allowed |
| `.../acoustic_features/<id>.json` | Preserved preprocessing artifact; extraction uses the existing context summary, not a learned audio embedding |
| `src/ataraxia/distributed/common.py` | OS locking, safe IDs, containment and SHA-256 utilities |
| `src/ataraxia/runtime/config.py` | Project-root and cache path resolution |

No raw video is decoded, no Whisper or Gemini call is repeated, and no source
annotation is rewritten. Raw affect scores do not enter embedding text. Source
metadata, transcripts and Gemini evidence are imperfect inputs, not verified
semantic truth. Stored audio/visual descriptions are interpretations of existing
evidence, not new audiovisual observations.

## Models and fixed representation

| Component | Exact checkpoint / revision | Settings |
| --- | --- | --- |
| Text extraction | `Qwen/Qwen3-4B-Instruct-2507` / `cdbee75f17c01a7cc42f958dc650907174af0554` | NF4, double quantization, BF16 compute, CUDA 0, greedy, seed 20261013, max 8192 input / 2048 output tokens, batch 2 |
| Dense embedding | `BAAI/bge-m3` / `5617a9f61b028005a4858fdac845db406aefb181` | FP16 forward, XLM-R CLS dense pooling, float32 L2 normalization/storage, model-reported 1024 dimensions required, 8192-token maximum, batch 4 |

The selected Qwen is an instruct **text** model, separate from the existing
Qwen3-VL annotation deployment. Its published non-thinking instruction interface,
multilingual capability and native Transformers support fit extraction from
existing evidence. An 8B extractor adds memory cost without measured evidence of
benefit here; a larger reasoning model adds unnecessary generation overhead.
The selection uses published interfaces and static compatibility inspection,
not a local benchmark. English, Urdu, Roman Urdu and mixed-language reliability
are not guaranteed. See the [official Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507).

Approximate planning estimates, **not measured peaks**: NF4 extraction weights
plus nonquantized tensors/quantization overhead may occupy roughly 3–5 GiB;
KV cache and activations add workload-dependent memory. BGE FP16 weights are
roughly 1.1 GiB, with substantial extra activation memory on long batched inputs.
Default `staged` mode unloads the extractor before embedding each bounded queue
of up to four videos. Models are reused across their stage's batch, not loaded
for every video. `resident` keeps both between polls, but is unverified on 16 GB.
OOM recursively halves batches; it never silently changes token limits or model
precision. A singleton OOM becomes an explicit bounded-retry failure.

BGE's pinned [pooling configuration](https://huggingface.co/BAAI/bge-m3/blob/5617a9f61b028005a4858fdac845db406aefb181/1_Pooling/config.json)
specifies CLS pooling and 1024 dimensions. This implementation uses only its
dense branch, with no sparse/ColBERT outputs, fine-tuning or mixed-model vectors.

Every run freezes configuration, extractor/embedder immutable revisions,
taxonomy, extraction prompt, embedding template, schemas, metadata manifest,
reused source-code hashes and installed package versions. Definition snapshots
are saved before work. Resume and each batch compare them. Changing any of these
requires a **new run name**, including changing batches/cache paths. Gemini may
append new results without changing the run definition. Changed transcripts,
contexts or annotation contents create separate source-hash versions under that
same run. Never combine vectors from different run fingerprints into one index
without deliberately treating them as different representation versions.

The taxonomy retains the 18 named broad dataset categories. The original
`Unmapped / Needs Review` remains source metadata; derived insufficient evidence
uses `unknown`. Subcategories, formats and styles are controlled. Topics and
tags remain evidence-supported free text. Original labels are retained by
reference; the original dataset is not recategorized.

Derived descriptions use English while preserving relevant original-language
terms and transcript text. A deterministic template renders summary, taxonomy,
topics, activities, objects, setting, speech/audio/intent/humor/content focus,
then existing Gemini evidence, transcript excerpt and explicitly unverified
creator metadata. Exact repeated text is deduplicated. Gendered audience claims
must be explicitly supported, never inferred from appearance.

Every asserted semantic field must have an exact source quote. Unknown scalars
are null or controlled `unknown` and appear in `unsupported_fields`; lists may
be empty. Acoustic statistics may support vocal delivery only. Quote checks
establish traceability, **not entailment, correctness or calibrated confidence**.
Schema-valid outputs can still misunderstand humor, intent and cultural context.

## One-time installation and explicit downloads

From the repository root, run these yourself. They create a separate environment
and do not alter the CUDA/Gemini environments. Python 3.12 and a compatible NVIDIA
driver must already be installed. Commands do not activate/change another shell's
environment or restart Gemini.

```powershell
Set-Location E:\ALI\Ataraxia\annotation
py -3.12 -m venv .venv-semantic
.\.venv-semantic\Scripts\python.exe -m pip install --upgrade pip
.\.venv-semantic\Scripts\python.exe -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
.\.venv-semantic\Scripts\python.exe -m pip install -r .\semantic_pipeline\requirements.txt
.\.venv-semantic\Scripts\python.exe -m pip install -e . --no-deps
.\.venv-semantic\Scripts\python.exe -m pip check
.\.venv-semantic\Scripts\python.exe -m pip freeze > .\semantic_pipeline\installed-requirements.local.txt
```

The major inference dependencies mirror the repository CUDA pins. Resolve any
installation conflict explicitly before starting; Windows wheel availability
and this separate environment have not been runtime-tested. Full installed
versions are frozen on first run. Back up the installed-requirements snapshot.

Review `configs/pipeline.json` **before the first run**. Default cache is
`.cache/semantic_models` relative to `annotation/`; you may choose a local drive
such as `D:/ALI/AtaraxiaSemantic/cache`. The default GPU lock matches the main
distributed worker's `C:/ProgramData/AtaraxiaWorker/gpu0.lock`. If its state path
changes, both workflows must use the same lock. The lock does not coordinate
unrelated manually launched GPU applications.

Download only when you choose to do so. This command fetches the two configured
immutable snapshots and tokenizer/config files; it runs no inference and creates
no processing run:

```powershell
.\.venv-semantic\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py download
```

All worker model loading uses `local_files_only=True` and
`trust_remote_code=False`. Missing weights fail visibly rather than downloading
on demand. No Gemini credentials are loaded or required.

## Start, inspect and control

Continuous processing uses all currently valid completed Gemini rows and waits
for further appends, without an artificial video cap:

```powershell
.\.venv-semantic\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py run --run semantic_v1
```

In a second terminal, from `annotation/`:

```powershell
# Counts, pending/failed details, source errors, throughput and update timestamp:
.\.venv-semantic\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py status --run semantic_v1
# Read latest validated version, including array shape/dtype/L2 norm:
.\.venv-semantic\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py inspect --run semantic_v1 --video-id FV000001
# Follow recent errors and stage progress:
Get-Content .\semantic_pipeline\runs\semantic_v1\logs\events.jsonl -Tail 20 -Wait
# Reset failed attempts explicitly (preserves reset history and raw responses):
.\.venv-semantic\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py retry-failed --run semantic_v1
# Pause/resume between bounded batches:
.\.venv-semantic\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py pause --run semantic_v1
.\.venv-semantic\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py resume --run semantic_v1
# Stop gracefully, or press Ctrl+C in the worker terminal:
.\.venv-semantic\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py stop --run semantic_v1
```

If the worker exited, `resume` clears markers; issue the same `run` command again
to restart it. It verifies unchanged completed records and continues partial
metadata. An optional `run --once` drains currently eligible work then exits;
backoff-delayed work requires another run. Controls never execute GPU inference
themselves. Pause unloads models but retains the worker's exclusive GPU lock;
**stop the semantic worker before starting distributed local-GPU annotation**.
Gemini API processing is independent and continues.

Retries default to four attempts per version and exponential delays 30, 60,
120, ... capped at 1800 seconds. Exhausted failures remain visible. Deterministic
schema failures may recur identically; retries do not invent missing metadata or
change prompts. Fix definitions only in a new run. In-progress interrupted
attempts resume without consuming another retry. Manual retry resets are logged.

Stop/pause take effect between bounded stages, not during a CUDA kernel or model
load. There is no forced watchdog to kill a blocked driver call. After a process
crash the OS releases locks automatically; no stale-file deletion is necessary.
Status is a timestamped snapshot, not proof a process is alive.

## Storage and integrity

Only files are used. No SQLite, SQL, PostgreSQL, FAISS, migrations or database
dependencies are introduced.

```text
semantic_pipeline/
  configs/                         configuration, taxonomy, extraction prompt, text template
  schemas/                         extraction schema and completed-record schema
  scripts/semantic.py              thin command entry point
  tests/test_contracts.py           prepared CPU-only regression contracts
  runs/<run>/
    frozen.json                    immutable run definition + package/code fingerprints
    definitions/                   exact snapshots (including metadata CSV)
    worker.lock                    OS single-writer lock
    videos/<video_id>/<source_hash>/
      state.json                   atomic processing/retry state
      semantic_metadata.json       recoverable validated extraction stage
      embedding_input.txt          exact UTF-8 embedding input
      embedding.npy                independent float32 unit vector
      record.json                  complete per-video metadata, provenance and file hashes
      attempts/                    extraction responses and explicit retry-reset history
    manifests/processing_manifest.jsonl
    logs/events.jsonl
    reports/status.json
    reports/integrity.json
```

No giant dataset JSON contains all semantic records. Each completed per-video
record has structured metadata, description, exact input reference, timestamps,
source refs/hashes, extraction/embedding versions, language provenance, omitted
transcript information, original Gemini prompt metadata where available, and
quality indicators. Raw Gemini predictions/full transcripts are not copied.
The recoverable extraction-stage JSON is separate from its completion record.

JSON/text/NumPy writes use same-directory UUID temporary files, flush/fsync and
atomic replacement. `record.json` is published last, then verified against stage,
input and vector hashes, schema and finite float32 normalization. A manifest is
rebuilt from verified records each poll and at shutdown, so it cannot authorize
an incomplete output. A crash can leave a stale manifest until the next rebuild;
consumers must validate referenced completion records. JSONL event logs are
diagnostic, never authoritative checkpoints.

Identical duplicate Gemini rows are ignored; conflicting duplicate IDs are
quarantined and reported without choosing one. Incomplete final JSONL lines are
ignored until completed. Malformed rows are reported, not silently normalized.
Optional missing transcript/context does not fabricate evidence. Missing required
metadata IDs and corrupt completed outputs remain visible; the latter are not
silently overwritten. Source edits during a batch reject publication and the next
poll selects the new source version. Prior valid versions remain available.

Full transcript text has a frozen 6000-character extraction budget. For longer
clips, explicit beginning/middle/end excerpts are marked and omission counts
stored; complete transcript hashes/references remain. All sources plus schema and
taxonomy must fit the extractor's 8192-token budget. Oversized extraction or
embedding input fails without a hidden tokenizer crop. Substantial omitted speech
can limit semantics; change budgeting only in a new run. Existing ASR checkpoint
revisions are not invented; source hashes provide artifact identity but not
missing historical model provenance.

For interrupted work, restart with the same configuration/environment/run.
For a corrupted completed version, preserve its directory, investigate, and use
a new run for regeneration; do not delete historical evidence to hide corruption.
To rebuild the manifest while the worker is **stopped**:

```powershell
.\.venv-semantic\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py rebuild-manifest --run semantic_v1
```

The command reports every invalid version. Inspect current input/source hashes
before choosing among historical versions; the inspect command returns the most
recent completed version, not a guarantee it matches sources subsequently edited.
Single-writer locking is per run plus a shared GPU lock; do not bypass the GPU
lock with another path to process the same authoritative run concurrently.

## Source modules and prepared validation

| New file under `src/ataraxia/semantic/` | Responsibility |
| --- | --- |
| `config.py` | Freeze and compare definition snapshots, revisions, code and packages |
| `sources.py` | Read completed Gemini lines, align IDs, assemble existing evidence, hash inputs |
| `representation.py` | JSON/schema/taxonomy/quote checks and deterministic text rendering |
| `models.py` | Offline NF4 extraction, dense BGE encoding and OOM batch splitting |
| `storage.py` | Atomic artifacts, strict vector integrity and recoverable manifest |
| `worker.py` | Continuous polling, bounded two-stage batching, checkpoints, retries and signals |
| `cli.py` | User-controlled start/status/inspect/control/download/recovery commands |

Prepared tests cover partial appends, conflicting IDs, evidence quotes, controlled
taxonomy, duplicate tags, deterministic rendering, vector corruption, frozen
resume refusal and extraction-stage reuse. They are **not executed**. If desired,
run CPU-only contracts yourself after installation:

```powershell
.\.venv-semantic\Scripts\python.exe -m unittest discover -s .\semantic_pipeline\tests -v
```

No automatic model smoke test/pilot is required. Passing these contracts would
not establish model accuracy, real VRAM fit, throughput or ranking quality.

## Future application/database mapping (documentation only)

Use `video_id` as the stable content key and `(run_fingerprint, video_id,
source_fingerprint)` as the immutable derived-version key. A future application
can read validated records without importing models. Later normalized storage
could map video/source refs into a videos table; run/config fingerprints into
representation-version records; controlled taxonomy/topics/tags into related
tables; per-field quotes into provenance rows; and `embedding.npy` vectors into
a vector(1024) field indexed only within a compatible representation version.
Store input and vector SHA-256, model revision and preprocessing version alongside
each vector. Maintain affect annotations/calibration in separate records.
These are mapping considerations only; no database artifacts are implemented.

## Unresolved limits

The implementation was statically reviewed only. Dependency installation, imports,
actual inference, memory/latency, extraction success rate and multilingual
retrieval quality remain unverified by instruction. NF4 and FP16 CUDA kernels
can vary slightly across hardware, drivers and adaptive batch shapes; frozen
definitions improve reproducibility but do not promise bit-identical vectors.
Long transcripts, incorrect Gemini/ASR evidence and weak creator metadata can
produce incomplete or wrong semantics despite schema/quote validation. There
is no independently measured semantic confidence or audience targeting.

Polling currently rereads available Gemini lines and verifies completed vectors
and source hashes each cycle. This favors integrity at a few thousand videos,
but can add disk overhead. Staged mode reloads models per bounded queue; increase
batch sizes or use resident mode only in a new configuration/run after checking
memory yourself. Stop responsiveness depends on model calls returning. Keep
model caches and run artifacts backed up; the system never downloads missing
models automatically or changes frozen affect research behavior.
