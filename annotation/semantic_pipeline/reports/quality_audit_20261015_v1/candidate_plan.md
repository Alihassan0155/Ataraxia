# Semantic extraction candidate and retrieval review

The active semantic_full_v8_r2 configuration, source package, template, taxonomy,
models and results are unchanged. The candidate uses the existing adapters and
strict validators. No inference or download was run for this audit.

## Implemented candidate

`configs/pipeline_v9_candidate.json` uses a separately versioned v4 candidate
prompt: compact JSON, concise content, short source quotes and minimal sufficient
evidence rather than transcript paragraphs. It explicitly distinguishes speech
summary from visual narrative and discourages category claims supported only by
metadata. It does not promise entailment validation.

The output allowance increases from 2048 to 4096 tokens to address truncated JSON;
extractor batch size decreases from two to one to reduce memory pressure. The
checkpoint, NF4 quantization, seed, greedy generation, source transcript budget,
taxonomy, schema, embedding template and embedding model are unchanged. The
250-character quote limit and all existing semantic checks remain enforced.
Missing optional fields remain missing when unsupported. Do not interpret higher
field coverage alone as better quality. Repair-selection behavior is unchanged;
incomplete selector decisions may still fail. The candidate has NOT been shown
to improve extraction, latency or GPU memory use in live inference.

## Safe six-video trial

`configs/pipeline_v9_canary6.json` references an immutable copied Gemini snapshot
containing ONLY FV000002, FV000005, FV000006, FV000016, FV000032 and FV000057.
These include prior successes and failures for a development sensitivity check,
not an independent held-out evaluation. This deliberately reprocesses only six
videos into a separate run; it does not overwrite or reuse incompatible records.
The input Gemini predictions were copied verbatim as parsed JSON; originals remain
untouched. The full metadata manifest is retained for evidence lookup; only the
six Gemini IDs can enter this trial queue.

After gracefully stopping the active worker and waiting for its `stopped` event,
run from the annotation directory:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py stop --run semantic_full_v8_r2
# Wait for the existing terminal to report stopped; then:
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py run --config .\semantic_pipeline\configs\pipeline_v9_canary6.json --run semantic_v9_canary6 --once
```

The once command drains currently eligible jobs. Failures in backoff may remain;
inspect status instead of assuming all six passed. Do not run the all-source
candidate on the full dataset until this trial is reviewed. Existing runs cannot
silently adopt these prompt/generation changes. No cross-run reuse of changed
semantic definitions is implemented by this candidate.

## Existing embedding sample

Six nearest-neighbor examples were inspected using saved summaries. Some pairs
share useful broad themes: FV000016/FV000110 both feature psychological/social
discussion; FV000006/FV000053 share absurd comedy. Others warrant scrutiny:
FV000014/FV000105 share comedy-related vocabulary but differ substantially in
topic, and FV000018/FV000060 share religious terms despite different purposes.
These are qualitative text inspections, not human judgments of the raw videos.
With only 47 indexed videos, the best available neighbor may still be irrelevant.
No relevance threshold, ranking rule or embedding template was changed.

The 141 top-three neighbor rows are in retrieval_review.csv. Record independent
relevant/partial/unrelated judgments there before computing retrieval metrics.
131 metadata-source evidence flags are in evidence_review.csv; a flag is not a
confirmed error. Schema/exact-quote correctness does not establish entailment.

## Validation

Both candidate configurations passed existing definition validation. The existing
29 semantic regression tests passed. The read-only audit revalidated all 47
completed records, their current source fingerprints, exact-source quotes,
taxonomy, rendered embedding inputs, file hashes and normalized vectors; no
artifact errors or exact duplicate vectors were found. The active run had 13
exhausted failures. Machine-readable details are in summary.json and failures.csv.
