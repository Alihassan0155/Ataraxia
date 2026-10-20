"""Approved manifest-only S3 delivery; persistent checkpoints, pilot gate, full GET hashes."""
import csv, hashlib, json, os, sqlite3, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'backend/reports/s3_upload_20261018'
MANIFEST=ROOT/'backend/reports/s3_dry_run_20261018/audit/manifest.csv'
BUCKET='ataraxia-fyp-videos-068371986822-ap-south-1-an'
OWNER='068371986822'
STOP=threading.Event()

def now(): return datetime.now(timezone.utc).isoformat()
def digest_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def load_rows():
    expected=json.loads((MANIFEST.parent/'checksums.json').read_text())['manifest.csv']
    if digest_file(MANIFEST)!=expected:raise ValueError('Manifest checksum changed')
    with MANIFEST.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    if len(rows)!=1140 or len({r['video_id'] for r in rows})!=1140 or len({r['s3_key'] for r in rows})!=1140:raise ValueError('Scope mismatch')
    for r in rows:
        group=r['source_group'];vid=r['video_id']
        if group not in ('finevideo','tiktok') or r['s3_key']!=f'videos/{group}/{vid}.mp4' or r['s3_uri']!=f's3://{BUCKET}/{r["s3_key"]}' or r['sha256']!=r['expected_sha256'] or r['status']!='matched_sha256':raise ValueError('Invalid mapping')
        r['size_bytes']=int(r['size_bytes'])
    return rows

def checkpoint(r,status,**extra):
    value=dict(r,status=status,updated_at=now(),**extra)
    with sqlite3.connect(OUT/'checkpoint.sqlite',timeout=60) as db:
        db.execute('PRAGMA synchronous=FULL')
        db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)',(r['video_id'],status,json.dumps(value)))
    return value

def verify(client,r):
    params=dict(Bucket=BUCKET,Key=r['s3_key'],ExpectedBucketOwner=OWNER)
    head=client.head_object(**params)
    if head['ContentLength']!=r['size_bytes']:raise ValueError('Conflicting S3 size')
    response=client.get_object(**params,IfMatch=head['ETag'])
    h=hashlib.sha256();size=0
    with response['Body'] as body:
        for chunk in iter(lambda:body.read(8*1024*1024),b''):
            h.update(chunk);size+=len(chunk)
    if size!=r['size_bytes'] or h.hexdigest()!=r['sha256']:raise ValueError('Conflicting S3 content hash')
    return {'verified_sha256':h.hexdigest(),'verified_bytes':size,'etag':head['ETag'],'verification':'full_download_sha256','verified_at':now()}

def upload(client,r):
    params=dict(Bucket=BUCKET,Key=r['s3_key'],ExpectedBucketOwner=OWNER)
    path=Path(r['source_path'])
    if r['size_bytes']<16*1024*1024:
        with path.open('rb') as f:client.put_object(**params,Body=f,ContentType='video/mp4',IfNoneMatch='*')
    else:
        upload_id=client.create_multipart_upload(**params,ContentType='video/mp4')['UploadId']
        checkpoint(r,'multipart_started',upload_id=upload_id)
        try:
            parts=[]
            with path.open('rb') as f:
                for n,chunk in enumerate(iter(lambda:f.read(8*1024*1024),b''),1):
                    result=client.upload_part(**params,UploadId=upload_id,PartNumber=n,Body=chunk)
                    parts.append({'PartNumber':n,'ETag':result['ETag']})
            client.complete_multipart_upload(**params,UploadId=upload_id,MultipartUpload={'Parts':parts},IfNoneMatch='*')
        except BaseException:
            try:client.abort_multipart_upload(**params,UploadId=upload_id)
            except Exception:pass
            raise

def process(client,r):
    from botocore.exceptions import ClientError,ConnectionError,HTTPClientError
    for attempt in range(1,5):
        if STOP.is_set():return checkpoint(r,'pending')
        try:
            checkpoint(r,'validating',attempt=attempt)
            path=Path(r['source_path'])
            before=path.stat()
            if before.st_size!=r['size_bytes'] or digest_file(path)!=r['sha256']:raise ValueError('Local file hash/size changed')
            exists=True
            try:client.head_object(Bucket=BUCKET,Key=r['s3_key'],ExpectedBucketOwner=OWNER)
            except ClientError as e:
                if e.response['Error']['Code'] in ('404','NoSuchKey','NotFound'):exists=False
                else:raise
            if not exists:
                checkpoint(r,'uploading',attempt=attempt)
                upload(client,r)
                if path.stat().st_mtime_ns!=before.st_mtime_ns:raise ValueError('Local file changed during upload')
            evidence=verify(client,r)
            result=checkpoint(r,'verified',delivery='existing_verified' if exists else 'uploaded_verified',attempt=attempt,**evidence)
            print(json.dumps({'event':'verified','video_id':r['video_id'],'delivery':result['delivery']}),flush=True)
            return result
        except Exception as e:
            error=getattr(e,'response',{}).get('Error',{})
            code=error.get('Code');message=error.get('Message')
            transient=code in ('SlowDown','RequestTimeout','InternalError','ServiceUnavailable','500','503','ConditionalRequestConflict') or isinstance(e,(ConnectionError,HTTPClientError))
            if code in ('AccessDenied','InvalidAccessKeyId','SignatureDoesNotMatch','ExpiredToken','InvalidToken','403'):STOP.set()
            checkpoint(r,'retrying' if transient and attempt<4 else 'failed',attempt=attempt,error_type=type(e).__name__,aws_code=code,error=message or (str(e) if isinstance(e,ValueError) else type(e).__name__))
            if transient and attempt<4:time.sleep(2**attempt);continue
            print(json.dumps({'event':'failed','video_id':r['video_id'],'code':code,'error':message or type(e).__name__}),flush=True)
            return None

