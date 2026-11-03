"""Execute only the separately approved 2026-11-03 physical retention plan.

No S3 client, metadata replacement, generalized delete, or historical replay.
Any exception before commit rolls back. The watcher remains paused on failure.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from psycopg import sql

from .artifacts import fingerprint
from .catalogue import ORDER, key, load_package, read_snapshot, validate
from .config import DatabaseSettings, connect
from .physical_dedup_plan import OUT, TARGETS
from .rehearse_catalogue import compare

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'backend/reports/physical_dedup_execution_20261104'
WATCH = ROOT / 'backend/reports/automatic_batch_sync_20261018'


def save(name, value):
    REPORT.mkdir(exist_ok=True)
    raw = json.dumps(value, indent=2, default=str, allow_nan=False).encode()
    path = REPORT / name
    with path.with_suffix('.tmp').open('wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    path.with_suffix('.tmp').replace(path)


def integrity():
    checks = json.loads((OUT / 'checksums.json').read_bytes())
    for name, digest in checks.items():
        if hashlib.sha256((OUT / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Prepared evidence drift: ' + name)
    original, manifest = load_package(OUT / 'backup')
    desired, _ = load_package(OUT / 'canonical')
    ids = json.loads((OUT / 'identities.json').read_bytes())
    for table in ORDER:
        before = {key(r, table) for r in original[table]}
        after = {key(r, table) for r in desired[table]}
        if sorted(before-after) != ids[table]['delete'] or sorted(after) != ids[table]['retain']:
            raise ValueError('Identity plan drift')
    if sum(len(v['delete']) for v in ids.values()) != 819:
        raise ValueError('Unexpected deletion scope')
    proof = json.loads((REPORT / 'local_validation/rehearsal.json').read_bytes())
    required = ('native_restore_matches_every_original_row', 'rollback_preserves_all_rows',
                'dedup_matches_exact_retained_ids_and_values', 'repeat_deletes_zero',
                'future_update_rollback_preserves_canonical_rows',
                'future_complete_update_is_atomic_idempotent_and_preserves_ids',
                'partial_cannot_overwrite_complete', 'older_complete_replay_ignored',
                'replaced_version_durably_archived_before_upsert', 'cross_video_embedding_link_rejected')
    if not all(proof.get(k) is True for k in required):
        raise ValueError('Local restore/migration/writer verification incomplete')
    cutover=json.loads((REPORT/'cutover_validation.json').read_bytes())
    if not cutover or not all(v is True for v in cutover.values()):
        raise ValueError('Queue adapter and legacy guard validation incomplete')
    return original, desired, manifest, ids


def queue_audit(ids):
    with sqlite3.connect((WATCH/'queue.sqlite').resolve().as_uri()+'?mode=ro', uri=True) as conn:
        keep = set(ids['video_semantics']['retain']); removed = set(ids['video_semantics']['delete'])
        result = {}
        for status in ('synced', 'superseded', 'pending', 'inflight'):
            rows = [r[0] for r in conn.execute('SELECT semantic_id FROM items WHERE status=?', (status,))]
            result[status] = dict(versions=len(rows), retained=sum(x in keep for x in rows),
                archived_only_after_dedup=sum(x in removed for x in rows),
                outside_snapshot=sum(x not in keep|removed for x in rows))
    if result != json.loads((OUT/'queue_dependency_audit.json').read_bytes()):
        raise ValueError('Watcher queue dependency drift')
    return result


class Watcher:
    """Native Windows process inspection without WMI or extra dependencies."""
    def __init__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.nt = ctypes.WinDLL('ntdll')
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.nt.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p,
                                                     wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        self.nt.NtSuspendProcess.argtypes = [wintypes.HANDLE]
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.handles = []

    def inspect(self, pid):
        handle = self.kernel.OpenProcess(0x1000 | 0x0800 | 0x0001 | 0x00100000, False, pid)
        if not handle:
            raise ValueError('Prepared watcher unavailable')
        class Unicode(ctypes.Structure):
            _fields_ = [('length', wintypes.USHORT), ('maximum', wintypes.USHORT), ('buffer', ctypes.c_void_p)]
        size = wintypes.ULONG()
        self.nt.NtQueryInformationProcess(handle, 60, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if self.nt.NtQueryInformationProcess(handle, 60, buf, len(buf), ctypes.byref(size)):
            raise ValueError('Cannot verify watcher command')
        value = Unicode.from_buffer(buf)
        command = ctypes.wstring_at(value.buffer, value.length//2)
        if 'watch_batch_sync.py' not in command or str(ROOT) not in command or ' -B ' not in command:
            raise ValueError('Watcher identity drift')
        self.handles.append((pid, handle, command))

    def pause(self):
        # The verified venv launcher and actual interpreter are the exact prepared tree.
        self.inspect(24508); self.inspect(25012)
        expected=subprocess.list2cmdline([str(ROOT/'backend/.venv-import/Scripts/pythonw.exe'),'-B',str(ROOT/'backend/watch_batch_sync.py')])
        if self.startup()!=expected:
            raise ValueError('Watcher startup configuration drift')
        if json.loads((WATCH/'watcher_process.json').read_bytes())['pid'] != 25012:
            raise ValueError('Watcher process record drift')
        save('watcher_before.json', dict(processes=[dict(pid=p,command=c) for p,h,c in self.handles],
            startup=self.startup(), script_sha256=hashlib.sha256((ROOT/'backend/watch_batch_sync.py').read_bytes()).hexdigest()))
        for pid, handle, command in reversed(self.handles):
            if self.nt.NtSuspendProcess(handle):
                raise ValueError('Watcher suspension failed')
        save('watcher_paused.json', dict(pids=[p for p,h,c in self.handles], paused=True))
        # The watcher holds its OS queue lock for its entire lifetime. Stop the
        # verified suspended tree to release it; preserve queue/startup/config.
        self.retire()

    @staticmethod
    def startup():
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as k:
            return winreg.QueryValueEx(k, 'AtaraxiaBatchSync')[0]

    def retire(self):
        for pid, handle, command in reversed(self.handles):
            if self.kernel.WaitForSingleObject(handle, 0) == 0:
                self.kernel.CloseHandle(handle)
                continue
            if not self.kernel.TerminateProcess(handle, 0):
                raise ValueError('Cannot retire old watcher')
            if self.kernel.WaitForSingleObject(handle, 10000) != 0:
                raise ValueError('Old watcher did not exit')
            self.kernel.CloseHandle(handle)


def exact(conn, original, manifest):
    data, catalog, signature = read_snapshot(conn, 'public')
    if signature != manifest['info']['schema_signature']:
        raise ValueError('Production schema/security/dependency drift')
    compare(original, data)
    for table in ORDER:
        if fingerprint(sorted(data[table], key=lambda r:key(r,table))) != fingerprint(sorted(original[table], key=lambda r:key(r,table))):
            raise ValueError('Production exact-row drift: ' + table)
    return catalog


def apply():
    original, desired, manifest, ids = integrity()
    queue_audit(ids)
    settings = DatabaseSettings.load()
    if settings.schema != 'public':
        raise ValueError('Prepared schema differs')
    # A fresh read-only check immediately precedes quiescence.
    with connect(settings) as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            exact(conn, original, manifest)
    watcher = Watcher()
    watcher.pause()
    sys.path.insert(0, str(ROOT/'annotation/src'))
    from ataraxia.distributed.common import lock
    committed = False
    with lock(WATCH/'queue.sqlite.worker.lock'):
        queue_audit(ids)
        with connect(settings) as conn:
            with conn.transaction():
                conn.execute("SET LOCAL statement_timeout='120s'")
                if not conn.execute('SELECT pg_try_advisory_xact_lock(193701,1140)').fetchone()[0]:
                    raise ValueError('Another writer holds advisory lock')
                conn.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(
                    sql.SQL(',').join(sql.Identifier('public',t) for t in ORDER)))
                exact(conn, original, manifest)
                queue_audit(ids)
                counts = {}
                for table in ('video_embeddings','video_semantics','affect_annotations','video_context'):
                    cur = conn.execute(sql.SQL('DELETE FROM {} WHERE id=ANY(%s)').format(sql.Identifier('public',table)), (ids[table]['delete'],))
                    counts[table] = cur.rowcount
                    if cur.rowcount != len(ids[table]['delete']):
                        raise ValueError('Unexpected affected count: '+table)
                for table in TARGETS:
                    conn.execute(sql.SQL('CREATE UNIQUE INDEX {} ON {}(video_id)').format(
                        sql.Identifier(table+'_one_video_physical_v1'), sql.Identifier('public',table)))
                conn.execute('CREATE UNIQUE INDEX video_semantics_identity_video_run_v1 ON public.video_semantics(id,video_id,run_id)')
                conn.execute('ALTER TABLE public.video_embeddings ADD CONSTRAINT video_embeddings_same_semantic_video_run_v1 '
                    'FOREIGN KEY(semantic_id,video_id,run_id) REFERENCES public.video_semantics(id,video_id,run_id) DEFERRABLE INITIALLY DEFERRED')
                conn.execute('SET CONSTRAINTS ALL IMMEDIATE')
                data, catalog, signature = read_snapshot(conn,'public')
                compare(desired,data)
                validation = validate(data,clean=False)
                if any(len(data[t]) != len({r['video_id'] for r in data[t]}) for t in TARGETS):
                    raise ValueError('Final 1:1 verification failed')
                if any(not r['convalidated'] for r in catalog['constraints'] if r['table_name'] in ORDER):
                    raise ValueError('Unvalidated FK/constraint')
                save('precommit.json', dict(exact_canonical_rows=True, validation=validation, deleted=counts,
                    original_schema_signature=manifest['info']['schema_signature'],final_schema_signature=signature))
            committed = True
        save('committed.json',dict(committed=True,at=datetime.now(timezone.utc).isoformat(),deleted=counts,validation=validation))
        # Old Python modules must never run again after physical deduplication.
    # Verify independently before resuming delivery.
    with connect(settings) as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            data,catalog,signature = read_snapshot(conn,'public')
            compare(desired,data)
            save('postcommit.json',dict(exact_canonical_rows=True,validation=validate(data,clean=False)))
    before=json.loads((REPORT/'watcher_before.json').read_bytes())
    if Watcher.startup()!=before['startup'] or hashlib.sha256((ROOT/'backend/watch_batch_sync.py').read_bytes()).hexdigest()!=before['script_sha256']:
        raise ValueError('Watcher startup configuration drift')
    child=subprocess.Popen([str(ROOT/'backend/.venv-import/Scripts/pythonw.exe'),'-B',str(ROOT/'backend/watch_batch_sync.py')],
        cwd=str(ROOT),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW)
    save('watcher_restart.json',dict(launcher_pid=child.pid,original_scope=1140,batch_size=10,max_wait_seconds=1800,startup_unchanged=True))
    print(json.dumps(dict(status='committed_watcher_restarted',deleted=counts,validation=validation)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-approved-plan', action='store_true',required=True)
    parser.parse_args()
    try:
        apply()
    except BaseException as error:
        save('stopped.json',dict(status='stopped',error_type=type(error).__name__,
            reason=str(error) if isinstance(error,ValueError) else 'Inspect local execution log; credentials omitted',
            committed=(REPORT/'committed.json').exists(),watcher_may_be_paused=(REPORT/'watcher_paused.json').exists()))
        print(json.dumps(dict(status='stopped',error_type=type(error).__name__)),flush=True)
        raise SystemExit(1)
