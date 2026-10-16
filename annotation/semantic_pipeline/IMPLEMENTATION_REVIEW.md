# Implementation review — 2026-10-13

This is a static implementation review, not a runtime validation report.
No Python scripts, tests, installation, model downloads, inference, embedding
generation, workers or database operations were executed. Gemini was not stopped,
restarted or modified. Existing source annotations, media, transcripts,
preprocessing and research outputs were not edited.

Implemented boundaries:

- Independent `ataraxia.semantic` package; explicit checkout launcher under
  `semantic_pipeline/scripts/`; no changes to affect model implementations.
- Read-only completed Gemini JSONL ingestion using the existing `VideoAnnotation`
  contract; strict metadata IDs, partial-line deferral and conflicting-ID reporting.
- Frozen run snapshots covering both immutable model revisions, taxonomy, prompt,
  schemas, embedding template, metadata CSV, inference settings, code and installed
  package versions. Resume and publication refuse definition drift.
- Evidence-supported semantic JSON plus deterministic retrieval text, original
  language/context references, explicit unknowns and uncalibrated confidence.
- Offline NF4 text extraction and dense-only CLS BGE-M3 encoding; float32 unit
  vectors, exact text preservation, batch splitting on OOM and no silent token crop.
- Atomic file artifacts, per-source versions, recoverable extraction stage,
  bounded backoff, single-writer/GPU locks, graceful controls and manifest rebuild.
- Portable project/run-relative source references and documented future normalized
  storage mapping; no database/index implementation.

Static inspection found the shared main-PC distributed lock is
`C:/ProgramData/AtaraxiaWorker/gpu0.lock`; the semantic default matches it. A paused
semantic worker retains that lock; stop it before using that GPU for distributed
annotation. Gemini's API worker is independent.

Prepared CPU-only tests cover completed/partial source detection, conflicting IDs,
quotes, taxonomy/tags, text determinism, vector validation, frozen resume refusal,
metadata reuse and OOM batch splitting. They are not reported as passing because
they were not executed. Installation and invocation commands are in README.md.

Unresolved checks: import/package compatibility in the new environment, actual
offline snapshot loading, CUDA memory/throughput, schema success rate, multilingual
semantic accuracy and retrieval quality. Source quotes verify traceability only.
Historical ASR/Gemini provider revisions cannot be reconstructed from missing
provenance. Frozen settings do not ensure bit-identical GPU results across hardware.
The worker has no forced driver-call watchdog; clean stopping waits for bounded
model calls to return. Source/output verification on every poll trades additional
disk reads for integrity. A damaged completed artifact is reported and preserved,
with regeneration directed to a new run instead of overwriting research evidence.
