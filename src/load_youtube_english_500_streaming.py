"""Check metadata and immediately download eligible English YouTube Shorts."""

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path

from tqdm import tqdm

from download_youtube_metadata_shortlist import (
    append_jsonl,
    cookie_arguments,
    download_video,
    load_checkpoint,
    probe_orientation,
    write_manifest,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = BASE_DIR / "data" / "youtube_shorts"
TARGET_TOTAL = 500
CATEGORY_QUOTAS = {
    "Entertainment": 120,
    "People & Blogs": 92,
    "Comedy": 46,
    "Education": 53,
    "Science & Technology": 29,
    "Sports": 29,
    "Gaming": 21,
    "How-to & Style": 17,
    "Music": 17,
    "News & Politics": 14,
    "Pets & Animals": 10,
    "Film & Animation": 18,
    "Travel & Events": 17,
    "Cars & Vehicles": 17,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Check metadata row by row and immediately download videos that "
            "fit the English 500-video quotas."
        )
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--minimum-english-score", type=float, default=0.65)
    parser.add_argument("--minimum-duration", type=float, default=10.0)
    parser.add_argument("--maximum-duration", type=float, default=90.0)
    parser.add_argument("--maximum-horizontal-fraction", type=float, default=0.30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="Retry candidates that failed on a previous run.",
    )
    parser.add_argument(
        "--retry-probe-errors",
        action="store_true",
        help="Retry candidates whose orientation probe previously failed.",
    )
    cookie_group = parser.add_mutually_exclusive_group()
    cookie_group.add_argument("--cookies-from-browser")
    cookie_group.add_argument("--cookies-file", type=Path)
    return parser.parse_args()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def numeric(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_downloaded(videos_dir, video_id):
    path = videos_dir / f"{video_id}.mp4"
    return path.exists() and path.stat().st_size > 0


def metadata_matches(row, args):
    return (
        row.get("prefilter_status") == "english_candidate"
        and numeric(row.get("english_score")) >= args.minimum_english_score
        and args.minimum_duration
        <= numeric(row.get("duration"), -1)
        <= args.maximum_duration
        and row.get("category") in CATEGORY_QUOTAS
        and bool(row.get("source_url", "").strip())
    )


def horizontal_is_allowed(horizontal_count, total_count, maximum_fraction):
    return (horizontal_count + 1) / (total_count + 1) <= maximum_fraction


def existing_counts(rows_by_id, videos_dir, orientation_results):
    category_counts = Counter()
    orientation_counts = Counter()
    downloaded_ids = set()
    for video_path in videos_dir.glob("*.mp4"):
        video_id = video_path.stem
        row = rows_by_id.get(video_id)
        if row is None or video_path.stat().st_size <= 0:
            continue
        downloaded_ids.add(video_id)
        category_counts[row["category"]] += 1
        orientation = orientation_results.get(video_id, {}).get(
            "orientation", "unknown"
        )
        orientation_counts[orientation] += 1
    return downloaded_ids, category_counts, orientation_counts


def write_downloaded_metadata(
    path, rows_by_id, downloaded_ids, videos_dir, orientation_results
):
    output = []
    for video_id in sorted(downloaded_ids):
        row = rows_by_id[video_id]
        orientation = orientation_results.get(video_id, {})
        video_path = videos_dir / f"{video_id}.mp4"
        output.append(
            {
                **row,
                "display_width": orientation.get("display_width", ""),
                "display_height": orientation.get("display_height", ""),
                "orientation": orientation.get("orientation", "unknown"),
                "local_path": str(video_path),
                "size_bytes": video_path.stat().st_size,
                "download_status": "downloaded",
            }
        )
    if output:
        write_manifest(path, output)


def main():
    args = parse_args()
    if not 0 <= args.maximum_horizontal_fraction <= 1:
        raise ValueError("Horizontal fraction must be between 0 and 1")
    if args.minimum_duration > args.maximum_duration:
        raise ValueError("Minimum duration cannot exceed maximum duration")

    dataset_dir = args.dataset_dir.resolve()
    source_path = dataset_dir / "metadata_language_prefilter.csv"
    subset_dir = dataset_dir / "english_500"
    videos_dir = subset_dir / "videos"
    orientation_path = subset_dir / "orientation_scan.jsonl"
    failures_path = subset_dir / "download_failures.jsonl"
    events_path = subset_dir / "streaming_load_events.jsonl"
    output_path = subset_dir / "metadata_downloaded.csv"
    cookie_args = cookie_arguments(args.cookies_from_browser, args.cookies_file)

    rows = read_csv(source_path)
    rows_by_id = {row["assigned_id"]: row for row in rows}
    orientation_results = load_checkpoint(orientation_path)
    previous_failures = load_checkpoint(failures_path)
    videos_dir.mkdir(parents=True, exist_ok=True)

    downloaded_ids, category_counts, orientation_counts = existing_counts(
        rows_by_id, videos_dir, orientation_results
    )
    if len(downloaded_ids) > TARGET_TOTAL:
        raise RuntimeError(
            f"The English folder already contains {len(downloaded_ids)} videos; "
            f"the configured target is {TARGET_TOTAL}."
        )

    candidates = [row for row in rows if metadata_matches(row, args)]
    random.Random(args.seed).shuffle(candidates)
    print(f"Metadata candidates available: {len(candidates):,}")
    print(f"Already downloaded: {len(downloaded_ids):,}/{TARGET_TOTAL}")

    progress = tqdm(
        total=TARGET_TOTAL,
        initial=len(downloaded_ids),
        unit="video",
        desc="English videos",
    )
    try:
        for row in candidates:
            if len(downloaded_ids) >= TARGET_TOTAL:
                break

            video_id = row["assigned_id"]
            category = row["category"]
            if video_id in downloaded_ids:
                continue
            if category_counts[category] >= CATEGORY_QUOTAS[category]:
                continue
            if video_id in previous_failures and not args.retry_failures:
                continue

            probe = orientation_results.get(video_id)
            if (
                probe is not None
                and probe.get("probe_status") == "error"
                and args.retry_probe_errors
            ):
                probe = None
            if probe is None:
                try:
                    width, height, orientation = probe_orientation(row, cookie_args)
                    probe = {
                        "assigned_id": video_id,
                        "display_width": width,
                        "display_height": height,
                        "orientation": orientation,
                        "probe_status": "complete",
                        "probe_error": "",
                    }
                except Exception as error:
                    probe = {
                        "assigned_id": video_id,
                        "display_width": "",
                        "display_height": "",
                        "orientation": "unknown",
                        "probe_status": "error",
                        "probe_error": f"{type(error).__name__}: {error}",
                    }
                orientation_results[video_id] = probe
                append_jsonl(orientation_path, probe)

            orientation = probe.get("orientation", "unknown")
            if orientation not in {"vertical", "horizontal"}:
                continue
            if orientation == "horizontal" and not horizontal_is_allowed(
                orientation_counts["horizontal"],
                len(downloaded_ids),
                args.maximum_horizontal_fraction,
            ):
                continue

            progress.set_postfix_str(category[:24])
            failure = download_video(row, videos_dir, cookie_args)
            if failure is not None:
                previous_failures[video_id] = failure
                append_jsonl(failures_path, failure)
                append_jsonl(
                    events_path,
                    {
                        "assigned_id": video_id,
                        "category": category,
                        "orientation": orientation,
                        "result": "failed",
                    },
                )
                continue

            if is_downloaded(videos_dir, video_id):
                downloaded_ids.add(video_id)
                category_counts[category] += 1
                orientation_counts[orientation] += 1
                append_jsonl(
                    events_path,
                    {
                        "assigned_id": video_id,
                        "category": category,
                        "orientation": orientation,
                        "result": "downloaded",
                    },
                )
                progress.update(1)
    finally:
        progress.close()
        write_downloaded_metadata(
            output_path,
            rows_by_id,
            downloaded_ids,
            videos_dir,
            orientation_results,
        )

    print(f"Downloaded total: {len(downloaded_ids):,}/{TARGET_TOTAL}")
    for category, quota in CATEGORY_QUOTAS.items():
        print(f"  {category}: {category_counts[category]}/{quota}")
    horizontal = orientation_counts["horizontal"]
    horizontal_percentage = (
        horizontal / len(downloaded_ids) * 100 if downloaded_ids else 0
    )
    print(f"Orientations: {dict(orientation_counts)}")
    print(f"Horizontal percentage: {horizontal_percentage:.2f}%")
    print(f"Metadata: {output_path}")

    shortages = {
        category: quota - category_counts[category]
        for category, quota in CATEGORY_QUOTAS.items()
        if category_counts[category] < quota
    }
    if shortages:
        print(f"Unfilled category quotas: {shortages}")
        print("Rerun with --retry-failures if fresh candidates were exhausted.")


if __name__ == "__main__":
    main()
