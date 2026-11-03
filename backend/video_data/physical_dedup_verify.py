"""Read-only post-cutover constraints, counts, vectors, evidence and watcher checks."""
import hashlib
import json
from pathlib import Path
import sqlite3

from psycopg import sql

from .catalogue import ORDER
from .config import DatabaseSettings,connect
from .physical_dedup_plan import OUT,TARGETS
from .physical_dedup_execute import REPORT,WATCH,Watcher,save


def verify_database():
    expected=json.loads((REPORT/'committed.json').read_bytes())['validation']['counts']
    result={}
    with connect(DatabaseSettings.load()) as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            counts={t:conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier('public',t))).fetchone()[0] for t in ORDER}
            if counts!=expected:raise ValueError('Final count drift')
            for table in TARGETS:
                dup=conn.execute(sql.SQL('SELECT video_id FROM {} GROUP BY video_id HAVING count(*)>1 LIMIT 1').format(sql.Identifier('public',table))).fetchone()
                if dup:raise ValueError('Duplicate video: '+table)
                index=conn.execute('SELECT i.indisunique,i.indisvalid,i.indisready,pg_get_indexdef(i.indexrelid) FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s',('public',table+'_one_video_physical_v1')).fetchone()
                if not index or index[:3]!=(True,True,True) or not index[3].endswith('(video_id)'):
                    raise ValueError('Missing/invalid video uniqueness index')
            cur=conn.execute("SELECT c.relname AS table_name,p.conname,p.contype,p.convalidated,pg_get_constraintdef(p.oid) AS definition FROM pg_constraint p JOIN pg_class c ON c.oid=p.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname,p.conname")
            constraints=[dict(zip([d.name for d in cur.description],r)) for r in cur.fetchall()]
            old=json.loads((OUT/'backup/catalog.json').read_bytes())['constraints']
            new=[r for r in constraints if r['conname']=='video_embeddings_same_semantic_video_run_v1']
            if [r for r in constraints if r not in new]!=old or len(new)!=1 or not new[0]['convalidated']:
                raise ValueError('Unexpected FK/constraint changes')
            if new[0]['definition']!='FOREIGN KEY (semantic_id, video_id, run_id) REFERENCES video_semantics(id, video_id, run_id) DEFERRABLE INITIALLY DEFERRED':
                raise ValueError('Unexpected composite FK definition')
            cur=conn.execute("SELECT p.convalidated,p.condeferrable,p.condeferred,p.confdeltype FROM pg_constraint p WHERE p.conrelid='public.video_embeddings'::regclass AND p.conname='video_embeddings_same_semantic_video_run_v1'")
            if cur.fetchone()!=(True,True,True,'a'):raise ValueError('Composite FK configuration mismatch')
            vector_schema=conn.execute("SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'").fetchone()[0]
            bad=conn.execute(sql.SQL('SELECT count(*) FROM public.video_embeddings WHERE {}(embedding)<>1024 OR abs({}(embedding)-1)>0.0001 OR embedding IS NULL').format(sql.Identifier(vector_schema,'vector_dims'),sql.Identifier(vector_schema,'vector_norm'))).fetchone()[0]
            if bad:raise ValueError('Invalid embedding vectors')
            orphans=conn.execute('SELECT count(*) FROM public.video_embeddings e LEFT JOIN public.video_semantics s ON (s.id,s.video_id,s.run_id)=(e.semantic_id,e.video_id,e.run_id) WHERE s.id IS NULL').fetchone()[0]
            missing=conn.execute('SELECT count(*) FROM public.video_semantics s LEFT JOIN public.video_embeddings e ON e.semantic_id=s.id WHERE e.id IS NULL').fetchone()[0]
            if orphans or missing:raise ValueError('Missing/incompatible semantic embedding relationships')
            result=dict(counts=counts,unique_video_indexes_valid=True,original_constraints_unchanged=True,
                deferred_embedding_fk_valid=True,invalid_embeddings=bad,orphan_embeddings=orphans,semantics_without_embedding=missing)
    save('database_verification.json',result)
    return result


def verify_watcher():
    lines=(WATCH/'watcher.log').read_text(encoding='utf-8').splitlines()
    events=[json.loads(s) for s in lines if s.startswith('{')]
    start=max(i for i,e in enumerate(events) if e.get('event')=='canonical_writer_enabled')
    recent=events[start:]
    if any(e.get('event')=='watcher_retry' for e in recent):raise ValueError('Restarted watcher reported an error')
    reconciled=[e for e in recent if e.get('event')=='startup_reconciliation_completed']
    scans=[e for e in recent if 'pending_versions' in e]
    if not reconciled or not scans:return None
    last=scans[-1]
    if reconciled[-1]['videos']!=1111 or last['pending_versions'] or last['new_versions'] or last['statuses']!={'synced':1111,'superseded':92}:
        raise ValueError('Unexpected watcher queue state')
    with sqlite3.connect((WATCH/'queue.sqlite').resolve().as_uri()+'?mode=ro',uri=True) as c:
        errors=c.execute('SELECT * FROM discovery_errors').fetchall()
        if len(errors)!=1 or errors[0][0:2]!=('remote-reconciliation','OperationalError') or errors[0][-1]!=1:
            raise ValueError('New watcher errors')
    process=json.loads((WATCH/'watcher_process.json').read_bytes())
    inspector=Watcher();inspector.inspect(process['pid'])
    before=json.loads((REPORT/'watcher_before.json').read_bytes())
    if inspector.startup()!=before['startup']:raise ValueError('Startup registration changed')
    result=dict(pid=process['pid'],canonical_writer_enabled=True,startup_reconciled_videos=1111,
        scan=last,new_errors=0,startup_unchanged=True,original_scope=1140)
    save('watcher_verification.json',result)
    return result


if __name__=='__main__':
    for name,digest in json.loads((OUT/'checksums.json').read_bytes()).items():
        if hashlib.sha256((OUT/name).read_bytes()).hexdigest()!=digest:raise ValueError('Backup/evidence integrity changed: '+name)
    db=verify_database()
    watcher=verify_watcher()
    print(json.dumps(dict(database=db,watcher=watcher,prepared_evidence_checksums_valid=True)),flush=True)
