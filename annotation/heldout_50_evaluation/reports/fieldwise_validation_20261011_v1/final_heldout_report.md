# Held-out evaluation against three-human soft references

This evaluates the untouched 50-video test selection using only frozen development calibration. Original predictions/human files remain unchanged. No fitting, threshold changes or inference occurred. The human reference represents perceptions, not truth.

## Validation and eligible counts

All three models: 50 valid unique predictions, no missing/duplicate/unexpected IDs; frozen checkpoint, evidence, prompt and media checks pass. All humans now have 50 aligned unique IDs. All three scalars: 50 valid three-human references. Emotion distributions: 48/50. Ali declared dominant labels: 0/50. Ghayas/Zara declared labels: 50/50 each.

Ali emotion totals 11 (TT_7440201647755644182) and 14 (YT_WiBhWcqrhF0) remain invalid. All Ali declared dominant labels are blank. Four optional confidence values are absent. Invalid fields alone are excluded; missing categorical labels are not inferred or counted as disagreements. No two-human reference replaces a missing third value. Detailed errors are in input_validation.json. Ghayas ID corrections are backed up and documented.

## Human agreement

Human scalars are on [0,10]. Emotion scores must total 10 and are converted to probabilities. Reference means require three valid values per field. Uncertainty is the mean of three range-normalized mean pairwise scalar differences and mean pairwise emotion TV. Declared-label disagreement is separate. No held-out quantiles set thresholds.

| Pair | Field | N | MAE / TV | Pearson / agreement | Spearman / kappa |
| --- | --- | --- | --- | --- | --- |
| ali_vs_ghayas | valence | 50 | 1.220 | 0.288 | 0.310 |
| ali_vs_ghayas | arousal | 50 | 1.960 | 0.209 | 0.207 |
| ali_vs_ghayas | recovery_suitability | 50 | 1.260 | 0.438 | 0.410 |
| ali_vs_ghayas | dominant_emotion | 0 | unavailable | unavailable | unavailable |
| ali_vs_ghayas | emotion_distribution | 48 | 0.535 | unavailable | unavailable |
| ali_vs_zara | valence | 50 | 1.000 | 0.601 | 0.574 |
| ali_vs_zara | arousal | 50 | 1.840 | 0.351 | 0.316 |
| ali_vs_zara | recovery_suitability | 50 | 1.620 | 0.338 | 0.306 |
| ali_vs_zara | dominant_emotion | 0 | unavailable | unavailable | unavailable |
| ali_vs_zara | emotion_distribution | 48 | 0.500 | unavailable | unavailable |
| ghayas_vs_zara | valence | 50 | 1.180 | 0.321 | 0.290 |
| ghayas_vs_zara | arousal | 50 | 0.880 | 0.556 | 0.513 |
| ghayas_vs_zara | recovery_suitability | 50 | 1.280 | 0.460 | 0.433 |
| ghayas_vs_zara | dominant_emotion | 50 | unavailable | 0.420 | 0.235 |
| ghayas_vs_zara | emotion_distribution | 50 | 0.450 | unavailable | unavailable |

Three-human declared-label agreement/Fleiss kappa: unavailable (N=0). Distribution-derived pooled maxima remain separate and preserve ties.

Frozen uncertainty cutpoints: 0.200000, 0.250000; bins: {'medium': 19, 'low': 18, 'high': 11, None: 2}. Invalid distributions yield unbinned rows while their scalar metrics remain eligible.

## Raw and frozen-calibrated performance

Valence is [-1,1]; arousal/recovery are [0,1]. Scalar N=50; distribution N=48. JSD is base-2 divergence. Signed bias is model minus human.

