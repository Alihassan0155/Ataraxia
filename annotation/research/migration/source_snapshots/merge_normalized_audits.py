"""Combine finished audits, preserving originals and per-video checkpoint evidence."""
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from normalized_paths import ROOT, METADATA, AUDIT, SELECTED, PREPROCESSED, HELDOUT
from validate_normalized_dataset import write_csv

SOURCES = [ROOT / "data/normalized/audit_v2", ROOT / "data/normalized/audit_yt_master_new"]


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if AUDIT.exists() or METADATA.parent.exists():
        raise FileExistsError("Merged output already exists; preserve it rather than overwriting review work")
    records, checkpoints, provenance, config = {}, {}, [], None
    for source in SOURCES:
        current_config = json.loads((source / "configuration.json").read_text())
        comparable = {k: current_config[k] for k in ("model", "device", "compute_type", "language_threshold", "window_seconds", "seed", "schema_version")}
        if config is not None and config != comparable:
            raise ValueError("Audit methods differ; do not silently merge them")
        config = comparable
        latest = {}
        with (source / "checkpoint.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                result = json.loads(line)
                latest[result["assigned_id"]] = result
        for row in read(source / "validation_manifest.csv"):
            key = row["assigned_id"]
            if key in records:
                raise ValueError(f"Overlapping or duplicate input ID: {key}")
            result = latest.get(key)
            if not result or result.get("media_status") != "full_video_decode_passed" or not result.get("language_status") or result["language_status"] == "review_language_error":
                raise ValueError(f"Missing/failed/incomplete checkpoint: {key}")
            if row["language_status"] != result["language_status"] or row["media_sha256"] != result["media_sha256"]:
                raise ValueError(f"Checkpoint/manifest mismatch: {key}")
            row["audit_source"] = str(source.relative_to(ROOT)).replace('\\', '/')
            records[key] = row
            checkpoints[key] = dict(result)
        provenance.append({"folder": str(source.relative_to(ROOT)), "input_count": len(latest),
                           "sha256": {name: sha(source / name) for name in ("configuration.json", "checkpoint.jsonl", "validation_manifest.csv", "summary.json")}})
    assert len(records) == 4320
    original = read(ROOT / "data/normalized/local_candidates.csv") + read(ROOT / "data/normalized/yt_master_new_624.csv")
    assert {r["assigned_id"] for r in original} == set(records)
    # Prefer the now-complete master folder; reuse the verified Drive-copy hashes.
    master = {"YT_" + r["video_id"]: r for r in read(ROOT / "data/youtube_shorts_drive/mapped_metadata.csv")}
    for key, row in records.items():
        result = checkpoints[key]
        if key in master:
            candidate = ROOT / "data/yt_shorts_master/videos" / (master[key]["video_id"] + ".mp4")
            if not candidate.is_file() or candidate.stat().st_size != int(master[key]["file_size_bytes"]) or master[key]["media_sha256"] != result["media_sha256"]:
                raise ValueError(f"Master copy is inconsistent with the audited content: {key}")
            row["original_audited_file_path"] = row["file_path"]
            row["file_path"] = candidate.relative_to(ROOT).as_posix()
            row["file_path_scope"] = "project_relative"
            result["original_audited_signature"] = result["signature"]
            result["signature"] = {"path": str(candidate), "size": candidate.stat().st_size, "mtime_ns": candidate.stat().st_mtime_ns}
            row["signature"] = json.dumps(result["signature"])
        path = Path(row["file_path"])
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file() or path.stat().st_size != result["signature"]["size"]:
            raise ValueError(f"Audited local file unavailable or changed: {key}")
        result["audit_source"] = row["audit_source"]
    # Recompute cross-audit duplicates and global orientation selection.
    grouped = defaultdict(list)
    for row in records.values():
        row["audit_selection_status"] = "target_language_candidate" if row["language_status"] == "target_language_candidate" else "needs_review"
        grouped[row["media_sha256"]].append(row)
    duplicates = []
    for digest, group in grouped.items():
        representative = min(group, key=lambda r: (r["split"] != "original_pilot", r["assigned_id"]))
        for row in group:
            row["audit_duplicate_representative"] = representative["assigned_id"]
            if row is not representative:
                row["audit_selection_status"] = "duplicate_content"
        if len(group) > 1:
            duplicates.append({"sha256": digest, "representative": representative["assigned_id"], "ids": [r["assigned_id"] for r in group]})
    rows = sorted(records.values(), key=lambda r: r["assigned_id"])
    candidates = [r for r in rows if r["audit_selection_status"] == "target_language_candidate" and r["orientation"] != "unknown"]
    horizontal = [r for r in candidates if r["orientation"] == "horizontal"]
    other = [r for r in candidates if r["orientation"] != "horizontal"]
    cap = min(len(horizontal), 3 * len(other) // 7)
    chosen = [r for r in horizontal if r["split"] == "original_pilot"]
    if len(chosen) > cap:
        raise ValueError("Cannot preserve eligible pilot videos within horizontal cap")
    rng = random.Random(config["seed"])
    pools = defaultdict(list)
    for row in horizontal:
        if row not in chosen:
            pools[row["category"]].append(row)
    for pool in pools.values():
        rng.shuffle(pool)
    targets = Counter(r["category"] for r in horizontal)
    while len(chosen) < cap:
        category = max((k for k, v in pools.items() if v), key=lambda k: (cap * targets[k] / len(horizontal) - sum(r["category"] == k for r in chosen), k))
        chosen.append(pools[category].pop())
    selected = sorted(other + chosen, key=lambda r: r["assigned_id"])
    assert not selected or len(chosen) / len(selected) <= .30
    AUDIT.mkdir(parents=True)
    METADATA.parent.mkdir(parents=True)
    fields = sorted({k for r in rows for k in r})
    write_csv(METADATA, rows, fields)
    write_csv(AUDIT / "validation_manifest.csv", rows, fields)
    review = [r for r in rows if r["audit_selection_status"] == "needs_review" or r["orientation"] == "unknown" or r["category"] == "Unmapped / Needs Review" or r.get("category_conflict") == "True"]
    write_csv(AUDIT / "review_queue.csv", review, fields)
    write_csv(AUDIT / "provisional_selected_metadata.csv", selected, fields)
    with (AUDIT / "checkpoint.jsonl").open("w", encoding="utf-8") as handle:
        for key in sorted(checkpoints):
            handle.write(json.dumps(checkpoints[key], ensure_ascii=False) + '\n')
    configuration = {"input_sha256": sha(METADATA), **config, "script_sha256": sha(ROOT / "src/validate_normalized_dataset.py")}
    (AUDIT / "configuration.json").write_text(json.dumps(configuration, indent=2))
    summary = {"total": len(rows), "unique_ids": len(records), "input_overlap": 0,
               "media": dict(Counter(r["media_status"] for r in rows)),
               "language": dict(Counter(r["language_status"] for r in rows)),
               "provisional_selected": len(selected), "horizontal_selected": len(chosen),
               "orientation_status": "provisional_cap_passed", "review_queue_rows": len(review),
               "categories": dict(Counter(r["category"] for r in selected)),
               "full_category_distribution": dict(Counter(r["category"] for r in rows)),
               "orientation": dict(Counter(r["orientation"] for r in rows)),
               "duplicate_groups": duplicates, "sources": provenance,
               "note": "Active combined audit. Language screening is provisional; unmapped/conflicting categories still need review. Provisional selection has not applied category-review decisions. Original audits and pilot evidence preserved; no preprocessing or annotation launched."}
    (AUDIT / "summary.json").write_text(json.dumps(summary, indent=2))
    active = {"metadata": str(METADATA.relative_to(ROOT)).replace('\\', '/'),
              "audit": str(AUDIT.relative_to(ROOT)).replace('\\', '/'),
              "selected": str(SELECTED.relative_to(ROOT)).replace('\\', '/'),
              "preprocessed": str(PREPROCESSED.relative_to(ROOT)).replace('\\', '/'),
              "heldout": str(HELDOUT.relative_to(ROOT)).replace('\\', '/'), "total": len(rows)}
    (ROOT / "data/normalized/active_dataset.json").write_text(json.dumps(active, indent=2))
    report = '# Active merged Ataraxia dataset\n\n' + f"{len(rows)} local video IDs, all with passed full video decoding. {len(selected)} provisional target-language candidates; {sum(r['language_status'] != 'target_language_candidate' for r in rows)} language-review cases.\n\n"
    report += 'All downstream defaults use this merged cohort. The original 3696-video and 624-video audits remain historical snapshots. The master collection now resolves to data/yt_shorts_master/videos.\n\n'
    report += '| Language status | Count |\n| --- | ---: |\n' + '\n'.join(f'| {k} | {v} |' for k, v in summary['language'].items())
    report += '\n\n## Active paths\n\n' + '\n'.join(f'- {k}: `{v}`' for k, v in active.items())
    report += '\n\n## Next commands\n\n`./run_post_language.ps1 -Phase review` creates the decision template; complete applicable keep/exclude/category decisions, then run `-Phase select`, `-Phase preprocess`, and `-Phase heldout`. Selection defers blank review cases; it does not erase them. Human language judgements and model language candidates remain distinguished. No model annotation starts.\n'
    (METADATA.parent / "normalization_report.md").write_text(report, encoding="utf-8")
    for source in provenance:
        folder = ROOT / source["folder"]
        assert all(sha(folder / name) == value for name, value in source["sha256"].items())
    print(json.dumps({k: summary[k] for k in ("total", "media", "language", "provisional_selected", "horizontal_selected", "review_queue_rows")}, indent=2))


if __name__ == '__main__':
    main()
