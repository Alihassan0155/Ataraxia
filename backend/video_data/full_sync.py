"""Approved 4,226-video synchronization: conditional S3 creation and SQL INSERT only.

Preparation freezes validated local entities. Apply rechecks live identities,
holds the legacy watcher's queue lock, and checkpoints each committed video.
No inference, UPDATE, DELETE, schema DDL, or placeholder annotation rows.
"""
import argparse
import base64
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

from .artifacts import (Reader, affect, canonical, categories, context_entity,
                        entity, fingerprint, video)
from .catalogue import ORDER, row_from_entity, validate, vector_array
from .config import DatabaseSettings, TABLES, connect
from .repository import compatibility, inspect_schema

ROOT = Path(__file__).resolve().parents[2]
AR = ROOT / 'annotation'
BUCKET = 'ataraxia-fyp-videos-068371986822-ap-south-1-an'
OWNER = '068371986822'
OUT = ROOT / 'backend/reports/full_sync_20261103'
WATCH_QUEUE = ROOT / 'backend/reports/automatic_batch_sync_20261018/queue.sqlite.worker.lock'


class Conflict(ValueError):
    """An unsafe identity/content change; must never be retried as a write."""


def now():
    return datetime.now(timezone.utc).isoformat()


def log(event, **details):
    print(json.dumps({'at': now(), 'event': event, **details}), flush=True)


def sha(path):
    h = hashlib.sha256()
    before = path.stat()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise Conflict('File changed during hashing')
    return h.hexdigest(), after.st_size, after.st_mtime_ns


