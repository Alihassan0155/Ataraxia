"""Create resumable shared evidence bundles for the 858-video dataset."""

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import mlx_whisper
import opensmile
import pandas as pd
from tqdm import tqdm


BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_DIR = BASE_DIR / "data" / "FineVideo"
DEFAULT_METADATA_PATH = DATASET_DIR / "metadata.csv"
DEFAULT_VIDEOS_DIR = DATASET_DIR / "videos"
DEFAULT_OUTPUT_DIR = DATASET_DIR / "preprocessed"

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
CAPTION_COLUMNS = (
    "caption",
    "video_caption",
    "description",
    "text",
    "title",
)
ACOUSTIC_KEYS = (
    "mean_loudness",
    "loudness_variability",
    "mean_pitch",
    "pitch_variability",
    "spectral_flux",
    "sound_level_db",
)


smile = opensmile.Smile(
    feature_set=opensmile.FeatureSet.eGeMAPSv02,
    feature_level=opensmile.FeatureLevel.Functionals,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Extract audio, transcribe speech, calculate acoustic features, "
            "and create one shared context JSON per filtered video."
        )
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=DEFAULT_METADATA_PATH,
    )
    parser.add_argument(
        "--videos-dir",
        type=Path,
        default=DEFAULT_VIDEOS_DIR,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N rows. Zero processes every row.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate existing audio, transcripts, and contexts.",
    )
    return parser.parse_args()


def atomic_write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(text, encoding="utf-8")
    temporary_path.replace(path)


def find_caption_column(columns):
    column_map = {str(column).lower(): column for column in columns}
    for candidate in CAPTION_COLUMNS:
        if candidate in column_map:
            return column_map[candidate]
    return None


def resolve_video_path(row, videos_dir):
    video_id = str(row["assigned_id"]).strip()

    standard_path = videos_dir / f"{video_id}.mp4"
    if standard_path.exists():
        return standard_path

    configured_value = str(row.get("file_path", "")).strip()
    if configured_value:
        configured_path = Path(configured_value)
        candidates = [videos_dir / configured_path.name]
        if configured_path.is_absolute():
            candidates.insert(0, configured_path)
        else:
            candidates.insert(0, BASE_DIR / configured_path)

        for candidate in candidates:
            if candidate.exists():
                return candidate

    raise FileNotFoundError(f"Video file not found for {video_id}")


def is_valid_context(path, expected_video_id):
    if not path.exists():
        return False

    try:
        context = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    acoustic = context.get("acoustic_features")
    return (
        context.get("video_id") == expected_video_id
        and isinstance(context.get("transcript"), str)
        and isinstance(acoustic, dict)
        and all(key in acoustic for key in ACOUSTIC_KEYS)
        and isinstance(context.get("metadata_caption"), str)
        and context.get("caption_priority") == "low"
    )


