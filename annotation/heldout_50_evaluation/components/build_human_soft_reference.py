"""Preserve paired human disagreement as uncertainty; evaluate saved models."""
import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from build_human_fieldwise_consensus import (
    BASE, EMOTIONS, SCALARS, EPS, read_source, validated, maxima,
    tv_jsd, pearson, ranks,
)
from common_annotation import VideoAnnotation, validate_emotion_points
from compare_pilot_models import SOURCES


def write_csv(path, rows):
    # DictReader preserves unquoted extra note cells under a None key; don't
    # sort mixed-type keys or discard those cells from the raw annotation copy.
    with path.open('w', encoding='utf-8', newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})


def normalize_scalar(field, value):
    return (value-5)/5 if field == "valence" else value/10


def quantile(values, fraction):
    values=sorted(values)
    position=(len(values)-1)*fraction
    lower=math.floor(position);upper=math.ceil(position)
    return values[lower]+(values[upper]-values[lower])*(position-lower)


def reference_rows(expected, sources):
    groups, audits = {}, {}
    for m,path in sources.items():
        groups[m],audits[m]=read_source(path,expected)
        audits[m]['csv_extra_cells']=[{'video_id':vid,'extra_cells':raw[None]}
            for vid,records in groups[m].items() for raw in records if None in raw]
    rows=[]
    for vid in expected:
        source={m:groups[m].get(vid) for m in sources}
        parsed={m:validated(source[m]) for m in sources}
        row={"video_id":vid}
        for m in sources:
            row[f"human_{m}_raw_annotations"] = source[m][0] if source[m] is not None and len(source[m])==1 else source[m]
            row[f"human_{m}_validation_errors"]=parsed[m][1]
        for f,key in SCALARS.items():
            a,b=parsed['a'][0].get(f),parsed['b'][0].get(f)
            for m in sources:
                raw=row[f"human_{m}_raw_annotations"]
                row[f"human_{m}_{key}"]=raw.get(key) if isinstance(raw,dict) else None
                value=parsed[m][0].get(f)
                row[f"human_{m}_{key}_model_scale"]=normalize_scalar(f,value) if value is not None else None
            mean=(a+b)/2 if a is not None and b is not None else None
            diff=abs(a-b) if mean is not None else None
            row[f"{key}_human_mean"]=mean
            row[f"{key}_human_mean_model_scale"]=normalize_scalar(f,mean) if mean is not None else None
            row[f"{key}_human_abs_difference"]=diff
            row[f"{f}_uncertainty"]=diff
            row[f"{f}_uncertainty_range_normalized"]=diff/10 if diff is not None else None
            row[f"{key}_pair_status"]="valid_pair" if mean is not None else "missing" if any(parsed[m][2]=="missing" for m in sources) else "invalid"
        for m in sources:
            raw=row[f"human_{m}_raw_annotations"]
            row[f"human_{m}_emotion_scores"]={e:raw.get(e) for e in EMOTIONS} if isinstance(raw,dict) else None
            row[f"human_{m}_emotion_distribution"]=parsed[m][0].get("emotion_distribution")
            row[f"human_{m}_dominant"]=raw.get("dominant_emotion") if isinstance(raw,dict) else None
        a,b=[parsed[m][0].get("emotion_distribution") for m in sources]
        if a is not None and b is not None:
            pooled={e:(a[e]+b[e])/2 for e in EMOTIONS}
            assert abs(sum(pooled.values())-1)<=EPS
            tv,jsd=tv_jsd(a,b)
        else:
            pooled=tv=jsd=None
        row.update(pooled_emotion_distribution=pooled,emotion_tv=tv,emotion_jsd=jsd,
            emotion_distribution_pair_status="valid_pair" if pooled is not None else "missing" if any(parsed[m][2]=="missing" for m in sources) else "invalid")
        a,b=[parsed[m][0].get("dominant_emotion") for m in sources]
        agree=a==b if a is not None and b is not None else None
        derived=maxima(pooled) if pooled is not None else []
        row.update(dominant_agreement=agree,dominant_disagreement=not agree if agree is not None else None,
            dominant_pair_status="valid_pair" if agree is not None else "missing" if any(parsed[m][2]=="missing" for m in sources) else "invalid",
            pooled_distribution_dominant=derived[0] if derived else None,
            pooled_distribution_dominant_set=derived)
        components=[row[f"{f}_uncertainty_range_normalized"] for f in SCALARS]+[tv,float(not agree) if agree is not None else None]
        overall=statistics.mean(components) if all(v is not None for v in components) else None
        row.update(overall_human_uncertainty=overall,uncertainty_bin=None)
        rows.append(row)
    valid=[r['overall_human_uncertainty'] for r in rows if r['overall_human_uncertainty'] is not None]
    bounds=[quantile(valid,1/3),quantile(valid,2/3)] if valid else None
    if bounds:
        for r in rows:
            u=r['overall_human_uncertainty']
            if u is not None:r['uncertainty_bin']='low' if u<=bounds[0]+EPS else 'medium' if u<=bounds[1]+EPS else 'high'
    return rows,audits,bounds


