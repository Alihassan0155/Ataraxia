"""Resumable held-out adapter around the frozen, working Gemini annotator."""
import hashlib
import importlib.metadata
import json
import os
import time
import multiprocessing as mp
import queue
from support import ROOT, validate_freeze, predictions, prediction_path, append, write


class GeminiWorkerError(RuntimeError):
    def __init__(self,message,category):
        super().__init__(message);self.category=category


def video_worker(messages,keys,vid,index,disabled,cfg):
    """A separate process allows a genuinely hung SDK call to be terminated."""
    from google import genai
    import annotate_gemini as existing
    existing.MODEL=cfg['models']['gemini']['checkpoint']
    def progress(video_id,stage,**details):
        if 'key_slot' in details:details['key_slot']=index+1
        messages.put({'event':'stage','video_id':video_id,'stage':stage,**details})
    existing.PROGRESS_HOOK=progress
    clients=[genai.Client(api_key=keys[index],http_options={'timeout':120000})]
    local_disabled=set()
    try:
        result,_=existing.annotate_video(clients,ROOT/'videos'/f'{vid}.mp4',vid,start_client_index=0,disabled_client_indexes=local_disabled)
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
                    append(ROOT/'predictions/gemini/events.jsonl',{'video_id':vid,'event':'heartbeat','stage':last,'elapsed_seconds':elapsed})
                    next_heartbeat=elapsed+15
                continue
            if event['event']=='stage':
                last=event['stage'];event['elapsed_seconds']=elapsed
                print(f'Gemini {vid}: {last} '+str({k:v for k,v in event.items() if k in ['state','key_slot']}),flush=True)
                append(ROOT/'predictions/gemini/events.jsonl',event)
                write(ROOT/'predictions/gemini/current_video.json',event)
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
            append(ROOT/'predictions/gemini/events.jsonl',{'event':'key_failover','video_id':vid,'key_slot':slot+1,'reason':str(exc)})
    raise GeminiWorkerError(f'{vid}: no result within 600s; attempted key slots {[k+1 for k in tried]}','KeyFailoverExhausted')


def main():
    cfg=validate_freeze()
    from dotenv import load_dotenv
    import annotate_gemini as existing
    load_dotenv(ROOT.parent/'.env')
    keys=existing.load_api_keys()
    existing.MODEL=cfg['models']['gemini']['checkpoint']
    done=predictions('gemini',cfg,repair_tail=True);failures=[];index=0;disabled=set()
    for vid in cfg['heldout_ids']:
        if vid in done:continue
        start=time.perf_counter()
        try:
            print(f'START Gemini {vid}; completed={len(done)}/50; deadline=600s',flush=True)
            try:result,index=rotating_video(keys,vid,index,disabled,cfg)
            except Exception:
                index=(index+1)%len(keys)
                raise
            result['run_metadata'].update({'media_sha256':hashlib.sha256((ROOT/'videos'/f'{vid}.mp4').read_bytes()).hexdigest(),
                'seconds':time.perf_counter()-start,'sdk_version':importlib.metadata.version('google-genai'),
                'frozen_config_sha256':hashlib.sha256((ROOT/'config/frozen_config.json').read_bytes()).hexdigest(),
                'provider_configuration_gaps':cfg['models']['gemini'],'heldout':True})
            result['run_metadata']['reliability_policy_version']='hard_per_key_failover_v4'
            append(prediction_path('gemini'),result);done[vid]=result
            print(f'OK Gemini {vid} {len(done)}/50',flush=True)
        except Exception as exc:
            error=repr(exc)
            for key in keys:error=error.replace(key,'[REDACTED]')
            failures.append(vid);append(ROOT/'predictions/gemini/failures.jsonl',{'video_id':vid,'error':error,'seconds':time.perf_counter()-start})
            print(f'FAILED Gemini {vid}: {error}',flush=True)
            # A failed video remains pending; attempt later videos without losing prior results.
            if len(disabled)==len(keys) or getattr(exc,'category',None)=='AllGeminiKeysUnavailable':break
        finally:write(ROOT/'predictions/gemini/status.json',{'expected':50,'completed':len(done),'failed_this_run':failures,'passed':len(done)==50 and not failures})
    if len(done)!=50:raise SystemExit(1)


if __name__=='__main__':main()
