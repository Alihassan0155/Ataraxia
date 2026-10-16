# Semantic v12: local summary fallback

Implementation only. No scripts, inference, tests, downloads or workers executed.
All prior outputs and v11 configuration files are preserved. The semantic v2
schema, prompt, taxonomy, model checkpoints, generation and embedding settings
and embedding template remain unchanged.

New frozen normalization policy: practical-v2-summary. V11 practical-v1 keeps its
old behavior; source files changed so old frozen runs cannot resume using this
checkout. Never edit an old frozen.json to bypass that guard. Use a new run.

When semantic_summary is absent, null, blank or an unknown/null placeholder:

1. Copy an existing speech_summary if it fits the unchanged summary schema.
2. Otherwise copy an existing meaning if it fits.
3. Otherwise fail explicitly; never generate filler or stitch topics into prose.

Suitable candidates are strings, trimmed, 20-1000 characters, with alphabetic
content. Descriptive source fields are left unchanged. A valid existing summary
is never replaced. Unsupported/unverified status is rebuilt by existing provenance
logic; a fallback is still an unverified model description, not a verified fact.
normalization_changes records the copied-from field and original/new values.

Existing practical cleanup still supplies absent nullable fields as null and
absent list fields as empty lists; it handles fences, trailing commas, numeric
and boolean strings and list duplicates. A missing core confidence or malformed/
truncated JSON is not invented or silently filled. No GPU repair call is added.

Changed files: normalization.py, worker.py, config.py. Added pipeline_v12.json,
tests/test_summary_fallback.py and this report. Tests cover real cached FV000014
when present, source preference, blank summaries, no valid candidate, preserving
valid summaries and optional/JSON cleanup. Tests have NOT been executed here.

## Manual commands

From E:\ALI\Ataraxia\annotation, stop existing semantic workers with Ctrl+C and
wait for exit before retrying. No process was stopped automatically.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
.\.venv-qwen-cuda\Scripts\python.exe -m unittest discover -s .\semantic_pipeline\tests -v
```

After tests pass, retry ONLY FV000014 using its cached v11 output. This performs
local parsing/normalization and embedding, not another Qwen forward pass:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py retry-cached --config .\semantic_pipeline\configs\pipeline_v12.json --source-run semantic_full_v11 --run semantic_v12_retry_FV000014 --video-ids FV000014
```

The new target run must be unused. The source run must contain a failed cached
output for FV000014 with matching source fingerprints. Other videos and successful
v11 records are not processed or overwritten. The command explicitly reports any
remaining validation error rather than claiming success in advance.

For later full processing:

```powershell
.\.venv-qwen-cuda\Scripts\python.exe .\semantic_pipeline\scripts\semantic.py run --config .\semantic_pipeline\configs\pipeline_v12.json --run semantic_full_v12
```

Repeat the exact command to resume this NEW run. Completions from previous runs
are preserved, but not silently imported across changed definitions; this full
run may process previously completed videos again. Use the targeted retry above
when only FV000014 needs recovery. No full run was started by this change.
