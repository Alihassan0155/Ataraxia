# Stage 4A.1 · Explicit Like simulation

Enable Likes with `SimulatorConfig(like=LikeConfig())`. The default
`SimulatorConfig()` remains the watch-only baseline and returns the existing
`StepResult` type and fields. In Like mode, `LikeStepResult` extends
`StepResult` with one boolean field, `liked`. Record the mode in experiment
metadata to distinguish watch-only runs from runs with zero sampled Likes.

An immediate pass always returns `liked=False` in Like mode. After an engaged
view, sample a Bernoulli outcome with probability

$$
p_t = \sigma(\alpha + \gamma_a a_t + \gamma_r r_t + b_u),
$$

where $a_t$ is the pre-interaction latent-interest cosine clipped to $[-1,1]$,
$r_t$ is the sampled watch ratio, and $b_u$ is an optional profile-level
propensity drawn from $N(0,\sigma_b^2)$. The sigmoid calculation uses the
existing stable implementation with zero Like-specific lapse. Configuration
validation rejects non-real or nonfinite values, negative coefficients or
propensity scale, and magnitudes above the safe logit range. Valid extreme
logits can saturate to zero or one.

| Parameter | Provisional default |
|---|---:|
| Intercept $\alpha$ | −4.0 |
| Affinity coefficient $\gamma_a$ | 1.0 |
| Watch-ratio coefficient $\gamma_r$ | 1.0 |
| Profile propensity scale $\sigma_b$ | 0.0 |

The intercept starts with a low Like probability. At neutral affinity and 50%
watch, the defaults give about 2.9%. Positive slopes let affinity and watch
ratio affect the odds. The default propensity scale disables extra
between-profile variation.

KuaiRand records Like separately from view time. RecSim motivates sampling user
responses conditioned on latent state. The logistic form, immediate-pass gate,
and coefficients are Ataraxia modelling choices.
[KuaiRand, CIKM 2022](https://doi.org/10.1145/3511808.3557624) ·
[RecSim, 2019](https://arxiv.org/abs/1909.04847)

## Randomness and public feedback

The Like draw uses `SeedSequence(environment_seed, spawn_key=(4, step, *profile_key))`.
The one-based step and profile key follow Stage 3C. Optional propensity uses
`SeedSequence(profile_seed, spawn_key=(5,))` once per reset and is identical
across environment seeds for that profile. The new keys are disjoint from
profile initialization (empty key), quality (0), engagement (1), watch (2),
and transition noise (3). Policy names, pool labels, served IDs, and prior draw
counts are absent from the seed keys. Immediate passes need no Like draw.

Only the sampled boolean extends public feedback. Latent affinity, propensity,
probability and draws stay internal. Like has no role in watch sampling,
interest transitions, or exposure updates.

Stage 4A.1b lets STM consume the same public boolean with
$q_i = \mathrm{watch\_ratio}_i + \beta_{\mathrm{like}} L_i$. Its provisional
`beta_like=0.5` is configurable. A missing Like flag or zero beta preserves
the watch-only STM. See [STAGE4A.md](STAGE4A.md) for the paired replay.

## Validation

```sh
.venv/bin/python -B -m unittest discover -s research/recommendation/tests
.venv/bin/python -B -m research.recommendation.simulator.like_diagnostic
```

All 59 research tests passed, including six Like-specific tests. The diagnostic
ranked the full 2,317-video local catalogue by each profile's public onboarding
vector. It replayed fixed 30-item sequences drawn from high, middle, and low
ranking bands for 16 profiles and three environment seeds. All existing public
fields matched exactly across both modes over 1,440 impressions. Regression tests
also compared private interest and exposure state exactly and replayed Like
outcomes under matched seeds.

| Watch-ratio bin | Likes / impressions | Rate |
|---|---:|---:|
| 0 (immediate pass) | 0 / 598 | 0.00% |
| (0, 0.25] | 5 / 111 | 4.50% |
| (0.25, 0.50] | 4 / 93 | 4.30% |
| (0.50, 0.75] | 5 / 71 | 7.04% |
| (0.75, 1) | 8 / 59 | 13.56% |
| 1 (completed) | 37 / 508 | 7.28% |
| All impressions | 59 / 1,440 | 4.10% |
| Engaged views | 59 / 842 | 7.01% |

The bin rates describe this synthetic replay. The highest partial-watch bin had
only 59 impressions, and the bins mix different latent affinities. Their rates
can vary nonmonotonically even with a positive watch coefficient at fixed
affinity. The model also uses affinity both indirectly through the watch
response and directly in Like probability, which may amplify synthetic
preference signals. No parameters were fitted to real users. The full
parameter-sensitivity sweep is deferred to Stage 7.
