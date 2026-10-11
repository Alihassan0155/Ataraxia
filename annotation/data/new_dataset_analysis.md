# New dataset inventory

Checked: 2026-10-05. This is a filesystem and metadata audit, not an audiovisual or spoken-language assessment. No source records or media were changed.

## Summary

| Measure | fyp_videos_1250 | yt_shorts_master |
|---|---:|---:|
| Metadata rows / unique IDs | 1,250 / 1,250 | 760 / 760 |
| Local MP4 files | 1,250 | 136 |
| Metadata rows with matching local media | 1,250 | 136 |
| Missing media rows | 0 | 624 |
| Media size | 6.154 GiB | 1.982 GiB |
| Duration range, metadata | 5–90 seconds | 6–90 seconds |
| Mean duration, metadata | 34.52 seconds | 42.42 seconds |
| Total duration, metadata | 11.99 hours | 8.95 hours |

No duplicate metadata IDs, duplicate TikTok media filenames, unmatched media filenames, or zero-byte MP4s were found. YouTube's 136 local file sizes match the metadata exactly. File existence and size do not establish successful decoding or content correctness. Content-hash deduplication was not performed.

## TikTok collection

Metadata: `fyp_videos_1250/fyp_videos_1250_metadata.csv`. The copy at `fyp_videos_1250/videos/metadata.csv` is byte-identical (SHA-256 checked). Actual media is nested at `fyp_videos_1250/videos/videos/<id>.mp4`.

Sources recorded in metadata: 1,000 records from `The-data-company/TikTok-10M`; 250 from `Suthans/tiktok (mirror of kuben-developer/tiktok-videos-4b)`.

| Category | Count |
|---|---:|
| fitness | 130 |
| travel | 120 |
| comedy | 110 |
| islamic | 100 |
| political | 100 |
| entertainment | 95 |
| beauty | 85 |
| relationships | 85 |
| dance | 85 |
| music | 75 |
| food | 70 |
| lifestyle | 55 |
| sports | 50 |
| animals | 50 |
| family | 40 |

Country fields: US 1,000; PK 212; IN 38. All US records are in the first twelve categories; PK/IN records are exclusively islamic, political, and sports. Language, country, source, and category effects therefore need careful separation in any comparison; country does not establish spoken language. A US beauty record has a Spanish description, which demonstrates that country is insufficient even for caption-language selection. Its spoken language has not been assessed.

Missing fields: create_time 1,015; subtype 1,000; music_author_name 252; desc 7; music_title 2. IDs, filenames, categories, source, URLs, and durations are populated. UTF-8 parsing preserves accents and emoji; garbled text in default Windows PowerShell output should not be mistaken for corrupt source CSV data.

No width/height, verified-language fields, explicit study splits, transcripts, acoustic features, shared contexts, or annotations are supplied. TikTok orientation remains unverified.

## YouTube collection

Metadata: `yt_shorts_master/youtube_shorts_master.csv`. Actual media is at `yt_shorts_master/videos/<video_id>.mp4`; metadata paths such as `raw/<video_id>.mp4` do not describe this folder layout and need a derived path mapping before pipeline use. Preserve the original paths as provenance.

| Category | Metadata rows | Local videos |
|---|---:|---:|
| Unassigned | 307 | 83 |
| sports_trick_shots | 72 | 1 |
| high_speed_science | 72 | 0 |
| tech_review | 68 | 8 |
| challenge_stunts | 57 | 0 |
| asmr | 44 | 6 |
| cooking_food | 43 | 29 |
| travel_adventure | 35 | 4 |
| vfx_magic | 25 | 2 |
| gaming | 20 | 0 |
| animation_edu | 10 | 0 |
| diy_crafts | 7 | 3 |

The 136-file subset is not representative of the complete metadata category mix: 83 files (61.0%) are uncategorized, and several categories have no local examples.

Metadata splits: train 277, validation 113, test 63, unassigned 307. Local subset: train 19, validation 22, test 12, unassigned 83. No channel ID appears across multiple nonblank splits; this is useful protection against creator overlap but does not rule out duplicated or related content. All 307 unassigned records also lack category and source_query.

Metadata dimensions: 758 vertical and two square; no horizontal entries. The square IDs are `ljx8bQENFMU` and `Pe4Uh74Ef7U`, both 1080 × 1080. All 136 local records have vertical metadata dimensions; actual dimensions were not probed. Dates span 2019-09-26 through 2026-09-25.

All 760 license fields are blank. Four metadata video IDs also occur in URL fields in the existing `youtube_shorts/metadata.csv`, so combining collections requires ID deduplication. This is source-record overlap, not proof that the same media exists locally in both datasets.

No spoken-language verification, transcripts, acoustic features, shared contexts, or affective annotations are supplied.

## Implications for Ataraxia

These folders add 1,386 locally present videos and 2,010 metadata records. They remain separate from the completed FineVideo pilot and do not constitute additional completed annotation work.

1. Create normalized metadata with source-qualified study IDs, resolved local paths, original source IDs/paths, and a common category mapping; preserve original CSVs.
2. Probe media for decodability, actual duration/dimensions, and audio presence. FFprobe was not available on PATH during this audit.
3. Audit spoken language before admitting videos under the English/Urdu/Hindi constraint. Distinguish silence, mixed language, and failed detection.
4. Resolve missing YouTube media and category/split coverage, and remove cross-collection duplicates from derived selections.
5. Build transcripts, acoustic features, and context bundles before invoking the existing annotators; metadata titles/descriptions remain auxiliary evidence and cannot establish affect alone.
6. Keep the blind 50-video human evaluation as the next validation milestone before deciding the full annotation workflow. New categories and language groups need representation in later validation.

The current annotation code uses MLX for Qwen video inference and Whisper preprocessing; running those stages on Windows still requires a backend port.
