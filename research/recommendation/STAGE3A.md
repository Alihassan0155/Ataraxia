# Stage 3A — Synthetic user simulator

Stage 3A runs one video at a time on the full Stage 1 catalogue. It is
literature-grounded and has no empirical calibration against real Ataraxia users.
Gemini annotations describe content. The simulator measures annotated exposure
and assigns no causal recovery, psychological fatigue or mood dynamics.

## Interfaces

- `SimulatorConfig` describes one synthetic population or experimental condition.
- `SyntheticSimulator(catalogue, config).reset(profile_seed, environment_seed)`
  returns public onboarding categories, the onboarding vector and zero exposure.
- `step(video_id)` takes one eligible ID and returns watch duration in seconds,
  watch ratio, completion, immediate pass, incomplete viewing, step count,
  termination and truncation flags, reason and updated public observation.
- Consumers should receive only the frozen `Observation` and `StepResult`
  values. Underscored simulator fields are private Python implementation
  state. Code with the simulator object itself can introspect those fields.
- `profiles.py` generates priors, `response.py` samples viewing,
  `transition.py` updates preference/exposure and `episode.py` orchestrates.

The Stage 1 loader adds a trailing optional duration field to preserve existing
callers and fixtures. The simulator requires positive finite durations for every
record and reuses Stage 2 checks for aligned IDs and finite unit embeddings.
It rejects invalid input as a whole. The retained local catalogue has 2,317
valid durations (4.90–90.83 seconds). The CLI loads it read-only.

## Equations and provenance

Let e be the unit item embedding, s the private unit interest, B the prior
exposure of its category, q the private item quality and R the watch ratio.

