# Stage 2 — dynamic candidate retrieval

`CandidateRetriever` reuses the validated Stage 1 `Catalogue`. It keeps every
eligible embedding available and scores the entire catalogue on every call.
It returns candidate pools; it never chooses a final recommendation, advances a
simulator, learns preferences, computes rewards or trains a model.

Run from the repository root:

```sh
.venv/bin/python -m research.recommendation.retrieval_demo
.venv/bin/python -m unittest discover -s research/recommendation/tests -v
```

Select initial categories, pool size and thresholds:

```sh
.venv/bin/python -m research.recommendation.retrieval_demo \
  --category 'Comedy' --category 'Music & Dance' --k 20 \
  --min-relevance 0.30 --max-relevance-drop 0.15
```

Use `--show-candidates` to print IDs, categories, scores, affect and eligibility.
`--report research/recommendation/local/NEW_FILENAME.json` saves all results to a
new file (existing files are refused). Keep detailed reports under ignored
`local/`. The demo defaults to the existing local restore through Stage 1's
Unix-socket/read-only loader. `--database NAME` or `--package PATH` selects another
local source. There is no remote fallback, new inference or database write.

## Interfaces and state changes

```python
from dataclasses import replace
from research.recommendation import (
    CandidateRetriever, RetrievalConfig, load_local_database,
)

catalogue = load_local_database()
retriever = CandidateRetriever(catalogue, RetrievalConfig(main_k=20))
state = retriever.initialize_state({'Comedy': 1.0, 'Music & Dance': 1.0})
main = retriever.retrieve_relevant(state)  # default Top-20
more_diverse = retriever.retrieve_diverse_alternatives(state)
more_recovery = retriever.retrieve_recovery_alternatives(state)

# Explicit exposure supplied by the caller, not a policy implemented here:
state = replace(state, watched_ids=state.watched_ids + ('AN_ELIGIBLE_VIDEO_ID',))
fresh = retriever.retrieve_relevant(state)

# Explicit preference replacement; history is retained:
state = retriever.initialize_state(
    {'Nature, Animals & Conservation': 1.0}, watched_ids=state.watched_ids,
)
fresh = retriever.retrieve_relevant(state)
```

The history example uses a placeholder; supply an actual canonical catalogue ID.
`RetrievalState` is immutable and accepts a finite, nonzero 1,024-dimensional
interest vector, so later experiments may supply updated vectors directly.
This module implements no rule for how user interests evolve. History is an
oldest-first tuple of watched/exposed video IDs. Unknown history IDs are rejected
rather than silently ignored.

Each category centroid is the arithmetic mean of all its eligible video vectors,
then normalized. Initialization normalizes the weighted sum of these unit
centroids. A sequence of category names gives equal weights, independent of
category size; a mapping gives explicit nonnegative weights. Empty selections,
unknown categories, duplicate names, invalid weights and zero/cancelled vectors
raise `ValueError`. Centroids use the fixed eligible catalogue, including watched
items; history controls retrieval availability, not the definition of a category.

Each retrieval call normalizes the current interest vector, scores all N videos
using dot products with the normalized embeddings (cosine similarity), excludes
history, and sorts by descending relevance with canonical ID as a tie breaker.
There is no random sampling, permanent playlist or state-dependent score cache.
An exposure-only update can leave raw cosine scores unchanged but changes
availability, the main pool, relative floor and alternative eligibility.

## Provisional defaults

These are transparent experiment settings, **not calibrated quality thresholds**.
All are configurable through `RetrievalConfig`; the demo exposes corresponding
flags (`--include-main` flips `outside_main_only` to false).

| Setting | Default | Meaning |
| --- | --- | --- |
| `main_k` | 20 | Main pool size |
| `alternative_k` | 20 | Maximum returned alternatives per search |
| `history_rule` | `all` | Exclude all previously watched IDs |
| `history_window` | 20 | For `recent`, exclude IDs from the last N exposure events |
| `min_relevance` | 0.30 | Absolute cosine floor for alternatives |
| `max_relevance_drop` | 0.15 | Maximum relevance loss from current best available video |
| `min_semantic_distance` | 0.10 | Minimum cosine distance from the nearest main-pool video |
| `min_recovery` | 0.60 | Absolute Gemini recovery-suitability floor |
| `recovery_margin` | 0.05 | Required strict gain over mean main-pool recovery |
| `outside_main_only` | true | Alternatives must lie outside the current main pool |

