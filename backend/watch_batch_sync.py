"""Windows hidden watcher entrypoint with absolute paths and local logs."""
from pathlib import Path
import contextlib
import json
import os
import sys
import time
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

if __name__=='__main__':
    target=ROOT/'backend/reports/automatic_batch_sync_20261018'
    target.mkdir(parents=True,exist_ok=True)
    with (target/'watcher.log').open('a',encoding='utf-8',buffering=1) as log:
        with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            from backend.video_data.batch_sync import main
            (target/'watcher_process.json').write_text(json.dumps({'pid':os.getpid(),
                'started_at':datetime.now(timezone.utc).isoformat()},indent=2),encoding='utf-8')
            args=['--queue',str(target/'queue.sqlite'),
                    '--approved-snapshot',str(ROOT/'backend/reports/catalogue_final_20261018/production_snapshot'),
                    '--annotation-root',str(ROOT/'annotation'),'--watch','--apply','--allow-live-writes']
            while True:
                try:
                    result=main(args)
                    if result in (None,0):break
                except Exception as error:
                    print(json.dumps({'event':'watcher_retry','error_type':type(error).__name__}),flush=True)
                time.sleep(30)
