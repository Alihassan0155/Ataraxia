"""Read-only production metadata profiling plus isolated HTTP fixture timings.

No real user is selected or impersonated; both variants use the same two public
taxonomy categories as a fixture. No preference write or S3 object request occurs.
"""
import ast
import json
from pathlib import Path
import statistics
import subprocess
from time import perf_counter
from uuid import uuid4

import boto3
from botocore.config import Config
from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.testclient import TestClient
import psycopg
from psycopg.rows import dict_row
from backend.video_data.config import DatabaseSettings
from backend.onboarding.api import get_service
from backend.onboarding.delivery import create_delivery_router
from backend.onboarding.repository import CANDIDATE_POOL_SQL
from backend.onboarding.service import PreferenceService


def run():
    target = Path('backend/reports/feed_latency_20261020')
    target.mkdir(parents=True, exist_ok=True)
    report = {'scope': 'Local fixture HTTP identity; read-only production video/taxonomy SQL only.',
              'production_preference_save_ms': None, 'iphone_first_frame_ms': None,
              'authentication_provider_latency_included': False, 'production_writes': 0}
    try:
        settings = DatabaseSettings.load()
        started = perf_counter()
        with psycopg.connect(settings.dsn, sslmode='require', connect_timeout=15,
                autocommit=True, row_factory=dict_row, options='-c statement_timeout=15000') as conn:
            report['cold_connection_ms'] = round((perf_counter()-started)*1000, 2)
            with conn.transaction():
                conn.execute('SET TRANSACTION READ ONLY')
                assert conn.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
                categories = conn.execute("""SELECT c.id,c.name,c.taxonomy_version,count(*) n
                    FROM public.videos v JOIN public.interest_categories c ON c.name=v.payload->>'category'
                    WHERE c.is_onboarding AND v.availability='s3_verified'
                    GROUP BY c.id,c.name,c.taxonomy_version ORDER BY n DESC LIMIT 2""").fetchall()
            ids = [r['id'] for r in categories]
            source = subprocess.check_output(['git', 'show', '1d47050ddf8de518c4ad8097576e875be5f39a6e:backend/onboarding/repository.py']).decode('utf-8-sig')
            tree = ast.parse(source)
            legacy = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'candidate_pool')
            old_query = next(node.value for node in ast.walk(legacy) if isinstance(node, ast.Constant)
                             and isinstance(node.value, str) and 'SELECT v.video_id' in node.value)
            # Substitute a category-only fixture for the preferences relation. This
            # profiles both query shapes without reading production user data.
            new_query = CANDIDATE_POOL_SQL.replace('FROM public.user_interest_preferences p',
                'FROM (SELECT unnest(%s::text[]) AS category_id) p').replace('p.user_id = %s AND ', '')
            with conn.transaction():
                conn.execute('SET TRANSACTION READ ONLY')
                plan = conn.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+new_query, (ids,)).fetchone()['QUERY PLAN'][0]
                old_rows = conn.execute(old_query, (ids,)).fetchall()
                new_rows = conn.execute(new_query, (ids,)).fetchall()
                assert [{k:v for k,v in row.items() if k not in ('taxonomy_version','media_sha256')} for row in new_rows if row['video_id']] == old_rows
            report.update(sql_rows_equivalent=True, read_only_transactions_verified=True, query_plan=plan)
            env = dotenv_values('backend/.env')
            signer = boto3.Session(aws_access_key_id=env.get('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=env.get('AWS_SECRET_ACCESS_KEY'), aws_session_token=env.get('AWS_SESSION_TOKEN'),
                region_name=env.get('AWS_REGION')).client('s3', endpoint_url=f"https://s3.{env['AWS_REGION']}.amazonaws.com", config=Config(signature_version='s3v4',s3={'addressing_style':'virtual'}))
            bucket = env['S3_BUCKET_NAME']
            timings = {'old_db_ms': [], 'new_db_ms': []}
            class Repo:
                def __init__(self, optimized): self.optimized = optimized
                def candidate_pool(self, user_id):
                    started = perf_counter()
                    with conn.transaction():
                        if self.optimized:
                            with conn.pipeline():
                                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                                cursor = conn.execute(new_query, (ids,))
                            rows = cursor.fetchall()
                            rows = [{k:v for k,v in row.items() if k!='taxonomy_version'} for row in rows if row['video_id']]
                        else:
                            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                            conn.execute('SELECT id,name,taxonomy_version FROM interest_categories WHERE id=ANY(%s::text[]) ORDER BY name,id', (ids,)).fetchall()
                            rows = conn.execute(old_query, (ids,)).fetchall()
                    timings['new_db_ms' if self.optimized else 'old_db_ms'].append((perf_counter()-started)*1000)
                    return categories, rows
            old_service = PreferenceService(Repo(False), bucket)
            new_service = PreferenceService(Repo(True), bucket)
            app = FastAPI()
            uid = str(uuid4())
            def fixture_identity(): return {'id': uid}
            def media(vid):
                with conn.transaction():
                    with conn.pipeline():
                        conn.execute('SET TRANSACTION READ ONLY')
                        cursor = conn.execute('SELECT video_id,media_uri,availability,media_sha256 FROM videos WHERE video_id=%s', (vid,))
                    return cursor.fetchone()
            app.include_router(create_delivery_router(fixture_identity, signer, bucket, media_lookup=media))
            app.dependency_overrides[get_service] = lambda: new_service
            @app.get('/baseline')
            def baseline():
                videos=[]
                for row in old_service.candidates(uid)['videos']:
                    vid=row['video_id']; key=('videos/finevideo/' if vid.startswith('FV') else 'videos/tiktok/')+vid+'.mp4'
                    url=signer.generate_presigned_url('get_object',Params={'Bucket':bucket,'Key':key},ExpiresIn=300)
                    videos.append({'video_key':key,'playback_url':url})
                return {'videos':videos}
            runs=[]
            with TestClient(app) as client:
                for _ in range(5):
                    started=perf_counter(); old=client.get('/baseline'); old_ms=(perf_counter()-started)*1000
                    started=perf_counter(); first=client.get('/recommendations/feed'); first_ms=(perf_counter()-started)*1000
                    assert old.status_code == first.status_code == 200
                    page=first.json(); count=len(page['videos']); cursor=page['next_cursor']; initial_signed=bool(page.get('initial_playback'))
                    started=perf_counter(); playback=client.get('/catalogue/videos/'+page['videos'][0]['video_id']+'/playback'); playback_ms=(perf_counter()-started)*1000
                    assert playback.status_code==200
                    started=perf_counter()
                    while cursor:
                        response=client.get('/recommendations/feed',params={'cursor':cursor,'page_size':45})
                        assert response.status_code==200
                        page=response.json(); count+=len(page['videos']); cursor=page['next_cursor']
                    rest_ms=(perf_counter()-started)*1000
                    runs.append({'before_first_response_ms':old_ms,'after_first_candidates_ms':first_ms,
                        'after_first_url_ms':first_ms if initial_signed else first_ms+playback_ms,'remaining_pages_ms':rest_ms,
                        'after_all_metadata_ms':first_ms+rest_ms,'before_response_bytes':len(old.content),
                        'after_first_response_bytes':len(first.content),'candidate_count':count})
            report['runs']=[{k:round(v,2) for k,v in row.items()} for row in runs]
            report['medians']={k:round(statistics.median(row[k] for row in runs),2) for k in runs[0]}
            report['database_medians']={k:round(statistics.median(v),2) for k,v in timings.items()}
    except Exception as exc:
        report['error_type']=type(exc).__name__
    (target/'comparison.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('query_plan','runs')},indent=2))


if __name__=='__main__': run()
