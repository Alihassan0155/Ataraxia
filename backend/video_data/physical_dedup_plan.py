"""Prepare/rehearse physical deduplication. No production apply command exists.

Production access is restricted to existing read-only snapshot/dump routines.
All deletion, index creation and update tests run on an isolated localhost DB.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .artifacts import fingerprint
from .catalogue import (ORDER, capture, compatible, dump_backup, key, load_package,
                        timestamp, validate, write_package)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'backend/reports/physical_dedup_20261103'
BIN = ROOT / 'backend/reports/catalogue_final_20261018/tools/pgsql/bin'
AFFECT = 'gemini-3.8-flash'
SEMANTIC = 'Qwen/Qwen3-4B-Instruct-2507'
EMBEDDING = 'BAAI/bge-m3'
REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
TARGETS = ('video_context', 'affect_annotations', 'video_semantics', 'video_embeddings')


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n', encoding='utf-8')


def select(data):
    validate(data, clean=False)
    maps = {t: {key(r, t): r for r in data[t]} for t in ORDER}
    bysem, byaff, byctx = defaultdict(list), defaultdict(list), defaultdict(list)
    byemb = defaultdict(list)
    for s in data['video_semantics']:
        bysem[s['video_id']].append(s)
    for a in data['affect_annotations']:
        byaff[a['video_id']].append(a)
    for c in data['video_context']:
        byctx[c['video_id']].append(c)
    for e in data['video_embeddings']:
        byemb[e['semantic_id']].append(e)
    keep = {t: set() for t in TARGETS}
    selection, blockers = [], []
    for vid in sorted(maps['videos']):
        bundles = []
        for s in bysem[vid]:
            a = maps['affect_annotations'][s['affect_id']]
            matching = [e for e in byemb[s['id']] if compatible(e, s) and
                        e['model'] == EMBEDDING and e['revision'] == REVISION]
            if (s['payload']['status'] == 'complete' and
                    s['payload']['extractor']['checkpoint'] == SEMANTIC and
                    a['model'] == AFFECT and len(matching) == 1):
                bundles.append((s, matching[0]))
        selected = dict(video_id=vid)
        if bundles:
            latest = max(timestamp(s['payload']['completed_at']) for s, e in bundles)
            winners = [(s, e) for s, e in bundles if timestamp(s['payload']['completed_at']) == latest]
            if len(winners) != 1:
                blockers.append(dict(video_id=vid, reason='ambiguous_complete_timestamp'))
                continue
            s, e = winners[0]
            selected.update(context_id=s['context_id'], affect_id=s['affect_id'],
                            semantic_id=s['id'], embedding_id=e['id'],
                            completed_at=s['payload']['completed_at'], reason='latest_valid_complete_bundle')
        else:
            if bysem[vid]:
                blockers.append(dict(video_id=vid, reason='existing_semantics_without_approved_complete_bundle'))
                continue
            candidates = [a for a in byaff[vid] if a['model'] == AFFECT]
            if candidates:
                latest = max(timestamp(a['payload']['run_metadata']['annotated_at_utc']) for a in candidates)
                winners = [a for a in candidates if timestamp(a['payload']['run_metadata']['annotated_at_utc']) == latest]
                if len({a['content_hash'] for a in winners}) != 1:
                    blockers.append(dict(video_id=vid, reason='ambiguous_partial_affect_timestamp'))
                    continue
                def priority(a):
                    name = maps['processing_runs'][a['run_id']]['name']
                    return ('canary' in name or 'snapshot' in name, name, a['id'])
                selected['affect_id'] = min(winners, key=priority)['id']
            # Existing context with authentic richest acoustic representation.
            # Never use created_at: bulk import time is not evidence recency.
            contexts = byctx[vid]
            richest = max(len(c['acoustic_features']) for c in contexts)
            winners = [c for c in contexts if len(c['acoustic_features']) == richest]
            if len(winners) != 1:
                blockers.append(dict(video_id=vid, reason='ambiguous_context_provenance'))
                continue
            selected.update(context_id=winners[0]['id'], reason='production_partial_or_context_only')
        for field, table in [('context_id', 'video_context'), ('affect_id', 'affect_annotations'),
                             ('semantic_id', 'video_semantics'), ('embedding_id', 'video_embeddings')]:
            if selected.get(field):
                keep[table].add(selected[field])
        selection.append(selected)
    if blockers:
        raise ValueError('Canonical-selection blockers: ' + json.dumps(blockers))
    result = {t: [r for r in data[t] if t not in keep or key(r, t) in keep[t]] for t in ORDER}
    validate(result, clean=False)
    for t in TARGETS:
        if len(result[t]) != len({r['video_id'] for r in result[t]}):
            raise ValueError('Selection is not 1:1')
    return result, selection


def migration_sql(data, desired):
    """Unexecuted proposal. A future executor must also verify the full catalog signature."""
    from psycopg import sql
    rows = ['-- PROPOSAL ONLY. Requires separate user approval. No CASCADE/TRUNCATE.',
            'BEGIN;', "SET LOCAL lock_timeout='5s';", "SET LOCAL statement_timeout='120s';",
            "DO $$ BEGIN IF current_setting('ataraxia.physical_dedup_approved',true) IS DISTINCT FROM "
            "'separate-user-approval-and-exact-snapshot-recheck-required' THEN RAISE EXCEPTION "
            "'Proposal is disabled; no production apply executor is provided'; END IF; END $$;",
            'SELECT pg_advisory_xact_lock(193701,1140);',
            'LOCK TABLE ' + ','.join('public.' + t for t in ORDER) + ' IN ACCESS EXCLUSIVE MODE;']
    for t in ORDER:
        k = 'video_id' if t == 'videos' else 'id'
        # Exact original row values (including created_at and vectors), stable JSONB representation.
        expected = fingerprint(sorted(data[t], key=lambda r: key(r, t)))
        rows.append('-- Python executor must compare full snapshot fingerprint ' + t + ': ' + expected)
        rows.append(f'DO $$ BEGIN IF (SELECT count(*) FROM public.{t}) <> {len(data[t])} THEN '
                    f"RAISE EXCEPTION 'Stale snapshot: {t}'; END IF; END $$;")
    for t in ('video_embeddings', 'video_semantics', 'affect_annotations', 'video_context'):
        chosen = {r['id'] for r in desired[t]}
        removed = [r['id'] for r in data[t] if r['id'] not in chosen]
        for offset in range(0, len(removed), 100):
            ids = ','.join(sql.Literal(x).as_string() for x in removed[offset:offset+100])
            rows.append(f'DELETE FROM public.{t} WHERE id IN ({ids});')
    for t in TARGETS:
        rows.append(f'CREATE UNIQUE INDEX {t}_one_video_physical_v1 ON public.{t}(video_id);')
        rows.append(f'DO $$ BEGIN IF (SELECT count(*) FROM public.{t}) <> {len(desired[t])} THEN '
                    f"RAISE EXCEPTION 'Unexpected final count: {t}'; END IF; END $$;")
    rows.extend([
        'CREATE UNIQUE INDEX video_semantics_identity_video_run_v1 ON public.video_semantics(id,video_id,run_id);',
        'ALTER TABLE public.video_embeddings ADD CONSTRAINT video_embeddings_same_semantic_video_run_v1 '
        'FOREIGN KEY(semantic_id,video_id,run_id) REFERENCES public.video_semantics(id,video_id,run_id) '
        'DEFERRABLE INITIALLY DEFERRED;'])
    # Default cannot commit even if someone mistakenly runs the proposal file.
    rows.extend(['-- Intentionally ROLLBACK. Approved executor required to COMMIT.', 'ROLLBACK;'])
    return '\n'.join(rows) + '\n'


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    if not (OUT / 'backup/manifest.json').exists():
        capture(OUT / 'backup')
    data, manifest = load_package(OUT / 'backup')
    print(json.dumps(dict(event='backup_package_verified', counts=validate(data, clean=False)['counts'])), flush=True)
    catalog = json.loads((OUT / 'backup/catalog.json').read_bytes())
    # Fail on any unexpected external FK into a table whose rows would be removed.
    external = [r for r in catalog['inbound_fks'] if r['nspname'] != 'public' or
                (r['relname'] not in ORDER and any(t in r['definition'] for t in TARGETS))]
    if external:
        raise ValueError('External inbound references require explicit mapping: ' + json.dumps(external))
    desired, selection = select(data)
    if not (OUT / 'canonical/manifest.json').exists():
        write_package(OUT / 'canonical', desired, dict(kind='physical-dedup-canonical-plan',
                      backup_manifest_sha256=hashlib.sha256((OUT / 'backup/manifest.json').read_bytes()).hexdigest()))
    identities = {}
    for t in ORDER:
        keep = {key(r, t) for r in desired[t]}
        identities[t] = dict(retain=sorted(keep), delete=sorted(key(r, t) for r in data[t] if key(r, t) not in keep))
    save(OUT / 'identities.json', identities)
    save(OUT / 'selection.json', selection)
    (OUT / 'migration_proposal_rollback.sql').write_text(migration_sql(data, desired), encoding='utf-8')
    # References are retained exactly; no remapping is necessary in this snapshot.
    plan = dict(status='prepared_not_approved_for_production', production_mutations=0,
                backup=str(OUT / 'backup'), canonical=str(OUT / 'canonical'), remappings=[],
                native_backup=str(OUT / 'native_backup/video_tables.dump'),
                backup_restore_verified=(json.loads((OUT / 'rehearsal.json').read_bytes()).get(
                    'native_restore_matches_every_original_row', False) if (OUT / 'rehearsal.json').exists() else False),
                proposed_constraints={'unique_video_id_tables':list(TARGETS),
                    'semantic_unique_columns':['id','video_id','run_id'],
                    'deferred_embedding_fk':['semantic_id','video_id','run_id']},
                counts={t: dict(before=len(data[t]), retain=len(desired[t]), delete=len(identities[t]['delete'])) for t in ORDER},
                inbound_foreign_keys=catalog['inbound_fks'], blockers=[],
                source_schema_signature=manifest['info']['schema_signature'],
                risks=['Pause/restore exact watcher process tree only at approved execution.',
                       'Recheck complete row hashes and schema/dependencies under locks before deletion.',
                       'Legacy immutable insert-only writers must be replaced before watcher restart.',
                       'Archive every future replaced production version before canonical upsert.',
                       'Local restore needs existing pgvector and original roles/grants for a full environment restore.'])
    save(OUT / 'plan.json', plan)
    if not (OUT / 'native_backup/manifest.json').exists():
        dump_backup(OUT / 'native_backup', BIN / 'pg_dump.exe', BIN / 'pg_restore.exe')
    save(OUT / 'checksums.json', {p.relative_to(OUT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in OUT.rglob('*') if p.is_file() and p.name != 'checksums.json'
                                and 'local_pgdata' not in p.parts})
    print(json.dumps(dict(event='plan_prepared', counts=plan['counts'], production_mutations=0)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare'])
    parser.parse_args()
    prepare()


if __name__ == '__main__':
    main()
