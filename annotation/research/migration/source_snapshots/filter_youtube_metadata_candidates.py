"""Create the capped metadata-only Hindi/Urdu candidate shortlist."""

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = BASE_DIR / "data" / "youtube_shorts"
CATEGORY_CAPS = {
    "People & Blogs": 250,
    "Education": 150,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Keep metadata-based Hindi/Urdu candidates lasting 10–90 seconds, "
            "cap People & Blogs at 250 and Education at 150, and retain all "
            "other categories."
        )
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
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


def candidate_rank(row):
    return (
        -numeric(row.get("target_score")),
        -numeric(row.get("metadata_language_confidence")),
        row.get("assigned_id", ""),
    )


def main():
    args = parse_args()
    dataset_dir = args.dataset_dir.resolve()
    input_path = dataset_dir / "metadata_language_prefilter.csv"
    output_path = dataset_dir / "metadata_hindi_urdu_candidates_filtered.csv"

    if not input_path.exists():
        raise FileNotFoundError(f"Missing metadata prefilter: {input_path}")

    rows = read_csv(input_path)
    candidates = [
        row
        for row in rows
        if row.get("prefilter_status") == "hindi_urdu_candidate"
        and 10 <= numeric(row.get("duration"), -1) <= 90
    ]

    by_category = defaultdict(list)
    for row in candidates:
        by_category[row["category"]].append(row)

    selected = []
    for category in sorted(by_category):
        category_rows = sorted(by_category[category], key=candidate_rank)
        cap = CATEGORY_CAPS.get(category, len(category_rows))
        for rank, row in enumerate(category_rows[:cap], start=1):
            selected.append(
                {
                    **row,
                    "metadata_candidate_rank_within_category": rank,
                }
            )

    selected.sort(key=lambda row: row["assigned_id"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(output_path.name + ".tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        fields = list(selected[0])
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(selected)
    temporary_path.replace(output_path)

    counts = Counter(row["category"] for row in selected)
    print(f"Filtered metadata candidates: {len(selected):,}")
    for category, count in counts.most_common():
        print(f"  {category}: {count}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