`retrieve_relevant(state, k=...)` overrides size for that call. Alternative methods
also accept `k=...` for their output limit; their main reference pool always uses
`config.main_k`. Set `main_k` in the shared config to change the reference pool
consistently across all searches. Separate retrieval calls do not depend on
which method was called previously.

The main search returns the best available K videos by relevance. The alternative
relevance floor is `max(min_relevance, best_available_cosine - max_relevance_drop)`.
The main pool itself has no relevance cutoff: it is the requested semantic Top-K.
Both alternative searches scan the full available catalogue, applying the floor
before accepting any candidate.

Diversity uses `1 - max(dot(candidate, main_video))` across the entire current main
pool. Accepted candidates are sufficiently different from every main-pool item.
They are sorted by descending semantic distance, then relevance, then ID. This
is a pool of relevant alternatives; it does not enforce pairwise diversity among
returned alternatives or implement a final diversification policy.

Recovery requires the absolute recovery floor **and** a score strictly greater
than `mean(main_pool_recovery) + recovery_margin`. It means improvement relative
to the current main-pool average, not necessarily every main item. Candidates
are sorted by descending recovery suitability, then relevance, then ID. Recovery
suitability is the existing Gemini annotation, not observed user recovery.

`history_rule='recent'` excludes the unique IDs in the last `history_window`
events (repeat exposures consume events). `none` permits previously watched
videos. History is always applied before choosing the main pool and computing
relative thresholds; no search can return an excluded ID.

## Results and failures

Every `RetrievalResult` includes the effective config, requested K, catalogue and
available counts, excluded history count, total qualifying count, relevance floor,
main-pool recovery baseline, status and reason. Each candidate includes:

- Canonical ID, category, cosine relevance and rank among available videos.
- Valence, arousal, recovery suitability, confidence, eight emotion probabilities
  in `catalogue.EMOTIONS` order, and dominant emotion.
- `main_pool`, `meets_relevance_floor`, `diverse` and `recovery` eligibility flags,
  alternative disqualification reasons, outside-main status, distance and gain.

Empty results use `status='empty'` and a reason: `no_qualifying_alternative`,
`history_exhausted_catalogue` or `empty_catalogue`. Partial pools return the
available qualifying items with their total count; they are never padded.
No fallback relaxes relevance, novelty, recovery or history constraints. Invalid
parameters, vector dimensions or catalogue alignment raise an explicit error.
Candidates may qualify for both alternative searches. No ID repeats within a
pool; shared IDs across pools are intentional.

## Local validation — 2026-11-16

Stage 1 still yielded **2,317 videos**, embeddings **(2317, 1024)**. The demo used
Comedy + Music & Dance centroids, default thresholds and a main K of 20.

| Explicit input snapshot | Available | Main returned | Diverse qualifying / returned | Recovery qualifying / returned |
| --- | ---: | ---: | ---: | ---: |
| Initial | 2,317 | 20 | 1,790 / 20 | 581 / 20 |
| Three main IDs added to history | 2,314 | 20 | 1,875 / 20 | 613 / 20 |
| Interests replaced with Nature, Animals & Conservation, history retained | 2,314 | 20 | 999 / 20 | 197 / 20 |

All 20 returned candidates from each alternative search were outside its current
Top-20. Initial relevance floor was 0.669164; minimum returned relevance was
0.669941 for diversity and 0.673283 for recovery. Initial main-pool mean recovery
was 0.337. No irrelevant random padding was used.

Independent full-matrix ordering, deterministic repeated retrieval, alternative
relevance thresholds, history exclusion and unique IDs passed on the local data.
The synthetic suite covers exact Top-20 order, configurable K, alternatives
outside Top-20, relevance/novelty/recovery constraints, all history modes, dynamic
preference and exposure changes, ties, empty/short catalogues, no qualifying
alternatives, ID alignment and malformed inputs. All 30 automated tests passed: 16 Stage 2 tests and 14 unchanged Stage 1 tests.
The saved local main-pool IDs also changed after both exposure and preference updates.

Detailed candidate reports are private under `local/`; the demo can reproduce
the results from the retained database. No database files or backups were changed.

Stage 2 files created:

- `research/recommendation/retrieval.py`
- `research/recommendation/retrieval_demo.py`
- `research/recommendation/tests/test_retrieval.py`
- `research/recommendation/STAGE2.md`
- `research/recommendation/local/stage2_validation_20261116.json` (ignored initial report)
- `research/recommendation/local/stage2_validation_20261116_final.json` (ignored final report)

Files modified: `research/recommendation/__init__.py` (public retrieval exports)
and `research/recommendation/README.md` (Stage 2 link and scope).
