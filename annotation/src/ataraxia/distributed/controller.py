"""Main-PC scheduler. SQLite is LOCAL; workers never open the database.

Only the controller publishes accepted results. Attempts have unique directories;
expired attempts are fenced by ID and workers hold a machine-local OS GPU lock.
"""
import argparse
import base64
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

from .common import lock, read, safe_id, sha, source_hashes, under, verify_sources, write


def database(run):
    db = sqlite3.connect(run/'scheduler.sqlite', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
          model TEXT, video_id TEXT, state TEXT DEFAULT 'pending', tries INTEGER DEFAULT 0,
          attempt TEXT, result TEXT, error TEXT, PRIMARY KEY(model,video_id));
        CREATE TABLE IF NOT EXISTS attempts (
          id TEXT PRIMARY KEY, worker TEXT, model TEXT, started REAL, deadline REAL,
          state TEXT DEFAULT 'running');
    ''')
    return db


def csv_write(path, rows):
    with Path(path).open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def config(path):
    c = read(path)
    if not c['workers'] or len({w['id'] for w in c['workers']}) != len(c['workers']):
        raise ValueError('Need distinct worker IDs')
    addresses = []
    for w in c['workers']:
        safe_id(w['id'])
        if w['transport'] not in ('local', 'ssh', 'ssh-task'):
            raise ValueError('Transport must be local, ssh, or ssh-task')
        if w.get('ssh_auth', 'key') not in ('key', 'interactive'):
            raise ValueError('ssh_auth must be key or interactive')
        if any(k in w for k in ('password', 'ssh_password')):
            raise ValueError('Never put SSH passwords in configuration')
        address = 'local' if w['transport'] == 'local' else w['host']
        if address in addresses:
            raise ValueError('Configure one worker per machine')
        addresses.append(address)
    if not 1 <= c.get('batch_size', 2) <= 16:
        raise ValueError('batch_size must be 1..16')
    if not 1 <= c.get('max_attempts', 3) <= 10:
        raise ValueError('max_attempts must be 1..10')
    return c


def worker_command(w, attempt=None, health=False):
    # EncodedCommand prevents PowerShell quoting/injection and supports UNC/spaces.
    from pathlib import PureWindowsPath
    script = w.get('bootstrap') or str(PureWindowsPath(w['root'])/'commands/distributed_worker.py')
    args = [w['python'], script, '--root', w['root'], '--local-root', w['local_root'], '--cache', w['cache']]
    if health:
        args += ['--health']
    else:
        args += ['--attempt', attempt]
    if w['transport'] == 'local':
        return args
    quote = lambda s: "'" + str(s).replace("'", "''") + "'"
    if w['transport'] == 'ssh-task':
        ps = ('& schtasks.exe /Run /TN ' + quote(w.get('task_name','AtaraxiaGPUWorker')) +
              ' 2>&1 | ForEach-Object { $_.ToString() }; exit $LASTEXITCODE')
    else:
        # OpenSSH prompts stay on its console. Redirect only REMOTE diagnostics
        # into stdout, which the controller can capture without password input.
        checks = '; '.join(
            'if (-not (Test-Path -LiteralPath ' + quote(path) +
            ')) { throw ' + quote(label + ': ' + str(path)) + ' }'
            for label, path in [('Worker Python missing', w['python']),
                                ('Project share inaccessible', w['root']),
                                ('Worker entry script missing', script)])
        ps = ('$ErrorActionPreference = "Stop"; try { ' + checks +
              '; & ' + ' '.join(map(quote, args)) +
              ' 2>&1 | ForEach-Object { $_.ToString() }; $code = $LASTEXITCODE; '
              'if ($code -ne 0) { Write-Output ("ATARAXIA_REMOTE_EXIT=" + $code) }; exit $code '
              '} catch { Write-Output ("ATARAXIA_REMOTE_ERROR: " + $_.ToString()); exit 1 }')
    encoded = base64.b64encode(ps.encode('utf-16le')).decode()
    auth = (['-o', 'BatchMode=no', '-o', 'PasswordAuthentication=yes',
             '-o', 'PreferredAuthentications=publickey,keyboard-interactive,password']
            if w.get('ssh_auth', 'key') == 'interactive' else ['-o', 'BatchMode=yes'])
    return ['ssh', *auth, '-o', 'StrictHostKeyChecking=yes',
            '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15',
            '-o', 'ServerAliveCountMax=3', w['host'],
            'powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]


def interactive_transport(w):
    return w['transport'] != 'local' and w.get('ssh_auth', 'key') == 'interactive'


def transport_options(w):
    if not interactive_transport(w):
        return {}
    if os.name != 'nt':
        raise RuntimeError('Interactive SSH workers require a Windows desktop console')
    # Each concurrent SSH process gets its own secure, echo-free OpenSSH prompt.
    # stderr and stdin stay out of logs; stdout still carries backend output.
    return {'creationflags': subprocess.CREATE_NEW_CONSOLE}


def launch(w, relative, log, timeout):
    with Path(log).open('ab') as f:
        try:
            return subprocess.run(worker_command(w, relative), stdout=f,
                                  stderr=None if interactive_transport(w) else subprocess.STDOUT,
                                  timeout=timeout, check=False, **transport_options(w)).returncode
        except subprocess.TimeoutExpired:
            f.write(b'\nController transport timeout; remote local watchdog fences inference.\n')
            return 124
        except OSError as e:
            f.write((repr(e)+'\n').encode()); return 127


def health_checks(c, busy=None, previous=None):
    results = {}
    for w in c['workers']:
        if w['id'] in (busy or set()):
            # Do not overwrite a scheduled task's inbox during an existing lease.
            results[w['id']] = (previous or {}).get(w['id'], {'ok':False,'error':'Existing lease; resume after its deadline'})
            continue
        try:
            probe = None
            log = (Path(c['controller_root'])/'runs/distributed_health_logs'/w['id']/(uuid.uuid4().hex+'.json')
                   if c.get('controller_root') else None)
            if w['transport'] == 'ssh-task':
                root = Path(c['controller_root'])
                probe = root/'runs/distributed_probes'/uuid.uuid4().hex/'health.json'
                write(root/'runs/distributed_inbox'/(w['id']+'.json'),
                      {'health_result':probe.relative_to(root).as_posix()})
            p = subprocess.run(worker_command(w, health=True), stdout=subprocess.PIPE,
                               stderr=None if interactive_transport(w) else subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace', timeout=90,
                               **transport_options(w))
            if log:
                write(log, {'worker':w['id'], 'host':w.get('host'), 'time':time.time(),
                            'returncode':p.returncode, 'stdout':p.stdout,
                            'stderr':p.stderr, 'interactive':interactive_transport(w)})
            if p.returncode:
                raise RuntimeError((p.stderr or '')[-2000:] or p.stdout[-2000:] or
                                   f'SSH exited {p.returncode}; inspect the interactive SSH window')
            if probe:
                end = time.monotonic()+90
                while not probe.exists() and time.monotonic() < end: time.sleep(1)
                if not probe.exists():
                    raise TimeoutError('Scheduled task produced no health report; inspect LastTaskResult, local logs/last_dispatch.json, SMB credentials for the task account and share ACLs')
                h = read(probe)
                if 'error' in h: raise RuntimeError(h['error'])
            else:
                h = json.loads(p.stdout.strip().splitlines()[-1])
            if abs(time.time()-h['utc_time']) > 30:
                raise RuntimeError('Worker clock differs by >30s; synchronize Windows clocks before dispatch')
            results[w['id']] = {'ok': True, **h}
        except Exception as e:
            results[w['id']] = {'ok': False, 'error': str(e)}
            if log and not log.exists():
                write(log, {'worker':w['id'], 'host':w.get('host'), 'time':time.time(),
                            'error':str(e), 'interactive':interactive_transport(w)})
        if log:
            results[w['id']]['diagnostic_log'] = str(log)
    return results


def initialize(root, run, manifest, limit, models, smoke_run=None):
    if run.exists():
        raise ValueError('Run already exists; resume it or choose a new run name')
    if not 3 <= limit <= 6:
        if smoke_run is None:
            raise ValueError('Full deployment needs --smoke-run with verified three-machine inference first')
        proof = smoke_report(smoke_run)
        if not proof['three_gpu_passed']:
            raise ValueError('Three-GPU smoke has not passed for both backends')
        if read(smoke_run/'frozen.json')['sources'] != source_hashes(root):
            raise ValueError('Code changed since smoke validation; run a fresh smoke first')
    if limit < 0:
        raise ValueError('Limit must be positive, or 0 for all remaining videos')
    with manifest.open(encoding='utf-8-sig', newline='') as f:
        candidates = list(csv.DictReader(f))
    ids = [r.get('assigned_id') or r.get('video_id') for r in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate input IDs')
    # Smoke on NEW videos only, across all saved research and distributed runs.
    excluded = set()
    for p in (root/'runs/distributed').glob('*/frozen.json'):
        excluded.update(read(p)['inputs'])
    for directory in ('outputs', 'pilot_50_reels_30h', 'heldout_50_evaluation', 'runs/distributed'):
        for p in (root/directory).rglob('annotations.jsonl'):
            for line in p.read_text(encoding='utf-8-sig').splitlines():
                if line.strip():
                    excluded.add(json.loads(line)['video_id'])
    # Preserve isolation of development and final held-out sets even for missing predictions.
    for p in [root/'pilot_50_reels_30h/pilot_metadata.csv', root/'heldout_50_evaluation/pilot_metadata.csv']:
        if p.exists():
            with p.open(encoding='utf-8-sig', newline='') as f:
                excluded.update(r['assigned_id'] for r in csv.DictReader(f))
    selected = []
    for r, vid in zip(candidates, ids):
        safe_id(vid)
        if vid in excluded:
            continue
        video = Path(r.get('file_path') or r.get('video_path') or '')
        context = Path(r.get('context_path') or '')
        if not video.is_absolute(): video = root/video
        if not context.is_absolute(): context = root/context
        if not video.is_file() or not context.is_file():
            raise FileNotFoundError(f'Input paths unavailable: {vid}; resolve the manifest, do not guess')
        selected.append((vid, video, context, r.get('duration_seconds') or r.get('duration') or '0'))
        if len(selected) == limit: break
    if not selected or (limit and len(selected) != limit):
        raise ValueError('Insufficient new eligible videos')
    original = read(root/'heldout_50_evaluation/config/frozen_config.json')['models']
    frozen = {'schema': 1, 'created': time.time(), 'sources': source_hashes(root),
              'manifest_sha256': sha(manifest), 'inputs': {}, 'models': {},
              'scope': 'smoke' if 3 <= limit <= 6 else 'full',
              'calibration': 'none; raw outputs only; frozen calibration remains separate'}
    for model in models:
        m = original[model]
        args = ['--revision', m['revision'], '--fps', '1.0', '--max-new-tokens', '1200',
                '--max-device-gib', '15.8', '--offline', '--max-frames', '32' if model == 'qwen' else '16']
        if model == 'qwen':
            args += ['--max-pixels', '262144', '--total-pixels', '0', '--allow-unbenchmarked-pilot']
        frozen['models'][model] = {'checkpoint': m['checkpoint'], 'revision': m['revision'],
                                  'arguments': args, 'packages': original['qwen']['pilot_configuration']['packages']}
    run.mkdir(parents=True)
    rows = []
    for vid, video, context, duration in selected:
        for kind, src, suffix in [('videos', video, '.mp4'), ('context', context, '.json')]:
            dest = run/'evidence'/kind/(vid+suffix)
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Central staging makes externally stored raw files accessible via ONE share.
            # Copies protect historical evidence from downstream accidental mutation.
            shutil.copy2(src, dest)
        frozen['inputs'][vid] = {'videos_sha256': sha(video), 'context_sha256': sha(context),
                                  'source_video': str(video), 'source_context': str(context)}
        rows.append({'assigned_id': vid, 'duration': duration})
    csv_write(run/'metadata.csv', rows)
    write(run/'frozen.json', frozen)
    db = database(run)
    with db:
        db.executemany('INSERT INTO jobs(model,video_id) VALUES (?,?)',
                       [(m, r['assigned_id']) for m in models for r in rows])
    export(db,run)
    db.close()


def smoke_report(run):
    frozen = read(run/'frozen.json')
    db = database(run)
    machines = {m: set() for m in ('qwen','internvl')}
    for row in db.execute("SELECT model,result FROM jobs WHERE state='done'"):
        item = json.loads(row['result'])
        machine = item['run_metadata'].get('distributed',{}).get('machine')
        if machine: machines[row['model']].add(machine)
    incomplete = db.execute("SELECT count(*) FROM jobs WHERE state!='done'").fetchone()[0]
    db.close()
    result = {'three_gpu_passed': not incomplete and 3 <= len(frozen['inputs']) <= 6
              and all(len(s) >= 3 for s in machines.values()),
              'machines_by_model': {k:sorted(v) for k,v in machines.items()},
              'incomplete_jobs': incomplete, 'video_count':len(frozen['inputs']),
              'note':'Requires accepted real predictions for each backend from three distinct machine hostnames.'}
    write(run/'smoke_validation.json',result)
    return result


def reconcile(db, run, frozen, max_attempts):
    from ataraxia.annotation.common import VideoAnnotation
    for a in db.execute("SELECT * FROM attempts WHERE state='running'").fetchall():
        folder = run/'attempts'/a['id']
        if not (folder/'receipt.json').exists() and time.time() < a['deadline']:
            continue
        receipt = read(folder/'receipt.json') if (folder/'receipt.json').exists() else {'error': 'deadline expired without receipt'}
        if not receipt.get('machine') and (folder/'health.json').exists():
            receipt['machine'] = read(folder/'health.json')['machine']
        accepted = {}
        seen = set()
        errors = []
        predictions = folder/'output/pilot/annotations.jsonl'
        if predictions.exists():
            for line in predictions.read_text(encoding='utf-8').splitlines():
                try:
                    item = json.loads(line)
                    VideoAnnotation.model_validate(item)
                    vid = item['video_id']
                    if vid in seen:
                        accepted.pop(vid,None)
                        raise ValueError('Duplicate result ID within attempt')
                    seen.add(vid)
                    job = db.execute('SELECT * FROM jobs WHERE model=? AND video_id=?', (a['model'], vid)).fetchone()
                    if not job or job['attempt'] != a['id'] or vid in accepted:
                        raise ValueError('Duplicate, unexpected, or stale prediction')
                    md = item['run_metadata']
                    cfg = frozen['models'][a['model']]
                    if md.get('revision') != cfg['revision'] or md.get('media_sha256') != frozen['inputs'][vid]['videos_sha256']:
                        raise ValueError('Revision/media hash mismatch')
                    if md.get('peak_device_gib') is None or md['peak_device_gib'] > 15.8:
                        raise ValueError('Device-memory gate failed; raw prediction retained in attempt')
                    accepted[vid] = item
                except Exception as e:
                    errors.append(str(e))
        with db:
            for j in db.execute("SELECT * FROM jobs WHERE attempt=? AND state='running'", (a['id'],)).fetchall():
                vid = j['video_id']
                if vid in accepted:
                    item = accepted[vid]
                    item['run_metadata']['distributed'] = {'worker_id': a['worker'],
                        'attempt_id': a['id'], 'machine': receipt.get('machine'),
                        'receipt': str(folder.relative_to(run)/'receipt.json')}
                    db.execute("UPDATE jobs SET state='done',result=?,error=NULL WHERE model=? AND video_id=?",
                               (json.dumps(item), a['model'], vid))
                else:
                    state = 'failed' if j['tries'] >= max_attempts else 'pending'
                    error = json.dumps({'receipt': receipt, 'validation_errors': errors})
                    db.execute('UPDATE jobs SET state=?,error=? WHERE model=? AND video_id=?', (state,error,a['model'],vid))
            db.execute("UPDATE attempts SET state='finished' WHERE id=?", (a['id'],))


def export(db, run):
    counts = [dict(r) for r in db.execute('SELECT model,state,count(*) AS count FROM jobs GROUP BY model,state')]
    workers = [dict(r) for r in db.execute("SELECT id,worker,model,started,deadline FROM attempts WHERE state='running'")]
    for a in workers:
        p = run/'attempts'/a['id']/'heartbeat.json'
        if p.exists():
            a['heartbeat'] = read(p)
            a['heartbeat_age_seconds'] = time.time()-a['heartbeat']['time']
        status = run/'attempts'/a['id']/'output/pilot/status.json'
        if status.exists():
            a['backend_progress'] = read(status)
    write(run/'progress.json', {'time': time.time(), 'counts': counts, 'active': workers})
    for model in {r['model'] for r in counts}:
        folder = run/'results'/model
        folder.mkdir(parents=True, exist_ok=True)
        completed = next((r['count'] for r in counts if r['model']==model and r['state']=='done'),0)
        marker = folder/'export_state.json'
        if marker.exists() and read(marker)['completed']==completed and (folder/'annotations.jsonl').exists():
            continue
        tmp = folder/'annotations.jsonl.tmp'
        tmp.write_text(''.join(r['result']+'\n' for r in db.execute(
            "SELECT result FROM jobs WHERE state='done' AND model=? ORDER BY video_id", (model,))), encoding='utf-8')
        os.replace(tmp, folder/'annotations.jsonl')
        write(marker,{'completed':completed})
    write(run/'failures.json', [dict(r) for r in db.execute('SELECT model,video_id,state,tries,error FROM jobs WHERE error IS NOT NULL')])
    return counts


def schedule(root, run, c, resume=False):
    frozen = read(run/'frozen.json')
    verify_sources(root, frozen['sources'])
    # This lock lives on the main PC, never an SMB-hosted SQLite database.
    with lock(root/'runs/distributed/controller.lock'), closing(database(run)) as db:
        config_record = run/'scheduler_config.json'
        if config_record.exists() and read(config_record) != c:
            write(run/'scheduler_config_history'/(uuid.uuid4().hex+'.json'),
                  {'changed':time.time(),'previous':read(config_record),'replacement':c})
        write(config_record,c)
        if resume:
            for name in ('STOP', 'ABORT'):
                (run/name).unlink(missing_ok=True)
        elif (run/'STOP').exists():
            raise ValueError('Run is stopped; use resume')
        reconcile(db,run,frozen,c.get('max_attempts',3))
        busy = {r['worker'] for r in db.execute("SELECT worker FROM attempts WHERE state='running'")}
        previous = read(run/'worker_health.json') if (run/'worker_health.json').exists() else {}
        health = health_checks(c,busy,previous)
        write(run/'worker_health.json', health)
        healthy = [w for w in c['workers'] if health[w['id']]['ok']]
        machine_names = [health[w['id']]['machine'] for w in healthy]
        if len(machine_names) != len(set(machine_names)):
            raise RuntimeError('Several configured workers resolve to the same PC; fix the worker list')
        if not healthy:
            raise RuntimeError('No healthy workers; see worker_health.json')
        futures = {}
        cooldown = {}
        with ThreadPoolExecutor(max_workers=len(healthy)) as pool:
            while True:
                for wid, (future, aid) in list(futures.items()):
                    if future.done():
                        code = future.result()
                        write(run/'attempts'/aid/'transport.json', {'returncode': code, 'time': time.time()})
                        # SSH disconnect is NOT proof that remote CUDA has stopped.
                        # Reconcile only receipt or bounded watchdog deadline + grace.
                        cooldown[wid] = time.time() + (30 if code else 0)
                        del futures[wid]
                reconcile(db, run, frozen, c.get('max_attempts', 3))
                export(db, run)
                running = db.execute("SELECT count(*) FROM attempts WHERE state='running'").fetchone()[0]
                pending = db.execute("SELECT count(*) FROM jobs WHERE state='pending'").fetchone()[0]
                if (not pending or (run/'STOP').exists()) and not running and not futures:
                    break
                if not (run/'STOP').exists():
                    for w in healthy:
                        wid = w['id']
                        if wid in futures or time.time() < cooldown.get(wid, 0): continue
                        if db.execute("SELECT 1 FROM attempts WHERE worker=? AND state='running'", (wid,)).fetchone(): continue
                        first = db.execute("SELECT model FROM jobs WHERE state='pending' ORDER BY model DESC LIMIT 1").fetchone()
                        if not first: break
                        model = first['model']
                        jobs = db.execute("SELECT video_id FROM jobs WHERE model=? AND state='pending' ORDER BY video_id LIMIT ?",
                                          (model,c.get('batch_size',2))).fetchall()
                        ids = [j['video_id'] for j in jobs]
                        aid = uuid.uuid4().hex
                        folder = run/'attempts'/aid
                        folder.mkdir(parents=True)
                        timeout = c.get('timeout_per_video_seconds',2400)*len(ids)+c.get('model_load_seconds',300)
                        lease_deadline = time.time()+timeout+120
                        request = {'attempt': aid, 'worker_id': wid, 'model': model, 'ids': ids,
                                   'run_relative': run.relative_to(root).as_posix(), 'timeout_seconds': timeout,
                                   'lease_deadline':lease_deadline}
                        write(folder/'request.json', request)
                        if w['transport'] == 'ssh-task':
                            write(root/'runs/distributed_inbox'/(wid+'.json'),
                                  {'attempt':folder.relative_to(root).as_posix()})
                        with (run/'metadata.csv').open(encoding='utf-8',newline='') as f:
                            rows = [r for r in csv.DictReader(f) if r['assigned_id'] in ids]
                        csv_write(folder/'metadata.csv',rows)
                        with db:
                            db.execute('INSERT INTO attempts(id,worker,model,started,deadline) VALUES (?,?,?,?,?)',
                                       (aid,wid,model,time.time(),lease_deadline))
                            db.executemany("UPDATE jobs SET state='running',tries=tries+1,attempt=? WHERE model=? AND video_id=?",
                                           [(aid,model,vid) for vid in ids])
                        print(f'{wid}: {model} {ids} attempt={aid}', flush=True)
                        futures[wid] = (pool.submit(launch,w,folder.relative_to(root).as_posix(),folder/'worker.log',timeout+90),aid)
                time.sleep(2)
        counts = export(db,run)
        db.close()
        print(json.dumps(counts,indent=2))
        if any(r['state']=='failed' for r in counts):
            raise SystemExit(1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['init','run','resume','status','stop','abort','health','verify-smoke'])
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--run', default='smoke_6')
    p.add_argument('--manifest', type=Path)
    p.add_argument('--limit', type=int, default=6)
    p.add_argument('--smoke-run')
    p.add_argument('--models', nargs='+', choices=['qwen','internvl'], default=['qwen','internvl'])
    a = p.parse_args()
    c = config(a.config)
    root = Path(c['controller_root']).resolve()
    if str(root).startswith('\\\\'):
        raise ValueError('Run controller on main PC using local disk, not UNC (SQLite)')
    os.environ['ATARAXIA_PROJECT_ROOT'] = str(root)
    run = under(root/'runs/distributed',safe_id(a.run))
    if a.action == 'init':
        proof = under(root/'runs/distributed',safe_id(a.smoke_run)) if a.smoke_run else None
        initialize(root,run,a.manifest or root/'data/normalized/preprocessed_merged_v2/ready_metadata.csv',a.limit,a.models,proof)
        print(f'Prepared {a.limit} new videos at {run}; inference has NOT started.')
    elif a.action == 'health':
        with lock(root/'runs/distributed/controller.lock'):
            print(json.dumps(health_checks(c),indent=2))
    elif a.action == 'verify-smoke':
        result = smoke_report(run)
        print(json.dumps(result,indent=2))
        if not result['three_gpu_passed']: raise SystemExit(1)
    elif a.action in ('stop','abort'):
        run.joinpath('STOP').write_text('Stop dispatching; finish active batches',encoding='utf-8')
        if a.action == 'abort': run.joinpath('ABORT').write_text('Abort active workers',encoding='utf-8')
    elif a.action == 'status':
        print(json.dumps(read(run/'progress.json'),indent=2))
    else:
        schedule(root,run,c,a.action=='resume')


if __name__ == '__main__':
    main()
