"""Build shared evidence, reusing FineVideo contexts and whole-clip audit transcripts."""
import argparse
import csv
import hashlib
import json
import math
import wave
from pathlib import Path
from validate_normalized_dataset import ROOT, decode_mono_audio, write_csv
from normalized_paths import AUDIT, SELECTED, PREPROCESSED


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=SELECTED / "selected_metadata.csv")
    parser.add_argument("--audit", type=Path, default=AUDIT)
    parser.add_argument("--output", type=Path, default=PREPROCESSED)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    import numpy as np
    import opensmile
    smile = opensmile.Smile(feature_set=opensmile.FeatureSet.eGeMAPSv02, feature_level=opensmile.FeatureLevel.Functionals)
    with args.metadata.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len({r["assigned_id"] for r in rows})
    audit = {}
    with (args.audit / "checkpoint.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            result = json.loads(line)
            audit[result["assigned_id"]] = result
    for sub in ("audio", "transcripts", "context", "acoustic_features"):
        (args.output / sub).mkdir(parents=True, exist_ok=True)
    configuration = {"metadata_sha256": hashlib.sha256(args.metadata.read_bytes()).hexdigest(),
                     "audit_sha256": hashlib.sha256((args.audit / "checkpoint.jsonl").read_bytes()).hexdigest(),
                     "audio": "mono 16000 Hz PCM signed 16-bit WAV", "acoustics": "eGeMAPSv02 Functionals",
                     "transcripts": "Reuse existing FineVideo transcripts; otherwise full-clip audit segments, no second ASR",
                     "opensmile_version": opensmile.__version__}
    config_path = args.output / "configuration.json"
    if config_path.exists() and json.loads(config_path.read_text()) != configuration:
        raise ValueError("Inputs/settings changed; use a new preprocessing output version")
    config_path.write_text(json.dumps(configuration, indent=2))
    processed, failures = [], []
    for index, row in enumerate(rows[:args.limit] if args.limit else rows, 1):
        key = row["assigned_id"]
        context_path = args.output / "context" / f"{key}.json"
        audio_path = args.output / "audio" / f"{key}.wav"
        transcript_path = args.output / "transcripts" / f"{key}.txt"
        try:
            if not (context_path.exists() and audio_path.exists() and transcript_path.exists()):
                path = Path(row["file_path"])
                if not path.is_absolute():
                    path = ROOT / path
                if not audio_path.exists():
                    samples = decode_mono_audio(path)
                    temporary = audio_path.with_suffix(".tmp")
                    with wave.open(str(temporary), "wb") as handle:
                        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
                        handle.writeframes(np.clip(np.rint(samples * 32768), -32768, 32767).astype('<i2').tobytes())
                    temporary.replace(audio_path)
                existing = ROOT / row["context_path"] if row.get("context_path") else None
                if existing and existing.is_file():
                    context = json.loads(existing.read_text(encoding="utf-8"))
                    if context.get("video_id") != key:
                        raise ValueError("Existing context ID mismatch")
                else:
                    result = audit.get(key, {})
                    if result.get("language_error") or "language_windows" not in result:
                        raise ValueError("No reusable audited transcript; resolve language audit first")
                    transcript = " ".join(w.get("text", "").strip() for w in result["language_windows"]).strip()
                    features = smile.process_file(str(audio_path)).iloc[0]
                    def value(fragments):
                        for name in features.index:
                            if all(fragment in str(name).lower() for fragment in fragments):
                                number = float(features[name])
                                return round(number, 4) if math.isfinite(number) else None
                        return None
                    acoustic = {name: value(parts) for name, parts in {
                        "mean_loudness": ("loudness", "amean"), "loudness_variability": ("loudness", "stddev"),
                        "mean_pitch": ("f0semitone", "amean"), "pitch_variability": ("f0semitone", "stddev"),
                        "spectral_flux": ("spectralflux", "amean"), "sound_level_db": ("equivalentsoundlevel",)}.items()}
                    raw = {str(k): float(v) if math.isfinite(float(v)) else None for k, v in features.items()}
                    (args.output / "acoustic_features" / f"{key}.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
                    context = {"video_id": key, "transcript": transcript, "acoustic_features": acoustic,
                               "metadata_caption": row.get("metadata_caption", ""), "caption_priority": "low"}
                transcript_path.write_text(context["transcript"], encoding="utf-8")
                temporary = context_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                temporary.replace(context_path)
            saved = json.loads(context_path.read_text(encoding="utf-8"))
            if saved.get("video_id") != key or not isinstance(saved.get("acoustic_features"), dict):
                raise ValueError("Invalid completed context")
            processed.append({**row, "audio_path": str(audio_path), "context_path": str(context_path),
                              "transcript_path": str(transcript_path), "preprocessing_status": "complete"})
            print(f"OK {key} {index}/{len(rows)}", flush=True)
        except Exception as error:
            failure = {"video_id": key, "error": f"{type(error).__name__}: {error}"}
            failures.append(failure)
            with (args.output / "failures.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(failure) + "\n")
            print(f"FAILED {key}: {failure['error']}", flush=True)
    if processed:
        write_csv(args.output / "ready_metadata.csv", processed, list(processed[0]))
    (args.output / "status.json").write_text(json.dumps({"selected": len(rows), "completed_checked_this_run": len(processed), "failed_this_run": len(failures), "limited_run": bool(args.limit)}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
