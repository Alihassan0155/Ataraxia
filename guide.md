# Ataraxia developer guide

The active study uses Gemini and Qwen3-VL. Molmo is intentionally excluded.

## Active structure

- `data/FineVideo/`: filtered 858-video source dataset
- `data/FineVideo/audit/`: preserved filtering audit records
- `data/FineVideo/preprocessed/`: 858 audio, transcript, and context bundles
- `data/youtube_shorts/`: 58,868 source metadata rows; 953 shortlist video files
- `data/youtube_shorts/english_500/`: 500 downloaded vertical videos selected using metadata language scores (speech language is not yet verified)
- `pilot_50_reels_30h/`: 50-video pilot (35 vertical, 15 horizontal)
- `outputs/reels_30h/gemini/`: Gemini pilot annotations
- `outputs/reels_30h/qwen/`: Qwen pilot annotations
- `annotation_rules.txt`: short human-annotation guide

Only English, Urdu, and Hindi are allowed. The current dataset contains 857
English videos and one Urdu video. The orientation mix is 601 vertical and 257
horizontal videos.

## Run preprocessing

```bash
source .venv/bin/activate
python src/preprocess_pilot.py
```

The default pilot is `pilot_50_reels_30h`. It can be overridden with
`ATARAXIA_PILOT_DIR`.

## Run Gemini

```bash
source .venv/bin/activate
python src/annotate_gemini.py
```

## Run Qwen

```bash
source .venv-qwen-mlx/bin/activate
python src/annotate_qwen.py
```

## Run both smoke tests

```bash
source .venv/bin/activate
python src/run_all_parallel.py
```

By default, annotations are written under `outputs/reels_30h/`. Both models use
the same transcript, acoustic features, and low-priority metadata caption from
the matching context JSON.

## Preprocess the complete dataset

The full-dataset preprocessor is resumable. Existing valid contexts are skipped,
and existing audio or transcripts are reused when a context is incomplete.

Test the first two videos:

```bash
source .venv/bin/activate
python src/preprocess_full_dataset.py --limit 2
```

All 858 contexts are currently complete. To resume or regenerate missing evidence:

```bash
source .venv/bin/activate
python src/preprocess_full_dataset.py
```

Artifacts are stored under `data/FineVideo/preprocessed/`. Check `status.json`
for progress and `failures.jsonl` for videos that need to be retried. Rerun the
same command to resume; use `--force` only when intentional regeneration is
required.

## Audit YouTube Shorts languages

First prepare the normalized YouTube metadata:

```bash
source .venv/bin/activate
python src/load_youtube_shorts.py
```

Test language detection on ten records:

```bash
python src/audit_youtube_languages.py --limit 10
```

Then audit every eligible record:

```bash
python src/audit_youtube_languages.py
```

For the constrained YouTube sample, scan in a reproducibly shuffled order and
stop once there are enough language and orientation candidates. First rank the
records using metadata only:

```bash
python src/prefilter_youtube_languages.py
```

Then run Whisper only on likely target-language and uncertain candidates:

```bash
python src/audit_youtube_languages.py \
  --target-english 800 \
  --target-hindi-urdu 1300 \
  --maximum-horizontal-fraction 0.30
```

Build the 2,100-video selection without downloading full videos:

```bash
python src/build_youtube_language_sample.py
```

After reviewing `data/youtube_shorts/selected_metadata.csv`, download only the
selected videos:

```bash
python src/build_youtube_language_sample.py --download
```

The audit is resumable and downloads only temporary audio when a local video is
unavailable. Results are saved in `data/youtube_shorts/language_manifest.csv`,
with totals in `language_counts.csv`. Temporary audio is deleted after each
scan. Use `--retry-errors` to retry failed records.

### Metadata-only Hindi/Urdu shortlist

To skip Whisper, build the capped metadata shortlist:

```bash
python src/filter_youtube_metadata_candidates.py
```

Test orientation probing without downloading videos:

```bash
python src/download_youtube_metadata_shortlist.py --limit 10 --probe-only
```

Then probe all candidates, enforce the 30% horizontal maximum, and download the
accepted videos:

```bash
python src/download_youtube_metadata_shortlist.py
```

