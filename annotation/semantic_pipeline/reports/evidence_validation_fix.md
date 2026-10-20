# Evidence validation and bounded repair — 2026-10-13

## Scope and outcome

Only FV000002 and FV000005 were dispatched for live cached retries. No other
videos, emotion annotation models, affect scores, original predictions, successful
semantic records or calibration outputs were changed. The existing continuous
semantic v3 worker received a graceful STOP request before targeted execution.
Gemini was not stopped or restarted. All weights were loaded offline from cache;
no installation or model download occurred.

**27 regression tests passed** in the existing CUDA environment. The final cached
replay passes FV000005 schema/semantic validation; its embedding is blocked by missing
BGE-M3 weights. FV000002 remains invalid because Qwen retracted its required summary.
Neither has a completed record or embedding. The previous failed drafts and new correction responses
are preserved in separate frozen run directories.

## Why previous repair failed

- FV000002 copied a full transcript paragraph into a quote with a 250-character
  maximum. Previous repair was a complete-response generation without a safe
  preprocessing step. The new response could repeat the same paragraph. Inspection
  also found a quote with punctuation differing from its designated speech source,
  `Parody` used as a broad category rather than a subcategory, and missing evidence
  for several asserted fields.
- FV000005 initially fabricated/paraphrased an activities quote and linked transcript
  content to `speech_text`, which is a separate Gemini summary. Full-response repair
  introduced/repeated another overlong paragraph. Other quotes also used the wrong
  designated source or concatenated descriptions not present verbatim.
- Validators reported the first error only, so repairing one quote could reveal
  previously hidden coverage/taxonomy failures. Long full-response repair also risked
  exhausting the existing 2048-token output budget; this occurred in the live retry.

## Repair policy

The JSON schema is unchanged: `field_evidence[].quote` remains 1–250 characters.
Prompts now request exact short phrases, preferably at most 200 characters, and
explicitly distinguish transcript, speech-summary and visual evidence sources.

After JSON parsing and nullable-blank canonicalization, `evidence.py` checks every
quote before schema and semantic validation. An exact-source overlong quote is
shortened only when a complete sentence or contiguous sentence block within the
limit has lexical anchors to the original field. All retained list values need
anchors. Negations and qualifiers within retained sentences are not removed by
arbitrary character clipping. If no safe candidate is found, repair is rejected.
This lexical screen is not a claim of semantic entailment.

For nonverbatim quotes, deterministic matching allows only unique matches after
normalizing whitespace and common typographic apostrophes, quotation marks and
dashes. The replacement is copied from the original source using tracked offsets;
its final text must match that source exactly. No word substitutions, fuzzy
paraphrases, source changes or invented replacements are allowed. Ambiguous matches
and unmatched quotes are rejected. Valid short quotes are unchanged. Visual quotes
are checked against visual evidence, not against transcripts.

The worker still permits only one model repair per job attempt. Normal continuous
retry/backoff limits are unchanged. Error feedback includes the precise failing
path and all available schema/quote/coverage issues. Every corrected response is
parsed, safely repaired and fully validated again before metadata is saved.

The v5 bounded correction reduces output size by asking Qwen to select exact-source
passage IDs plus explicit unknown/taxonomy corrections. Catalog entries are at most
200 characters. Materialization cannot accept invented IDs, descriptions or confidence
changes. Only explicit model choices may select a different evidence source or retract
a claim; deterministic quote repair never does so. Unparseable initial JSON retains
the bounded full-response fallback. Catalog identity is not proof of entailment.
All materialized responses must pass the existing complete validators.

The final v7 policy simplifies the correction to one explicit passage decision per
content field, allowing multiple real IDs for list fields. Missing fields are accepted
only when originally empty/null/unknown. Every positive claim needs an explicit model
decision. Null decisions retract unsupported claims using schema-correct null, empty
lists or controlled unknown values. The required nonempty summary cannot be retracted,
so a null summary decision is rejected instead of fabricating replacement content.
`--selection-run` reuses stored model decisions after verifying the original draft hash.
Final replay made no additional Qwen forward calls. All explicit retractions and selected
source passages are preserved in per-video repair provenance. This is an explicit
model retraction mechanism, not automatic deletion of evidence to retain invalid claims.

## Tests executed

