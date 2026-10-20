"""Approved local category-only inference; no database connection or semantic writer."""
from collections import Counter
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import time

from .category_completion import ROOT,MODEL,REVISION,contract
from .category_discovery import validate_candidate

def accept(request,result,taxonomy,approved_ids):
    return validate_candidate(request,result,taxonomy)
from .artifacts import fingerprint
from .__main__ import atomic_json


def utc():return datetime.now(timezone.utc).isoformat()


def filler_only(sources):
    """Conservative abstention for sources containing only generic utterances.

    This is not a category classifier. Any other words defer to Qwen; metadata
    cannot make non-informative content sufficient.
    """
    import re
    words=re.findall(r'[^\W\d_]+',' '.join(v for v in sources.values() if v).casefold())
    generic=set('hello hi hey heyo ha haha hahaha hee he mmm mm hmm mhm huh oh o ah uh um '
                'no yes yeah yep you i me my we it this that here there go do let s thank thanks '
                'for watching bye good god goodness whoa what really boop meep hup shit'.split())
    return not words or all(w in generic for w in words)


def load_inputs(prepared):
    prepared=Path(prepared)
    frozen_contract=json.loads((prepared/'contract.json').read_text(encoding='utf-8'))
    rows=[json.loads(line) for line in (prepared/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
    requests=[r for r in rows if r['disposition']=='awaiting_qwen_approval']
    if len(requests)!=172 or len({r['video_id'] for r in requests})!=172:
        raise ValueError('Expected the approved 172 unique evidence-bearing requests')
    taxonomy=json.loads((ROOT/'annotation/semantic_pipeline/configs/taxonomy_category_ids_v1.json').read_text())
    allowed,schema=contract(taxonomy)
    if (frozen_contract['allowed_categories']!=allowed or frozen_contract['output_schema']!=schema or
            frozen_contract['model']!=MODEL or frozen_contract['revision']!=REVISION):
        raise ValueError('Prepared model or category contract changed')
    for r in requests:
        payload={k:r[k] for k in ('video_id','sources','metadata','transcript_budget')}
        if fingerprint(payload)!=r['input_hash'] or not any(r['sources'].values()):
            raise ValueError('Prepared input hash/content mismatch')
        if r['model']!=MODEL or r['revision']!=REVISION or r['database_exists']:
            raise ValueError('Unexpected request model/scope')
    return requests,taxonomy,frozen_contract


def summarize(out,requests,run_id):
    results=[]
    for request in requests:
        p=out/'videos'/request['video_id']/'result.json'
        if p.exists():
            r=json.loads(p.read_text(encoding='utf-8'))
            if r['run_id']!=run_id or r['input_hash']!=request['input_hash']:
                raise ValueError('Checkpoint identity mismatch')
            results.append(r)
    valid=[r for r in results if r['execution_status']=='completed']
    report={'at':utc(),'approved_total':len(requests),'total_processed':len(results),
            'successfully_classified':sum(r['effective_category']!='unknown' for r in valid),
            'unknown_abstained':sum(r['effective_category']=='unknown' for r in valid),
            'failed':sum(r['execution_status']=='failed' for r in results),
            'invalid_classifications':sum(r['execution_status']=='invalid' for r in results),
            'unsupported_proposals_abstained':sum(bool(r.get('rejected_category_proposal')) for r in results),
            'remaining':len(requests)-len(results),'category_distribution':dict(Counter(r['effective_category'] for r in valid)),
            'database_writes':0,'extra_videos_processed':0,'run_id':run_id,'output_directory':str(out.resolve())}
    atomic_json(out/'report.json',report)
    # JSONL is a derived index; per-video atomic records are authoritative.
    (out/'results.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in results),encoding='utf-8')
    return report


def run(prepared,out):
    import os
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    from ataraxia.distributed.common import lock
    from ataraxia.semantic.models import Extractor,release
    from ataraxia.semantic.normalization import parse_practical
    requests,taxonomy,definition=load_inputs(prepared)
    prior=ROOT/'backend/reports/category_completion_run_20261017_r3/reviewed/results.jsonl'
    prior_rows=[json.loads(line) for line in prior.read_text(encoding='utf-8').splitlines()]
    retained={r['video_id'] for r in prior_rows if r.get('execution_status')=='completed' and r.get('effective_category') not in (None,'unknown')}
    requests=[r for r in requests if r['video_id'] not in retained]
    if len(requests)!=118:raise ValueError('Expected 118 unresolved videos')
    from .category_discovery import discovery_contract as proposal_contract
    definition={**definition,**proposal_contract()}
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    configuration=json.loads((ROOT/'annotation/semantic_pipeline/configs/pipeline_v13.json').read_text())['extractor']
    configuration={**configuration,'max_new_tokens':definition['max_new_tokens'],
                   'max_input_tokens':definition['max_input_tokens'],'batch_size':1}
    versions={p:importlib.metadata.version(p) for p in ('torch','transformers','bitsandbytes','numpy')}
    identity={'requests':requests,'contract':definition,'taxonomy':taxonomy,'configuration':configuration,
              'versions':versions,'runner_sha256':__import__('hashlib').sha256(Path(__file__).read_bytes()).hexdigest(),
              'policy_sources':{name:__import__('hashlib').sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('category_discovery.py','propose_categories.py')}}
    run_id=fingerprint(identity)
    manifest=out/'run.json'
    if manifest.exists():
        if json.loads(manifest.read_text(encoding='utf-8'))['run_id']!=run_id:
            raise ValueError('Frozen run changed; do not overwrite checkpoints')
    else:atomic_json(manifest,{'run_id':run_id,'created_at':utc(),'identity':identity})
    smoke_ids=[r['video_id'] for r in requests[:5]]
    model=None
    with lock(out/'worker.lock'):
        with lock(Path('C:/ProgramData/AtaraxiaWorker/gpu0.lock')):
            try:
                print(json.dumps({'event':'loading_category_only_model','model':MODEL,'revision':REVISION}),flush=True)
                model=Extractor(configuration,ROOT/'annotation/.cache/semantic_models')
                for index,request in enumerate(requests):
                    if index==5:
                        smoke=[json.loads((out/'videos'/vid/'result.json').read_text(encoding='utf-8')) for vid in smoke_ids]
                        passed=all(r['execution_status']=='completed' for r in smoke)
                        atomic_json(out/'smoke_report.json',{'video_ids':smoke_ids,'passed':passed,
                                    'valid_outputs':sum(r['execution_status']=='completed' for r in smoke),
                                    'run_id':run_id,'at':utc()})
                        if not passed:
                            print(json.dumps({'event':'smoke_failed_stopping_before_remaining'}),flush=True)
                            break
                        approval=out/'smoke_approval.json'
                        if not approval.exists() or json.loads(approval.read_text(encoding='utf-8'))!={
                                'run_id':run_id,'video_ids':smoke_ids,'evidence_review_passed':True}:
                            print(json.dumps({'event':'smoke_schema_passed_awaiting_evidence_review','valid_outputs':5}),flush=True)
                            break
                        print(json.dumps({'event':'smoke_passed','valid_outputs':5,'continuing':len(requests)-5}),flush=True)
                    folder=out/'videos'/request['video_id'];folder.mkdir(parents=True,exist_ok=True)
                    checkpoint=folder/'result.json'
                    if checkpoint.exists():
                        previous=json.loads(checkpoint.read_text(encoding='utf-8'))
                        if previous['run_id']!=run_id:raise ValueError('Checkpoint identity mismatch')
                        continue
                    start=time.monotonic()
                    base={'video_id':request['video_id'],'input_hash':request['input_hash'],'run_id':run_id,
                          'model':MODEL,'revision':REVISION,'started_at':utc(),'database_sync_allowed':False}
                    try:
                        payload={k:request[k] for k in ('video_id','sources','metadata','transcript_budget')}
                        caution=('\nEVIDENCE GATE: Classify only when the supplied content sources support the category '
                                 'INDEPENDENTLY of title/caption. Metadata is unverified; never use it to fill missing '
                                 'visuals, actions or subject matter. Greetings, laughter, filler, isolated exclamations '
                                 'or generic conversational words cannot establish a topic: abstain. '
                                 'Read the WHOLE content for context, satire or conflicting signals, not a convenient '
                                 'isolated sentence. If multiple interpretations remain plausible and no category is '
                                 'supported conservatively, abstain. A copied quote must actually support the selected '
                                 'category, not merely exist in the transcript. Output a null category rather than guessing. '
                                 'Use at most ONE evidence quote: copy ONE contiguous substring of 10 to 60 characters EXACTLY, including punctuation and spelling. Never join separate sentences or correct transcription errors. '
                                 'Never quote a whole paragraph.\n')
                        if filler_only(request['sources']):
                            caution+='\nThese content sources contain only generic filler/utterances. Return exactly {"category":null,"description":"","existing_fit":"Insufficient content evidence","evidence":[]}.\n'
                        messages=[{'role':'system','content':definition['prompt']+caution+'\nExisting category references (non-exhaustive; no preference):\n'+
                                   json.dumps(definition['allowed_categories'],ensure_ascii=False)+'\nOutput schema:\n'+
                                   json.dumps(definition['output_schema'],ensure_ascii=False)},
                                  {'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
                        text=model.tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
                        tokens=len(model.tokenizer.encode(text))
                        if tokens>configuration['max_input_tokens']:raise ValueError('Input exceeds frozen budget; no silent truncation')
                        raw=model.generate([text])[0]
                        (folder/'response.txt').write_text(raw,encoding='utf-8')
                        try:
                            parsed=parse_practical(raw)
                            rejected=None
                            if filler_only(request['sources']) and parsed.get('category') is not None:
                                # Preserve the unaccepted proposal and enforce abstention;
                                # never turn a guessed category into an accepted label.
                                rejected=parsed
                                parsed={'category':None,'description':'','existing_fit':'Insufficient content evidence','evidence':[]}
                            try:
                                result=accept(request,parsed,taxonomy,set())
                            except ValueError as exc:
                                # Invalid evidence never becomes an accepted proposal.
                                rejected={'output':parsed,'validation_error':str(exc)}
                                parsed={'category':None,'description':'','existing_fit':'Insufficient content evidence','evidence':[]}
                                result=accept(request,parsed,taxonomy,set())
                            result={**base,**result,'execution_status':'completed','raw_response':parsed,
                                    'confidence':None,'confidence_note':'Not requested or calibrated',
                                    'input_tokens':tokens,'completed_at':utc()}
                            if rejected:
                                result['rejected_category_proposal']=rejected
                                result['abstention_reason']='unsupported_or_invalid_content_evidence'
                        except Exception as exc:
                            result={**base,'execution_status':'invalid','error_type':type(exc).__name__,
                                    'error':str(exc)[:500],'completed_at':utc()}
                    except Exception as exc:
                        result={**base,'execution_status':'failed','error_type':type(exc).__name__,
                                'error':str(exc)[:500],'completed_at':utc()}
                    result['elapsed_seconds']=round(time.monotonic()-start,3)
                    atomic_json(checkpoint,result)
                    print(json.dumps({'event':'category_result','processed':index+1,'video_id':request['video_id'],
                                      'status':result['execution_status'],'category':result.get('effective_category'),
                                      'seconds':result['elapsed_seconds']}),flush=True)
                    summarize(out,requests,run_id)
            finally:
                if model is not None:release(model)
    report=summarize(out,requests,run_id)
    print(json.dumps(report,indent=2),flush=True)
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared',type=Path,default=ROOT/'backend/reports/category_completion_20261017')
    parser.add_argument('--out',type=Path,default=ROOT/'backend/reports/category_discovery_inference_20261018')
    parser.add_argument('--approved-inference',action='store_true',help='Use only after explicit user approval of new discovery inference')
    args=parser.parse_args()
    parser.error('Inference requires explicit approval; use --approved-inference only after user authorization') if not args.approved_inference else run(args.prepared,args.out)
