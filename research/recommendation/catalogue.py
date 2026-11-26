"""Read-only catalogue, with explicit provenance joins and deterministic row order.

Never loads .env, Supabase clients, media or models. Database access is restricted
to a Unix socket, in a repeatable-read READ ONLY transaction.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
import math
import os
import re
from types import MappingProxyType
from typing import Mapping

import numpy as np

from backend.video_data.catalogue import (ORDER, load_package, timestamp, validate,
                                          vector_array)

EMOTIONS = ('joy', 'sadness', 'anger', 'fear_anxiety', 'surprise', 'disgust',
            'calm_contentment', 'neutral')
TABLES = tuple(t for t in ORDER if t != 'processing_jobs')
DEFAULT_DATABASE = 'ataraxia_backup_20261109t193806z'


@dataclass(frozen=True)
class VideoFeatures:
    video_id: str
    category: str
    category_id: str
    title: str
    language: str
    semantic_summary: str
    semantic_id: str
    affect_id: str
    context_id: str
    embedding_id: str
    run_id: str
    embedding_model: str
    embedding_revision: str
    valence: float
    arousal: float
    recovery_suitability: float
    confidence: float
    emotions: tuple[float, ...]
    dominant_emotion: str
    duration_seconds: float | None = None


@dataclass(frozen=True)
class Catalogue:
    records: tuple[VideoFeatures, ...]
    embeddings: np.ndarray
    affect: np.ndarray
    video_ids: np.ndarray
    id_to_row: Mapping[str, int]
    report: dict


def load_local_database(database=DEFAULT_DATABASE):
    """Use only /tmp PostgreSQL; ambient PGHOST/DSN/service settings are ignored."""
    import psycopg
    if not isinstance(database, str) or not re.fullmatch(r'[A-Za-z0-9_]+', database):
        raise ValueError('Expected a local database name, not a connection string')
    if any(os.environ.get(k) for k in ('PGSERVICE', 'PGHOSTADDR')):
        raise ValueError('Unset PGSERVICE and PGHOSTADDR before using local research loader')
    with psycopg.connect('', host='/tmp', hostaddr='', dbname=database,
                         port=5432, connect_timeout=5,
                         options='-c default_transaction_read_only=on -c statement_timeout=30000') as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        data = {t: [r[0] for r in conn.execute(f'SELECT to_jsonb(t) FROM public.{t} t')]
                for t in TABLES}
    return build_catalogue(data, source=f'local PostgreSQL /tmp:5432/{database}')


def load_local_package(path):
    """Reuse the existing checksummed catalogue JSONL package format."""
    data, _ = load_package(path)
    return build_catalogue(data, source=f'local package {path}')


def _affect(a):
    if not isinstance(a['model'], str) or not a['model'].startswith('gemini-'):
        raise ValueError('affect model is not Gemini')
    for field, lo in [('valence', -1), ('arousal', 0), ('recovery_suitability', 0), ('confidence', 0)]:
        value = a[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= 1:
            raise ValueError('invalid affect field: ' + field)
    emotions = a['emotions']
    if set(emotions) != set(EMOTIONS) or a['dominant_emotion'] not in EMOTIONS:
        raise ValueError('invalid emotion keys or dominant emotion')
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or not 0 <= v <= 1 for v in emotions.values()):
        raise ValueError('invalid emotion probabilities')
    if not .99 <= sum(emotions.values()) <= 1.01:
        raise ValueError('emotion probabilities do not sum to one')


def build_catalogue(data, *, source='in-memory'):
    """Use latest semantic per canonical ID; ties fail closed, no older fallback.

    Eligibility requires a complete Qwen/BGE-M3 bundle, linked Gemini affect and
    context, valid existing provenance/hashes, and a resolved taxonomy category.
    Invalid bundles are excluded, never repaired or silently normalized. Duplicate
    primary keys abort because joins would be ambiguous. Unknown category is
    explicitly unresolved. No sample size, orientation or confidence cutoff.
    """
    maps = {}
    for table in TABLES:
        rows = data.get(table, [])
        key = 'video_id' if table == 'videos' else 'id'
        index = {}
        for row in rows:
            identity = row.get(key)
            if not isinstance(identity, str) or not identity or identity in index:
                raise ValueError('missing/duplicate primary key: ' + table)
            index[identity] = row
        maps[table] = index
    categories = {}
    for c in maps['interest_categories'].values():
        if c['name'] in categories:
            raise ValueError('ambiguous category name')
        categories[c['name']] = c
    semantics, embeddings = defaultdict(list), defaultdict(list)
    issues = []
    for table in TABLES:
        if table == 'videos':
            continue
        for row in maps[table].values():
            if 'video_id' in row and row['video_id'] not in maps['videos']:
                issues.append(dict(table=table, id=row['id'], reason='orphan video reference'))
    for s in maps['video_semantics'].values():
        semantics[s['video_id']].append(s)
    for e in maps['video_embeddings'].values():
        embeddings[e['semantic_id']].append(e)
        if e['semantic_id'] not in maps['video_semantics']:
            issues.append(dict(table='video_embeddings', id=e['id'], reason='orphan semantic reference'))
    records, vectors, excluded = [], [], []
    for vid, v in sorted(maps['videos'].items()):
        try:
            candidates = semantics[vid]
            if not candidates:
                raise ValueError('missing semantic record')
            latest = max(timestamp(s['payload']['completed_at']) for s in candidates)
            winners = [s for s in candidates if timestamp(s['payload']['completed_at']) == latest]
            if len(winners) != 1:
                raise ValueError('ambiguous latest semantic record')
            s = winners[0]
            linked = embeddings[s['id']]
            if len(linked) != 1:
                raise ValueError('missing or ambiguous linked embedding')
            e = linked[0]
            a = maps['affect_annotations'][s['affect_id']]
            ctx = maps['video_context'][s['context_id']]
            category = categories.get(s['primary_category'])
            if category is None or category['name'].casefold() == 'unknown':
                raise ValueError('unresolved category assignment')
            if category['payload']['name'] != category['name']:
                raise ValueError('category projection mismatch')
            # Reuse established payload hashes, frozen run/config/source provenance,
            # same-video FKs, embedding input/model/revision/template and vector checks.
            bundle = {t: [] for t in ORDER}
            bundle.update(videos=[v], interest_categories=[category], video_semantics=[s], video_embeddings=[e],
                          affect_annotations=[a], video_context=[ctx],
                          processing_runs=list({r: maps['processing_runs'][r]
                                                for r in {s['run_id'], a['run_id']}}.values()))
            validate(bundle, clean=False)
            _affect(a)
            if not s['payload']['extractor']['checkpoint'].startswith('Qwen/'):
                raise ValueError('semantic extractor is not Qwen')
            if not isinstance(s['semantic_summary'], str) or not s['semantic_summary'].strip():
                raise ValueError('missing semantic summary')
            records.append(VideoFeatures(
                vid, category['name'], category['id'], v.get('title', ''), v.get('language', ''),
                s['semantic_summary'], s['id'], a['id'], ctx['id'], e['id'], s['run_id'],
                e['model'], e['revision'], a['valence'], a['arousal'], a['recovery_suitability'],
                a['confidence'], tuple(a['emotions'][k] for k in EMOTIONS), a['dominant_emotion'], v.get('duration_seconds')))
            vectors.append(vector_array(e['embedding']))
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            excluded.append(dict(video_id=vid, reason=str(exc)))
    # A similarity matrix must never mix model revisions/templates.
    spaces = {(r.embedding_model, r.embedding_revision,
               maps['video_embeddings'][r.embedding_id]['template_version']) for r in records}
    if len(spaces) > 1:
        raise ValueError('multiple embedding spaces; choose a homogeneous source snapshot')
    matrix = np.array(vectors, dtype=np.float32).reshape(-1, 1024)
    affect = np.array([[r.valence, r.arousal, r.recovery_suitability, r.confidence, *r.emotions]
                       for r in records], dtype=np.float32).reshape(-1, 12)
    ids = np.array([r.video_id for r in records], dtype=str)
    for array in (matrix, affect, ids):
        array.setflags(write=False)
    affect_videos = {a['video_id'] for a in maps['affect_annotations'].values()} & maps['videos'].keys()
    report = dict(source=source, source_counts={t: len(maps[t]) for t in TABLES},
                  eligible_videos=len(records), category_distribution=dict(sorted(Counter(r.category for r in records).items())),
                  embedding_shape=list(matrix.shape), embedding_dtype=str(matrix.dtype),
                  embedding_norm_range=[float(np.linalg.norm(matrix, axis=1).min()), float(np.linalg.norm(matrix, axis=1).max())] if records else None,
                  affect_coverage=dict(canonical_videos_with_annotation=len(affect_videos), canonical_videos=len(maps['videos']),
                                       eligible_with_valid_annotation=len(records)),
                  excluded_count=len(excluded), exclusion_reasons=dict(Counter(x['reason'] for x in excluded)),
                  excluded_records=excluded, integrity_issues=issues,
                  affect_columns=['valence', 'arousal', 'recovery_suitability', 'confidence', *EMOTIONS])
    return Catalogue(tuple(records), matrix, affect, ids,
                     MappingProxyType({r.video_id: i for i, r in enumerate(records)}), report)