def extract_audio(video_path, audio_path, force=False):
    if audio_path.exists() and not force:
        return

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = audio_path.with_name(f"{audio_path.stem}.tmp.wav")
    temporary_path.unlink(missing_ok=True)

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(temporary_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        temporary_path.replace(audio_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def transcribe_audio(audio_path, transcript_path, force=False):
    if transcript_path.exists() and not force:
        return transcript_path.read_text(encoding="utf-8").strip()

    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=WHISPER_MODEL,
    )
    transcript = str(result.get("text", "")).strip()
    atomic_write_text(transcript_path, transcript)
    return transcript


def find_acoustic_feature(features, fragments):
    for column in features.index:
        column_name = str(column).lower()
        if all(fragment.lower() in column_name for fragment in fragments):
            try:
                return round(float(features[column]), 4)
            except (TypeError, ValueError):
                return None
    return None


def extract_acoustic_summary(audio_path):
    features = smile.process_file(str(audio_path)).iloc[0]
    return {
        "mean_loudness": find_acoustic_feature(
            features,
            ("loudness", "amean"),
        ),
        "loudness_variability": find_acoustic_feature(
            features,
            ("loudness", "stddev"),
        ),
        "mean_pitch": find_acoustic_feature(
            features,
            ("f0semitone", "amean"),
        ),
        "pitch_variability": find_acoustic_feature(
            features,
            ("f0semitone", "stddev"),
        ),
        "spectral_flux": find_acoustic_feature(
            features,
            ("spectralflux", "amean"),
        ),
        "sound_level_db": find_acoustic_feature(
            features,
            ("equivalentsoundlevel",),
        ),
    }


def append_failure(path, video_id, error):
    failure = {
        "video_id": video_id,
        "failed_at_utc": datetime.now(timezone.utc).isoformat(),
        "error_type": type(error).__name__,
        "error": str(error),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(failure, ensure_ascii=False) + "\n")


def write_status(
    path,
    selected,
    completed_this_run,
    skipped_existing,
    failed_this_run,
    completed_total,
    last_video_id,
):
    status = {
        "selected_videos": selected,
        "completed_this_run": completed_this_run,
        "skipped_existing": skipped_existing,
        "failed_this_run": failed_this_run,
        "completed_contexts_total": completed_total,
        "last_video_id": last_video_id,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_text(
        path,
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
    )


def main():
    args = parse_args()
    if args.limit < 0:
        raise ValueError("--limit cannot be negative")

    metadata_path = args.metadata.resolve()
    videos_dir = args.videos_dir.resolve()
    output_dir = args.output_dir.resolve()
    audio_dir = output_dir / "audio"
    transcript_dir = output_dir / "transcripts"
    context_dir = output_dir / "context"
    failure_log = output_dir / "failures.jsonl"
    status_path = output_dir / "status.json"

    metadata = pd.read_csv(metadata_path)
    if "assigned_id" not in metadata.columns:
        raise ValueError("Metadata must contain an assigned_id column")
    if metadata["assigned_id"].duplicated().any():
        raise ValueError("Metadata contains duplicate assigned_id values")

    if args.limit:
        metadata = metadata.head(args.limit)

    caption_column = find_caption_column(metadata.columns)
    for directory in (audio_dir, transcript_dir, context_dir):
        directory.mkdir(parents=True, exist_ok=True)

    completed_this_run = 0
    skipped_existing = 0
    failed_this_run = 0
    last_video_id = None

    print(f"Metadata: {metadata_path}")
    print(f"Videos: {videos_dir}")
    print(f"Output: {output_dir}")
    print(f"Selected videos: {len(metadata)}")
    print(f"Caption column: {caption_column or 'none'}")

    for _, row in tqdm(
        metadata.iterrows(),
        total=len(metadata),
        unit="video",
    ):
        video_id = str(row["assigned_id"]).strip()
        last_video_id = video_id
        context_path = context_dir / f"{video_id}.json"

        if not args.force and is_valid_context(context_path, video_id):
            skipped_existing += 1
            completed_total = sum(1 for _ in context_dir.glob("*.json"))
            write_status(
                status_path,
                len(metadata),
                completed_this_run,
                skipped_existing,
                failed_this_run,
                completed_total,
                last_video_id,
            )
            continue

        audio_path = audio_dir / f"{video_id}.wav"
        transcript_path = transcript_dir / f"{video_id}.txt"

        try:
            video_path = resolve_video_path(row, videos_dir)
            extract_audio(video_path, audio_path, force=args.force)
            transcript = transcribe_audio(
                audio_path,
                transcript_path,
                force=args.force,
            )
            acoustic_features = extract_acoustic_summary(audio_path)

            caption = ""
            if caption_column is not None:
                caption_value = row.get(caption_column, "")
                if pd.notna(caption_value):
                    caption = str(caption_value).strip()

            context = {
                "video_id": video_id,
                "transcript": transcript,
                "acoustic_features": acoustic_features,
                "metadata_caption": caption,
                "caption_priority": "low",
            }
            atomic_write_text(
                context_path,
                json.dumps(context, ensure_ascii=False, indent=2) + "\n",
            )
            completed_this_run += 1
        except Exception as error:
            failed_this_run += 1
            append_failure(failure_log, video_id, error)
            tqdm.write(
                f"FAILED {video_id}: {type(error).__name__}: {error}"
            )
        finally:
            completed_total = sum(1 for _ in context_dir.glob("*.json"))
            write_status(
                status_path,
                len(metadata),
                completed_this_run,
                skipped_existing,
                failed_this_run,
                completed_total,
                last_video_id,
            )

    print(
        "Finished: "
        f"completed={completed_this_run}, "
        f"skipped={skipped_existing}, "
        f"failed={failed_this_run}"
    )
    if failed_this_run:
        print(f"Failure log: {failure_log}")


if __name__ == "__main__":
    main()
