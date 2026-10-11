"""Probe and download the English 500-video YouTube Shorts subset."""
from ataraxia.runtime.config import project_root

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from tqdm import tqdm

from ataraxia.research.collection.download_youtube_metadata_shortlist import (
    append_jsonl,
    cookie_arguments,
    download_video,
    load_checkpoint,
    run_orientation_scan,
    write_manifest,
)


BASE_DIR = project_root()
DEFAULT_DATASET_DIR = BASE_DIR / "data" / "youtube_shorts"


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Download exactly the configured English category quotas while "
            "keeping horizontal videos at or below 30 percent."
        )
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--maximum-horizontal-fraction", type=float, default=0.30)
    parser.add_argument("--probe-only", action="store_true")
    cookie_group = parser.add_mutually_exclusive_group()
    cookie_group.add_argument("--cookies-from-browser")
    cookie_group.add_argument("--cookies-file", type=Path)
    return parser.parse_args()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def file_downloaded(videos_dir, video_id):
    path = videos_dir / f"{video_id}.mp4"
    return path.exists() and path.stat().st_size > 0


def quotas_from_rows(rows):
    quotas = {}
    for row in rows:
        quotas[row["category"]] = int(row["target_category_quota"])
    return quotas


def write_status(path, rows, videos_dir, failures_path, quotas):
    latest_failures = load_checkpoint(failures_path)
    downloaded_by_category = Counter(
        row["category"]
        for row in rows
        if file_downloaded(videos_dir, row["assigned_id"])
    )
    status_rows = []
    for row in rows:
        video_id = row["assigned_id"]
        video_path = videos_dir / f"{video_id}.mp4"
        if file_downloaded(videos_dir, video_id):
            status = "downloaded"
            error = ""
        elif row.get("download_decision", "").startswith("exclude"):
            status = row["download_decision"]
            error = row.get("probe_error", "")
        elif video_id in latest_failures:
            status = "failed"
            error = latest_failures[video_id].get("error", "")
        elif downloaded_by_category[row["category"]] >= quotas[row["category"]]:
            status = "reserve_not_needed"
            error = ""
        else:
            status = "pending"
            error = ""
        status_rows.append(
            {
                "assigned_id": video_id,
                "category": row["category"],
                "category_quota": quotas[row["category"]],
                "orientation": row.get("orientation", ""),
                "download_status": status,
                "source_url": row["source_url"],
                "local_path": str(video_path) if status == "downloaded" else "",
                "last_error": error,
            }
        )
    write_manifest(path, status_rows)
    counts = Counter(row["download_status"] for row in status_rows)
    print(f"Current candidate status: {dict(counts)}")
    print(f"Status tracker: {path}")


def main():
    args = parse_args()
    if not 0 <= args.maximum_horizontal_fraction <= 1:
        raise ValueError("Horizontal fraction must be between 0 and 1")

    dataset_dir = args.dataset_dir.resolve()
    subset_dir = dataset_dir / "english_500"
    shortlist_path = subset_dir / "metadata_candidates.csv"
    checkpoint_path = subset_dir / "orientation_scan.jsonl"
    manifest_path = subset_dir / "download_manifest.csv"
    failures_path = subset_dir / "download_failures.jsonl"
    status_path = subset_dir / "download_status.csv"
    videos_dir = subset_dir / "videos"
    cookie_args = cookie_arguments(args.cookies_from_browser, args.cookies_file)

    rows = read_csv(shortlist_path)
    quotas = quotas_from_rows(rows)
    orientation_results = run_orientation_scan(
        rows, checkpoint_path, False, cookie_args
    )

    decisions = []
    for row in rows:
        probe = orientation_results[row["assigned_id"]]
        orientation = probe.get("orientation", "unknown")
        if orientation in {"vertical", "horizontal"}:
            decision = "eligible"
        elif orientation == "square":
            decision = "exclude_square"
        else:
            decision = "exclude_probe_error"
        decisions.append({**row, **probe, "download_decision": decision})
    write_manifest(manifest_path, decisions)

    eligible = [row for row in decisions if row["download_decision"] == "eligible"]
    print(f"Eligible after orientation probe: {len(eligible):,}")
    print(f"Orientation counts: {dict(Counter(row['orientation'] for row in eligible))}")
    print(f"Manifest: {manifest_path}")
    if args.probe_only:
        return

    videos_dir.mkdir(parents=True, exist_ok=True)
    by_category = defaultdict(list)
    for row in eligible:
        by_category[row["category"]].append(row)
    for category in by_category:
        by_category[category].sort(
            key=lambda row: int(row["metadata_candidate_rank_within_category"])
        )

    failures_this_run = []
    category_counts = Counter()
    orientation_counts = Counter()
    for row in eligible:
        if file_downloaded(videos_dir, row["assigned_id"]):
            category_counts[row["category"]] += 1
            orientation_counts[row["orientation"]] += 1

    # Try vertical candidates first so horizontal content never displaces reels.
    for orientation_pass in ("vertical", "horizontal"):
        for category, quota in quotas.items():
            needed = quota - category_counts[category]
            if needed <= 0:
                continue
            candidates = [
                row
                for row in by_category[category]
                if row["orientation"] == orientation_pass
                and not file_downloaded(videos_dir, row["assigned_id"])
            ]
            for row in tqdm(candidates, desc=category, unit="video"):
                if category_counts[category] >= quota:
                    break
                total_downloaded = sum(category_counts.values())
                if orientation_pass == "horizontal":
                    allowed = math.floor(
                        args.maximum_horizontal_fraction * (total_downloaded + 1)
                    )
                    if orientation_counts["horizontal"] + 1 > allowed:
                        continue
                failure = download_video(row, videos_dir, cookie_args)
                if failure is not None:
                    failures_this_run.append(failure)
                    append_jsonl(failures_path, failure)
                    continue
                if file_downloaded(videos_dir, row["assigned_id"]):
                    category_counts[category] += 1
                    orientation_counts[orientation_pass] += 1

    write_status(status_path, decisions, videos_dir, failures_path, quotas)
    print(f"Downloaded total: {sum(category_counts.values()):,}/500")
    for category, quota in quotas.items():
        print(f"  {category}: {category_counts[category]}/{quota}")
    total = sum(orientation_counts.values())
    horizontal_percentage = (
        orientation_counts["horizontal"] / total * 100 if total else 0
    )
    print(f"Downloaded orientations: {dict(orientation_counts)}")
    print(f"Horizontal percentage: {horizontal_percentage:.2f}%")
    print(f"Download failures this run: {len(failures_this_run):,}")


if __name__ == "__main__":
    main()