def distribution_match(model,a,b,pooled):
    tv,jsd=tv_jsd(model,pooled)
    ta,ja=tv_jsd(model,a);tb,jb=tv_jsd(model,b)
    return {"emotion_tv_to_pool":tv,"emotion_jsd_to_pool":jsd,
        "emotion_tv_to_human_a":ta,"emotion_tv_to_human_b":tb,
        "emotion_jsd_to_human_a":ja,"emotion_jsd_to_human_b":jb,
        "mixture_closer_than_both_humans_tv":tv<min(ta,tb)-EPS,
        "mixture_closer_than_both_humans_jsd":jsd<min(ja,jb)-EPS}


def evaluate(model, record, reference):
    r={"video_id":reference['video_id'],"model":model,
       "overall_human_uncertainty":reference['overall_human_uncertainty'],
       "uncertainty_bin":reference['uncertainty_bin'],"model_valid":record is not None}
    for f,key in SCALARS.items():
        target=reference[f'{key}_human_mean_model_scale']
        pred=record[key] if record is not None else None
        difference=abs(pred-target) if pred is not None and target is not None else None
        r.update({f'{key}_model_value':pred,f'{key}_human_mean_model_scale':target,
            f'{key}_absolute_error':difference,f'{key}_squared_error':difference**2 if difference is not None else None,
            f'{key}_range_normalized_error':difference/2 if f=='valence' and difference is not None else difference})
    pooled=reference['pooled_emotion_distribution']
    prob=None
    if record is not None:
        total=sum(record['emotions'].values())
        prob={e:record['emotions'][e]/total for e in EMOTIONS}
    r['model_emotion_distribution']=prob
    r['pooled_emotion_distribution']=pooled
    if pooled is not None and prob is not None:
        r.update(distribution_match(prob,reference['human_a_emotion_distribution'],reference['human_b_emotion_distribution'],pooled))
        r['emotion_cosine_to_pool']=sum(prob[e]*pooled[e] for e in EMOTIONS)/math.sqrt(sum(v*v for v in prob.values())*sum(v*v for v in pooled.values()))
    else:
        for k in ['emotion_tv_to_pool','emotion_jsd_to_pool','emotion_tv_to_human_a','emotion_tv_to_human_b','emotion_jsd_to_human_a','emotion_jsd_to_human_b','mixture_closer_than_both_humans_tv','mixture_closer_than_both_humans_jsd','emotion_cosine_to_pool']:r[k]=None
    dominant=record['dominant_emotion'] if record is not None else None
    r['model_dominant']=dominant
    for m in ['a','b']:
        target=reference[f'human_{m}_dominant']
        target_valid=target is not None and 'dominant_emotion' not in reference[f'human_{m}_validation_errors']
        r[f'dominant_agrees_human_{m}']=dominant==target if dominant is not None and target_valid else None
    pooled_dom=reference['pooled_distribution_dominant']
    r['dominant_agrees_pooled']=dominant==pooled_dom if dominant is not None and pooled_dom is not None else None
    r['dominant_agrees_pooled_tie_aware']=dominant in reference['pooled_distribution_dominant_set'] if dominant is not None and pooled_dom is not None else None
    r['human_dominant_disagreement']=reference['dominant_disagreement']
    errors=[r[f'{key}_range_normalized_error'] for key in SCALARS.values()]+[r['emotion_tv_to_pool']]
    r['overall_soft_reference_distance']=statistics.mean(errors) if all(v is not None for v in errors) else None
    r['mixture_closer_with_human_dominant_disagreement_tv']=r['mixture_closer_than_both_humans_tv'] and reference['dominant_disagreement'] if r['mixture_closer_than_both_humans_tv'] is not None and reference['dominant_disagreement'] is not None else None
    return r


