# Three-model pilot annotation comparison

Computed from the same 50 pilot video IDs. No human annotations are loaded. Agreement measures consistency, not correctness or model quality.

## Comparison rules

Valence is on [-1, 1]; arousal and recovery suitability on [0, 1]. Emotion comparisons use the saved `emotions` probability vectors, not the CUDA `emotion_points` values. Historical near-unit totals are normalized in analysis only; source annotations are unchanged.

Thresholds were specified before computing results. Strong pair agreement requires matching dominant emotion AND absolute valence difference <=0.20, arousal <=0.15, recovery <=0.15, and emotion total-variation distance (TV) <=0.20. Substantial pair disagreement means any numerical difference > twice its corresponding strong limit. TV is half the sum of absolute differences across all eight probabilities (range 0 to 1).

All-three strong agreement requires all three pairs to agree strongly. Two-agree/one-outlier requires exactly one strong pair and substantial disagreement between the outsider and BOTH members of that pair. All-three substantial disagreement requires all three pairs to disagree substantially. Remaining cases are mixed/borderline; a dominant-label mismatch alone does not establish substantial numerical disagreement. These are descriptive thresholds, not validated research selection criteria.

## Overall pairwise agreement

| Pair | Valence MAE | Arousal MAE | Recovery MAE | Dominant match | Kappa | Mean TV | Mean JSD (bits) | Strong pairs | Substantial pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemini vs Qwen | 0.266 | 0.140 | 0.346 | 28/50 | 0.312 | 0.455 | 0.293 | 1/50 | 40/50 |
| Gemini vs InternVL | 0.236 | 0.212 | 0.211 | 13/50 | 0.056 | 0.469 | 0.264 | 1/50 | 33/50 |
| Qwen vs InternVL | 0.240 | 0.172 | 0.234 | 26/50 | 0.318 | 0.436 | 0.304 | 7/50 | 32/50 |

MAE is on each scalar's original scale, so valence MAE is not directly comparable to arousal/recovery MAE. Kappa adjusts dominant-label agreement for marginal frequencies; JSD uses log base 2. RMSE, signed biases, Pearson r, concordance correlation (CCC), threshold counts, per-emotion differences and confusion matrices are in the machine-readable exports.

## Consensus and outliers

- all three strong agreement: 0/50.
- two agree one outlier: 5/50.
- all three substantially disagree: 20/50.
- mixed or borderline: 25/50.

All three declared dominant labels match on 12/50 videos; matching that single field does not imply strong agreement across all requested fields. Dominant-label comparisons use the saved declared label, including any valid maximum-score ties.

Strict outlier counts: Gemini: 4; Qwen: 0; InternVL: 1. A model being an outlier does not establish that it is wrong.

## Systematic differences

| Model | Mean valence | Mean arousal | Mean recovery | Zero recovery |
| --- | ---: | ---: | ---: | ---: |
| Gemini | 0.365 | 0.420 | 0.507 | 0/50 |
| Qwen | 0.483 | 0.472 | 0.200 | 32/50 |
| InternVL | 0.299 | 0.618 | 0.404 | 3/50 |

| Emotion | Gemini mean / dominant count | Qwen mean / dominant count | InternVL mean / dominant count |
| --- | ---: | ---: | ---: |
| joy | 0.347 / 24 | 0.466 / 33 | 0.317 / 21 |
| sadness | 0.021 / 1 | 0.044 / 3 | 0.068 / 5 |
| anger | 0.019 / 0 | 0.048 / 3 | 0.110 / 7 |
| fear_anxiety | 0.032 / 1 | 0.034 / 2 | 0.071 / 4 |
| surprise | 0.082 / 1 | 0.102 / 0 | 0.184 / 7 |
| disgust | 0.016 / 0 | 0.020 / 1 | 0.053 / 4 |
| calm_contentment | 0.237 / 10 | 0.016 / 0 | 0.104 / 2 |
| neutral | 0.247 / 13 | 0.270 / 8 | 0.093 / 0 |

Qwen assigns the highest mean valence (0.483) and selects joy most often (33/50). It assigns recovery zero on 32/50 videos, with a lower recovery mean (0.200) than Gemini (0.507) or InternVL (0.404). InternVL assigns higher mean arousal (0.618), selects no neutral dominant labels, and distributes dominant labels across more negative/surprise categories. Gemini assigns more calm_contentment probability (mean 0.237) and calm dominant labels (10/50) than either CUDA model.

