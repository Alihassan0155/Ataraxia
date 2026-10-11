"""Resumable native-media and whole-clip speech-language audit. No source edits."""
import argparse
import csv
import hashlib
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from normalized_paths import METADATA, AUDIT

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"en", "hi", "ur"}


def language_decision(windows):
    speech = [w for w in windows if w["speech_characters"] >= 5]
    if not speech:
        return "review_no_detected_speech"
    languages = {w["language"] for w in speech}
    if any(w["probability"] < 0.80 for w in speech):
        return "review_low_confidence"
    if len(languages) != 1:
        return "review_mixed_language"
    return "target_language_candidate" if languages <= TARGETS else "review_non_target_language"


def media_audit(path):
    import av
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("No video stream")
        stream = container.streams.video[0]
        stream.codec_context.thread_count = 2
        frame_count, first, last_timestamp = 0, None, 0.0
        for frame in container.decode(stream):
            if frame.is_corrupt:
                raise ValueError("Corrupt decoded video frame")
            if first is None:
                first = frame
            frame_count += 1
            if frame.time is not None:
                last_timestamp = max(last_timestamp, float(frame.time))
        if first is None:
            raise ValueError("No decodable video frames")
        rotation = int(round(float(getattr(first, "rotation", stream.metadata.get("rotate", 0))))) % 360
        width, height = first.width, first.height
        if rotation in (90, 270):
            width, height = height, width
        if rotation not in (0, 90, 180, 270):
            orientation = "unknown"
        else:
            orientation = "vertical" if height > width else "horizontal" if width > height else "square"
        return {"media_status": "full_video_decode_passed", "media_sha256": digest.hexdigest(),
                "decoded_frames": frame_count, "duration_seconds": float(container.duration / av.time_base) if container.duration else last_timestamp,
                "display_width": width, "display_height": height, "rotation_degrees": rotation,
                "orientation": orientation, "has_audio": bool(container.streams.audio), "media_error": ""}


def decode_mono_audio(path):
    """Decode strictly using the installed PyAV API, then resample to 16 kHz mono."""
    import av
    import numpy as np
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
    chunks = []
    with av.open(str(path), mode="r") as container:
        if not container.streams.audio:
            raise ValueError("No audio stream")
        for frame in container.decode(audio=0):
            if frame.is_corrupt:
                raise ValueError("Corrupt audio frame")
            frame.pts = None
            for output in resampler.resample(frame):
                chunks.append(output.to_ndarray().reshape(-1))
        for output in resampler.resample(None):
            chunks.append(output.to_ndarray().reshape(-1))
    if not chunks:
        raise ValueError("Audio stream has no decoded samples")
    audio = np.concatenate(chunks).astype(np.float32, copy=False)
    if not np.isfinite(audio).all():
        raise ValueError("Nonfinite audio samples")
    return audio


def speech_audit(path, model):
    audio = decode_mono_audio(path)
    windows = []
    # Adjacent 30-second windows cover the whole audio; each detects its own language.
    for offset in range(0, len(audio), 30 * 16000):
        chunk = audio[offset:offset + 30 * 16000]
        if not len(chunk):
            continue
        segments, info = model.transcribe(chunk, language=None, beam_size=1,
                                          temperature=0, vad_filter=True,
                                          condition_on_previous_text=False)
        segments = list(segments)
        text = " ".join(s.text.strip() for s in segments)
        windows.append({"start_seconds": offset / 16000, "end_seconds": (offset + len(chunk)) / 16000,
                        "language": info.language, "probability": float(info.language_probability),
                        "speech_characters": len(text.strip()), "text": text,
                        "segments": [{"start": offset / 16000 + s.start, "end": offset / 16000 + s.end,
                                      "text": s.text, "no_speech_probability": s.no_speech_prob} for s in segments]})
    return {"language_status": language_decision(windows), "language_windows": windows,
            "language_error": "", "audio_decode_status": "full_audio_decode_passed"}


