"""Load and normalize the JamilAL01 YouTube Shorts dataset metadata."""

import argparse
import json
import subprocess
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = BASE_DIR / "data" / "youtube_shorts"
METADATA_URL = (
    "https://raw.githubusercontent.com/JamilAL01/"
    "YouTube-Shorts-Dataset/main/shorts_metadata.json"
)
SOURCE_DATASET = "JamilAL01/YouTube-Shorts-Dataset"


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Download, filter, and normalize YouTube Shorts metadata. "
            "Video downloading is disabled unless --download-limit is set."
        )
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
        help="Destination for raw metadata, normalized metadata, and videos.",
    )
    parser.add_argument(
        "--minimum-duration",
        type=float,
        default=10.0,
    )
    parser.add_argument(
        "--maximum-duration",
        type=float,
        default=90.0,
    )
    parser.add_argument(
        "--download-limit",
        type=int,
        default=0,
        help="Download the first N filtered videos; zero downloads none.",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help=(
            "Restrict optional downloads to a category. Repeat this option "
            "to include multiple categories."
        ),
    )
    parser.add_argument(
        "--refresh-metadata",
        action="store_true",
        help="Download raw metadata again even when it already exists.",
    )
    return parser.parse_args()


def download_raw_metadata(path, refresh=False):
    if path.exists() and not refresh:
        print(f"Using existing raw metadata: {path}")
        return

    response = requests.get(METADATA_URL, timeout=60)
    response.raise_for_status()

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_bytes(response.content)
    temporary_path.replace(path)
    print(f"Saved raw metadata: {path}")


def load_raw_metadata(path):
    with path.open(encoding="utf-8") as handle:
        records = json.load(handle)

    if not isinstance(records, list):
        raise ValueError("Expected the raw metadata to contain a JSON list")

    frame = pd.DataFrame(records)
    required_columns = {"duration", "short_url", "category_name"}
    missing = sorted(required_columns - set(frame.columns))
    if missing:
        raise ValueError(f"Raw metadata is missing columns: {missing}")
    return frame


def normalize_metadata(frame, minimum_duration, maximum_duration):
    if minimum_duration < 0:
        raise ValueError("Minimum duration cannot be negative")
    if maximum_duration < minimum_duration:
        raise ValueError("Maximum duration must be at least the minimum")

    working = frame.copy()
    working["duration"] = pd.to_numeric(
        working["duration"],
        errors="coerce",
    )
    working = working[
        working["duration"].between(
            minimum_duration,
            maximum_duration,
            inclusive="both",
        )
    ].copy()
    working.reset_index(drop=True, inplace=True)

    assigned_ids = [
        f"YT{number:06d}"
        for number in range(1, len(working) + 1)
    ]
    working.insert(0, "assigned_id", assigned_ids)
    working.insert(1, "source_dataset", SOURCE_DATASET)
    working["category"] = working["category_name"]
    working["source_url"] = working["short_url"]
    working["file_path"] = working["assigned_id"].map(
        lambda video_id: (
            f"data/youtube_shorts/videos/{video_id}.mp4"
        )
    )
    return working


def save_csv(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    frame.to_csv(temporary_path, index=False)
    temporary_path.replace(path)


def print_category_summary(frame):
    summary = (
        frame["category"]
        .value_counts(dropna=False)
        .rename_axis("category")
        .reset_index(name="count")
    )
    summary["percentage"] = (
        summary["count"] / len(frame) * 100
    ).round(2)
    print("\nCategory summary:")
    print(summary.to_string(index=False))


def select_download_rows(frame, categories, limit):
    if limit < 0:
        raise ValueError("--download-limit cannot be negative")
    if limit == 0:
        return frame.head(0)

    selected = frame
    if categories:
        requested = {category.casefold() for category in categories}
        selected = selected[
            selected["category"].astype(str).str.casefold().isin(requested)
        ]
        if selected.empty:
            available = sorted(frame["category"].dropna().astype(str).unique())
            raise ValueError(
                "No rows matched the requested categories. "
                f"Available categories: {available}"
            )
    return selected.head(limit)


def download_videos(frame, videos_dir):
    videos_dir.mkdir(parents=True, exist_ok=True)
    failures = []

    for row in tqdm(
        frame.itertuples(index=False),
        total=len(frame),
        unit="video",
    ):
        destination = videos_dir / f"{row.assigned_id}.mp4"
        if destination.exists() and destination.stat().st_size > 0:
            continue

        output_template = videos_dir / f"{row.assigned_id}.%(ext)s"
        result = subprocess.run(
            [
                "yt-dlp",
                "--no-playlist",
                "--no-overwrites",
                "-f",
                "bv*+ba/b",
                "--merge-output-format",
                "mp4",
                "-o",
                str(output_template),
                str(row.source_url),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            failures.append(
                {
                    "assigned_id": row.assigned_id,
                    "source_url": row.source_url,
                    "error": result.stderr[-2000:],
                }
            )

    return failures


def main():
    args = parse_args()
    dataset_dir = args.dataset_dir.resolve()
    raw_metadata_path = dataset_dir / "raw_metadata.json"
    metadata_path = dataset_dir / "metadata.csv"
    category_summary_path = dataset_dir / "category_summary.csv"
    videos_dir = dataset_dir / "videos"
    failures_path = dataset_dir / "download_failures.jsonl"

    download_raw_metadata(
        raw_metadata_path,
        refresh=args.refresh_metadata,
    )
    raw_frame = load_raw_metadata(raw_metadata_path)
    normalized = normalize_metadata(
        raw_frame,
        minimum_duration=args.minimum_duration,
        maximum_duration=args.maximum_duration,
    )
    save_csv(normalized, metadata_path)

    category_summary = (
        normalized["category"]
        .value_counts(dropna=False)
        .rename_axis("category")
        .reset_index(name="count")
    )
    category_summary["percentage"] = (
        category_summary["count"] / len(normalized) * 100
    ).round(2)
    save_csv(category_summary, category_summary_path)

    print(f"Raw rows: {len(raw_frame):,}")
    print(f"Filtered rows: {len(normalized):,}")
    print(f"Normalized metadata: {metadata_path}")
    print_category_summary(normalized)

    selected = select_download_rows(
        normalized,
        categories=args.category,
        limit=args.download_limit,
    )
    if selected.empty:
        print("\nNo videos downloaded. Use --download-limit to opt in.")
        return

    failures = download_videos(selected, videos_dir)
    if failures:
        with failures_path.open("a", encoding="utf-8") as handle:
            for failure in failures:
                handle.write(json.dumps(failure, ensure_ascii=False) + "\n")

    print(f"\nDownload selection: {len(selected)}")
    print(f"Successful or already present: {len(selected) - len(failures)}")
    print(f"Failed: {len(failures)}")
    if failures:
        print(f"Failure log: {failures_path}")


if __name__ == "__main__":
    main()