def atomic(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def checkpoint():
    db = sqlite3.connect(OUT / 'checkpoint.sqlite', timeout=60)
    db.execute('PRAGMA synchronous=FULL')
    db.execute('''CREATE TABLE IF NOT EXISTS progress(
        video_id TEXT PRIMARY KEY, s3 TEXT, db TEXT, detail TEXT, updated_at TEXT)''')
    db.commit()
    return db


def mark(vid, stage, status, **detail):
    if stage not in ('s3', 'db'):
        raise ValueError('Invalid checkpoint stage')
    with checkpoint() as db:
        db.execute(f'''INSERT INTO progress(video_id,{stage},detail,updated_at) VALUES(?,?,?,?)
          ON CONFLICT(video_id) DO UPDATE SET {stage}=excluded.{stage},
          detail=excluded.detail,updated_at=excluded.updated_at''',
                   (vid, status, canonical(detail), now()))


def s3_client():
    # Reuse the previously verified provider profile; never expose credentials.
    sys.path.insert(0, str(ROOT / 'backend/reports/s3_dry_run_20261018/dependencies'))
    import boto3
    from botocore.config import Config
    os.environ.setdefault('AWS_EC2_METADATA_DISABLED', 'true')
    session = boto3.Session(profile_name='ataraxia', region_name='ap-south-1')
    config = Config(connect_timeout=10, read_timeout=180,
                    retries={'total_max_attempts': 4, 'mode': 'standard'}, max_pool_connections=12)
    identity = session.client('sts', config=config).get_caller_identity()
    if identity['Account'] != OWNER:
        raise Conflict('AWS owner changed')
    client = session.client('s3', config=config)
    head = client.head_bucket(Bucket=BUCKET, ExpectedBucketOwner=OWNER)
    region = head.get('BucketRegion') or head['ResponseMetadata']['HTTPHeaders'].get('x-amz-bucket-region')
    if region != 'ap-south-1':
        raise Conflict('S3 region changed')
    return client


def inventory(client):
    return {o['Key']: o for p in client.get_paginator('list_objects_v2').paginate(
        Bucket=BUCKET, ExpectedBucketOwner=OWNER) for o in p.get('Contents', [])}


def target_key(row):
    vid = row['assigned_id']
    prefixes = {'finevideo': 'FV', 'tiktok': 'TT_', 'youtube': 'YT_'}
    platform = row['platform']
    if platform not in prefixes or not vid.startswith(prefixes[platform]):
        raise Conflict('Platform/canonical ID mismatch')
    expected = row['source_id'] if platform == 'finevideo' else prefixes[platform] + row['source_id']
    if vid != expected:
        raise Conflict('Source/canonical ID mismatch')
    return f'videos/{platform}/{vid}.mp4'


def prepare():
    if (OUT / 'plan.json').exists():
        log('plan_exists_resume_only')
        return
    OUT.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader((ROOT / 'data/normalized/preprocessed_merged_v2/ready_metadata.csv').open(
        encoding='utf-8-sig', newline='')))
    ids = {r['assigned_id'] for r in rows}
    if len(rows) != 4226 or len(ids) != 4226:
        raise Conflict('Approved scope must be exactly 4,226 unique IDs')
    client = s3_client()
    objects = inventory(client)
    audit = json.loads((ROOT / 'backend/reports/s3_upload_20261018/final_audit.json').read_text())
    prior = {r['s3_key']: r for r in audit['records']}
    manifest = []

    def media(row):
        p = Path(row['file_path'])
        digest, size, mtime = sha(p)
        if digest != row['media_sha256'] or not size or size >= 5 * 1024 ** 3:
            raise Conflict('Local media hash/size conflict: ' + row['assigned_id'])
        key = target_key(row)
        alternatives = [key, row['assigned_id'] + '.mp4']
        if row['platform'] == 'youtube':
            alternatives.append(row['source_id'] + '.mp4')
        present = [k for k in alternatives if k in objects]
        if len(present) > 1:
            raise Conflict('Multiple S3 destinations for ' + row['assigned_id'])
        proof = None
        if present:
            key = present[0]
            obj = objects[key]
            if obj['Size'] != size:
                raise Conflict('Existing S3 size mismatch')
            old = prior.get(key)
            if old and old['sha256'] == digest and old['etag'] == obj['ETag']:
                proof = dict(kind='prior_full_download_sha256_same_etag', etag=obj['ETag'])
            else:
                h = hashlib.sha256()
                response = client.get_object(Bucket=BUCKET, Key=key, ExpectedBucketOwner=OWNER, IfMatch=obj['ETag'])
                with response['Body'] as body:
                    for chunk in iter(lambda: body.read(8 * 1024 * 1024), b''):
                        h.update(chunk)
                if h.hexdigest() != digest:
                    raise Conflict('Existing S3 content mismatch')
                proof = dict(kind='full_download_sha256', etag=obj['ETag'])
        return dict(video_id=row['assigned_id'], path=str(p.resolve()), sha256=digest,
                    size=size, mtime_ns=mtime, key=key, existing=bool(present), proof=proof)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, result in enumerate(pool.map(media, rows), 1):
            manifest.append(result)
            if i % 500 == 0:
                log('media_validated', count=i)
    reader = Reader(AR)
    entities = {t: {} for t in TABLES}
    issues = []

    def add(item):
        dest = entities[item['table']]
        old = dest.get(item['key'])
        if old and canonical(old) != canonical(item):
            raise Conflict('Local immutable identity collision')
        dest[item['key']] = item

    # Genuine contexts exist independently of annotations; no invented annotation stages.
    for row in rows:
        vid = row['assigned_id']
        item = video(vid, row)
        m = manifest[len(entities['videos'])]
        item['columns'].update(media_uri=f's3://{BUCKET}/{m["key"]}', availability='s3_verified')
        add(item)
        ctx = json.loads(Path(row['context_path']).read_bytes())
        if ctx.get('video_id') != vid:
            raise Conflict('Context identity mismatch')
        tr = Path(row['transcript_path']).read_text(encoding='utf-8-sig')
        fp = ROOT / 'data/normalized/preprocessed_merged_v2/acoustic_features' / f'{vid}.json'
        features = json.loads(fp.read_bytes()) if fp.exists() else None
        add(context_entity(vid, row, ctx, tr, features))
    rowmap = {r['assigned_id']: r for r in rows}
    for base in ('runs', 'outputs', 'pilot_50_reels_30h', 'heldout_50_evaluation'):
        for p in sorted((AR / base).rglob('annotations.jsonl')):
            raw = p.read_bytes()
            lines = raw.splitlines()
            if raw and not raw.endswith(b'\n'):
                lines = lines[:-1]
                issues.append(dict(path=str(p.relative_to(AR)), reason='partial_trailing_line_deferred'))
            for number, line in enumerate(lines, 1):
                try:
                    ann = json.loads(line)
                    reader.api[-1].model_validate(ann)
                    vid = ann['video_id']
                    if vid not in ids:
                        raise ValueError('Outside approved IDs')
                except Exception as error:
                    issues.append(dict(path=str(p.relative_to(AR)), line=number, reason=type(error).__name__))
                    continue
                origin = reader.affect_run(p)
                add(origin)
                add(affect(vid, ann, origin['key']))
    cache = {}
    paths = sorted((AR / 'semantic_pipeline/runs').glob('*/videos/*/*/record.json'))
    for i, p in enumerate(paths, 1):
        run = p.parents[3]
        if run not in cache:
            cache[run] = (reader.api[1](run / 'frozen.json'), reader.api[3](run))
        # Fail closed on a purported completed bundle that cannot be validated.
        for item in reader.semantic_bundle(run, p, *cache[run]):
            if item['table'] == 'videos':
                continue  # Frozen metadata is provenance, never overwrite source metadata.
            add(item)
        statepath = p.parent / 'state.json'
        if statepath.exists():
            state = json.loads(statepath.read_bytes())
            if state.get('status') == 'complete':
                rid = fingerprint(['semantic', run.relative_to(AR).as_posix(), cache[run][0]['fingerprint']])
                payload = dict(video_id=p.parent.parent.name, source_fingerprint=p.parent.name, state=state)
                add(entity('processing_jobs', fingerprint([rid, payload]), payload,
                           video_id=payload['video_id'], run_id=rid, stage=state.get('stage', 'complete'),
                           status='complete', attempts=int(state.get('attempts', 0))))
        if i % 500 == 0:
            log('bundles_validated', count=i)
    for item in categories(AR / 'semantic_pipeline/configs/taxonomy.json'):
        add(item)
    hashes = {}
    for t in ORDER:
        path = OUT / (t + '.jsonl')
        path.write_text(''.join(canonical(e) + '\n' for e in entities[t].values()), encoding='utf-8')
        hashes[path.name] = sha(path)[0]
    atomic(OUT / 'media.json', manifest)
    hashes['media.json'] = sha(OUT / 'media.json')[0]
    atomic(OUT / 'issues.json', issues)
    plan = dict(version=1, created_at=now(), scope=sorted(ids), files=hashes,
                local_entities={t: len(v) for t, v in entities.items()},
                missing_s3=sum(not m['existing'] for m in manifest),
                upload_bytes=sum(m['size'] for m in manifest if not m['existing']), issues=len(issues))
    atomic(OUT / 'plan.json', plan)
    log('prepared', **{k: v for k, v in plan.items() if k not in ('scope', 'files')})


