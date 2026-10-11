"""Resumably detect spoken language for YouTube Shorts with Whisper."""
from ataraxia.runtime.config import project_root

import argparse
import csv
import json
import math
import random
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import mlx.core as mx
from mlx_whisper.audio import (
    N_FRAMES,
    N_SAMPLES,
    log_mel_spectrogram,
    pad_or_trim,
)
from mlx_whisper.load_models import load_model
from tqdm import tqdm


BASE_DIR = project_root()
DEFAULT_DATASET_DIR = BASE_DIR / "data" / "youtube_shorts"
MODEL_ID = "mlx-community/whisper-large-v3-turbo"
SCAN_METHOD = "whisper_language_id_first_30s"
TARGET_LANGUAGES = {"en", "hi", "ur"}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Detect spoken language for normalized YouTube Shorts records. "
            "Results are checkpointed after every video."
        )
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Audit at most N metadata rows; zero selects every row.",
    )
    parser.add_argument(
        "--minimum-confidence",
        type=float,
        default=0.80,
        help="Below this confidence, mark the result for human review.",
    )
    parser.add_argument(
        "--retry-errors",
        action="store_true",
        help="Retry checkpointed download and scan errors.",
    )
    parser.add_argument(
        "--keep-temporary-audio",
        action="store_true",
        help="Keep downloaded language-audit audio instead of deleting it.",
    )
    parser.add_argument(
        "--target-english",
        type=int,
        default=0,
        help="Stop once this many eligible English candidates are available.",
    )
    parser.add_argument(
        "--target-hindi-urdu",
        type=int,
        default=0,
        help="Stop once this many eligible Hindi/Urdu candidates are available.",
    )
    parser.add_argument(
        "--maximum-horizontal-fraction",
        type=float,
        default=0.30,
    )
    parser.add_argument(
        "--shuffle-seed",
        type=int,
        default=42,
        help="Deterministically randomize scan order when quotas are used.",
    )
    parser.add_argument(
        "--prefilter-manifest",
        type=Path,
        default=None,
        help=(
            "Metadata-language prefilter CSV. If omitted, the default "
            "prefilter is used automatically when it exists."
        ),
    )
    parser.add_argument(
        "--include-likely-non-target",
        action="store_true",
        help="Also audit metadata rows guessed to be non-target languages.",
    )
    return parser.parse_args()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_checkpoint(path):
    completed = {}
    if not path.exists():
        return completed

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            result = json.loads(line)
            completed[result["video_id"]] = result
        except (json.JSONDecodeError, KeyError):
            continue
    return completed


def append_checkpoint(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False) + "\n")


