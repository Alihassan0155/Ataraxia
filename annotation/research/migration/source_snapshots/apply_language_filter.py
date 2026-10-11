import csv
import json
import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_DIR = BASE_DIR / "data" / "FineVideo"
SOURCE_METADATA = DATASET_DIR / "metadata.csv"
LANGUAGE_MANIFEST = DATASET_DIR / "language_manifest.csv"
ORIENTATION_MANIFEST = DATASET_DIR / "orientation_manifest.csv"
SOURCE_VIDEOS = DATASET_DIR / "videos"
SOURCE_QUARANTINE = DATASET_DIR / "quarantine_non_target_language"

PILOT_DIR = BASE_DIR / "pilot_50_reels_30h"
PILOT_METADATA = PILOT_DIR / "pilot_metadata.csv"
PILOT_QUARANTINE = PILOT_DIR / "quarantine_non_target_language"

OUTPUT_ROOT = BASE_DIR / "outputs" / "reels_30h"
OUTPUT_QUARANTINE = OUTPUT_ROOT / "quarantine_non_target_language"

PILOT_REMOVED_ID = "FV000037"
PILOT_REPLACEMENT_ID = "FV000131"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def move_if_present(source, destination):
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Quarantine target already exists: {destination}")
    shutil.move(str(source), str(destination))


def filter_jsonl(path, removed_id, quarantine_path):
    if not path.exists():
        return 0

    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    removed = [row for row in rows if row.get("video_id") == removed_id]
    retained = [row for row in rows if row.get("video_id") != removed_id]

    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in retained
        ),
        encoding="utf-8",
    )

    if removed:
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        quarantine_path.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False) + "\n"
                for row in removed
            ),
            encoding="utf-8",
        )
    return len(removed)


def main():
    source_rows = read_csv(SOURCE_METADATA)
    source_fields = list(source_rows[0])
    language_rows = read_csv(LANGUAGE_MANIFEST)
    language_fields = list(language_rows[0])
    orientation_rows = read_csv(ORIENTATION_MANIFEST)
    orientation_fields = list(orientation_rows[0])

    language_by_id = {
        row["assigned_id"]: row for row in language_rows
    }
    orientation_by_id = {
        row["assigned_id"]: row for row in orientation_rows
    }
    source_by_id = {row["assigned_id"]: row for row in source_rows}

    removal_ids = {
        row["assigned_id"]
        for row in language_rows
        if row["status"] == "remove_non_target_language"
    }
    if len(removal_ids) != 8:
        raise ValueError(
            f"Expected 8 high-confidence removal candidates, got {len(removal_ids)}"
        )
    if PILOT_REMOVED_ID not in removal_ids:
        raise ValueError(f"{PILOT_REMOVED_ID} is not marked for removal")

    replacement_language = language_by_id[PILOT_REPLACEMENT_ID]
    replacement_orientation = orientation_by_id[PILOT_REPLACEMENT_ID]
    if replacement_language["status"] != "keep_target_language":
        raise ValueError("Pilot replacement is not a target-language video")
    if replacement_orientation["orientation"] != "horizontal":
        raise ValueError("Pilot replacement must be horizontal")
    if replacement_language["category"] != "Mental Health Tips":
        raise ValueError("Pilot replacement must preserve the category")

    SOURCE_QUARANTINE.mkdir(parents=True, exist_ok=True)
    backup = SOURCE_QUARANTINE / "metadata_before_filter.csv"
    if not backup.exists():
        shutil.copy2(SOURCE_METADATA, backup)

    removed_source_rows = [
        row for row in source_rows if row["assigned_id"] in removal_ids
    ]
    write_csv(
        SOURCE_QUARANTINE / "removed_metadata.csv",
        removed_source_rows,
        source_fields,
    )

    replacement_source = SOURCE_VIDEOS / f"{PILOT_REPLACEMENT_ID}.mp4"
    pilot_replacement = PILOT_DIR / "videos" / replacement_source.name
    shutil.copy2(replacement_source, pilot_replacement)

    for row in removed_source_rows:
        filename = Path(row["file_path"]).name
        move_if_present(
            SOURCE_VIDEOS / filename,
            SOURCE_QUARANTINE / "videos" / filename,
        )

    retained_source = [
        row for row in source_rows if row["assigned_id"] not in removal_ids
    ]
    write_csv(SOURCE_METADATA, retained_source, source_fields)
    write_csv(
        LANGUAGE_MANIFEST,
        [
            row for row in language_rows
            if row["assigned_id"] not in removal_ids
        ],
        language_fields,
    )
    write_csv(
        ORIENTATION_MANIFEST,
        [
            row for row in orientation_rows
            if row["assigned_id"] not in removal_ids
        ],
        orientation_fields,
    )

    pilot_rows = read_csv(PILOT_METADATA)
    pilot_fields = list(pilot_rows[0])
    old_pilot_row = next(
        row for row in pilot_rows
        if row["assigned_id"] == PILOT_REMOVED_ID
    )
    new_pilot_row = {
        "pilot_id": old_pilot_row["pilot_id"],
        **source_by_id[PILOT_REPLACEMENT_ID],
        "orientation": replacement_orientation["orientation"],
        "display_width": replacement_orientation["display_width"],
        "display_height": replacement_orientation["display_height"],
        "pilot_origin": "language_replacement",
        "pilot_video_path": f"videos/{PILOT_REPLACEMENT_ID}.mp4",
    }
    updated_pilot = [
        new_pilot_row if row["assigned_id"] == PILOT_REMOVED_ID else row
        for row in pilot_rows
    ]
    write_csv(PILOT_METADATA, updated_pilot, pilot_fields)

    for folder, suffix in (
        ("videos", ".mp4"),
        ("audio", ".wav"),
        ("transcripts", ".txt"),
        ("context", ".json"),
    ):
        filename = f"{PILOT_REMOVED_ID}{suffix}"
        move_if_present(
            PILOT_DIR / folder / filename,
            PILOT_QUARANTINE / folder / filename,
        )

    output_removals = {}
    for model in ("gemini", "qwen"):
        output_removals[model] = filter_jsonl(
            OUTPUT_ROOT / model / "annotations.jsonl",
            PILOT_REMOVED_ID,
            OUTPUT_QUARANTINE / model / "annotations.jsonl",
        )

    print(f"Source videos quarantined: {len(removal_ids)}")
    print(f"Source videos retained: {len(retained_source)}")
    print(
        f"Pilot replacement: {PILOT_REMOVED_ID} -> "
        f"{PILOT_REPLACEMENT_ID}"
    )
    print(f"Output annotations quarantined: {output_removals}")


if __name__ == "__main__":
    main()
