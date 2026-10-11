"""Build an uncertainty-preserving, strictly three-human pilot reference."""
import argparse
import csv
import hashlib
import itertools
import json
import statistics as st
from collections import Counter
from pathlib import Path

from build_human_fieldwise_consensus import BASE, EMOTIONS, SCALARS, EPS, read_source, validated, maxima, tv_jsd, pearson, ranks
from build_human_soft_reference import write_csv, normalize_scalar, quantile
from common_annotation import VideoAnnotation, validate_emotion_points
from compare_pilot_models import SOURCES

HUMANS = {'ali': BASE/'human_annotation/ali_annotation.json',
          'ghayas': BASE/'human_annotation/ghayas_annotation.csv',
          'zara': BASE/'human_annotation/zara_annotation.txt'}
PAIRS = list(itertools.combinations(HUMANS, 2))


def avg(values):
    values = [v for v in values if v is not None]
    return st.mean(values) if values else None


def scalar_stats(x, y):
    return {'n': len(x), 'mae': avg([abs(a-b) for a,b in zip(x,y)]),
            'rmse': (avg([(a-b)**2 for a,b in zip(x,y)])**.5 if x else None),
            'signed_bias': avg([a-b for a,b in zip(x,y)]),
            'pearson': pearson(x,y), 'spearman': pearson(ranks(x),ranks(y))}


def build(expected, sources=HUMANS):
    grouped, audits = {}, {}
    for name,path in sources.items():
        grouped[name],audits[name] = read_source(path,expected)
    rows=[]
    for vid in expected:
        parsed={h:validated(grouped[h].get(vid)) for h in sources}
        row={'video_id':vid}
        for h in sources:
            raw=grouped[h].get(vid)
            row[f'human_{h}_raw_annotations']=raw[0] if raw is not None and len(raw)==1 else raw
            row[f'human_{h}_validation_errors']=parsed[h][1]
            for field,key in SCALARS.items():
                row[f'human_{h}_{key}']=parsed[h][0].get(field)
            row[f'human_{h}_emotion_distribution']=parsed[h][0].get('emotion_distribution')
            row[f'human_{h}_dominant']=parsed[h][0].get('dominant_emotion')
        for field,key in SCALARS.items():
            values=[row[f'human_{h}_{key}'] for h in sources]
            complete=all(v is not None for v in values)
            row[f'{key}_human_mean']=st.mean(values) if complete else None
            row[f'{key}_human_mean_model_scale']=normalize_scalar(field,st.mean(values)) if complete else None
            differences={f'{a}_vs_{b}':abs(row[f'human_{a}_{key}']-row[f'human_{b}_{key}']) for a,b in PAIRS if row[f'human_{a}_{key}'] is not None and row[f'human_{b}_{key}'] is not None}
            row[f'{key}_pairwise_differences']=differences
            row[f'{key}_uncertainty']=st.mean(differences.values()) if complete else None
            row[f'{key}_human_sd']=st.stdev(values) if complete else None
            row[f'{key}_status']='three_valid' if complete else 'missing_or_invalid'
        vectors=[row[f'human_{h}_emotion_distribution'] for h in sources]
        complete=all(v is not None for v in vectors)
        pool={e:st.mean(v[e] for v in vectors) for e in EMOTIONS} if complete else None
        if pool is not None: assert abs(sum(pool.values())-1)<EPS
        distances={f'{a}_vs_{b}':dict(zip(('tv','jsd'),tv_jsd(row[f'human_{a}_emotion_distribution'],row[f'human_{b}_emotion_distribution']))) for a,b in PAIRS if row[f'human_{a}_emotion_distribution'] is not None and row[f'human_{b}_emotion_distribution'] is not None}
        row.update(pooled_emotion_distribution=pool,emotion_pairwise_distances=distances,
                   emotion_tv=avg([d['tv'] for d in distances.values()]) if complete else None,
                   emotion_jsd=avg([d['jsd'] for d in distances.values()]) if complete else None)
        doms=[row[f'human_{h}_dominant'] for h in sources]
        dom_complete=all(d is not None for d in doms)
        row['dominant_pairwise_disagreement']=st.mean(a!=b for a,b in itertools.combinations(doms,2)) if dom_complete else None
        row['all_three_dominant_agree']=len(set(doms))==1 if dom_complete else None
        row['pooled_distribution_dominant_set']=maxima(pool) if pool is not None else []
        row['pooled_distribution_dominant']=row['pooled_distribution_dominant_set'][0] if pool is not None else None
        # The categorical label is separate: absent declared labels cannot erase valid numeric evidence.
        components=[row[f'{key}_uncertainty']/10 if row[f'{key}_uncertainty'] is not None else None for key in SCALARS.values()]+[row['emotion_tv']]
        row['overall_human_uncertainty']=st.mean(components) if all(v is not None for v in components) else None
        row['uncertainty_bin']=None
        rows.append(row)
    values=[r['overall_human_uncertainty'] for r in rows if r['overall_human_uncertainty'] is not None]
    bounds=[quantile(values,p) for p in (1/3,2/3)] if values else None
    for r in rows:
        u=r['overall_human_uncertainty']
        if u is not None:r['uncertainty_bin']='low' if u<=bounds[0]+EPS else 'medium' if u<=bounds[1]+EPS else 'high'
    return rows,audits,bounds


