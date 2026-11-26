# Stage 3C — Simulator hardening

The behavioural equations, defaults, exposure definitions, watch distribution
and 30-step protocol are unchanged. Stage 3B's observations about weak default
preference evolution remain a research question.

## Numerical handling

The two hidden-interest normalization sites now share a scaled Euclidean
normalizer. For a finite vector v, divide by max(abs(v)) first and then by the
norm of the scaled vector. Compare the original norm against the existing
1e−12 cutoff by division to avoid overflow. A zero or near-zero proposal
uses the normalized fallback. Invalid shape, nonfinite values and an unusable
fallback raise ValueError. The reached preference direction is equivalent to
the original expression in exact arithmetic.

The Gaussian proposal is rescaled before addition if its per-coordinate
standard deviation exceeds one. This preserves direction and scales the
near-zero threshold by the same factor. The same Gaussian distribution and
transition coefficients apply. Stage 2 normalizations used for profile
creation only receive bounded means of checked unit embeddings and at most
one category weight per catalogue category. The response distance and
transition displacement are also bounded by the unit-vector inputs.

Configuration validation rejects non-real, Boolean and nonfinite coefficients
as well as values outside declared domains. Logit coefficients reserve
float64 headroom at max/8. Dirichlet concentration must be at least the
smallest positive normal float64 and at most max/8/category_count so its
aggregate scale has headroom. Extreme finite noise remains supported.

## Seed derivation

Call `reset(profile_seed, environment_seed, quality_seed=...)` with nonnegative
integer seeds. The two-argument call defaults quality_seed to environment_seed.
All generators use NumPy default_rng.

| Channel | Derivation |
| --- | --- |
| Profile | default_rng(profile_seed), preserving onboarding and hidden initialization draws |
| Catalogue quality | SeedSequence(quality_seed, spawn_key=(0,)), preserving the original quality map for the same seed, sorted canonical IDs and quality mode |
| Initial engagement | SeedSequence(environment_seed, spawn_key=(1, step, *profile_key)) |
| Watch duration | Same derivation with channel 2 |
| Interest-transition noise | Same derivation with channel 3 |

Here profile_key is the four uint32 words of
`SeedSequence(profile_seed).generate_state(4)`, and step is one-based.
Each response generator is recreated from its key. Profile and environment
pairs have separate response streams, while policies using the same pair
get common random numbers at corresponding steps. Video IDs, strategy
labels, policy identity, quality seed and previous draw counts are absent
from the response key. NumPy version and RNG scheme should be pinned for
experiment reproduction.

## Revalidation

Run from the repository root:

```sh
.venv/bin/python -B -m unittest discover -s research/recommendation/tests -v
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python -B -m research.recommendation.simulator.validate > research/recommendation/local/stage3c_results.json
```

The runner is unchanged from Stage 3B. It uses 128 profiles crossed with
six environment seeds, nine conditions and the full 2,317-video catalogue.
With the two-argument reset, the six quality maps are still shared across
profiles within each environment. The same crossed 2,000-replicate bootstrap
keeps the comparison method fixed and accounts for the shared quality-map
axis. The original results remain in `local/stage3b_results.json` with SHA-256
`1af2525c2fcc4c65a0e91d3bee061bf6fbe0f3c4802ba7b074748cf4b323a3a9`.

Each cell reports the mean and 95% crossed bootstrap interval.

