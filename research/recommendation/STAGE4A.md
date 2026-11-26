# Stage 4A · Short-term preference memory

After interaction $t$, the session preference is

$$
S_t = \operatorname{normalize}\!\left(\sum_{i\in H_t} e^{-\lambda(t-t_i)} q_i E_i\right).
$$

- $H_t$ contains the last **10** completed interaction events by default, including immediate passes. Age is counted in interactions, so the newest event has age zero.
- $\lambda$ defaults to **0.2 per interaction**. A one-interaction age difference gives a relative factor of about 0.819. Use `STMConfig(history_window=..., decay=...)` to vary either provisional parameter. A zero decay disables recency weighting.
- $q_i = r_i + \beta_{\mathrm{like}} L_i$, where $r_i$ is the public watch ratio in $[0,1]$ and $L_i$ is the public Like indicator. Missing Like feedback counts as false. The provisional `STMConfig(beta_like=0.5)` gives a maximum combined weight of 1.5 without clipping. A simulator pass has zero weight and still advances the window. Set `beta_like=0` for the exact watch-only weighting.
- $E_i$ is the existing normalized 1024-dimensional BGE-M3 embedding looked up by canonical video ID.

Chen et al. use exponential time decay over interaction timestamps before LLM-based current-interest inference. Stage 4A uses the same exponential form with interaction index as the clock. [ProRec-Video, AAAI 2026](https://ojs.aaai.org/index.php/AAAI/article/view/38475)

Zheng et al. mean-pool recent item embeddings to construct a short-term proxy for contrastive supervision. Stage 4A adapts the recent embedding aggregate into a standalone preference vector and adds watch-ratio weighting as the Ataraxia-specific feedback rule. [CLSR, WWW 2022](https://arxiv.org/abs/2202.13090)

## Session API

Construct `ShortTermMemory(catalogue, observation.onboarding_vector)` at session start, or call `reset(observation.onboarding_vector)` on an existing instance. Reset clears both the recent window and served history. Use `retrieval_state()` for the first retrieval and pass the result of `update(result.video_id, result.watch_ratio)` to `CandidateRetriever.retrieve_relevant(state)` after each interaction. This boundary uses public onboarding, public feedback and catalogue embeddings. The returned `RetrievalState` contains the STM direction and the full chronological served-ID history for Stage 2 exclusion. A future caller can supply the session's onboarding direction and consume the STM snapshot independently.

Empty or all-zero-weight windows return the normalized onboarding direction. The implementation rescales positive weights by their largest value in log space and accumulates in float64. This preserves direction even when a pass streak or large decay would underflow every original coefficient. It uses the existing scaled unit-normalization routine and falls back to onboarding if the rescaled aggregate norm is below $10^{-12}$, as can happen with cancelling directions.

Like-aware callers pass `liked=getattr(result, 'liked', False)` to `update`. The caller can replay the same public events through separate STM instances to isolate the bonus while holding served IDs and watch ratios fixed.

## Verification

```sh
.venv/bin/python -B -m unittest discover -s research/recommendation/tests
.venv/bin/python -B -m research.recommendation.stm_demo
.venv/bin/python -B -m research.recommendation.stm_demo --likes
.venv/bin/python -B -m research.recommendation.stm_demo --likes --environment-seed 901
```

All 64 research tests passed, including five new Like-aware STM tests. Demos used the read-only 2,317-video local catalogue. In paired mode, the beta-zero STM chooses which video to serve, and both memories receive identical feedback. For profile seed 42 and environment seed 73, zero Likes were sampled in 30 steps, so vectors and Top-20 pools matched exactly. For environment seed 901, one Like was sampled at step 10 with a watch ratio of 0.8. Over 30 steps, the mean and maximum vector L2 differences were 0.018525 and 0.070012. Mean Top-20 overlap was 19.60 out of 20, with a minimum of 18. The vectors and pools matched again when the Like left the 10-event window at step 20. This replay measures the isolated weighting effect for these sequences.