def load_plan():
    plan = json.loads((OUT / 'plan.json').read_bytes())
    for name, expected in plan['files'].items():
        if sha(OUT / name)[0] != expected:
            raise Conflict('Frozen plan changed: ' + name)
    entities = {t: [json.loads(l) for l in (OUT / (t + '.jsonl')).read_bytes().splitlines()] for t in ORDER}
    return plan, json.loads((OUT / 'media.json').read_bytes()), entities


def read_db(conn):
    result = {}
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        for t in ORDER:
            cur = conn.execute('SELECT * FROM public.' + t)
            result[t] = [dict(zip([c.name for c in cur.description], r)) for r in cur.fetchall()]
    validate(result, clean=False)
    return result


def same(expected, actual):
    import numpy as np
    for k, v in expected.items():
        if k == 'embedding':
            if not np.array_equal(vector_array(v), vector_array(actual[k])):
                return False
        elif actual.get(k) != v:
            return False
    return True


def insert(conn, item, vector_schema):
    if item['table'] in ('videos','video_context','affect_annotations','video_semantics','video_embeddings','interest_categories'):
        from .physical_writer_guard import require_legacy_disabled
        require_legacy_disabled(conn)
    from psycopg import sql
    from psycopg.types.json import Jsonb
    t = item['table']
    key = 'video_id' if t == 'videos' else 'id'
    table = sql.Identifier('public', t)
    cur = conn.execute(sql.SQL('SELECT * FROM {} WHERE {}=%s').format(table, sql.Identifier(key)), (item['key'],))
    row = cur.fetchone()
    expected = row_from_entity(item)
    if row:
        actual = dict(zip([c.name for c in cur.description], row))
        if t == 'videos':
            if actual['media_sha256'] != expected['media_sha256'] or actual['media_uri'] != expected['media_uri']:
                raise Conflict('Existing video storage differs: ' + item['key'])
            return False  # Existing metadata remains entirely authoritative.
        if not same(expected, actual):
            raise Conflict('Immutable row collision: ' + t + '/' + item['key'])
        return False
    columns = list(expected)
    values, holders = [], []
    for name in columns:
        value = expected[name]
        if name == 'embedding':
            values.append('[' + ','.join(str(float(v)) for v in value) + ']')
            holders.append(sql.SQL('%s::{}').format(sql.Identifier(vector_schema, 'vector')))
        else:
            values.append(Jsonb(value) if isinstance(value, (list, dict)) else value)
            holders.append(sql.Placeholder())
    conn.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
        table, sql.SQL(',').join(map(sql.Identifier, columns)), sql.SQL(',').join(holders)), values)
    return True