| Model | Variant | Field | MAE | RMSE | Pearson | Spearman | Bias |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qwen | raw | valence | 0.439 | 0.510 | 0.468 | 0.408 | 0.344 |
| qwen | raw | arousal | 0.164 | 0.213 | 0.442 | 0.432 | 0.005 |
| qwen | raw | recovery_suitability | 0.382 | 0.431 | 0.311 | 0.298 | -0.290 |
| qwen | calibrated | valence | 0.152 | 0.191 | 0.468 | 0.408 | 0.036 |
| qwen | calibrated | arousal | 0.164 | 0.213 | 0.442 | 0.432 | 0.005 |
| qwen | calibrated | recovery_suitability | 0.105 | 0.125 | 0.311 | 0.298 | -0.042 |
| internvl | raw | valence | 0.371 | 0.427 | 0.484 | 0.496 | 0.151 |
| internvl | raw | arousal | 0.204 | 0.228 | 0.600 | 0.515 | 0.201 |
| internvl | raw | recovery_suitability | 0.225 | 0.263 | 0.322 | 0.233 | -0.095 |
| internvl | calibrated | valence | 0.148 | 0.189 | 0.484 | 0.496 | 0.035 |
| internvl | calibrated | arousal | 0.071 | 0.093 | 0.600 | 0.515 | -0.008 |
| internvl | calibrated | recovery_suitability | 0.106 | 0.125 | 0.322 | 0.233 | -0.041 |
| gemini | raw | valence | 0.292 | 0.328 | 0.634 | 0.704 | 0.232 |
| gemini | raw | arousal | 0.081 | 0.102 | 0.734 | 0.730 | -0.034 |
| gemini | raw | recovery_suitability | 0.160 | 0.202 | 0.431 | 0.356 | -0.019 |
| gemini | calibrated | valence | 0.292 | 0.328 | 0.634 | 0.704 | 0.232 |
| gemini | calibrated | arousal | 0.081 | 0.102 | 0.734 | 0.730 | -0.034 |
| gemini | calibrated | recovery_suitability | 0.102 | 0.123 | 0.431 | 0.356 | -0.046 |

| Model | Variant | TV | JSD | Dominant Ali | Dominant Ghayas | Dominant Zara | Pooled dominant |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qwen | raw | 0.564 | 0.372 | unavailable | 0.300 | 0.260 | 0.292 |
| qwen | calibrated | 0.453 | 0.255 | unavailable | 0.280 | 0.240 | 0.312 |
| internvl | raw | 0.465 | 0.269 | unavailable | 0.280 | 0.260 | 0.292 |
| internvl | calibrated | 0.372 | 0.189 | unavailable | 0.340 | 0.340 | 0.438 |
| gemini | raw | 0.298 | 0.129 | unavailable | 0.500 | 0.440 | 0.500 |
| gemini | calibrated | 0.298 | 0.129 | unavailable | 0.500 | 0.440 | 0.500 |

Canonical pooled dominant agreement uses the frozen emotion-key tie rule; tie-aware agreement is also exported. Per-emotion model/human means and biases are in model_bias_analysis.csv.

## Paired bootstrap confidence intervals

5,000 paired video-level percentile resamples, frozen seed 20261009; identical 50-video draws for every model/variant. Metric-specific invalid references are masked within each draw. Degenerate correlations are omitted with valid draw counts. Calibrators remain fixed. CIs exclude refitting, provider repetition, annotator population and model-selection uncertainty. No multiplicity adjustment; interpret intervals descriptively.

| Model | Variant | Metric | Estimate | 95% CI |
| --- | --- | --- | --- | --- |
| qwen | raw | valence_mae | 0.439 | [0.366, 0.511] |
| qwen | raw | arousal_mae | 0.164 | [0.128, 0.203] |
| qwen | raw | recovery_suitability_mae | 0.382 | [0.327, 0.437] |
| qwen | raw | emotion_tv | 0.564 | [0.514, 0.613] |
| qwen | calibrated | valence_mae | 0.152 | [0.122, 0.187] |
| qwen | calibrated | arousal_mae | 0.164 | [0.128, 0.203] |
| qwen | calibrated | recovery_suitability_mae | 0.105 | [0.086, 0.124] |
| qwen | calibrated | emotion_tv | 0.453 | [0.399, 0.508] |
| internvl | raw | valence_mae | 0.371 | [0.314, 0.428] |
| internvl | raw | arousal_mae | 0.204 | [0.176, 0.233] |
| internvl | raw | recovery_suitability_mae | 0.225 | [0.188, 0.263] |
| internvl | raw | emotion_tv | 0.465 | [0.418, 0.511] |
| internvl | calibrated | valence_mae | 0.148 | [0.117, 0.183] |
| internvl | calibrated | arousal_mae | 0.071 | [0.055, 0.088] |
| internvl | calibrated | recovery_suitability_mae | 0.106 | [0.088, 0.125] |
| internvl | calibrated | emotion_tv | 0.372 | [0.334, 0.410] |
| gemini | raw | valence_mae | 0.292 | [0.252, 0.334] |
| gemini | raw | arousal_mae | 0.081 | [0.065, 0.100] |
| gemini | raw | recovery_suitability_mae | 0.160 | [0.127, 0.194] |
| gemini | raw | emotion_tv | 0.298 | [0.259, 0.339] |
| gemini | calibrated | valence_mae | 0.292 | [0.252, 0.334] |
| gemini | calibrated | arousal_mae | 0.081 | [0.065, 0.100] |
| gemini | calibrated | recovery_suitability_mae | 0.102 | [0.082, 0.122] |
| gemini | calibrated | emotion_tv | 0.298 | [0.259, 0.339] |

