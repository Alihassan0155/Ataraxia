# Active selection policy ? 2026-10-08

**4,226 selected videos; only 94 non-target-language flags excluded.** Low-confidence, mixed-language, no-detected-speech, and unmapped categories are retained with their flags. No raw files were deleted. Active metadata: `data/normalized/selected_merged_v2/selected_metadata.csv`. Evidence output: `data/normalized/preprocessed_merged_v2/`. The held-out 50 remains fixed.

Next: run `./run_post_language.ps1 -Phase preprocess`. Human review is optional under the new policy; the earlier review-first instructions below are historical.

---

# Active dataset update ? 2026-10-08

The active combined dataset has **4,320 videos**. Use [the merged report](merged/normalization_report.md), [merged candidates](merged/local_candidates.csv), and [merged audit summary](audit_merged/summary.json). All downstream defaults now use these paths. The report below is the preserved historical 3,696-video snapshot.

---

# Normalized Ataraxia dataset

Created 2026-10-08. Original metadata, media, annotations and prior study outputs are unchanged.

61,732 unique platform identities from 63,552 source records; 3,696 local byte-unique representatives.

The large YouTube metadata catalogue remains inventory-only when media is absent. Local availability and eligibility are separate.

## Local category distribution

| Shared category | Local representatives |
| --- | ---: |
| ASMR | 6 |
| Beauty & Style | 153 |
| Comedy | 541 |
| DIY, Crafts & Outdoor Hobbies | 18 |
| Education | 155 |
| Entertainment & Animation | 504 |
| Food & Cooking | 99 |
| Gaming | 193 |
| Lifestyle, Vlogs & Relationships | 524 |
| Mental Health & Motivation | 54 |
| Music & Dance | 299 |
| Nature, Animals & Conservation | 105 |
| News, Politics & Social Issues | 139 |
| Religion & Spirituality | 100 |
| Science & Technology | 151 |
| Sports & Fitness | 340 |
| Travel & Adventure | 204 |
| Unmapped / Needs Review | 82 |
| Vehicles | 29 |

## Interface and remaining work

inventory.csv retains all canonical IDs; source_records.csv preserves every source row and original metadata. id_aliases.csv connects historical YT IDs to platform identities. category_mapping.csv documents broad mappings; conflicts remain flagged. Native media is referenced without copying, resizing or renaming.

FineVideo contexts/transcripts are reused by path; pending evidence is listed in preprocessing_queue.csv. This is metadata/interface normalization, not completed audiovisual preprocessing.

Next: validate decoding and orientation, audit speech across clips, produce matching 16 kHz mono PCM audio/transcripts/eGeMAPS/context bundles with a CUDA-compatible backend, resolve category conflicts and unmapped labels, then enforce the <=30% horizontal constraint and freeze eligible metadata. Do not sample the combined held-out cohort until these eligibility decisions are recorded.

## Limitations

- Available does not mean fully decodable or language eligible
- Historical language audit may inspect only initial speech
- Different hashes do not rule out reposts
- External media paths require restoration for portability
- Broad source categories are metadata groupings, not content-verified labels
- No final selection or new study splits frozen; horizontal cap must be enforced after eligibility
- Existing FineVideo-only held out selection is provisional and unchanged

## Reproduce

Run `.venv-qwen-cuda/Scripts/python.exe src/build_normalized_dataset.py --output data/normalized_v2` to generate a new version without overwriting this inventory.
