from pathlib import Path
import shutil
import pandas as pd

SEED = 42

BASE_DIR = Path(__file__).resolve().parent.parent

FINEVIDEO_CANDIDATES = [
    BASE_DIR / "data" / "FineVideo",
    BASE_DIR / "FineVideo",
]
FINEVIDEO_DIR = next((p for p in FINEVIDEO_CANDIDATES if p.exists()), FINEVIDEO_CANDIDATES[0])
METADATA_PATH = FINEVIDEO_DIR / "metadata.csv"
VIDEOS_DIR = FINEVIDEO_DIR / "videos"

OUTPUT_DIR = BASE_DIR / "pilot_50"
OUTPUT_VIDEOS_DIR = OUTPUT_DIR / "videos"
OUTPUT_METADATA_PATH = OUTPUT_DIR / "pilot_metadata.csv"

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

CATEGORY_CANDIDATES = [
    "category",
    "fine_category",
    "subcategory",
    "label",
    "class",
]

FILE_CANDIDATES = [
    "file_path",
    "filename",
    "file_name",
    "video_filename",
    "video_file",
    "video",
    "path",
    "video_path",
]


def find_column(df, candidates, column_type):
    lower_map = {col.lower(): col for col in df.columns}

    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]

    raise ValueError(
        f"Could not find {column_type} column.\n"
        f"Available columns: {list(df.columns)}\n"
        f"Expected one of: {candidates}"
    )


def resolve_video_path(value):
    value = str(value).strip()
    if not value:
        return None

    path = Path(value)
    basename = path.name

    candidates = []

    if path.is_absolute():
        candidates.append(path)

    if basename:
        candidates.extend(
            [
                VIDEOS_DIR / basename,
                FINEVIDEO_DIR / basename,
                BASE_DIR / basename,
                BASE_DIR / "data" / "FineVideo" / "videos" / basename,
                Path("data") / "FineVideo" / "videos" / basename,
            ]
        )

    # Handle Colab/Drive paths by resolving to the local basename in the workspace.
    if "FineVideo/videos" in value or "content/drive" in value.lower():
        drive_basename = value.split("/")[-1]
        if drive_basename:
            for candidate_root in [
                VIDEOS_DIR,
                FINEVIDEO_DIR / "videos",
                BASE_DIR / "data" / "FineVideo" / "videos",
                BASE_DIR / "FineVideo" / "videos",
            ]:
                candidates.append(candidate_root / drive_basename)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    if basename:
        stem = path.stem
        for extension in [".mp4", ".mov", ".mkv", ".webm", ".avi"]:
            candidate = VIDEOS_DIR / f"{stem}{extension}"
            if candidate.exists() and candidate.is_file():
                return candidate

    return None


def main():
    if not METADATA_PATH.exists():
        raise FileNotFoundError(f"metadata.csv not found at:\n{METADATA_PATH}")

    if not VIDEOS_DIR.exists():
        raise FileNotFoundError(f"videos folder not found at:\n{VIDEOS_DIR}")

    df = pd.read_csv(METADATA_PATH)

    print(f"Loaded metadata rows: {len(df)}")
    print(f"Columns: {list(df.columns)}")

    category_col = find_column(df, CATEGORY_CANDIDATES, "category")
    file_col = find_column(df, FILE_CANDIDATES, "video filename/path")

    print(f"\nUsing category column: {category_col}")
    print(f"Using video column: {file_col}")

    selected_parts = []

    for category, target_count in TARGET_COUNTS.items():
        category_df = df[
            df[category_col].astype(str).str.strip().eq(category)
        ].copy()

        if len(category_df) < target_count:
            raise ValueError(
                f"Not enough videos for '{category}'. Need {target_count}, found {len(category_df)}."
            )

        sample = category_df.sample(n=target_count, random_state=SEED)
        selected_parts.append(sample)

    pilot_df = pd.concat(selected_parts, ignore_index=True)
    pilot_df = pilot_df.sample(frac=1, random_state=SEED).reset_index(drop=True)

    OUTPUT_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    copied_files = []
    missing_files = []

    for idx, row in pilot_df.iterrows():
        source = resolve_video_path(row[file_col])

        if source is None:
            missing_files.append(
                {
                    "row": idx,
                    "category": row[category_col],
                    "metadata_value": row[file_col],
                }
            )
            copied_files.append(None)
            continue

        destination = OUTPUT_VIDEOS_DIR / source.name
        shutil.copy2(source, destination)
        copied_files.append(str(Path("videos") / source.name))

    pilot_df["pilot_video_path"] = copied_files

    if missing_files:
        print("\nMissing video files:")
        for item in missing_files:
            print(item)

        raise FileNotFoundError(
            "\nCould not locate selected videos. Nothing should be considered complete until these are fixed."
        )

    pilot_df.insert(0, "pilot_id", [f"PILOT_{i:03d}" for i in range(1, len(pilot_df) + 1)])
    pilot_df.to_csv(OUTPUT_METADATA_PATH, index=False)

    print("\nPilot dataset created successfully.")
    print(f"Total selected: {len(pilot_df)}")

    print("\nCategory distribution:")
    print(pilot_df[category_col].value_counts().sort_index())

    print(f"\nVideos copied to:\n{OUTPUT_VIDEOS_DIR}")
    print(f"\nMetadata saved to:\n{OUTPUT_METADATA_PATH}")


if __name__ == "__main__":
    main()
