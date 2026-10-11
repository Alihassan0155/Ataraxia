"""Initialize an isolated held-out study from verified existing local assets."""
import csv
import hashlib
import importlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parent


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def put(path,value):
    text=json.dumps(value,ensure_ascii=False,indent=2)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8-sig'))!=value:raise ValueError(f'Frozen file changed: {path}')
    else:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')


def copy(source,target,transform=None):
    target.parent.mkdir(parents=True,exist_ok=True)
    if transform:
        data=transform(source.read_text(encoding='utf-8-sig')).encode('utf-8')
        if target.exists() and target.read_bytes()!=data:raise ValueError(f'Snapshot changed: {target}')
        if not target.exists():target.write_bytes(data)
    else:
        if target.exists():
            if digest(source)!=digest(target):raise ValueError(f'Snapshot changed: {target}')
        else:shutil.copy2(source,target)


def main():
    manifest=ROOT/'config/freeze_manifest.json'
    if manifest.exists():
        sys.path.insert(0,str(ROOT/'scripts'))
        from support import validate_freeze
        validate_freeze();print('Existing freeze verified; human inputs/predictions are preserved.');return
    selected=PROJECT/'held out/merged_50'
    with (selected/'held_out_50.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    ids=[r['video_id'] for r in rows]
    with (PROJECT/'pilot_50_reels_30h/pilot_metadata.csv').open(encoding='utf-8-sig',newline='') as f:pilot=[r['assigned_id'] for r in csv.DictReader(f)]
    if len(ids)!=50 or len(set(ids))!=50 or set(ids)&set(pilot):raise ValueError('Expected exactly 50 distinct IDs with zero pilot overlap')
    copies={r['video_id']:r for r in json.loads((selected/'video_copy_manifest.json').read_text(encoding='utf-8'))['files']}
    # Original pilot hashes are already logged in the original native-video run.
    pilot_prediction=PROJECT/'outputs/reels_30h/gemini/annotations.jsonl'
    original=[json.loads(l) for l in pilot_prediction.read_text(encoding='utf-8').splitlines() if l.strip()]
    # Gemini did not log media hashes consistently; CUDA predictions did.
    qwen_original=PROJECT/'pilot_50_reels_30h/results/pilot50_qwen_nf4_max32_limit15p8_v5/qwen/pilot/annotations.jsonl'
    original_qwen=[json.loads(l) for l in qwen_original.read_text(encoding='utf-8').splitlines() if l.strip()]
    pilot_hashes={r['run_metadata']['media_sha256'] for r in original_qwen}
    assets=[]
    for row in rows:
        vid=row['video_id'];source=PROJECT/copies[vid]['heldout_video_path']
        h=digest(source)
        if h!=copies[vid]['sha256'] or h in pilot_hashes:raise ValueError(f'Media mismatch or pilot-byte overlap: {vid}')
        context=PROJECT/'data/normalized/preprocessed_merged_v2/context'/f'{vid}.json'
        ctx=json.loads(context.read_text(encoding='utf-8'))
        if ctx.get('video_id')!=vid:raise ValueError(f'Context ID mismatch: {vid}')
        if not all(k in ctx for k in ['transcript','acoustic_features','metadata_caption']):raise ValueError(f'Incomplete evidence: {vid}')
        copy(source,ROOT/'videos'/f'{vid}.mp4');copy(context,ROOT/'context'/f'{vid}.json')
        row['assigned_id']=vid;row['pilot_video_path']=f'videos/{vid}.mp4'
        row['duration']=row['duration_seconds']
        assets.append({'video_id':vid,'media_sha256':h,'context_file_sha256':digest(context),'source_video':str(source),'source_context':str(context),'category':row['category']})
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with (ROOT/'pilot_metadata.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)
    copy(selected/'held_out_50.csv',ROOT/'selection/held_out_50.csv')
    copy(selected/'selection_summary.json',ROOT/'selection/selection_summary.json')
    copy(PROJECT/'annotation_rules.txt',ROOT/'human_annotations/annotation_rules.txt')
    codefiles=['prompts.py','common_annotation.py','annotate_qwen_cuda.py','annotate_internvl_cuda.py','annotate_gemini.py',
               'build_human_fieldwise_consensus.py','build_human_soft_reference.py','build_three_human_reference.py',
               'compare_pilot_models.py','analyze_model_calibration.py']
    provenance=[]
    for name in codefiles:
        def adapt(text):
            if name in ['annotate_qwen_cuda.py','annotate_internvl_cuda.py']:
                text=text.replace('BASE / "data/pilot_50_reels_30h/pilot_50_reels_30h/videos"','BASE / "videos"')
                text=text.replace('BASE / "pilot_50_reels_30h/pilot_metadata.csv"','BASE / "pilot_metadata.csv"')
                text=text.replace('revision = getattr(model.config, "_commit_hash", None)', 'revision = getattr(model.config, "_commit_hash", None) or args.revision')
            if name=='annotate_gemini.py':
                text=text.replace('            annotation = finalize_annotation(', '            if raw.get("video_id") != video_id:\n                raise ValueError("Gemini returned mismatched video ID")\n\n            from pathlib import Path\n            import json\n            raw_path = OUTPUT_ROOT / "gemini" / "raw_responses.jsonl"\n            raw_path.parent.mkdir(parents=True, exist_ok=True)\n            with raw_path.open("a", encoding="utf-8") as handle:\n                handle.write(json.dumps({"video_id": video_id, "text": response.output_text, "provider_response": response.model_dump(mode="json")}, ensure_ascii=False) + "\\n")\n\n            annotation = finalize_annotation(')
            if name=='build_human_fieldwise_consensus.py':
                text=text.replace('r"FV\\d{6}"','r"(?:FV\\d{6}|YT_[A-Za-z0-9_-]+|TT_\\d+)"')
            return text
        source=PROJECT/'src'/name;target=ROOT/'components'/name
        copy(source,target,adapt)
        provenance.append({'file':name,'original_sha256':digest(source),'snapshot_sha256':digest(target),'adaptation':'CUDA input paths redirected; pinned requested revision logged when HF omits commit hash; human YT/TT grammar enabled; Gemini adds strict ID check and raw/full response logging. Inference/preprocessing otherwise preserved.'})
    for directory in ['predictions/qwen','predictions/internvl','predictions/gemini','reports','logs','checkpoints','calibrated']:(ROOT/directory).mkdir(parents=True,exist_ok=True)
    humanfields=['video_id','valence','arousal','recovery_suitability','joy','sadness','anger','fear_anxiety','surprise','disgust','calm_contentment','neutral','dominant_emotion','confidence','notes']
    for name in ['ghayas','zara','ali']:
        path=ROOT/'human_annotations'/name/'annotations.csv';path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            with path.open('w',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=humanfields);w.writeheader();w.writerows({'video_id':vid} for vid in ids)
        with (path.parent/'video_list.csv').open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['video_id','video_path']);w.writeheader();w.writerows({'video_id':vid,'video_path':f'../../videos/{vid}.mp4'} for vid in ids)
    selection=PROJECT/'pilot_50_reels_30h/results/three_human_evaluation/calibration_final/selected_final_models.json'
    copy(selection,ROOT/'config/pilot_calibration_and_selection.json')
    reference=PROJECT/'pilot_50_reels_30h/results/three_human_evaluation/reference/human_uncertainty_summary.json'
    uncertainty=json.loads(reference.read_text(encoding='utf-8'))
    models={};gaps=[]
    configs={'qwen':qwen_original.parent.parent/'configuration.json',
             'internvl':PROJECT/'pilot_50_reels_30h/results/pilot50_cuda_nf4_qwen32_intern16_limit15p8_v5/internvl/configuration.json'}
    for name,path in configs.items():
        cfg=json.loads(path.read_text(encoding='utf-8'))
        checkpoint=cfg['model'];ref=PROJECT/'.cache/huggingface/hub'/('models--'+checkpoint.replace('/','--'))/'refs/main'
        revision=ref.read_text().strip() if ref.exists() else None
        if revision is None or not re.fullmatch('[0-9a-f]{40}',revision):raise ValueError(f'No immutable cached revision for {name}; freeze must be resolved before inference')
        models[name]={'checkpoint':checkpoint,'revision':revision,'revision_source':'current local cache refs/main; not proof of historical pilot revision','pilot_configuration':cfg,'prompt_version':'v1.1-points10','native_raw_audio':False}
        gaps.append(name+': historical pilot immutable revision was not logged; prospective held-out revision is pinned to the current cache')
    gemini=original[0]
    models['gemini']={'checkpoint':gemini['model'],'immutable_provider_revision':None,'generation_settings':None,'provider_sampling':None,
                      'request_api':'google.genai.Client.interactions.create','processing':'static','response_format':'application/json with VideoAnnotation schema',
                      'prompt_version':gemini['run_metadata']['prompt_version'],'native_raw_audio':True,
                      'defaults_policy':'Reuse existing SDK call without inventing temperature/token/FPS defaults; record full response and package versions for each request'}
    gaps+=['Gemini: historical provider revision and video sampling/generation defaults unlogged; matching the historical deployment cannot be proven',
           'Shared context does not mean identical direct modality access: Gemini hears raw audio, CUDA models do not',
           'No ID or exact-byte overlap; creator/repost/near-duplicate leakage is not certified by byte hashing']
    cfg={'schema':'heldout-frozen-v1','expected_n':50,'original_pilot_ids':pilot,'heldout_ids':ids,'models':models,
         'calibration_source_sha256':digest(selection),'calibration_policy':'Only retained pilot full_pilot_fit_parameters; no fitting, selection or tuning on held-out labels',
         'uncertainty_cutpoints':uncertainty['tertile_cutpoints'],'uncertainty_formula':uncertainty['uncertainty_formula'],
         'ranking_weights':json.loads(selection.read_text(encoding='utf-8'))['ranking_weights'],
         'evaluation_metrics':['MAE','RMSE','Pearson','Spearman','emotion TV','emotion JSD bits','dominant agreement per human and pooled/tie-aware'],
         'bootstrap':{'resamples':5000,'seed':20261009,'confidence':.95,'method':'paired video-level percentile; identical sampled IDs for model/variant differences; fixed frozen calibration; no refitting','undefined_correlations':'omit degenerate bootstrap draws and report valid draw count'},
         'gaps':gaps,'scope':'prospective held-out validation; no full-dataset annotation','source_code':provenance,'assets':assets}
    put(ROOT/'config/frozen_config.json',cfg)
    # Freeze complete instantiated prompts as well as the shared prompt source.
    import os
    os.environ['ATARAXIA_PILOT_DIR']=str(ROOT);os.environ['ATARAXIA_OUTPUT_ROOT']=str(ROOT/'predictions')
    sys.path.insert(0,str(ROOT/'components'))
    common=importlib.import_module('common_annotation')
    for model in models:
        for vid in ids:
            prompt,_=common.build_prompt(vid,model=='gemini',emotion_scale='probabilities' if model=='gemini' else 'points10')
            path=ROOT/'prompts'/model/(vid+'.txt');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(prompt,encoding='utf-8')
    frozenfiles=[ROOT/'pilot_metadata.csv',ROOT/'config/frozen_config.json',ROOT/'config/pilot_calibration_and_selection.json',
                 *list((ROOT/'scripts').glob('*.py')),*list(ROOT.glob('*.ps1')),*list(ROOT.glob('requirements*.txt')),
                 *list((ROOT/'components').glob('*.py')),*list((ROOT/'context').glob('*.json')),*list((ROOT/'prompts').rglob('*.txt')),*list((ROOT/'videos').glob('*.mp4'))]
    put(manifest,{'files':{p.relative_to(ROOT).as_posix():digest(p) for p in frozenfiles},'original_inputs_unchanged':True})
    put(ROOT/'checkpoints/preparation.json',{'expected':50,'unique_ids':50,'pilot_id_overlap':0,'pilot_byte_overlap':0,'evidence_bundles':50,'status':'prepared_human_labels_pending','configuration_gaps':gaps})
    print('Prepared 50 unique held-out videos; zero ID/byte overlap; 50 contexts; separate blank human templates. No inference/evaluation performed.')


if __name__=='__main__':main()