def insert_batch(conn, items, vector_schema):
    """Recheck all batch identities under short table locks, pipeline INSERTs."""
    from .physical_writer_guard import require_legacy_disabled
    require_legacy_disabled(conn)
    from psycopg import sql
    from psycopg.types.json import Jsonb
    counts = Counter()
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(
            sql.SQL(',').join(sql.Identifier('public', t) for t in ORDER)))
        for t in ORDER:
            group = [e for e in items if e['table'] == t]
            if not group:
                continue
            key = 'video_id' if t == 'videos' else 'id'
            table = sql.Identifier('public', t)
            cur = conn.execute(sql.SQL('SELECT * FROM {} WHERE {}=ANY(%s)').format(
                table, sql.Identifier(key)), ([e['key'] for e in group],))
            old = {r[key]: r for r in (dict(zip([c.name for c in cur.description], values))
                                       for values in cur.fetchall())}
            pending = []
            for e in group:
                row = row_from_entity(e)
                actual = old.get(e['key'])
                if actual:
                    if t == 'videos':
                        if (actual['media_sha256'], actual['media_uri']) != (row['media_sha256'], row['media_uri']):
                            raise Conflict('Existing video mapping differs: ' + e['key'])
                    elif not same(row, actual):
                        raise Conflict('Immutable identity collision: ' + t + '/' + e['key'])
                else:
                    pending.append(row)
            if not pending:
                continue
            columns = list(pending[0])
            if any(list(r) != columns for r in pending):
                raise Conflict('Inconsistent columns in batch')
            holders = [sql.SQL('%s::{}').format(sql.Identifier(vector_schema, 'vector'))
                       if k == 'embedding' else sql.Placeholder() for k in columns]
            values = []
            for row in pending:
                values.append([
                    '[' + ','.join(str(float(v)) for v in row[k]) + ']' if k == 'embedding'
                    else Jsonb(row[k]) if isinstance(row[k], (list, dict)) else row[k]
                    for k in columns])
            query = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(table,
                sql.SQL(',').join(map(sql.Identifier, columns)), sql.SQL(',').join(holders))
            with conn.cursor() as cursor:
                cursor.executemany(query, values)
            counts[t] += len(pending)
    return counts