Calibrated minus raw: negative error differences favor calibration. Intervals containing zero do not establish improvement or equivalence.

| Model | Metric | Calibrated − raw | 95% CI | Includes zero |
| --- | --- | --- | --- | --- |
| qwen | valence_mae | -0.286 | [-0.355, -0.214] | False |
| qwen | arousal_mae | 0.000 | [0.000, 0.000] | True |
| qwen | recovery_suitability_mae | -0.278 | [-0.333, -0.219] | False |
| qwen | emotion_tv | -0.111 | [-0.129, -0.090] | False |
| qwen | emotion_jsd | -0.116 | [-0.139, -0.091] | False |
| qwen | scalar_plus_tv_composite | -0.132 | [-0.148, -0.115] | False |
| internvl | valence_mae | -0.223 | [-0.278, -0.163] | False |
| internvl | arousal_mae | -0.133 | [-0.168, -0.098] | False |
| internvl | recovery_suitability_mae | -0.119 | [-0.155, -0.081] | False |
| internvl | emotion_tv | -0.093 | [-0.119, -0.065] | False |
| internvl | emotion_jsd | -0.080 | [-0.104, -0.056] | False |
| internvl | scalar_plus_tv_composite | -0.113 | [-0.132, -0.093] | False |
| gemini | valence_mae | 0.000 | [0.000, 0.000] | True |
| gemini | arousal_mae | 0.000 | [0.000, 0.000] | True |
| gemini | recovery_suitability_mae | -0.058 | [-0.087, -0.027] | False |
| gemini | emotion_tv | 0.000 | [-0.000, 0.000] | True |
| gemini | emotion_jsd | 0.000 | [-0.000, 0.000] | True |
| gemini | scalar_plus_tv_composite | -0.014 | [-0.022, -0.007] | False |

## Human uncertainty strata

| Model | Variant | Bin | N | Valence MAE | Arousal MAE | Recovery MAE | TV | JSD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qwen | raw | low | 18 | 0.485 | 0.134 | 0.304 | 0.519 | 0.320 |
| qwen | raw | medium | 19 | 0.378 | 0.199 | 0.411 | 0.616 | 0.424 |
| qwen | raw | high | 11 | 0.523 | 0.136 | 0.433 | 0.548 | 0.367 |
| qwen | calibrated | low | 18 | 0.188 | 0.134 | 0.106 | 0.413 | 0.225 |
| qwen | calibrated | medium | 19 | 0.131 | 0.199 | 0.110 | 0.517 | 0.308 |
| qwen | calibrated | high | 11 | 0.142 | 0.136 | 0.100 | 0.406 | 0.215 |
| internvl | raw | low | 18 | 0.407 | 0.190 | 0.194 | 0.428 | 0.236 |
| internvl | raw | medium | 19 | 0.306 | 0.220 | 0.227 | 0.521 | 0.312 |
| internvl | raw | high | 11 | 0.442 | 0.195 | 0.258 | 0.429 | 0.248 |
| internvl | calibrated | low | 18 | 0.195 | 0.095 | 0.105 | 0.366 | 0.184 |
| internvl | calibrated | medium | 19 | 0.110 | 0.070 | 0.110 | 0.399 | 0.209 |
| internvl | calibrated | high | 11 | 0.146 | 0.042 | 0.105 | 0.335 | 0.165 |
| gemini | raw | low | 18 | 0.317 | 0.064 | 0.133 | 0.268 | 0.104 |
| gemini | raw | medium | 19 | 0.284 | 0.079 | 0.151 | 0.319 | 0.143 |
| gemini | raw | high | 11 | 0.258 | 0.104 | 0.222 | 0.308 | 0.145 |
| gemini | calibrated | low | 18 | 0.317 | 0.064 | 0.105 | 0.268 | 0.104 |
| gemini | calibrated | medium | 19 | 0.284 | 0.079 | 0.092 | 0.319 | 0.143 |
| gemini | calibrated | high | 11 | 0.258 | 0.104 | 0.119 | 0.308 | 0.145 |

