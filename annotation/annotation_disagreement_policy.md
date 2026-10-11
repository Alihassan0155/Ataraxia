# Ataraxia: Gemini–Qwen disagreement policy

Policy version: `v0.1-provisional`  
Created: 2026-09-25  
Scope: annotation policy specification; no runtime enforcement is implemented by this document.

## Definition

High disagreement means that two valid, comparable annotations differ beyond at least one of the limits below. Low disagreement means that every comparison passes. A close match on one field cannot compensate for a large mismatch on another.

These are proposed starting thresholds for Ataraxia, not established research standards or thresholds validated on this dataset. Low disagreement is a candidate acceptance rule; human evaluation and random audits are needed to establish how reliable the resulting silver labels are.

## Comparison thresholds

Let `G` denote Gemini's prediction and `Q` denote Qwen's prediction for the same video.

| Field | Difference calculation | Low disagreement | High disagreement |
|---|---|---|---|
| Valence, range −1 to +1 | `abs(G.valence - Q.valence)` | ≤ 0.20 | > 0.20 |
| Arousal, range 0 to 1 | `abs(G.arousal - Q.arousal)` | ≤ 0.15 | > 0.15 |
| Recovery suitability, range 0 to 1 | `abs(G.recovery_suitability - Q.recovery_suitability)` | ≤ 0.15 | > 0.15 |
| Eight-emotion distribution | Total variation distance, defined below | ≤ 0.20 | > 0.20 |
| Dominant emotion | Compare the sets of highest-scoring emotions | At least one shared maximum | No shared maximum |

The scalar limits permit differences of 10% of the full valence scale and 15% of the arousal/recovery scales. These percentages explain the proposed settings; they do not demonstrate validity. Recovery is checked independently because it is not simply inverse arousal.

For numeric comparisons, values exactly at the limit pass. Use an absolute numerical tolerance of `1e-9` to prevent floating-point artifacts from changing boundary decisions; do not round differences before comparison.

### Emotion distribution difference

Use the same eight keys in both vectors: `joy`, `sadness`, `anger`, `fear_anxiety`, `surprise`, `disgust`, `calm_contentment`, and `neutral`.

```text
TVD = 0.5 × sum(abs(G.emotions[e] - Q.emotions[e]) for each emotion e)
```

TVD ranges from 0 (identical distributions) to 1 (no overlapping probability mass). A limit of 0.20 permits at most 20 percentage points of redistributed probability mass across the distribution; it is not a 20% error probability.

Before calculating TVD, validate each distribution as described below, then divide its entries by its sum to correct permissible rounding drift. This policy uses TVD, not Jensen–Shannon distance; their thresholds are not interchangeable.

### Dominant emotion and ties

Recompute the highest-scoring emotions from each distribution. Treat scores within `1e-9` of the maximum as tied. If the two maximum sets intersect, the dominant-emotion check passes, even if the models selected different members of an exact tie. Otherwise it fails.

Near-ties that are not exact ties still fail if the leading emotions differ. This is deliberately conservative and may exclude similar mixed-emotion videos. Any later relaxation must be evaluated on development data and recorded as a policy change.

## Validity and evidence checks come first

Only calculate disagreement after confirming:

- Both predictions exist and refer to the same video, rubric version, and shared context version. Record video/context hashes and model versions for reproducibility.
- Both models were run independently, without seeing the other model's answer, using the identical shared evidence block required by `AGENTS.md`.
- Numeric values are finite and within their permitted ranges; all eight emotion scores are present and each lies in [0, 1]. Each distribution must sum to between 0.99 and 1.01 inclusive, allowing `1e-9` numerical tolerance. Larger errors are invalid and must not be silently normalized away.
- Each reported dominant emotion belongs to that model's maximum set.
- The video/temporal input was successfully supplied, required evidence fields are present, and missing modalities are represented honestly. An empty transcript due to genuine silence is different from failed transcription. Likewise, a genuinely absent caption is not a pipeline failure.
- Gemini's direct raw-audio access and Qwen's use of transcript/acoustic evidence are recorded. That expected capability difference is not itself disagreement. A missing shared context, failed extraction, or known unsupported modality claim prevents acceptance.

Distinguish `uncertain_invalid_output` and `uncertain_incomparable_inputs` from `uncertain_high_disagreement`. They all enter the uncertain pool but represent different problems. In particular, a missing model result does not establish disagreement.

