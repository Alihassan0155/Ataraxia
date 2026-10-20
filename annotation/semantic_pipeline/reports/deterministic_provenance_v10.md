# Semantic v10: deterministic provenance

Implementation only. No scripts, tests, inference, downloads or workers were run
for this change. Tests below are provided for manual execution, not reported as
passing. Existing prediction files, completion records and frozen definitions
were not edited. All model checkpoints, taxonomy labels, affect rubrics,
calibration, semantic content fields and embedding template remain unchanged.

## Cause

V9 asked Qwen to paraphrase semantic content and independently reproduce exact
quotes in the same response. The all-fields-must-have-quotes validator conflated
absent quotations with unsupported content. GPU passage selection then retracted
descriptions or failed on omitted decisions. Taxonomy labels were occasionally
cited as observed evidence. Longer token budgets did not resolve this design
problem.

## New data contract

The original 31 semantic fields and their types/limits remain. V2 adds one field,
`unverified_fields`, and a record-level `source_provenance` object. The explicit
record version is `semantic-record-v2`. The minimal schema extension is necessary
to distinguish an asserted but unverified description from null/unknown fields;
putting both in unsupported_fields would violate the old contract and erase this
distinction. JSON object structure remains; there is no switch to passage-ID
model output and no requirement for compact one-line JSON.

Qwen emits semantic fields and empty field_evidence/unverified_fields arrays.
The application populates provenance without another model request:

1. Retain content values exactly (except existing blank-null normalization).
2. Inspect any legacy/model-supplied evidence, record its disposition, and exclude
   it from authoritative field_evidence. Bad field/source/quote object structures
   still fail. Taxonomy citations are excluded and recorded, never renamed.
3. For descriptive fields, look for the literal field string (or a literal list
   member) in a predetermined source family. Accept only a single occurrence in
   that designated source and only when 1-250 characters. Store exact offsets and
   original bytes as a reference. Do not normalize punctuation/case/whitespace,
   fuzzy-match, crop long quotations, or search another source for a rejected
   model citation. Independent field-text lookup is not a repair of model quotes.
4. If no unique reference exists, emit no evidence entry; keep the field and mark
   it unverified. Partial references for list members do not verify the whole list.
5. Null/unknown scalar fields remain unsupported. Empty lists are absent.
6. Classifications record frozen taxonomy membership separately and remain
   observationally unverified. Taxonomy is never observed evidence.
7. Revalidate full schema, controlled labels, exact/unique retained references,
   modality associations and assertion statuses. Cache recovery reconstructs
   deterministic offsets/statuses; mismatches fail.

All asserted fields remain unverified even when an exact reference exists. String
matching is not semantic entailment: for example `dangerous` inside `not dangerous`
must not establish truth. This implementation does not perform contradiction
detection and explicitly records that limitation. A source contradiction is not
resolved by omitting a quote or declaring a field verified. Human or separately
validated semantic review is required to establish/refute such claims. Model
confidence stays uncalibrated and is not raised after provenance construction.

No GPU evidence/summary repair requests are used in v10 (both limits zero).
Malformed JSON or invalid semantic fields still fail and use the ordinary bounded
job retry policy; no invalid completion is saved. Schema limits and 250-character
quote limit remain. New runs can still fail for malformed extraction JSON or
incorrect controlled labels; deterministic provenance is not a blanket success
bypass. Semantic assertions remain in embedding input under the unchanged
template: consumers must consult unverified_fields and source_provenance rather
than treating embeddings as verified facts.

## Files

- `src/ataraxia/semantic/provenance.py`: independent deterministic provenance.
- `representation.py`: explicit v2 status handling and strict retained references;
  v1 continues to require evidence for each assertion.
- `worker.py`: new policy branch, provenance storage and cache integrity checks.
- `storage.py`: final record matches metadata-stage provenance.
- `config.py`: validates/fingerprints policy, zero GPU repairs and matching schemas.
- `schemas/semantic_metadata.v2.schema.json`, `schemas/record.v2.schema.json`.
- `configs/extraction_prompt_v5_provenance.txt`.
- `configs/pipeline_v10_canary6.json`: same six Gemini snapshot IDs as v9.
- `tests/test_deterministic_provenance.py`: synthetic and saved FV000002,
  FV000005 and FV000006 regressions, exact offsets, source restrictions,
  ambiguous quotations, null/unverified separation and cache integrity.

No v8/v9 config, schema, prompt, inference checkpoint or historical result changed.
Shared semantic source code changed, so prior run hashes WILL differ. Do not
edit old frozen.json or silently resume those runs under new code. Stop existing
workers before using new code. Older runs require their original code checkout
to resume. This change does not add cross-version completion reuse.

## Manual Windows commands

From `E:\ALI\Ataraxia\annotation`, first stop any existing semantic worker with
Ctrl+C and wait for it to exit. Nothing was started/stopped automatically.

Run tests (no inference; download calls in existing tests are mocked):

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
.\.venv-qwen-cuda\Scripts\python.exe -m unittest discover -s .\semantic_pipeline\tests -v
```

Only after tests pass, explicitly run a NEW six-video development canary:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py run --config .\semantic_pipeline\configs\pipeline_v10_canary6.json --run semantic_v10_canary6 --once
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py status --run semantic_v10_canary6
```

The source snapshot contains FV000002, FV000005, FV000006, FV000016, FV000032 and
FV000057. No full-dataset dispatch. `--once` drains eligible work, then exits;
backoff failures may remain, so inspect the report. All records are in a separate
run. The original cached FV000002/5/6 cases are read by tests when available.

For an explicit cache-first retry of just the three original v9 failures (no Qwen
request when their cached semantic JSON is valid, but BGE-M3 embedding still runs):

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py retry-cached --config .\semantic_pipeline\configs\pipeline_v10_canary6.json --source-run semantic_v9_canary6 --run semantic_v10_cached3 --video-ids FV000002 FV000005 FV000006
```

The cached retry refuses source IDs already completed, missing/mismatched source
fingerprints, malformed JSON or invalid semantic labels. Use the fresh six-video
canary if historical drafts cannot be reused; do not edit labels to force a pass.
New output paths must be unused; preserve earlier failed runs for provenance.

## Acceptance review

Check that content has not been erased solely for absent quotes, taxonomy never
appears as an evidence source, references are literal/unique, unsupported and
unverified remain distinct, no GPU quote-repair events occur, and invalid schema
or fabricated retained references still fail. Semantic quality requires a separate
human/retrieval review; no live performance or quality improvement is claimed.
