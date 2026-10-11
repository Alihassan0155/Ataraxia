"""Independent field-wise human consensus. Never loads model predictions."""
import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
EMOTIONS = ("joy", "sadness", "anger", "fear_anxiety", "surprise", "disgust", "calm_contentment", "neutral")
SCALARS = {"valence": "valence", "arousal": "arousal", "recovery": "recovery_suitability"}
FIELDS = (*SCALARS, "dominant_emotion", "emotion_distribution")
EPS = 1e-9


def numeric(value):
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError("missing or nonnumeric score")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 10:
        raise ValueError("score must be finite and within [0,10]")
    return result


def read_source(path, expected):
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            raw = list(csv.DictReader(handle))
    else:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected row array in {path}")
    groups, issues = defaultdict(list), []
    for position, row in enumerate(raw, 1):
        vid = row.get("video_id") if isinstance(row, dict) else None
        if not isinstance(vid, str) or not re.fullmatch(r"(?:FV\d{6}|YT_[A-Za-z0-9_-]+|TT_\d+)", vid):
            issues.append({"row": position, "video_id": vid, "kind": "malformed_id", "raw_row": row})
            continue
        groups[vid].append(row)
        if vid not in expected:
            issues.append({"row": position, "video_id": vid, "kind": "unexpected_id"})
    for vid, rows in groups.items():
        if len(rows) > 1:
            issues.append({"video_id": vid, "kind": "duplicate_id", "count": len(rows)})
    field_issues = []
    for vid, rows in groups.items():
        for index, row in enumerate(rows, 1):
            _, errors, _ = validated([row])
            if "confidence" in row:
                try:
                    numeric(row["confidence"])
                except (ValueError, TypeError, OverflowError) as exc:
                    errors["confidence"] = str(exc)
            if errors:
                field_issues.append({"video_id":vid,"occurrence":index,"errors":errors})
    return groups, {"row_count": len(raw), "missing_ids": sorted(set(expected)-set(groups)),
                    "unexpected_ids": sorted(set(groups)-set(expected)), "issues": issues,
                    "field_validation_issues":field_issues}


def validated(rows):
    """Validate each field without letting a scalar failure poison other fields."""
    if rows is None:
        return {}, {f: "missing annotation row" for f in FIELDS}, "missing"
    if len(rows) != 1:
        return {}, {f: "duplicate ID; no row chosen" for f in FIELDS}, "invalid"
    row, values, errors = rows[0], {}, {}
    for field, key in SCALARS.items():
        try:
            values[field] = numeric(row.get(key))
        except (ValueError, TypeError, OverflowError) as exc:
            errors[field] = str(exc)
    try:
        points = {e: numeric(row.get(e)) for e in EMOTIONS}
        total = sum(points.values())
        if abs(total - 10) > EPS:
            raise ValueError(f"emotion points must total 10; got {total}")
        # Normalize this analysis copy only, correcting floating arithmetic drift.
        values["emotion_distribution"] = {e: points[e]/total for e in EMOTIONS}
    except (ValueError, TypeError, OverflowError) as exc:
        errors["emotion_distribution"] = str(exc)
    dominant = row.get("dominant_emotion")
    if dominant not in EMOTIONS:
        errors["dominant_emotion"] = "unknown/missing dominant emotion"
    elif "emotion_distribution" not in values:
        errors["dominant_emotion"] = "cannot validate maximum against invalid emotion scores"
    elif dominant not in maxima(values["emotion_distribution"]):
        errors["dominant_emotion"] = "dominant emotion is not a maximum"
    else:
        values["dominant_emotion"] = dominant
    return values, errors, "present"


def maxima(probabilities):
    highest = max(probabilities.values())
    return [e for e in EMOTIONS if abs(probabilities[e]-highest) <= EPS]


def tv_jsd(a, b):
    tv = sum(abs(a[e]-b[e]) for e in EMOTIONS)/2
    jsd = 0.0
    for e in EMOTIONS:
        midpoint = (a[e]+b[e])/2
        for p in (a[e], b[e]):
            if p:
                jsd += .5*p*math.log2(p/midpoint)
    return tv, max(0.0, jsd)


def pearson(x, y):
    if len(x) < 2:
        return None
    mx, my = statistics.mean(x), statistics.mean(y)
    covariance = sum((a-mx)*(b-my) for a,b in zip(x,y))
    denominator = math.sqrt(sum((a-mx)**2 for a in x)*sum((b-my)**2 for b in y))
    return covariance/denominator if denominator else None


