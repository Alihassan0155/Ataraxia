# Three-human pilot bias, nested calibration and model selection

47 aligned complete three-human numeric/distribution references are used for shared nested calibration and rankings. Raw scalar evaluation AND separate nested scalar calibration retain every valid three-human scalar field (scalar_calibration_all_valid_fields.csv and its per-video predictions). Missing/invalid distributions exclude only the joint-ranking subset. No two-human fallback is used. All original humans/models remain unchanged. No full-dataset annotation starts. Soft labels represent three perceptions, not objective truth. See the reference report for validation issues; no ID replacements are guessed.

## Evaluation protocol

Shared outer 5-fold CV, seed 20261007, stratified on the existing low/medium/high human-uncertainty bins ({'low': 19, 'high': 15, 'medium': 13}). Each outer training set uses 4 inner folds to select a method without seeing outer targets. All models use the same folds. No in-sample fit performance is offered as evidence. Exact train/test IDs and per-fold fits are exported.

Scalar candidates: raw; ordinary least-squares slope/intercept; increasing isotonic regression using weighted PAVA, equal-x groups and linear interpolation between fitted knots. Predictions clip to original bounds. Emotion correction fixes every slope at 1, adds training-only mean human-minus-model offsets, clips to [0,1], and renormalizes. No temperature fitting or complex emotion calibrator is used.

Inner selection requires >=5% relative and >=0.01 full-range absolute MAE gain with >=3/4 inner-fold wins. Isotonic is eligible only with >=8 unique input levels in every inner-training set; near-equal results favor linear. Emotion correction requires TV improvement >=0.01 and >=5%, lower JSD, and >=3/4 fold wins. These conservative rules were set before running this analysis.

Retention for deployment additionally requires material nested OOF gain, >=4/5 outer-fold wins, same method in >=4/5 outer selections, and no high-bin deterioration exceeding 0.01 full range (TV for emotions). A conservative post-OOF sensitivity screen requires isotonic to recur in >=80% of the 20 outer folds across four seeds; otherwise keep raw rather than cherry-pick another method after seeing held-out errors. Full-pilot coefficients are exported only for application, not evaluated in-sample. Individual candidate method OOF results and the inner-selected nested policy are separate. The retained-policy row is post-OOF exploratory selection, not a new independent performance estimate.

## Raw scalar bias

| Model | Field | Signed bias | MAE | RMSE | Pearson | Spearman |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Gemini | valence | 0.203 | 0.247 | 0.285 | 0.644 | 0.660 |
| Gemini | arousal | -0.027 | 0.087 | 0.103 | 0.731 | 0.702 |
| Gemini | recovery_suitability | 0.023 | 0.145 | 0.167 | 0.609 | 0.640 |
| Qwen | valence | 0.325 | 0.411 | 0.479 | 0.573 | 0.414 |
| Qwen | arousal | 0.034 | 0.183 | 0.235 | 0.411 | 0.423 |
| Qwen | recovery_suitability | -0.293 | 0.381 | 0.413 | 0.323 | 0.309 |
| InternVL | valence | 0.133 | 0.318 | 0.376 | 0.561 | 0.480 |
| InternVL | arousal | 0.182 | 0.208 | 0.242 | 0.289 | 0.246 |
| InternVL | recovery_suitability | -0.082 | 0.218 | 0.247 | 0.489 | 0.426 |

Signed bias is model minus pooled human: positive means overprediction, negative underprediction. Valence is [-1,1]; arousal/recovery [0,1]. Mean predictions, human means and all eight emotion biases are in model_bias_analysis.csv.

## Nested OOF scalar performance

| Model | Field | Raw MAE | Nested MAE | Raw bias | Nested bias | Fold wins | Selected outer methods | Retained deployment method |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Gemini | valence | 0.247 | 0.115 | 0.203 | -0.003 | 5/5 | ['linear', 'isotonic', 'isotonic', 'isotonic', 'isotonic'] | raw |
| Gemini | arousal | 0.087 | 0.081 | -0.027 | -0.006 | 2/5 | ['linear', 'linear', 'raw', 'linear', 'linear'] | raw |
| Gemini | recovery_suitability | 0.145 | 0.081 | 0.023 | 0.000 | 5/5 | ['linear', 'linear', 'linear', 'linear', 'linear'] | linear |
| Qwen | valence | 0.411 | 0.137 | 0.325 | -0.001 | 5/5 | ['linear', 'linear', 'linear', 'linear', 'linear'] | linear |
| Qwen | arousal | 0.183 | 0.087 | 0.034 | 0.006 | 5/5 | ['linear', 'linear', 'isotonic', 'isotonic', 'isotonic'] | raw |
| Qwen | recovery_suitability | 0.381 | 0.108 | -0.293 | 0.002 | 5/5 | ['linear', 'linear', 'linear', 'linear', 'linear'] | linear |
| InternVL | valence | 0.318 | 0.137 | 0.133 | -0.000 | 5/5 | ['linear', 'linear', 'linear', 'linear', 'linear'] | linear |
| InternVL | arousal | 0.208 | 0.095 | 0.182 | 0.000 | 5/5 | ['linear', 'linear', 'linear', 'linear', 'linear'] | linear |
| InternVL | recovery_suitability | 0.218 | 0.103 | -0.082 | 0.002 | 5/5 | ['linear', 'linear', 'linear', 'linear', 'linear'] | linear |

