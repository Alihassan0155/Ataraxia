"""OOF/nested-CV bias calibration audit; writes only a new analysis directory."""
import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
import numpy as np

from build_human_fieldwise_consensus import BASE, EMOTIONS, pearson, ranks, tv_jsd
from compare_pilot_models import SOURCES
from common_annotation import VideoAnnotation, validate_emotion_points

FIELDS=('valence','arousal','recovery_suitability')
RANGES=np.array([2.,1.,1.])
LOWER=np.array([-1.,0.,0.]);UPPER=np.ones(3)
SEED=20261007


def json_default(value):
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,np.ndarray):return value.tolist()
    raise TypeError(type(value).__name__)


def folds(labels,k,seed):
    """Stratify on preexisting uncertainty bins only; no target/error strata."""
    rng=np.random.default_rng(seed);buckets=[[] for _ in range(k)]
    for label in sorted(set(labels)):
        indices=np.where(np.array(labels)==label)[0];rng.shuffle(indices)
        # Start with the currently smallest bucket to balance strata remainders.
        start=min(range(k),key=lambda j:len(buckets[j]))
        for i,index in enumerate(indices):buckets[(start+i)%k].append(int(index))
    return [np.array(sorted(b),dtype=int) for b in buckets]


def fit_scalar(x,y,method):
    if method=='raw':return {'method':'raw'}
    if method=='linear':
        if np.ptp(x)<1e-12:return {'method':'linear','slope':0.,'intercept':float(np.mean(y))}
        slope,intercept=np.linalg.lstsq(np.column_stack((x,np.ones(len(x)))),y,rcond=None)[0]
        return {'method':'linear','slope':float(slope),'intercept':float(intercept)}
    order=np.argsort(x,kind='stable');xx=x[order];yy=y[order]
    knots,starts=np.unique(xx,return_index=True)
    ends=np.r_[starts[1:],len(xx)]
    weights=ends-starts;averages=np.array([np.mean(yy[a:b]) for a,b in zip(starts,ends)])
    # Weighted pool-adjacent-violators, grouping equal predictions first.
    blocks=[]
    for j,(value,weight) in enumerate(zip(averages,weights)):
        blocks.append([j,j,float(weight),float(value)*weight])
        while len(blocks)>1 and blocks[-2][3]/blocks[-2][2]>blocks[-1][3]/blocks[-1][2]:
            b=blocks.pop();a=blocks.pop();blocks.append([a[0],b[1],a[2]+b[2],a[3]+b[3]])
    fitted=np.empty(len(knots))
    for first,last,weight,total in blocks:fitted[first:last+1]=total/weight
    return {'method':'isotonic','x_knots':knots.tolist(),'y_knots':fitted.tolist(),
            'unique_input_levels':len(knots),'monotone_blocks':len(blocks)}


def apply_scalar(x,fit,j):
    if fit['method']=='raw':result=x.copy()
    elif fit['method']=='linear':result=fit['slope']*x+fit['intercept']
    else:result=np.interp(x,fit['x_knots'],fit['y_knots'])
    return np.clip(result,LOWER[j],UPPER[j])


def fit_emotion(x,y,method):
    return {'method':method,'offsets':(np.mean(y-x,axis=0) if method!='raw' else np.zeros(8)).tolist(),
            'fallback_distribution':np.mean(y,axis=0).tolist(),'slopes':[1.]*8}


def apply_emotion(x,fit):
    corrected=np.clip(x+np.array(fit['offsets']),0,1);total=corrected.sum(axis=1)
    good=total>1e-12
    corrected[good]/=total[good,None]
    corrected[~good]=fit['fallback_distribution']
    return corrected


def scalar_metrics(x,y):
    delta=x-y
    return {'signed_bias':float(np.mean(delta)),'mae':float(np.mean(abs(delta))),
            'rmse':float(np.sqrt(np.mean(delta**2))),'pearson':pearson(x.tolist(),y.tolist()),
            'spearman':pearson(ranks(x.tolist()),ranks(y.tolist()))}


def emotion_distances(x,y):
    return np.array([tv_jsd(dict(zip(EMOTIONS,a)),dict(zip(EMOTIONS,b))) for a,b in zip(x,y)])


def choose_scalar(x,y,labels,j,seed):
    inner=folds(labels,4,seed);pred={m:np.empty(len(x)) for m in ['raw','linear','isotonic']}
    for test in inner:
        train=np.setdiff1d(np.arange(len(x)),test)
        for m in pred:pred[m][test]=apply_scalar(x[test],fit_scalar(x[train],y[train],m),j)
    base=float(np.mean(abs(pred['raw']-y)));candidates=[]
    for m in ['linear','isotonic']:
        gain=base-float(np.mean(abs(pred[m]-y)))
        wins=sum(np.mean(abs(pred[m][t]-y[t]))<np.mean(abs(pred['raw'][t]-y[t])) for t in inner)
        # Isotonic with few distinct model scores is particularly fragile.
        adequate=m!='isotonic' or all(len(np.unique(x[np.setdiff1d(np.arange(len(x)),t)]))>=8 for t in inner)
        if gain>=.01*RANGES[j] and gain>=.05*base and wins>=3 and adequate:
            candidates.append((float(np.mean(abs(pred[m]-y))),m))
    if not candidates:return 'raw'
    best=min(candidates)[1]
    if best=='isotonic' and any(m=='linear' and error<=min(candidates)[0]+.003*RANGES[j] for error,m in candidates):best='linear'
    return best