If YouTube requests sign-in or bot verification, first open YouTube in your
browser, then resume using that browser's cookies:

```bash
python src/download_youtube_metadata_shortlist.py --cookies-from-browser chrome
```

The command is resumable. It saves videos under `data/youtube_shorts/videos/`
and writes the final decisions to
`data/youtube_shorts/metadata_candidate_download_manifest.csv`.

## Move to another computer and prepare Git

Snapshot checked on 2026-10-04. This directory currently has no `.git` repository.
The existing environments use Python 3.11 on macOS Apple Silicon. Qwen invokes
`mlx_vlm.generate --video` with `mlx-community/Qwen3-VL-8B-Instruct-4bit`;
Whisper also uses MLX. A Windows/Linux PC requires a backend port before these
scripts can run there. Gemini and metadata utilities do not themselves require MLX,
but the complete requirements snapshots include it.

`requirements.txt` records every package from `.venv`, including transitive
packages. `requirements-qwen-mlx.txt` records the separate Qwen environment:
its MLX-VLM is 0.7.0 versus 0.7.3 in the main environment. Keep these environments
separate. Pins describe installed versions; a clean installation on the destination
has not been tested. Do not copy virtual environments between computers.

On an Apple Silicon destination, install Python 3.11 and FFmpeg (which supplies
both `ffmpeg` and `ffprobe`) using your system package manager, then run:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
python3.11 -m venv .venv-qwen-mlx
.venv-qwen-mlx/bin/python -m pip install -r requirements-qwen-mlx.txt
cp .env.example .env
```

Fill in your Gemini key locally. The code currently specifies `gemini-3.8-flash`;
confirm access with your account before making a paid annotation run. Model
weights are downloaded separately into the Hugging Face cache. YouTube downloads
use yt-dlp; some extraction paths may also require its supported JavaScript runtime.

Git includes code, guides, requirements, CSV metadata and audits, JSON/JSONL
study records, transcripts, shared contexts, and model annotations. `.gitignore`
excludes credentials, browser cookies, media, environments, model weights, caches,
and run logs. Media includes files above common Git hosting size limits.

Transfer the ignored media separately using an external drive or private storage,
keeping these directory paths intact:

- `data/FineVideo/videos/`
- `data/FineVideo/preprocessed/audio/`
- `pilot_50_reels_30h/videos/` and `pilot_50_reels_30h/audio/`
- `data/youtube_shorts/videos/`
- `data/youtube_shorts/english_500/videos/`

The current working directory is approximately 22 GB including environments;
`data/` is approximately 19 GB. Transfer credentials privately, or create new keys.
Some YouTube audit/status records contain absolute `local_path` values from the
original machine. Preserve those historical records; verify files under the new
project root and rerun the appropriate resumable downloader to refresh status.
FineVideo and pilot metadata use relative video paths.

Before pushing, initialize Git and inspect exactly what will be staged:

```bash
git init
git add --dry-run .
git add .
git diff --cached --stat
git diff --cached --name-only
```

Review the staged content, then commit and add your repository remote:

```bash
git commit -m "Prepare Ataraxia pipeline and study handoff"
git branch -M main
git remote add origin <YOUR_REPOSITORY_URL>
git push -u origin main
```

On the destination, restore the media and check the dataset counts before running
preprocessing. Existing valid contexts and annotations are skipped, so the default
parallel smoke test may perform no new inference on this completed pilot. Use a
separate output directory with `ATARAXIA_LIMIT=2` when intentionally testing fresh
annotations; `run_all_parallel.py` hardcodes the original output directory and limit.

## Current YouTube English sample workflow

```bash
python src/filter_youtube_english_500.py --help
python src/download_youtube_english_500.py --help
python src/load_youtube_english_500_streaming.py --help
python src/extract_youtube_video_info.py --help
```

The English sample has 633 candidate records and 500 downloaded records, all
vertical. Metadata language scores are candidate selection evidence, not verified
spoken-language labels. The Hindi/Urdu shortlist manifest has 1,316 rows, while
the download status has 952 downloaded records and the media directory has 953
files; reconcile the extra file before treating this as a finalized dataset.
