# Practical semantic normalization (v11)

Implemented only. No tests, scripts, models, downloads or workers were executed.
Existing successful results, frozen files and raw predictions are unchanged.

## What failed and what changes

The saved FV000002/FV000005 drafts already used valid primary_category Comedy.
Their invalid secondary categories were Parody (a subcategory) and Performance
(not a broad category). V10 rejected the entire video. FV000006 included an
irrelevant extraction_confidence citation and failed before provenance generation.

The new, opt-in `normalization_policy: practical-v1` performs local cleanup before
the existing schema/taxonomy validation and deterministic provenance:

- Match controlled category names regardless of case/punctuation. Common aliases
  map to existing broad categories. Uniquely owned subcategories map to their
  parent broad category. Conservative near-name spelling matches use a fixed
  threshold/margin; unmatched primary categories become unknown. Unmatched
  secondary labels are omitted, and repeated/primary secondary categories removed.
- Example: Parody maps to Comedy and is removed from secondary_categories when
  Comedy is already primary. Ambiguous Performance is omitted rather than guessed.
- Match subcategories only within the chosen primary category; otherwise null.
  Normalize format/style labels or use unknown, retaining descriptive fields.
- Ignore and record all unnecessary model evidence, including citations of
  confidence, unsupported/unverified arrays, taxonomy or malformed evidence items.
  Only application-built exact unique references enter final field_evidence.
- Accept JSON fences, a leading BOM, trailing commas outside quoted strings,
  scalar strings for list fields, empty optional lists, numeric/boolean strings,
  duplicate/blank list items and blank/missing nullable fields.
- Ignore extra keys while retaining original values in normalization_changes.
  Content values otherwise remain unchanged. Taxonomy cleanup does not edit topics,
  tags or summaries. Raw model output and all normalization decisions are saved.

No evidence fuzzy matching, quote fabrication or cross-source repair was added.
Name similarity applies ONLY to category/format/style labels. Missing quotes
still mark assertions unverified instead of deleting descriptions. No new schema
fields or embedding-template changes were introduced; this retains semantic v2.
Malformed/truncated JSON, duplicate JSON keys, invalid core content and out-of-range
confidence still fail; we do not invent missing text or clamp confidence. This
does not guarantee semantic accuracy, which remains a separate quality concern.

The Qwen checkpoint, quantization, generation settings, tokenizer and embedding
pipeline match v10. GPU evidence repairs stay disabled. Simple cached validation
errors can be retried without Qwen forward passes; embedding valid cached metadata
still uses BGE-M3. Cached inputs must match the current source fingerprint.

## Files

- `src/ataraxia/semantic/normalization.py`: safe parser, aliases/label mapping and
  deterministic field cleanup, with an audit trail.
- `provenance.py`: practical mode ignores irrelevant model evidence; the default
  v10/legacy behavior remains strict.
- `worker.py`: opts into cleanup only for the new policy; saves normalization_changes.
- `config.py`: freezes and validates the named policy.
- `configs/pipeline_v11_canary6.json`: six-video snapshot for targeted retry.
- `configs/pipeline_v11.json`: full current Gemini source, for later manual use.
- `tests/test_practical_normalization.py`: regressions for cached FV000002/5/6,
  harmless JSON cleanup, label mapping, ignored evidence and strict retained quotes.

Source hashes changed: do not resume a v10/v9 run with the new source or edit its
frozen.json. New runs below preserve all old files, including successful FV000016.

## Manual commands (annotation directory)

Stop any existing semantic worker with Ctrl+C and wait for exit first. No process
was stopped or started automatically.

1. Tests (not yet run by the assistant):

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
.\.venv-qwen-cuda\Scripts\python.exe -m unittest discover -s .\semantic_pipeline\tests -v
```

2. After tests pass, retry ONLY the three failed cached videos into a NEW run:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py retry-cached --config .\semantic_pipeline\configs\pipeline_v11_canary6.json --source-run semantic_v10_canary6 --run semantic_v11_cached3 --video-ids FV000002 FV000005 FV000006
```

This reuses saved drafts, not Qwen inference, and does not touch successful
FV000016. No `--selection-run` is needed. Inspect the printed per-ID validation
and embedding results; success is not claimed until that command completes.

3. Full pipeline AFTER reviewing the retry, if desired:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py run --config .\semantic_pipeline\configs\pipeline_v11.json --run semantic_full_v11
```

Repeat the exact full-run command to resume it and skip its verified completions.
Cross-run results are NOT silently imported; the new full run can process videos
completed under earlier definitions again. Earlier results remain preserved.
Do not assume an empty new-run counter means older results were lost.

The full config reads the currently configured full Gemini prediction JSONL and
waits for further Gemini outputs. It is not limited to the six-video snapshot.
No full run or paid Gemini request has been started by this change.
