"""Local-only backup restore, rollback and canonical-update rehearsal.

Never loads database settings or connects to production. Uses a new dedicated
localhost PostgreSQL cluster; original production rows exist only in backup.
"""
from collections import Counter
import json
import copy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from .catalogue import ORDER, load_package, validate
from .physical_dedup_plan import BIN, OUT, TARGETS, save
from .rehearse_catalogue import compare
from .artifacts import fingerprint
from .canonical_update_proposal import upsert_bundle, source_version_matches_active

DATABASE = 'physical_dedup_rehearsal_v2'


def connection():
    c = psycopg.connect(host='127.0.0.1', port=55441, user='postgres', dbname=DATABASE,
                       sslmode='disable', connect_timeout=5, autocommit=True)
    address, database = c.execute('SELECT inet_server_addr(),current_database()').fetchone()
    if str(address) != '127.0.0.1' or database != DATABASE:
        c.close()
        raise ValueError('Dedicated localhost fixture required')
    return c


def rows(c):
    result = {}
    for t in ORDER:
        cur = c.execute('SELECT * FROM public.' + t)
        result[t] = [dict(zip([d.name for d in cur.description],
                              [v.astimezone(timezone.utc).isoformat() if isinstance(v, datetime) else v for v in r]))
                     for r in cur.fetchall()]
    return result


def start():
    data = OUT / 'local_pgdata'
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    if not (data / 'PG_VERSION').exists():
        result = subprocess.run([str(BIN / 'initdb.exe'), '-D', str(data), '-U', 'postgres',
                                 '-A', 'trust', '--no-locale', '-E', 'UTF8'], capture_output=True, creationflags=flags)
        (OUT / 'local_init.log').write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise ValueError('Local initdb failed; inspect local_init.log')
    status = subprocess.run([str(BIN / 'pg_ctl.exe'), '-D', str(data), 'status'], capture_output=True, creationflags=flags)
    if status.returncode:
        # Real file handles avoid waiting for EOF on pipes inherited by the
        # Windows PostgreSQL background service after pg_ctl has returned.
        with (OUT / 'local_start.log').open('ab') as startup_log:
            result = subprocess.run([str(BIN / 'pg_ctl.exe'), '-D', str(data), '-l', str(OUT / 'local_server.log'),
                                     '-o', '-p 55441 -h 127.0.0.1', '-w', 'start'],
                                    stdout=startup_log, stderr=subprocess.STDOUT, creationflags=flags)
        if result.returncode:
            raise ValueError('Local server failed to start')
    with psycopg.connect(host='127.0.0.1', port=55441, user='postgres', dbname='postgres',
                         sslmode='disable', autocommit=True) as c:
        if c.execute('SELECT 1 FROM pg_database WHERE datname=%s', (DATABASE,)).fetchone():
            raise ValueError('Rehearsal database already exists; retained for inspection, never dropped automatically')
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(DATABASE)))
    with connection() as c:
        c.execute('CREATE SCHEMA extensions')
        c.execute("CREATE EXTENSION vector WITH SCHEMA extensions VERSION '0.8.2'")
    result = subprocess.run([str(BIN / 'pg_restore.exe'), '--no-owner', '--no-privileges', '--exit-on-error',
                             '-h', '127.0.0.1', '-p', '55441', '-U', 'postgres', '-d', DATABASE,
                             str(OUT / 'native_backup/video_tables.dump')], capture_output=True, creationflags=flags)
    (OUT / 'native_restore.log').write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise ValueError('Native restore failed; inspect native_restore.log')


