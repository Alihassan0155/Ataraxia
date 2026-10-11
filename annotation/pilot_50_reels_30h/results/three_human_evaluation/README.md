# Active three-human pilot evaluation

This is the only active human-reference evaluation. The superseded two-human outputs were deleted; reusable historical scripts and original predictions remain preserved. Do not run historical two-human scripts to recreate an active reference.

The saved Ali file now contains 50 rows. Ghayas and Zara each omit FV000131; Ghayas also contains unexpected FV000037, which has not been remapped. Ali has 31 null dominant labels and two unrecognized labels (`neutal`, `calm`). His emotion totals are 9 for FV000131 and 11 for FV000151/FV000363. Original values remain unchanged.

Evaluation coverage is 49 three-human references per scalar, 47 distributions, and 16 complete validated sets of declared dominant labels. Invalid/missing fields do not discard valid fields. No two-rater fallback, invented labels or adjudication is used. Complete joint rankings and calibration use the same 47 videos; separate scalar nested calibration uses all 49 eligible scalar references.

- [Human agreement, validation and raw model evaluation](reference/human_soft_reference_report.md)
- [Bias, nested calibration and model selection](calibration_final/final_calibration_report.md)
- [Selected models and calibration parameters](calibration_final/selected_final_models.json)
- [Candidate deployment configuration](calibration_final/frozen_annotation_config.json)
- [Exact deleted/created file ledger](migration_report.md)

Raw and nested-calibrated ranking: Gemini, InternVL, Qwen. The conservative retained-policy ranking is InternVL, Gemini, Qwen because unstable or insufficiently consistent corrections are not retained. Both select **Gemini + InternVL**. These are descriptive pilot recommendations; model/prompt/modality differences and incomplete human labels prevent a definitive full-pilot capability claim.

The selected configuration is not ready for an immutable production freeze: historical checkpoint/provider revisions and Gemini sampling/generation settings are incomplete. No full-dataset annotation was started. Missing/invalid human fields should be completed before claiming a finalized 50-video evaluation, and the selected deployment needs fresh held-out validation.

Reproduce from the project root (choose new output directories to preserve an existing three-human run):

```powershell
.\.venv-qwen-cuda\Scripts\python.exe src/build_three_human_reference.py
.\.venv-qwen-cuda\Scripts\python.exe src/analyze_three_human_calibration.py
```

Defaults point to `reference/` and `calibration_final/` here. Existing output directories are rejected. For an independent rerun, give the reference builder a fresh `--output-dir`, then pass that directory to the calibration script with `--reference-dir` and a fresh calibration `--output-dir`. No API inference occurs.