def verify_s3(client, m, allow_create=False):
    from botocore.exceptions import ClientError
    params = dict(Bucket=BUCKET, Key=m['key'], ExpectedBucketOwner=OWNER)
    try:
        head = client.head_object(**params, ChecksumMode='ENABLED')
    except ClientError as error:
        if error.response['Error']['Code'] not in ('404', 'NoSuchKey', 'NotFound'):
            raise
        if not allow_create:
            raise Conflict('Expected S3 object disappeared') from error
        p = Path(m['path'])
        digest, size, _ = sha(p)
        if digest != m['sha256'] or size != m['size']:
            raise Conflict('Local video changed before upload')
        with p.open('rb') as stream:
            try:
                client.put_object(**params, Body=stream, ContentType='video/mp4', IfNoneMatch='*',
                                  ChecksumSHA256=base64.b64encode(bytes.fromhex(digest)).decode(),
                                  Metadata={'canonical-video-id': m['video_id'], 'sha256': digest})
            except ClientError as put_error:
                if put_error.response['Error']['Code'] not in ('PreconditionFailed', '412'):
                    raise
        head = client.head_object(**params, ChecksumMode='ENABLED')
    if head['ContentLength'] != m['size']:
        raise Conflict('S3 size conflict')
    checksum = base64.b64encode(bytes.fromhex(m['sha256'])).decode()
    if head.get('ChecksumSHA256') == checksum:
        return dict(etag=head['ETag'], proof='s3_full_object_sha256')
    if m.get('proof') and head['ETag'] == m['proof']['etag']:
        return dict(etag=head['ETag'], proof=m['proof']['kind'])
    # Unknown/racing object: stream and verify instead of trusting custom metadata.
    h = hashlib.sha256()
    response = client.get_object(**params, IfMatch=head['ETag'])
    with response['Body'] as body:
        for b in iter(lambda: body.read(8 * 1024 * 1024), b''):
            h.update(b)
    if h.hexdigest() != m['sha256']:
        raise Conflict('S3 content conflict')
    return dict(etag=head['ETag'], proof='full_download_sha256')


def baseline(conn, data):
    path = OUT / 'baseline.json'
    if path.exists():
        return json.loads(path.read_bytes())
    # Row JSON includes timestamps and vectors: every existing byte/value must survive.
    rows = {}
    for t in ORDER:
        key = 'video_id' if t == 'videos' else 'id'
        rows[t] = dict(conn.execute(f'SELECT {key},md5(row_to_json(t)::text) FROM public.{t} t').fetchall())
    result = dict(at=now(), rows=rows, counts={t: len(v) for t, v in data.items()},
                  schema_fingerprint=fingerprint(inspect_schema(conn)))
    atomic(path, result)
    return result


