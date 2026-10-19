"""Original full-run Gemini resume and checkpointed Qwen → BGE-M3 delivery."""
import argparse,csv,hashlib,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
ANNOTATION=ROOT/'annotation'
def run_ids(target):
    if target=='gemini':
        source=ANNOTATION/'runs/gemini_full_remaining_20261012'
        config=json.loads((source/'configuration.json').read_text())
        ids=config['selected_ids']
        manifest=Path(config['manifest'])
        if hashlib.sha256(manifest.read_bytes()).hexdigest()!=config['manifest_sha256']:
            raise ValueError('Original Gemini manifest changed')
    else:
        path=ANNOTATION/'semantic_pipeline/runs/semantic_full_v12/definitions/metadata_csv'
        with path.open(encoding='utf-8-sig',newline='') as f:
            ids=[r.get('assigned_id') or r.get('video_id') for r in csv.DictReader(f)]
    if not ids or len(set(ids))!=len(ids) or not all(ids):raise ValueError('Invalid run selection')
    return set(ids)

def validated_ids(paths,allowed,validator):
    done=set()
    for path in paths:
        if not path.exists():continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            try:
                row=json.loads(line);vid=row['video_id']
                if vid in allowed:validator(row);done.add(vid)
            except (ValueError,KeyError,TypeError):continue
    return done

def embedding_jobs(worker,rows,allowed):
    pending,completed,failures,invalid=worker.queue({k:v for k,v in rows.items() if k in allowed})
    jobs=[];waiting=[]
    for job in pending:
        try:
            if worker.recover_metadata(job) is not None:jobs.append(job)
            else:waiting.append(job['video_id'])
        except Exception as e:invalid.append({'video_id':job['video_id'],'error_type':type(e).__name__})
    return jobs,completed,failures,invalid,waiting

def process_semantic_batch(worker,batch,write,utc):
    """Reuse the frozen worker's staged extraction/embedding and retry state."""
    missing=[]
    for job in batch:
        state=worker.state(job)
        attempts=state['attempts'] if state.get('status') in ('processing','metadata_ready') else state['attempts']+1
        state.update(status='processing',attempts=attempts,started_at=utc())
        write(worker.state_path(job),state)
        try:
            if worker.recover_metadata(job) is None:missing.append(job)
        except Exception as exc:
            worker.failed(job,'cached_metadata',exc)
    width=worker.cfg['extractor']['batch_size']
    for offset in range(0,len(missing),width):
        if worker.interrupted():break
        worker.extract(missing[offset:offset+width])
    if not worker.interrupted():worker.embed(batch)

def gemini(allowed,once):
    from ataraxia.runtime.config import Settings
    from ataraxia.distributed.common import lock
    source=ANNOTATION/'runs/gemini_full_remaining_20261012'
    target=source
    env=Settings.load(ANNOTATION).child_environment()
    env.update(ATARAXIA_PILOT_DIR=str(source/'evidence'),ATARAXIA_METADATA_PATH=str(source/'metadata.csv'),ATARAXIA_OUTPUT_ROOT=str(target/'predictions'),ATARAXIA_GEMINI_ALL_KEYS_BEFORE_STOP='1',ATARAXIA_EXPECTED_VIDEO_COUNT=str(len(allowed)))
    os.environ.update(env)
    from ataraxia.annotation.common import VideoAnnotation,save_annotation
    from ataraxia.annotation.backends import gemini as api
    from ataraxia.annotation.backends.gemini_execution import rotating_video
    from ataraxia.semantic.storage import write
    config=json.loads((source/'configuration.json').read_text())
    if api.MODEL!=config['model']['checkpoint']:raise ValueError('Gemini model differs from frozen configuration')
    if allowed!=set(config['selected_ids']):raise ValueError('Original Gemini selection differs')
    output=target/'predictions/gemini/annotations.jsonl'
    target.mkdir(parents=True,exist_ok=True)
    # Same checkpoint destination and lock as the original broad controller.
    with lock(source/'controller.lock'):
        keys=None;index=0;disabled=set()
        while True:
            paths=list((ANNOTATION/'runs').glob('*/predictions/gemini/annotations.jsonl'))
            paths+=list((ANNOTATION/'outputs').glob('**/gemini/annotations.jsonl'))
            done=validated_ids(paths,allowed,VideoAnnotation.model_validate)
            pending=sorted(allowed-done)
            status={'catalogue_total':len(allowed),'validated_complete':len(done),'pending':len(pending),'model':api.MODEL,'output':str(output)}
            write(target/'status.json',status);print(json.dumps(status),flush=True)
            if not pending:return
            if keys is None:keys=api.load_api_keys()
            for vid in pending:
                for p in (source/'evidence/videos'/f'{vid}.mp4',source/'evidence/context'/f'{vid}.json'):
                    if not p.is_file():raise FileNotFoundError('Missing Gemini evidence: '+str(p))
                result,index=rotating_video(keys,vid,index,disabled,{'models':{'gemini':{'checkpoint':api.MODEL}}})
                VideoAnnotation.model_validate(result)
                if result['video_id']!=vid:raise ValueError('Gemini returned wrong video ID')
                save_annotation(output,result)
                with output.open('ab') as f:f.flush();os.fsync(f.fileno())
                done.add(vid)
                write(target/'status.json',{**status,'validated_complete':len(done),'pending':len(allowed-done)})
            if once:return
            time.sleep(30)

