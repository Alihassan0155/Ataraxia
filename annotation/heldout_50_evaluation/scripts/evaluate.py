"""Held-out validation with frozen pilot calibration; never fit held-out data."""
import csv
import hashlib
import itertools
import json
import math
from collections import Counter
import numpy as np
from support import ROOT, read, write, validate_freeze, predictions
from build_three_human_reference import build, agreement, scalar_stats
from build_human_fieldwise_consensus import EMOTIONS, EPS, maxima, ranks
from build_human_soft_reference import write_csv
from analyze_model_calibration import apply_scalar, apply_emotion, scalar_metrics, emotion_distances

FIELDS=('valence','arousal','recovery_suitability')
MODELS=('qwen','internvl','gemini')
HUMANS=('ali','ghayas','zara')
RANGES=np.array([2.,1.,1.])


def calibration(raw_scalars,raw_distributions,plan):
    """Pure application of coefficients loaded from the original pilot."""
    scalars=np.column_stack([apply_scalar(raw_scalars[:,j],plan[key]['full_pilot_fit_parameters'],j) for j,key in enumerate(FIELDS)])
    distribution=apply_emotion(raw_distributions,plan['emotions']['full_pilot_fit_parameters'])
    if not np.allclose(distribution.sum(axis=1),1):raise ValueError('Calibrated distribution not normalized')
    return scalars,distribution


def metric_values(x,p,y,q,dom,ref_doms,pooled_sets):
    result={}
    for j,key in enumerate(FIELDS):result.update({key+'_'+metric:value for metric,value in scalar_metrics(x[:,j],y[:,j]).items()})
    d=emotion_distances(p,q)
    result.update(emotion_tv=float(np.mean(d[:,0])),emotion_jsd=float(np.mean(d[:,1])))
    for h,target in ref_doms.items():result['dominant_agreement_'+h]=float(np.mean([a==b for a,b in zip(dom,target)]))
    result['dominant_agreement_pooled']=float(np.mean([a==target[0] for a,target in zip(dom,pooled_sets)]))
    result['dominant_agreement_pooled_tie_aware']=float(np.mean([a in target for a,target in zip(dom,pooled_sets)]))
    result['scalar_plus_tv_composite']=float(np.mean(np.column_stack((abs(x-y)/RANGES,d[:,0]))))
    return result


def subset(values,indices):
    x,p,y,q,dom,ref_doms,pool=values
    return x[indices],p[indices],y[indices],q[indices],[dom[i] for i in indices],{h:[ds[i] for i in indices] for h,ds in ref_doms.items()},[pool[i] for i in indices]


def confidence(draws):
    valid=np.array([v for v in draws if v is not None and math.isfinite(v)])
    return {'ci_lower':float(np.quantile(valid,.025)) if len(valid) else None,
            'ci_upper':float(np.quantile(valid,.975)) if len(valid) else None,'valid_bootstrap_draws':len(valid)}


def bootstrap(values,settings):
    rng=np.random.default_rng(settings['seed']);samples=rng.integers(0,50,size=(settings['resamples'],50))
    # Exact same sampled videos for every model, variant and paired difference.
    results={key:[] for key in values}
    for indices in samples:
        for key,data in values.items():results[key].append(metric_values(*subset(data,indices)))
    point={key:metric_values(*data) for key,data in values.items()}
    intervals=[];differences=[]
    for key,metrics in point.items():
        for metric,value in metrics.items():intervals.append({'model':key[0],'variant':key[1],'metric':metric,'estimate':value,**confidence([r[metric] for r in results[key]])})
    comparisons=[((a,variant),(b,variant)) for variant in ['raw','calibrated'] for a,b in itertools.combinations(MODELS,2)]
    comparisons += [((model,'calibrated'),(model,'raw')) for model in MODELS]
    for first,second in comparisons:
        for metric in point[first]:
            av,bv=point[first][metric],point[second][metric]
            diff=[a[metric]-b[metric] if a[metric] is not None and b[metric] is not None else None for a,b in zip(results[first],results[second])]
            ci=confidence(diff)
            higher='pearson' in metric or 'spearman' in metric or 'agreement' in metric
            differences.append({'first_model':first[0],'first_variant':first[1],'second_model':second[0],'second_variant':second[1],
                'metric':metric,'difference_first_minus_second':av-bv if av is not None and bv is not None else None,**ci,
                'higher_is_better':higher,'interval_includes_zero':ci['ci_lower']<=0<=ci['ci_upper'] if ci['ci_lower'] is not None else None,
                'interpretation':'Paired percentile CI conditional on fixed pilot calibration and held-out sample; excludes refitting and model-selection uncertainty'})
    return point,intervals,differences


