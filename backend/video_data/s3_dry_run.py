"""Read-only AWS checks and a hash-verified local-video upload manifest. NO upload API."""
import argparse
from collections import Counter,defaultdict
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime,timezone
from .config import DatabaseSettings,connect

ROOT=Path(__file__).resolve().parents[2]


def destination(video_id,dataset,prefix):
    if prefix!='videos/':raise ValueError('Expected approved videos/ prefix')
    if re.fullmatch(r'FV\d+',video_id) and 'finevideo' in dataset.lower():group='finevideo'
    elif re.fullmatch(r'TT_\d+',video_id) and 'tiktok' in dataset.lower():group='tiktok'
    else:raise ValueError('Unapproved source/video identity')
    return group,prefix+group+'/'+video_id+'.mp4'


def file_hash(path):
    before=path.stat();sha=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):sha.update(chunk)
    after=path.stat()
    if before.st_size!=after.st_size or before.st_mtime_ns!=after.st_mtime_ns:
        raise ValueError('Video changed during hashing')
    return sha.hexdigest(),after.st_size


def candidate_index(rows,roots):
    roots={Path(p).resolve() for p in roots if Path(p).is_dir()}
    direct={};wanted=set()
    for r in rows:
        vid=r['video_id'];wanted.add(vid);wanted.add(vid.removeprefix('TT_'))
        paths=[]
        for value in [r.get('media_uri'),r.get('payload',{}).get('file_path')]:
            if not value:continue
            p=Path(value)
            choices=[p] if p.is_absolute() else [ROOT/p,ROOT/'annotation'/p]
            for p in choices:
                if p.is_file():
                    resolved=p.resolve()
                    if resolved not in paths:paths.append(resolved)
                    roots.add(resolved.parent)
        direct[vid]=paths
    index=defaultdict(list)
    for root in sorted(roots,key=str):
        for p in sorted(root.rglob('*'),key=str):
            if p.is_file() and p.suffix.lower()=='.mp4' and p.stem in wanted:
                resolved=p.resolve()
                if resolved not in index[p.stem]:index[p.stem].append(resolved)
    return direct,index,sorted(str(p) for p in roots)


def map_files(rows,bucket,prefix,roots):
    if len({r['video_id'] for r in rows})!=len(rows):raise ValueError('Duplicate video IDs')
    direct,index,scanned=candidate_index(rows,roots);results=[];seen_keys=set()
    for number,r in enumerate(sorted(rows,key=lambda r:r['video_id']),1):
        vid=r['video_id'];group,key=destination(vid,r['source_dataset'],prefix)
        if key in seen_keys:raise ValueError('Duplicate object key')
        seen_keys.add(key)
        choices=list(dict.fromkeys(direct[vid]+index.get(vid,[])+index.get(vid.removeprefix('TT_'),[])))
        expected=r.get('media_sha256') or r.get('payload',{}).get('media_sha256')
        result={'video_id':vid,'source_group':group,'source_path':None,'s3_key':key,
            's3_uri':'s3://'+bucket+'/'+key,'size_bytes':None,'sha256':None,'expected_sha256':expected,
            'status':'missing_local_file' if not choices else 'hash_not_verified',
            'candidate_paths':[str(p) for p in choices],'rejected_candidates':[]}
        if not expected or not re.fullmatch(r'[0-9a-fA-F]{64}',expected):
            result['status']='missing_or_invalid_stored_hash'
        else:
            for path in choices:
                try:digest,size=file_hash(path)
                except (OSError,ValueError) as error:
                    result['rejected_candidates'].append({'path':str(path),'reason':type(error).__name__});continue
                if digest.lower()!=expected.lower():
                    result['rejected_candidates'].append({'path':str(path),'reason':'sha256_mismatch'});continue
                result.update(source_path=str(path),sha256=digest,size_bytes=size,status='matched_sha256')
                break
            if choices and result['source_path'] is None:result['status']='no_matching_file_hash'
        results.append(result)
        if number%100==0:print(json.dumps({'event':'local_manifest_progress','checked':number}),flush=True)
    return results,scanned


