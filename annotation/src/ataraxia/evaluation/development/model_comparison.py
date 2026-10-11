"""Descriptive model agreement only; no human labels or model-quality ranking."""
from ataraxia.runtime.config import project_root
import csv
import hashlib
import itertools
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from ataraxia.annotation.common import VideoAnnotation, validate_emotion_points

BASE = project_root()
SOURCES = {
    "Gemini": BASE / "outputs/reels_30h/gemini/annotations.jsonl",
    "Qwen": BASE / "pilot_50_reels_30h/results/pilot50_qwen_nf4_max32_limit15p8_v5/qwen/pilot/annotations.jsonl",
    "InternVL": BASE / "pilot_50_reels_30h/results/pilot50_cuda_nf4_qwen32_intern16_limit15p8_v5/internvl/pilot/annotations.jsonl",
}
EMOTIONS = ["joy", "sadness", "anger", "fear_anxiety", "surprise", "disgust", "calm_contentment", "neutral"]
SCALARS = ["valence", "arousal", "recovery_suitability"]
LIMITS = {"valence": .20, "arousal": .15, "recovery_suitability": .15, "emotion_tv": .20}
PAIRS = list(itertools.combinations(SOURCES, 2))


def distribution(record):
    # Historical schema permits a total in [0.99, 1.01]. Normalize only a local
    # analysis copy for probability-distance metrics; preserve saved evidence.
    values = [record["emotions"][e] for e in EMOTIONS]
    return [v / sum(values) for v in values]


def pair_record(a, b):
    p, q = distribution(a), distribution(b)
    tv = sum(abs(x - y) for x, y in zip(p, q)) / 2
    m = [(x + y) / 2 for x, y in zip(p, q)]
    jsd = sum(x * math.log2(x / z) if x else 0 for x, z in zip(p, m)) / 2
    jsd += sum(x * math.log2(x / z) if x else 0 for x, z in zip(q, m)) / 2
    differences = {key: abs(a[key] - b[key]) for key in SCALARS}
    differences["emotion_tv"] = tv
    same = a["dominant_emotion"] == b["dominant_emotion"]
    return {**differences, "emotion_jsd_bits": max(0, jsd), "dominant_match": same,
            "strong": same and all(differences[k] <= v + 1e-12 for k, v in LIMITS.items()),
            "substantial": any(differences[k] > 2 * v + 1e-12 for k, v in LIMITS.items()),
            "composite_distance": statistics.mean([differences["valence"] / 2,
                differences["arousal"], differences["recovery_suitability"], tv])}


