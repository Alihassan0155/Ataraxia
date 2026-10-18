# Category discovery results ? 2026-10-18

Fresh pinned Qwen category-only discovery completed on all **118** unresolved videos after a five-video smoke test. The initial smoke attempt stopped for overlong justifications; its outputs are preserved. A fresh attempt passed validation after explicit brief-response instructions. Evidence review flagged the satirical apology suggestion, and invalid evidence was withheld before continuing. Passing the smoke gate established safe local proposal collection, not classification accuracy.

| Outcome | Unique videos |
|---|---:|
| New-category proposals | 0 |
| Existing-category proposals, all requiring review | 62 |
| Unknown / abstained | 49 |
| Invalid outputs | 7 |
| Execution failures | 0 |

## New categories

**None.** There are no new names, descriptions, supporting videos or frequencies to list. Both validated results and raw responses (including rejected/invalid responses) were checked for new labels. No synonymous new labels existed to merge. The open prompt did not prefer the existing taxonomy, but Qwen still selected existing labels or abstained. This does not demonstrate that the existing taxonomy is complete.

## Existing-category proposals

Counts below are distinct-video proposal frequencies, not independently verified supporting-video counts. All remain unaccepted. Per-video descriptions, comparison justifications, exact evidence and review flags are in the local JSONL output.

| Existing category | Proposed videos |
|---|---:|
| Comedy | 23 |
| ASMR | 8 |
| DIY, Crafts & Outdoor Hobbies | 5 |
| Education | 5 |
| Travel & Adventure | 5 |
| Food & Cooking | 3 |
| Lifestyle, Vlogs & Relationships | 3 |
| Mental Health & Motivation | 2 |
| News, Politics & Social Issues | 2 |
| Science & Technology | 2 |
| Sports & Fitness | 2 |
| Beauty & Style | 1 |
| Music & Dance | 1 |

## Evidence and review

All available category inputs were transcripts only; no native video or audio was inspected. Quotation presence does not establish a category in context. Nineteen invalid-evidence/filler proposals were preserved and converted to abstentions; these are included within the 49 unknowns. Seven malformed/schema-invalid outputs remain separate. All 62 existing-label proposals require content review; explicit agent flags identify satire, unsupported topic inferences, sparse fragments and uncertain ASMR claims. No proposals were automatically accepted.

Examples of saved evidence (proposals only):

- `YT_oPxc8bLucY8` ? Food & Cooking: [{"source": "transcript", "quote": "Rough chop some of these tomatoes. Throw them in a oven dish."}]
- `YT_dGdZf5eNlLs` ? Science & Technology: [{"source": "transcript", "quote": "You will not believe the tech in Chinese cars."}]
- `YT_fLB_A0jLYP4` ? Travel & Adventure: [{"source": "transcript", "quote": "These are the world's newest overwater villas. They're located in Saudi Arabia"}]

## Preservation and outputs

The previous 54 accepted classifications and taxonomy file hashes are unchanged. The other 133 evidence-empty videos were not processed. No Supabase access/writes, taxonomy updates, Gemini, Whisper, BGE-M3 or full semantic extraction occurred. Model and revision: `Qwen/Qwen3-4B-Instruct-2507`, `cdbee75f17c01a7cc42f958dc650907174af0554`; greedy cached NF4 model. All 54 backend tests passed.

Local run: `backend/reports/category_discovery_inference_20261018_r2/`.

- `run.json`: frozen input/configuration, model revision, versions and code hashes.
- `videos/<video_id>/response.txt` and `result.json`: raw responses and atomic checkpoints.
- `smoke_report.json`, `smoke_review.json`, `smoke_approval.json`: smoke validation and review.
- `reviewed/report.json`: final counts and preservation checks.
- `reviewed/new_categories.json`: new-category report (empty groups).
- `reviewed/existing_category_proposals.jsonl`: 62 separate existing-category proposals and evidence.
- `reviewed/withheld_proposals.json`: 19 withheld outputs.
- `reviewed/invalid_outputs.json`: seven invalid outputs.
- `checksums.json`: verified saved-file hashes.

Inference is finished and the worker exited successfully. No database changes follow this run.