## Frozen quality ranking and pair recommendation

Joint ranking N=48 complete numeric/distribution references. Weights remain 40% scalar alignment, 25% TV, 15% high-uncertainty error, 10% absolute normalized bias, 10% worst normalized scalar MAE. Runtime is separate. No criterion was selected after viewing held-out errors.

| Variant | Rank | Model | Scalar alignment | TV | High-bin error | Abs bias | Worst scalar | Weighted rank |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| calibrated | 1 | internvl | 0.085 | 0.372 | 0.139 | 0.023 | 0.107 | 1.250 |
| calibrated | 2 | gemini | 0.109 | 0.298 | 0.165 | 0.065 | 0.145 | 1.850 |
| calibrated | 3 | qwen | 0.115 | 0.453 | 0.178 | 0.026 | 0.160 | 2.900 |
| raw | 1 | gemini | 0.128 | 0.298 | 0.191 | 0.057 | 0.160 | 1.000 |
| raw | 2 | internvl | 0.204 | 0.465 | 0.276 | 0.124 | 0.222 | 2.000 |
| raw | 3 | qwen | 0.254 | 0.564 | 0.345 | 0.158 | 0.376 | 3.000 |

Paired calibrated model differences in shared scalar-plus-TV error (positive means first model is worse); this error metric is distinct from weighted metric rank.

| Comparison | Difference | 95% CI | Inconclusive |
| --- | --- | --- | --- |
| qwen − internvl | 0.043 | [0.025, 0.061] | False |
| qwen − gemini | 0.043 | [0.021, 0.066] | False |
| internvl − gemini | 0.001 | [-0.020, 0.022] | True |

Raw order: gemini > internvl > qwen.
Frozen-calibrated order: internvl > gemini > qwen.
**Nominal recommended pair: internvl, gemini.** This is qualified by incomplete human fields, metric-specific intervals and the frozen deployment/provenance limitations. A weighted rank alone is not evidence of superiority; a zero-crossing difference is inconclusive, not equivalence. Final completeness requires Ali corrections. Do not tune calibration using this test.

## Runtime

| Model | Timed videos | Sum hours | Median seconds | Normalized records |
| --- | --- | --- | --- | --- |
| qwen | 50 | 4.318 | 85.659 | 0 |
| internvl | 50 | 9.756 | 478.666 | 0 |
| gemini | 50 | 0.918 | 39.623 | 0 |

Saved successful inference times exclude loading and may exclude failed attempts/key retries; these are not total wall-clock costs.

## Deviations and readiness

- qwen: historical pilot immutable revision was not logged; prospective held-out revision is pinned to the current cache
- internvl: historical pilot immutable revision was not logged; prospective held-out revision is pinned to the current cache
- Gemini: historical provider revision and video sampling/generation defaults unlogged; matching the historical deployment cannot be proven
- Shared context does not mean identical direct modality access: Gemini hears raw audio, CUDA models do not
- No ID or exact-byte overlap; creator/repost/near-duplicate leakage is not certified by byte hashing
- Field-specific exclusions for invalid human labels; no two-human fallback.
- Joint ranking uses complete three-human scalar/distribution subset, matching development convention.
- Ghayas nine IDs corrected with user authorization; original backup and correction mapping retained.
- Reliability amendments v2/v3/v4 changed timeout/key-failover and InternVL repair policy after failures.

Reliability amendment files v2/v3/v4 are preserved. InternVL normalization events retain original model scores; human invalid totals have not been normalized. Human independence is user-confirmed; blindness to model outputs is unverified. The balanced category/source selection is not a random sample proportional to the full dataset, so estimates should not be presented as full-population performance.

**Not ready for an unconditional full-dataset release:** finish human corrections, resolve provider provenance gaps and version the deployment/application policy. The frozen calibration has been independently tested on all valid held-out fields. No full-dataset annotation started.

## Reproduce

```powershell
.\.venv-qwen-cuda\Scripts\python.exe heldout_50_evaluation/scripts/evaluate_valid_fields.py --output-dir heldout_50_evaluation/reports/<new-folder>
```

All source hashes, frozen parameters and complete metric tables are preserved in this folder. Choose a new output folder for any rerun; previous results stay unchanged.