def agreement(rows):
    records=[]
    for a,b in PAIRS:
        for key in SCALARS.values():
            eligible=[r for r in rows if r[f'human_{a}_{key}'] is not None and r[f'human_{b}_{key}'] is not None]
            records.append({'pair':f'{a}_vs_{b}','field':key,**scalar_stats([r[f'human_{a}_{key}'] for r in eligible],[r[f'human_{b}_{key}'] for r in eligible])})
        eligible=[r for r in rows if r[f'human_{a}_dominant'] is not None and r[f'human_{b}_dominant'] is not None]
        x=[r[f'human_{a}_dominant'] for r in eligible];y=[r[f'human_{b}_dominant'] for r in eligible];n=len(x)
        observed=avg([u==v for u,v in zip(x,y)])
        chance=sum(Counter(x)[e]*Counter(y)[e] for e in EMOTIONS)/n**2 if n else None
        records.append({'pair':f'{a}_vs_{b}','field':'dominant_emotion','n':n,'agreement':observed,'cohen_kappa':(observed-chance)/(1-chance) if n and chance<1 else None})
        distances=[tv_jsd(r[f'human_{a}_emotion_distribution'],r[f'human_{b}_emotion_distribution']) for r in rows if r[f'human_{a}_emotion_distribution'] is not None and r[f'human_{b}_emotion_distribution'] is not None]
        records.append({'pair':f'{a}_vs_{b}','field':'emotion_distribution','n':len(distances),'mean_tv':avg([d[0] for d in distances]),'median_tv':st.median(d[0] for d in distances) if distances else None,'mean_jsd':avg([d[1] for d in distances])})
    eligible=[r for r in rows if r['all_three_dominant_agree'] is not None]
    n=len(eligible);counts=[Counter(r[f'human_{h}_dominant'] for h in HUMANS) for r in eligible]
    observed=avg([sum(c*(c-1) for c in count.values())/6 for count in counts])
    chance=sum((sum(c[e] for c in counts)/(3*n))**2 for e in EMOTIONS) if n else None
    return records,{'n':n,'all_three_agreement':avg([r['all_three_dominant_agree'] for r in eligible]),'fleiss_kappa':(observed-chance)/(1-chance) if n and chance<1 else None}


def evaluate(model,record,ref):
    result={'video_id':ref['video_id'],'model':model,'uncertainty_bin':ref['uncertainty_bin'],'overall_human_uncertainty':ref['overall_human_uncertainty']}
    for key in SCALARS.values():
        result[key+'_prediction']=record[key]
        result[key+'_reference']=ref[key+'_human_mean_model_scale']
    prob={e:record['emotions'][e]/sum(record['emotions'].values()) for e in EMOTIONS}
    pool=ref['pooled_emotion_distribution'];result['model_distribution']=prob;result['pooled_distribution']=pool
    result['emotion_tv'],result['emotion_jsd']=tv_jsd(prob,pool) if pool is not None else (None,None)
    for h in HUMANS:
        target=ref[f'human_{h}_dominant']
        result[f'dominant_agrees_{h}']=record['dominant_emotion']==target if target is not None else None
    result['dominant_agrees_pool']=record['dominant_emotion']==ref['pooled_distribution_dominant'] if pool is not None else None
    result['dominant_agrees_pool_tie_aware']=record['dominant_emotion'] in ref['pooled_distribution_dominant_set'] if pool is not None else None
    distances=[tv_jsd(prob,ref[f'human_{h}_emotion_distribution']) for h in HUMANS] if pool is not None else []
    result['mixture_closer_than_all_humans_tv']=result['emotion_tv']<min(d[0] for d in distances)-EPS if distances else None
    result['mixture_closer_than_all_humans_jsd']=result['emotion_jsd']<min(d[1] for d in distances)-EPS if distances else None
    return result