def ranks(values):
    ordered = sorted(range(len(values)), key=values.__getitem__)
    result, i = [0.0]*len(values), 0
    while i < len(ordered):
        j = i+1
        while j < len(ordered) and values[ordered[j]] == values[ordered[i]]:
            j += 1
        for k in ordered[i:j]:
            result[k] = (i+1+j)/2
        i = j
    return result


def build(expected, sources):
    source_groups, validation = {}, {}
    for name, path in sources.items():
        source_groups[name], validation[name] = read_source(path, expected)
    rows, queue, pairs = [], [], {f: [] for f in FIELDS}
    for vid in expected:
        raw = {m: source_groups[m].get(vid) for m in sources}
        parsed = {m: validated(raw[m]) for m in sources}
        row = {"video_id": vid, "emotion_tv": None, "emotion_jsd_bits": None}
        for field in FIELDS:
            status_key = {"dominant_emotion": "dominant_status", "emotion_distribution": "emotion_distribution_status"}.get(field, field+"_status")
            a, b = parsed["a"][0].get(field), parsed["b"][0].get(field)
            for m in sources:
                original = raw[m][0] if raw[m] is not None and len(raw[m]) == 1 else None
                value = ({e: original.get(e) for e in EMOTIONS} if field == "emotion_distribution" else original.get(SCALARS.get(field,field))) if original else None
                row[f"annotator_{m}_{field}"] = value
            row["consensus_"+field] = None
            reasons = {m: parsed[m][1].get(field) for m in sources if field in parsed[m][1]}
            if reasons:
                # Invalid data takes precedence when another source is also missing.
                invalid = any(parsed[m][2] != "missing" and field in parsed[m][1] for m in sources)
                row[status_key] = "invalid" if invalid else "missing"
                row[field+"_validation_errors"] = reasons
                continue
            pairs[field].append((a,b))
            if field in SCALARS:
                metric = abs(a-b)
                status = "pooled" if metric <= 2+EPS else "needs_adjudication"
                consensus = (a+b)/2
            elif field == "dominant_emotion":
                metric = int(a != b)
                status = "exact_agreement" if a == b else "needs_adjudication"
                consensus = a
            else:
                metric, jsd = tv_jsd(a,b)
                row.update(emotion_tv=metric, emotion_jsd_bits=jsd)
                status = "pooled" if metric <= .40+EPS else "needs_adjudication"
                consensus = {e:(a[e]+b[e])/2 for e in EMOTIONS}
                assert abs(sum(consensus.values())-1) <= EPS
            row[status_key] = status
            if status == "needs_adjudication":
                queue.append({"video_id":vid,"field":field,
                    "annotator_a_value":row["annotator_a_"+field], "annotator_b_value":row["annotator_b_"+field],
                    "disagreement_metric":metric, "metric_name": "absolute_difference_0_to_10" if field in SCALARS else "label_mismatch" if field=="dominant_emotion" else "total_variation",
                    "final_adjudicated_value":"","adjudicator":"","reason":""})
            else:
                row["consensus_"+field] = consensus
        status_keys = [f+"_status" for f in SCALARS]+["dominant_status","emotion_distribution_status"]
        row["disputed_field_count"] = sum(row[k] == "needs_adjudication" for k in status_keys)
        row["needs_any_adjudication"] = bool(row["disputed_field_count"])
        row["needs_data_resolution"] = any(row[k] in ("missing","invalid") for k in status_keys)
        probabilities = row["consensus_emotion_distribution"]
        derived = maxima(probabilities) if probabilities is not None else []
        row["distribution_derived_dominant_emotions"] = derived
        row["distribution_derived_dominant_emotion"] = derived[0] if derived else None
        declared = row["consensus_dominant_emotion"]
        row["dominant_distribution_consistency"] = "unresolved" if not derived or declared is None else "consistent" if declared in derived else "mismatch"
        rows.append(row)
    stats = {}
    for f in SCALARS:
        x,y = [a for a,b in pairs[f]], [b for a,b in pairs[f]]
        stats[f] = {"n":len(x),"mae_0_to_10":statistics.mean(abs(a-b) for a,b in pairs[f]) if x else None,
                    "pearson_r":pearson(x,y),"spearman_rho":pearson(ranks(x),ranks(y))}
    p = pairs["dominant_emotion"]
    ca,cb = Counter(a for a,b in p), Counter(b for a,b in p)
    n = len(p)
    agree = sum(a==b for a,b in p)
    chance = sum(ca[e]*cb[e] for e in EMOTIONS)/n**2 if n else None
    stats["dominant_emotion"] = {"n":n,"exact_matches":agree,"raw_agreement":agree/n if n else None,
        "cohen_kappa":(agree/n-chance)/(1-chance) if n and chance<1 else None}
    distances = [tv_jsd(a,b) for a,b in pairs["emotion_distribution"]]
    stats["emotion_distribution"] = {"n":len(distances),
        **{prefix+"_"+name:func([v[index] for v in distances]) if distances else None for prefix,func in [("mean",statistics.mean),("median",statistics.median)] for index,name in enumerate(["tv","jsd_bits"])}}
    counts = {}
    for f in FIELDS:
        key = {"dominant_emotion":"dominant_status","emotion_distribution":"emotion_distribution_status"}.get(f,f+"_status")
        counts[f] = dict(Counter(r[key] for r in rows))
    automatic = sum(c.get("pooled",0)+c.get("exact_agreement",0) for c in counts.values())
    disputes = len(queue)
    paired_rows = [r for r in rows if not r["needs_data_resolution"]]
    summary = {"schema_version":"fieldwise-human-consensus-v1", "independent_annotators":"confirmed_by_user",
        "blinding_to_models":"unverified", "expected_videos":len(expected),"source_validation":validation,
        "agreement":stats,"field_status_counts":counts,"automatic_fields":automatic,"disputed_fields":disputes,
        "missing_or_invalid_fields":len(expected)*5-automatic-disputes,
        "automatic_percentage_all_expected_fields":100*automatic/(len(expected)*5),
        "automatic_percentage_valid_paired_fields":100*automatic/(automatic+disputes) if automatic+disputes else None,
        "videos_by_disputed_field_count_all_expected":{"zero":sum(r["disputed_field_count"]==0 for r in rows),"one":sum(r["disputed_field_count"]==1 for r in rows),"two_or_more":sum(r["disputed_field_count"]>=2 for r in rows)},
        "videos_by_disputed_field_count_valid_paired":{"zero":sum(r["disputed_field_count"]==0 for r in paired_rows),"one":sum(r["disputed_field_count"]==1 for r in paired_rows),"two_or_more":sum(r["disputed_field_count"]>=2 for r in paired_rows)},
        "videos_needing_adjudication":sum(r["needs_any_adjudication"] for r in rows),
        "videos_needing_data_resolution":sum(r["needs_data_resolution"] for r in rows),
        "videos_needing_any_human_revisit":sum(r["needs_data_resolution"] or r["needs_any_adjudication"] for r in rows),
        "cross_field_mismatch_ids":[r["video_id"] for r in rows if r["dominant_distribution_consistency"]=="mismatch"],
        "thresholds":{"scalar_difference_0_to_10":2,"emotion_tv":.40,"dominant":"exact declared label agreement"},
        "scales":{"consensus_scalars":"human 0 to 10","raw_emotions":"human points totaling 10","consensus_emotions":"probabilities totaling 1","jsd":"base-2 divergence, not square-root distance"},
        "reference_state":"partial; disputed/missing/invalid values are null, not final adjudicated labels"}
    return rows, queue, summary