Schema checks and provenance cannot automatically prove that free-text evidence is truthful or complete. Preserve evidence for audits; any known material evidence contradiction puts the item on hold as `uncertain_evidence`.

## Routing decision

```text
Invalid output, incomparable inputs, or known material evidence problem
    → Uncertain pool, with the corresponding reason
Otherwise, any disagreement threshold fails
    → uncertain_high_disagreement
Otherwise
    → silver_agreement under this policy version
```

For high disagreement, record every failing check: `valence_gap`, `arousal_gap`, `recovery_gap`, `emotion_distribution_gap`, and/or `dominant_emotion_mismatch`. Preserve the differences and both original annotations. Do not average high-disagreement predictions into a usable recommendation label.

Uncertain items are initially excluded from the recommendation experiment; they are not deleted and do not require immediate human annotation. A bounded retry can address technical failures. Do not keep regenerating valid predictions until they happen to agree.

## Constructing accepted silver labels

- Average Gemini and Qwen equally for valence, arousal, and recovery suitability.
- Average their normalized emotion distributions element by element; retain calculation precision so the result sums to 1. Round for display only.
- Derive the dominant emotion from the averaged distribution. Preserve every tied maximum as `co_dominant_emotions`; if a consumer requires a single string, use the first tied emotion in the fixed eight-key order above and record that this was a tie.
- Preserve each model's evidence and confidence separately. Do not average confidence into a purported probability of correctness or use it to weight labels.
- Save the policy version, provenance, routing reasons, individual differences, and final label status alongside the original annotations.

Model confidence is not part of the initial acceptance thresholds. High confidence cannot override a failed check. Low inter-model disagreement also does not mean the clip has a single clear emotion or that the annotation is correct.

## Worked examples

Unless otherwise stated, all other checks pass. Emotion examples show nonzero entries only; the remaining required keys have value zero.

| Example | Calculation | Result |
|---|---|---|
| Valence 0.30 vs 0.10 | Difference = 0.20 | This check passes at the boundary |
| Valence −0.40 vs 0.20 | Difference = 0.60 | High disagreement |
| Arousal 0.35 vs 0.65 | Difference = 0.30 | High disagreement |
| Recovery 0.70 vs 0.45 | Difference = 0.25 | High disagreement |
| G: joy 0.90, neutral 0.10; Q: joy 0.60, neutral 0.40 | TVD = 0.30, both leaders joy | High disagreement despite the same dominant emotion |
| G: joy 0.45, calm_contentment 0.40, neutral 0.15; Q: joy 0.40, calm_contentment 0.45, neutral 0.15 | TVD = 0.05, leaders differ | High disagreement due to dominant-emotion mismatch |
| G: V=0.30, A=0.40, R=0.60; Q: V=0.20, A=0.50, R=0.50; both emotion distributions joy 0.60, neutral 0.40 | Scalar gaps = 0.10 each; TVD = 0; same leader | Silver: V=0.25, A=0.45, R=0.55, unchanged distribution |

## Minimal human validation

Use the previously proposed budget: 25 development videos, 25 held-out evaluation videos, and 25 additional randomly sampled accepted videos for audit, with two independent raters per video. Split the pilot before tuning. Keep raters blind to model predictions.

Tune thresholds only on development data; freeze the prompt, policy, and model versions before held-out evaluation. Report acceptance coverage together with errors against human labels, human–human agreement, uncertainty intervals, and exclusion rates by category/language. A small held-out set gives preliminary estimates, not strong subgroup guarantees or calibrated confidence probabilities.

If humans only provide dominant/secondary emotions rather than full distributions, explicitly report that the eight-emotion distribution is not directly human-validated. The TVD threshold then measures inter-model consistency only.

Audit failures may require further data or a revised policy and fresh evaluation. Do not loosen thresholds merely to fill dataset quotas. Exclusions may bias the usable dataset toward easier content; report the retained and excluded composition. New language or cultural groups require additional validation before carrying over reliability claims.

## Methodological basis

Abstention trades coverage against prediction error; it does not establish the quality of Ataraxia's thresholds without evaluation. See [Selective Classification via One-Sided Prediction](https://proceedings.mlr.press/v130/gangrade21a.html).

Blind human reference labeling reduces the risk of model suggestions influencing evaluation labels. See [Just Put a Human in the Loop? Investigating LLM-Assisted Annotation for Subjective Tasks](https://aclanthology.org/2025.findings-acl.1323/).

Neither source establishes the numerical limits in this document. These values are Ataraxia design proposals that require pilot validation.