def local_video_path(row, videos_dir):
    preferred = videos_dir / f"{row['assigned_id']}.mp4"
    if preferred.exists() and preferred.stat().st_size > 0:
        return preferred

    configured = str(row.get("file_path", "")).strip()
    if configured:
        candidate = BASE_DIR / configured
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def download_audio_sample(row, temporary_root):
    video_id = row["assigned_id"]
    video_dir = temporary_root / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    output_template = video_dir / "audio.%(ext)s"

    result = subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "--no-overwrites",
            "--download-sections",
            "*0-30",
            "-f",
            "bestaudio/best",
            "-o",
            str(output_template),
            str(row["source_url"]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or "yt-dlp failed")

    candidates = [
        path
        for path in video_dir.iterdir()
        if path.is_file() and not path.name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        raise FileNotFoundError("yt-dlp produced no usable audio file")
    return max(candidates, key=lambda path: path.stat().st_size)


def detect_language(media_path, model):
    mel = log_mel_spectrogram(
        str(media_path),
        n_mels=model.dims.n_mels,
        padding=N_SAMPLES,
    )
    mel_segment = pad_or_trim(
        mel,
        N_FRAMES,
        axis=-2,
    ).astype(mx.float16)
    _, probabilities = model.detect_language(mel_segment)
    language, confidence = max(
        probabilities.items(),
        key=lambda item: item[1],
    )
    return language or "unknown", float(confidence)


def orientation_from_dimensions(width, height):
    width = int(width or 0)
    height = int(height or 0)
    if width <= 0 or height <= 0:
        raise ValueError("Missing usable video dimensions")
    if height > width:
        return width, height, "vertical"
    if width > height:
        return width, height, "horizontal"
    return width, height, "square"


def probe_orientation(row, local_video):
    if local_video is not None:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height:stream_tags=rotate:stream_side_data=rotation",
                "-of",
                "json",
                str(local_video),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        stream = json.loads(result.stdout)["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        rotation = int(stream.get("tags", {}).get("rotate", 0) or 0)
        for side_data in stream.get("side_data_list", []):
            if side_data.get("rotation") is not None:
                rotation = int(side_data["rotation"])
        if abs(rotation) % 180 == 90:
            width, height = height, width
        return orientation_from_dimensions(width, height)

    result = subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "--skip-download",
            "--dump-single-json",
            str(row["source_url"]),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or "orientation probe failed")

    info = json.loads(result.stdout)
    width = info.get("width")
    height = info.get("height")
    if not width or not height:
        video_formats = [
            item
            for item in info.get("formats", [])
            if item.get("vcodec") not in (None, "none")
            and item.get("width")
            and item.get("height")
        ]
        if not video_formats:
            raise ValueError("YouTube metadata contains no video dimensions")
        best = max(
            video_formats,
            key=lambda item: int(item["width"]) * int(item["height"]),
        )
        width = best["width"]
        height = best["height"]
    return orientation_from_dimensions(width, height)


def audit_row(
    row,
    model,
    videos_dir,
    temporary_root,
    minimum_confidence,
    keep_temporary_audio,
):
    video_id = row["assigned_id"]
    downloaded = False
    existing_video = local_video_path(row, videos_dir)

    try:
        media_path = existing_video
        if media_path is None:
            media_path = download_audio_sample(row, temporary_root)
            downloaded = True

        language, confidence = detect_language(media_path, model)
        width = ""
        height = ""
        orientation = ""

        if confidence < minimum_confidence:
            status = "review_low_confidence"
        elif language in TARGET_LANGUAGES:
            try:
                width, height, orientation = probe_orientation(
                    row,
                    existing_video,
                )
                status = "keep_target_language"
            except Exception as error:
                status = "orientation_error"
                orientation_error = f"{type(error).__name__}: {error}"
        else:
            status = "non_target_language"

        return {
            "video_id": video_id,
            "detected_language": language,
            "language_confidence": confidence,
            "status": status,
            "display_width": width,
            "display_height": height,
            "orientation": orientation,
            "scan_method": SCAN_METHOD,
            "used_existing_video": not downloaded,
            "scanned_at_utc": datetime.now(timezone.utc).isoformat(),
            "error": locals().get("orientation_error", ""),
        }
    except Exception as error:
        return {
            "video_id": video_id,
            "detected_language": "unknown",
            "language_confidence": "",
            "status": "scan_error",
            "display_width": "",
            "display_height": "",
            "orientation": "",
            "scan_method": SCAN_METHOD,
            "used_existing_video": not downloaded,
            "scanned_at_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(error).__name__}: {error}",
        }
    finally:
        if downloaded and not keep_temporary_audio:
            shutil.rmtree(temporary_root / video_id, ignore_errors=True)


def write_manifest(path, metadata_rows, results):
    output_rows = []
    for row in metadata_rows:
        result = results.get(row["assigned_id"])
        if result is not None:
            output_rows.append({**row, **result})

    extra_fields = [
        "video_id",
        "detected_language",
        "language_confidence",
        "status",
        "display_width",
        "display_height",
        "orientation",
        "scan_method",
        "used_existing_video",
        "scanned_at_utc",
        "error",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(metadata_rows[0]) + extra_fields,
        )
        writer.writeheader()
        writer.writerows(output_rows)
    temporary_path.replace(path)


def write_counts(path, results, announce=True):
    language_counts = Counter(
        result["detected_language"] for result in results.values()
    )
    status_counts = Counter(
        result["status"] for result in results.values()
    )

    rows = [
        {"detected_language": language, "count": count}
        for language, count in language_counts.most_common()
    ]
    temporary_path = path.with_name(path.name + ".tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["detected_language", "count"],
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(path)

    if announce:
        print("\nDetected languages:")
        for row in rows:
            print(f"  {row['detected_language']}: {row['count']}")
        print("Statuses:")
        for status, count in status_counts.most_common():
            print(f"  {status}: {count}")


def quotas_reached(
    results,
    target_english,
    target_hindi_urdu,
    maximum_horizontal_fraction,
):
    if target_english == 0 and target_hindi_urdu == 0:
        return False

    eligible = [
        result
        for result in results.values()
        if result.get("status") == "keep_target_language"
        and result.get("orientation") in {"vertical", "horizontal"}
    ]
    english = sum(
        result.get("detected_language") == "en" for result in eligible
    )
    hindi_urdu = sum(
        result.get("detected_language") in {"hi", "ur"}
        for result in eligible
    )
    total_target = target_english + target_hindi_urdu
    required_vertical = math.ceil(
        total_target * (1.0 - maximum_horizontal_fraction)
    )
    english_vertical = sum(
        result.get("detected_language") == "en"
        and result.get("orientation") == "vertical"
        for result in eligible
    )
    hindi_urdu_vertical = sum(
        result.get("detected_language") in {"hi", "ur"}
        and result.get("orientation") == "vertical"
        for result in eligible
    )
    maximum_selectable_vertical = (
        min(english_vertical, target_english)
        + min(hindi_urdu_vertical, target_hindi_urdu)
    )
    return (
        english >= target_english
        and hindi_urdu >= target_hindi_urdu
        and maximum_selectable_vertical >= required_vertical
    )


def order_from_prefilter(
    path,
    include_likely_non_target,
    seed,
):
    rows = read_csv(path)
    allowed = {
        "hindi_urdu_candidate",
        "english_candidate",
        "uncertain_candidate",
    }
    if include_likely_non_target:
        allowed.add("likely_non_target")

    rows = [
        row for row in rows if row.get("prefilter_status") in allowed
    ]
    random.Random(seed).shuffle(rows)

    def sort_key(row):
        try:
            priority = int(row.get("audit_priority", 99))
        except (TypeError, ValueError):
            priority = 99
        try:
            target_score = float(row.get("target_score", 0))
        except (TypeError, ValueError):
            target_score = 0.0
        return priority, -target_score

    rows.sort(key=sort_key)
    return rows


def main():
    args = parse_args()
    if args.limit < 0:
        raise ValueError("--limit cannot be negative")
    if args.target_english < 0 or args.target_hindi_urdu < 0:
        raise ValueError("Language targets cannot be negative")
    if not 0 <= args.minimum_confidence <= 1:
        raise ValueError("--minimum-confidence must be between 0 and 1")
    if not 0 <= args.maximum_horizontal_fraction <= 1:
        raise ValueError(
            "--maximum-horizontal-fraction must be between 0 and 1"
        )
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp is required but was not found")

    dataset_dir = args.dataset_dir.resolve()
    metadata_path = dataset_dir / "metadata.csv"
    videos_dir = dataset_dir / "videos"
    checkpoint_path = dataset_dir / "language_scan.jsonl"
    manifest_path = dataset_dir / "language_manifest.csv"
    counts_path = dataset_dir / "language_counts.csv"
    temporary_root = dataset_dir / "language_audio_tmp"
    default_prefilter_path = dataset_dir / "metadata_language_prefilter.csv"

    if not metadata_path.exists():
        raise FileNotFoundError(
            f"Missing {metadata_path}. Run load_youtube_shorts.py first."
        )

    metadata_rows = read_csv(metadata_path)
    prefilter_path = args.prefilter_manifest
    if prefilter_path is None and default_prefilter_path.exists():
        prefilter_path = default_prefilter_path

    if prefilter_path is not None:
        prefilter_path = prefilter_path.resolve()
        if not prefilter_path.exists():
            raise FileNotFoundError(
                f"Metadata prefilter does not exist: {prefilter_path}"
            )
        scan_rows = order_from_prefilter(
            prefilter_path,
            args.include_likely_non_target,
            args.shuffle_seed,
        )
        print(f"Using metadata prefilter: {prefilter_path}")
    else:
        scan_rows = list(metadata_rows)

    if (
        prefilter_path is None
        and (args.target_english or args.target_hindi_urdu)
    ):
        random.Random(args.shuffle_seed).shuffle(scan_rows)
    if args.limit:
        scan_rows = scan_rows[: args.limit]
    if not scan_rows:
        raise ValueError("No metadata rows were selected")

    results = load_checkpoint(checkpoint_path)
    selected_ids = {row["assigned_id"] for row in scan_rows}
    results = {
        video_id: result
        for video_id, result in results.items()
        if video_id in selected_ids
    }
    if args.retry_errors:
        results = {
            video_id: result
            for video_id, result in results.items()
            if result.get("status")
            not in {"scan_error", "orientation_error"}
        }

    pending_rows = [
        row
        for row in scan_rows
        if row["assigned_id"] not in results
        or (
            results[row["assigned_id"]].get("status")
            == "keep_target_language"
            and not results[row["assigned_id"]].get("orientation")
        )
    ]

    print(f"Rows selected: {len(scan_rows):,}")
    print(f"Already scanned: {len(results):,}")
    print(f"Pending: {len(pending_rows):,}")

    model = None
    if pending_rows:
        model = load_model(MODEL_ID, dtype=mx.float16)

    for row in tqdm(pending_rows, unit="video"):
        if quotas_reached(
            results,
            args.target_english,
            args.target_hindi_urdu,
            args.maximum_horizontal_fraction,
        ):
            print("Requested language/orientation candidate quotas reached.")
            break

        result = audit_row(
            row,
            model,
            videos_dir,
            temporary_root,
            args.minimum_confidence,
            args.keep_temporary_audio,
        )
        results[result["video_id"]] = result
        append_checkpoint(checkpoint_path, result)

        if len(results) % 500 == 0:
            write_manifest(manifest_path, metadata_rows, results)
            write_counts(counts_path, results, announce=False)

    write_manifest(manifest_path, metadata_rows, results)
    write_counts(counts_path, results)

    if (
        (args.target_english or args.target_hindi_urdu)
        and not quotas_reached(
            results,
            args.target_english,
            args.target_hindi_urdu,
            args.maximum_horizontal_fraction,
        )
    ):
        print(
            "WARNING: Requested quotas were not reached from the selected "
            "candidate pool. Review counts or rerun with "
            "--include-likely-non-target."
        )

    print(f"\nScanned: {len(results):,}/{len(scan_rows):,}")
    print(f"Manifest: {manifest_path}")
    print(f"Counts: {counts_path}")


if __name__ == "__main__":
    main()
