"""Build a source-preserving Ataraxia inventory; never infer speech from metadata."""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = {
    "Comedy": "Parodies|Pranks|Sketches|Stand-up|comedy|Comedy",
    "Entertainment & Animation": "entertainment|Entertainment|Film & Animation|challenge_stunts|vfx_magic",
    "Lifestyle, Vlogs & Relationships": "Daily Vlogs|Storytime|lifestyle|family|relationships|People & Blogs",
    "Travel & Adventure": "Destination Guides|Travel Vlogs|travel|travel_adventure|Travel & Events",
    "Gaming": "Game Commentary|Game Highlights|Gameplay Tutorials|gaming|Gaming",
    "Music & Dance": "Covers|Music Videos|music|dance|Music",
    "Sports & Fitness": "Training Techniques|Workout Routines|fitness|sports|sports_trick_shots|Sports",
    "Science & Technology": "Biology|Physics|Science Explainers|high_speed_science|tech_review|Science & Technology",
    "Education": "Education|animation_edu",
    "Mental Health & Motivation": "Mental Health Tips|Motivational Talks",
    "Beauty & Style": "Makeup Tutorials|beauty|How-to & Style",
    "Food & Cooking": "food|cooking_food",
    "Nature, Animals & Conservation": "Conservation Efforts|animals|Pets & Animals",
    "DIY, Crafts & Outdoor Hobbies": "Camping|diy_crafts",
    "Religion & Spirituality": "islamic",
    "News, Politics & Social Issues": "political|News & Politics|Nonprofits & Activism",
    "Vehicles": "Cars & Vehicles",
    "ASMR": "asmr",
    "Unmapped / Needs Review": "",
}
MAPPING = {original: broad for broad, labels in TAXONOMY.items()
           for original in labels.split("|") if original}
SOURCES = [
    ("finevideo", "data/FineVideo/metadata.csv"),
    ("tiktok", "data/fyp_videos_1250/fyp_videos_1250_metadata.csv"),
    ("youtube", "data/youtube_shorts/metadata.csv"),
    ("youtube", "data/youtube_shorts/metadata_candidate_download_manifest.csv"),
    ("youtube", "data/youtube_shorts/english_500/metadata_downloaded.csv"),
    ("youtube_master", "data/yt_shorts_master/youtube_shorts_master.csv"),
]


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fields} for row in rows)


