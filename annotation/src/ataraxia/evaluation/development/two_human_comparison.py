"""Human-file agreement and provisional pooled reference; preserve originals."""
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from ataraxia.evaluation.development.model_comparison import BASE, EMOTIONS, SCALARS, SOURCES, correlation, distribution, pair_record, write_csv

HUMANS = {"A": BASE / "human_annotation/my_annotations.csv", "B": BASE / "human_annotation/annotations.txt"}


def load(path):
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig"))) if path.suffix == ".csv" else json.loads(path.read_text(encoding="utf-8-sig"))
    output = {}
    for r in rows:
        vid = r["video_id"]
        if vid in output:
            raise ValueError(f"Duplicate ID {vid}")
        for k in SCALARS + EMOTIONS:
            r[k] = float(r[k])
            if not math.isfinite(r[k]) or not 0 <= r[k] <= 10:
                raise ValueError(f"Invalid {vid} {k}")
        if abs(sum(r[e] for e in EMOTIONS)-10)>1e-9:
            raise ValueError(f"Emotion total invalid {vid}")
        if r["dominant_emotion"] not in maxima(r):
            raise ValueError(f"Dominant mismatch {vid}")
        output[vid] = r
    return output


def maxima(r):
    return {e for e in EMOTIONS if abs(r[e]-max(r[k] for k in EMOTIONS))<=1e-9}


def normalize(r):
    return {"video_id":r["video_id"], "valence":(r["valence"]-5)/5, "arousal":r["arousal"]/10,
            "recovery_suitability":r["recovery_suitability"]/10,
            "emotions":{e:r[e]/10 for e in EMOTIONS}, "dominant_emotion":r["dominant_emotion"]}


def metrics(a,b,ids):
    result={}
    for k in SCALARS:
        x,y=[a[v][k] for v in ids],[b[v][k] for v in ids]
        result[k]={"mae":statistics.mean(abs(u-v) for u,v in zip(x,y)),
                   "signed_bias_first_minus_second":statistics.mean(u-v for u,v in zip(x,y)), **correlation(x,y)}
    ca=Counter(a[v]["dominant_emotion"] for v in ids);cb=Counter(b[v]["dominant_emotion"] for v in ids)
    n=len(ids);count=sum(a[v]["dominant_emotion"]==b[v]["dominant_emotion"] for v in ids)
    chance=sum(ca[e]*cb[e] for e in EMOTIONS)/n**2
    result["dominant"]={"matches":count,"n":n,"agreement":count/n,"cohen_kappa":(count/n-chance)/(1-chance) if chance<1 else None}
    return result


