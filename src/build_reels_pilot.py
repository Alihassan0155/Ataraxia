import csv
import json
import random
import shutil
import subprocess
from collections import Counter
from pathlib import Path


SEED = 42

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_DIR = BASE_DIR / "data" / "FineVideo"
SOURCE_VIDEOS_DIR = SOURCE_DIR / "videos"
SOURCE_METADATA_PATH = SOURCE_DIR / "metadata.csv"
ORIENTATION_MANIFEST_PATH = SOURCE_DIR / "orientation_manifest.csv"

OLD_PILOT_DIR = BASE_DIR / "pilot_50"
NEW_PILOT_DIR = BASE_DIR / "pilot_50_reels_30h"
NEW_VIDEOS_DIR = NEW_PILOT_DIR / "videos"
NEW_METADATA_PATH = NEW_PILOT_DIR / "pilot_metadata.csv"

OLD_OUTPUT_ROOT = BASE_DIR / "outputs"
NEW_OUTPUT_ROOT = BASE_DIR / "outputs" / "reels_30h"

TARGET_COUNTS = {
    "Camping": 2,
    "Stand-up": 3,
    "Sketches": 3,
    "Storytime": 2,
    "Pranks": 3,
    "Motivational Talks": 2,
    "Daily Vlogs": 2,
    "Science Explainers": 2,
    "Workout Routines": 2,
    "Parodies": 2,
    "Game Highlights": 2,
    "Music Videos": 3,
    "Biology": 2,
    "Training Techniques": 2,
    "Physics": 2,
    "Game Commentary": 2,
    "Destination Guides": 2,
    "Mental Health Tips": 2,
    "Covers": 2,
    "Conservation Efforts": 2,
    "Makeup Tutorials": 2,
    "Travel Vlogs": 2,
    "Gameplay Tutorials": 2,
}

# Four three-video categories receive one horizontal item each. Eleven of the
# two-video categories receive one horizontal item. This totals 15/50 (30%).
# Categories with scarce portrait material are prioritized for a mixed pair.
HORIZONTAL_COUNTS = {
    "Camping": 1,
    "Stand-up": 1,
    "Sketches": 1,
    "Storytime": 1,
    "Pranks": 1,
    "Motivational Talks": 0,
    "Daily Vlogs": 0,
    "Science Explainers": 0,
    "Workout Routines": 0,
    "Parodies": 1,
    "Game Highlights": 1,
    "Music Videos": 1,
    "Biology": 1,
    "Training Techniques": 1,
    "Physics": 1,
    "Game Commentary": 0,
    "Destination Guides": 0,
    "Mental Health Tips": 1,
    "Covers": 0,
    "Conservation Efforts": 1,
    "Makeup Tutorials": 1,
    "Travel Vlogs": 0,
    "Gameplay Tutorials": 1,
}


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def probe_video(path):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:stream_tags=rotate:stream_side_data=rotation",
        "-of",
        "json",
        str(path),
    ]
    payload = json.loads(
        subprocess.check_output(command, text=True)
    )
    stream = payload["streams"][0]
    width = int(stream["width"])
    height = int(stream["height"])
    rotation = int(stream.get("tags", {}).get("rotate", 0) or 0)

    for side_data in stream.get("side_data_list", []):
        if side_data.get("rotation") is not None:
            rotation = int(side_data["rotation"])

    if abs(rotation) % 180 == 90:
        width, height = height, width

    if height > width:
        orientation = "vertical"
    elif width > height:
        orientation = "horizontal"
    else:
        orientation = "square"

    return width, height, orientation


def build_orientation_manifest(metadata_rows):
    manifest_rows = []

    for row in metadata_rows:
        video_id = row["assigned_id"]
        source_path = SOURCE_VIDEOS_DIR / f"{video_id}.mp4"
        if not source_path.exists():
            source_path = SOURCE_VIDEOS_DIR / Path(row["file_path"]).name
        if not source_path.exists():
            raise FileNotFoundError(f"Missing source video: {video_id}")

        width, height, orientation = probe_video(source_path)
        manifest_row = dict(row)
        manifest_row.update(
            {
                "display_width": width,
                "display_height": height,
                "aspect_ratio": round(width / height, 6),
                "orientation": orientation,
            }
        )
        manifest_rows.append(manifest_row)

    fieldnames = list(metadata_rows[0]) + [
        "display_width",
        "display_height",
        "aspect_ratio",
        "orientation",
    ]
    write_csv(ORIENTATION_MANIFEST_PATH, manifest_rows, fieldnames)
    return manifest_rows