def apply(workers=8):
    from .physical_writer_guard import require_legacy_disabled
    with connect(DatabaseSettings.load()) as guard_conn:
        require_legacy_disabled(guard_conn)
    from psycopg import sql
    plan, media, entities = load_plan()
    sys.path.insert(0, str(AR / 'src'))
    from ataraxia.distributed.common import lock
    failures = []
    client = s3_client()
    # OS lock proves the old watcher is stopped; held through all remote work.
    with lock(WATCH_QUEUE), lock(OUT / 'worker.lock'), connect(DatabaseSettings.load()) as conn:
        inv = inspect_schema(conn)
        if not compatibility(inv, 'public', {t: t for t in TABLES})['compatible']:
            raise Conflict('Schema changed/incompatible')
        vector_schema = next(e['schema'] for e in inv['extensions'] if e['name'] == 'vector')
        data = read_db(conn)
        baseline(conn, data)
        live_ids = {v['video_id'] for v in data['videos']}
        if not live_ids.issubset(set(plan['scope'])):
            raise Conflict('Unexpected remote canonical IDs')
        byvideo = defaultdict(list)
        shared = []
        maps = {t: {r['video_id'] if t == 'videos' else r['id']: r for r in data[t]} for t in ORDER}
        preflight = Counter()
        for t in ORDER:
            for e in entities[t]:
                expected = row_from_entity(e)
                old = maps[t].get(e['key'])
                if old:
                    if t == 'videos':
                        if old['media_sha256'] != expected['media_sha256'] or old['media_uri'] != expected['media_uri']:
                            raise Conflict('Existing video mapping conflict')
                    elif not same(expected, old):
                        raise Conflict('Preflight immutable collision: ' + t)
                else:
                    preflight[t] += 1
                if 'video_id' in e['columns'] or t == 'videos':
                    byvideo[e['key'] if t == 'videos' else e['columns']['video_id']].append(e)
                else:
                    shared.append(e)
        atomic(OUT / 'preflight.json', dict(at=now(), inserts=dict(preflight), updates=0, deletes=0))
        log('preflight', inserts=dict(preflight), updates=0)
        # Same advisory lock as legacy writer, held for the entire synchronization.
        if not conn.execute('SELECT pg_try_advisory_lock(193701,1140)').fetchone()[0]:
            raise Conflict('Another remote batch writer is active')
        shared_insertions = Counter()
        with conn.transaction():
            for e in shared:
                if insert(conn, e, vector_schema):
                    shared_insertions[e['table']] += 1
        ready = set()
        stop = threading.Event()

        def upload_one(m):
            if stop.is_set():
                return None
            for attempt in range(4):
                try:
                    proof = verify_s3(client, m, allow_create=not m['existing'])
                    mark(m['video_id'], 's3', 'verified', **proof)
                    return m['video_id']
                except Conflict:
                    mark(m['video_id'], 's3', 'conflict')
                    raise
                except Exception as error:
                    if attempt == 3:
                        mark(m['video_id'], 's3', 'failed', error_type=type(error).__name__)
                        raise
                    time.sleep(2 ** attempt)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(upload_one, m): m['video_id'] for m in media}
            for i, future in enumerate(as_completed(futures), 1):
                vid = futures[future]
                try:
                    result = future.result()
                    if result:
                        ready.add(result)
                except Exception as error:
                    failures.append(dict(video_id=vid, stage='s3', error_type=type(error).__name__))
                    log('video_failed', **failures[-1])
                if i % 50 == 0:
                    log('s3_progress', checked=i, verified=len(ready), failed=len(failures))
        # Resume in bounded 50-video transactions; isolate any unsafe batch.
        inserted = Counter(shared_insertions)
        ordered = sorted(ready)
        for offset in range(0, len(ordered), 50):
            batch = ordered[offset:offset+50]
            for attempt in range(4):
                try:
                    counts = insert_batch(conn, [e for vid in batch for e in byvideo[vid]], vector_schema)
                    inserted.update(counts)
                    for vid in batch:
                        mark(vid, 'db', 'verified')
                    break
                except Conflict:
                    for vid in batch:
                        try:
                            counts = insert_batch(conn, byvideo[vid], vector_schema)
                            inserted.update(counts)
                            mark(vid, 'db', 'verified')
                        except Exception as error:
                            mark(vid, 'db', 'conflict', error_type=type(error).__name__)
                            failures.append(dict(video_id=vid, stage='db', error_type=type(error).__name__))
                    break
                except Exception as error:
                    if attempt == 3:
                        for vid in batch:
                            mark(vid, 'db', 'failed', error_type=type(error).__name__)
                            failures.append(dict(video_id=vid, stage='db', error_type=type(error).__name__))
                    else:
                        time.sleep(2 ** attempt)
                        if conn.closed or conn.broken:
                            conn = connect(DatabaseSettings.load())
                            if not conn.execute('SELECT pg_try_advisory_lock(193701,1140)').fetchone()[0]:
                                raise Conflict('Remote writer appeared during reconnect')
            log('db_progress', checked=offset+len(batch), inserted=dict(inserted), failed=len(failures))
        atomic(OUT / 'execution.json', dict(at=now(), inserted=dict(inserted), failures=failures,
                                            s3_verified=len(ready), updates=0, deletes=0))
    return verify()