These are descriptive tendencies on this pilot, not causal effects or significance-tested population differences.

## Per-video disagreement

Triples are Gemini / Qwen / InternVL. Maximum TV is over the three pairs. The CSV also contains all eight probabilities per model and every pairwise distance/flag. Rows follow pilot metadata order.

| Video ID | Pattern | Outlier | Valence G/Q/I | Arousal G/Q/I | Recovery G/Q/I | Dominant G/Q/I | Max TV |
| --- | --- | --- | --- | --- | --- | --- | ---: |
| FV000012 | All disagree | - | 0.58 / 0.60 / -0.50 | 0.32 / 0.40 / 0.75 | 0.76 / 0.00 / 0.25 | joy / joy / disgust | 0.800 |
| FV000776 | Mixed | - | 0.48 / 0.60 / 0.65 | 0.64 / 0.70 / 0.75 | 0.28 / 0.00 / 0.50 | joy / joy / joy | 0.200 |
| FV000380 | All disagree | - | -0.05 / 0.00 / -0.50 | 0.18 / 0.00 / 0.75 | 0.65 / 0.00 / 0.00 | neutral / neutral / disgust | 0.900 |
| FV000363 | Mixed | - | 0.64 / 0.90 / 0.75 | 0.35 / 0.30 / 0.30 | 0.70 / 0.70 / 0.80 | joy / joy / joy | 0.460 |
| FV000537 | Mixed | - | 0.35 / 0.00 / 0.30 | 0.58 / 0.00 / 0.70 | 0.22 / 0.00 / 0.20 | joy / neutral / anger | 0.900 |
| FV000198 | All disagree | - | 0.21 / 0.00 / -0.30 | 0.28 / 0.00 / 0.40 | 0.58 / 0.00 / 0.20 | calm_contentment / neutral / sadness | 1.000 |
| FV000073 | 2 agree + outlier | Gemini | 0.62 / 0.75 / 0.75 | 0.22 / 0.25 / 0.40 | 0.85 / 0.75 / 0.80 | calm_contentment / joy / joy | 0.620 |
| FV000770 | All disagree | - | 0.35 / 0.60 / 0.65 | 0.32 / 0.30 / 0.75 | 0.65 / 0.00 / 0.80 | neutral / joy / joy | 0.630 |
| FV000942 | Mixed | - | 0.35 / 0.30 / 0.30 | 0.50 / 0.60 / 0.70 | 0.30 / 0.00 / 0.20 | joy / sadness / surprise | 0.580 |
| FV000978 | All disagree | - | 0.18 / 0.85 / 0.30 | 0.45 / 0.80 / 0.80 | 0.38 / 0.10 / 0.20 | neutral / joy / surprise | 0.630 |
| FV000134 | Mixed | - | 0.74 / 0.85 / 0.75 | 0.38 / 0.30 / 0.60 | 0.72 / 0.70 / 0.80 | joy / joy / joy | 0.340 |
| FV000472 | All disagree | - | 0.22 / 0.30 / 0.30 | 0.28 / 0.20 / 0.60 | 0.68 / 0.00 / 0.70 | neutral / neutral / calm_contentment | 0.800 |
| FV000304 | All disagree | - | 0.28 / 0.60 / 0.65 | 0.26 / 0.30 / 0.75 | 0.68 / 0.00 / 0.50 | calm_contentment / joy / joy | 0.650 |
| FV000254 | Mixed | - | 0.38 / 0.85 / 0.30 | 0.62 / 0.75 / 0.75 | 0.20 / 0.00 / 0.20 | joy / joy / fear_anxiety | 0.500 |
| FV000650 | 2 agree + outlier | Gemini | 0.62 / 0.85 / 0.65 | 0.28 / 0.35 / 0.50 | 0.82 / 0.75 / 0.75 | calm_contentment / joy / joy | 0.600 |
| FV000275 | Mixed | - | 0.40 / 0.85 / 0.75 | 0.32 / 0.35 / 0.60 | 0.70 / 0.65 / 0.80 | calm_contentment / joy / joy | 0.600 |
| FV000954 | Mixed | - | 0.68 / 0.95 / 0.75 | 0.69 / 0.85 / 0.85 | 0.22 / 0.00 / 0.30 | joy / joy / joy | 0.200 |
| FV000087 | Mixed | - | 0.48 / 0.85 / 0.75 | 0.46 / 0.45 / 0.60 | 0.52 / 0.30 / 0.80 | joy / joy / joy | 0.300 |
| FV000359 | Mixed | - | 0.52 / 0.60 / 0.65 | 0.30 / 0.30 / 0.40 | 0.78 / 0.70 / 0.70 | calm_contentment / joy / joy | 0.450 |
| FV000004 | All disagree | - | 0.58 / 0.30 / 0.20 | 0.42 / 0.60 / 0.70 | 0.55 / 0.00 / 0.10 | joy / anger / disgust | 0.880 |
| FV000367 | All disagree | - | 0.22 / 0.30 / 0.30 | 0.34 / 0.50 / 0.60 | 0.58 / 0.00 / 0.20 | neutral / neutral / fear_anxiety | 0.700 |
| FV000151 | Mixed | - | 0.28 / 0.60 / 0.30 | 0.60 / 0.40 / 0.70 | 0.22 / 0.00 / 0.20 | joy / joy / joy | 0.330 |
| FV000308 | All disagree | - | -0.48 / -0.80 / -0.50 | 0.58 / 0.95 / 0.85 | 0.08 / 0.00 / 0.10 | fear_anxiety / fear_anxiety / anger | 0.800 |
| FV000131 | Mixed | - | -0.35 / -0.75 / -0.50 | 0.26 / 0.25 / 0.30 | 0.28 / 0.00 / 0.00 | sadness / sadness / sadness | 0.320 |
| FV000814 | Mixed | - | 0.58 / 0.85 / 0.75 | 0.38 / 0.65 / 0.60 | 0.70 / 0.20 / 0.40 | calm_contentment / joy / joy | 0.540 |
| FV000081 | All disagree | - | 0.58 / 0.75 / 0.30 | 0.45 / 0.60 / 0.70 | 0.60 / 0.00 / 0.20 | joy / joy / surprise | 0.530 |
| FV000662 | All disagree | - | 0.72 / 0.60 / 0.65 | 0.56 / 0.40 / 0.45 | 0.42 / 0.00 / 0.75 | joy / joy / joy | 0.380 |
| FV000895 | All disagree | - | 0.38 / 0.60 / 0.30 | 0.48 / 0.60 / 0.70 | 0.42 / 0.00 / 0.20 | joy / joy / sadness | 0.650 |
| FV001003 | 2 agree + outlier | Gemini | 0.15 / -0.50 / -0.50 | 0.32 / 0.75 / 0.75 | 0.52 / 0.00 / 0.00 | neutral / anger / anger | 0.820 |
| FV000097 | Mixed | - | 0.62 / 0.75 / 0.30 | 0.68 / 0.85 / 0.75 | 0.24 / 0.00 / 0.20 | joy / joy / anger | 0.550 |
| FV000393 | All disagree | - | 0.28 / 0.60 / 0.30 | 0.31 / 0.30 / 0.60 | 0.58 / 0.00 / 0.20 | joy / joy / surprise | 0.520 |
| FV000998 | Mixed | - | 0.74 / 0.85 / 0.85 | 0.38 / 0.65 / 0.75 | 0.78 / 0.30 / 0.60 | joy / joy / joy | 0.460 |
| FV000366 | Mixed | - | 0.72 / 0.85 / 0.65 | 0.48 / 0.45 / 0.40 | 0.58 / 0.75 / 0.70 | joy / joy / joy | 0.150 |
| FV000849 | Mixed | - | 0.52 / 0.30 / -0.30 | 0.64 / 0.60 / 0.75 | 0.28 / 0.00 / 0.20 | joy / joy / disgust | 0.700 |
| FV000983 | All disagree | - | 0.68 / 0.85 / 0.30 | 0.58 / 0.75 / 0.70 | 0.38 / 0.00 / 0.20 | joy / joy / fear_anxiety | 0.720 |
| FV000674 | 2 agree + outlier | Gemini | 0.58 / 0.75 / 0.65 | 0.28 / 0.25 / 0.40 | 0.80 / 0.75 / 0.75 | calm_contentment / joy / joy | 0.560 |
| FV000013 | Mixed | - | 0.30 / 0.60 / 0.30 | 0.38 / 0.40 / 0.60 | 0.68 / 0.00 / 0.40 | neutral / joy / surprise | 0.400 |
| FV000079 | Mixed | - | 0.12 / 0.60 / 0.60 | 0.28 / 0.20 / 0.40 | 0.48 / 0.80 / 0.70 | neutral / neutral / surprise | 0.600 |
| FV000133 | 2 agree + outlier | InternVL | 0.68 / 0.85 / 0.75 | 0.72 / 0.75 / 0.60 | 0.25 / 0.10 / 0.70 | joy / joy / joy | 0.100 |
| FV001015 | All disagree | - | 0.52 / 0.85 / 0.20 | 0.53 / 0.80 / 0.85 | 0.35 / 0.00 / 0.10 | joy / joy / anger | 0.600 |
| FV000033 | All disagree | - | 0.28 / 0.30 / -0.30 | 0.42 / 0.40 / 0.60 | 0.45 / 0.00 / 0.20 | joy / disgust / anger | 0.780 |
| FV000811 | All disagree | - | 0.12 / -0.50 / -0.50 | 0.48 / 0.80 / 0.75 | 0.30 / 0.00 / 0.25 | neutral / fear_anxiety / fear_anxiety | 0.920 |
| FV000120 | Mixed | - | 0.22 / 0.75 / 0.65 | 0.52 / 0.85 / 0.75 | 0.30 / 0.00 / 0.30 | neutral / joy / joy | 0.480 |
| FV000744 | Mixed | - | 0.22 / 0.95 / 0.75 | 0.42 / 0.35 / 0.60 | 0.38 / 0.75 / 0.80 | neutral / joy / joy | 0.570 |
| FV000544 | Mixed | - | 0.42 / 0.30 / 0.30 | 0.36 / 0.40 / 0.50 | 0.70 / 0.00 / 0.20 | calm_contentment / sadness / sadness | 0.750 |
| FV000031 | All disagree | - | 0.22 / 0.00 / 0.30 | 0.20 / 0.00 / 0.40 | 0.72 / 0.00 / 0.70 | neutral / neutral / surprise | 0.900 |
| FV000320 | Mixed | - | -0.38 / -0.50 / -0.50 | 0.62 / 0.75 / 0.75 | 0.15 / 0.00 / 0.25 | surprise / anger / anger | 0.670 |
| FV000241 | All disagree | - | 0.15 / 0.30 / -0.20 | 0.26 / 0.20 / 0.30 | 0.70 / 0.80 / 0.20 | neutral / neutral / sadness | 0.900 |
| FV000015 | Mixed | - | 0.28 / 0.85 / 0.30 | 0.46 / 0.65 / 0.75 | 0.42 / 0.20 / 0.20 | joy / joy / joy | 0.500 |
| FV000001 | Mixed | - | 0.25 / 0.60 / 0.30 | 0.18 / 0.30 / 0.40 | 0.78 / 0.70 / 0.70 | calm_contentment / joy / calm_contentment | 0.730 |

