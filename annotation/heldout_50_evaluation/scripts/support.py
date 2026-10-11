"""Local frozen-file and checkpoint validation, shared by held-out tools."""
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
os.environ['ATARAXIA_PILOT_DIR']=str(ROOT)
os.environ['ATARAXIA_OUTPUT_ROOT']=str(ROOT/'predictions')
sys.path.insert(0,str(ROOT/'components'))


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def append(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(value,ensure_ascii=False)+'\n')


def validate_freeze():
    frozen=read(ROOT/'config/freeze_manifest.json')
    for rel,h in frozen['files'].items():
        p=(ROOT/rel).resolve()
        if ROOT not in p.parents or not p.is_file() or sha(p)!=h:raise ValueError(f'Frozen input changed/missing: {rel}')
    cfg=read(ROOT/'config/frozen_config.json')
    ids=cfg['heldout_ids']
    if len(ids)!=50 or len(set(ids))!=50 or set(ids)&set(cfg['original_pilot_ids']):raise ValueError('Invalid held-out isolation')
    return cfg


def prediction_path(model):
    return ROOT/'predictions'/model/('annotations.jsonl' if model=='gemini' else 'pilot/annotations.jsonl')


def predictions(model,cfg,repair_tail=False):
    from common_annotation import VideoAnnotation, validate_emotion_points, build_prompt
    path=prediction_path(model)
    if not path.exists():return {}
    lines=path.read_text(encoding='utf-8').splitlines();records={}
    for index,line in enumerate(lines):
        if not line.strip():continue
        try:r=json.loads(line)
        except json.JSONDecodeError:
            if repair_tail and index==len(lines)-1:
                append(ROOT/'logs/recovered_partial_lines.jsonl',{'model':model,'line':line})
                path.write_text('\n'.join(lines[:index])+'\n',encoding='utf-8');break
            raise
        VideoAnnotation.model_validate(r)
        if 'emotion_points' in r:validate_emotion_points({**r,'emotions':r['emotion_points']})
        vid=r['video_id']
        if vid not in cfg['heldout_ids'] or vid in records:raise ValueError('Duplicate or unexpected prediction ID')
        meta=r['run_metadata'];expected=cfg['models'][model]
        if r['model']!=expected['checkpoint']:raise ValueError('Wrong model checkpoint')
        if model!='gemini' and meta.get('revision')!=expected['revision']:raise ValueError('Wrong checkpoint revision')
        if meta.get('media_sha256')!=sha(ROOT/'videos'/f'{vid}.mp4'):raise ValueError('Prediction media mismatch')
        prompt,context=build_prompt(vid,model=='gemini',emotion_scale='probabilities' if model=='gemini' else 'points10')
        context_hash=hashlib.sha256(json.dumps(context,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if meta.get('context_sha256')!=context_hash or meta.get('prompt_sha256')!=hashlib.sha256(prompt.encode()).hexdigest():raise ValueError('Prediction evidence/prompt mismatch')
        records[vid]=r
    return records