def ranking(values,labels,weights):
    rows=[]
    high=np.array(labels)=='high'
    for (model,variant),(x,p,y,q,*_) in values.items():
        d=emotion_distances(p,q)[:,0]
        errors=abs(x-y)/RANGES
        rows.append({'model':model,'variant':variant,'scalar_alignment_mean':float(np.mean(errors)),
                     'emotion_tv':float(np.mean(d)),
                     'high_uncertainty_composite':float(np.mean(np.column_stack((errors[high],d[high])))) if sum(high) else None,
                     'mean_absolute_scalar_bias':float(np.mean(abs(np.mean(x-y,axis=0))/RANGES)),
                     'worst_scalar_normalized_mae':float(np.max(np.mean(errors,axis=0)))})
    for variant in ['raw','calibrated']:
        subset_rows=[r for r in rows if r['variant']==variant]
        usable={k:w for k,w in weights.items() if all(r[k] is not None for r in subset_rows)}
        total=sum(usable.values())
        for r in subset_rows:r['weighted_metric_rank']=0.;r['effective_weights']={k:w/total for k,w in usable.items()}
        for metric,weight in usable.items():
            for r,value in zip(subset_rows,ranks([r[metric] for r in subset_rows])):r['weighted_metric_rank']+=value*weight/total
        for position,r in enumerate(sorted(subset_rows,key=lambda r:(r['weighted_metric_rank'],r['scalar_alignment_mean'])),1):r['rank']=position
    return rows