## Provenance and interpretation limits

Gemini is the saved historical v1.0 deployment with direct audio access; Qwen and InternVL are v1.1-points10 CUDA runs with shared transcript/acoustic/caption context and no direct raw audio. Qwen caps at 32 uniformly sampled frames and InternVL at 16, with different vision processors. Therefore this compares saved deployments, not models under identical native modality access and sampling.

- Gemini vs Qwen: context hashes match 50/50; prompt hashes match 0/50.
- Gemini vs InternVL: context hashes match 50/50; prompt hashes match 0/50.
- Qwen vs InternVL: context hashes match 50/50; prompt hashes match 50/50.

Analysis-only normalization counts: Gemini: 0, Qwen: 0, InternVL: 0. File hashes and original near-unit totals are preserved in `comparison.json`.

No model is selected or ranked as best. Human validation has deliberately not been used.

## Reproduce and exports

Run `.venv-qwen-cuda/Scripts/python.exe src/compare_pilot_models.py` from the project root. Source files and their hashes are recorded in the JSON.

- [Per-video disagreement CSV](pilot_50_reels_30h/results/three_model_comparison/per_video_disagreement.csv)
- [Pairwise scalar metrics CSV](pilot_50_reels_30h/results/three_model_comparison/pairwise_scalar_metrics.csv)
- [Complete comparison JSON](pilot_50_reels_30h/results/three_model_comparison/comparison.json)
