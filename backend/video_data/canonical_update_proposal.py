"""Canonical upserts for the explicitly approved physical-1:1 migration.

No implicit production connection factory.
Caller supplies a connection, validated Reader bundle and durable archive path.
Stable destination IDs preserve FKs; original source artifact IDs stay archived.
"""
import json
import os
from pathlib import Path

from psycopg import sql
from psycopg.types.json import Jsonb

from .artifacts import fingerprint
from .catalogue import ORDER, row_from_entity, timestamp, validate
from .full_sync import insert, same
from .physical_dedup_plan import AFFECT, SEMANTIC, EMBEDDING, REVISION, TARGETS


def archive_before_replace(directory, vid, old, incoming):
    """Durable write-once recovery evidence exists BEFORE updating DB records."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = dict(video_id=vid, replaced=old, incoming=incoming)
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str,
                     allow_nan=False, separators=(',', ':')).encode()
    name = __import__('hashlib').sha256(raw).hexdigest() + '.json'
    path = directory / name
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Archive identity collision')
    else:
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return path


def replace_row(conn, table, old, candidate, vector_schema):
    """Upsert by video_id with a stable canonical ID; never write video metadata."""
    if table not in TARGETS:
        raise ValueError('Only canonical related rows may be upserted')
    columns = list(candidate)
    holders, values = [], []
    for col in columns:
        v = candidate[col]
        if col == 'embedding':
            holders.append(sql.SQL('%s::{}').format(sql.Identifier(vector_schema, 'vector')))
            values.append('[' + ','.join(str(float(x)) for x in v) + ']')
        else:
            holders.append(sql.Placeholder())
            values.append(Jsonb(v) if isinstance(v, (dict, list)) else v)
    table_sql = sql.Identifier('public', table)
    updates = sql.SQL(',').join(sql.SQL('{}=EXCLUDED.{}').format(sql.Identifier(k), sql.Identifier(k))
                               for k in columns if k not in ('id', 'video_id', 'created_at'))
    conn.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT(video_id) DO UPDATE SET {}').format(
        table_sql, sql.SQL(',').join(map(sql.Identifier, columns)), sql.SQL(',').join(holders), updates), values)


def upsert_bundle(conn, items, archive_dir):
    """Apply a validated full bundle atomically, or a production-only partial.

No context/affect partial may replace any existing complete semantic bundle.
Newer complete versions replace all four related rows together. Stable IDs
may differ from incoming Reader artifact IDs; archive preserves that mapping.
"""
    source = {e['table']: e for e in items if e['table'] in TARGETS}
    if not source:
        return 'no_production_records'
    video_ids = {e['columns']['video_id'] for e in source.values()}
    if len(video_ids) != 1:
        raise ValueError('Cross-video input')
    vid = next(iter(video_ids))
    complete = 'video_semantics' in source and 'video_embeddings' in source
    if ('video_semantics' in source) != ('video_embeddings' in source):
        raise ValueError('Semantic/embedding stages must be supplied together')
    incoming = {t: row_from_entity(e) for t, e in source.items()}
    if incoming.get('affect_annotations', {}).get('model', AFFECT) != AFFECT:
        return 'research_model_preserved_in_source_archive_only'
    if complete:
        if set(incoming) != set(TARGETS):
            raise ValueError('A complete bundle requires context, affect, semantic and embedding')
        s, e, a, ctx = (incoming[t] for t in ('video_semantics', 'video_embeddings', 'affect_annotations', 'video_context'))
        if (s['payload']['status'] != 'complete' or s['payload']['extractor']['checkpoint'] != SEMANTIC
                or e['model'] != EMBEDDING or e['revision'] != REVISION
                or a['model'] != AFFECT or s['affect_id'] != a['id'] or s['context_id'] != ctx['id']):
            raise ValueError('Not an approved valid production bundle')
    with conn.transaction():
        if not conn.execute('SELECT pg_try_advisory_xact_lock(193701,1140)').fetchone()[0]:
            raise ValueError('Concurrent writer')
        conn.execute('SET LOCAL lock_timeout=\'5s\'')
        conn.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(
            sql.SQL(',').join(sql.Identifier('public', t) for t in ORDER)))
        data = {}
        for t in ORDER:
            cur = conn.execute('SELECT * FROM public.' + t)
            data[t] = [dict(zip([d.name for d in cur.description], r)) for r in cur.fetchall()]
        validate(data, clean=False)
        old = {t: next((r for r in data[t] if r['video_id'] == vid), None) for t in TARGETS}
        if not any(v['video_id'] == vid for v in data['videos']):
            raise ValueError('Canonical video must already exist')
        existing = old['video_semantics']
        if existing and not complete:
            return 'partial_cannot_replace_complete'
        if existing and complete:
            before = timestamp(existing['payload']['completed_at'])
            after = timestamp(incoming['video_semantics']['payload']['completed_at'])
            if after < before:
                return 'older_complete_ignored'
            if after == before and incoming['video_semantics']['content_hash'] != existing['content_hash']:
                raise ValueError('Conflicting equal completion timestamps')
        if not complete and old['affect_annotations'] and 'affect_annotations' in incoming:
            before = timestamp(old['affect_annotations']['payload']['run_metadata']['annotated_at_utc'])
            after = timestamp(incoming['affect_annotations']['payload']['run_metadata']['annotated_at_utc'])
            if after < before:
                return 'older_partial_ignored'
            if after == before and incoming['affect_annotations']['content_hash'] != old['affect_annotations']['content_hash']:
                raise ValueError('Conflicting equal affect timestamps')
        for t, row in incoming.items():
            if old[t]:
                row['id'] = old[t]['id']
        if complete:
            incoming['video_semantics'].update(context_id=incoming['video_context']['id'],
                                                affect_id=incoming['affect_annotations']['id'])
            incoming['video_embeddings']['semantic_id'] = incoming['video_semantics']['id']
        if all(old[t] and same(row, old[t]) for t, row in incoming.items()):
            return 'unchanged'
        projected = {t: list(v) for t, v in data.items()}
        for t, row in incoming.items():
            projected[t] = [r for r in projected[t] if r['video_id'] != vid] + [row]
        for e in items:
            if e['table'] == 'processing_runs' and not any(r['id'] == e['key'] for r in projected['processing_runs']):
                projected['processing_runs'].append(row_from_entity(e))
        validate(projected, clean=False)
        archive_before_replace(archive_dir, vid, old, items)
        vector_schema = conn.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'").fetchone()[0]
        for e in items:
            if e['table'] == 'processing_runs':
                insert(conn, e, vector_schema)
        for t in TARGETS:
            if t in incoming:
                replace_row(conn, t, old[t], incoming[t], vector_schema)
        return 'canonical_updated'


def source_version_matches_active(source_semantic, active_semantic):
    """Reconcile queue source IDs against stable canonical IDs after an upsert.

