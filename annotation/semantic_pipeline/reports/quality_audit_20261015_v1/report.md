# Semantic quality audit

Verified 47/47 completed artifacts; 0 artifact errors.

47 records required repair; 13 current failures, 13 exhausted. Failure groups: {'incomplete_repair_decisions': 1, 'other_validation': 2, 'unsupported_or_overlong_quote': 4, 'malformed_or_truncated_json': 5, 'controlled_vocabulary': 1}.

Use retrieval_review.csv to label nearest-neighbor relevance as relevant/partial/unrelated. There is no automatic retrieval-quality pass. Evidence review flags are review prompts, not proven errors. Missing fields are not filled automatically.

## Sparse fields

- secondary_categories: 47/47 empty
- audience_focus: 46/47 empty
- meaning: 45/47 empty
- intent: 44/47 empty
- humor_type: 44/47 empty
- educational_purpose: 41/47 empty
- subcategory: 37/47 empty
- content_focus: 32/47 empty
- setting: 32/47 empty
- music: 31/47 empty
- sound_effects: 31/47 empty
- temporal_context: 29/47 empty
- cultural_references: 24/47 empty
- activities: 15/47 empty
- vocal_delivery: 13/47 empty
- tags: 12/47 empty
- objects: 10/47 empty
- presentation: 10/47 empty
- dialogue_themes: 8/47 empty
- topics: 6/47 empty
- content_style: 6/47 empty
- subjects: 6/47 empty
- spoken_language: 5/47 empty
- video_format: 5/47 empty
- speech_summary: 1/47 empty

## Limitations

- Structural validation does not establish semantic entailment.
- Existing-video nearest neighbors are not a held-out text-query benchmark.
- No raw-video viewing or human relevance judgments were performed.
- Live input files may grow after this read-only snapshot.
