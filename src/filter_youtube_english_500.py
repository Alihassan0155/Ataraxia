"""Create a metadata-only English shortlist with category reserves."""

import argparse
import csv
import math
import random
from collections import Counter, defaultdict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = BASE_DIR / "data" / "youtube_shorts"
DEFAULT_SEED = 42
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
            "Select English metadata candidates lasting 10–90 seconds and "
            "add category-level reserves for a final 500-video download."
        )
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument(
        "--reserve-factor",
        type=float,
        default=1.25,
        help="Candidates per quota slot; 1.25 supplies a 25%% reserve.",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args()


def numeric(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(path)


def main():
    args = parse_args()
    if args.reserve_factor < 1:
        raise ValueError("--reserve-factor must be at least 1")

    dataset_dir = args.dataset_dir.resolve()
    source_path = dataset_dir / "metadata_language_prefilter.csv"
    output_dir = dataset_dir / "english_500"
    output_path = output_dir / "metadata_candidates.csv"

    rows = read_csv(source_path)
    candidates = [
        row
        for row in rows
        if row.get("prefilter_status") == "english_candidate"
        and numeric(row.get("english_score")) >= 0.65
        and 10 <= numeric(row.get("duration"), -1) <= 90
        and row.get("category") in CATEGORY_QUOTAS
        and row.get("source_url", "").strip()
    ]

    by_category = defaultdict(list)
    for row in candidates:
        by_category[row["category"]].append(row)

    selected = []
    for category, quota in CATEGORY_QUOTAS.items():
        available = sorted(
            by_category[category], key=lambda row: row["assigned_id"]
        )
        random.Random(f"{args.seed}:{category}").shuffle(available)
        reserve_count = math.ceil(quota * args.reserve_factor)
        if len(available) < reserve_count:
            raise RuntimeError(
                f"{category} has {len(available)} candidates; "
                f"{reserve_count} are required including reserves"
            )
        for rank, row in enumerate(available[:reserve_count], start=1):
            selected.append(
                {
                    **row,
                    "target_category_quota": quota,
                    "metadata_candidate_rank_within_category": rank,
                }
            )

    selected.sort(key=lambda row: (row["category"], int(row["metadata_candidate_rank_within_category"])))
    write_csv(output_path, selected)

    print(f"Final target: {sum(CATEGORY_QUOTAS.values()):,}")
    print(f"Metadata candidates including reserves: {len(selected):,}")
    counts = Counter(row["category"] for row in selected)
    for category, quota in CATEGORY_QUOTAS.items():
        print(f"  {category}: target {quota}, shortlisted {counts[category]}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
