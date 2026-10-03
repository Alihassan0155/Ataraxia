"""Build and optionally download the constrained YouTube Shorts sample."""

import argparse
import csv
import json
import random
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from tqdm import tqdm


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = BASE_DIR / "data" / "youtube_shorts"
TARGET_ENGLISH = 800
TARGET_HINDI_URDU = 1300
MAXIMUM_HORIZONTAL = 630
SEED = 42


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Select 800 English and 1,300 Hindi/Urdu videos while keeping "
            "horizontal content at or below 30 percent."
        )
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the selected full videos after building the manifest.",
    )
    return parser.parse_args()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(path)


def allocate_categories(candidates, total, category_weights):
    capacities = Counter(row["category"] for row in candidates)
    categories = sorted(category_weights)
    desired = {
        category: total * category_weights[category]
        for category in categories
    }
    allocation = {
        category: min(int(desired[category]), capacities[category])
        for category in categories
    }

    remaining = total - sum(allocation.values())
    while remaining:
        available = [
            category
            for category in categories
            if allocation[category] < capacities[category]
        ]
        if not available:
            raise ValueError(
                f"Only {total - remaining} eligible candidates are available "
                f"for a requested group of {total}"
            )
        category = max(
            available,
            key=lambda value: (
                desired[value] - allocation[value],
                category_weights[value],
                capacities[value] - allocation[value],
                value,
            ),
        )
        allocation[category] += 1
        remaining -= 1
    return allocation


def select_group(candidates, total, category_weights, rng):
    allocation = allocate_categories(candidates, total, category_weights)
    by_category = defaultdict(list)
    for row in candidates:
        by_category[row["category"]].append(row)

    selected = []
    for category in sorted(allocation):
        rows = list(by_category[category])
        rng.shuffle(rows)
        rows.sort(key=lambda row: row["orientation"] != "vertical")
        selected.extend(rows[: allocation[category]])
    return selected


def enforce_horizontal_cap(selected, eligible, maximum_horizontal, rng):
    selected_ids = {row["assigned_id"] for row in selected}
    horizontal = [row for row in selected if row["orientation"] == "horizontal"]
    if len(horizontal) <= maximum_horizontal:
        return selected

    rng.shuffle(horizontal)
    by_bucket_and_category = defaultdict(list)
    by_bucket = defaultdict(list)
    for row in eligible:
        if row["assigned_id"] in selected_ids or row["orientation"] != "vertical":
            continue
        bucket = "en" if row["detected_language"] == "en" else "hi_ur"
        by_bucket_and_category[(bucket, row["category"])].append(row)
        by_bucket[bucket].append(row)

    replacements_needed = len(horizontal) - maximum_horizontal
    replacements = {}
    used_replacements = set()

    for old_row in horizontal:
        if len(replacements) >= replacements_needed:
            break
        bucket = (
            "en" if old_row["detected_language"] == "en" else "hi_ur"
        )
        exact = by_bucket_and_category[(bucket, old_row["category"])]
        candidate = next(
            (
                row
                for row in exact
                if row["assigned_id"] not in used_replacements
            ),
            None,
        )
        if candidate is None:
            candidate = next(
                (
                    row
                    for row in by_bucket[bucket]
                    if row["assigned_id"] not in used_replacements
                ),
                None,
            )
        if candidate is None:
            continue
        replacements[old_row["assigned_id"]] = candidate
        used_replacements.add(candidate["assigned_id"])

    if len(replacements) < replacements_needed:
        raise ValueError(
            "Not enough vertical candidates to satisfy the 30% horizontal cap"
        )

    return [
        replacements.get(row["assigned_id"], row)
        for row in selected
    ]