def write_csv(path, rows, columns=None):
    keys = columns or list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w",encoding="utf-8",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=keys)
        writer.writeheader()
        for r in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in r.items()})


def fmt(v):
    return "undefined" if v is None else f"{v:.3f}"


def report(summary, output):
    s = summary
    lines = ["# Field-wise human consensus", "", "Only the two independent human sources are loaded. No model predictions are read or compared. Original files are unchanged. This is a partial field-level reference, not invented human adjudication.", "",
        "## Sources, validation and alignment", "", "A: `human_annotation/my_annotations.csv` (CSV); B: `human_annotation/annotations.txt` (JSON array). Strict pilot `video_id` alignment produces one row for each of the 50 expected videos. Unexpected IDs are reported, not mapped or appended to the reference. Duplicate IDs are quarantined without choosing a row.", ""]
    for name,v in s["source_validation"].items():
        lines.append(f"- {name.upper()}: {v['row_count']} source rows; missing IDs {v['missing_ids']}; unexpected IDs {v['unexpected_ids']}; ID issues {len(v['issues'])}.")
    lines += ["", "Known coverage: FV000131 is missing from both sources; FV000037 is unexpected in A. No replacement has been guessed. Field errors and raw source hashes are in the JSON outputs. Scores must be finite in [0,10], all eight point values present, total exactly 10 within 1e-9 arithmetic tolerance, and declared dominant a maximum. Invalid scalars affect only their own field; invalid distributions also prevent dominant consistency validation.", "",
        "## Independent consensus rules", "", "Scalar absolute difference <=2/10: midpoint/mean, status pooled; larger: only that scalar needs adjudication. Dominant emotion: exact declared-label equality, including valid ties; otherwise only that label needs adjudication. Distribution TV <=0.40: element-wise mean of analysis-copy probabilities; larger: only the distribution needs adjudication. Equality at a threshold is accepted (1e-9 arithmetic tolerance). Raw emotion scores remain 10-point allocations; consensus probabilities sum to 1.", "",
        "The pooled distribution's dominant maximum set is derived separately; exact ties are retained, with the first emotion in the documented key order exposed as a deterministic convenience label. It never replaces or adjudicates the separate declared-dominant field. Any cross-field mismatch is explicitly reported and does not discard other fields.", "", f"Cross-field declared/derived mismatch IDs: {s['cross_field_mismatch_ids'] or 'none'}.", "",
        "## Human-human agreement", "", "| Field | Valid pairs | MAE (0 to 10) | Pearson r | Spearman rho |", "| --- | ---: | ---: | ---: | ---: |"]
    for field in SCALARS:
        a=s["agreement"][field];lines.append(f"| {field} | {a['n']} | {fmt(a['mae_0_to_10'])} | {fmt(a['pearson_r'])} | {fmt(a['spearman_rho'])} |")
    d=s["agreement"]["dominant_emotion"];e=s["agreement"]["emotion_distribution"]
    lines += ["",f"Dominant emotion: {d['exact_matches']}/{d['n']} exact agreement ({100*d['raw_agreement']:.1f}%); Cohen's kappa {fmt(d['cohen_kappa'])}.",f"Emotion distributions ({e['n']} pairs): mean/median TV {fmt(e['mean_tv'])}/{fmt(e['median_tv'])}; mean/median JSD {fmt(e['mean_jsd_bits'])}/{fmt(e['median_jsd_bits'])} bits. JSD is base-2 divergence. Spearman uses average ranks for ties; correlations with constant or insufficient data are null/undefined.", "",
        "## Field coverage", "", "The denominator uses five label types per video: three scalars, one dominant label, and the eight-emotion vector as one distribution field. This is not 12 independent fields.", "", "| Field | Automatic | Adjudication | Missing | Invalid |", "| --- | ---: | ---: | ---: | ---: |"]
    for field,c in s["field_status_counts"].items():
        lines.append(f"| {field} | {c.get('pooled',0)+c.get('exact_agreement',0)} | {c.get('needs_adjudication',0)} | {c.get('missing',0)} | {c.get('invalid',0)} |")
    c=s["videos_by_disputed_field_count_valid_paired"]
    lines += ["",f"Among videos with all fields valid and paired: zero disputes {c['zero']}; one disputed field {c['one']}; two or more {c['two_or_more']}. All-50 counts, including missing data, are in the summary JSON; a missing video with zero disputes is not a complete reference.", "",
        "The adjudication queue contains only fields whose two valid labels disagree beyond their acceptance rule. Missing/invalid inputs are separately reported for data resolution; no blank missing row is disguised as an annotator disagreement. Final adjudicated values, adjudicator and reason are left blank. No previously supplied adjudication is consumed by this builder.", "",
        "## Improvement over whole-video rejection", "", "The earlier rule retained 16/49 whole videos, equivalent to 80/245 field slots. Its dominant rule allowed intersecting maximum sets; this pipeline follows the requested stricter exact declared-label rule, so complete-row counts are not a pure granularity comparison.", "",
        f"This pipeline retains {s['automatic_fields']}/{s['automatic_fields']+s['disputed_fields']} valid paired field slots automatically ({s['automatic_percentage_valid_paired_fields']:.1f}%), versus the historical 80/245 (32.7%) previously: {s['automatic_fields']-80} additional usable fields. Across all {s['expected_videos']*5} expected slots, automatic coverage is {s['automatic_percentage_all_expected_fields']:.1f}%; missing/invalid slots are counted separately. Fields are pooled even when other fields in the same video are disputed.", "",
        "## Reproduce and outputs", "", "Run `.venv-qwen-cuda/Scripts/python.exe src/build_human_fieldwise_consensus.py` from the project root. Existing comparison scripts and their outputs remain unchanged.", "",
        "- `human_fieldwise_consensus.csv` and `.json`: 50 field-level rows; raw A/B values, consensus values, statuses, metrics, derived dominant labels and validation errors.", "- `human_adjudication_queue.csv`: one row per disputed field; final decisions blank.", "- `human_agreement_summary.json`: agreement metrics, coverage, anomalies and input hashes.", "- `human_agreement_report.md`: this report.", "",
        "The queue is a generated blank template; the builder refuses to overwrite it if adjudication columns have been filled. Save completed decisions separately and implement an audited application step before claiming a finalized reference. Independence is user-confirmed; blindness to model labels remains unverified.", "", "## Summary", ""]
    most=max(s["field_status_counts"],key=lambda f:s["field_status_counts"][f].get("needs_adjudication",0))
    lines += [f"1. Automatically pooled/accepted fields: {s['automatic_fields']} ({s['automatic_percentage_valid_paired_fields']:.1f}% of valid paired fields).",f"2. Fields requiring adjudication: {s['disputed_fields']}; missing/invalid fields: {s['missing_or_invalid_fields']}.",f"3. Highest disagreement: {most} ({s['field_status_counts'][most].get('needs_adjudication',0)} fields).",f"4. Human revisit: {s['videos_needing_adjudication']} videos for adjudication plus {s['videos_needing_data_resolution']} for data resolution ({s['videos_needing_any_human_revisit']} unique videos).",f"5. Compared with the old 16/49 whole-video rule, {s['automatic_fields']-80} additional agreed field values are retained rather than discarded.", ""]
    output.write_text("\n".join(lines),encoding="utf-8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotator-a",type=Path,default=BASE/"human_annotation/my_annotations.csv")
    parser.add_argument("--annotator-b",type=Path,default=BASE/"human_annotation/annotations.txt")
    parser.add_argument("--output-dir",type=Path,default=BASE/"pilot_50_reels_30h/results/human_comparison")
    args=parser.parse_args()
    sources={"a":args.annotator_a,"b":args.annotator_b}
    hashes={m:hashlib.sha256(p.read_bytes()).hexdigest() for m,p in sources.items()}
    metadata=BASE/"pilot_50_reels_30h/pilot_metadata.csv"
    with metadata.open(encoding="utf-8") as handle:
        expected=[r["assigned_id"] for r in csv.DictReader(handle)]
    if len(expected)!=50 or len(set(expected))!=50:
        raise ValueError("Expected 50 distinct pilot IDs")
    rows,queue,summary=build(expected,sources)
    summary["sources"]={m:{"path":str(p.resolve()),"sha256":hashes[m]} for m,p in sources.items()}
    summary["pilot_metadata_sha256"]=hashlib.sha256(metadata.read_bytes()).hexdigest()
    out=args.output_dir
    out.mkdir(parents=True,exist_ok=True)
    queue_path=out/"human_adjudication_queue.csv"
    if queue_path.exists():
        with queue_path.open(encoding="utf-8-sig") as handle:
            existing=list(csv.DictReader(handle))
        if any(any(r.get(k,"").strip() for k in ("final_adjudicated_value","adjudicator","reason")) for r in existing):
            raise ValueError("Adjudication queue contains decisions; choose a fresh output directory")
    write_csv(out/"human_fieldwise_consensus.csv",rows)
    (out/"human_fieldwise_consensus.json").write_text(json.dumps({"schema_version":summary['schema_version'],"sources":summary['sources'],"rows":rows},indent=2,ensure_ascii=False),encoding="utf-8")
    write_csv(queue_path,queue,["video_id","field","annotator_a_value","annotator_b_value","disagreement_metric","metric_name","final_adjudicated_value","adjudicator","reason"])
    (out/"human_agreement_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
    report(summary,out/"human_agreement_report.md")
    assert hashes=={m:hashlib.sha256(p.read_bytes()).hexdigest() for m,p in sources.items()},"Original source modified"
    print(json.dumps({k:summary[k] for k in ["automatic_fields","disputed_fields","missing_or_invalid_fields","automatic_percentage_valid_paired_fields","field_status_counts","videos_needing_any_human_revisit"]},indent=2))


if __name__=="__main__":
    main()
