# Stage 4B · Long-term preference memory

FYP Equation 5.2 maintains a unit direction in the existing 1,024-dimensional
BGE-M3 space. Initialize it from the public onboarding centroid.

$$
L_t = \operatorname{normalize}\!\left((1-\alpha_l q_t)L_{t-1} + \alpha_l q_t E_i\right).
$$

Apply the first matching rule.

| Public interaction | Feedback weight $q_t$ |
|---|---:|
| Immediate pass or zero watch ratio | 0 |
| Explicit Like | 1 |
| Watch ratio at or above the threshold | $\beta_l$ × watch ratio |
| Other | 0 |

The provisional defaults are `alpha_l=0.02`, `threshold=0.8`, and
`beta_l=0.5`. A Like uses a 0.02 mixing coefficient even on a partial watch.
An unliked watch at the threshold uses 0.008, and an unliked full watch uses
0.01. These gates deliberately emphasize strong positive signals. They ignore
weaker feedback and can reinforce the choices of the serving policy. All three
settings and the raw watch ratio must lie in [0, 1]. Missing Like feedback is
false. Zero feedback keeps the previous direction exactly. The update reuses
scaled unit normalization and falls back to the previous direction if the
proposal cancels or has norm below the existing near-zero cutoff.

CLSR motivates keeping long- and short-term preferences separately accessible.
RecSim NG §3.3 illustrates an incremental direction update based on a consumed
item and the previous latent state. Ataraxia's normalized EMA and public
feedback gates are its own adaptations. Here the vector is recommender memory,
and the update uses public watch and Like feedback instead of latent quality or
transition noise. [CLSR, WWW 2022](https://doi.org/10.1145/3485447.3512098) ·
[RecSim NG](https://arxiv.org/abs/2103.08057)

## Lifecycle and standalone retrieval

Create one `LongTermMemory(catalogue, onboarding_vector)` per user and retain
that instance across sessions. At a session boundary, reset STM and start with
empty session exclusion history. LTM retains its vector in process. Use
`reset_for_user(new_onboarding_vector)` to reassign an instance, or create a
separate instance for a different user.

Call `update(video_id, watch_ratio, liked=..., immediate_pass=...)` after a
public interaction. It returns the feedback weight for diagnostics. Retrieve
independently with `retriever.retrieve_relevant(ltm.retrieval_state(watched_ids))`.
The caller supplies current session history. LTM alone does not track served
videos. STM continues to expose its own retrieval state.

## Validation

```sh
.venv/bin/python -B -m unittest discover -s research/recommendation/tests
.venv/bin/python -B -m research.recommendation.ltm_demo
```

All 71 research tests passed, including the previous 64. The demo used the
read-only 2,317-item local catalogue, profile seed 42, a fixed quality seed
901, and three sessions of 30 steps each. STM supplied the served items. Both
memories received the same public feedback and used the same session exclusions
when comparing candidate sets. Drift is Euclidean distance from each memory's
session-start vector. Cumulative LTM drift is measured from initial onboarding.

| Environment seed | Eligible updates | Likes | STM drift | LTM drift | Cumulative LTM drift | Top-20 overlap mean / min / final |
|---|---:|---:|---:|---:|---:|---:|
| 901 | 9 | 1 | 0.516929 | 0.030675 | 0.030675 | 4.90 / 2 / 5 |
| 902 | 12 | 0 | 0.586896 | 0.037454 | 0.054443 | 5.67 / 0 / 9 |
| 903 | 13 | 3 | 0.612382 | 0.052216 | 0.091003 | 4.00 / 0 / 0 |

Every session began with STM at onboarding and LTM exactly at the prior
session's ending vector. This validates memory persistence in process. The
simulator independently resets latent interest and exposure at each boundary.
The single synthetic profile, its sampled Likes and the provisional gates
provide no empirical calibration of cross-session behaviour.
