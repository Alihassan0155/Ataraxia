import csv
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path


SEED = 42
TARGET_HORIZONTAL = 257

BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_DIR = BASE_DIR / "data" / "FineVideo"
METADATA_PATH = DATASET_DIR / "metadata.csv"
ORIENTATION_PATH = DATASET_DIR / "orientation_manifest.csv"
LANGUAGE_PATH = DATASET_DIR / "language_manifest.csv"
VIDEOS_DIR = DATASET_DIR / "videos"
PILOT_METADATA_PATH = (
    BASE_DIR / "pilot_50_reels_30h" / "pilot_metadata.csv"
)
QUARANTINE_DIR = DATASET_DIR / "quarantine_orientation_filter"
SELECTION_MANIFEST_PATH = (
    DATASET_DIR / "orientation_sampling_manifest.csv"
)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def allocate_proportionally(capacities, total):
    available = sum(capacities.values())
    if total > available:
        raise ValueError(
            f"Cannot allocate {total} slots from {available} candidates"
        )
    if available == 0:
        return {category: 0 for category in capacities}

    exact = {
        category: total * count / available
        for category, count in capacities.items()
    }
    allocation = {
        category: min(int(exact[category]), count)
        for category, count in capacities.items()
    }
    remaining = total - sum(allocation.values())

    order = sorted(
        capacities,
        key=lambda category: (
            -(exact[category] - int(exact[category])),
            category,
        ),
    )
    while remaining:
        changed = False
        for category in order:
            if allocation[category] >= capacities[category]:
                continue
            allocation[category] += 1
            remaining -= 1
            changed = True
            if remaining == 0:
                break
        if not changed:
            raise RuntimeError("Unable to finish proportional allocation")

    return allocation


def main():
    metadata = read_csv(METADATA_PATH)
    metadata_fields = list(metadata[0])
    orientation = read_csv(ORIENTATION_PATH)
    orientation_fields = list(orientation[0])
    language = read_csv(LANGUAGE_PATH)
    language_fields = list(language[0])
    pilot = read_csv(PILOT_METADATA_PATH)

    metadata_by_id = {row["assigned_id"]: row for row in metadata}
    orientation_by_id = {
        row["assigned_id"]: row for row in orientation
    }
    pilot_ids = {row["assigned_id"] for row in pilot}

    current_counts = Counter(
        row["orientation"] for row in orientation
    )
    expected = {"vertical": 601, "horizontal": 418, "square": 9}
    if dict(current_counts) != expected:
        raise ValueError(
            f"Expected current orientation counts {expected}, "
            f"got {dict(current_counts)}"
        )

    vertical_ids = {
        row["assigned_id"]
        for row in orientation
        if row["orientation"] == "vertical"
    }
    horizontal_rows = [
        row for row in orientation
        if row["orientation"] == "horizontal"
    ]
    square_ids = {
        row["assigned_id"]
        for row in orientation
        if row["orientation"] == "square"
    }
    mandatory_horizontal = {
        row["assigned_id"]
        for row in horizontal_rows
        if row["assigned_id"] in pilot_ids
    }
    if len(mandatory_horizontal) != 15:
        raise ValueError(
            "Expected 15 mandatory pilot horizontal videos, got "
            f"{len(mandatory_horizontal)}"
        )

    candidates_by_category = defaultdict(list)
    for row in horizontal_rows:
        video_id = row["assigned_id"]
        if video_id not in mandatory_horizontal:
            candidates_by_category[row["category"]].append(video_id)

    remaining_slots = TARGET_HORIZONTAL - len(mandatory_horizontal)
    capacities = {
        category: len(video_ids)
        for category, video_ids in candidates_by_category.items()
    }
    allocation = allocate_proportionally(capacities, remaining_slots)

    rng = random.Random(SEED)
    selected_horizontal = set(mandatory_horizontal)
    for category in sorted(candidates_by_category):
        candidates = sorted(candidates_by_category[category])
        selected_horizontal.update(
            rng.sample(candidates, allocation[category])
        )

    retained_ids = vertical_ids | selected_horizontal
    removed_ids = set(metadata_by_id) - retained_ids

    if len(selected_horizontal) != TARGET_HORIZONTAL:
        raise ValueError("Horizontal selection did not reach target")
    if len(retained_ids) != 858:
        raise ValueError(
            f"Expected 858 retained videos, got {len(retained_ids)}"
        )
    if not pilot_ids.issubset(retained_ids):
        missing = sorted(pilot_ids - retained_ids)
        raise ValueError(f"Pilot videos would be removed: {missing}")

    selection_rows = []
    for row in orientation:
        video_id = row["assigned_id"]
        if video_id in retained_ids:
            decision = "keep"
        elif video_id in square_ids:
            decision = "remove_square"
        else:
            decision = "remove_horizontal"
        selection_rows.append({**row, "orientation_filter_decision": decision})
    write_csv(
        SELECTION_MANIFEST_PATH,
        selection_rows,
        orientation_fields + ["orientation_filter_decision"],
    )

    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    backup = QUARANTINE_DIR / "metadata_before_orientation_filter.csv"
    if not backup.exists():
        shutil.copy2(METADATA_PATH, backup)

    removed_metadata = [
        row for row in metadata if row["assigned_id"] in removed_ids
    ]
    write_csv(
        QUARANTINE_DIR / "removed_metadata.csv",
        removed_metadata,
        metadata_fields,
    )

    for row in removed_metadata:
        filename = Path(row["file_path"]).name
        source = VIDEOS_DIR / filename
        destination = QUARANTINE_DIR / "videos" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(
                f"Quarantine target already exists: {destination}"
            )
        shutil.move(str(source), str(destination))

    write_csv(
        METADATA_PATH,
        [row for row in metadata if row["assigned_id"] in retained_ids],
        metadata_fields,
    )
    write_csv(
        ORIENTATION_PATH,
        [row for row in orientation if row["assigned_id"] in retained_ids],
        orientation_fields,
    )
    write_csv(
        LANGUAGE_PATH,
        [row for row in language if row["assigned_id"] in retained_ids],
        language_fields,
    )

    removed_orientation_counts = Counter(
        orientation_by_id[video_id]["orientation"]
        for video_id in removed_ids
    )
    print(f"Retained videos: {len(retained_ids)}")
    print("Retained orientations: vertical=601, horizontal=257")
    print(f"Removed orientations: {dict(removed_orientation_counts)}")
    print(f"Pilot videos retained: {len(pilot_ids)}")
    print(f"Selection manifest: {SELECTION_MANIFEST_PATH}")


if __name__ == "__main__":
    main()
