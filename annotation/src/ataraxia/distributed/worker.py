"""One isolated batch per invocation; runs unchanged backend main in this process."""
import argparse
import importlib.metadata
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys
import threading
import time
import traceback

from .common import lock, read, sha, under, verify_sources, write


def health(root, cache):
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable')
    return {'machine': socket.gethostname(), 'python': sys.executable,
            'utc_time':time.time(),
            'project': str(root), 'cache': str(cache), 'cuda': torch.version.cuda,
            'gpu': torch.cuda.get_device_name(0),
            'vram_bytes': torch.cuda.get_device_properties(0).total_memory,
            'packages': {k: importlib.metadata.version(k) for k in
                         ('torch', 'transformers', 'bitsandbytes', 'accelerate', 'qwen-vl-utils', 'av')}}


def execute(root, attempt, local_root, cache):
    request = read(attempt/'request.json')
    run = under(root, request['run_relative'])
    frozen = read(run/'frozen.json')
    verify_sources(root, frozen['sources'])
    cfg = frozen['models'][request['model']]
    # All accounts on this PC must share the configured local state/lock path.
    with lock(local_root/'gpu0.lock'):
        stop = threading.Event()
        start = time.time()
        remaining = request['lease_deadline'] - start - 30
        if remaining <= 0:
            raise RuntimeError('Attempt lease expired before inference; refusing late execution')
        # Separate timer: a blocked SMB heartbeat must not disable the local deadline.
        deadline = threading.Timer(min(request['timeout_seconds'], remaining), lambda: os._exit(124))
        deadline.daemon = True
        deadline.start()
        def watchdog():
            while not stop.wait(5):
                try:
                    if (run/'ABORT').exists():
                        write(attempt/'receipt.json', {'machine':socket.gethostname(),
                              'exit_code':124, 'error':'operator abort', 'finished':time.time()})
                        os._exit(124)
                    write(attempt/'heartbeat.json', {'time': time.time(), 'pid': os.getpid(),
                          'machine': socket.gethostname(), 'elapsed': time.time()-start})
                except OSError:
                    pass  # Local deadline remains active even when SMB disconnects.
                if (run/'ABORT').exists() or time.time()-start > request['timeout_seconds']:
                    # Inference is inside THIS process; exiting releases its CUDA context.
                    os._exit(124)
        threading.Thread(target=watchdog, daemon=True).start()
        receipt = {'machine': socket.gethostname(), 'worker_id': request['worker_id'],
                   'attempt': request['attempt'], 'started': start, 'pid': os.getpid()}
        try:
            os.environ.update(ATARAXIA_PROJECT_ROOT=str(root),
                ATARAXIA_PILOT_DIR=str(run/'evidence'),
                ATARAXIA_METADATA_PATH=str(attempt/'metadata.csv'),
                ATARAXIA_EXPECTED_VIDEO_COUNT=str(len(request['ids'])),
                HF_HOME=str(cache), HF_HUB_DISABLE_XET='1',
                HF_HUB_CACHE=str(cache/'hub'), HF_ASSETS_CACHE=str(cache/'assets'),
                FORCE_QWENVL_VIDEO_READER='pyav', PYTHONUTF8='1')
            receipt['health'] = health(root, cache)
            expected_packages = cfg['packages']
            if receipt['health']['packages'] != expected_packages:
                raise RuntimeError('Package versions differ from frozen validated environment')
            if 'RTX A4000' not in receipt['health']['gpu']:
                raise RuntimeError('Expected RTX A4000; review a new deployment config for other GPUs')
            for vid in request['ids']:
                item = frozen['inputs'][vid]
                for kind, suffix in [('videos', '.mp4'), ('context', '.json')]:
                    if sha(run/'evidence'/kind/(vid+suffix)) != item[kind+'_sha256']:
                        raise RuntimeError(f'Evidence changed: {vid}/{kind}')
            write(attempt/'health.json', receipt['health'])
            sys.argv = [request['model'], '--run-dir', str(attempt/'output'),
                        '--phase', 'pilot', *cfg['arguments']]
            try:
                runpy.run_module('ataraxia.annotation.backends.'+request['model'], run_name='__main__')
                receipt['exit_code'] = 0
            except SystemExit as exc:
                receipt['exit_code'] = int(exc.code or 0)
        except BaseException:
            receipt.update(exit_code=1, error=traceback.format_exc())
        finally:
            stop.set()
            receipt.update(finished=time.time(), elapsed_seconds=time.time()-start)
            write(attempt/'receipt.json', receipt)
            deadline.cancel()
        return receipt['exit_code']


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--attempt')
    p.add_argument('--local-root', required=True, type=Path)
    p.add_argument('--cache', required=True, type=Path)
    p.add_argument('--health', action='store_true')
    a = p.parse_args()
    if str(a.local_root).startswith('\\\\') or str(a.cache).startswith('\\\\'):
        raise ValueError('Worker state and model cache must be LOCAL paths')
    a.local_root.mkdir(parents=True, exist_ok=True)
    a.cache.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HOME'] = str(a.cache)
    os.environ['HF_HUB_CACHE'] = str(a.cache/'hub')
    os.environ['HF_ASSETS_CACHE'] = str(a.cache/'assets')
    if a.health:
        import json
        print(json.dumps(health(a.root, a.cache)))
        return
    raise SystemExit(execute(a.root, under(a.root, a.attempt), a.local_root, a.cache))


if __name__ == '__main__':
    main()
