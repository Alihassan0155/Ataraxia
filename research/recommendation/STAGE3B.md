# Stage 3B — Simulator validation

Stage 3B audits the simulator described in [STAGE3A.md](STAGE3A.md) against
the approved v0.2 design. The experiments use the retained read-only local
catalogue. Simulator source and parameter defaults are unchanged.

## Mathematical audit

| Mechanism | Finding |
| --- | --- |
| Choice | The stable sigmoid implements exp(logit)/(1+exp(logit)) for one video and a zero-logit outside option. The logit uses negative Euclidean distance and category exposure. Quality first enters after engagement. This combines the affinity example in [RecSim NG §3.3, p.11](https://storage.googleapis.com/gweb-research2023-media/pubtools/6160.pdf#page=11) with the outside-option structure of [§4.2, p.18](https://storage.googleapis.com/gweb-research2023-media/pubtools/6160.pdf#page=18). Neither the coefficients nor the repetition term come from that paper. |
| Interest transition | On engagement, the code adds the signed displacement rate × quality × (item − interest) and Gaussian noise with per-coordinate standard deviation noise/sqrt(d). Unit projection and the near-zero fallback are the v0.2 adaptations. A pass skips the transition. |
| Utility | The convex interest/quality mixture matches the functional form in [RecSim §3.2, pp.10–11](https://arxiv.org/pdf/1909.04847#page=10). Unit-vector dot products and the independent bounded quality prior are Ataraxia choices. |
| Watch trajectory | [SWaT §3.3.2, Eq. 7, PDF p.5](https://arxiv.org/pdf/2408.07759#page=5) uses a geometric continuation distribution in seconds. The simulator implements its survival function for progress units. Conditional on engagement, P(N ≥ n) = chi^((n−1)/(J−1)) for n = 1…J. Completion has mass chi, and pass has zero units. The separate engagement gate, censoring and utility-to-chi mapping are v0.2 adaptations/extensions. |
| Repetition | [Rebounding Bandits §3, Eq. 1, p.3](https://proceedings.neurips.cc/paper/2021/file/2109737282d2c2de4fc5534be26c9bb6-Paper.pdf#page=3) decays arm satiation and adds a pull impulse plus noise. Ataraxia uses a bounded EMA with a watch-ratio-weighted category impulse, omits exposure noise and applies the penalty to logits. Repeated category viewing need not increase exposure on every step. It rises exactly when the current ratio exceeds prior exposure and decays when another category is served. |
| Other controls | The Gaussian/Dirichlet profile prior, synthetic quality, lapses, annotation exposure and horizon are the documented synthetic choices. Stage 3A deliberately excludes affective response preferences, Like, causal recovery, fatigue and session exit. |

## Experiment protocol

- 128 profile seeds (1000–1127) crossed with six environment seeds (901–906).
- Nine conditions and 30 unique served IDs per episode. Video sequence, profile
  seed and step-specific random channels are paired across conditions.
- For the exposure experiment, rank the full catalogue by the public onboarding
  vector. Serve ten videos from the first selected category, ten from the
  second, then ten unused videos from the first. If category sizes cannot fill
  the blocks, select two viable categories by public ranking. Retain all
  profiles. The output reports the number of such fallbacks.
- Semantic probes independently reset and serve the highest or lowest
  onboarding-ranked video at step 1, with shared random draws and stationary
  preferences. This probes the range of the semantic signal, including the
  lapse-1 null control. The two videos may differ on other features. Quality is
  absent from the engagement equation, so it cannot confound that comparison.
- Repetition and quality interventions hold hidden interests stationary.
  The quality pair also disables repetition sensitivity. Lapse conditions
  retain the default transition and vary only the lapse probability.
- Each confidence interval uses 2,000 percentile bootstrap replicates with
  independently resampled profile and seed axes, preserving pairing and within
  episode dependence. Standard deviations are across profile averages.
  Inference is conditional on this catalogue and schedule. Six environment
  seeds limit uncertainty estimates, and intervals are descriptive rather than
  adjusted for multiple comparisons.

## Reproduction

```sh
.venv/bin/python -B -m unittest discover -s research/recommendation/tests -v
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python -B -m research.recommendation.simulator.validate > research/recommendation/local/stage3b_results.json
```

Use the existing ignored local directory for the JSON results. The validation
runner reads private state only for diagnostic assertions and aggregates. It
never passes those data to candidate selection or the public response.

## Results

The run completed 6,912 episodes (207,360 steps) plus 3,072 one-step probes.
All 2,317 catalogue items were available for ranking. The controlled blocks
served 575 distinct videos and 12 profiles needed the category-size fallback.

| Condition | Engagement | Completion / offer | Mean watch ratio | Seconds / offer |
| --- | ---: | ---: | ---: | ---: |
| Default | 54.11% | 37.04% | 0.450 | 18.56 |
| Stationary | 54.11% | 37.03% | 0.450 | 18.55 |
| Repetition zero | 62.50% | 44.97% | 0.535 | 21.95 |
| Repetition low (0.25) | 60.76% | 43.14% | 0.516 | 21.18 |
| Repetition high (2) | 49.89% | 29.39% | 0.398 | 16.43 |
| Quality −1 | 62.50% | 40.55% | 0.517 | 21.22 |
| Quality +1 | 62.50% | 47.89% | 0.552 | 22.62 |
| Lapse 0.5 | 49.01% | 30.15% | 0.394 | 16.26 |
| Lapse 1 | 47.22% | 25.56% | 0.366 | 15.10 |

The default immediate pass rate was **45.89%** (95% CI 40.18–53.55%).
Completion per offer was **37.04%** (32.74–40.50%), or 68.45% among
engaged views. Median watch time per offer was 5.67 s, with a 75th
percentile of 32.21 s and a 90th percentile of 60.01 s. Median watch ratio
was 0.20 overall and 0.40 among engaged incomplete views. Default mean
watch ratio was 0.450 (0.396–0.492), with profile-average SD 0.0128.
Mean watch time was 18.56 s (16.29–20.47 s).

- **Semantic preference.** The top-ranked versus bottom-ranked onboarding
  probe increased hidden cosine by 0.284 and engagement by 38.67 percentage
  points (8.20–72.92 pp). Lapse 1 gave exactly equal paired engagement and
  watch ratios. Extreme-rank probes establish direction, not separation
  among adjacent candidates.
- **Repetition.** High minus low sensitivity reduced engagement by 10.86 pp
  (8.59–14.22 pp reduction), completion by 13.75 pp (11.12–16.47 pp
  reduction) and seconds by 4.75 (3.99–5.79 s reduction). Low minus zero
  reduced mean watch ratio by 0.019 (0.013–0.025 reduction). The first
  category's exposure under high sensitivity went 0.369 → 0.040 → 0.319
  at steps 10, 20 and 30. The middle block multiplied exposure by exactly
  0.8^10 within rounding tolerance in every run. The observed exposure
  rebound follows renewed consumption. In the zero-sensitivity condition,
  exposure still moved 0.475 → 0.051 → 0.423.
- **Quality.** Positive minus negative constant quality increased
  completion by 7.34 pp (5.92–8.73 pp) with identical initial engagement
  on every paired step. A focused test also confirmed opposite directions
  of preference movement for positive and negative quality without noise.
  Across six complete catalogue quality draws, the largest absolute Pearson
  correlation with duration or an affect field was 0.0634. Recovery
  correlations ranged from −0.0285 to +0.0144. These are descriptive
  checks. Independence by construction comes from the quality generator
  receiving only IDs and its independent random stream.
- **Preference dynamics.** Default final hidden displacement was 0.0358
  in unit-vector Euclidean distance (0.0330–0.0381). The change in mean
  watch ratio versus stationary was −0.0001 (−0.0007 to +0.0006), providing
  little behavioural separation over this horizon and schedule. Stationary
  interests and pass transitions were exactly unchanged. Maximum norm error
  across tested trajectories was 4.45e−16.
- **Noise.** Lapse 0.5 and 1 reduced default engagement by 5.09 pp
  (3.22–6.98 pp) and 6.88 pp (5.43–8.03 pp), respectively. A lapse is a
  shrinkage toward 0.5, so introducing it can change the mean as well as
  reduce preference sensitivity. Lapse 1 analytically implies 50% engagement
  and 25% marginal completion. Observed rates of 47.22% and 25.56% are
  consistent with those values given the seed variability.
- **Saturation.** Across all conditions, zero evaluated propensities were
  below 0.01 or above 0.99. Default initial engagement probabilities ranged
  0.400–0.735 and conditional completion 0.400–0.708. The high pass and
  completion masses cannot be judged realistic without real-user data.

The JSON contains all group and paired intervals, seed means, profile
variability, distribution quantiles and feature correlations.

## Verified controls and confirmed limitations

The 40-test suite includes all 37 pre-existing tests and three focused
checks for recovery mutation, exact geometric survival intervals and
quality-driven transition direction. Mutating only the recovery annotation
changed only the corresponding affect exposure coordinate, with identical
feedback, quality and hidden interests for the fixed video sequence.
Strategies are absent from the `step(video_id)` interface and its RNG key.
The same seeded video replay yields the same result. Public dataclasses
contain only public fields. The Python simulator object itself remains
introspectable, so a future policy must receive public values and never the
environment object or validation diagnostics.

**Confirmed numerical defect outside the tested experiment range.**
`SimulatorConfig(initial_noise=1e200)` accepts a finite value. On the
synthetic fixture, the norm calculation overflows and reset produces an
all-zero hidden direction. The intended defaults and all tested controls
preserved unit norms. This audit leaves the simulator source untouched.
A separate fix should use scaling-safe normalization or reject unsupported
configurations and check the resulting direction.

**Dependence and realism limits.** A shared environment seed reuses the
same step-specific random draws across profiles, not only across paired
conditions. The six independent seed streams, rather than 768 independent
response streams, explain the wide intervals and exactly zero profile
variability in lapse-1 watch ratio. A future benchmark should separate
quality-map seeds from profile-specific response streams while retaining
paired draws across policies. The current progress model also creates
point masses at zero and full duration, and generates positive watch time
in 5% increments regardless of seconds. Its duration effect and the fixed
30-step horizon cannot establish human viewing or exit patterns. Category
is a coarse topic proxy. Recovery exposure describes material served and
the response model has no causal recovery term.

## Readiness

Ready for controlled four-pool interface integration using the tested
configuration range and a public-observation-only boundary. Before using
the simulator for comparative policy claims, address the numerical defect
and improve response-seed independence. Include preregistered alternative
duration dynamics and report the weak default preference-evolution signal.
Mathematical agreement and internal consistency are verified within this
scope. Empirical validity against real Ataraxia users remains untested.
