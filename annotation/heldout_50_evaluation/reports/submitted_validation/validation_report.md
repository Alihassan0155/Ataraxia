# Submitted held-out annotation validation

Status: blocked_by_annotation_validation. Exactly 50 frozen IDs with zero original-pilot ID overlap.

All original source files and frozen components remain unchanged. No IDs are guessed, human totals repaired, or missing dominant labels inferred. No calibration is fitted.

## Human coverage

| Annotator | Rows | Missing IDs | Unexpected IDs | Duplicate/malformed ID issues | Invalid affect fields |
| --- | ---: | ---: | ---: | ---: | ---: |
| ali | 50 | 0 | 0 | 0 | 52 |
| ghayas | 50 | 0 | 0 | 0 | 0 |
| zara | 50 | 0 | 0 | 0 | 0 |

Detailed ID lists and all field errors are in input_validation.json and invalid_human_fields.csv. Optional blank confidence scores are reported separately and do not block affect evaluation.

Valid three-human scalar counts: {'valence': 50, 'arousal': 50, 'recovery_suitability': 50}. Valid distributions: 48/50. Valid three-human declared dominant labels: 0/50.

## Models

- qwen: 50/50 validated predictions; missing=[], unexpected=[], duplicates={}, error=None.
- internvl: 50/50 validated predictions; missing=[], unexpected=[], duplicates={}, error=None.
- gemini: 50/50 validated predictions; missing=[], unexpected=[], duplicates={}, error=None.

## Final evaluation gate

Complete final ranking, calibration comparison, confidence intervals and model-pair selection wait for complete valid human annotations. Available pairwise human agreement and partial references are labeled as incomplete. No final ranking is claimed.

Rerun `..\..\.venv-qwen-cuda\Scripts\python.exe scripts\evaluate_submitted.py` from heldout_50_evaluation, or use the root command below:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe heldout_50_evaluation/scripts/evaluate_submitted.py
```
