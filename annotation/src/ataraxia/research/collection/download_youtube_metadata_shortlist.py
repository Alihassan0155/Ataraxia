"""Probe orientation and download the filtered metadata-only shortlist."""
from ataraxia.runtime.config import project_root

import argparse
import csv
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

from tqdm import tqdm


BASE_DIR = project_root()
DEFAULT_DATASET_DIR = BASE_DIR / "data" / "youtube_shorts"
DEFAULT_MAXIMUM_HORIZONTAL_FRACTION = 0.30


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Probe shortlist orientation, enforce the horizontal cap, and "
            "download accepted YouTube Shorts."
        )
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument(
        "--maximum-horizontal-fraction",
        type=float,
        default=DEFAULT_MAXIMUM_HORIZONTAL_FRACTION,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N shortlisted rows; zero means all rows.",
    )
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Build the orientation-aware manifest without downloading videos.",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Refresh the current download-status CSV without downloading.",
    )
    parser.add_argument(
        "--retry-failed-only",
        action="store_true",
        help="Retry only accepted videos currently recorded as failed.",
    )
    parser.add_argument(
        "--retry-probe-errors",
        action="store_true",
        help="Retry rows whose earlier orientation probe failed.",
    )
    cookie_group = parser.add_mutually_exclusive_group()
    cookie_group.add_argument(
        "--cookies-from-browser",
        help="Browser name for yt-dlp cookies, such as chrome or firefox.",
    )
    cookie_group.add_argument(
        "--cookies-file",
        type=Path,
        help="Netscape-format cookies file for yt-dlp.",
    )
    return parser.parse_args()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def numeric(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_checkpoint(path):
    results = {}
    if not path.exists():
        return results
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            results[row["assigned_id"]] = row
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def append_jsonl(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def orientation_from_info(info):
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
            raise ValueError("No video dimensions found in YouTube metadata")
        best = max(
            video_formats,
            key=lambda item: int(item["width"]) * int(item["height"]),
        )
        width = best["width"]
        height = best["height"]

    width = int(width)
    height = int(height)
    if height > width:
        orientation = "vertical"
    elif width > height:
        orientation = "horizontal"
    else:
        orientation = "square"
    return width, height, orientation


def cookie_arguments(browser, cookies_file):
    if browser:
        return ["--cookies-from-browser", browser]
    if cookies_file:
        return ["--cookies", str(cookies_file.resolve())]
    return []


def probe_orientation(row, cookie_args):
    command = [
            "yt-dlp",
            "--no-playlist",
            "--skip-download",
            "--dump-single-json",
            "--js-runtimes",
            "node",
        ]
    command.extend(cookie_args)
    command.append(str(row["source_url"]))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or "yt-dlp probe failed")
    return orientation_from_info(json.loads(result.stdout))


def run_orientation_scan(rows, checkpoint_path, retry_errors, cookie_args):
    results = load_checkpoint(checkpoint_path)
    selected_ids = {row["assigned_id"] for row in rows}
    results = {
        video_id: result
        for video_id, result in results.items()
        if video_id in selected_ids
    }
    if retry_errors:
        results = {
            video_id: result
            for video_id, result in results.items()
            if result.get("probe_status") != "error"
        }

    pending = [row for row in rows if row["assigned_id"] not in results]
    print(f"Orientation already checked: {len(results):,}")
    print(f"Orientation pending: {len(pending):,}")

    for row in tqdm(pending, unit="video"):
        try:
            width, height, orientation = probe_orientation(row, cookie_args)
            result = {
                "assigned_id": row["assigned_id"],
                "display_width": width,
                "display_height": height,
                "orientation": orientation,
                "probe_status": "complete",
                "probe_error": "",
            }
        except Exception as error:
            result = {
                "assigned_id": row["assigned_id"],
                "display_width": "",
                "display_height": "",
                "orientation": "unknown",
                "probe_status": "error",
                "probe_error": f"{type(error).__name__}: {error}",
            }
        results[row["assigned_id"]] = result
        append_jsonl(checkpoint_path, result)
    return results


def candidate_rank(row):
    return (
        -numeric(row.get("target_score")),
        -numeric(row.get("metadata_language_confidence")),
        row.get("assigned_id", ""),
    )


def build_decisions(rows, orientation_results, maximum_horizontal_fraction):
    enriched = []
    for row in rows:
        orientation = orientation_results.get(row["assigned_id"])
        if orientation is not None:
            enriched.append({**row, **orientation})

    vertical = sorted(
        [row for row in enriched if row["orientation"] == "vertical"],
        key=candidate_rank,
    )
    horizontal = sorted(
        [row for row in enriched if row["orientation"] == "horizontal"],
        key=candidate_rank,
    )

    if maximum_horizontal_fraction >= 1:
        horizontal_limit = len(horizontal)
    elif maximum_horizontal_fraction == 0:
        horizontal_limit = 0
    else:
        horizontal_limit = math.floor(
            maximum_horizontal_fraction
            * len(vertical)
            / (1.0 - maximum_horizontal_fraction)
        )
    accepted_horizontal_ids = {
        row["assigned_id"] for row in horizontal[:horizontal_limit]
    }

    output = []
    for row in enriched:
        if row["orientation"] == "vertical":
            decision = "download"
        elif row["orientation"] == "horizontal":
            decision = (
                "download"
                if row["assigned_id"] in accepted_horizontal_ids
                else "exclude_horizontal_cap"
            )
        elif row["orientation"] == "square":
            decision = "exclude_square"
        else:
            decision = "exclude_probe_error"
        output.append({**row, "download_decision": decision})
    return output


def write_manifest(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(path)


def write_download_status(path, accepted, videos_dir, failures_path):
    latest_failures = load_checkpoint(failures_path)
    status_rows = []
    for row in accepted:
        video_path = videos_dir / f"{row['assigned_id']}.mp4"
        if video_path.exists() and video_path.stat().st_size > 0:
            status = "downloaded"
            size_bytes = video_path.stat().st_size
            error = ""
        elif row["assigned_id"] in latest_failures:
            status = "failed"
            size_bytes = ""
            error = latest_failures[row["assigned_id"]].get("error", "")
        else:
            status = "pending"
            size_bytes = ""
            error = ""
        status_rows.append(
            {
                "assigned_id": row["assigned_id"],
                "source_url": row["source_url"],
                "category": row.get("category", ""),
                "orientation": row.get("orientation", ""),
                "download_status": status,
                "local_path": str(video_path) if status == "downloaded" else "",
                "size_bytes": size_bytes,
                "last_error": error,
            }
        )
    write_manifest(path, status_rows)
    counts = Counter(row["download_status"] for row in status_rows)
    print(f"Current download status: {dict(counts)}")
    print(f"Status tracker: {path}")


def download_video(row, videos_dir, cookie_args):
    destination = videos_dir / f"{row['assigned_id']}.mp4"
    if destination.exists() and destination.stat().st_size > 0:
        return None

    output_template = videos_dir / f"{row['assigned_id']}.%(ext)s"
    command = [
            "yt-dlp",
            "--no-playlist",
            "--continue",
            "--no-overwrites",
            "--retries",
            "3",
            "--fragment-retries",
            "3",
            "--sleep-interval",
            "2",
            "--max-sleep-interval",
            "5",
            "--js-runtimes",
            "node",
            "-f",
            "bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "--remux-video",
            "mp4",
            "-o",
            str(output_template),
        ]
    command.extend(cookie_args)
    command.append(str(row["source_url"]))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return None
    return {
        "assigned_id": row["assigned_id"],
        "source_url": row["source_url"],
        "error": result.stderr[-2000:] or "yt-dlp download failed",
    }


def main():
    args = parse_args()
    if args.limit < 0:
        raise ValueError("--limit cannot be negative")
    if not 0 <= args.maximum_horizontal_fraction <= 1:
        raise ValueError(
            "--maximum-horizontal-fraction must be between 0 and 1"
        )

    dataset_dir = args.dataset_dir.resolve()
    shortlist_path = dataset_dir / "metadata_hindi_urdu_candidates_filtered.csv"
    checkpoint_path = dataset_dir / "metadata_candidate_orientation_scan.jsonl"
    manifest_path = dataset_dir / "metadata_candidate_download_manifest.csv"
    failures_path = dataset_dir / "metadata_candidate_download_failures.jsonl"
    status_path = dataset_dir / "metadata_candidate_download_status.csv"
    videos_dir = dataset_dir / "videos"
    cookie_args = cookie_arguments(
        args.cookies_from_browser,
        args.cookies_file,
    )

    if not shortlist_path.exists():
        raise FileNotFoundError(f"Missing shortlist: {shortlist_path}")

    rows = read_csv(shortlist_path)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise ValueError("No shortlisted rows were selected")

    orientation_results = run_orientation_scan(
        rows,
        checkpoint_path,
        args.retry_probe_errors,
        cookie_args,
    )
    decisions = build_decisions(
        rows,
        orientation_results,
        args.maximum_horizontal_fraction,
    )
    write_manifest(manifest_path, decisions)

    accepted = [
        row for row in decisions if row["download_decision"] == "download"
    ]
    orientations = Counter(row["orientation"] for row in accepted)
    print(f"Accepted for download: {len(accepted):,}")
    print(f"Accepted orientations: {dict(orientations)}")
    if accepted:
        print(
            "Horizontal percentage: "
            f"{orientations['horizontal'] / len(accepted) * 100:.2f}%"
        )
    print(f"Manifest: {manifest_path}")

    if args.probe_only:
        print("Probe-only mode: no videos downloaded.")
        return

    videos_dir.mkdir(parents=True, exist_ok=True)
    if args.status_only:
        write_download_status(status_path, accepted, videos_dir, failures_path)
        return

    download_rows = accepted
    if args.retry_failed_only:
        failed_ids = set(load_checkpoint(failures_path))
        download_rows = [
            row
            for row in accepted
            if row["assigned_id"] in failed_ids
            and not (
                (videos_dir / f"{row['assigned_id']}.mp4").exists()
                and (videos_dir / f"{row['assigned_id']}.mp4").stat().st_size > 0
            )
        ]
        print(f"Failed videos selected for retry: {len(download_rows):,}")

    failures = []
    try:
        for row in tqdm(download_rows, unit="video"):
            failure = download_video(row, videos_dir, cookie_args)
            if failure is not None:
                failures.append(failure)
                append_jsonl(failures_path, failure)
    finally:
        write_download_status(status_path, accepted, videos_dir, failures_path)

    print(f"Download failures this run: {len(failures)}")
    if failures:
        print(f"Failure log: {failures_path}")


if __name__ == "__main__":
    main()