Command, from `annotation/`:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe -m unittest discover -s .\semantic_pipeline\tests -v
```

27/27 passed, including: unchanged valid short quote; overlong verbatim passage;
fabricated/paraphrased rejection; punctuation/whitespace handling; unrepairable
long sentence; multiple invalid items; negation preservation; visual-source
isolation; ambiguous matching; real historical FV000002/FV000005 failures;
selector source identity, unknown-ID rejection and forbidden descriptive/confidence
changes. Existing frozen-resume, vector-integrity and extraction-cache tests passed.
Additional tests cover every asserted-field decision, rejecting retracted required
summaries, multiple real passage IDs for lists, safe omitted-empty fields and explicit
embedder-only downloads including `.bin` weights (download mocked; no weights fetched).
The CLI help entry point also passed its safe smoke check.
These tests establish contract behavior, not semantic accuracy.

## Live targeted retries

| Run | FV000002 | FV000005 |
| --- | --- | --- |
| `semantic_evidence_fix_v4` | Rejected: tags quote still not exact in designated speech source | Rejected: full JSON repair ends with an unterminated string |
| `semantic_evidence_fix_v5` | Rejected: `Parody` remains outside broad category taxonomy | Rejected: selector attempts descriptive corrections outside its permitted contract (`subjects` is first reported); coverage/array types also need correction |
| `semantic_evidence_fix_v6` | Initial decoder rejected a list of real IDs as a scalar | Initial decoder rejected an omitted already-empty secondary-category field |
| `semantic_evidence_fix_v7` | Rejected: explicit null decision retracts the required summary | **Schema/semantic validation passed**; embedding blocked by unavailable BGE-M3 weights |

The v5 FV000002 selector response produces source-backed short quotes, but leaves
the invalid broad-category value. The FV000005 selector response is not a complete
valid repair: only one evidence selection is present, several list fields are null,
and descriptive fields are repeated in corrections. The protocol refuses it rather
than inventing support or silently erasing claims to make the record pass.

Machine-readable outcomes:

- `runs/semantic_evidence_fix_v4/reports/targeted_retry.json`
- `runs/semantic_evidence_fix_v5/reports/targeted_retry.json`
- `runs/semantic_evidence_fix_v6/reports/targeted_retry.json`
- `runs/semantic_evidence_fix_v7/reports/targeted_retry.json` (**final live status**)

Raw inputs, correction/selector outputs, errors and cache provenance hashes are in
each run's `videos/<id>/<source-fingerprint>/` directory. These runs contain only
the two requested video IDs. There are no completed per-video records.

## Files changed

- `src/ataraxia/semantic/evidence.py`: exact-source quote repair and bounded passage catalogs/materialization.
- `representation.py`: aggregate error feedback without weakening validators.
- `worker.py`: prevalidation repair, complete revalidation, cache replay and preserved repair provenance.
- `models.py`: stricter short-quote repair instructions and compact selector generation.
- `retry.py`: explicit failed-ID-only replay into a new frozen run, using cached drafts.
- `cli.py`: `retry-cached` command with required source run and explicit video IDs.
- `config.py`, `configs/pipeline.json`: frozen repair policy/version validation.
- `configs/extraction_prompt.txt`: short, exact, correctly sourced quotes.
- `tests/test_evidence.py`: focused quote and selector regressions.
- `tests/test_contracts.py`: explicit embedder download regression, with downloads mocked.
- `scripts/inspect_failed_evidence.py`: read-only cached-response diagnostics.
- `README.md` and this report: policy, commands and actual validation status.

## Remaining actions

Do not restart whole-dataset semantic processing assuming both videos now pass.
FV000002 needs a supported replacement summary from a new explicit extraction/repair,
or must remain a recorded failure. The system does not automatically substitute
plausible descriptive text for its retracted summary. This is the remaining semantic
validation error: `Cannot retract required nonempty field: semantic_summary`.

FV000005's validated metadata is saved in the v7 run. Its error is operational:
`BAAI/bge-m3 does not appear to have a file named pytorch_model.bin or model.safetensors`.
The initial download helper omitted `.bin` snapshots; this has been fixed and tested.
No models were downloaded. Explicit embedder-only download command:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py download --models embedder
```

Any later retry must use a new run name because the final CLI download/error-exit
fix changes frozen source hashes. Cached v6 selectors can be reused without a Qwen
call; paths and hashes are verified. Neither quote-length relaxation nor removing
invalid evidence while retaining unsupported assertions is acceptable.

No additional automatic retries or full-dataset dispatch were started after the
reported bounded attempts. The two failures remain explicit and reviewable.