def deduplicate(c, identities):
    for t in ('video_embeddings', 'video_semantics', 'affect_annotations', 'video_context'):
        c.execute(sql.SQL('DELETE FROM {} WHERE id=ANY(%s)').format(sql.Identifier('public', t)),
                  (identities[t]['delete'],))
    for t in TARGETS:
        c.execute(sql.SQL('CREATE UNIQUE INDEX {} ON {}(video_id)').format(
            sql.Identifier(t + '_one_video_physical_v1'), sql.Identifier('public', t)))
    c.execute('CREATE UNIQUE INDEX video_semantics_identity_video_run_v1 ON public.video_semantics(id,video_id,run_id)')
    c.execute('ALTER TABLE public.video_embeddings ADD CONSTRAINT video_embeddings_same_semantic_video_run_v1 '
              'FOREIGN KEY(semantic_id,video_id,run_id) REFERENCES public.video_semantics(id,video_id,run_id) '
              'DEFERRABLE INITIALLY DEFERRED')


def main():
    original, _ = load_package(OUT / 'backup')
    desired, _ = load_package(OUT / 'canonical')
    ids = json.loads((OUT / 'identities.json').read_bytes())
    start()
    result = dict(production_writes=0, localhost='127.0.0.1:55441', database=DATABASE,
                  restoration_owner_acl_substitution='Local --no-owner --no-privileges; production catalog/grants preserved in backup/catalog.json')
    with connection() as c:
        compare(original, rows(c))
        result['native_restore_matches_every_original_row'] = True
        try:
            with c.transaction():
                deduplicate(c, ids)
                compare(desired, rows(c))
                raise RuntimeError('intentional rollback')
        except RuntimeError as e:
            if str(e) != 'intentional rollback':
                raise
        compare(original, rows(c))
        result['rollback_preserves_all_rows'] = True
        with c.transaction():
            deduplicate(c, ids)
        compare(desired, rows(c))
        result['dedup_matches_exact_retained_ids_and_values'] = True
        result['validation'] = validate(rows(c), clean=False)
        # Idempotent repeated retention deletes zero rows. Existing uniqueness
        # is checked rather than recreating indexes during a retry.
        with c.transaction():
            deleted = sum(c.execute(sql.SQL('DELETE FROM {} WHERE id=ANY(%s)').format(
                sql.Identifier('public', t)), (ids[t]['delete'],)).rowcount for t in TARGETS)
        result['repeat_deletes_zero'] = deleted == 0
        guards = {}
        for t in TARGETS:
            try:
                with c.transaction():
                    columns = [col for col in next(iter(desired[t])).keys() if col != 'id']
                    c.execute(sql.SQL("INSERT INTO {} ({}) SELECT 'fixture_duplicate_id',{} FROM {} LIMIT 1").format(
                        sql.Identifier('public', t),
                        sql.SQL(',').join(map(sql.Identifier, ['id'] + columns)),
                        sql.SQL(',').join(map(sql.Identifier, columns)),
                        sql.Identifier('public', t)))
            except psycopg.errors.UniqueViolation:
                guards[t] = True
            else:
                raise AssertionError('Expected unique(video_id) rejection')
        result['unique_video_id_enforced'] = guards
        # True production-shaped fixture, synthetic version change ONLY locally.
        maps = {t: {r['id']: r for r in desired[t]} for t in TARGETS}
        sem = copy.deepcopy(desired['video_semantics'][0])
        vid = sem['video_id']
        bundle = { 'video_semantics': sem,
                   'video_context': copy.deepcopy(maps['video_context'][sem['context_id']]),
                   'affect_annotations': copy.deepcopy(maps['affect_annotations'][sem['affect_id']]),
                   'video_embeddings': copy.deepcopy(next(e for e in desired['video_embeddings'] if e['semantic_id'] == sem['id'])) }
        original_semantic_id = sem['id']
        from .catalogue import timestamp
        sem['payload']['completed_at'] = (timestamp(sem['payload']['completed_at']) + timedelta(seconds=1)).isoformat()
        sem['content_hash'] = fingerprint(sem['payload'])
        for t, r in bundle.items():
            r['id'] = 'fixture_source_' + t
        sem.update(context_id=bundle['video_context']['id'], affect_id=bundle['affect_annotations']['id'])
        bundle['video_embeddings']['semantic_id'] = sem['id']
        from .catalogue import vector_array
        bundle['video_embeddings']['embedding'] = vector_array(bundle['video_embeddings']['embedding']).tolist()
        run = copy.deepcopy(next(r for r in desired['processing_runs'] if r['id'] == sem['run_id']))
        run['id'] = 'fixture_future_production_run'
        run['name'] = 'fixture_future_production_run'
        run['payload']['name'] = run['name']
        run['content_hash'] = fingerprint(run['payload'])
        sem['run_id'] = run['id']
        bundle['video_embeddings']['run_id'] = run['id']
        def entities():
            source = dict(bundle, processing_runs=run)
            return [dict(table=t, key=r['id'], payload=r['payload'], content_hash=r['content_hash'],
                         columns={k:v for k,v in r.items() if k not in ('id','payload','content_hash','created_at')})
                    for t,r in source.items()]
        archive = OUT / 'local_future_version_archive'
        # Fail after first canonical SQL update; entire operation must roll back.
        from unittest.mock import patch
        from . import canonical_update_proposal as writer
        real = writer.replace_row
        def fail_after_one(*args, **kwargs):
            real(*args, **kwargs)
            raise RuntimeError('injected update failure')
        try:
            with patch.object(writer, 'replace_row', fail_after_one):
                upsert_bundle(c, entities(), archive)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Expected injected failure')
        compare(desired, rows(c))
        result['future_update_rollback_preserves_canonical_rows'] = True
        assert upsert_bundle(c, entities(), archive) == 'canonical_updated'
        assert upsert_bundle(c, entities(), archive) == 'unchanged'
        after_update = rows(c)
        assert all(len(after_update[t]) == len(desired[t]) + (1 if t == 'processing_runs' else 0) for t in ORDER)
        assert next(s for s in after_update['video_semantics'] if s['video_id']==vid)['id'] == original_semantic_id
        validate(after_update, clean=False)
        result['future_complete_update_is_atomic_idempotent_and_preserves_ids'] = True
        active = next(s for s in after_update['video_semantics'] if s['video_id'] == vid)
        assert source_version_matches_active(sem, active)
        assert sem['id'] != active['id']
        stale = copy.deepcopy(sem)
        stale['content_hash'] = 'different-historical-version'
        assert not source_version_matches_active(stale, active)
        result['watcher_reconciliation_uses_source_version_not_destination_id'] = True
        partial = [e for e in entities() if e['table'] in ('video_context','affect_annotations')]
        assert upsert_bundle(c, partial, archive) == 'partial_cannot_replace_complete'
        compare(after_update, rows(c))
        result['partial_cannot_overwrite_complete'] = True
        sem['payload']['completed_at'] = (timestamp(sem['payload']['completed_at']) - timedelta(seconds=2)).isoformat()
        sem['content_hash'] = fingerprint(sem['payload'])
        assert upsert_bundle(c, entities(), archive) == 'older_complete_ignored'
        result['older_complete_replay_ignored'] = True
        assert list(archive.glob('*.json'))
        result['replaced_version_durably_archived_before_upsert'] = True
        try:
            with c.transaction():
                c.execute('UPDATE public.video_embeddings SET video_id=%s WHERE semantic_id=%s',
                          (next(r['video_id'] for r in desired['videos'] if r['video_id'] not in {e['video_id'] for e in desired['video_embeddings']}), original_semantic_id))
                c.execute('SET CONSTRAINTS ALL IMMEDIATE')
        except psycopg.errors.ForeignKeyViolation:
            result['cross_video_embedding_link_rejected'] = True
        else:
            raise AssertionError('Expected composite FK rejection')
        # Current legacy watcher preflight remains valid; its immutable insert
        # path is deliberately not activated against the deduplicated fixture.
        result['watcher_new_writer_required_before_restart'] = True
    save(OUT / 'rehearsal.json', result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
