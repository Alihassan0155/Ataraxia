# Stage 4C · Four-pool retrieval

`FourPoolRetriever(catalogue, pool_size=10).retrieve_pools(stm_vector, ltm_vector,
served_ids)` returns a `FourPoolResult` with the original Stage 2 diagnostics
for each pool. The fixed order is **Current, Stable, Recovery, Diverse**.
The availability mask reports whether each pool contains at least one candidate.
Pairwise overlap counts shared canonical IDs across pools.

| Pool | Query and reference |
|---|---|
| Current | Exact cosine Top-K against STM |
| Stable | Exact cosine Top-K against LTM |
| Recovery | STM relevance-gated recovery search with Current as reference |
| Diverse | STM relevance-gated diversity search with Current as reference |

The adapter uses a dedicated Stage 2 config with `main_k=K`, `alternative_k=K`,
`outside_main_only=True`, and `history_rule='all'`. Both vectors receive the same
chronological session history, including passes. The adapter holds no user or
session state. Stage 2's standalone Top-20 defaults still apply to its existing
callers.

The alternative cosine floor remains the larger of 0.30 and the best available
cosine minus 0.15. Recovery also requires suitability of at least 0.60 and a
strict gain above 0.05 relative to the Current pool's mean suitability.
Diversity requires a cosine distance of at least 0.10 from the nearest Current
item. Both alternatives exclude Current candidates. Overlap with Stable and
between alternatives is allowed. Underfilled or empty results retain their
Stage 2 diagnostics and receive no extra items. Moving the alternative reference
from Top-20 to Top-K can change eligibility and rank at the same thresholds.
See [STAGE2.md](STAGE2.md) for equations and ordering.

## FYP alignment

The FYP framework describes four candidate sources refreshed after each
interaction. This stage implements that retrieval boundary with exact cosine
over the local catalogue. Stable-interest uses the learned Stage 4B LTM.
The earlier simulator spec used stable onboarding and outlined one proposal per
eventual DQN action. This stage returns up to K candidates per pool and a mask.
The broader FYP architecture's ANN index, merged pre-ranking, and downstream
policy are beyond this retrieval stage. Recovery is based on Gemini item
annotations. It does not estimate a causal recovery effect.

## Validation

```sh
.venv/bin/python -B -m unittest discover -s research/recommendation/tests
.venv/bin/python -B -m research.recommendation.four_pool_demo
```

All 77 research tests passed, including the 71 prior tests. Streamlit AppTest
covered manual Like and pass feedback, simulator feedback, all-pool refresh,
rerun deduplication, session LTM retention, user reset, and empty alternatives.

The full-catalogue demo scored all 2,317 videos on 31 snapshots, including
onboarding, with fixed profile seed 42 and environment seed 901. It served the
first Current candidate at each step and updated both memories from the public
feedback. All four pools were available on all snapshots. Thirty snapshots
returned ten candidates in each pool. After interaction 22 the sizes were
(10, 10, 1, 6).

| Pair | Shared-ID range across snapshots |
|---|---:|
| Current / Stable | 0–10 |
| Current / Recovery | 0 |
| Current / Diverse | 0 |
| Stable / Recovery | 0–3 |
| Stable / Diverse | 0–1 |
| Recovery / Diverse | 0–2 |

One local run measured bundle latency at 19.56 ms median, 35.14 ms p95, and
37.92 ms maximum. This times retrieval only. Direct reuse performs four
sequential Stage 2 calls, including repeated scoring, sorting, and candidate
similarities to the reference set. For N videos of dimension d this costs
O(NdK + N log N) time and O(NK) temporary space per call beyond the catalogue.