The queue must acknowledge its ORIGINAL semantic_id, never substitute the
canonical destination ID or relabel a superseded historical version.
"""
    return (source_semantic['video_id'] == active_semantic['video_id'] and
            source_semantic['run_id'] == active_semantic['run_id'] and
            source_semantic['content_hash'] == active_semantic['content_hash'] and
            source_semantic['payload'] == active_semantic['payload'])


class CanonicalBatchWriterProposal:
    """Canonical queue adapter; caller supplies the connection and archive path."""
    def __init__(self, root, approved_ids, connection_factory, archive_dir):
        from .batch_writer import BatchWriter
        from .config import DatabaseSettings
        self.validator = BatchWriter(root, approved_ids, DatabaseSettings('disabled-no-default-connection'),
                                     connection_factory)
        self.connection_factory = connection_factory
        self.archive_dir = archive_dir
        self.last_insertions = {}

    def __call__(self, queued_rows):
        if len({r['video_id'] for r in queued_rows}) != len(queued_rows):
            raise ValueError('One selected version per batch video required')
        outcomes = {}
        self.last_insertions = {}
        bundles = self.validator._bundles(queued_rows)
        with self.connection_factory() as conn:
            indexes = {r[0] for r in conn.execute('SELECT indexname FROM pg_indexes WHERE schemaname=%s', ('public',))}
            if not {t+'_one_video_physical_v1' for t in TARGETS}.issubset(indexes):
                raise ValueError('Physical 1:1 constraints are required before canonical delivery')
            fk = conn.execute("SELECT convalidated,condeferrable,condeferred FROM pg_constraint WHERE conname='video_embeddings_same_semantic_video_run_v1' AND conrelid='public.video_embeddings'::regclass").fetchone()
            if fk != (True,True,True):
                raise ValueError('Validated deferred embedding identity FK required')
            for queued, items, semantic in bundles:
                with conn.transaction():
                    outcome = upsert_bundle(conn, items, self.archive_dir)
                    if outcome in ('older_complete_ignored', 'older_partial_ignored'):
                        outcomes[queued['semantic_id']] = 'superseded'
                        continue
                    if outcome not in ('unchanged', 'canonical_updated'):
                        raise ValueError('Unexpected queue candidate outcome: ' + outcome)
                    vector_schema = conn.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'").fetchone()[0]
                    for item in items:
                        if item['table'] == 'processing_jobs':
                            insert(conn, item, vector_schema)
                    outcomes[queued['semantic_id']] = 'synced'
        return outcomes
