"""Minimal local launcher for an authenticated scheduled task; code stays on SMB.

Copy only this file to the worker. Task Scheduler owns the saved account logon;
neither this launcher nor the controller receives or logs its password.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
p.add_argument('--root', type=Path, required=True)
p.add_argument('--worker', required=True)
p.add_argument('--local-root', required=True)
p.add_argument('--cache', required=True)
p.add_argument('--logs', type=Path)
a = p.parse_args()
if a.logs:
    a.logs.mkdir(parents=True, exist_ok=True)
# Local diagnostics must work even before importing code from the SMB share.
import os
import socket
import time
import traceback

def local_diagnostic(value):
    if a.logs:
        target = a.logs/'last_dispatch.json'
        tmp = target.with_suffix('.tmp')
        tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
        os.replace(tmp, target)

try:
    local_diagnostic({'worker':a.worker, 'machine':socket.gethostname(),
                      'started':time.time(), 'stage':'opening_share'})
    if not (a.root/'src').is_dir():
        raise RuntimeError(f'Project share inaccessible to scheduled task account: {a.root}')
    sys.path.insert(0,str(a.root/'src'))
    from ataraxia.distributed.common import read, under, write, lock

    with lock(Path(a.local_root)/'scheduled_dispatch.lock'):
        message = read(a.root/'runs/distributed_inbox'/(a.worker+'.json'))
        cmd = [sys.executable,str(a.root/'commands/distributed_worker.py'),'--root',str(a.root),
               '--local-root',a.local_root,'--cache',a.cache]
        if 'health_result' in message:
            target = under(a.root,message['health_result'])
            try:
                r = subprocess.run(cmd+['--health'],capture_output=True,text=True,timeout=80)
                if r.returncode: raise RuntimeError(r.stderr[-2000:] or r.stdout[-2000:] or f'Worker exited {r.returncode}')
                write(target,json.loads(r.stdout.strip().splitlines()[-1]))
                local_diagnostic({'worker':a.worker,'finished':time.time(),'stage':'health_passed'})
            except Exception as e:
                write(target,{'error':str(e)})
                local_diagnostic({'worker':a.worker,'failed':time.time(),'error':str(e)})
        else:
            attempt = under(a.root,message['attempt'])
            if (attempt/'receipt.json').exists(): raise SystemExit(0)
            with (attempt/'scheduled_worker.log').open('ab') as f:
                # Worker owns its deadline and GPU OS lock; Task Scheduler IgnoreNew
                # additionally prevents two task instances on this machine.
                r = subprocess.run(cmd+['--attempt',message['attempt']],stdout=f,stderr=subprocess.STDOUT)
                if a.logs:
                    write(a.logs/'last_attempt.json', {'attempt':message['attempt'],'returncode':r.returncode})
                raise SystemExit(r.returncode)
except Exception:
    local_diagnostic({'worker':a.worker, 'machine':socket.gethostname(),
                      'failed':time.time(), 'error':traceback.format_exc()})
    raise
