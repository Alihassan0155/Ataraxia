"""Run frozen Qwen -> InternVL -> Gemini in separate sequential processes."""
import argparse
import json
import os
import subprocess
import sys
import time
from support import ROOT, validate_freeze, predictions, write, append


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight-only',action='store_true')
    args=parser.parse_args();cfg=validate_freeze()
    env=os.environ.copy();env.update(PYTHONUTF8='1',PYTHONUNBUFFERED='1',ATARAXIA_PILOT_DIR=str(ROOT),ATARAXIA_OUTPUT_ROOT=str(ROOT/'predictions'),HF_HOME=str(ROOT.parent/'.cache/huggingface'),HF_HUB_DISABLE_XET='1')
    common=['--phase','pilot','--fps','1.0','--max-new-tokens','1200','--max-device-gib','15.8','--offline']
    gemini_python=ROOT/'.venv-gemini/Scripts/python.exe'
    if not args.preflight_only:
        if not gemini_python.is_file():raise RuntimeError('Run heldout_50_evaluation/setup_gemini.ps1 first; missing isolated Gemini environment. No inference started.')
        check=subprocess.run([str(gemini_python),'-c','from google import genai; import pandas,dotenv,pydantic,tqdm'],env=env,capture_output=True,text=True)
        if check.returncode:raise RuntimeError('Gemini dependency check failed. Run setup_gemini.ps1; no inference started.')
    commands={
        'qwen':[sys.executable,str(ROOT/'components/annotate_qwen_cuda.py'),'--run-dir',str(ROOT/'predictions/qwen'),'--revision',cfg['models']['qwen']['revision'],'--max-frames','32','--max-pixels','262144','--total-pixels','0','--allow-unbenchmarked-pilot',*common],
        'internvl':[sys.executable,str(ROOT/'components/annotate_internvl_cuda.py'),'--run-dir',str(ROOT/'predictions/internvl'),'--revision',cfg['models']['internvl']['revision'],'--max-frames','16',*common],
        'gemini':[str(gemini_python),str(ROOT/'scripts/run_gemini.py')]}
    errors=[];status={'order':list(commands),'started':time.time(),'models':{}}
    for model,command in commands.items():
        done=predictions(model,cfg,repair_tail=True)
        if len(done)==50:
            print(f'{model}: all 50 validated predictions already present; skipping model loading.',flush=True)
            status['models'][model]={'completed':50,'skipped':True};continue
        if args.preflight_only:
            if model=='gemini':continue
            command=command+['--preflight']
        print(f'Starting {model}; validated saved predictions: {len(done)}/50',flush=True)
        append(ROOT/'checkpoints/inference_events.jsonl',{'model':model,'event':'start','time':time.time(),'completed_before':len(done)})
        with (ROOT/'logs'/f'{model}.log').open('a',encoding='utf-8') as log:
            child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
            for line in child.stdout:print(line,end='',flush=True);log.write(line);log.flush()
            code=child.wait()
        completed=len(predictions(model,cfg))
        status['models'][model]={'exit_code':code,'completed':completed,'preflight_only':args.preflight_only}
        append(ROOT/'checkpoints/inference_events.jsonl',{'model':model,'event':'finish','time':time.time(),'exit_code':code,'completed':completed})
        if code:errors.append(model)
        write(ROOT/'checkpoints/inference_status.json',status)
        # Separate processes ensure the GPU model/allocator is released before the next model.
    status['finished']=time.time();status['passed']=not errors and (args.preflight_only or all(r['completed']==50 for r in status['models'].values()))
    write(ROOT/'checkpoints/inference_status.json',status)
    if not status['passed']:raise SystemExit(1)


if __name__=='__main__':main()
