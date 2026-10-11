"""Review, select, and sample normalized data without altering original sources."""
import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from ataraxia.datasets.validation import ROOT, write_csv
from ataraxia.datasets.paths import AUDIT, SELECTED, PREPROCESSED, HELDOUT


def load(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["review", "select", "heldout"])
    parser.add_argument("--audit", type=Path, default=AUDIT)
    parser.add_argument("--output", type=Path, default=SELECTED)
    parser.add_argument("--seed", type=int, default=20261008)
    parser.add_argument("--policy", choices=["reviewed", "non_target_only"], default="non_target_only",
                        help="Default user policy retains uncertain/mixed/speechless and unmapped categories")
    parser.add_argument("--preprocessed", type=Path, default=PREPROCESSED)
    parser.add_argument("--allow-pending-evidence", action="store_true",
                        help="Select native-video holdout now; shared evidence may be prepared later")
    args = parser.parse_args()
    if args.phase == "heldout":
        rows = load(args.output / "selected_metadata.csv")
        if not args.allow_pending_evidence:
            ready = load(args.preprocessed / "ready_metadata.csv")
            if {r["assigned_id"] for r in ready} != {r["assigned_id"] for r in rows}:
                raise ValueError("Complete evidence preprocessing or explicitly use --allow-pending-evidence for native-video sampling")
            rows = ready
        pilot = {r["assigned_id"] for r in load(ROOT / "pilot_50_reels_30h/pilot_metadata.csv")}
        groups = defaultdict(list)
        for row in rows:
            if row["assigned_id"] not in pilot:
                groups[row["category"]].append(row)
        rng = random.Random(args.seed)
        categories = sorted(groups)
        rng.shuffle(categories)
        selected = []
        for category in sorted(groups):
            group = groups[category]
            group.sort(key=lambda r: r["assigned_id"])
            rng.shuffle(group)
        while len(selected) < 50:
            before = len(selected)
            for category in categories:
                if groups[category] and len(selected) < 50:
                    selected.append(groups[category].pop())
            if before == len(selected):
                raise ValueError("Fewer than 50 eligible non-pilot videos")
        assert len({r["assigned_id"] for r in selected}) == 50
        assert not pilot.intersection(r["assigned_id"] for r in selected)
        assert len({r["media_sha256"] for r in selected}) == 50
        audited = load(args.audit / "validation_manifest.csv")
        pilot_hashes = {r["media_sha256"] for r in audited if r["assigned_id"] in pilot}
        assert not pilot_hashes.intersection(r["media_sha256"] for r in selected)
        for row in selected:
            path = Path(row["file_path"])
            assert (path if path.is_absolute() else ROOT / path).is_file()
        destination = HELDOUT
        if destination.exists():
            raise FileExistsError("Preserve existing holdout; use a new version")
        destination.mkdir(parents=True)
        write_csv(destination / "held_out_50.csv", selected, list(rows[0]))
        (destination / "held_out_50.txt").write_text("video_id\tcategory\tfile_path\n" + "\n".join(
            f"{r['assigned_id']}\t{r['category']}\t{r['file_path']}" for r in selected) + "\n", encoding="utf-8")
        summary = {"total": 50, "pilot_overlap": 0, "seed": args.seed,
                   "duplicate_ids": 0, "exact_byte_pilot_overlap": 0,
                   "candidate_pool_size": sum(r["assigned_id"] not in pilot for r in rows),
                   "shared_evidence_required_before_model_inference": True,
                   "pending_evidence_allowed_for_selection": args.allow_pending_evidence,
                   "selected_metadata_sha256": hashlib.sha256((args.output / "selected_metadata.csv").read_bytes()).hexdigest(),
                   "orientations": dict(Counter(r["orientation"] for r in selected)),
                   "categories": dict(Counter(r["category"] for r in selected)),
                   "source_composition": dict(Counter(r["platform"] for r in selected)),
                   "note": "Category-balanced, not source-balanced; exact-byte duplicates removed upstream. Repost/creator leakage still requires review."}
        (destination / "selection_summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        return
    rows = load(args.audit / "validation_manifest.csv")
    if len({r["assigned_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate audit IDs")
    decisions_path = args.audit / "human_review_decisions.csv"
    if args.phase == "review":
        if decisions_path.exists():
            raise FileExistsError("Review file exists; preserve your decisions")
        review = [{"assigned_id": r["assigned_id"], "file_path": r["file_path"],
                   "language_status": r["language_status"], "category": r["category"],
                   "decision": "", "final_category": "", "reviewer": "", "reason": ""}
                  for r in rows if r["language_status"] != "target_language_candidate"
                  or r["category"] == "Unmapped / Needs Review" or r.get("category_conflict") == "True"]
        write_csv(decisions_path, review, ["assigned_id", "file_path", "language_status", "category", "decision", "final_category", "reviewer", "reason"])
        print(f"Review rows: {len(review)}. Enter keep/exclude after direct video review, reviewer, reason; correct category if needed. Blank decisions remain pending.")
        return
    if any(r["media_status"] == "pending" or r["language_status"] == "pending" for r in rows):
        raise ValueError("Finish the full media/language audit before selection")
    decisions = load(decisions_path) if decisions_path.exists() else []
    if len({r["assigned_id"] for r in decisions}) != len(decisions):
        raise ValueError("Duplicate review decisions")
    overrides = {r["assigned_id"]: r for r in decisions}
    eligible, excluded = [], []
    for row in rows:
        decision = overrides.get(row["assigned_id"], {})
        value = decision.get("decision", "").strip()
        if value not in {"", "keep", "exclude"}:
            raise ValueError(f"Invalid decision for {row['assigned_id']}")
        if value and (not decision.get("reviewer", "").strip() or not decision.get("reason", "").strip()):
            raise ValueError("Review decisions require reviewer and reason")
        if decision.get("final_category", "").strip():
            from ataraxia.datasets.normalization import TAXONOMY
            category = decision["final_category"].strip()
            if category not in TAXONOMY:
                raise ValueError(f"Unknown shared category: {category}")
            row["category"] = category
        good = row["media_status"] == "full_video_decode_passed" and row.get("orientation") in {"vertical", "horizontal", "square"}
        good = good and row.get("audit_selection_status") != "duplicate_content" and value != "exclude"
        category_review = row["category"] == "Unmapped / Needs Review" or (row.get("category_conflict") == "True" and not decision.get("final_category"))
        if args.policy == "non_target_only":
            good = row["media_status"] == "full_video_decode_passed" and row.get("orientation") in {"vertical", "horizontal", "square"}
            good = good and row.get("audit_selection_status") != "duplicate_content" and row["language_status"] != "review_non_target_language"
            row["eligibility_basis"] = "user_policy_retain_unresolved_language_and_category"
        else:
            good = good and not category_review and (value == "keep" or row["language_status"] == "target_language_candidate")
            row["eligibility_basis"] = "human_review" if value == "keep" else "automatic_language_screen"
        row["review_decision_json"] = json.dumps(decision)
        row["selection_reason"] = "eligible_candidate" if good else "non_target_language_flag" if args.policy == "non_target_only" and row["language_status"] == "review_non_target_language" else "excluded_or_pending_review"
        (eligible if good else excluded).append(row)
    horizontal = [r for r in eligible if r["orientation"] == "horizontal"]
    other = [r for r in eligible if r["orientation"] != "horizontal"]
    cap = min(len(horizontal), 3 * len(other) // 7)
    chosen = [r for r in horizontal if r["split"] == "original_pilot"]
    if len(chosen) > cap:
        raise ValueError("Horizontal cap cannot be met while retaining eligible original pilot videos")
    pools = defaultdict(list)
    for row in horizontal:
        if row not in chosen:
            pools[row["category"]].append(row)
    rng = random.Random(args.seed)
    for pool in pools.values():
        pool.sort(key=lambda r: r["assigned_id"])
        rng.shuffle(pool)
    targets = Counter(r["category"] for r in horizontal)
    while len(chosen) < cap:
        category = max((k for k, v in pools.items() if v), key=lambda k: (cap * targets[k] / len(horizontal) - sum(r["category"] == k for r in chosen), k))
        chosen.append(pools[category].pop())
    kept = {r["assigned_id"] for r in chosen}
    for row in horizontal:
        if row["assigned_id"] not in kept:
            row["selection_reason"] = "horizontal_cap"
            excluded.append(row)
    selected = sorted(other + chosen, key=lambda r: r["assigned_id"])
    assert not selected or len(chosen) / len(selected) <= .30
    if args.output.exists():
        raise FileExistsError("Selection version already exists; use --output for a new version")
    args.output.mkdir(parents=True)
    fields = sorted({k for r in rows for k in r})
    write_csv(args.output / "selected_metadata.csv", selected, fields)
    write_csv(args.output / "excluded_or_pending.csv", excluded, fields)
    summary = {"selected": len(selected), "horizontal": len(chosen), "excluded_or_pending": len(excluded),
               "policy": args.policy,
               "language_statuses_retained": dict(Counter(r["language_status"] for r in selected)),
               "exclusion_reasons": dict(Counter(r["selection_reason"] for r in excluded)),
               "seed": args.seed, "categories": dict(Counter(r["category"] for r in selected)),
               "note": "Dataset selection follows the recorded user policy, not verified language ground truth. Original language/category uncertainty is retained. Native media unchanged; historical pilot records preserved. Held-out 50 stays fixed."}
    (args.output / "selection_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