def main():
    cfg=validate_freeze();sources={h:ROOT/'human_annotations'/h/'annotations.csv' for h in HUMANS}
    refs,audits,_=build(cfg['heldout_ids'],sources)
    invalid=[{'video_id':r['video_id'],'annotator':h,'errors':r[f'human_{h}_validation_errors']} for r in refs for h in HUMANS if r[f'human_{h}_validation_errors']]
    # Labels are required for all five affect fields. Confidence/notes are optional.
    source_id_issues=any(a['missing_ids'] or a['unexpected_ids'] or a['issues'] for a in audits.values())
    if invalid or source_id_issues:
        write(ROOT/'reports/input_status.json',{'status':'waiting_for_complete_valid_three_human_annotations','human_source_validation':audits,'field_errors':invalid,'evaluation_performed':False})
        print(f'Evaluation stopped: complete valid labels required from all three humans for exactly 50 IDs. {len(invalid)} invalid/missing annotator-video records; see reports/input_status.json.')
        raise SystemExit(2)
    # Frozen pilot thresholds; held-out quantiles are never used for policy selection.
    low,medium=cfg['uncertainty_cutpoints']
    for r in refs:
        u=r['overall_human_uncertainty'];r['uncertainty_bin']='low' if u<=low+EPS else 'medium' if u<=medium+EPS else 'high'
    raw={m:predictions(m,cfg) for m in MODELS}
    missing={m:sorted(set(cfg['heldout_ids'])-set(r)) for m,r in raw.items() if len(r)!=50}
    if missing:
        write(ROOT/'reports/input_status.json',{'status':'waiting_for_complete_model_predictions','missing_ids':missing,'evaluation_performed':False});print('Evaluation stopped: incomplete model predictions.');raise SystemExit(2)
    selection=read(ROOT/'config/pilot_calibration_and_selection.json')
    before=hashlib.sha256((ROOT/'config/pilot_calibration_and_selection.json').read_bytes()).hexdigest()
    if before!=cfg['calibration_source_sha256']:raise ValueError('Pilot calibration changed')
    y=np.array([[r[key+'_human_mean_model_scale'] for key in FIELDS] for r in refs]);q=np.array([[r['pooled_emotion_distribution'][e] for e in EMOTIONS] for r in refs])
    labels=[r['uncertainty_bin'] for r in refs];ids=[r['video_id'] for r in refs]
    ref_doms={h:[r[f'human_{h}_dominant'] for r in refs] for h in HUMANS};pooled_sets=[r['pooled_distribution_dominant_set'] for r in refs]
    values={};per_video=[];name_map={'qwen':'Qwen','internvl':'InternVL','gemini':'Gemini'}
    for model in MODELS:
        records=[raw[model][vid] for vid in ids]
        x=np.array([[r[key] for key in FIELDS] for r in records]);p=np.array([[r['emotions'][e] for e in EMOTIONS] for r in records]);p/=p.sum(axis=1)[:,None]
        plan=selection['calibration_plans'][name_map[model]]['calibration']
        sx,sp=calibration(x,p,plan)
        original_dom=[r['dominant_emotion'] for r in records]
        corrected_dom=original_dom if plan['emotions']['method']=='raw' else [maxima(dict(zip(EMOTIONS,row)))[0] for row in sp]
        values[(model,'raw')]=(x,p,y,q,original_dom,ref_doms,pooled_sets)
        values[(model,'calibrated')]=(sx,sp,y,q,corrected_dom,ref_doms,pooled_sets)
        corrected=[]
        for i,vid in enumerate(ids):
            r={'video_id':vid,'raw_annotation':records[i],'calibrated_scalars':dict(zip(FIELDS,map(float,sx[i]))),'calibrated_emotions':dict(zip(EMOTIONS,map(float,sp[i]))),'calibrated_dominant':corrected_dom[i],
               'pilot_calibration_sha256':before,'uncertainty_bin':labels[i]}
            corrected.append(r)
            for variant,xx,pp,dom in [('raw',x,p,original_dom),('calibrated',sx,sp,corrected_dom)]:
                distances=emotion_distances(pp[i:i+1],q[i:i+1])[0]
                per_video.append({'video_id':vid,'model':model,'variant':variant,'uncertainty_bin':labels[i],
                    **{key+'_absolute_error':float(abs(xx[i,j]-y[i,j])) for j,key in enumerate(FIELDS)},'emotion_tv':float(distances[0]),'emotion_jsd':float(distances[1]),
                    **{f'dominant_agrees_{h}':dom[i]==ref_doms[h][i] for h in HUMANS},'dominant_agrees_pooled':dom[i]==pooled_sets[i][0],
                    'dominant_agrees_pooled_tie_aware':dom[i] in pooled_sets[i]})
        write(ROOT/'calibrated'/f'{model}.json',corrected)
    print('Inputs complete. Computing paired bootstrap with frozen calibration only...',flush=True)
    points,intervals,differences=bootstrap(values,cfg['bootstrap'])
    ranked=ranking(values,labels,cfg['ranking_weights']);stratified=[]
    for key,data in values.items():
        for label in ['low','medium','high']:
            indices=np.where(np.array(labels)==label)[0]
            if len(indices):stratified.append({'model':key[0],'variant':key[1],'uncertainty_bin':label,'n':len(indices),**metric_values(*subset(data,indices))})
    agreements,multi=agreement(refs)
    write(ROOT/'reports/human_soft_reference.json',{'rows':refs,'uncertainty_cutpoints_source':'frozen original pilot','cutpoints':[low,medium],'source_validation':audits})
    write_csv(ROOT/'reports/human_soft_reference.csv',refs)
    write_csv(ROOT/'reports/human_pairwise_agreement.csv',agreements)
    write_csv(ROOT/'reports/raw_vs_calibrated_metrics.csv',[{'model':k[0],'variant':k[1],'n':50,**v} for k,v in points.items()])
    write_csv(ROOT/'reports/metric_confidence_intervals.csv',intervals)
    write_csv(ROOT/'reports/paired_bootstrap_differences.csv',differences)
    write_csv(ROOT/'reports/uncertainty_stratified_metrics.csv',stratified)
    write_csv(ROOT/'reports/per_video_errors.csv',per_video)
    write_csv(ROOT/'reports/model_ranking.csv',ranked)
    order={variant:[r['model'] for r in sorted([r for r in ranked if r['variant']==variant],key=lambda r:r['rank'])] for variant in ['raw','calibrated']}
    inconclusive=[r for r in differences if r['first_variant']==r['second_variant']=='calibrated' and r['metric']=='scalar_plus_tv_composite' and r['interval_includes_zero']]
    decision={'raw_ranking':order['raw'],'frozen_calibrated_ranking':order['calibrated'],'recommended_pair':order['calibrated'][:2],
              'ranking_weights_source':'original pilot, not tuned on held-out labels','inconclusive_calibrated_composite_pairs':inconclusive,
              'qualification':'Nominal descriptive recommendation; CI overlap/inconclusive differences are not evidence of superiority or equivalence. Comparing three candidates can still introduce model-selection optimism.',
              'human_dominant_agreement':multi,'uncertainty_bins':dict(Counter(labels)),'configuration_gaps':cfg['gaps'],'full_dataset_annotation_started':False}
    amendment=ROOT/'config/reliability_amendment_v4.json'
    if not amendment.exists():amendment=ROOT/'config/reliability_amendment_v3.json'
    if not amendment.exists():amendment=ROOT/'config/reliability_amendment_v2.json'
    if amendment.exists():decision['operational_protocol_amendment']=read(amendment)
    write(ROOT/'reports/final_model_selection.json',decision)
    lines=['# Held-out 50-video validation','','Exactly 50 unique held-out IDs; zero original-pilot ID/byte overlap. All 150 human annotation records validated; originals and model predictions unchanged. Frozen pilot coefficients were only applied, never fitted or selected here. Human uncertainty cutpoints and ranking weights were frozen from development.','',
           '## Raw and calibrated performance','','| Model | Variant | Valence MAE | Arousal MAE | Recovery MAE | TV | JSD | Pooled dominant agreement |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for key,v in points.items():lines.append('| '+key[0]+' | '+key[1]+' | '+' | '.join(f'{v[k]:.3f}' for k in ['valence_mae','arousal_mae','recovery_suitability_mae','emotion_tv','emotion_jsd','dominant_agreement_pooled'])+' |')
    lines+=['','RMSE, Pearson, Spearman, signed bias and agreement with each of the three humans are exported. Raw predictions and original human labels remain separate from calibrated/reference copies.','',
            '## Uncertainty and paired confidence intervals','',f'Human uncertainty bin counts: {dict(Counter(labels))}. Three-rater declared-label agreement: {multi}.',
            f'Bootstrap: {cfg["bootstrap"]["resamples"]} matched video-level resamples, seed {cfg["bootstrap"]["seed"]}; percentile 95% intervals. Calibrators and the observed three human perceptions remain fixed; these intervals do not quantify annotator-population or provider-repeat variability. Degenerate correlation draws are omitted with valid counts recorded. No multiple-comparison adjustment is claimed; all intervals are descriptive.','',
            '| Calibrated comparison | Composite difference | Paired 95% CI | Inconclusive |','| --- | ---: | --- | --- |']
    for r in differences:
        if r['first_variant']==r['second_variant']=='calibrated' and r['metric']=='scalar_plus_tv_composite':lines.append(f'| {r["first_model"]} - {r["second_model"]} | {r["difference_first_minus_second"]:.3f} | [{r["ci_lower"]:.3f}, {r["ci_upper"]:.3f}] | {r["interval_includes_zero"]} |')
    lines+=['','Per-model metric intervals, all pairwise metric differences, within-model calibration gains, and low/medium/high metrics are exported. Lower scalar errors and TV/JSD are better; higher correlations and dominant agreement are better. Signed bias alone is not a quality rank.','',
            '## Final research recommendation','', 'Raw order: '+' > '.join(order['raw'])+'.','Frozen-calibrated order: '+' > '.join(order['calibrated'])+'.',
            'Nominal pair: '+', '.join(decision['recommended_pair'])+'.',decision['qualification'],'',
            '## Configuration and interpretation limits','',*['- '+g for g in cfg['gaps']], '',
            'Operational amendments in config/reliability_amendment_v2.json, v3.json and v4.json record changed timeouts and InternVL repair/normalization policy after observed failures. V4 adds bounded same-video key failover. V3 permits proportional total-10 normalization after two repairs; normalized records are explicitly flagged with original scores preserved. Earlier predictions retain their earlier policy. Pilot calibration and primary prompts were not retuned. This limits claims of completely unchanged held-out inference.','',
            'Direct modality access, prompt versions and frame sampling differ across deployments. Byte-level isolation does not establish creator/near-duplicate independence. Held-out labels cannot be reused to improve these calibrators; a new development study/version would be required. No full-dataset annotation has started.']
    (ROOT/'reports/final_heldout_report.md').write_text('\n'.join(lines),encoding='utf-8')
    assert hashlib.sha256((ROOT/'config/pilot_calibration_and_selection.json').read_bytes()).hexdigest()==before
    write(ROOT/'reports/input_status.json',{'status':'complete','human_records':150,'predictions':150,'calibration_refitted':False,'configuration_gaps':cfg['gaps']})
    print(json.dumps(decision,indent=2))


if __name__=='__main__':main()
