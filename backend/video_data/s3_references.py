"""Prepare and explicitly approve atomic S3-location updates; no S3 APIs or models."""
import argparse,csv,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from psycopg import sql
from .config import DatabaseSettings,connect,TABLES
from .artifacts import fingerprint

ROOT=Path(__file__).resolve().parents[2]
AUDIT=ROOT/'backend/reports/s3_upload_20261018/final_audit.csv'
BUCKET='ataraxia-fyp-videos-068371986822-ap-south-1-an'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str)
def digest(value):return hashlib.sha256(dump(value).encode()).hexdigest()
def audit_rows():
    checks=json.loads((AUDIT.parent/'checksums.json').read_text())
    if sha(AUDIT)!=checks[AUDIT.name]:raise ValueError('Upload audit checksum mismatch')
    manifest=ROOT/'backend/reports/s3_dry_run_20261018/audit/manifest.csv'
    original_checks=json.loads((manifest.parent/'checksums.json').read_text())
    if sha(manifest)!=original_checks[manifest.name]:raise ValueError('Original manifest checksum mismatch')
    def read(path):
        with path.open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))
    rows=read(AUDIT);original=read(manifest)
    if len(rows)!=1140 or len({r['video_id'] for r in rows})!=1140 or len({r['s3_key'] for r in rows})!=1140:raise ValueError('Audit scope not 1140 unique records')
    originals={r['video_id']:r for r in original}
    if set(originals)!={r['video_id'] for r in rows}:raise ValueError('Approved IDs differ')
    for r in rows:
        old=originals[r['video_id']]
        for k in ('source_path','s3_key','s3_uri','sha256','size_bytes'):
            if r[k]!=old[k]:raise ValueError('Original mapping differs: '+r['video_id'])
        if r['status']!='verified' or r['sha256']!=r['verified_sha256'] or r['s3_uri']!=f's3://{BUCKET}/'+r['s3_key']:raise ValueError('Unverified S3 mapping')
    return rows

def snapshot(conn,lock=False):
    with conn.transaction():
        return _snapshot(conn,lock)

def _snapshot(conn,lock=False):
    # Stable timestamp serialization across Supabase and Windows PostgreSQL.
    conn.execute("SET LOCAL TIME ZONE 'UTC'")
    if lock:
        conn.execute('SELECT pg_advisory_xact_lock(193701,1140)')
        # Protect complete post-verification against concurrent processing writes.
        conn.execute('LOCK TABLE '+','.join('public.'+t for t in sorted(TABLES))+' IN SHARE ROW EXCLUSIVE MODE')
    cur=conn.execute('SELECT * FROM public.videos ORDER BY video_id'+(' FOR UPDATE' if lock else ''))
    rows=[dict(zip([c.name for c in cur.description],r)) for r in cur.fetchall()]
    immutable={r['video_id']:digest({k:v for k,v in r.items() if k not in ('media_uri','availability')}) for r in rows}
    others={}
    for t in TABLES:
        if t=='videos':continue
        count,hashvalue=conn.execute(sql.SQL("SELECT count(*),md5(string_agg(md5(row_to_json(t)::text),'' ORDER BY id COLLATE \"C\")) FROM public.{} t").format(sql.Identifier(t))).fetchone()
        others[t]={'count':count,'digest':hashvalue}
    return rows,{'videos_immutable':immutable,'other_tables':others}

def prepare(conn,out):
    rows=audit_rows();mapping={r['video_id']:r for r in rows}
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        videos,invariants=snapshot(conn)
    if {v['video_id'] for v in videos}!=set(mapping):raise ValueError('Live IDs differ from approved 1140')
    records=[]
    for v in videos:
        r=mapping[v['video_id']]
        if v['media_sha256']!=r['sha256'] or fingerprint(v['payload'])!=v['content_hash']:raise ValueError('Video hash mismatch')
        before={k:v[k] for k in ('media_uri','availability')}
        after={'media_uri':r['s3_uri'],'availability':'s3_verified'}
        if before['availability']=='s3_verified' and before!=after:raise ValueError('Conflicting verified S3 reference')
        records.append({'video_id':v['video_id'],'media_sha256':r['sha256'],'before':before,'after':after})
    plan={'version':1,'prepared_at':datetime.now(timezone.utc).isoformat(),'audit_sha256':sha(AUDIT),'invariants':invariants,'records':records}
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    path=out/'plan.json';path.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    (out/'checksums.json').write_text(json.dumps({'plan.json':sha(path)},indent=2))
    return {'matched':len(records),'updates':sum(r['before']!=r['after'] for r in records),'plan_sha256':sha(path)}