Candidate linear/isotonic OOF MAE, RMSE, Pearson, Spearman, signed bias and fold variability for every field/bin are in scalar_calibration_cv.csv. The nested policy can use raw in a fold. Method variability/low distinct-score counts are instability signals; isotonic is not forced.

## OOF emotion calibration

| Model | Method | TV | JSD | Fold wins |
| --- | --- | ---: | ---: | ---: |
| Gemini | raw | 0.279 | 0.112 | 0/5 |
| Gemini | offset | 0.261 | 0.112 | 4/5 |
| Gemini | nested_policy | 0.281 | 0.123 | 1/5 |
| Qwen | raw | 0.484 | 0.314 | 0/5 |
| Qwen | offset | 0.400 | 0.237 | 5/5 |
| Qwen | nested_policy | 0.400 | 0.237 | 5/5 |
| InternVL | raw | 0.476 | 0.289 | 0/5 |
| InternVL | offset | 0.392 | 0.205 | 5/5 |
| InternVL | nested_policy | 0.392 | 0.205 | 5/5 |

## Ranking with individual criteria

Primary scalar alignment is the mean of valence MAE/2, arousal MAE, recovery MAE. Ranking averages metric ranks with weights 40% scalar alignment, 25% TV, 15% high-uncertainty scalar-plus-TV error, 10% absolute normalized bias, 10% worst scalar normalized MAE. This prespecified weighting is a descriptive decision aid, not a universal quality score. Individual field errors, JSD and correlations must be read alongside it. Runtime does not enter ranking.

| Variant | Rank | Model | Scalar alignment | TV | High-bin distance | Abs bias | Worst scalar | Weighted rank |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| nested_calibrated | 1 | Gemini | 0.073 | 0.281 | 0.148 | 0.002 | 0.081 | 1.100 |
| nested_calibrated | 2 | InternVL | 0.089 | 0.392 | 0.164 | 0.001 | 0.103 | 2.300 |
| nested_calibrated | 3 | Qwen | 0.088 | 0.400 | 0.174 | 0.003 | 0.108 | 2.600 |
| raw | 1 | Gemini | 0.118 | 0.279 | 0.176 | 0.051 | 0.145 | 1.000 |
| raw | 2 | InternVL | 0.195 | 0.476 | 0.244 | 0.110 | 0.218 | 2.000 |
| raw | 3 | Qwen | 0.257 | 0.484 | 0.324 | 0.163 | 0.381 | 3.000 |
| retained_policy_exploratory | 1 | InternVL | 0.089 | 0.392 | 0.164 | 0.001 | 0.103 | 1.400 |
| retained_policy_exploratory | 2 | Gemini | 0.097 | 0.279 | 0.159 | 0.043 | 0.124 | 1.700 |
| retained_policy_exploratory | 3 | Qwen | 0.120 | 0.400 | 0.191 | 0.012 | 0.183 | 2.900 |

## Low / medium / high uncertainty

| Model | Variant | Bin | Valence MAE | Arousal MAE | Recovery MAE | TV | JSD |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Gemini | raw | low | 0.245 | 0.079 | 0.128 | 0.241 | 0.086 |
| Gemini | raw | medium | 0.238 | 0.095 | 0.144 | 0.288 | 0.123 |
| Gemini | raw | high | 0.258 | 0.090 | 0.168 | 0.319 | 0.136 |
| Gemini | nested_calibrated | low | 0.067 | 0.064 | 0.066 | 0.231 | 0.096 |
| Gemini | nested_calibrated | medium | 0.148 | 0.094 | 0.086 | 0.301 | 0.133 |
| Gemini | nested_calibrated | high | 0.147 | 0.091 | 0.097 | 0.329 | 0.149 |
| Qwen | raw | low | 0.409 | 0.154 | 0.389 | 0.468 | 0.300 |
| Qwen | raw | medium | 0.410 | 0.240 | 0.329 | 0.487 | 0.307 |
| Qwen | raw | high | 0.416 | 0.171 | 0.416 | 0.500 | 0.339 |
| Qwen | nested_calibrated | low | 0.121 | 0.073 | 0.094 | 0.389 | 0.232 |
| Qwen | nested_calibrated | medium | 0.138 | 0.089 | 0.126 | 0.410 | 0.229 |
| Qwen | nested_calibrated | high | 0.156 | 0.104 | 0.110 | 0.406 | 0.249 |
| InternVL | raw | low | 0.316 | 0.229 | 0.242 | 0.461 | 0.282 |
| InternVL | raw | medium | 0.324 | 0.228 | 0.217 | 0.509 | 0.285 |
| InternVL | raw | high | 0.314 | 0.163 | 0.188 | 0.467 | 0.302 |
| InternVL | nested_calibrated | low | 0.108 | 0.098 | 0.086 | 0.396 | 0.211 |
| InternVL | nested_calibrated | medium | 0.168 | 0.085 | 0.133 | 0.392 | 0.191 |
| InternVL | nested_calibrated | high | 0.147 | 0.099 | 0.100 | 0.385 | 0.209 |