def verify():
    plan, media, entities = load_plan()
    baseline_data = json.loads((OUT / 'baseline.json').read_bytes())
    client = s3_client()
    objects = inventory(client)
    s3_failures = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(verify_s3, client, m): m['video_id'] for m in media}
        for i, f in enumerate(as_completed(futures), 1):
            try:
                f.result()
            except Exception as error:
                s3_failures.append(dict(video_id=futures[f], error_type=type(error).__name__))
            if i % 500 == 0:
                log('s3_final_verification', checked=i)
    with connect(DatabaseSettings.load()) as conn:
        data = read_db(conn)
        schema_unchanged = baseline_data['schema_fingerprint'] == fingerprint(inspect_schema(conn))
        preserved = {}
        for t in ORDER:
            key = 'video_id' if t == 'videos' else 'id'
            actual = dict(conn.execute(f'SELECT {key},md5(row_to_json(t)::text) FROM public.{t} t').fetchall())
            preserved[t] = all(actual.get(k) == v for k, v in baseline_data['rows'][t].items())
    maps = {t: {r['video_id'] if t == 'videos' else r['id']: r for r in data[t]} for t in ORDER}
    missing = {t: [e['key'] for e in entities[t] if e['key'] not in maps[t]] for t in ORDER}
    mismatches = []
    for t in ORDER:
        for e in entities[t]:
            actual = maps[t].get(e['key'])
            if actual and t != 'videos' and not same(row_from_entity(e), actual):
                mismatches.append(dict(table=t, id=e['key']))
    full = {e['video_id'] for e in data['video_embeddings']}
    ann = {a['video_id'] for a in data['affect_annotations']}
    contexts = {c['video_id'] for c in data['video_context']}
    result = dict(at=now(), scope=len(plan['scope']), s3_objects=len(objects),
                  s3_verified=len(media)-len(s3_failures), s3_failures=s3_failures,
                  database_validation=validate(data, clean=False), existing_rows_preserved=preserved,
                  missing_entities={t: len(v) for t, v in missing.items()}, mismatches=mismatches,
                  fully_annotated=len(full), partially_annotated=len(ann-full),
                  unannotated=len(set(plan['scope'])-ann-full), contexts_unique=len(contexts),
                  annotation_models=dict(Counter(a['model'] for a in data['affect_annotations'])),
                  inserted_since_baseline={t: len(data[t])-baseline_data['counts'][t] for t in ORDER},
                  updates=0, deletes=0, schema_changes=0, schema_unchanged=schema_unchanged)
    atomic(OUT / 'remaining.json', missing)
    atomic(OUT / 'verification.json', result)
    log('verified', **result)
    return 0 if not s3_failures and not mismatches and not any(missing.values()) and all(preserved.values()) and schema_unchanged else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'apply', 'verify'])
    parser.add_argument('--approved-all-4226', action='store_true')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    if args.action == 'apply' and not args.approved_all_4226:
        parser.error('Explicit --approved-all-4226 required')
    try:
        if args.action == 'prepare':
            prepare()
            return 0
        return apply(args.workers) if args.action == 'apply' else verify()
    except Exception as error:
        log('stopped', error_type=type(error).__name__,
            reason=str(error) if isinstance(error, Conflict) else 'See stage checkpoints; driver output withheld')
        return 1


if __name__ == '__main__':
    sys.exit(main())
