# Local catalogue and dynamic candidate retrieval (Stages 1–2)

This standalone research package loads existing features and retrieves dynamic
candidate pools. It contains no simulator, final recommendation policy, RL
implementation, model inference or cloud client. Stage 2 interfaces, provisional
thresholds and validation results are documented in [STAGE2.md](STAGE2.md).

From the repository root, with the existing main Python environment:

```sh
.venv/bin/python -m research.recommendation.demo
.venv/bin/python -m unittest discover -s research/recommendation/tests -v
```

Dependencies: Python 3.11+, NumPy and psycopg 3 (already installed in the main
environment and recorded in the existing environment snapshot). Imports reuse
`backend.video_data.catalogue` and `backend.video_data.artifacts`; no production
backend files were changed. The project root must be on the Python import path
(the commands above ensure this).

The default source is the retained database
`ataraxia_backup_20261109t193806z`, accessed only through `/tmp:5432`. The loader
starts a repeatable-read, read-only transaction with a statement timeout. It
never loads `.env` or a production DSN. `--database NAME` selects another local
restore; URLs/connection strings and ambient PGSERVICE/PGHOSTADDR routing are
rejected. It reads seven feature/provenance tables, excluding Auth, user
preferences and processing jobs. A missing local database fails; there is no
cloud fallback or automatic restore.

An alternative is `--package PATH` for an existing
`ataraxia-catalogue-package-v1` JSONL package. The existing utility verifies its
manifest checksums and row counts. The native `.dump` is not that format; use
the retained local database rather than rewriting or re-exporting the backup.

To save detailed exclusions, create an ignored `local/` directory and pass a
fresh filename (existing files are refused):

```sh
mkdir -p research/recommendation/local
.venv/bin/python -m research.recommendation.demo \
  --report research/recommendation/local/my_validation.json
```

## Data sources and identity policy

- Native verified backup: `backend/backups/20261109T193503Z/`, captured November
  10 Pakistan time. Its README identifies the retained local restore. The dump
  includes the full feature tables and sensitive Auth data; it stays ignored.
- Canonical `public.videos.video_id` joins to
  `public.video_semantics.video_id`. Semantics explicitly select `affect_id`
  and `context_id`. Embeddings join by `semantic_id`, with matching canonical
  video and run, model/revision, template, input hash and embedding metadata.
- `public.affect_annotations` contains Gemini outputs;
  `public.video_semantics` contains Qwen semantic outputs;
  `public.video_embeddings` contains BGE-M3 vectors;
  `public.interest_categories` is the existing category taxonomy.
- Existing pipeline access/import logic is in `backend/video_data/artifacts.py`,
  `catalogue.py`, `repository.py` and `full_sync.py`. Filesystem semantic records
  would normally live at `annotation/semantic_pipeline/runs/*/videos/*/*/record.json`
  and reference `embedding.npy`. That runs directory is absent in this checkout.
  Other local annotation/transcript artifacts exist, but a complete feature
  source is already available in PostgreSQL; no reconstruction is necessary.

Latest semantic completion timestamps determine selection, with no older
fallback when the latest record is incomplete or invalid. Timestamp ties,
ambiguous embeddings and cross-video relationships fail closed. Duplicate
primary IDs abort loading. Orphan relationships are reported. Current snapshot
has exactly one semantic and embedding per annotated semantic video.

Existing validators check payload hashes, frozen run and source provenance,
projection consistency and exact embedding compatibility. Eligible vectors must
be finite float32, dimension 1,024, and have L2 norm within 0.0001 of one. Nothing
is normalized or repaired. A single embedding model/revision/template space is
required. Affect needs finite in-range valence [-1,1], arousal, recovery suitability
and confidence [0,1], the eight existing emotion keys, valid dominant emotion,
and probabilities [0,1] summing within [0.99,1.01], following the existing
annotation schema. A category must resolve to an existing taxonomy entry;
`unknown` is excluded as unresolved. No confidence threshold, sample cap,
orientation resampling or new language inference is applied. Source language
fields are preserved as supplied; blank values are not speech verification.
Eligibility here means feature completeness/validity, not a new media or
language eligibility audit. Media is not downloaded or opened; later playback
would need separate access. Affect predictions remain model estimates.

## Python interface

```python
from research.recommendation import load_local_database

catalogue = load_local_database()
i = catalogue.id_to_row[catalogue.records[0].video_id]
vector = catalogue.embeddings[i]       # float32, (1024,)
record = catalogue.records[i]          # frozen VideoFeatures, explicit provenance IDs
features = catalogue.affect[i]         # float32, (12,); names in report['affect_columns']
```

`records`, `video_ids`, embedding rows and affect rows share canonical-ID sorted
order. Arrays are marked read-only, and `id_to_row` is an immutable mapping.
`VideoFeatures` preserves category identity, summary, affect, emotions, model
revision and the linked feature IDs. `report` contains coverage, distributions,
exclusions and orphan issues. No catalogue payloads or vectors are written by
loading. Aggregate validation is in `validation_summary.json`; detailed video
IDs are kept only in ignored `local/` reports.