def aws_verify(config):
    import boto3
    from botocore.config import Config
    report={'verified_at':datetime.now(timezone.utc).isoformat(),'bucket':config['AWS_S3_BUCKET'],
        'configured_region':config['AWS_REGION'],'identity':None,'bucket_verified':False,
        'region_verified':False,'list_prefix_verified':False,'upload_permission':'unverified',
        'uploads':0,'bucket_creations':0,'errors':[]}
    def failure(step,error):
        response=getattr(error,'response',{})
        report['errors'].append({'step':step,'error_type':type(error).__name__,
                                'code':response.get('Error',{}).get('Code')})
    # Use the configured local provider chain; do not probe EC2 metadata from this PC.
    os.environ.setdefault('AWS_EC2_METADATA_DISABLED','true')
    try:
        session=boto3.Session(region_name=config['AWS_REGION'])
        credentials=session.get_credentials()
        if credentials is None:
            report['credentials_status']='not_found_in_configured_provider_chain'
            return report
        report['credentials_status']='available';report['credential_provider']=credentials.method
        client_config=Config(connect_timeout=8,read_timeout=15,retries={'max_attempts':2})
        identity=session.client('sts',config=client_config).get_caller_identity()
        report['identity']={k:identity[k] for k in ('Account','Arn')}
    except Exception as error:failure('identity',error);return report
    s3=session.client('s3',config=client_config)
    params={'Bucket':config['AWS_S3_BUCKET'],'ExpectedBucketOwner':identity['Account']}
    try:
        head=s3.head_bucket(**params);report['bucket_verified']=True
        region=head.get('BucketRegion') or head.get('ResponseMetadata',{}).get('HTTPHeaders',{}).get('x-amz-bucket-region')
        report['actual_region']=region
        if region is None:
            region=s3.get_bucket_location(**params).get('LocationConstraint') or 'us-east-1'
            report['actual_region']=region
        report['region_verified']=region==config['AWS_REGION']
    except Exception as error:failure('bucket_owner_region',error);return report
    if not report['region_verified']:return report
    try:
        objects=[]
        for page in s3.get_paginator('list_objects_v2').paginate(**params,Prefix=config['AWS_S3_PREFIX']):
            objects.extend({'key':v['Key'],'size_bytes':v['Size']} for v in page.get('Contents',[]))
        report['list_prefix_verified']=True;report['existing_objects']=objects
    except Exception as error:failure('list_prefix',error)
    # Optional identity-policy evidence only, never represented as a successful PUT.
    arn=identity['Arn']
    try:
        iam=session.client('iam',config=client_config)
        if ':assumed-role/' in arn:
            arn=iam.get_role(RoleName=arn.split('/')[-2])['Role']['Arn']
        if ':iam::' in arn and (':user/' in arn or ':role/' in arn):
            simulation=iam.simulate_principal_policy(PolicySourceArn=arn,
                ActionNames=['s3:PutObject','s3:AbortMultipartUpload','s3:ListMultipartUploadParts'],
                ResourceArns=['arn:aws:s3:::'+config['AWS_S3_BUCKET']+'/'+config['AWS_S3_PREFIX']+'*'])
            report['upload_policy_simulation']=[{'action':r['EvalActionName'],'decision':r['EvalDecision'],
                'missing_context':r.get('MissingContextValues',[])} for r in simulation['EvaluationResults']]
            report['upload_permission']='policy_simulation_only_not_live_write_verification'
    except Exception as error:failure('upload_policy_simulation',error)
    report['permission_limit']='No writes performed. Identity-policy simulation does not establish all bucket-policy, SCP or KMS conditions.'
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--sdk-path',type=Path)
    parser.add_argument('--media-root',action='append',type=Path,default=[])
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.sdk_path:sys.path.insert(0,str(args.sdk_path.resolve()))
    from dotenv import dotenv_values
    config={**dotenv_values(ROOT/'backend/.env'),**dotenv_values(args.env_file),**os.environ}
    if not config.get('AWS_S3_BUCKET') or not config.get('AWS_REGION'):parser.error('AWS_S3_BUCKET and AWS_REGION required')
    config.setdefault('AWS_S3_PREFIX','videos/')
    for k,v in config.items():
        if k.startswith('AWS_') and v:os.environ.setdefault(k,v)
    args.out.mkdir(parents=True,exist_ok=False)
    aws=aws_verify(config)
    (args.out/'aws_verification.json').write_text(json.dumps(aws,indent=2),encoding='utf-8')
    with connect(DatabaseSettings.load()) as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            cur=conn.execute('SELECT video_id,source_dataset,media_uri,media_sha256,payload FROM public.videos')
            rows=[dict(zip([c.name for c in cur.description],r)) for r in cur.fetchall()]
    if len(rows)!=1140 or len({r['video_id'] for r in rows})!=1140:raise ValueError('Expected exactly 1,140 approved existing IDs')
    from .catalogue import load_package
    approved,_=load_package(ROOT/'backend/reports/catalogue_final_20261018/production_snapshot')
    if {r['video_id'] for r in rows}!={r['video_id'] for r in approved['videos']}:raise ValueError('Approved ID set changed')
    results,roots=map_files(rows,config['AWS_S3_BUCKET'],config['AWS_S3_PREFIX'],
        args.media_root+[ROOT/'data/FineVideo/videos',ROOT/'data/fyp_videos_1250/videos/videos'])
    existing={r['key']:r for r in aws.get('existing_objects',[])}
    for r in results:
        r['destination_status']='existing_key_requires_content_verification' if r['s3_key'] in existing else (
            'absent_at_list_snapshot' if aws['list_prefix_verified'] else 'not_verified')
    (args.out/'manifest.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in results),encoding='utf-8')
    fields=['video_id','source_group','source_path','s3_key','s3_uri','size_bytes','sha256','expected_sha256','status','destination_status']
    with (args.out/'manifest.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(results)
    report={'scope_unique_videos':len(rows),'matched':sum(r['status']=='matched_sha256' for r in results),
        'statuses':dict(Counter(r['status'] for r in results)),
        'groups':dict(Counter(r['source_group'] for r in results)),
        'total_matched_bytes':sum(r['size_bytes'] or 0 for r in results),'scanned_roots':roots,
        'bucket':config['AWS_S3_BUCKET'],'region':config['AWS_REGION'],'prefix':config['AWS_S3_PREFIX'],
        'aws_identity_verified':bool(aws['identity']),'bucket_verified':aws['bucket_verified'],
        'region_verified':aws['region_verified'],'uploads':0,'supabase_updates':0,
        'approval_required_before_upload':True}
    (args.out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    checks={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.out.iterdir() if p.is_file()}
    (args.out/'checksums.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