## Recommended pair and freeze status

Raw ranking: Gemini > InternVL > Qwen.
Nested calibrated ranking: Gemini > InternVL > Qwen.
Conservative retained-policy ranking (exploratory): InternVL > Gemini > Qwen.
Recommended research pair: InternVL, Gemini.

## Fold sensitivity and ranking uncertainty

Three extra shared nested-CV split seeds were evaluated without choosing a favorable seed. The primary seed and rules stay fixed. See calibration_seed_sensitivity.csv.

| Seed | Nested ranking |
| --- | --- |
| 20261008 | Gemini > InternVL > Qwen |
| 20261009 | Gemini > InternVL > Qwen |
| 20261010 | Gemini > Qwen > InternVL |

| Comparison | Metric | Difference | Fixed-OOF bootstrap interval |
| --- | --- | ---: | --- |
| Qwen - InternVL | scalar_alignment | -0.001 | [-0.007, 0.006] |
| Qwen - InternVL | emotion_tv | 0.009 | [-0.055, 0.072] |
| Qwen - InternVL | scalar_plus_tv_composite | 0.001 | [-0.017, 0.021] |

The bootstrap resamples matched video errors within uncertainty bins; it does not refit calibrators and is not an independent model-selection test. Intervals spanning zero and ranking changes across seeds weaken a decisive second-place claim. Qwen/InternVL tradeoffs should be carried into fresh validation rather than hidden by a weighted score.
Method counts across the four seeds are recorded in selected_final_models.json. Unstable isotonic selections retain raw values; no post-hoc fallback is chosen to rescue a ranking.

- Gemini: valence=raw, arousal=raw, recovery_suitability=linear, emotions=raw.
- Qwen: valence=linear, arousal=raw, recovery_suitability=linear, emotions=offset.
- InternVL: valence=linear, arousal=linear, recovery_suitability=linear, emotions=offset.

## Confirmed bias tendencies

- Qwen recovery_suitability: signed bias -0.293; underpredicts relative to this pooled reference, not objective truth.
- InternVL arousal: signed bias +0.182; overpredicts relative to this pooled reference, not objective truth.
- Gemini recovery_suitability: signed bias +0.023; overpredicts relative to this pooled reference, not objective truth.
- Gemini calm_contentment: signed bias +0.090; overpredicts relative to this pooled reference, not objective truth.

Full-pilot parameters, clipping/renormalization behavior, prompts, evidence usage and known sampling/generation settings are in frozen_annotation_config.json. Calibration is downstream postprocessing; original evidence and labels remain unchanged. Distribution-derived dominant labels must be recomputed downstream if a distribution correction is applied; retain the original declared label alongside it.

Freeze gaps: InternVL: immutable checkpoint/provider version not logged; Gemini: immutable checkpoint/provider version not logged; Gemini: provider video sampling and generation settings not recorded in historical annotations.
The analysis/configuration can be versioned, but the pipeline is not yet an immutable production freeze. Re-running or scaling Gemini may require matching its historical provider configuration. Cached HF commit names alone do not prove which unlogged revision produced the saved annotations.

## Limitations

Model/prompt/native-modality differences remain confounded. The same pilot informs recommendations; there is no independent post-selection holdout. Nested CV protects per-video calibrator evaluation but cannot make selection among models/policies on this pilot unbiased. OOF fold variation is not a statistical confidence interval. With this small three-human pilot, isotonic step maps and final coefficients may be unstable under new content; do not extrapolate to 4,000 videos without a fresh validation check. Distribution correction improves distance to a three-human mixture, not truth.

All outputs are new files under this analysis directory. Reproduce with `.venv-qwen-cuda/Scripts/python.exe src/analyze_three_human_calibration.py --output-dir <new-directory>`. No network inference or full-dataset annotation occurs.

## Concise conclusion

1. Bias directions and magnitudes are computed above from this three-human reference; no previous two-human bias conclusion is carried forward.
2. Nested out-of-fold gains and retained methods are reported per model/field above; raw values remain where correction fails the materiality, fold-consistency or uncertainty screens.
3. Nominal research pair under the stated criteria: InternVL, Gemini. Calibrated second-place separation must be interpreted with fold sensitivity and paired intervals; it is not definitive model superiority.
4. Preserve raw outputs and store calibrated values separately for the retained fields/distributions. Do not replace original annotations or interpret recalibrated confidence as calibrated probability of correctness.
5. Freeze the analysis and candidate calibration specification now; production freeze remains incomplete because of the logged provenance gaps and the need for fresh validation before scaling. No full-dataset annotation has started.