def correlation(x, y):
    mx, my = statistics.mean(x), statistics.mean(y)
    vx = statistics.mean([(v - mx) ** 2 for v in x])
    vy = statistics.mean([(v - my) ** 2 for v in y])
    cov = statistics.mean([(a - mx) * (b - my) for a, b in zip(x, y)])
    return {"pearson_r": cov / math.sqrt(vx * vy) if vx * vy else None,
            "concordance_ccc": 2 * cov / (vx + vy + (mx - my) ** 2)
            if vx + vy + (mx - my) ** 2 else None}


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    expected = [r["assigned_id"] for r in csv.DictReader(
        (BASE / "pilot_50_reels_30h/pilot_metadata.csv").open(encoding="utf-8"))]
    assert len(expected) == len(set(expected)) == 50
    data, normalization = {}, {}
    for model, path in SOURCES.items():
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(records) == 50 and {r["video_id"] for r in records} == set(expected), model
        normalization[model] = []
        for record in records:
            VideoAnnotation.model_validate(record)
            if "emotion_points" in record:
                validate_emotion_points({**record, "emotions": record["emotion_points"]})
            total = sum(record["emotions"].values())
            if abs(total - 1) > 1e-9:
                normalization[model].append({"video_id": record["video_id"], "original_total": total})
        data[model] = {r["video_id"]: r for r in records}
    out = BASE / "pilot_50_reels_30h/results/three_model_comparison"
    out.mkdir(parents=True, exist_ok=True)
    videos, flat = [], []
    for vid in expected:
        pairs = {f"{a} vs {b}": pair_record(data[a][vid], data[b][vid]) for a, b in PAIRS}
        strong = [pair for pair in PAIRS if pairs[f"{pair[0]} vs {pair[1]}"]["strong"]]
        outlier = None
        if len(strong) == 3:
            classification = "all_three_strong_agreement"
        elif all(p["substantial"] for p in pairs.values()):
            classification = "all_three_substantially_disagree"
        elif len(strong) == 1:
            candidate = next(m for m in SOURCES if m not in strong[0])
            outsider_pairs = [p for name, p in pairs.items() if candidate in name.split(" vs ")]
            if all(p["substantial"] for p in outsider_pairs):
                classification, outlier = "two_agree_one_outlier", candidate
            else:
                classification = "mixed_or_borderline"
        else:
            classification = "mixed_or_borderline"
        row = {"video_id": vid, "classification": classification, "outlier": outlier or ""}
        for m in SOURCES:
            r = data[m][vid]
            for key in SCALARS + ["dominant_emotion"]:
                row[f"{m}_{key}"] = r[key]
            for e, v in zip(EMOTIONS, distribution(r)):
                row[f"{m}_emotion_{e}"] = v
        for name, values in pairs.items():
            for key, value in values.items():
                row[f"{name}_{key}"] = value
        flat.append(row)
        videos.append({"video_id": vid, "classification": classification, "outlier": outlier,
                       "pairs": pairs})
    pair_summaries, scalar_rows = {}, []
    for a, b in PAIRS:
        name = f"{a} vs {b}"
        details = [v["pairs"][name] for v in videos]
        scalar = {}
        for key in SCALARS:
            x, y = [data[a][v][key] for v in expected], [data[b][v][key] for v in expected]
            delta = [u - v for u, v in zip(x, y)]
            scalar[key] = {"mae": statistics.mean(map(abs, delta)),
                           "rmse": math.sqrt(statistics.mean([v*v for v in delta])),
                           "signed_bias_first_minus_second": statistics.mean(delta),
                           "within_threshold_count": sum(abs(v) <= LIMITS[key] + 1e-12 for v in delta),
                           **correlation(x, y)}
            scalar_rows.append({"pair": name, "metric": key, **scalar[key]})
        ca = Counter(data[a][v]["dominant_emotion"] for v in expected)
        cb = Counter(data[b][v]["dominant_emotion"] for v in expected)
        observed = sum(p["dominant_match"] for p in details) / 50
        chance = sum(ca[e] * cb[e] for e in EMOTIONS) / 2500
        pair_summaries[name] = {"scalars": scalar, "dominant_agreement_count": round(observed*50),
            "dominant_agreement_fraction": observed, "dominant_cohen_kappa": (observed-chance)/(1-chance) if chance<1 else None,
            "mean_emotion_tv": statistics.mean(p["emotion_tv"] for p in details),
            "mean_emotion_jsd_bits": statistics.mean(p["emotion_jsd_bits"] for p in details),
            "strong_agreement_count": sum(p["strong"] for p in details),
            "substantial_disagreement_count": sum(p["substantial"] for p in details),
            "emotion_mean_absolute_differences": {e: statistics.mean(abs(distribution(data[a][v])[j]-distribution(data[b][v])[j]) for v in expected) for j,e in enumerate(EMOTIONS)},
            "dominant_confusion_matrix": {e: dict(Counter(data[b][v]["dominant_emotion"] for v in expected if data[a][v]["dominant_emotion"] == e)) for e in EMOTIONS}}
    model_summaries = {m: {"scalar_means": {k: statistics.mean(data[m][v][k] for v in expected) for k in SCALARS},
        "zero_recovery_count": sum(data[m][v]["recovery_suitability"] == 0 for v in expected),
        "dominant_counts": dict(Counter(data[m][v]["dominant_emotion"] for v in expected)),
        "mean_emotions": {e: statistics.mean(distribution(data[m][v])[j] for v in expected) for j,e in enumerate(EMOTIONS)}} for m in SOURCES}
    categories = dict(Counter(v["classification"] for v in videos))
    outliers = {m: sum(v["outlier"] == m for v in videos) for m in SOURCES}
    audit = {f"{a} vs {b}": {"context_hash_matches": sum(data[a][v]["run_metadata"].get("context_sha256") == data[b][v]["run_metadata"].get("context_sha256") for v in expected),
        "prompt_hash_matches": sum(data[a][v]["run_metadata"].get("prompt_sha256") == data[b][v]["run_metadata"].get("prompt_sha256") for v in expected)} for a,b in PAIRS}
    result = {"n": 50, "sources": {m: {"path": p.relative_to(BASE).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for m,p in SOURCES.items()},
        "strong_limits": LIMITS, "substantial_limits": {k:2*v for k,v in LIMITS.items()},
        "distribution_normalization": normalization, "evidence_audit": audit,
        "categories": categories, "outlier_counts": outliers, "pairs": pair_summaries,
        "models": model_summaries, "videos": videos}
    (out / "comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_csv(out / "per_video_disagreement.csv", flat)
    write_csv(out / "pairwise_scalar_metrics.csv", scalar_rows)
    report = ["# Three-model pilot annotation comparison", "", "Computed from the same 50 pilot video IDs. No human annotations are loaded. Agreement measures consistency, not correctness or model quality.", "",
        "## Comparison rules", "", "Valence is on [-1, 1]; arousal and recovery suitability on [0, 1]. Emotion comparisons use the saved `emotions` probability vectors, not the CUDA `emotion_points` values. Historical near-unit totals are normalized in analysis only; source annotations are unchanged.", "",
        "Thresholds were specified before computing results. Strong pair agreement requires matching dominant emotion AND absolute valence difference <=0.20, arousal <=0.15, recovery <=0.15, and emotion total-variation distance (TV) <=0.20. Substantial pair disagreement means any numerical difference > twice its corresponding strong limit. TV is half the sum of absolute differences across all eight probabilities (range 0 to 1).", "",
        "All-three strong agreement requires all three pairs to agree strongly. Two-agree/one-outlier requires exactly one strong pair and substantial disagreement between the outsider and BOTH members of that pair. All-three substantial disagreement requires all three pairs to disagree substantially. Remaining cases are mixed/borderline; a dominant-label mismatch alone does not establish substantial numerical disagreement. These are descriptive thresholds, not validated research selection criteria.", "",
        "## Overall pairwise agreement", "", "| Pair | Valence MAE | Arousal MAE | Recovery MAE | Dominant match | Kappa | Mean TV | Mean JSD (bits) | Strong pairs | Substantial pairs |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name,p in pair_summaries.items():
        s=p["scalars"]
        report.append(f"| {name} | {s['valence']['mae']:.3f} | {s['arousal']['mae']:.3f} | {s['recovery_suitability']['mae']:.3f} | {p['dominant_agreement_count']}/50 | {p['dominant_cohen_kappa']:.3f} | {p['mean_emotion_tv']:.3f} | {p['mean_emotion_jsd_bits']:.3f} | {p['strong_agreement_count']}/50 | {p['substantial_disagreement_count']}/50 |")
    report += ["", "MAE is on each scalar's original scale, so valence MAE is not directly comparable to arousal/recovery MAE. Kappa adjusts dominant-label agreement for marginal frequencies; JSD uses log base 2. RMSE, signed biases, Pearson r, concordance correlation (CCC), threshold counts, per-emotion differences and confusion matrices are in the machine-readable exports.", "", "## Consensus and outliers", ""]
    for category in ["all_three_strong_agreement", "two_agree_one_outlier", "all_three_substantially_disagree", "mixed_or_borderline"]:
        report.append(f"- {category.replace('_', ' ')}: {categories.get(category,0)}/50.")
    report += ["", "Strict outlier counts: " + "; ".join(f"{m}: {n}" for m,n in outliers.items()) + ". A model being an outlier does not establish that it is wrong.", "", "## Systematic differences", "", "| Model | Mean valence | Mean arousal | Mean recovery | Zero recovery |", "| --- | ---: | ---: | ---: | ---: |"]
    for m,s in model_summaries.items():
        means=s["scalar_means"]
        report.append(f"| {m} | {means['valence']:.3f} | {means['arousal']:.3f} | {means['recovery_suitability']:.3f} | {s['zero_recovery_count']}/50 |")
    report += ["", "| Emotion | Gemini mean / dominant count | Qwen mean / dominant count | InternVL mean / dominant count |", "| --- | ---: | ---: | ---: |"]
    for e in EMOTIONS:
        report.append("| " + e + " | " + " | ".join(f"{model_summaries[m]['mean_emotions'][e]:.3f} / {model_summaries[m]['dominant_counts'].get(e,0)}" for m in SOURCES) + " |")
    report += ["", "These are descriptive tendencies on this pilot, not causal effects or significance-tested population differences.", "", "## Per-video disagreement", "", "Triples are Gemini / Qwen / InternVL. Maximum TV is over the three pairs. The CSV also contains all eight probabilities per model and every pairwise distance/flag. Rows follow pilot metadata order.", "", "| Video ID | Pattern | Outlier | Valence G/Q/I | Arousal G/Q/I | Recovery G/Q/I | Dominant G/Q/I | Max TV |", "| --- | --- | --- | --- | --- | --- | --- | ---: |"]
    abbreviations={"all_three_strong_agreement":"All agree", "two_agree_one_outlier":"2 agree + outlier", "all_three_substantially_disagree":"All disagree", "mixed_or_borderline":"Mixed"}
    for v in videos:
        vid=v["video_id"]
        triples=[" / ".join(f"{data[m][vid][k]:.2f}" for m in SOURCES) for k in SCALARS]
        dom=" / ".join(data[m][vid]["dominant_emotion"] for m in SOURCES)
        report.append(f"| {vid} | {abbreviations[v['classification']]} | {v['outlier'] or '-'} | " + " | ".join(triples) + f" | {dom} | {max(p['emotion_tv'] for p in v['pairs'].values()):.3f} |")
    report += ["", "## Provenance and interpretation limits", "", "Gemini is the saved historical v1.0 deployment with direct audio access; Qwen and InternVL are v1.1-points10 CUDA runs with shared transcript/acoustic/caption context and no direct raw audio. Qwen caps at 32 uniformly sampled frames and InternVL at 16, with different vision processors. Therefore this compares saved deployments, not models under identical native modality access and sampling.", ""]
    for name,a in audit.items():
        report.append(f"- {name}: context hashes match {a['context_hash_matches']}/50; prompt hashes match {a['prompt_hash_matches']}/50.")
    report += ["", f"Analysis-only normalization counts: {', '.join(f'{m}: {len(a)}' for m,a in normalization.items())}. File hashes and original near-unit totals are preserved in `comparison.json`.", "", "No model is selected or ranked as best. Human validation has deliberately not been used.", "", "## Reproduce and exports", "", "Run `.venv-qwen-cuda/Scripts/python.exe src/compare_pilot_models.py` from the project root. Source files and their hashes are recorded in the JSON.", "", "- [Per-video disagreement CSV](pilot_50_reels_30h/results/three_model_comparison/per_video_disagreement.csv)", "- [Pairwise scalar metrics CSV](pilot_50_reels_30h/results/three_model_comparison/pairwise_scalar_metrics.csv)", "- [Complete comparison JSON](pilot_50_reels_30h/results/three_model_comparison/comparison.json)", ""]
    all_dominant = sum(len({data[m][v]["dominant_emotion"] for m in SOURCES}) == 1 for v in expected)
    text = "\n".join(report)
    text = text.replace("Strict outlier counts:",
        f"All three declared dominant labels match on {all_dominant}/50 videos; matching that single field does not imply strong agreement across all requested fields. Dominant-label comparisons use the saved declared label, including any valid maximum-score ties.\n\nStrict outlier counts:")
    # The tables above provide the exact numeric values behind these tendencies.
    text = text.replace("These are descriptive tendencies on this pilot",
        "Qwen assigns the highest mean valence and selects joy most often. It assigns recovery zero much more frequently and has the lowest mean recovery. InternVL assigns the highest mean arousal, selects no neutral dominant labels, and distributes dominant labels across more negative/surprise categories. Gemini assigns more calm_contentment probability and calm dominant labels than either CUDA model.\n\nThese are descriptive tendencies on this pilot")
    (BASE / "pilot_model_comparison.md").write_text(text, encoding="utf-8")
    print(json.dumps({"categories": categories, "outlier_counts": outliers, "pairs": pair_summaries,
                      "models": model_summaries, "audit": audit}, indent=2))


if __name__ == "__main__":
    main()