def main():
    expected=[r["assigned_id"] for r in csv.DictReader((BASE/"pilot_50_reels_30h/pilot_metadata.csv").open(encoding="utf-8"))]
    h={m:load(p) for m,p in HUMANS.items()}
    ids=[v for v in expected if all(v in h[m] for m in h)]
    coverage={m:{"rows":len(a),"missing":sorted(set(expected)-set(a)),"unexpected":sorted(set(a)-set(expected))} for m,a in h.items()}
    out=BASE/"pilot_50_reels_30h/results/human_comparison";out.mkdir(parents=True,exist_ok=True)
    normalized={m:{v:normalize(a[v]) for v in ids} for m,a in h.items()}
    raw_metrics=metrics(h["A"],h["B"],ids)
    normalized_metrics=metrics(normalized["A"],normalized["B"],ids)
    rows=[];reference={};ambiguous=[]
    for v in ids:
        a,b=h["A"][v],h["B"][v];pair=pair_record(normalized["A"][v],normalized["B"][v]);reasons=[]
        for k in SCALARS:
            if abs(a[k]-b[k])>2+1e-9:reasons.append(k+"_difference_gt_2")
        shared=maxima(a)&maxima(b)
        if not shared:reasons.append("dominant_maxima_disjoint")
        if pair["emotion_tv"]>.4+1e-9:reasons.append("emotion_tv_gt_0.40")
        row={"video_id":v,"ambiguous":bool(reasons),"reasons":";".join(reasons),"emotion_tv":pair["emotion_tv"],"dominant_A":a["dominant_emotion"],"dominant_B":b["dominant_emotion"],"tie_aware_dominant_agreement":bool(shared)}
        for k in SCALARS:row.update({k+"_A":a[k],k+"_B":b[k],k+"_absolute_difference":abs(a[k]-b[k])})
        rows.append(row)
        if reasons:ambiguous.append(v)
        else:
            na,nb=normalized["A"][v],normalized["B"][v]
            r={"video_id":v,**{k:(na[k]+nb[k])/2 for k in SCALARS},"emotions":{e:(na["emotions"][e]+nb["emotions"][e])/2 for e in EMOTIONS},"dominant_emotion":next(e for e in EMOTIONS if e in shared),"reference_status":"provisional_pooled_low_disagreement","independent_annotator_provenance":"confirmed_by_user"}
            reference[v]=r
    write_csv(out/"per_video_human_disagreement.csv",rows)
    # Empty fields are deliberately left for human discussion, never filled using model predictions.
    adjudication=[{"video_id":v,"reason":next(r["reasons"] for r in rows if r["video_id"]==v),**{k:"" for k in SCALARS+EMOTIONS+["dominant_emotion","adjudicator","decision_notes"]}} for v in ambiguous]
    for v in expected:
        if v not in ids:adjudication.append({"video_id":v,"reason":"missing_human_labels",**{k:"" for k in SCALARS+EMOTIONS+["dominant_emotion","adjudicator","decision_notes"]}})
    template=out/"adjudication_template.csv"
    if not template.exists() and adjudication:write_csv(template,adjudication)
    (out/"provisional_reference.jsonl").write_text("".join(json.dumps(r)+"\n" for r in reference.values()),encoding="utf-8")
    model_metrics={}
    for m,path in SOURCES.items():
        predictions={r["video_id"]:r for r in [json.loads(l) for l in path.read_text().splitlines()]}
        if reference:
            model_metrics[m]=metrics(predictions,reference,list(reference))
            model_metrics[m]["mean_emotion_tv"]=statistics.mean(pair_record(predictions[v],reference[v])["emotion_tv"] for v in reference)
    result={"coverage":coverage,"paired_n":len(ids),"independent_annotator_provenance":"confirmed_by_user","human_metrics_0_to_10":raw_metrics,"human_metrics_model_scales":normalized_metrics,"tie_aware_dominant_matches":sum(r["tie_aware_dominant_agreement"] for r in rows),"ambiguous_ids":ambiguous,"reference_n":len(reference),"model_vs_provisional_reference":model_metrics,"sources":{m:{"path":str(p.relative_to(BASE)),"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for m,p in HUMANS.items()},"thresholds":{"scalar_difference_0_to_10":2,"emotion_tv":.4,"dominant_rule":"nonoverlapping maximum sets"}}
    (out/"comparison.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    report=["# Human agreement and provisional model comparison","","The user confirmed these are two independent human annotators. Whether annotation was blind to model predictions has not been verified. Coverage and adjudication remain incomplete; no final full-pilot reference or model selection is claimed.","","## Coverage","",f"Matched pilot IDs: {len(ids)}/50. A = my_annotations.csv; B = annotations.txt. Both omit FV000131. A also contains unexpected FV000037, excluded without guessing its intended ID.","","All matched rows pass 0-to-10 scalar bounds, eight-emotion total exactly 10, and dominant-maximum checks.","","## Agreement between supplied files","","| Field | Pearson r | MAE (0 to 10) | MAE (model scale) |","| --- | ---: | ---: | ---: |"]
    for k in SCALARS:
        a=raw_metrics[k];b=normalized_metrics[k];report.append(f"| {k} | {a['pearson_r']:.3f} | {a['mae']:.3f} | {b['mae']:.3f} |")
    d=raw_metrics["dominant"];report += ["",f"Declared dominant agreement: {d['matches']}/{len(ids)} ({d['agreement']:.1%}); Cohen's kappa: {d['cohen_kappa']:.3f}. Tie-aware maximum-set overlap: {result['tie_aware_dominant_matches']}/{len(ids)}.","","## Ambiguity and provisional reference","","Thresholds set before calculations: ambiguous if any scalar differs by more than 2/10, dominant maximum sets do not overlap, or emotion TV exceeds 0.40. These are descriptive starting criteria, not validated cutoffs.","",f"Ambiguous: {len(ambiguous)}/{len(ids)}. Low-disagreement provisional pooled reference: {len(reference)}/{len(ids)}. Missing FV000131 is excluded separately.","","Provisional reference averages both scalar scores and emotion distributions on eligible IDs only. Valence maps as (score-5)/5; arousal and recovery map as score/10. Shared dominant maxima determine the reference label; exact ties use the documented emotion-key order. High-disagreement rows are not averaged into evaluation. No adjudication is invented. Blank adjudication-template scores use the human 0-to-10 guide.","","## Models versus provisional reference","","The two annotators are confirmed independent; blindness to model outputs is unverified. This restricted-subset comparison is not a finalized 50-video human validation. Excluding disputed videos can make agreement appear better; do not extrapolate subset metrics to the full pilot.","","| Model | N | Valence MAE / r | Arousal MAE / r | Recovery MAE / r | Dominant match | Kappa | Mean emotion TV |","| --- | ---: | --- | --- | --- | ---: | ---: | ---: |"]
    for m,s in model_metrics.items():
        cells=[f"{s[k]['mae']:.3f} / {s[k]['pearson_r']:.3f}" if s[k]['pearson_r'] is not None else f"{s[k]['mae']:.3f} / undefined" for k in SCALARS];d=s['dominant'];kap=f"{d['cohen_kappa']:.3f}" if d['cohen_kappa'] is not None else 'undefined'
        report.append(f"| {m} | {len(reference)} | "+" | ".join(cells)+f" | {d['matches']}/{len(reference)} | {kap} | {s['mean_emotion_tv']:.3f} |")
    report += ["","Scalar model MAEs use valence [-1,1] and arousal/recovery [0,1]. Deployment differences (Gemini rubric/direct audio versus CUDA rubric/shared audio context and differing frame caps) remain possible confounders.","","## Per-video human disagreement","","| Video | Ambiguous | Reasons | Valence delta | Arousal delta | Recovery delta | Dominant A / B | TV |","| --- | --- | --- | ---: | ---: | ---: | --- | ---: |"]
    for r in rows:report.append(f"| {r['video_id']} | {r['ambiguous']} | {r['reasons'] or '-'} | {r['valence_absolute_difference']:.1f} | {r['arousal_absolute_difference']:.1f} | {r['recovery_suitability_absolute_difference']:.1f} | {r['dominant_A']} / {r['dominant_B']} | {r['emotion_tv']:.3f} |")
    report += ["","## Next required inputs","","Independence is confirmed; verify blindness to model predictions. Supply both labels for FV000131 and resolve whether FV000037 is intentional or an ID typo. Adjudicate ambiguous cases through discussion or a third human using direct video evidence, without model predictions. Preserve original labels and record adjudicator, reason and final decision. Only then finalize full-pilot model evaluation.","","Exports: `pilot_50_reels_30h/results/human_comparison/` contains comparison JSON, per-video CSV, provisional reference and blank adjudication template. Reproduce with `.venv-qwen-cuda/Scripts/python.exe src/compare_human_annotations.py`.",""]
    (BASE/"human_annotation_comparison.md").write_text("\n".join(report),encoding="utf-8")
    print(json.dumps({k:result[k] for k in ['coverage','paired_n','human_metrics_0_to_10','reference_n','ambiguous_ids','model_vs_provisional_reference']},indent=2))

if __name__=="__main__":main()