def aggregate(model,label,rows):
    result={'model':model,'uncertainty_bin':label,'video_rows':len(rows)}
    for key in SCALARS.values():
        eligible=[r for r in rows if r[key+'_reference'] is not None]
        result.update({key+'_'+k:v for k,v in scalar_stats([r[key+'_prediction'] for r in eligible],[r[key+'_reference'] for r in eligible]).items()})
    for key in ['emotion_tv','emotion_jsd',*[f'dominant_agrees_{h}' for h in HUMANS],'dominant_agrees_pool','dominant_agrees_pool_tie_aware','mixture_closer_than_all_humans_tv','mixture_closer_than_all_humans_jsd']:
        result[key+'_mean']=avg([r[key] for r in rows]);result[key+'_n']=sum(r[key] is not None for r in rows)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=BASE/'pilot_50_reels_30h/results/three_human_evaluation/reference')
    args=parser.parse_args();out=args.output_dir
    if out.exists():raise ValueError('Choose a new output directory; do not overwrite an analysis')
    hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in [*HUMANS.values(),*SOURCES.values()]}
    with (BASE/'pilot_50_reels_30h/pilot_metadata.csv').open(encoding='utf-8') as f:expected=[r['assigned_id'] for r in csv.DictReader(f)]
    assert len(expected)==len(set(expected))==50
    refs,audits,bounds=build(expected);pairs,multi=agreement(refs);evals=[];model_audits={}
    for model,path in SOURCES.items():
        records=[json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
        ids=[r['video_id'] for r in records]
        if len(ids)!=len(set(ids)) or set(ids)!=set(expected):raise ValueError(f'{model}: nonmatching or duplicate pilot IDs')
        for r in records:
            VideoAnnotation.model_validate(r)
            if 'emotion_points' in r:validate_emotion_points({**r,'emotions':r['emotion_points']})
        by={r['video_id']:r for r in records}
        evals.extend(evaluate(model,by[r['video_id']],r) for r in refs)
        model_audits[model]={'n':len(ids),'missing_ids':[],'unexpected_ids':[],'duplicates':[]}
    aggregates=[aggregate(m,label,[r for r in evals if r['model']==m and (label=='overall' or r['uncertainty_bin']==label)]) for m in SOURCES for label in ['overall','low','medium','high']]
    counts=Counter(r['uncertainty_bin'] for r in refs if r['uncertainty_bin'] is not None)
    summary={'schema_version':'three-human-soft-reference-v1','annotators':list(HUMANS),'human_source_validation':audits,'model_validation':model_audits,
             'sources':{p.relative_to(BASE).as_posix():digest for p,digest in hashes.items()},'expected_n':50,'complete_uncertainty_n':sum(counts.values()),
             'field_eligible_counts':{key:sum(r[key+'_human_mean'] is not None for r in refs) for key in SCALARS.values()},
             'distribution_eligible_n':sum(r['pooled_emotion_distribution'] is not None for r in refs),
             'average_human_disagreement':{**{key:avg([r[key+'_uncertainty'] for r in refs]) for key in SCALARS.values()},'emotion_tv':avg([r['emotion_tv'] for r in refs]),'emotion_jsd':avg([r['emotion_jsd'] for r in refs]),'dominant_pairwise_disagreement':avg([r['dominant_pairwise_disagreement'] for r in refs])},
             'uncertainty_formula':'mean(mean_pairwise_abs_valence/10, mean_pairwise_abs_arousal/10, mean_pairwise_abs_recovery/10, mean_pairwise_emotion_TV); declared dominant disagreement is reported separately',
             'tertile_cutpoints':bounds,'bin_counts':dict(counts),'pairwise_agreement':pairs,'three_rater_dominant_agreement':multi,'aggregated_model_metrics':aggregates,
             'independence':'user_confirmed','blindness':'unverified','pooling_policy':'Require three valid values per field; never silently fall back to two annotators. Invalid distributions do not discard scalar values. Raw labels preserved.'}
    out.mkdir(parents=True)
    write_csv(out/'human_soft_reference.csv',refs)
    (out/'human_soft_reference.json').write_text(json.dumps({'schema_version':summary['schema_version'],'rows':refs},indent=2,ensure_ascii=False),encoding='utf-8')
    (out/'human_uncertainty_summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    write_csv(out/'human_pairwise_agreement.csv',pairs)
    write_csv(out/'model_vs_soft_human_reference.csv',evals)
    write_csv(out/'uncertainty_stratified_model_results.csv',aggregates)
    lines=['# Three-human soft reference and pilot evaluation','','Ali, Ghayas and Zara are independent according to the user. Blindness to model predictions is unverified. This reference represents three perceptions, not perfect ground truth. Raw files are unchanged.','','## Validation','',json.dumps(audits,indent=2), '',
           'Require all three valid annotations independently per field. Emotion totals must equal 10; invalid totals are reported, never silently repaired. Missing/invalid dominant labels remain unresolved; no synonyms or ID replacements are guessed. Valid disagreements are always preserved and pooled. Scalars use mean(A,B,C); distributions use the element-wise mean of the three probability vectors. Valence maps as (score-5)/5; arousal/recovery as score/10. Pooled maximum ties remain available, with emotion-key order used only for the separate canonical display label.','',
           'Uncertainty: '+summary['uncertainty_formula']+'. JSD uses base-2 logarithms. Tertiles use linear-interpolated quantiles on complete numeric/distribution references; ties are not split. Dominant disagreement is separate so null categorical labels do not invalidate complete numeric evidence.','',
           f'Coverage: scalar fields {summary["field_eligible_counts"]}; distributions {summary["distribution_eligible_n"]}/50; complete three-rater dominant labels {multi["n"]}/50. Bins {dict(counts)}; cutpoints {bounds}.','',
           '## Human-human agreement','','| Pair | Field | N | MAE / mean TV | Pearson / agreement | Spearman / kappa |','| --- | --- | ---: | --- | --- | --- |']
    for r in pairs:lines.append(f'| {r["pair"]} | {r["field"]} | {r["n"]} | {r.get("mae",r.get("mean_tv"))} | {r.get("pearson",r.get("agreement"))} | {r.get("spearman",r.get("cohen_kappa"))} |')
    lines+=['',f'Three-rater categorical statistics: {multi}. These use only valid declared labels, not invented distribution-derived replacements.','','## Model comparison by uncertainty','','| Model | Bin | Valence MAE | Arousal MAE | Recovery MAE | TV | JSD |','| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for r in aggregates:lines.append('| '+r['model']+' | '+r['uncertainty_bin']+' | '+' | '.join(f'{r[k]:.3f}' if r[k] is not None else 'undefined' for k in ['valence_mae','arousal_mae','recovery_suitability_mae','emotion_tv_mean','emotion_jsd_mean'])+' |')
    lines+=['','Metric-specific counts, scalar RMSE/Pearson/Spearman/bias, each human dominant match, pooled tie-aware matches and mixture-closeness counts are exported. Mixture closeness means strictly closer to the pool than each individual human distribution; it is not an absolute accuracy threshold.','','Gemini uses a historical rubric and direct audio. CUDA models use shared transcript/eGeMAPS/caption evidence, different rubric/frame caps and no direct raw audio. Deployment comparisons remain confounded. Nested calibration and model recommendations are in ../calibration_final/final_calibration_report.md. No full-dataset annotation starts.']
    (out/'human_soft_reference_report.md').write_text('\n'.join(lines),encoding='utf-8')
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in hashes.items())
    print(json.dumps({'coverage':summary['field_eligible_counts'],'distributions':summary['distribution_eligible_n'],'dominant':multi,'bins':dict(counts)},indent=2))


if __name__=='__main__':main()