def embedder(allowed,once):
    from .runtime import historical_runtime
    runtime=historical_runtime(ANNOTATION)
    os.environ['ATARAXIA_PROJECT_ROOT']=str(runtime)
    sys.path.insert(0,str(runtime/'src'))
    from ataraxia.semantic.worker import Worker,utc
    from ataraxia.semantic.config import freeze,check_freeze
    from ataraxia.semantic.sources import annotations,metadata
    from ataraxia.semantic.storage import lock,read,write,rebuild_manifest
    from ataraxia.runtime.config import resolve_path
    run=ANNOTATION/'semantic_pipeline/runs/semantic_full_v12'
    config=runtime/'semantic_pipeline/configs/pipeline_v12.json'
    worker=Worker(runtime,config,run)
    # Same frozen worker and checkpoints; staged models share the GPU lock.
    with lock(run/'worker.lock'):
        worker.frozen=freeze(runtime,config,run)
        worker.cfg=worker.frozen['config'];worker.cache=resolve_path(runtime,worker.cfg['cache_dir'])
        worker.taxonomy=read(run/'definitions/taxonomy');worker.template=read(run/'definitions/template');worker.schema=read(run/'definitions/schema')
        worker.prompt=(run/'definitions/prompt').read_text(encoding='utf-8-sig')
        worker.metadata={k:v for k,v in metadata(run).items() if k in allowed}
        if set(worker.metadata)!=allowed:raise ValueError('Frozen semantic metadata selection differs')
        with lock(resolve_path(runtime,worker.cfg['gpu_lock'])):
            try:
                while not worker.interrupted():
                    check_freeze(runtime,config,run,worker.frozen)
                    # Refresh the isolated reader snapshot as Gemini appends. The
                    # existing JSONL reader ignores any partial trailing line.
                    for name in worker.cfg['gemini_sources']:
                        source=ANNOTATION/name;destination=runtime/name
                        data=source.read_bytes()
                        if destination.read_bytes()!=data:
                            temporary=destination.with_name(destination.name+'.launcher.tmp')
                            temporary.write_bytes(data);os.replace(temporary,destination)
                    rows,errors=annotations(runtime,worker.cfg)
                    jobs,completed,failures,invalid,waiting=embedding_jobs(worker,rows,allowed)
                    pending,_,_,_=worker.queue({k:v for k,v in rows.items() if k in allowed})
                    status={'updated_at':utc(),'catalogue_total':len(allowed),'verified_complete_in_this_run':len(completed),'embedding_pending':len(jobs),'qwen_pending':waiting,'awaiting_gemini':len(allowed-set(rows)),'failed_or_backoff':failures,'invalid':invalid,'source_errors':errors,'qwen_inference':True}
                    write(ROOT/'backend/reports/processing_launcher/embedder_status.json',status)
                    print(json.dumps({k:(len(v) if isinstance(v,list) else v) for k,v in status.items()}),flush=True)
                    if not pending:
                        if once:return
                        time.sleep(30);continue
                    batch=pending[:max(worker.cfg['extractor']['batch_size'],worker.cfg['embedder']['batch_size'])]
                    process_semantic_batch(worker,batch,write,utc)
                    rebuild_manifest(run,worker.frozen)
            finally:worker.unload()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('target',choices=['gemini','embedder']);p.add_argument('--once',action='store_true');p.add_argument('--check',action='store_true');args=p.parse_args()
    sys.path.insert(0,str(ANNOTATION/'src'))
    allowed=run_ids(args.target)
    if args.check:
        result={'target':args.target,'catalogue_total':len(allowed),'scope':'original_full_run','inference_started':False}
        if args.target=='gemini':
            import importlib
            try:
                api=importlib.import_module('ataraxia.annotation.backends.gemini')
                importlib.import_module('ataraxia.annotation.backends.gemini_execution')
                result.update(dependencies_available=True,model=api.MODEL,python=sys.executable)
            except ModuleNotFoundError as e:
                result.update(dependencies_available=False,missing_module=e.name,python=sys.executable)
                print(json.dumps(result));raise SystemExit(1)
        if args.target=='embedder':
            from .runtime import historical_runtime
            runtime=historical_runtime(ANNOTATION)
            sys.path.insert(0,str(runtime/'src'))
            from ataraxia.semantic.config import check_freeze
            from ataraxia.semantic.storage import read
            run=ANNOTATION/'semantic_pipeline/runs/semantic_full_v12'
            try:
                check_freeze(runtime,runtime/'semantic_pipeline/configs/pipeline_v12.json',run,read(run/'frozen.json'))
                result['frozen_compatible']=True
                result['isolated_runtime']=str(runtime)
            except RuntimeError:
                result['frozen_compatible']=False
                result['blocker']='Historical frozen definitions/packages differ; restore matching environment/code or prepare a reviewed cached-semantics migration. Frozen provenance is not bypassed.'
        print(json.dumps(result));return
    try:
        if args.target=='gemini':gemini(allowed,args.once)
        else:embedder(allowed,args.once)
    except KeyboardInterrupt:print('Stopped; validated completions preserved. Run the same command to resume.')
    except ModuleNotFoundError as e:
        print(json.dumps({'stopped':True,'error_type':'ModuleNotFoundError','missing_module':e.name,'python':sys.executable}));raise SystemExit(1)
    except Exception as e:
        # Provider exceptions can contain secrets; never emit raw messages.
        print(json.dumps({'stopped':True,'error_type':type(e).__name__,'hint':'Check worker/GPU locks, frozen definitions, evidence and model availability. Embedder runs Qwen semantics then BGE-M3.'}));raise SystemExit(1)

if __name__=='__main__':main()