| Mechanism | Equation and provenance |
| --- | --- |
| Profile | Select k distinct categories uniformly and use equal-weight normalized centroids for public onboarding. Privately draw Dirichlet weights with concentration alpha and normalize their centroid mixture plus Gaussian noise with per-coordinate scale sigma0/sqrt(d). Original category prior and centroid conditioning adapt the standard-normal initialization in [RecSim NG](https://storage.googleapis.com/gweb-research2023-media/pubtools/6160.pdf), §3.3 p.11. |
| Quality | Draw q uniformly on [-1,1] per sorted canonical ID, or use a configured constant. Original bounded prior independent of content features. It is fixed across episodes with the same catalogue and environment seed. |
| Initial choice | Bernoulli with sigmoid(b_start − affinity_weight × norm(e − s) − repetition_weight × B). Adapted negative Euclidean affinity and MNL from RecSim NG §3.3 p.11 and §4.2 p.18. The single item competes with a zero-logit outside option. Quality enters only after engagement. |
| Utility | U = (1 − quality_weight) × dot(s,e) + quality_weight × q. Adapted interest/quality mixture from [RecSim](https://arxiv.org/pdf/1909.04847), §3.2 pp.10–11. |
| Watching | Conditional completion propensity chi = sigmoid(b_watch + watch_weight × U − repetition_weight × B). This link is original. For J progress units, p = chi^(1/(J−1)). The geometric law P(G=g)=p^g(1−p) is directly adopted from [SWaT](https://arxiv.org/pdf/2408.07759), §3.3.2 PDF p.5 Eq.7. Inversion samples 1+min(G,J−1) units after engagement, with zero after a pass. Progress units, the engagement gate and end censoring are adaptations. |
| Outcomes | R = watched units / J, seconds = duration × R, completed iff all J units are watched. Conditional completion probability is p^(J−1)=chi. Incomplete viewing is the complement of completion and includes immediate passes. These indicators do not reproduce the production skip event. |
| Lapses | For each of the engagement and conditional completion probabilities, replace p with (1−lapse)p+lapse/2 before sampling or converting to continuation probability. Original noise control. |
| Interest | On engagement, normalize s + rate × q × (e−s) + sigma × N(0,I)/sqrt(d). Use the prior direction if the proposed norm is near zero. On pass, keep s. Adapted RecSim NG §3.3 p.11 with bounded direction and dimension-scaled noise. |
| Category exposure | B_next = gamma × B + (1−gamma) × R × one_hot(category). Adapted [Rebounding Bandits](https://proceedings.neurips.cc/paper/2021/file/2109737282d2c2de4fc5534be26c9bb6-Paper.pdf), §3 p.3 Eq.1, using category instead of arm, fractional consumption and bounded scaling without independent exposure noise. Category is a topic proxy. |
| Affect exposure | Z_next = delta × Z + (1−delta) × R × (valence, arousal, eight emotions, recovery score). Original descriptive summary in the Stage 1 emotion order. It is a weighted sum with zero initial mass. |
| Episodes | Fixed experimental horizon. Operational truncation occurs if every eligible ID has been served first. An immediate pass consumes a recommendation opportunity. These are original protocol choices. |

[KuaiSim](https://papers.neurips.cc/paper_files/paper/2023/file/8c7f8f98f9a8f5650922dd4545254f28-Paper-Datasets_and_Benchmarks.pdf),
§3.2 Algorithm 1, informed the modular separation of immediate responses and
episode handling. Its learned response network and temper rules are outside
this stage. Like, affect preference response terms and alternate duration
families from the broader v0.2 proposal are outside this simulator core.

## Provisional configuration

All numeric defaults are experimental settings.

| Fields | Defaults |
| --- | --- |
| horizon, category_count, concentration, initial_noise | 30, 2, 1, 0.10 |
| quality_constant, quality_weight | None (uniform), 0.25 |
| start_intercept, affinity_weight | 2, 2 |
| watch_intercept, watch_weight, progress_units | 0, 1, 20 |
| interest_rate, transition_noise | 0.02, 0.005 |
| repetition_retention, repetition_weight | 0.8, 1 |
| exposure_retention, lapse | 0.8, 0 |

Set both interest rate and transition noise to zero for stationary interests.
Set repetition weight to zero for unchanged exposure measurement without a
behavioural penalty. Use 0.25 and 2 for provisional low and high sensitivity.
Set quality_constant to 0 or 1 for constant-quality controls. Vary lapse to
change inconsistency. At lapse 1, both response propensities equal 0.5 for
every item, although private interests can still evolve.

Profile randomness uses the profile seed. Quality and step-indexed streams
for initial engagement, viewing and transition use distinct spawn keys under
the environment seed. This enables pairing runs without shifting the next
step's draws when a video is passed.

The v0.2 design left repeat serving and exhaustion policy open. Stage 3A
allows each ID once per episode, including passes. This matches the demo's
served-ID filtering and makes exhaustion explicit. Category repetition still
occurs across distinct videos. Horizon takes precedence if both limits occur
on the same step. Baseline termination is always false.

## Run and validate

```sh
.venv/bin/python -B -m unittest discover -s research/recommendation/tests -v
.venv/bin/python -B -m research.recommendation.simulator.demo --profile-seed 42 --environment-seed 73
```

The 37-test suite includes all 30 existing Stage 1/2 tests. The geometric
test uses 60,000 shared draws at each of 10, 20 and 40 progress units. For
target conditional completion 0.37, all three gave 0.3667. First-unit mass
and intermediate survival also agreed with analytical values within 0.008.

The CLI selects by the public onboarding vector and excludes previously
served IDs. Three paired 30-step runs used Beauty & Style and Religion &
Spirituality. Repetition weights 0, 0.25 and 2 yielded respectively 473.16,
468.93 and 434.79 seconds watched. Each had 13 passes and nine completions.
These are single-seed outcomes, not population estimates. All three stopped
at the horizon. A complete trace is available by running the command above.

Progress-normalized watching gives the same completion propensity for clips of
different lengths at identical utility. Raw watch seconds therefore reflect
clip duration as well as response. Behaviour coefficients and synthetic quality
are uncalibrated. The simulator represents first-pass viewing only and its
fixed horizon represents an experimental limit.
