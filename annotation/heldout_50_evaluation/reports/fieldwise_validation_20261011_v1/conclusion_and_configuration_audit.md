# Held-out conclusion and configuration audit

This conclusion is qualified: 50 valid three-human scalar references, 48 valid three-human distributions, and no valid Ali declared dominant labels. No invalid human scores or missing labels have been filled. It is not a complete 50-video categorical/distribution validation.

Raw ranking: gemini > internvl > qwen.
Frozen-calibrated ranking: internvl > gemini > qwen.
**Recommended research pair: InternVL + Gemini.** The pair is unchanged from development; the weighted ranking orders InternVL first. The ranking does not establish an unqualified overall superiority over Gemini.

## Calibration generalization

Frozen pilot calibration reduced Qwen valence/recovery MAE and distribution TV; InternVL all three scalar MAEs and distribution TV; and Gemini recovery MAE. Their paired 95% error-difference intervals exclude zero in the improving direction on the eligible held-out fields. Qwen arousal and Gemini valence/arousal/emotions retain raw methods and are unchanged. No method was refitted or chosen using held-out labels.

Use the already frozen per-field calibration and preserve raw values separately. These results validate alignment to three human perceptions; they do not establish calibrated probabilities of correctness.

## Pairwise uncertainty

- qwen − internvl: 0.0425, 95% CI [0.0251, 0.0611]; zero-crossing/inconclusive: False.
- qwen − gemini: 0.0432, 95% CI [0.0212, 0.0663]; zero-crossing/inconclusive: False.
- internvl − gemini: 0.0007, 95% CI [-0.0200, 0.0221]; zero-crossing/inconclusive: True.

InternVL has lower calibrated valence MAE than Gemini; Gemini has lower distribution TV/JSD. Their arousal and recovery MAE differences are inconclusive. Qwen vs InternVL valence/recovery differences are inconclusive, but Qwen has higher arousal error and distribution TV. Refer to all metric intervals, rather than reading a single weighted rank as a significance test.

## Runtime and provenance

Summed saved successful inference times: Gemini 0.92 h; Qwen 4.32 h; InternVL 9.76 h. These omit loading and may omit failed attempts/retries. Runtime is secondary to quality and does not enter the frozen ranking.

Configuration metadata checks are exported in recorded_configuration_audit.json. Missing per-video fields cannot be inferred from the current config file. Amended repair/timeouts/key rotation and historical Gemini default/provider revision gaps remain disclosed. No prompt, calibration, threshold or ranking weight was altered.

## Readiness

The nominal pair is supported by the available held-out evidence, but the pipeline is not ready for an unconditional full-dataset freeze: finish Ali human-field corrections, resolve/document provider reproducibility gaps, and version the deployment policy. Do not tune on these test labels. No full-dataset annotation was started.

[Detailed metrics, human agreement and confidence intervals](final_heldout_report.md).

Reproduce this addendum:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe heldout_50_evaluation/scripts/summarize_valid_field_evaluation.py
```
