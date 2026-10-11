"""Existing hard Gemini deadline/key-failover policy with configured output paths."""
import multiprocessing as mp
import queue
import time
from ataraxia.runtime.config import Settings
from ataraxia.runtime.paths import metadata_path
from ataraxia.runtime.paths import evidence_root
from ataraxia.annotation.common import OUTPUT_ROOT, load_processed_ids, save_annotation
import json
import csv

ROOT = OUTPUT_ROOT

def append(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(value,ensure_ascii=False)+'\n')

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)

class GeminiWorkerError(RuntimeError):
    def __init__(self,message,category):
        super().__init__(message);self.category=category


def video_worker(messages,keys,vid,index,disabled,cfg):
    """A separate process allows a genuinely hung SDK call to be terminated."""
    from google import genai
    from ataraxia.annotation.backends import gemini as existing
    existing.MODEL=cfg['models']['gemini']['checkpoint']
    def progress(video_id,stage,**details):
        if 'key_slot' in details:details['key_slot']=index+1
        messages.put({'event':'stage','video_id':video_id,'stage':stage,**details})
    existing.PROGRESS_HOOK=progress
    clients=[genai.Client(api_key=keys[index],http_options={'timeout':120000})]
    local_disabled=set()
    try:
        result,_=existing.annotate_video(clients,evidence_root()/'videos'/f'{vid}.mp4',vid,start_client_index=0,disabled_client_indexes=local_disabled)
        messages.put({'event':'result','annotation':result,'index':index,'disabled':[]})
    except Exception as exc:
        error=repr(exc)
        for key in keys:error=error.replace(key,'[REDACTED]')
        messages.put({'event':'error','error':error,'disabled':[index] if local_disabled else [],'category':type(exc).__name__})


def bounded_video(keys,vid,index,disabled,cfg,deadline_seconds=600,target=video_worker):
    context=mp.get_context('spawn');messages=context.Queue()
    worker=context.Process(target=target,args=(messages,keys,vid,index,list(disabled),cfg))
    worker.start();started=time.monotonic();last='starting';next_heartbeat=15
    try:
        while True:
            elapsed=time.monotonic()-started
            if elapsed>=deadline_seconds:raise TimeoutError(f'{vid}: total deadline {deadline_seconds}s exceeded; last stage={last}')
            try:event=messages.get(timeout=min(1,deadline_seconds-elapsed))
            except queue.Empty:
                if not worker.is_alive():raise RuntimeError(f'Gemini worker exited {worker.exitcode} without returning a result; last stage={last}')
                if elapsed>=next_heartbeat:
                    print(f'Gemini {vid}: waiting stage={last}, elapsed={elapsed:.0f}s / {deadline_seconds}s',flush=True)
                    append(ROOT/'gemini/events.jsonl',{'video_id':vid,'event':'heartbeat','stage':last,'elapsed_seconds':elapsed})
                    next_heartbeat=elapsed+15
                continue
            if event['event']=='stage':
                last=event['stage'];event['elapsed_seconds']=elapsed
                print(f'Gemini {vid}: {last} '+str({k:v for k,v in event.items() if k in ['state','key_slot']}),flush=True)
                append(ROOT/'gemini/events.jsonl',event)
                write(ROOT/'gemini/current_video.json',event)
            elif event['event']=='error':
                disabled.update(event.get('disabled',[]))
                raise GeminiWorkerError(f"{vid}: {event['category']} during {last}: {event['error']}",event['category'])
            elif event['event']=='result':
                disabled.update(event.get('disabled',[]))
                return event['annotation'],event['index']
    finally:
        worker.join(timeout=1)
        if worker.is_alive():worker.terminate();worker.join(timeout=5)
        messages.close()


def rotating_video(keys,vid,index,disabled,cfg,attempt_runner=bounded_video):
    started=time.monotonic();tried=[]
    for offset in range(len(keys)):
        slot=(index+offset)%len(keys)
        if slot in disabled:continue
        remaining=600-(time.monotonic()-started)
        if remaining<=0:break
        tried.append(slot)
        print(f'Gemini {vid}: trying key slot {slot+1}/{len(keys)} (maximum 180s for this key)',flush=True)
        try:return attempt_runner(keys,vid,slot,disabled,cfg,deadline_seconds=min(180,remaining))
        except (TimeoutError,GeminiWorkerError) as exc:
            if isinstance(exc,GeminiWorkerError) and exc.category not in ['AllGeminiKeysUnavailable','TimeoutError','ReadTimeout','ConnectTimeout']:
                raise
            print(f'Gemini {vid}: key slot {slot+1} failed/timed out; switching to next key',flush=True)
            append(ROOT/'gemini/events.jsonl',{'event':'key_failover','video_id':vid,'key_slot':slot+1,'reason':str(exc)})
    raise GeminiWorkerError(f'{vid}: no result within 600s; attempted key slots {[k+1 for k in tried]}','KeyFailoverExhausted')


def main():
    from ataraxia.annotation.backends import gemini as existing
    keys=existing.load_api_keys()
    cfg={'models':{'gemini':{'checkpoint':existing.MODEL}}}
    with metadata_path().open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    saved=OUTPUT_ROOT/'gemini/annotations.jsonl'
    saved.parent.mkdir(parents=True,exist_ok=True)
    done=load_processed_ids(saved);disabled=set();index=0;failures=[]
    for row in rows:
        vid=row['assigned_id']
        if vid in done:continue
        try:
            result,index=rotating_video(keys,vid,index,disabled,cfg)
            result['run_metadata']['reliability_policy_version']='hard_per_key_failover_v4'
            save_annotation(saved,result);done.add(vid)
        except Exception as exc:
            error=repr(exc)
            for key in keys:error=error.replace(key,'[REDACTED]')
            append(OUTPUT_ROOT/'gemini/failures.jsonl',{'video_id':vid,'error':error})
            failures.append(vid);index=(index+1)%len(keys)
            if len(disabled)==len(keys):break
    write(OUTPUT_ROOT/'gemini/status.json',{'expected':len(rows),'completed':len(done),'failed_video_ids':failures})
    if failures or len(done)<len(rows):raise SystemExit(1)

if __name__=='__main__':main()