def main():
    sys.path.insert(0,str(ROOT/'backend/reports/s3_dry_run_20261018/dependencies'))
    import boto3
    from botocore.config import Config
    OUT.mkdir(parents=True,exist_ok=True)
    # Windows advisory file lock prevents concurrent uploader processes.
    import msvcrt
    lock=(OUT/'worker.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    rows=load_rows()
    with sqlite3.connect(OUT/'checkpoint.sqlite') as db:
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS records(video_id TEXT PRIMARY KEY,status TEXT NOT NULL,payload TEXT NOT NULL)')
        prior=[json.loads(v[0]) for v in db.execute('SELECT payload FROM records')]
    session=boto3.Session(profile_name='ataraxia',region_name='ap-south-1')
    cfg=Config(connect_timeout=10,read_timeout=90,retries={'total_max_attempts':4,'mode':'standard'},max_pool_connections=8)
    identity=session.client('sts',config=cfg).get_caller_identity()
    if identity['Account']!=OWNER:raise ValueError('AWS account mismatch')
    client=session.client('s3',config=cfg)
    head=client.head_bucket(Bucket=BUCKET,ExpectedBucketOwner=OWNER)
    region=head.get('BucketRegion') or head['ResponseMetadata']['HTTPHeaders'].get('x-amz-bucket-region')
    if region!='ap-south-1':raise ValueError('Bucket region mismatch')
    # Recover our own unfinished multipart attempts only.
    for old in prior:
        if old.get('status')=='multipart_started' and old.get('upload_id'):
            try:client.abort_multipart_upload(Bucket=BUCKET,Key=old['s3_key'],UploadId=old['upload_id'],ExpectedBucketOwner=OWNER)
            except client.exceptions.NoSuchUpload:pass
    for r in rows:
        if r['video_id'] not in {p['video_id'] for p in prior}:checkpoint(r,'pending')
    pilot=[r for r in rows if r['source_group']=='finevideo'][:3]+[r for r in rows if r['source_group']=='tiktok'][:2]
    print(json.dumps({'event':'pilot_start','ids':[r['video_id'] for r in pilot]}),flush=True)
    for r in pilot:
        if not process(client,r):raise RuntimeError('Pilot failed; bulk upload blocked')
    (OUT/'pilot.json').write_text(json.dumps({'passed':True,'verified_at':now(),'video_ids':[r['video_id'] for r in pilot]},indent=2))
    print(json.dumps({'event':'pilot_passed','bulk_authorized':True}),flush=True)
    remaining=[r for r in rows if r not in pilot]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(process,client,r) for r in remaining]):future.result()
    # Every run revalidates each remote object; final index checks exact mappings.
    objects={}
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=BUCKET,Prefix='videos/',ExpectedBucketOwner=OWNER):
        for obj in page.get('Contents',[]):objects[obj['Key']]=obj['Size']
    with sqlite3.connect(OUT/'checkpoint.sqlite') as db:records=[json.loads(v[0]) for v in db.execute('SELECT payload FROM records ORDER BY video_id')]
    verified=[r for r in records if r['status']=='verified' and objects.get(r['s3_key'])==r['size_bytes']]
    audit={'finished_at':now(),'expected':1140,'verified':len(verified),'verified_bytes':sum(r['size_bytes'] for r in verified),'complete':len(verified)==1140,'missing_keys':[r['s3_key'] for r in rows if r['s3_key'] not in objects],'unexpected_keys':sorted(set(objects)-{r['s3_key'] for r in rows}),'records':records,'supabase_operations':0}
    (OUT/'final_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in audit.items() if k!='records'}),flush=True)
    if not audit['complete']:raise RuntimeError('Upload incomplete; inspect final audit')

if __name__=='__main__':main()