def write_csv(path, rows, fields):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(row[k], ensure_ascii=False) if isinstance(row.get(k), (list, dict)) else row.get(k, "") for k in fields})
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["media", "language", "all"], default="all")
    parser.add_argument("--metadata", type=Path, default=METADATA)
    parser.add_argument("--output", type=Path, default=AUDIT)
    parser.add_argument("--resume-media-from", type=Path,
                        help="Reuse media checks from an earlier audit; recheck file signatures")
    parser.add_argument("--model", default="Systran/faster-whisper-large-v3")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20261008)
    args = parser.parse_args()
    with args.metadata.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len({r["assigned_id"] for r in rows}), "Duplicate input IDs"
    args.output.mkdir(parents=True, exist_ok=True)
    config = {"input_sha256": hashlib.sha256(args.metadata.read_bytes()).hexdigest(),
              "model": args.model, "device": args.device, "compute_type": "int8_float16" if args.device == "cuda" else "int8",
              "language_threshold": 0.80, "window_seconds": 30, "seed": args.seed,
              "schema_version": "audit-v1", "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    config_path = args.output / "configuration.json"
    if config_path.exists() and json.loads(config_path.read_text()) != config:
        raise ValueError("Audit settings/input changed; use a new --output directory")
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    checkpoint = args.output / "checkpoint.jsonl"
    results = {}
    if checkpoint.exists():
        for number, line in enumerate(checkpoint.read_text(encoding="utf-8").splitlines(), 1):
            try:
                result = json.loads(line)
            except json.JSONDecodeError:
                raise ValueError(f"Checkpoint line {number} is incomplete; preserve it and repair before resuming")
            results[result["assigned_id"]] = result
    if args.resume_media_from:
        previous_config = json.loads((args.resume_media_from / "configuration.json").read_text())
        if previous_config["input_sha256"] != config["input_sha256"]:
            raise ValueError("Previous media audit used different input metadata")
        media_keys = {"assigned_id", "signature", "media_status", "media_sha256", "decoded_frames",
                      "duration_seconds", "display_width", "display_height", "rotation_degrees",
                      "orientation", "has_audio", "media_error"}
        previous = {}
        with (args.resume_media_from / "checkpoint.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                previous[record["assigned_id"]] = record
        for key, record in previous.items():
            if key not in results and record.get("media_status") == "full_video_decode_passed":
                results[key] = {k: v for k, v in record.items() if k in media_keys}
                results[key]["media_reused_from"] = str(args.resume_media_from)
        print(f"Imported media checks for {len(results)} videos; language errors not reused", flush=True)
    model = None
    dll_handles = []
    def unchanged_completed(row):
        result = results.get(row["assigned_id"], {})
        path = Path(row["file_path"])
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            return False
        signature = {"path": str(path), "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
        fields = ["media_status"] if args.phase == "media" else ["media_status", "language_status"]
        return result.get("signature") == signature and all(field in result for field in fields)
    if not args.limit and all(unchanged_completed(row) for row in rows) and (args.output / "summary.json").is_file():
        print("All requested checks are complete and source files are unchanged; preserved existing merged/historical outputs.")
        print((args.output / "summary.json").read_text())
        return
    if args.phase != "media" and any("language_status" not in results.get(row["assigned_id"], {}) for row in (rows[:args.limit] if args.limit else rows)):
        torch_lib = Path(sys.prefix) / "Lib/site-packages/torch/lib"
        if os.name == "nt" and torch_lib.exists():
            os.environ["PATH"] = str(torch_lib) + os.pathsep + os.environ.get("PATH", "")
            dll_handles.append(os.add_dll_directory(str(torch_lib)))
        from faster_whisper import WhisperModel
        print(f"Loading {args.model} on {args.device}", flush=True)
        model = WhisperModel(args.model, device=args.device, compute_type=config["compute_type"],
                             download_root=str(ROOT / ".cache/faster-whisper"))
    consecutive_language_errors = 0
    for index, row in enumerate(rows[:args.limit] if args.limit else rows, 1):
        key = row["assigned_id"]
        path = Path(row["file_path"])
        if not path.is_absolute():
            path = ROOT / path
        signature = {"path": str(path), "size": path.stat().st_size if path.exists() else None,
                     "mtime_ns": path.stat().st_mtime_ns if path.exists() else None}
        result = results.get(key, {"assigned_id": key})
        if result.get("signature") not in (None, signature):
            result = {"assigned_id": key}
        result["signature"] = signature
        if args.phase in ("media", "all") and "media_status" not in result:
            try:
                result.update(media_audit(path))
            except Exception as error:
                result.update(media_status="decode_failed", media_error=f"{type(error).__name__}: {error}")
        if args.phase in ("language", "all") and "language_status" not in result:
            if result.get("media_status") != "full_video_decode_passed":
                print(f"{index}/{len(rows)} {key}: media check required", flush=True)
                continue
            if not result["has_audio"]:
                result.update(language_status="review_no_audio_stream", language_windows=[], language_error="")
            else:
                try:
                    result.update(speech_audit(path, model))
                except Exception as error:
                    result.update(language_status="review_language_error", language_error=f"{type(error).__name__}: {error}")
        consecutive_language_errors = consecutive_language_errors + 1 if result.get("language_status") == "review_language_error" else 0
        results[key] = result
        with checkpoint.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(f"{index}/{len(rows)} {key}: {result.get('media_status')} / {result.get('language_status', 'pending_language')}", flush=True)
        if consecutive_language_errors >= 3:
            raise RuntimeError("Stopped after 3 consecutive language errors: " + result.get("language_error", "")
                               + "; checkpoint preserved. Fix the error and use a new output for retries.")
    combined, groups = [], defaultdict(list)
    for row in rows:
        result = {**row, **results.get(row["assigned_id"], {})}
        result["source_language_status"] = row.get("language_status", "")
        result["source_media_status"] = row.get("media_status", "")
        result["media_status"] = results.get(row["assigned_id"], {}).get("media_status", "pending")
        result["language_status"] = results.get(row["assigned_id"], {}).get("language_status", "pending")
        result["audit_selection_status"] = "pending"
        if result.get("media_status") == "decode_failed":
            result["audit_selection_status"] = "media_failed"
        elif result.get("language_status") == "target_language_candidate":
            result["audit_selection_status"] = "target_language_candidate"
        elif result.get("language_status", "").startswith("review_"):
            result["audit_selection_status"] = "needs_review"
        if result.get("media_status") == "full_video_decode_passed":
            groups[result["media_sha256"]].append(result)
        combined.append(result)
    for group in groups.values():
        representative = min(group, key=lambda r: (r["split"] != "original_pilot", r["assigned_id"]))
        for row in group:
            row["audit_duplicate_representative"] = representative["assigned_id"]
            if row is not representative:
                row["audit_selection_status"] = "duplicate_content"
    candidates = [r for r in combined if r["audit_selection_status"] == "target_language_candidate" and r.get("orientation") != "unknown"]
    horizontal = [r for r in candidates if r["orientation"] == "horizontal"]
    other = [r for r in candidates if r["orientation"] != "horizontal"]
    allowed = min(len(horizontal), 3 * len(other) // 7)
    protected = [r for r in horizontal if r["split"] == "original_pilot"]
    if len(protected) > allowed:
        candidates = []  # Never silently drop pilot videos to satisfy the cap.
        orientation_status = "blocked_protected_pilot_exceeds_cap"
    elif not candidates:
        orientation_status = "pending_eligible_candidates"
    else:
        selected = protected.copy()
        by_category = defaultdict(list)
        for row in horizontal:
            if row not in protected:
                by_category[row["category"]].append(row)
        rng = random.Random(args.seed)
        for pool in by_category.values():
            rng.shuffle(pool)
        while len(selected) < allowed:
            # Greedy proportional quota allocation with deterministic category ties.
            category = max((k for k, pool in by_category.items() if pool),
                           key=lambda k: (allowed * sum(r["category"] == k for r in horizontal) / len(horizontal)
                                          - sum(r["category"] == k for r in selected), k))
            selected.append(by_category[category].pop())
        candidates = other + selected
        orientation_status = "provisional_cap_passed"
    fields = sorted({key for row in combined for key in row})
    write_csv(args.output / "validation_manifest.csv", combined, fields)
    write_csv(args.output / "review_queue.csv", [r for r in combined if r["audit_selection_status"] == "needs_review" or r.get("orientation") == "unknown"], fields)
    write_csv(args.output / "provisional_selected_metadata.csv", candidates, fields)
    summary = {"total": len(rows), "media": dict(Counter(r.get("media_status", "pending") for r in combined)),
               "language": dict(Counter(r.get("language_status", "pending") for r in combined)),
               "provisional_selected": len(candidates), "orientation_status": orientation_status,
               "horizontal_selected": sum(r["orientation"] == "horizontal" for r in candidates),
               "categories": dict(Counter(r["category"] for r in candidates)),
               "note": "Model language decisions are provisional, not verified truth. Non-target, mixed, uncertain and speechless clips are retained for review. No files deleted; no annotation started. Resume with identical settings. Failure records are retained; use a new output to retry failures."}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