def mean_or_none(values):
    values=[v for v in values if v is not None]
    return statistics.mean(values) if values else None


def aggregate(model, label, rows):
    result={'model':model,'uncertainty_bin':label,'video_rows':len(rows)}
    for key in SCALARS.values():
        valid=[r for r in rows if r[f'{key}_absolute_error'] is not None]
        x=[r[f'{key}_model_value'] for r in valid];y=[r[f'{key}_human_mean_model_scale'] for r in valid]
        result.update({f'{key}_n':len(valid),f'{key}_mae':mean_or_none([r[f'{key}_absolute_error'] for r in valid]),
            f'{key}_rmse':math.sqrt(statistics.mean(r[f'{key}_squared_error'] for r in valid)) if valid else None,
            f'{key}_pearson':pearson(x,y),f'{key}_spearman':pearson(ranks(x),ranks(y))})
    for k in ['emotion_tv_to_pool','emotion_jsd_to_pool','emotion_cosine_to_pool','overall_soft_reference_distance']:
        result[k+'_mean']=mean_or_none([r[k] for r in rows])
        result[k+'_n']=sum(r[k] is not None for r in rows)
    for k in ['dominant_agrees_human_a','dominant_agrees_human_b','dominant_agrees_pooled','dominant_agrees_pooled_tie_aware','mixture_closer_than_both_humans_tv','mixture_closer_than_both_humans_jsd','mixture_closer_with_human_dominant_disagreement_tv']:
        result[k+'_count']=sum(r[k] is True for r in rows)
        result[k+'_n']=sum(r[k] is not None for r in rows)
        result[k+'_rate']=mean_or_none([int(r[k]) if r[k] is not None else None for r in rows])
    eligible=[r for r in rows if r['overall_soft_reference_distance'] is not None and r['overall_human_uncertainty'] is not None]
    result['uncertainty_vs_error_spearman']=pearson(ranks([r['overall_human_uncertainty'] for r in eligible]),ranks([r['overall_soft_reference_distance'] for r in eligible]))
    for key in SCALARS.values():
        eligible=[r for r in rows if r[f'{key}_absolute_error'] is not None and r['overall_human_uncertainty'] is not None]
        result[key+'_error_vs_uncertainty_spearman']=pearson(ranks([r['overall_human_uncertainty'] for r in eligible]),ranks([r[f'{key}_absolute_error'] for r in eligible]))
    eligible=[r for r in rows if r['emotion_tv_to_pool'] is not None and r['overall_human_uncertainty'] is not None]
    result['emotion_tv_vs_uncertainty_spearman']=pearson(ranks([r['overall_human_uncertainty'] for r in eligible]),ranks([r['emotion_tv_to_pool'] for r in eligible]))
    return result