def load_plan(package):
    p=Path(package);checks=json.loads((p/'checksums.json').read_text());path=p/'plan.json'
    if sha(path)!=checks['plan.json']:raise ValueError('Plan checksum mismatch')
    plan=json.loads(path.read_text());rows=audit_rows()
    if plan['audit_sha256']!=sha(AUDIT):raise ValueError('Audit changed')
    mapping={r['video_id']:r for r in rows}
    if len(plan['records'])!=1140 or {r['video_id'] for r in plan['records']}!=set(mapping):raise ValueError('Plan scope mismatch')
    for r in plan['records']:
        if r['after']!={'media_uri':mapping[r['video_id']]['s3_uri'],'availability':'s3_verified'} or r['media_sha256']!=mapping[r['video_id']]['sha256']:raise ValueError('Plan mapping mismatch')
    return plan

def execute(conn,plan,rollback=False,fail_after=None):
    direction='rollback' if rollback else 'apply';changed=0
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout='5s'")
        before,invariants=snapshot(conn,lock=True)
        if invariants!=plan['invariants']:raise ValueError('Concurrent metadata/processing change; prepare a fresh plan')
        vm={v['video_id']:v for v in before}
        if set(vm)!={r['video_id'] for r in plan['records']}:raise ValueError('Live scope changed')
        for r in plan['records']:
            source,target=(r['after'],r['before']) if rollback else (r['before'],r['after'])
            current={k:vm[r['video_id']][k] for k in target}
            if current==target:continue
            if current!=source:raise ValueError('Concurrent storage-reference conflict: '+r['video_id'])
            conn.execute('UPDATE public.videos SET media_uri=%s,availability=%s WHERE video_id=%s',(target['media_uri'],target['availability'],r['video_id']))
            changed+=1
            if fail_after and changed>=fail_after:raise RuntimeError('Injected transaction failure')
        after,observed=snapshot(conn)
        if observed!=invariants:raise ValueError('Unrelated data changed; rollback')
        expected={r['video_id']:r['before' if rollback else 'after'] for r in plan['records']}
        if any({k:v[k] for k in ('media_uri','availability')}!=expected[v['video_id']] for v in after):raise ValueError('Post-update verification failed')
    return {'direction':direction,'matched':1140,'changed':changed,'verified':1140,'unrelated_data_unchanged':True,'committed_at':datetime.now(timezone.utc).isoformat()}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','check','apply','rollback']);p.add_argument('--package',type=Path,required=True)
    p.add_argument('--approved-production-write',action='store_true');p.add_argument('--expected-plan-sha256')
    args=p.parse_args()
    try:
        if args.action=='check':
            plan=load_plan(args.package);print(json.dumps({'valid':True,'records':len(plan['records']),'plan_sha256':sha(args.package/'plan.json')}));return
        if args.action in ('apply','rollback'):
            if not args.approved_production_write:raise ValueError('Explicit production approval required')
            plan=load_plan(args.package)
            if args.expected_plan_sha256!=sha(args.package/'plan.json'):raise ValueError('Expected plan SHA256 required')
            rehearsal=json.loads((args.package/'rehearsal.json').read_text())
            bindings={'plan_sha256':sha(args.package/'plan.json'),
                      'utility_sha256':sha(Path(__file__)),
                      'repository_sha256':sha(Path(__file__).with_name('repository.py')),
                      'backup_sha256':sha(args.package/'native_backup/video_tables.dump')}
            if rehearsal.get('bindings')!=bindings or not rehearsal.get('rollback_restores_every_original_column'):
                raise ValueError('Successful rehearsal must match this exact plan, code and backup')
        with connect(DatabaseSettings.load()) as conn:
            if args.action=='prepare':result=prepare(conn,args.package)
            else:
                # Persist intent before BEGIN; a crash after COMMIT can be safely
                # reconciled by rerunning the same immutable idempotent plan.
                log=args.package/'execution.jsonl'
                import os
                def record(value):
                    with log.open('a',encoding='utf-8') as f:f.write(dump(value)+'\n');f.flush();os.fsync(f.fileno())
                record({'event':'intent','action':args.action,'plan_sha256':args.expected_plan_sha256,'time':datetime.now(timezone.utc).isoformat()})
                result=execute(conn,plan,rollback=args.action=='rollback');record({'event':'committed',**result})
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({'failed':True,'error_type':type(e).__name__,'reason':str(e) if isinstance(e,(ValueError,RuntimeError)) else 'Database operation failed','sqlstate':getattr(e,'sqlstate',None)}));raise SystemExit(1)

if __name__=='__main__':main()
