"""Pause the exact legacy watcher, run approved sync, restore its prior process state.

Run using the main environment (psutil); data import uses the import environment.
The startup registry value and watcher configuration files are never modified.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import winreg

import psutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'backend/reports/full_sync_20261103'
SCRIPT = ROOT / 'backend/watch_batch_sync.py'


def watchers():
    result = []
    for p in psutil.process_iter(['pid', 'ppid', 'name', 'cmdline']):
        try:
            if p.info['name'].lower() != 'pythonw.exe':
                continue
            if any(str(SCRIPT).lower() == x.lower() for x in p.info['cmdline'] or []):
                result.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def startup():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                        r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        try:
            return winreg.QueryValueEx(key, 'AtaraxiaBatchSync')
        except FileNotFoundError:
            return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    original = watchers()
    pids = {p.pid for p in original}
    parents = [p for p in original if p.ppid() not in pids]
    if len(parents) > 1:
        raise RuntimeError('Multiple original watcher trees; manual review required')
    command = parents[0].cmdline() if parents else None
    registry = startup()
    configs = [ROOT / 'backend/reports/automatic_batch_sync_20261018' / n
               for n in ['activation.json', 'activation_results.json']]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in configs if p.exists()}
    state = dict(original_pids=sorted(pids), was_running=bool(original), command=command,
                 startup=registry, configuration_hashes=hashes, restored=False)
    (OUT / 'watcher_state.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
    stopped = False
    try:
        # Terminate the supervising wrapper first to prevent respawn. PostgreSQL
        # rolls back an interrupted transaction; the sync also takes the OS and
        # PostgreSQL advisory locks before taking its preservation baseline.
        stopped = bool(original)
        for p in parents:
            p.terminate()
        for p in original:
            if p not in parents:
                try:
                    p.terminate()
                except psutil.NoSuchProcess:
                    pass
        _, alive = psutil.wait_procs(original, timeout=15)
        if alive or watchers():
            raise RuntimeError('Watcher did not stop; no sync attempted')
        state['paused'] = True
        (OUT / 'watcher_state.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        with (OUT / 'apply.log').open('a', encoding='utf-8') as log:
            code = subprocess.call([str(ROOT / 'backend/.venv-import/Scripts/python.exe'), '-B',
                '-u', '-m', 'backend.video_data.full_sync', 'apply', '--approved-all-4226'],
                cwd=ROOT, stdout=log, stderr=log)
        state['sync_exit_code'] = code
        return code
    finally:
        if stopped and command and not watchers():
            child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
            state['restored_wrapper_pid'] = child.pid
            time.sleep(3)
        state['restored_pids'] = [p.pid for p in watchers()]
        state['restored'] = bool(state['restored_pids']) == bool(original)
        state['startup_unchanged'] = startup() == registry
        state['configuration_unchanged'] = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
                                              for p, h in hashes.items())
        (OUT / 'watcher_state.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        if not all(state[k] for k in ('restored', 'startup_unchanged', 'configuration_unchanged')):
            raise RuntimeError('Watcher restoration verification requires attention')


if __name__ == '__main__':
    sys.exit(main())
