# Category-only Qwen execution results

Completed locally using `Qwen/Qwen3-4B-Instruct-2507`, revision `cdbee75f17c01a7cc42f958dc650907174af0554`.
NF4 double quantization, greedy generation, batch size 1, 400 output-token cap. Existing prepared evidence only.

| Outcome | Videos |
|---|---:|
| Total processed, unique approved IDs | 172 |
| Supported category selections after review | 54 |
| Unknown / abstained | 94 |
| Execution failures | 0 |
| Invalid schema/ID/evidence outputs, excluded | 24 |

## Category distribution

| Category | Videos |
|---|---:|
| unknown | 94 |
| Food & Cooking | 28 |
| DIY, Crafts & Outdoor Hobbies | 6 |
| News, Politics & Social Issues | 5 |
| Comedy | 3 |
| Entertainment & Animation | 3 |
| Science & Technology | 3 |
| ASMR | 2 |
| Sports & Fitness | 2 |
| Nature, Animals & Conservation | 1 |
| Travel & Adventure | 1 |

Distribution excludes the 24 invalid outputs. These have no accepted category and remain unresolved; they were not silently assigned a label.

## Validation and provenance

- All 172 approved requests processed; none of the other 133 evidence-empty videos processed.
- All accepted non-unknown categories use one existing onboarding ID. No category or taxonomy entry was created.
- Initial smoke attempts were rejected for unsupported evidence or excessive quote length; both are retained. The corrected five-video smoke validated before bulk continuation.
- The final run contains 172 unique checkpoints. Earlier smoke outputs are additional attempts on the same small subset, not additional video IDs.
- Nine filler-only category proposals were rejected at runtime. Fifty additional unsupported/ambiguous proposals were conservatively abstained in agent review: 59 withheld proposals total.
- Review only retains a proposal or changes it to unknown; it never substitutes a different category. Raw responses/checkpoints remain unchanged.
- Review is conservative agent evidence review, not independent human ground truth. Literal quotations alone do not prove entailment.
- Confidence was not requested or calibrated; no confidence score was fabricated.
- Per-record provenance includes model/revision, input hash, run identity, evidence and original category. Full prepared metadata and inputs are frozen in run.json.
- 46 backend tests pass. Final cohort, canonical IDs, arithmetic, per-record scope flags and file checksums verified.
- Inference process exited and released the shared GPU lock. No further model calls are pending.

## Output locations

- Final reviewed results: `backend/reports/category_completion_run_20261017_r3/reviewed/results.jsonl`
- Final report: `backend/reports/category_completion_run_20261017_r3/reviewed/report.json`
- Invalid outputs and errors: `backend/reports/category_completion_run_20261017_r3/reviewed/invalid_outputs.json`
- Review reasons: `backend/reports/category_completion_run_20261017_r3/reviewed/review_decisions.json`
- Raw aggregate: `backend/reports/category_completion_run_20261017_r3/results.jsonl`
- Atomic checkpoints/raw text: `backend/reports/category_completion_run_20261017_r3/videos/<video_id>/`
- Frozen configuration/inputs: `backend/reports/category_completion_run_20261017_r3/run.json`
- Five-video gate: `smoke_report.json` and `smoke_approval.json` in that run directory.
- File integrity: `backend/reports/category_completion_run_20261017_r3/checksums.json`
- Earlier smoke attempts: `backend/reports/category_completion_run_20261017/` and `backend/reports/category_completion_run_20261017_r2/`

## Resume

Run the same category-only runner with the same prepared directory and `--out backend/reports/category_completion_run_20261017_r3`. Frozen identity mismatches are refused and terminal checkpoints are skipped. No automatic retry of invalid outputs is performed.

**No Supabase writes/imports occurred. The existing 1,140 video records, metadata, historical semantics, embeddings and unknown taxonomy entry were not modified. Gemini, Whisper, BGE-M3 and full semantic extraction were not run.**