def select_pilot(manifest_rows, old_pilot_rows):
    rng = random.Random(SEED)
    by_id = {row["assigned_id"]: row for row in manifest_rows}
    old_ids = {row["assigned_id"] for row in old_pilot_rows}
    selected = []

    for category, target_count in TARGET_COUNTS.items():
        horizontal_target = HORIZONTAL_COUNTS[category]
        vertical_target = target_count - horizontal_target

        category_rows = [
            row for row in manifest_rows
            if row["category"] == category
        ]
        old_category_rows = [
            by_id[row["assigned_id"]]
            for row in old_pilot_rows
            if row["category"] == category
        ]

        for orientation, needed in (
            ("vertical", vertical_target),
            ("horizontal", horizontal_target),
        ):
            reusable = sorted(
                (
                    row for row in old_category_rows
                    if row["orientation"] == orientation
                ),
                key=lambda row: row["assigned_id"],
            )
            chosen = reusable[:needed]
            remaining = needed - len(chosen)

            candidates = sorted(
                (
                    row for row in category_rows
                    if row["orientation"] == orientation
                    and row["assigned_id"] not in old_ids
                ),
                key=lambda row: row["assigned_id"],
            )
            if len(candidates) < remaining:
                raise ValueError(
                    f"Not enough {orientation} videos for {category}: "
                    f"need {needed}, found {len(reusable) + len(candidates)}"
                )

            if remaining:
                chosen.extend(rng.sample(candidates, remaining))

            for row in chosen:
                selected_row = dict(row)
                selected_row["pilot_origin"] = (
                    "reused_original_pilot"
                    if row["assigned_id"] in old_ids
                    else "replacement"
                )
                selected.append(selected_row)

    rng.shuffle(selected)
    return selected


def copy_pilot_files(selected_rows):
    NEW_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    asset_folders = ("audio", "transcripts", "context")

    for folder in asset_folders:
        (NEW_PILOT_DIR / folder).mkdir(parents=True, exist_ok=True)

    metadata_rows = []
    for index, row in enumerate(selected_rows, start=1):
        video_id = row["assigned_id"]
        source_video = SOURCE_VIDEOS_DIR / f"{video_id}.mp4"
        if not source_video.exists():
            source_video = SOURCE_VIDEOS_DIR / Path(row["file_path"]).name
        destination_video = NEW_VIDEOS_DIR / source_video.name
        shutil.copy2(source_video, destination_video)

        if row["pilot_origin"] == "reused_original_pilot":
            for folder, suffix in (
                ("audio", ".wav"),
                ("transcripts", ".txt"),
                ("context", ".json"),
            ):
                source_asset = OLD_PILOT_DIR / folder / f"{video_id}{suffix}"
                if source_asset.exists():
                    shutil.copy2(
                        source_asset,
                        NEW_PILOT_DIR / folder / source_asset.name,
                    )

        metadata_row = {
            key: value
            for key, value in row.items()
            if key not in {
                "display_width",
                "display_height",
                "aspect_ratio",
                "orientation",
                "pilot_origin",
            }
        }
        metadata_row = {
            "pilot_id": f"PILOT_{index:03d}",
            **metadata_row,
            "orientation": row["orientation"],
            "display_width": row["display_width"],
            "display_height": row["display_height"],
            "pilot_origin": row["pilot_origin"],
            "pilot_video_path": str(Path("videos") / source_video.name),
        }
        metadata_rows.append(metadata_row)

    write_csv(
        NEW_METADATA_PATH,
        metadata_rows,
        list(metadata_rows[0]),
    )


def seed_existing_annotations(selected_rows):
    reused_ids = {
        row["assigned_id"]
        for row in selected_rows
        if row["pilot_origin"] == "reused_original_pilot"
    }

    for model in ("gemini", "qwen"):
        source = OLD_OUTPUT_ROOT / model / "annotations.jsonl"
        destination = NEW_OUTPUT_ROOT / model / "annotations.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)

        existing = {}
        if destination.exists():
            for line in destination.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    existing[row["video_id"]] = row

        for line in source.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row["video_id"] in reused_ids:
                existing.setdefault(row["video_id"], row)

        selected_ids = {row["assigned_id"] for row in selected_rows}
        kept = [
            existing[video_id]
            for video_id in sorted(existing)
            if video_id in selected_ids
        ]
        destination.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False) + "\n"
                for row in kept
            ),
            encoding="utf-8",
        )


def validate(selected_rows):
    if len(selected_rows) != 50:
        raise ValueError(f"Expected 50 videos, got {len(selected_rows)}")
    if len({row["assigned_id"] for row in selected_rows}) != 50:
        raise ValueError("Pilot contains duplicate video IDs")

    category_counts = Counter(row["category"] for row in selected_rows)
    if dict(category_counts) != TARGET_COUNTS:
        raise ValueError(
            f"Category counts do not match target: {category_counts}"
        )

    orientation_counts = Counter(
        row["orientation"] for row in selected_rows
    )
    expected = {"vertical": 35, "horizontal": 15}
    if dict(orientation_counts) != expected:
        raise ValueError(
            f"Orientation counts do not match {expected}: "
            f"{orientation_counts}"
        )


def main():
    metadata_rows = read_csv(SOURCE_METADATA_PATH)
    old_pilot_rows = read_csv(OLD_PILOT_DIR / "pilot_metadata.csv")

    manifest_rows = build_orientation_manifest(metadata_rows)
    selected_rows = select_pilot(manifest_rows, old_pilot_rows)
    validate(selected_rows)
    copy_pilot_files(selected_rows)
    seed_existing_annotations(selected_rows)

    orientation_counts = Counter(
        row["orientation"] for row in selected_rows
    )
    origin_counts = Counter(row["pilot_origin"] for row in selected_rows)
    print(f"Orientation manifest: {ORIENTATION_MANIFEST_PATH}")
    print(f"New pilot: {NEW_PILOT_DIR}")
    print(f"Orientation counts: {dict(orientation_counts)}")
    print(f"Origin counts: {dict(origin_counts)}")
    print(f"Seeded outputs: {NEW_OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