def choose_emotion(x,y,labels,seed):
    inner=folds(labels,4,seed);corrected=np.empty_like(x)
    for test in inner:
        train=np.setdiff1d(np.arange(len(x)),test)
        corrected[test]=apply_emotion(x[test],fit_emotion(x[train],y[train],'offset'))
    raw=emotion_distances(x,y);cal=emotion_distances(corrected,y)
    gain=np.mean(raw,axis=0)-np.mean(cal,axis=0)
    wins=sum(np.mean(cal[t,0])<np.mean(raw[t,0]) for t in inner)
    return 'offset' if gain[0]>=.01 and gain[0]>=.05*np.mean(raw[:,0]) and gain[1]>0 and wins>=3 else 'raw'


def write_csv(path,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        for row in rows:w.writerow({k:json.dumps(v) if isinstance(v,(list,dict)) else v for k,v in row.items()})


def profile(model,variant,x,p,y,q,labels):
    metrics=[scalar_metrics(x[:,j],y[:,j]) for j in range(3)]
    ds=emotion_distances(p,q);normalized=np.mean(abs(x-y)/RANGES,axis=0)
    high=np.array(labels)=='high'
    return {'model':model,'variant':variant,'valence_mae':metrics[0]['mae'],'arousal_mae':metrics[1]['mae'],
        'recovery_mae':metrics[2]['mae'],'scalar_alignment_mean':float(np.mean(normalized)),
        'emotion_tv':float(np.mean(ds[:,0])),'emotion_jsd':float(np.mean(ds[:,1])),
        'high_uncertainty_composite':float(np.mean(np.column_stack((abs(x[high]-y[high])/RANGES,ds[high,0])))),
        'mean_absolute_scalar_bias':float(np.mean([abs(metrics[j]['signed_bias'])/RANGES[j] for j in range(3)])),
        'worst_scalar_normalized_mae':float(max(normalized)),
        'equal_weight_scalar_plus_tv_composite':float(np.mean(np.r_[normalized,np.mean(ds[:,0])]))}


def add_ranking(rows):
    weights={'scalar_alignment_mean':.40,'emotion_tv':.25,'high_uncertainty_composite':.15,
             'mean_absolute_scalar_bias':.10,'worst_scalar_normalized_mae':.10}
    for variant in sorted({r['variant'] for r in rows}):
        subset=[r for r in rows if r['variant']==variant]
        for r in subset:r['weighted_metric_rank']=0.
        for key,weight in weights.items():
            values=ranks([r[key] for r in subset])
            for r,value in zip(subset,values):r[key+'_rank']=value;r['weighted_metric_rank']+=weight*value
        for rank,r in enumerate(sorted(subset,key=lambda r:(r['weighted_metric_rank'],r['scalar_alignment_mean'])),1):r['rank']=rank
    return weights


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=BASE/'pilot_50_reels_30h/results/final_calibration_analysis')
    args=parser.parse_args();out=args.output_dir
    if out.exists():raise ValueError('Create-new-only: choose a fresh --output-dir; existing analysis is preserved')
    soft=BASE/'pilot_50_reels_30h/results/human_comparison/human_soft_reference.json'
    previous=BASE/'pilot_50_reels_30h/results/human_comparison/human_uncertainty_summary.json'
    hashes={str(p.relative_to(BASE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [soft,previous,*SOURCES.values()]}
    refs=json.loads(soft.read_text())['rows'];ids=sorted(r['video_id'] for r in refs if r['overall_human_uncertainty'] is not None)
    assert len(ids)==49 and len(set(ids))==49
    by={r['video_id']:r for r in refs};labels=[by[v]['uncertainty_bin'] for v in ids]
    y=np.array([[by[v][k+'_human_mean_model_scale'] for k in FIELDS] for v in ids])
    q=np.array([[by[v]['pooled_emotion_distribution'][e] for e in EMOTIONS] for v in ids])
    outer=folds(labels,5,SEED);fold_id=np.empty(49,dtype=int)
    for fold,test in enumerate(outer):fold_id[test]=fold
    bias_rows=[];scalar_rows=[];emotion_rows=[];ranking=[];stratified=[];oof_rows=[];plans={};all_data={};policy_metrics={}
    nested_predictions={};sensitivity=[];operational_predictions={}
    for model,path in SOURCES.items():
        records=[json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert len(records)==len({r['video_id'] for r in records})==50
        data={r['video_id']:r for r in records};assert set(ids)<=set(data)
        for r in records:
            VideoAnnotation.model_validate(r)
            if 'emotion_points' in r:validate_emotion_points({**r,'emotions':r['emotion_points']})
        x=np.array([[data[v][k] for k in FIELDS] for v in ids])
        p=np.array([[data[v]['emotions'][e] for e in EMOTIONS] for v in ids]);p/=p.sum(axis=1)[:,None]
        all_data[model]=data
        scalar_oof={m:np.empty_like(x) for m in ['raw','linear','isotonic','nested_policy']}
        emotion_oof={m:np.empty_like(p) for m in ['raw','offset','nested_policy']}
        selected={k:[] for k in FIELDS};selected['emotions']=[];fitted=[]
        for fold,test in enumerate(outer):
            train=np.setdiff1d(np.arange(49),test);train_labels=[labels[t] for t in train]
            for j,key in enumerate(FIELDS):
                method=choose_scalar(x[train,j],y[train,j],train_labels,j,SEED+fold*101)
                selected[key].append(method)
                for m in ['raw','linear','isotonic']:scalar_oof[m][test,j]=apply_scalar(x[test,j],fit_scalar(x[train,j],y[train,j],m),j)
                scalar_oof['nested_policy'][test,j]=scalar_oof[method][test,j]
                fitted.append({'outer_fold':fold,'field':key,'train_ids':[ids[t] for t in train],
                    'test_ids':[ids[t] for t in test],'chosen_method':method,
                    'parameters':fit_scalar(x[train,j],y[train,j],method)})
            method=choose_emotion(p[train],q[train],train_labels,SEED+fold*101)
            selected['emotions'].append(method)
            for m in ['raw','offset']:emotion_oof[m][test]=apply_emotion(p[test],fit_emotion(p[train],q[train],m))
            emotion_oof['nested_policy'][test]=emotion_oof[method][test]
            fitted.append({'outer_fold':fold,'field':'emotions','train_ids':[ids[t] for t in train],
                'test_ids':[ids[t] for t in test],'chosen_method':method,'parameters':fit_emotion(p[train],q[train],method)})
        for j,key in enumerate(FIELDS):
            bias_rows.append({'model':model,'field':key,'field_type':'scalar','n':49,
                'mean_prediction':float(np.mean(x[:,j])),'mean_soft_reference':float(np.mean(y[:,j])),**scalar_metrics(x[:,j],y[:,j])})
            for method,pred in scalar_oof.items():
                for label in ['overall','low','medium','high']:
                    mask=np.ones(49,dtype=bool) if label=='overall' else np.array(labels)==label
                    errors=np.array([np.mean(abs(pred[t,j]-y[t,j])) for t in outer])
                    raw_errors=np.array([np.mean(abs(x[t,j]-y[t,j])) for t in outer])
                    scalar_rows.append({'model':model,'field':key,'method':method,'uncertainty_bin':label,
                        'n':int(sum(mask)),**scalar_metrics(pred[mask,j],y[mask,j]),
                        'outer_fold_maes':errors.tolist(),'fold_mae_std':float(np.std(errors,ddof=1)),
                        'folds_better_than_raw':int(sum(errors<raw_errors-1e-12)),
                        'inner_selected_methods':selected[key] if method=='nested_policy' else None})
        distances=emotion_distances(p,q)
        for j,e in enumerate(EMOTIONS):bias_rows.append({'model':model,'field':e,'field_type':'emotion','n':49,
            'mean_prediction':float(np.mean(p[:,j])),'mean_soft_reference':float(np.mean(q[:,j])),
            'signed_bias':float(np.mean(p[:,j]-q[:,j])),'mean_tv':float(np.mean(distances[:,0])),'mean_jsd':float(np.mean(distances[:,1]))})
        for method,pred in emotion_oof.items():
            distances=emotion_distances(pred,q);raw_distances=emotion_distances(p,q)
            for label in ['overall','low','medium','high']:
                mask=np.ones(49,dtype=bool) if label=='overall' else np.array(labels)==label
                fold_tv=[float(np.mean(distances[t,0])) for t in outer]
                emotion_rows.append({'model':model,'method':method,'uncertainty_bin':label,'n':int(sum(mask)),
                    'mean_tv':float(np.mean(distances[mask,0])),'mean_jsd':float(np.mean(distances[mask,1])),
                    'outer_fold_tv':fold_tv,'fold_tv_std':float(np.std(fold_tv,ddof=1)),
                    'folds_better_than_raw':sum(np.mean(distances[t,0])<np.mean(raw_distances[t,0])-1e-12 for t in outer),
                    'inner_selected_methods':selected['emotions'] if method=='nested_policy' else None})
        deployment={};operational_x=x.copy();operational_p=p.copy()
        for j,key in enumerate(FIELDS):
            method=choose_scalar(x[:,j],y[:,j],labels,j,SEED+999)
            raw_error=np.mean(abs(x[:,j]-y[:,j]));pred=scalar_oof['nested_policy'][:,j]
            gain=raw_error-np.mean(abs(pred-y[:,j]));high=np.array(labels)=='high'
            wins=sum(np.mean(abs(pred[t]-y[t,j]))<np.mean(abs(x[t,j]-y[t,j]))-1e-12 for t in outer)
            stable=selected[key].count(method)>=4
            retain=method!='raw' and gain>=.01*RANGES[j] and gain>=.05*raw_error and wins>=4 and stable and np.mean(abs(pred[high]-y[high,j]))<=np.mean(abs(x[high,j]-y[high,j]))+.01*RANGES[j]
            chosen=method if retain else 'raw'
            deployment[key]={'method':chosen,'full_pilot_fit_parameters':fit_scalar(x[:,j],y[:,j],chosen),
                'inner_choices_outer_folds':selected[key],'full_pilot_inner_cv_choice':method,
                'nested_oof_mae_gain':float(gain),'outer_fold_wins':wins,'stable_same_method_4_of_5':stable}
            if retain:operational_x[:,j]=pred
        method=choose_emotion(p,q,labels,SEED+999);raw_d=emotion_distances(p,q);cal_d=emotion_distances(emotion_oof['nested_policy'],q)
        gain=np.mean(raw_d,axis=0)-np.mean(cal_d,axis=0);high=np.array(labels)=='high'
        wins=sum(np.mean(cal_d[t,0])<np.mean(raw_d[t,0])-1e-12 for t in outer)
        retain=method!='raw' and gain[0]>=.01 and gain[0]>=.05*np.mean(raw_d[:,0]) and gain[1]>0 and wins>=4 and selected['emotions'].count(method)>=4 and np.mean(cal_d[high,0])<=np.mean(raw_d[high,0])+.01
        deployment['emotions']={'method':method if retain else 'raw','full_pilot_fit_parameters':fit_emotion(p,q,method if retain else 'raw'),
            'inner_choices_outer_folds':selected['emotions'],'nested_oof_tv_gain':float(gain[0]),'nested_oof_jsd_gain':float(gain[1]),'outer_fold_wins':wins}
        if retain:operational_p=emotion_oof['nested_policy']
        plans[model]={'calibration':deployment,'outer_fitted_models':fitted}
        operational_predictions[model]=(operational_x.copy(),operational_p.copy(),x.copy(),p.copy())
        nested_predictions[model]=(scalar_oof['nested_policy'].copy(),emotion_oof['nested_policy'].copy())
        for seed in [SEED+1,SEED+2,SEED+3]:
            sx=np.empty_like(x);sp=np.empty_like(p);choices={k:[] for k in FIELDS}
            for fold,test in enumerate(folds(labels,5,seed)):
                train=np.setdiff1d(np.arange(49),test);train_labels=[labels[t] for t in train]
                for j,key in enumerate(FIELDS):
                    method=choose_scalar(x[train,j],y[train,j],train_labels,j,seed+fold*101)
                    choices[key].append(method)
                    sx[test,j]=apply_scalar(x[test,j],fit_scalar(x[train,j],y[train,j],method),j)
                method=choose_emotion(p[train],q[train],train_labels,seed+fold*101)
                sp[test]=apply_emotion(p[test],fit_emotion(p[train],q[train],method))
            sensitivity.append({'seed':seed,**profile(model,'nested_calibrated',sx,sp,y,q,labels),
                'scalar_method_choices':choices})
        for variant,sx,sp in [('raw',x,p),('nested_calibrated',scalar_oof['nested_policy'],emotion_oof['nested_policy']),('retained_policy_exploratory',operational_x,operational_p)]:
            ranking.append(profile(model,variant,sx,sp,y,q,labels))
            for label in ['low','medium','high']:
                mask=np.array(labels)==label
                stratified.append({'model':model,'variant':variant,'uncertainty_bin':label,'n':int(sum(mask)),
                    **{key+'_mae':float(np.mean(abs(sx[mask,j]-y[mask,j]))) for j,key in enumerate(FIELDS)},
                    'mean_tv':float(np.mean(emotion_distances(sp[mask],q[mask])[:,0])),
                    'mean_jsd':float(np.mean(emotion_distances(sp[mask],q[mask])[:,1]))})
        for n,vid in enumerate(ids):
            row={'video_id':vid,'model':model,'outer_fold':int(fold_id[n]),'uncertainty_bin':labels[n]}
            for j,key in enumerate(FIELDS):
                row[key+'_human']=float(y[n,j])
                for method,pred in scalar_oof.items():row[key+'_'+method]=float(pred[n,j])
            for method,pred in emotion_oof.items():row['emotions_'+method]=pred[n].tolist()
            oof_rows.append(row)
    # Additional conservative screen for the high-flexibility isotonic map.
    # This is post-OOF deployment screening, not a new unbiased test estimate.
    # Don't cherry-pick a different calibrator after seeing its outer errors.
    for model,plan in plans.items():
        for j,key in enumerate(FIELDS):
            rule=plan['calibration'][key]
            choices=rule['inner_choices_outer_folds']+[choice for r in sensitivity if r['model']==model for choice in r['scalar_method_choices'][key]]
            rule['all_seed_method_counts']=dict(Counter(choices))
            if rule['method']=='isotonic' and choices.count('isotonic')<.8*len(choices):
                rule['method']='raw';rule['full_pilot_fit_parameters']={'method':'raw'}
                rule['retention_note']='Isotonic selected in less than 80% of all 20 outer folds across four seeds; retain raw rather than freeze an unstable nonlinear map or cherry-pick a fallback.'
                operational_predictions[model][0][:,j]=operational_predictions[model][2][:,j]
        sx,sp,_,_=operational_predictions[model]
        updated=profile(model,'retained_policy_exploratory',sx,sp,y,q,labels)
        for index,r in enumerate(ranking):
            if r['model']==model and r['variant']=='retained_policy_exploratory':ranking[index]=updated
        for r in stratified:
            if r['model']==model and r['variant']=='retained_policy_exploratory':
                mask=np.array(labels)==r['uncertainty_bin']
                r.update({key+'_mae':float(np.mean(abs(sx[mask,j]-y[mask,j]))) for j,key in enumerate(FIELDS)})
    weights=add_ranking(ranking)
    for seed in [SEED+1,SEED+2,SEED+3]:
        add_ranking([r for r in sensitivity if r['seed']==seed])
    # Paired, stratified bootstrap of fixed OOF errors: descriptive sampling
    # intervals only, not uncertainty in refitting or model selection.
    paired_uncertainty=[];rng=np.random.default_rng(SEED+77)
    bin_indices=[np.where(np.array(labels)==label)[0] for label in ['low','medium','high']]
    per_video={}
    for m,(sx,sp) in nested_predictions.items():
        tv=emotion_distances(sp,q)[:,0]
        scalars=np.mean(abs(sx-y)/RANGES,axis=1)
        per_video[m]={'scalar_alignment':scalars,'emotion_tv':tv,'scalar_plus_tv_composite':(scalars*3+tv)/4}
    for a,b in [('Qwen','InternVL'),('Gemini','Qwen'),('Gemini','InternVL')]:
        for metric in per_video[a]:
            differences=per_video[a][metric]-per_video[b][metric]
            draws=[]
            for _ in range(2000):
                sample=np.concatenate([rng.choice(indices,size=len(indices),replace=True) for indices in bin_indices])
                draws.append(float(np.mean(differences[sample])))
            paired_uncertainty.append({'first_model':a,'second_model':b,'metric':metric,
                'signed_difference_first_minus_second':float(np.mean(differences)),
                'bootstrap_2p5_percentile':float(np.quantile(draws,.025)),
                'bootstrap_97p5_percentile':float(np.quantile(draws,.975)),
                'interpretation':'Fixed-OOF descriptive paired stratified bootstrap; excludes refitting/model-selection uncertainty'})
    raw_order=sorted([r for r in ranking if r['variant']=='raw'],key=lambda r:r['rank'])
    cal_order=sorted([r for r in ranking if r['variant']=='nested_calibrated'],key=lambda r:r['rank'])
    retained_order=sorted([r for r in ranking if r['variant']=='retained_policy_exploratory'],key=lambda r:r['rank'])
    pair=[r['model'] for r in retained_order[:2]]
    frozen={};freeze_gaps=[]
    for model in pair:
        records=all_data[model];first=records[ids[0]];meta=first['run_metadata']
        config_path=SOURCES[model].parent.parent/'configuration.json'
        config=json.loads(config_path.read_text()) if config_path.exists() else {}
        frozen[model]={'checkpoint':meta.get('model',first.get('model')),'checkpoint_revision':meta.get('revision'),
            'quantization':config.get('quantization','provider-managed; not recorded'),
            'quantization_skip_modules':config.get('quantization_skip_modules'),
            'prompt_version':meta.get('prompt_version'),'prompt_sha256':meta.get('prompt_sha256'),
            'frame_sampling':'uniform full-clip, target 1 FPS with cap' if model!='Gemini' else 'native uploaded video; provider sampling not logged',
            'fps':config.get('fps'),'max_frames':config.get('max_frames'),
            'max_pixels':config.get('max_pixels'),'video_size':config.get('video_size'),
            'vision_microbatch':config.get('vision_microbatch'),'evidence_usage':first.get('input_context'),
            'generation':{'do_sample':config.get('do_sample'),'temperature':config.get('temperature',0 if config.get('do_sample') is False else None),
                'max_new_tokens':config.get('max_new_tokens'),'batch_size':config.get('batch_size')},
            'calibration':plans[model]['calibration'],
            'calibration_application':{'scalar_bounds':{'valence':[-1,1],'arousal':[0,1],'recovery_suitability':[0,1]},
                'isotonic_interpolation':'linear between knots, endpoint clamping outside trained x range',
                'emotion_processing':'add offsets, clip each value to [0,1], renormalize; derive new dominant maximum set separately; retain raw scores'},
            'attention':config.get('attention','sdpa' if model!='Gemini' else None),
            'double_quantization':config.get('double_quantization'),
            'compute_dtype':config.get('compute_dtype'),'max_device_gib':config.get('max_device_gib'),
            'cap_pixels_per_frame':config.get('cap_pixels_per_frame'),'total_pixels':config.get('total_pixels'),
            'media_sha256_by_video':{v:records[v]['run_metadata'].get('media_sha256') for v in ids},
            'context_sha256_by_video':{v:records[v]['run_metadata'].get('context_sha256') for v in ids},
            'source_annotation_sha256':hashes[str(SOURCES[model].relative_to(BASE))]}
        if frozen[model]['checkpoint_revision'] is None:freeze_gaps.append(model+': immutable checkpoint/provider version not logged')
        if model=='Gemini':freeze_gaps.append('Gemini: provider video sampling and generation settings not recorded in historical annotations')
    selection={'analysis_scope':'49-video pilot; no full-dataset annotation started','raw_ranking':[r['model'] for r in raw_order],
        'nested_calibrated_ranking':[r['model'] for r in cal_order],'retained_policy_exploratory_ranking':[r['model'] for r in retained_order],
        'recommended_pair':pair,'calibration_plans':plans,'ranking_weights':weights,
        'ranking_interpretation':'Descriptive pilot recommendation, not an unbiased evaluation of model selection. Nested policy OOF is leakage-free; selecting final retention/ranking after seeing OOF remains exploratory.',
        'sources':hashes,'outer_folds':[{'fold':i,'test_video_ids':[ids[j] for j in t]} for i,t in enumerate(outer)],
        'seed':SEED,'cv':'5 outer folds / 4 inner folds; uncertainty-stratified shared folds',
        'deployment_status':'research candidate configuration; full-dataset run prohibited by task',
        'freeze_ready':not freeze_gaps,'freeze_gaps':freeze_gaps}
    selection['seed_sensitivity']=sensitivity
    selection['paired_oof_bootstrap']=paired_uncertainty
    selection['isotonic_stability_screen']='Retain only if selected in >=80% of all 20 outer folds across four seeds; otherwise raw. This conservative post-OOF screen is not a new independent performance estimate.'
    out.mkdir(parents=True)
    write_csv(out/'model_bias_analysis.csv',bias_rows)
    write_csv(out/'scalar_calibration_cv.csv',scalar_rows)
    write_csv(out/'emotion_calibration_cv.csv',emotion_rows)
    write_csv(out/'raw_vs_calibrated_ranking.csv',ranking)
    write_csv(out/'uncertainty_stratified_calibration.csv',stratified)
    write_csv(out/'calibration_oof_predictions.csv',oof_rows)
    write_csv(out/'calibration_seed_sensitivity.csv',sensitivity)
    write_csv(out/'paired_oof_error_uncertainty.csv',paired_uncertainty)
    (out/'selected_final_models.json').write_text(json.dumps(selection,indent=2,default=json_default),encoding='utf-8')
    (out/'frozen_annotation_config.json').write_text(json.dumps({'selected_models':frozen,'freeze_ready':not freeze_gaps,'unresolved_gaps':freeze_gaps},indent=2,default=json_default),encoding='utf-8')
    lines=['# Final pilot bias and calibration analysis','',
        '49 aligned valid pilot videos; all humans/models and previous reports remain unchanged. No full-dataset annotation is started. FV000131 is excluded because paired human labels are missing; FV000037 is not mapped. Soft human labels represent two perceptions, not objective ground truth.','',
        '## Evaluation protocol','',
        f'Shared outer 5-fold CV, seed {SEED}, stratified on the existing low/medium/high human-uncertainty bins (19/17/13). Each outer training set uses 4 inner folds to select a method without seeing outer targets. All models use the same folds. No in-sample fit performance is offered as evidence. Exact train/test IDs and per-fold fits are exported.','',
        'Scalar candidates: raw; ordinary least-squares slope/intercept; increasing isotonic regression using weighted PAVA, equal-x groups and linear interpolation between fitted knots. Predictions clip to original bounds. Emotion correction fixes every slope at 1, adds training-only mean human-minus-model offsets, clips to [0,1], and renormalizes. No temperature fitting or complex emotion calibrator is used.','',
        'Inner selection requires >=5% relative and >=0.01 full-range absolute MAE gain with >=3/4 inner-fold wins. Isotonic is eligible only with >=8 unique input levels in every inner-training set; near-equal results favor linear. Emotion correction requires TV improvement >=0.01 and >=5%, lower JSD, and >=3/4 fold wins. These conservative rules were set before running this analysis.','',
        'Retention for deployment additionally requires material nested OOF gain, >=4/5 outer-fold wins, same method in >=4/5 outer selections, and no high-bin deterioration exceeding 0.01 full range (TV for emotions). A conservative post-OOF sensitivity screen requires isotonic to recur in >=80% of the 20 outer folds across four seeds; otherwise keep raw rather than cherry-pick another method after seeing held-out errors. Full-pilot coefficients are exported only for application, not evaluated in-sample. Individual candidate method OOF results and the inner-selected nested policy are separate. The retained-policy row is post-OOF exploratory selection, not a new independent performance estimate.','',
        '## Raw scalar bias','', '| Model | Field | Signed bias | MAE | RMSE | Pearson | Spearman |','| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    def f(v):return 'undefined' if v is None else f'{v:.3f}'
    for r in bias_rows:
        if r['field_type']=='scalar':lines.append(f"| {r['model']} | {r['field']} | "+' | '.join(f(r[k]) for k in ['signed_bias','mae','rmse','pearson','spearman'])+' |')
    lines += ['', 'Signed bias is model minus pooled human: positive means overprediction, negative underprediction. Valence is [-1,1]; arousal/recovery [0,1]. Mean predictions, human means and all eight emotion biases are in model_bias_analysis.csv.','',
        '## Nested OOF scalar performance','', '| Model | Field | Raw MAE | Nested MAE | Raw bias | Nested bias | Fold wins | Selected outer methods | Retained deployment method |','| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |']
    for m in SOURCES:
        for key in FIELDS:
            a=next(r for r in scalar_rows if r['model']==m and r['field']==key and r['method']=='raw' and r['uncertainty_bin']=='overall')
            b=next(r for r in scalar_rows if r['model']==m and r['field']==key and r['method']=='nested_policy' and r['uncertainty_bin']=='overall')
            lines.append(f"| {m} | {key} | {a['mae']:.3f} | {b['mae']:.3f} | {a['signed_bias']:.3f} | {b['signed_bias']:.3f} | {b['folds_better_than_raw']}/5 | {b['inner_selected_methods']} | {plans[m]['calibration'][key]['method']} |")
    lines += ['', 'Candidate linear/isotonic OOF MAE, RMSE, Pearson, Spearman, signed bias and fold variability for every field/bin are in scalar_calibration_cv.csv. The nested policy can use raw in a fold. Method variability/low distinct-score counts are instability signals; isotonic is not forced.','',
        '## OOF emotion calibration','', '| Model | Method | TV | JSD | Fold wins |','| --- | --- | ---: | ---: | ---: |']
    for r in emotion_rows:
        if r['uncertainty_bin']=='overall':lines.append(f"| {r['model']} | {r['method']} | {r['mean_tv']:.3f} | {r['mean_jsd']:.3f} | {r['folds_better_than_raw']}/5 |")
    lines += ['', '## Ranking with individual criteria','',
        'Primary scalar alignment is the mean of valence MAE/2, arousal MAE, recovery MAE. Ranking averages metric ranks with weights 40% scalar alignment, 25% TV, 15% high-uncertainty scalar-plus-TV error, 10% absolute normalized bias, 10% worst scalar normalized MAE. This prespecified weighting is a descriptive decision aid, not a universal quality score. Individual field errors, JSD and correlations must be read alongside it. Runtime does not enter ranking.','',
        '| Variant | Rank | Model | Scalar alignment | TV | High-bin distance | Abs bias | Worst scalar | Weighted rank |','| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in sorted(ranking,key=lambda r:(r['variant'],r['rank'])):
        lines.append(f"| {r['variant']} | {r['rank']} | {r['model']} | "+' | '.join(f(r[k]) for k in ['scalar_alignment_mean','emotion_tv','high_uncertainty_composite','mean_absolute_scalar_bias','worst_scalar_normalized_mae','weighted_metric_rank'])+' |')
    lines += ['', '## Low / medium / high uncertainty','', '| Model | Variant | Bin | Valence MAE | Arousal MAE | Recovery MAE | TV | JSD |','| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for r in stratified:
        if r['variant']=='retained_policy_exploratory':continue
        lines.append(f"| {r['model']} | {r['variant']} | {r['uncertainty_bin']} | "+' | '.join(f(r[k]) for k in ['valence_mae','arousal_mae','recovery_suitability_mae','mean_tv','mean_jsd'])+' |')
    lines += ['', '## Recommended pair and freeze status','',
        'Raw ranking: '+' > '.join(selection['raw_ranking'])+'.',
        'Nested calibrated ranking: '+' > '.join(selection['nested_calibrated_ranking'])+'.',
        'Conservative retained-policy ranking (exploratory): '+' > '.join(selection['retained_policy_exploratory_ranking'])+'.',
        'Recommended research pair: '+', '.join(pair)+'.','']
    lines += ['## Fold sensitivity and ranking uncertainty','',
        'Three extra shared nested-CV split seeds were evaluated without choosing a favorable seed. The primary seed and rules stay fixed. See calibration_seed_sensitivity.csv.','',
        '| Seed | Nested ranking |','| --- | --- |']
    for seed in [SEED+1,SEED+2,SEED+3]:
        order=sorted([r for r in sensitivity if r['seed']==seed],key=lambda r:r['rank'])
        lines.append('| '+str(seed)+' | '+' > '.join(r['model'] for r in order)+' |')
    lines += ['', '| Comparison | Metric | Difference | Fixed-OOF bootstrap interval |','| --- | --- | ---: | --- |']
    for r in paired_uncertainty:
        if r['first_model']=='Qwen':lines.append(f"| Qwen - InternVL | {r['metric']} | {r['signed_difference_first_minus_second']:.3f} | [{r['bootstrap_2p5_percentile']:.3f}, {r['bootstrap_97p5_percentile']:.3f}] |")
    lines += ['', 'The bootstrap resamples matched video errors within uncertainty bins; it does not refit calibrators and is not an independent model-selection test. Intervals spanning zero and ranking changes across seeds weaken a decisive second-place claim. Qwen/InternVL tradeoffs should be carried into fresh validation rather than hidden by a weighted score.',
        'Qwen arousal selected isotonic in only 12/20 outer folds across the four seeds. Its primary-seed gain was material, but method choice is unstable; the proposed deployment therefore retains raw Qwen arousal. Linear remains a tested candidate, not a post-hoc substitute chosen to rescue the ranking.','']
    for m in SOURCES:lines.append('- '+m+': '+', '.join(k+'='+v['method'] for k,v in plans[m]['calibration'].items())+'.')
    lines += ['', '## Confirmed bias tendencies','']
    for model,key in [('Qwen','recovery_suitability'),('InternVL','arousal'),('Gemini','recovery_suitability'),('Gemini','calm_contentment')]:
        r=next(r for r in bias_rows if r['model']==model and r['field']==key)
        lines.append(f"- {model} {key}: signed bias {r['signed_bias']:+.3f}; "+('overpredicts' if r['signed_bias']>0 else 'underpredicts')+' relative to this pooled reference, not objective truth.')
    lines += ['', 'Full-pilot parameters, clipping/renormalization behavior, prompts, evidence usage and known sampling/generation settings are in frozen_annotation_config.json. Calibration is downstream postprocessing; original evidence and labels remain unchanged. Distribution-derived dominant labels must be recomputed downstream if a distribution correction is applied; retain the original declared label alongside it.','',
        'Freeze gaps: '+'; '.join(freeze_gaps)+'.',
        'The analysis/configuration can be versioned, but the pipeline is not yet an immutable production freeze. Re-running or scaling Gemini may require matching its historical provider configuration. Cached HF commit names alone do not prove which unlogged revision produced the saved annotations.','',
        '## Limitations','',
        'Model/prompt/native-modality differences remain confounded. The same pilot informs recommendations; there is no independent post-selection holdout. Nested CV protects per-video calibrator evaluation but cannot make selection among models/policies on this pilot unbiased. OOF fold variation is not a statistical confidence interval. With 49 videos, isotonic step maps and final coefficients may be unstable under new content; do not extrapolate to 4,000 videos without a fresh validation check. Distribution correction improves distance to a two-human mixture, not truth.','',
        'All outputs are new files under this analysis directory. Reproduce with `.venv-qwen-cuda/Scripts/python.exe src/analyze_model_calibration.py --output-dir <new-directory>`. No network inference or full-dataset annotation occurs.','']
    lines += ['## Concise conclusion','',
        '1. Biases confirmed numerically: Qwen low recovery, InternVL high arousal, and Gemini mildly higher recovery/calm relative to the soft reference. All three overpredict mean valence.',
        '2. Nested out-of-fold calibration gives material gains, not merely in-sample improvements. Gemini arousal remains raw; retained corrections and all candidate metrics are detailed above.',
        '3. Nominal research pair under the stated criteria: '+', '.join(pair)+'. Calibrated second-place separation must be interpreted with fold sensitivity and paired intervals; it is not definitive model superiority.',
        '4. Preserve raw outputs and store calibrated values separately for the retained fields/distributions. Do not replace original annotations or interpret recalibrated confidence as calibrated probability of correctness.',
        '5. Freeze the analysis and candidate calibration specification now; production freeze remains incomplete because of the logged provenance gaps and the need for fresh validation before scaling. No full-dataset annotation has started.','']
    (out/'final_calibration_report.md').write_text('\n'.join(lines),encoding='utf-8')
    assert all(hashlib.sha256((BASE/path).read_bytes()).hexdigest()==digest for path,digest in hashes.items())
    print(json.dumps({'raw':selection['raw_ranking'],'nested':selection['nested_calibrated_ranking'],
        'retained':selection['retained_policy_exploratory_ranking'],'pair':pair,
        'methods':{m:{k:v['method'] for k,v in p['calibration'].items()} for m,p in plans.items()},'freeze_gaps':freeze_gaps},indent=2))


if __name__=='__main__':main()