def build_sample(metadata_rows, manifest_rows, seed):
    metadata_categories = Counter(row["category"] for row in metadata_rows)
    metadata_total = sum(metadata_categories.values())
    category_weights = {
        category: count / metadata_total
        for category, count in metadata_categories.items()
    }

    eligible = [
        row
        for row in manifest_rows
        if row.get("status") == "keep_target_language"
        and row.get("orientation") in {"vertical", "horizontal"}
        and row.get("detected_language") in {"en", "hi", "ur"}
    ]
    english = [
        row for row in eligible if row["detected_language"] == "en"
    ]
    hindi_urdu = [
        row
        for row in eligible
        if row["detected_language"] in {"hi", "ur"}
    ]

    if len(english) < TARGET_ENGLISH:
        raise ValueError(
            f"Need {TARGET_ENGLISH} English candidates; found {len(english)}"
        )
    if len(hindi_urdu) < TARGET_HINDI_URDU:
        raise ValueError(
            "Need "
            f"{TARGET_HINDI_URDU} Hindi/Urdu candidates; "
            f"found {len(hindi_urdu)}"
        )

    rng = random.Random(seed)
    selected = select_group(
        english,
        TARGET_ENGLISH,
        category_weights,
        rng,
    )
    selected.extend(
        select_group(
            hindi_urdu,
            TARGET_HINDI_URDU,
            category_weights,
            rng,
        )
    )
    selected = enforce_horizontal_cap(
        selected,
        eligible,
        MAXIMUM_HORIZONTAL,
        rng,
    )

    selected_languages = Counter(
        row["detected_language"] for row in selected
    )
    selected_orientations = Counter(row["orientation"] for row in selected)
    if len(selected) != TARGET_ENGLISH + TARGET_HINDI_URDU:
        raise RuntimeError("Selection did not produce exactly 2,100 videos")
    if len({row["assigned_id"] for row in selected}) != len(selected):
        raise RuntimeError("Selection contains duplicate video IDs")
    if selected_languages["en"] != TARGET_ENGLISH:
        raise RuntimeError("Selection does not contain exactly 800 English videos")
    if (
        selected_languages["hi"] + selected_languages["ur"]
        != TARGET_HINDI_URDU
    ):
        raise RuntimeError(
            "Selection does not contain exactly 1,300 Hindi/Urdu videos"
        )
    if selected_orientations["horizontal"] > MAXIMUM_HORIZONTAL:
        raise RuntimeError("Selection exceeds the 30% horizontal limit")

    rng.shuffle(selected)
    output = []
    for index, row in enumerate(selected, start=1):
        output.append(
            {
                "sample_id": f"YTS{index:04d}",
                **row,
                "sample_video_path": f"videos/{row['assigned_id']}.mp4",
            }
        )
    return output


def download_sample(rows, videos_dir, failure_path):
    videos_dir.mkdir(parents=True, exist_ok=True)
    failures = []

    for row in tqdm(rows, unit="video"):
        destination = videos_dir / f"{row['assigned_id']}.mp4"
        if destination.exists() and destination.stat().st_size > 0:
            continue

        output_template = videos_dir / f"{row['assigned_id']}.%(ext)s"
        result = subprocess.run(
            [
                "yt-dlp",
                "--no-playlist",
                "--no-overwrites",
                "-f",
                "bv*+ba/b",
                "--merge-output-format",
                "mp4",
                "--remux-video",
                "mp4",
                "-o",
                str(output_template),
                str(row["source_url"]),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            failure = {
                "assigned_id": row["assigned_id"],
                "source_url": row["source_url"],
                "error": result.stderr[-2000:],
            }
            failures.append(failure)
            with failure_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(failure, ensure_ascii=False) + "\n")
    return failures


def print_summary(rows):
    languages = Counter(row["detected_language"] for row in rows)
    orientations = Counter(row["orientation"] for row in rows)
    categories = Counter(row["category"] for row in rows)

    print(f"Selected videos: {len(rows)}")
    print(f"Languages: {dict(languages)}")
    print(f"Orientations: {dict(orientations)}")
    print(
        "Horizontal percentage: "
        f"{orientations['horizontal'] / len(rows) * 100:.2f}%"
    )
    print("Categories:")
    for category, count in sorted(categories.items()):
        print(f"  {category}: {count}")


def main():
    args = parse_args()
    dataset_dir = args.dataset_dir.resolve()
    metadata_path = dataset_dir / "metadata.csv"
    language_manifest_path = dataset_dir / "language_manifest.csv"
    sample_metadata_path = dataset_dir / "selected_metadata.csv"
    videos_dir = dataset_dir / "videos"
    failure_path = dataset_dir / "selected_download_failures.jsonl"

    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing metadata: {metadata_path}")
    if not language_manifest_path.exists():
        raise FileNotFoundError(
            f"Missing language audit: {language_manifest_path}"
        )

    metadata_rows = read_csv(metadata_path)
    manifest_rows = read_csv(language_manifest_path)
    selected = build_sample(metadata_rows, manifest_rows, args.seed)
    write_csv(
        sample_metadata_path,
        selected,
        list(selected[0]),
    )
    print_summary(selected)
    print(f"Selection manifest: {sample_metadata_path}")

    if args.download:
        failures = download_sample(selected, videos_dir, failure_path)
        print(f"Download failures: {len(failures)}")
        if failures:
            print(f"Failure log: {failure_path}")
    else:
        print("Videos were not downloaded. Add --download when ready.")


if __name__ == "__main__":
    main()