def path_string(path):
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def youtube_id(row):
    if row.get("video_id"):
        return row["video_id"].strip()
    url = row.get("source_url") or row.get("short_url") or ""
    match = re.search(r"(?:shorts/|youtu.be/|[?&]v=)([A-Za-z0-9_-]{11})(?:[/?&]|$)", url)
    return match.group(1) if match else ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/normalized")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Output exists; use --output for a new inventory version")
    args.output.mkdir(parents=True)
    # Restrict discovery to source-media trees, including restored sibling collections.
    media_roots = [ROOT / "data/FineVideo/videos", ROOT / "data/fyp_videos_1250/videos",
                   ROOT / "data/youtube_shorts/videos", ROOT / "data/youtube_shorts/english_500/videos",
                   ROOT / "data/yt_shorts_master/videos",
                   ROOT / "data/youtube_shorts_drive/videos",
                   ROOT.parent / "FineVideo/FineVideo/videos",
                   ROOT.parent / "fyp_videos_1250/videos",
                   ROOT.parent / "youtube_shorts/youtube_shorts/videos",
                   ROOT.parent / "youtube_shorts/youtube_shorts/english_500/videos",
                   ROOT.parent / "yt_shorts_master/videos"]
    media = defaultdict(list)
    for folder in media_roots:
        if folder.exists():
            for path in sorted(folder.rglob("*.mp4")):
                if not path.name.startswith("._") and "__MACOSX" not in path.parts:
                    media[path.stem].append(path.resolve())
    pilot = {r["assigned_id"] for r in read(ROOT / "pilot_50_reels_30h/pilot_metadata.csv")}
    languages = {}
    orientations = {}
    for folder in ("FineVideo", "youtube_shorts"):
        path = ROOT / f"data/{folder}/language_manifest.csv"
        if path.exists():
            languages.update({r["assigned_id"]: r for r in read(path)})
    orientations = {r["assigned_id"]: r for r in read(ROOT / "data/FineVideo/orientation_manifest.csv")}
    records = {}
    aliases, provenance, issues, hashes, mappings = [], [], [], {}, set()
    sources = SOURCES.copy()
    drive_metadata = "data/youtube_shorts_drive/metadata/youtube_shorts_master.csv"
    if (ROOT / drive_metadata).is_file():
        sources.append(("youtube_master", drive_metadata))
    for kind, relative in sources:
        source = ROOT / relative
        hashes[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
        source_seen = set()
        for number, raw in enumerate(read(source), 2):
            legacy = raw.get("assigned_id", "").strip()
            sid = legacy if kind == "finevideo" else raw.get("id", "").strip() if kind == "tiktok" else youtube_id(raw)
            valid = bool(re.fullmatch(r"FV\d{6}", sid)) if kind == "finevideo" else bool(re.fullmatch(r"\d+", sid)) if kind == "tiktok" else bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", sid))
            if not valid:
                issues.append({"source_manifest": relative, "row": number, "issue": "invalid_source_id", "value": sid})
                continue
            canonical = sid if kind == "finevideo" else ("TT_" if kind == "tiktok" else "YT_") + sid
            if canonical in source_seen:
                issues.append({"source_manifest": relative, "row": number, "issue": "duplicate_id_in_source", "value": canonical})
            source_seen.add(canonical)
            category = raw.get("category", "").strip()
            broad = MAPPING.get(category, "Unmapped / Needs Review")
            mappings.add((kind, category, broad))
            aliases.append({"assigned_id": canonical, "source_id": sid, "legacy_id": legacy, "source_manifest": relative})
            provenance.append({"assigned_id": canonical, "source_manifest": relative, "source_row": number,
                               "category_original": category, "source_file_path": raw.get("file_path", raw.get("filename", "")),
                               "raw_record_json": json.dumps(raw, ensure_ascii=False)})
            if canonical in records:
                row = records[canonical]
                row["source_record_count"] += 1
                if category and category != row["category_original"]:
                    row["category_conflict"] = True
                for path in media.get(sid, []) + media.get(legacy, []) if legacy else media.get(sid, []):
                    row["_paths"].add(path)
                continue
            paths = set(media.get(sid, []) + (media.get(legacy, []) if legacy else []))
            language = languages.get(legacy, {})
            accepted = language.get("status") == "keep_target_language"
            orientation = orientations.get(legacy, {})
            context = ROOT / f"data/FineVideo/preprocessed/context/{legacy}.json" if kind == "finevideo" else ROOT / f"data/normalized/preprocessed/context/{canonical}.json"
            transcript = ROOT / f"data/FineVideo/preprocessed/transcripts/{legacy}.txt" if kind == "finevideo" else ROOT / f"data/normalized/preprocessed/transcripts/{canonical}.txt"
            records[canonical] = {
                "assigned_id": canonical, "video_id": canonical, "source_id": sid,
                "platform": "finevideo" if kind == "finevideo" else "tiktok" if kind == "tiktok" else "youtube",
                "collection": kind, "source_dataset": raw.get("source_dataset", ""),
                "source_manifest": relative, "source_record_count": 1,
                "category_original": category, "category": broad, "category_conflict": False,
                "title": raw.get("title", ""), "description": raw.get("desc", raw.get("description", "")),
                "metadata_caption": raw.get("desc") or raw.get("description") or raw.get("title", ""),
                "source_url": raw.get("url") or raw.get("webpage_url") or raw.get("source_url") or raw.get("short_url", ""),
                "country": raw.get("country", ""), "creator_id": raw.get("channel_id", ""),
                "duration_reported": raw.get("duration", raw.get("duration_s", "")),
                "display_width_reported": orientation.get("display_width", raw.get("display_width", raw.get("width", ""))),
                "display_height_reported": orientation.get("display_height", raw.get("display_height", raw.get("height", ""))),
                "orientation": orientation.get("orientation", "unknown"),
                "orientation_status": "historical_probe" if orientation else "pending_probe",
                "language": language.get("detected_language", ""),
                "language_status": "historical_target_approved" if accepted else language.get("status", "pending_audio_audit"),
                "language_scan_method": language.get("scan_method", ""),
                "split_original": raw.get("split", ""), "split": "original_pilot" if legacy in pilot else "unassigned",
                "context_path": path_string(context) if context.exists() else "",
                "transcript_path": path_string(transcript) if transcript.exists() else "",
                "preprocessing_status": "existing_context_and_transcript" if context.exists() and transcript.exists() else "pending",
                "raw_audio_access": "model_specific", "_paths": paths,
            }
    digest_groups = defaultdict(list)
    for index, row in enumerate(records.values()):
        paths = sorted(row.pop("_paths"), key=lambda p: (not p.is_relative_to(ROOT), str(p)))
        paths = [p for p in paths if p.stat().st_size > 0]
        row["file_path"] = path_string(paths[0]) if paths else ""
        row["file_path_scope"] = "project_relative" if paths and paths[0].is_relative_to(ROOT) else "external_absolute" if paths else "unavailable"
        row["alternate_media_paths"] = json.dumps([path_string(p) for p in paths[1:]])
        row["media_status"] = "available_not_decode_validated" if paths else "missing"
        row["media_size_bytes"] = paths[0].stat().st_size if paths else ""
        row["media_sha256"] = ""
        if paths:
            h = hashlib.sha256()
            with paths[0].open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    h.update(chunk)
            row["media_sha256"] = h.hexdigest()
            digest_groups[h.hexdigest()].append(row["assigned_id"])
        row["selection_status"] = "pending_validation" if paths else "unavailable"
        row["duplicate_group"] = ""
        row["duplicate_representative"] = row["assigned_id"]
        if (index + 1) % 10000 == 0:
            print(f"Indexed {index + 1} records", flush=True)
    for digest, ids in digest_groups.items():
        if len(ids) > 1:
            representative = min(ids, key=lambda key: (records[key]["split"] != "original_pilot", key))
            for key in ids:
                records[key]["duplicate_group"] = digest
                records[key]["duplicate_representative"] = representative
                if key != representative:
                    records[key]["selection_status"] = "duplicate_content"
    rows = sorted(records.values(), key=lambda r: r["assigned_id"])
    fields = list(rows[0])
    write_csv(args.output / "inventory.csv", rows, fields)
    candidates = [r for r in rows if r["file_path"] and r["duplicate_representative"] == r["assigned_id"]]
    write_csv(args.output / "local_candidates.csv", candidates, fields)
    write_csv(args.output / "preprocessing_queue.csv", [r for r in candidates if r["preprocessing_status"] == "pending"], fields)
    write_csv(args.output / "id_aliases.csv", aliases, ["assigned_id", "source_id", "legacy_id", "source_manifest"])
    write_csv(args.output / "source_records.csv", provenance, list(provenance[0]))
    write_csv(args.output / "category_mapping.csv", [dict(zip(["source", "category_original", "category"], item)) for item in sorted(mappings)], ["source", "category_original", "category"])
    write_csv(args.output / "validation_issues.csv", issues, ["source_manifest", "row", "issue", "value"])
    summary = {"schema_version": "ataraxia-normalized-v1", "source_sha256": hashes,
               "source_records": len(provenance), "unique_videos": len(rows),
               "local_unique_candidates": len(candidates), "media_available": sum(bool(r["file_path"]) for r in rows),
               "exact_content_duplicate_groups": sum(len(ids) > 1 for ids in digest_groups.values()),
               "original_pilot_count": sum(r["split"] == "original_pilot" for r in rows),
               "category_conflicts": sum(r["category_conflict"] for r in rows), "validation_issues": len(issues),
               "by_platform": dict(Counter(r["platform"] for r in rows)),
               "local_categories": dict(sorted(Counter(r["category"] for r in candidates).items())),
               "language_status": dict(Counter(r["language_status"] for r in candidates)),
               "preprocessing_status": dict(Counter(r["preprocessing_status"] for r in candidates)),
               "limitations": ["Available does not mean fully decodable or language eligible", "Historical language audit may inspect only initial speech", "Different hashes do not rule out reposts", "External media paths require restoration for portability", "Broad source categories are metadata groupings, not content-verified labels", "No final selection or new study splits frozen; horizontal cap must be enforced after eligibility", "Existing FineVideo-only held out selection is provisional and unchanged"]}
    assert len({r["assigned_id"] for r in rows}) == len(rows)
    assert summary["original_pilot_count"] == 50
    for relative, digest in hashes.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
    (args.output / "validation_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    report = ["# Normalized Ataraxia dataset", "", "Created 2026-10-08. Original metadata, media, annotations and prior study outputs are unchanged.", "",
              f"{len(rows):,} unique platform identities from {len(provenance):,} source records; {len(candidates):,} local byte-unique representatives.", "",
              "The large YouTube metadata catalogue remains inventory-only when media is absent. Local availability and eligibility are separate.", "",
              "## Local category distribution", "", "| Shared category | Local representatives |", "| --- | ---: |"]
    report += [f"| {key} | {value} |" for key, value in summary["local_categories"].items()]
    report += ["", "## Interface and remaining work", "", "inventory.csv retains all canonical IDs; source_records.csv preserves every source row and original metadata. id_aliases.csv connects historical YT IDs to platform identities. category_mapping.csv documents broad mappings; conflicts remain flagged. Native media is referenced without copying, resizing or renaming.", "", "FineVideo contexts/transcripts are reused by path; pending evidence is listed in preprocessing_queue.csv. This is metadata/interface normalization, not completed audiovisual preprocessing.", "", "Next: validate decoding and orientation, audit speech across clips, produce matching 16 kHz mono PCM audio/transcripts/eGeMAPS/context bundles with a CUDA-compatible backend, resolve category conflicts and unmapped labels, then enforce the <=30% horizontal constraint and freeze eligible metadata. Do not sample the combined held-out cohort until these eligibility decisions are recorded.", "", "## Limitations", ""]
    report += [f"- {value}" for value in summary["limitations"]]
    report += ["", "## Reproduce", "", "Run `.venv-qwen-cuda/Scripts/python.exe src/build_normalized_dataset.py --output data/normalized_v2` from the project root. The builder refuses to overwrite an existing inventory version. Restore sibling source-media folders or update media roots for another machine."]
    (args.output / "normalization_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("unique_videos", "local_unique_candidates", "original_pilot_count", "category_conflicts", "validation_issues")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
