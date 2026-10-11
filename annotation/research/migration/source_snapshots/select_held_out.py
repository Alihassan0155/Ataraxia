"""Select a balanced, reproducible holdout from the validated FineVideo pool."""
import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261008)
    args = parser.parse_args()
    metadata = ROOT / "data/FineVideo/metadata.csv"
    pilot = ROOT / "pilot_50_reels_30h/pilot_metadata.csv"
    rows = read_csv(metadata)
    pilot_rows = read_csv(pilot)
    pilot_ids = {row["assigned_id"] for row in pilot_rows}
    if len(pilot_rows) != 50 or len(pilot_ids) != 50:
        raise ValueError("Original pilot must contain 50 unique IDs")
    counts = Counter(row["assigned_id"] for row in rows)
    if any(count != 1 for count in counts.values()):
        raise ValueError("Duplicate source IDs; resolve before sampling")
    groups = defaultdict(list)
    excluded = Counter()
    for row in rows:
        if row["assigned_id"] in pilot_ids:
            excluded["original_pilot"] += 1
            continue
        if row["language"] not in {"en", "ur", "hi"}:
            excluded["language"] += 1
            continue
        if not row["category"].strip():
            raise ValueError("Missing category")
        path = ROOT / row["file_path"]
        if not path.is_file() or path.stat().st_size == 0:
            excluded["eligible_metadata_with_missing_or_empty_media"] += 1
        groups[row["category"]].append(row)
    categories = sorted(groups)
    if sum(map(len, groups.values())) < 50:
        raise ValueError("Fewer than 50 eligible videos")
    rng = random.Random(args.seed)
    # Allocate balanced quotas, using seeded category order for residual slots.
    order = categories.copy()
    rng.shuffle(order)
    quotas = dict.fromkeys(categories, 0)
    while sum(quotas.values()) < 50:
        for category in order:
            if sum(quotas.values()) == 50:
                break
            if quotas[category] < len(groups[category]):
                quotas[category] += 1
    selected = []
    for category in categories:
        candidates = sorted(groups[category], key=lambda row: row["assigned_id"])
        selected.extend(rng.sample(candidates, quotas[category]))
    selected.sort(key=lambda row: (row["category"], row["assigned_id"]))
    ids = {row["assigned_id"] for row in selected}
    assert len(selected) == len(ids) == 50
    assert not ids.intersection(pilot_ids)
    output = ROOT / "held out"
    output.mkdir(exist_ok=True)
    destinations = [output / name for name in (
        "held_out_50.csv", "held_out_50.txt", "selection_manifest.json")]
    if any(path.exists() for path in destinations):
        raise FileExistsError("Holdout outputs already exist; preserve the frozen selection")
    fields = ["video_id", "category", "parent_category", "file_path", "language", "source_dataset", "local_media_available"]
    records = [{"video_id": row["assigned_id"], **{key: row[key] for key in fields[1:-1]},
                "local_media_available": (ROOT / row["file_path"]).is_file()
                and (ROOT / row["file_path"]).stat().st_size > 0}
               for row in selected]
    with destinations[0].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    with destinations[1].open("w", encoding="utf-8") as handle:
        handle.write("video_id\tcategory\tfile_path\n")
        for row in records:
            handle.write(f"{row['video_id']}\t{row['category']}\t{row['file_path']}\n")
    manifest = {
        "seed": args.seed, "total": 50, "pilot_overlap": 0, "duplicate_ids": 0,
        "scope": "Validated FineVideo metadata; unverified newer collections excluded",
        "algorithm": "Balanced round-robin quotas in seeded category order; sorted-ID random sampling",
        "category_distribution": quotas,
        "eligible_candidates": sum(map(len, groups.values())),
        "selected_local_media_available": sum(row["local_media_available"] for row in records),
        "media_note": "Selection is metadata-based; recorded media paths must be restored when absent",
        "exclusions": dict(excluded),
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (metadata, pilot)},
        "paths": "Project-root-relative; original source metadata unchanged",
        "interpretation": "New pilot-independent holdout; no labels or model predictions used in selection",
    }
    destinations[2].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for category, count in sorted(quotas.items()):
        print(f"{category}: {count}")
    print(f"Total: {len(records)} | Pilot overlap: 0 | Duplicate IDs: 0 | Seed: {args.seed}")


if __name__ == "__main__":
    main()
