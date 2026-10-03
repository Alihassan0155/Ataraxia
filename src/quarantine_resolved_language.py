import csv
import shutil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_DIR = BASE_DIR / "data" / "FineVideo"
VIDEO_ID = "FV000136"


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    metadata_path = DATASET_DIR / "metadata.csv"
    quarantine = DATASET_DIR / "quarantine_non_target_language"
    removed_path = quarantine / "removed_metadata.csv"

    metadata = read_csv(metadata_path)
    fields = list(metadata[0])
    removed = [row for row in metadata if row["assigned_id"] == VIDEO_ID]
    if len(removed) != 1:
        raise ValueError(f"Expected one active row for {VIDEO_ID}, got {len(removed)}")

    previous_removed = read_csv(removed_path)
    if not any(row["assigned_id"] == VIDEO_ID for row in previous_removed):
        previous_removed.extend(removed)
    write_csv(removed_path, previous_removed, fields)
    write_csv(
        metadata_path,
        [row for row in metadata if row["assigned_id"] != VIDEO_ID],
        fields,
    )

    for name in ("language_manifest.csv", "orientation_manifest.csv"):
        path = DATASET_DIR / name
        rows = read_csv(path)
        write_csv(
            path,
            [row for row in rows if row["assigned_id"] != VIDEO_ID],
            list(rows[0]),
        )

    source = DATASET_DIR / "videos" / f"{VIDEO_ID}.mp4"
    destination = quarantine / "videos" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    print(f"Quarantined confirmed Japanese video: {VIDEO_ID}")


if __name__ == "__main__":
    main()