| Condition | Engagement % before → after | Completion % before → after | Watch seconds / offer before → after |
| --- | --- | --- | --- |
| default | 54.11 [46.45, 59.82] → 58.73 [57.78, 59.68] | 37.04 [32.74, 40.50] → 34.25 [33.36, 35.20] | 18.56 [16.29, 20.47] → 18.65 [17.96, 19.40] |
| stationary | 54.11 [46.46, 59.83] → 58.75 [57.82, 59.69] | 37.03 [32.78, 40.48] → 34.27 [33.39, 35.22] | 18.55 [16.29, 20.47] → 18.65 [17.97, 19.42] |
| repeat_zero | 62.50 [55.13, 68.82] → 65.01 [63.94, 66.06] | 44.97 [40.22, 49.66] → 41.84 [40.72, 42.91] | 21.95 [19.82, 23.84] → 21.59 [20.80, 22.41] |
| repeat_low | 60.76 [53.26, 67.15] → 63.43 [62.40, 64.39] | 43.14 [38.75, 47.42] → 39.75 [38.69, 40.79] | 21.18 [19.01, 23.20] → 20.81 [20.07, 21.62] |
| repeat_high | 49.89 [42.82, 55.65] → 53.51 [52.62, 54.44] | 29.39 [25.62, 32.97] → 28.82 [28.13, 29.54] | 16.43 [14.39, 18.05] → 16.38 [15.80, 17.04] |
| quality_negative | 62.50 [55.13, 68.82] → 65.01 [63.94, 66.06] | 40.55 [36.30, 44.88] → 38.00 [36.97, 39.10] | 21.22 [19.14, 23.07] → 20.67 [19.92, 21.47] |
| quality_positive | 62.50 [55.13, 68.82] → 65.01 [63.94, 66.06] | 47.89 [43.59, 52.32] → 45.39 [44.35, 46.43] | 22.62 [20.51, 24.51] → 22.42 [21.62, 23.27] |
| lapse_half | 49.01 [40.80, 54.89] → 54.86 [53.91, 55.86] | 30.15 [25.59, 33.17] → 29.87 [29.00, 30.79] | 16.26 [13.95, 17.95] → 16.88 [16.27, 17.57] |
| lapse_full | 47.22 [40.00, 52.78] → 50.03 [49.05, 51.03] | 25.56 [21.67, 28.89] → 25.23 [24.41, 26.08] | 15.10 [13.04, 16.72] → 14.88 [14.32, 15.49] |

The run completed 6,912 episodes, 207,360 steps and 3,072 first-step probes.
All 45 tests passed, including the 40 existing tests. Profile and environment
IDs, catalogue size, the 575 distinct served IDs count, 12 fallback profiles
and the complete arrays of quality/content correlations were identical to
Stage 3B. Maximum hidden unit-norm error was 4.44e−16. No evaluated
probability crossed the 0.01 or 0.99 saturation thresholds.

- Default passes fell from 45.89% to 41.27%. Completion among engaged views
  fell from 68.45% to 58.32%. Most aggregate shifts were modest relative to
  Stage 3B intervals. With six draws per corresponding step in Stage 3B,
  a favorable or unfavorable draw affected every profile sharing its seed.
  The new streams remove that synchronized noise, narrowing intervals.
  Mean model engagement propensity moved only from 58.62% to 58.73%,
  and mean conditional completion propensity evaluated across offers moved
  from 57.46% to 57.57%. These checks support a sampling explanation for
  the larger shifts in realized outcomes.
- Lapse 1 gives the analytic targets of 50% engagement and 25% marginal
  completion. The corrected observed values were 50.03% and 25.23%.
  The across-profile SD of mean watch ratio rose from effectively zero to
  0.0333 despite smaller confidence intervals for the overall means.
  Top-versus-bottom semantic probes remain exactly paired under lapse 1.
- In the corrected semantic probe the engagement contrast was +17.71 pp
  (95% CI +13.54 to +22.53), versus +38.67 pp (+8.20 to +72.92) in Stage 3B.
  This large change is compatible with Stage 3B's wide interval. The
  corrected contrast still supports the expected direction.
- High versus low repetition reduced engagement by 9.92 pp (95% CI
  9.35–10.47 pp reduction), versus 10.86 pp before. Positive versus negative
  quality increased completion by 7.40 pp (6.87–7.91 pp), versus 7.34 pp
  before. Initial engagement remained identical across the quality pair.
  Exposure still decayed by 0.8^10 over every intervening category block.
- Default versus stationary watch ratio differed by about −0.01 percentage
  points (95% CI −0.06 to +0.02 pp). The default hidden direction moved
  0.0378 in Euclidean distance (0.0371–0.0385). The weak behavioural effect
  over this horizon persists.
- Both result files carry all metrics, profile SDs, seed means and paired
  intervals. The reported intervals describe this synthetic design and
  are not empirical confidence intervals for human viewing behaviour.

The simulator is ready for controlled four-pool integration using the public
observation interface. This establishes numerical and reproducibility
properties under the tested conditions. Real-user calibration and robustness
to alternate simulator assumptions remain separate questions.
