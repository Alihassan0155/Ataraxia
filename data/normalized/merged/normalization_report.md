# Active selection policy ? 2026-10-08

**4,226 selected videos; only 94 non-target-language flags excluded.** Low-confidence, mixed-language, no-detected-speech, and unmapped categories are retained with their flags. No raw files were deleted. Active metadata: `data/normalized/selected_merged_v2/selected_metadata.csv`. Evidence output: `data/normalized/preprocessed_merged_v2/`. The held-out 50 remains fixed.

Next: run `./run_post_language.ps1 -Phase preprocess`. Human review is optional under the new policy; the earlier review-first instructions below are historical.

---

# Active merged Ataraxia dataset

4320 local video IDs, all with passed full video decoding. 2345 provisional target-language candidates; 1975 language-review cases.

All downstream defaults use this merged cohort. The original 3696-video and 624-video audits remain historical snapshots. The master collection now resolves to data/yt_shorts_master/videos.

| Language status | Count |
| --- | ---: |
| target_language_candidate | 2345 |
| review_low_confidence | 968 |
| review_no_detected_speech | 905 |
| review_non_target_language | 94 |
| review_mixed_language | 8 |

## Active paths

- metadata: `data/normalized/merged/local_candidates.csv`
- audit: `data/normalized/audit_merged`
- selected: `data/normalized/selected_merged_v1`
- preprocessed: `data/normalized/preprocessed_merged_v1`
- heldout: `held out/merged_50`
- total: `4320`

## Next commands

`./run_post_language.ps1 -Phase review` creates the decision template; complete applicable keep/exclude/category decisions, then run `-Phase select`, `-Phase preprocess`, and `-Phase heldout`. Selection defers blank review cases; it does not erase them. Human language judgements and model language candidates remain distinguished. No model annotation starts.
