# Local category proposals

The user authorized evidence-supported new category proposals after the closed-taxonomy category completion run. This is a separate local category-only workflow; it does not change the frozen semantic extraction pipeline, the production taxonomy, or database records.

`python -m backend.video_data.run_category_proposals` reuses the existing pinned Qwen loader, 172 prepared inputs, checkpointing and five-video smoke gate. It preserves the 54 previously accepted classifications and processes only the other 118 evidence-bearing inputs. The other 133 evidence-empty videos remain excluded. All 118 are outside the approved 1,140-video database scope.

Prefer an existing category; otherwise propose one short reusable English label. New labels have no database category ID. All non-null results are proposals requiring review, including existing-category suggestions. Exact evidence quotes are validated but do not prove the label is supported in context. Invalid evidence proposals are retained in `rejected_category_proposal` and become abstentions; schema/parse errors remain invalid. No confidence scores are invented.

The successful smoke-validation run is `backend/reports/category_proposals_20261018_r3/`. Two earlier smoke attempts are preserved. In the successful attempt, malformed evidence is safely withheld. Smoke evidence review separately withholds the mental-health proposal on the satirical apology video. No smoke or bulk proposal is automatically added to the taxonomy or accepted into Supabase.

`run.json` freezes requests, model revision, configuration, package versions and runner hash. `policy_sources.json` records supporting policy source hashes. Per-video `videos/<id>/result.json` and `response.txt` preserve checkpoints and raw outputs; aggregate `results.jsonl` is a derived proposal index. `report.json` uses the inherited runner field `successfully_classified` to count non-null **proposals**, not independently accepted classifications. Final review summaries must distinguish these.

Model: `Qwen/Qwen3-4B-Instruct-2507`, revision `cdbee75f17c01a7cc42f958dc650907174af0554`, local cached NF4 configuration, greedy category-only generation. No Gemini, Whisper, BGE-M3, full semantic extraction or database writer is invoked.

Validation: 50 backend tests passed, including four proposal tests covering new labels, existing IDs, abstention, fabricated evidence rejection and original-category protection.

## Completed run

118 unique unresolved videos processed; 0 execution failures, 3 invalid outputs, 45 abstentions and 70 raw existing-label proposals. No new category labels were proposed. Smoke review withholds one ambiguous satire proposal; 69 remaining proposals require evidence review and are not accepted classifications. Seventeen invalid-evidence/filler proposals were preserved and safely abstained. The previous 54 accepted results remain unchanged. No database or taxonomy updates occurred. Final aggregate: `backend/reports/category_proposals_20261018_r3/proposal_summary.json`; remaining proposals: `pending_review.jsonl`; new-label list: `new_category_proposals.json` (empty). All checkpoint identities and saved file hashes verified.
