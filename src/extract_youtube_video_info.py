"""Extract local media information for downloaded YouTube Shorts."""

import argparse
import csv
import json
import subprocess
from fractions import Fraction
from pathlib import Path

from tqdm import tqdm


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATASET_DIR = BASE_DIR / "data" / "youtube_shorts"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract media information without filtering any videos."
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Probe videos again even if they already have checkpoint records.",
    )
    return parser.parse_args()


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_checkpoint(path):
    records = {}
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
                records[record["assigned_id"]] = record
            except (json.JSONDecodeError, KeyError):
                continue
    return records


def append_checkpoint(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def frame_rate(value):
    if not value or value == "0/0":
        return ""
    try:
        return round(float(Fraction(value)), 3)
    except (ValueError, ZeroDivisionError):
        return ""


def rotation_for_stream(stream):
    rotation = stream.get("tags", {}).get("rotate", 0)
    for item in stream.get("side_data_list", []):
        if "rotation" in item:
            rotation = item["rotation"]
            break
    try:
        return int(float(rotation)) % 360
    except (TypeError, ValueError):
        return 0


def probe_video(video_id, video_path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration,size,format_name:"
                "stream=codec_type,codec_name,width,height,r_frame_rate,"
                "avg_frame_rate:stream_tags=rotate:stream_side_data=rotation"
            ),
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")

    info = json.loads(result.stdout)
    streams = info.get("streams", [])
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise ValueError("No video stream found")
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        None,
    )

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    rotation = rotation_for_stream(video_stream)
    if rotation in (90, 270):
        width, height = height, width

    if height > width:
        orientation = "vertical"
    elif width > height:
        orientation = "horizontal"
    else:
        orientation = "square"

    format_info = info.get("format", {})
    return {
        "assigned_id": video_id,
        "actual_duration_seconds": round(float(format_info.get("duration") or 0), 3),
        "actual_width": width,
        "actual_height": height,
        "actual_aspect_ratio": round(width / height, 6) if height else "",
        "actual_orientation": orientation,
        "fps": frame_rate(
            video_stream.get("avg_frame_rate")
            or video_stream.get("r_frame_rate")
        ),
        "video_codec": video_stream.get("codec_name", ""),
        "audio_codec": audio_stream.get("codec_name", "") if audio_stream else "",
        "container": format_info.get("format_name", ""),
        "size_bytes": int(format_info.get("size") or video_path.stat().st_size),
        "file_path": str(video_path.relative_to(BASE_DIR)),
        "extraction_status": "complete",
        "extraction_error": "",
    }


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    fieldnames = list(rows[0])
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(path)


def main():
    args = parse_args()
    dataset_dir = args.dataset_dir.resolve()
    manifest_path = dataset_dir / "metadata_candidate_download_manifest.csv"
    videos_dir = dataset_dir / "videos"
    checkpoint_path = dataset_dir / "video_info_scan.jsonl"
    output_path = dataset_dir / "metadata_downloaded.csv"

    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")

    manifest = read_csv(manifest_path)
    downloaded = [
        row
        for row in manifest
        if row.get("download_decision") == "download"
        and (videos_dir / f"{row['assigned_id']}.mp4").is_file()
    ]
    checkpoint = {} if args.force else load_checkpoint(checkpoint_path)
    pending = [row for row in downloaded if row["assigned_id"] not in checkpoint]

    print(f"Downloaded videos found: {len(downloaded):,}")
    print(f"Already extracted: {len(downloaded) - len(pending):,}")
    print(f"Pending extraction: {len(pending):,}")

    for row in tqdm(pending, unit="video"):
        video_id = row["assigned_id"]
        video_path = videos_dir / f"{video_id}.mp4"
        try:
            record = probe_video(video_id, video_path)
        except Exception as error:
            record = {
                "assigned_id": video_id,
                "actual_duration_seconds": "",
                "actual_width": "",
                "actual_height": "",
                "actual_aspect_ratio": "",
                "actual_orientation": "unknown",
                "fps": "",
                "video_codec": "",
                "audio_codec": "",
                "container": "",
                "size_bytes": video_path.stat().st_size,
                "file_path": str(video_path.relative_to(BASE_DIR)),
                "extraction_status": "error",
                "extraction_error": f"{type(error).__name__}: {error}",
            }
        checkpoint[video_id] = record
        append_checkpoint(checkpoint_path, record)

    output = [{**row, **checkpoint[row["assigned_id"]]} for row in downloaded]
    if not output:
        raise RuntimeError("No downloaded videos were found")
    write_csv(output_path, output)

    complete = sum(row["extraction_status"] == "complete" for row in output)
    errors = len(output) - complete
    print(f"Video information extracted: {complete:,}")
    print(f"Extraction errors retained: {errors:,}")
    print(f"Final metadata: {output_path}")


if __name__ == "__main__":
    main()