def fmt(v):
    return 'undefined' if v is None else f'{v:.3f}'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=BASE/'pilot_50_reels_30h/results/human_comparison')
    args=parser.parse_args()
    human_sources={'a':BASE/'human_annotation/my_annotations.csv','b':BASE/'human_annotation/annotations.txt'}
    all_sources={**human_sources,**SOURCES}
    hashes={m:hashlib.sha256(p.read_bytes()).hexdigest() for m,p in all_sources.items()}
    with (BASE/'pilot_50_reels_30h/pilot_metadata.csv').open(encoding='utf-8') as f:
        expected=[r['assigned_id'] for r in csv.DictReader(f)]
    assert len(expected)==len(set(expected))==50
    references,audits,bounds=reference_rows(expected,human_sources)
    by_id={r['video_id']:r for r in references}
    evaluations=[];model_audits={}
    for model,path in SOURCES.items():
        raw=[json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
        groups={}
        for r in raw:groups.setdefault(r.get('video_id'),[]).append(r)
        valid={};issues=[]
        for vid,records in groups.items():
            if len(records)!=1:
                issues.append({'video_id':vid,'error':'duplicate ID'});continue
            try:
                VideoAnnotation.model_validate(records[0])
                if 'emotion_points' in records[0]:validate_emotion_points({**records[0],'emotions':records[0]['emotion_points']})
                valid[vid]=records[0]
            except (ValueError,TypeError,KeyError) as exc:issues.append({'video_id':vid,'error':str(exc)})
        model_audits[model]={'issues':issues,'missing_ids':sorted(set(expected)-set(groups)),
            'unexpected_ids':[v for v in groups if v not in expected],
            'probability_normalizations':[v for v,r in valid.items() if abs(sum(r['emotions'].values())-1)>EPS]}
        evaluations += [evaluate(model,valid.get(v),by_id[v]) for v in expected]
    aggregates=[]
    for m in SOURCES:
        for label in ['overall','low','medium','high']:
            aggregates.append(aggregate(m,label,[r for r in evaluations if r['model']==m and (label=='overall' or r['uncertainty_bin']==label)]))
    counts=Counter(r['uncertainty_bin'] for r in references if r['uncertainty_bin'] is not None)
    valid_n=sum(counts.values())
    disagreement={f:mean_or_none([r[f'{f}_uncertainty'] for r in references]) for f in SCALARS}
    disagreement.update(emotion_tv=mean_or_none([r['emotion_tv'] for r in references]),emotion_jsd=mean_or_none([r['emotion_jsd'] for r in references]),dominant_disagreement_rate=mean_or_none([int(r['dominant_disagreement']) if r['dominant_disagreement'] is not None else None for r in references]))
    overall={r['model']:r for r in aggregates if r['uncertainty_bin']=='overall'}
    high={r['model']:r for r in aggregates if r['uncertainty_bin']=='high'}
    eligible_overall=[r for r in overall.values() if r['overall_soft_reference_distance_mean'] is not None]
    closest=min(eligible_overall,key=lambda r:r['overall_soft_reference_distance_mean'])['model'] if eligible_overall else None
    closest_high=min((r for r in high.values() if r['overall_soft_reference_distance_mean'] is not None),key=lambda r:r['overall_soft_reference_distance_mean'])['model'] if any(r['overall_soft_reference_distance_mean'] is not None for r in high.values()) else None
    summary={'schema_version':'human-soft-reference-v1','human_source_validation':audits,'model_validation':model_audits,
        'sources':{m:{'path':p.relative_to(BASE).as_posix(),'sha256':hashes[m]} for m,p in all_sources.items()},
        'expected_n':50,'complete_uncertainty_n':valid_n,'average_human_disagreement':disagreement,
        'uncertainty_formula':'mean(abs(valenceA-valenceB)/10, abs(arousalA-arousalB)/10, abs(recoveryA-recoveryB)/10, emotion_TV, dominant_label_mismatch_0_or_1)',
        'tertile_cutpoints':bounds,'quantile_method':'linear interpolation at positions (n-1)*q; ties not split; low <=q1, medium <=q2, high >q2, tolerance 1e-9',
        'bin_counts':dict(counts),'bin_percentages_valid':{k:100*counts[k]/valid_n if valid_n else None for k in ['low','medium','high']},
        'bin_percentages_all_expected':{k:100*counts[k]/50 for k in ['low','medium','high']},
        'overall_distance_formula':'mean(abs(valence_error)/2, abs(arousal_error), abs(recovery_error), emotion_TV_to_pool)',
        'closest_deployment_overall_by_composite':closest,'closest_deployment_high_uncertainty_by_composite':closest_high,
        'independence':'confirmed_by_user','blindness_to_models':'unverified',
        'interpretation':'Descriptive closeness to two independent perceptions; no perfect ground truth, significance test or held-out model selection.',
        'aggregated_model_metrics':aggregates}
    out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'human_soft_reference.csv',references)
    (out/'human_soft_reference.json').write_text(json.dumps({'schema_version':summary['schema_version'],'rows':references},indent=2,ensure_ascii=False),encoding='utf-8')
    write_csv(out/'model_vs_soft_human_reference.csv',evaluations)
    write_csv(out/'uncertainty_stratified_model_results.csv',aggregates)
    (out/'human_uncertainty_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=['# Soft human reference and uncertainty-aware model comparison','',
        'Two independent human perceptions are preserved, not adjudicated. Every valid paired field is averaged regardless of disagreement. Missing/invalid fields remain null, not fabricated. The pooled distribution is a soft reference, not perfect ground truth; model outputs are not used to construct it.','',
        '## Coverage and provenance','',
        f'50 expected rows; {valid_n} complete human pairs. FV000131 and FV000037 coverage is explicitly recorded in source validation, with no guessed replacements. All raw source files, prior scripts and previous outputs remain unchanged. CSV scalar raw values and eight-emotion scores remain available alongside analysis-only probabilities. Detailed ID/field validation and source hashes are in the summary JSON. Any extra comma-separated CSV note cells are preserved and reported separately; they do not invalidate otherwise valid affect scores.','',
        'A is my_annotations.csv; B is annotations.txt. Duplicate IDs are quarantined, malformed/unexpected IDs reported, numeric values must be finite in [0,10], emotion points sum to 10, and each declared dominant must be a valid maximum. Invalid scalar fields do not poison unrelated fields. Invalid distributions prevent validating their dominant labels. Independence is user-confirmed; blindness to model predictions is unverified.','',
        '## Soft reference and uncertainty','',
        'Scalar mean=(A+B)/2; uncertainty=abs(A-B) on the human 0-to-10 scale. Model-scale valence=(mean-5)/5; arousal and recovery=mean/10. No disagreement threshold rejects valid fields. Both emotion vectors are converted to probabilities and averaged element-wise. TV=half the L1 distance; JSD uses log base 2 and is divergence, not square-root distance.','',
        'Both original dominant labels, exact agreement/disagreement and pooled maximum set are retained. No hard human consensus label is manufactured. A separate pooled-distribution label uses the first exact maximum in the emotion-key order joy, sadness, anger, fear_anxiety, surprise, disgust, calm_contentment, neutral; all ties remain available. Both canonical-label and tie-aware model agreement are reported.','',
        'Overall human uncertainty is the equal-weight mean of three range-normalized scalar differences, emotion TV, and dominant mismatch (0 or 1). It ranges from 0 to 1. This optional index deliberately includes related emotion signals (TV and dominant mismatch); its weights are descriptive choices, not validated psychometrics. Individual uncertainty measures are always retained.','',
        (f'Tertile cutpoints are {bounds[0]:.6f} and {bounds[1]:.6f}, computed from {valid_n} complete human pairs only using linear-interpolated quantiles.' if bounds else 'No complete pairs are available for uncertainty quantiles.')+' Low <= first cutpoint; medium <= second; high > second. Ties are not arbitrarily split, so counts need not be equal. Missing/incomplete videos have no uncertainty bin.','',
        f'| Bin | Videos | Percentage of {valid_n} valid pairs |','| --- | ---: | ---: |']
    for label in ['low','medium','high']:lines.append(f'| {label} | {counts[label]} | {100*counts[label]/valid_n if valid_n else 0:.1f}% |')
    lines += ['', '## Average human disagreement','', '| Field | Mean disagreement |','| --- | ---: |']
    for field,value in disagreement.items():lines.append(f'| {field} | {fmt(value)} |')
    lines += ['', 'Scalar uncertainties are in human 0-to-10 units; TV/JSD and categorical mismatch are on their own documented scales.','',
        '## Models against the pooled human reference','',
        'The overall descriptive distance is the equal-weight mean of valence MAE divided by its range 2, arousal MAE, recovery MAE, and emotion TV. Lower means closer under these explicitly chosen weights. This formula was declared before computing results; correlations and dominant matches are reported separately.','',
        '| Model | N | Valence MAE / RMSE / Pearson / Spearman | Arousal MAE / RMSE / Pearson / Spearman | Recovery MAE / RMSE / Pearson / Spearman | Mean TV | Mean JSD | Composite |','| --- | ---: | --- | --- | --- | ---: | ---: | ---: |']
    for m,s in overall.items():
        cells=[' / '.join(fmt(s[f'{key}_{metric}']) for metric in ['mae','rmse','pearson','spearman']) for key in SCALARS.values()]
        lines.append(f"| {m} | {s['overall_soft_reference_distance_n']} | "+' | '.join(cells)+f" | {fmt(s['emotion_tv_to_pool_mean'])} | {fmt(s['emotion_jsd_to_pool_mean'])} | {fmt(s['overall_soft_reference_distance_mean'])} |")
    lines += ['', 'Scalar errors are on model scales: valence [-1,1], arousal/recovery [0,1]. Metric-specific eligible sample counts are exported. A missing reference field excludes only that metric, not the full row.','',
        '| Model | Dominant agreement A | Dominant agreement B | Pooled canonical label | Pooled tie-aware | Mixture closer than both (TV) | Mixture closer than both (JSD) |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for m,s in overall.items():
        keys=['dominant_agrees_human_a','dominant_agrees_human_b','dominant_agrees_pooled','dominant_agrees_pooled_tie_aware','mixture_closer_than_both_humans_tv','mixture_closer_than_both_humans_jsd']
        lines.append('| '+m+' | '+' | '.join(f"{s[k+'_count']}/{s[k+'_n']}" for k in keys)+' |')
    lines += ['', '## Evaluation stratified by human uncertainty','', '| Model | Bin | N | Valence MAE | Arousal MAE | Recovery MAE | Mean TV | Mean JSD | Composite |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for s in aggregates:
        if s['uncertainty_bin']=='overall':continue
        keys=[key+'_mae' for key in SCALARS.values()]+['emotion_tv_to_pool_mean','emotion_jsd_to_pool_mean','overall_soft_reference_distance_mean']
        lines.append(f"| {s['model']} | {s['uncertainty_bin']} | {s['overall_soft_reference_distance_n']} | "+' | '.join(fmt(s[k]) for k in keys)+' |')
    lines += ['', 'Per-bin RMSE/correlations/dominant agreement are included in uncertainty_stratified_model_results.csv.','',
        '| Model | Low / medium / high composite | High minus low | Spearman uncertainty vs composite error |','| --- | --- | ---: | ---: |']
    for m,s in overall.items():
        bins={a['uncertainty_bin']:a for a in aggregates if a['model']==m}
        values=[bins[label]['overall_soft_reference_distance_mean'] for label in ['low','medium','high']]
        delta=values[2]-values[0] if values[2] is not None and values[0] is not None else None
        lines.append('| '+m+' | '+' / '.join(fmt(v) for v in values)+f" | {fmt(delta)} | {fmt(s['uncertainty_vs_error_spearman'])} |")
    lines += ['', 'Positive high-minus-low values indicate worse descriptive error on the high-uncertainty bin; positive Spearman suggests an increasing association. Inspect all bins: an endpoint difference does not prove monotonic degradation. Per-field error/uncertainty correlations are also exported. No significance or causal claim is made; these small bins contain different videos.','',
        '## Cases closer to a human mixture','',
        'A mixture-match case requires strict TV(model,pool) < min(TV(model,A),TV(model,B)) (tolerance 1e-9). This compares full probability distributions, not categorical labels. JSD has a separate analogous flag; flags can differ. Additional flags identify such cases where the humans chose different dominant labels. A canonical-label mismatch does not erase closeness to the mixture.','',
        '| Video | Model | Human A / B dominant | Model dominant | Pooled maximum set | TV to pool / A / B |','| --- | --- | --- | --- | --- | --- |']
    cases=[r for r in evaluations if r['mixture_closer_with_human_dominant_disagreement_tv']]
    for r in cases:
        ref=by_id[r['video_id']]
        lines.append(f"| {r['video_id']} | {r['model']} | {ref['human_a_dominant']} / {ref['human_b_dominant']} | {r['model_dominant']} | {', '.join(ref['pooled_distribution_dominant_set'])} | {r['emotion_tv_to_pool']:.3f} / {r['emotion_tv_to_human_a']:.3f} / {r['emotion_tv_to_human_b']:.3f} |")
    lines += ['', 'All mixture cases, including humans with the same declared label, are flagged in the per-video CSV. Closer-than-both is not itself an absolute low-error threshold.','',
        '## Limits and reproducibility','',
        'Saved deployments differ: Gemini uses historical v1.0 rubric and direct audio; CUDA models use v1.1-points10 and shared transcript/acoustic/caption evidence, with no direct audio. Qwen caps at 32 frames, InternVL at 16, with different processors. Context hashes previously matched, but native modality access and prompt versions differ. These are deployment comparisons, not isolated model-capability comparisons. The means can hide genuinely bimodal human perceptions, hence raw labels and uncertainty remain available. No pooled reference is claimed to be objective truth or an adjudicated final label.','',
        'Reproduce: `.venv-qwen-cuda/Scripts/python.exe src/build_human_soft_reference.py`. All six requested outputs are under pilot_50_reels_30h/results/human_comparison/. Source hashes and detailed aggregate metrics are in human_uncertainty_summary.json. No original or previous output is overwritten.','', '## Summary','',
        f'1. Mean human disagreement: valence {disagreement["valence"]:.3f}/10; arousal {disagreement["arousal"]:.3f}/10; recovery {disagreement["recovery"]:.3f}/10; emotion TV {disagreement["emotion_tv"]:.3f}; JSD {disagreement["emotion_jsd"]:.3f} bits; dominant mismatch {disagreement["dominant_disagreement_rate"]:.1%}.',
        '2. Low/medium/high uncertainty: '+', '.join(f'{label} {100*counts[label]/valid_n:.1f}% ({counts[label]}/{valid_n})' for label in ['low','medium','high'])+'. One missing paired video is unbinned.',
        f'3. Closest overall by the stated composite: {closest}; descriptive closeness only, not proof of correctness.',
        f'4. Closest on high-human-uncertainty cases by the same composite: {closest_high}.',
        '5. On this pilot, Qwen composite error rises low-to-medium-to-high; Gemini has higher high-bin error than low-bin error but is not monotonic; InternVL composite error decreases across bins. These descriptive associations do not show causality or universal degradation.',
        '6. TV mixture-match counts: '+', '.join(f"{m} {s['mixture_closer_than_both_humans_tv_count']}/{s['mixture_closer_than_both_humans_tv_n']}" for m,s in overall.items())+'. These reward closeness to the human mixture rather than only a hard label.', '']
    (out/'human_soft_reference_report.md').write_text('\n'.join(lines),encoding='utf-8')
    assert hashes=={m:hashlib.sha256(p.read_bytes()).hexdigest() for m,p in all_sources.items()},'Input changed during analysis'
    print(json.dumps({'disagreement':disagreement,'bins':dict(counts),'cutpoints':bounds,'closest_overall':closest,'closest_high':closest_high,
        'overall':[{'model':m,**{k:v for k,v in s.items() if k in ['overall_soft_reference_distance_mean','emotion_tv_to_pool_mean','mixture_closer_than_both_humans_tv_count','uncertainty_vs_error_spearman']}} for m,s in overall.items()]},indent=2))


if __name__=='__main__':main()
