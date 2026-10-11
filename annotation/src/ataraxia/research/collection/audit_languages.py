from ataraxia.runtime.config import project_root
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import mlx.core as mx
import mlx_whisper
from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim
from mlx_whisper.load_models import load_model
from tqdm import tqdm


BASE_DIR = project_root()
DATASET_DIR = BASE_DIR / "data" / "FineVideo"
METADATA_PATH = DATASET_DIR / "metadata.csv"
VIDEOS_DIR = DATASET_DIR / "videos"
CHECKPOINT_PATH = DATASET_DIR / "language_scan.jsonl"
MANIFEST_PATH = DATASET_DIR / "language_manifest.csv"
PILOT_METADATA_PATH = (
    BASE_DIR / "pilot_50_reels_30h" / "pilot_metadata.csv"
)

MODEL_ID = "mlx-community/whisper-large-v3-turbo"
TARGET_LANGUAGES = {"en", "hi", "ur"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Audit spoken languages in the FineVideo collection."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most this many metadata rows; 0 means all rows.",
    )
    return parser.parse_args()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_checkpoint():
    completed = {}
    if not CHECKPOINT_PATH.exists():
        return completed

    for line in CHECKPOINT_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            completed[row["video_id"]] = row
        except (json.JSONDecodeError, KeyError):
            continue
    return completed


def append_checkpoint(result):
    with CHECKPOINT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False) + "\n")


def resolve_video(row):
    video_id = row["assigned_id"]
    preferred = VIDEOS_DIR / f"{video_id}.mp4"
    if preferred.exists():
        return preferred

    fallback = VIDEOS_DIR / Path(row.get("file_path", "")).name
    if fallback.exists():
        return fallback

    raise FileNotFoundError(f"No source video found for {video_id}")


def audit_video(row, model):
    video_id = row["assigned_id"]
    video_path = resolve_video(row)

    try:
        mel = log_mel_spectrogram(
            str(video_path),
            n_mels=model.dims.n_mels,
            padding=N_SAMPLES,
        )
        mel_segment = pad_or_trim(
            mel,
            N_FRAMES,
            axis=-2,
        ).astype(mx.float16)
        _, probabilities = model.detect_language(mel_segment)
        detected_language, confidence = max(
            probabilities.items(),
            key=lambda item: item[1],
        )

        if detected_language in TARGET_LANGUAGES:
            status = "keep_target_language"
        elif confidence >= 0.80:
            status = "remove_non_target_language"
        else:
            status = "review_uncertain_or_no_speech"

        return {
            "video_id": video_id,
            "detected_language": detected_language or "unknown",
            "language_confidence": float(confidence),
            "status": status,
            "speech_characters_first_30s": "",
            "mean_no_speech_probability": "",
            "scan_method": "whisper_language_id_first_30s",
            "error": "",
        }
    except Exception as error:
        return {
            "video_id": video_id,
            "detected_language": "unknown",
            "language_confidence": "",
            "status": "review_scan_error",
            "speech_characters_first_30s": 0,
            "mean_no_speech_probability": None,
            "scan_method": "whisper_language_id_first_30s",
            "error": f"{type(error).__name__}: {error}",
        }


def write_manifest(metadata_rows, results):
    output_rows = []
    for row in metadata_rows:
        result = results.get(row["assigned_id"])
        if result is None:
            continue
        output_rows.append({**row, **result})

    extra_fields = [
        "video_id",
        "detected_language",
        "language_confidence",
        "status",
        "speech_characters_first_30s",
        "mean_no_speech_probability",
        "scan_method",
        "error",
    ]
    fields = list(metadata_rows[0]) + extra_fields

    with MANIFEST_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)


def print_counts(metadata_rows, results):
    scanned_ids = set(results)
    status_counts = Counter(
        result["status"] for result in results.values()
    )
    language_counts = Counter(
        result["detected_language"] for result in results.values()
    )

    print("\nFULL DATASET")
    print(f"Metadata rows: {len(metadata_rows)}")
    print(f"Scanned: {len(scanned_ids)}")
    print(f"Pending: {len(metadata_rows) - len(scanned_ids)}")
    for status, count in sorted(status_counts.items()):
        print(f"{status}: {count}")
    print("Detected languages:")
    for language, count in language_counts.most_common():
        print(f"  {language}: {count}")

    if not PILOT_METADATA_PATH.exists():
        return

    pilot_rows = read_csv(PILOT_METADATA_PATH)
    pilot_ids = {row["assigned_id"] for row in pilot_rows}
    pilot_results = {
        video_id: result
        for video_id, result in results.items()
        if video_id in pilot_ids
    }
    pilot_status = Counter(
        result["status"] for result in pilot_results.values()
    )
    pilot_languages = Counter(
        result["detected_language"]
        for result in pilot_results.values()
    )

    print("\nACTIVE PILOT")
    print(f"Pilot rows: {len(pilot_rows)}")
    print(f"Scanned: {len(pilot_results)}")
    print(f"Pending: {len(pilot_rows) - len(pilot_results)}")
    for status, count in sorted(pilot_status.items()):
        print(f"{status}: {count}")
    print("Detected languages:")
    for language, count in pilot_languages.most_common():
        print(f"  {language}: {count}")


def main():
    args = parse_args()
    metadata_rows = read_csv(METADATA_PATH)
    if args.limit > 0:
        metadata_rows = metadata_rows[: args.limit]

    results = load_checkpoint()
    selected_ids = {row["assigned_id"] for row in metadata_rows}
    results = {
        video_id: result
        for video_id, result in results.items()
        if video_id in selected_ids
    }

    pending_rows = [
        row
        for row in metadata_rows
        if row["assigned_id"] not in results
    ]

    print(f"Rows selected: {len(metadata_rows)}")
    print(f"Already scanned: {len(results)}")
    print(f"Pending: {len(pending_rows)}")

    model = None
    if pending_rows:
        model = load_model(MODEL_ID, dtype=mx.float16)

    for row in tqdm(pending_rows, unit="video"):
        result = audit_video(row, model)
        results[result["video_id"]] = result
        append_checkpoint(result)

    write_manifest(metadata_rows, results)
    print_counts(metadata_rows, results)
    print(f"\nManifest: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
