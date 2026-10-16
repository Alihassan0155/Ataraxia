# Bounded summary repair

The semantic-v8 configuration permits one summary-only model repair when the
existing field-passage selector retracts semantic_summary. The model receives
the exact source-passage catalog and returns only semantic_summary and passage_id.
No other content field can be changed by this patch. Unknown passages, empty
summaries and extra fields are rejected. All original schema and semantic checks
then run on the complete response. Quote maxLength remains 250.

Changes: evidence.py, models.py, worker.py, config.py, pipeline.json and
tests/test_evidence.py. The new policy and source code are frozen per run;
old runs and successful annotations remain unchanged. Source quotation checks
do not constitute an independent semantic-entailment judgment.

Validation: 29 unit tests passed. A live cached-draft retry of FV000002 only
completed successfully in semantic_summary_fix_v1: schema/semantic validation
passed and BGE-M3 embedding completed, exit code 0. No remaining validation
error for that video. No model downloads, full-dataset run or affect inference
were executed. Raw summary repair output and selected passage are preserved in
the run alongside its frozen configuration and final record.

Final machine-readable status:
../runs/semantic_summary_fix_v1/reports/targeted_retry.json
