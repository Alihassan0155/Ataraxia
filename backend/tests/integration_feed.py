"""Localhost-only SQL equivalence and preference timing; never loads .env."""
import json, random, statistics, time, unittest
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from backend.onboarding.repository import PreferenceRepository
from backend.onboarding.service import PreferenceService
from backend.onboarding.sampling import balanced_sample


def run():
    name = 'ataraxia_feed_' + uuid4().hex[:10]
    def connect(db=name):
        return psycopg.connect(host='127.0.0.1', port=55439, user='postgres', dbname=db, autocommit=True)
    with connect('postgres') as conn:
        assert str(conn.execute('SELECT inet_server_addr()').fetchone()[0]) == '127.0.0.1'
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    uid, other = uuid4(), uuid4()
    bucket = 'local-fixture'
    try:
        with connect() as conn:
            conn.execute('CREATE TABLE interest_categories(id text PRIMARY KEY,name text,taxonomy_version text,is_onboarding boolean)')
            conn.execute('CREATE TABLE user_interest_preferences(user_id uuid,category_id text,created_at timestamptz DEFAULT now(),PRIMARY KEY(user_id,category_id))')
            conn.execute('CREATE TABLE videos(video_id text PRIMARY KEY,title text,language text,duration_seconds float,orientation text,media_uri text,availability text,media_sha256 text,payload jsonb)')
            for category in ['a', 'b', 'empty']:
                conn.execute('INSERT INTO interest_categories VALUES(%s,%s,%s,true)', (category,category,'test'))
            for n in range(100):
                vid=f'FV{n:06}';category='a' if n<50 else 'b'
                conn.execute('INSERT INTO videos VALUES(%s,%s,%s,10,%s,%s,%s,%s,%s)',
                    (vid,'title','en','vertical',f's3://{bucket}/videos/finevideo/{vid}.mp4','s3_verified','a'*64,json.dumps({'category':category})))
        repo=PreferenceRepository(connect)
        samples=[]
        for _ in range(5):
            t=time.perf_counter();repo.replace(uid,['a','b','empty']);samples.append((time.perf_counter()-t)*1000)
        selected, rows=repo.candidate_pool(uid)
        assert {r['id'] for r in selected}=={'a','b','empty'}
        assert len(rows)==100 and len({r['video_id'] for r in rows})==100
        assert [r['video_id'] for r in rows]==sorted(r['video_id'] for r in rows)
        actual=PreferenceService(repo,bucket,random.Random(3)).candidates(uid)
        groups={category:[] for category in ['a','b','empty']}
        for row in rows:
            groups[row['category_id']].append({k:row[k] for k in ('video_id','title','language','duration_seconds','orientation','category_id','category_name')})
        assert actual['videos']==balanced_sample(groups,50,random.Random(3))
        assert len(actual['videos'])==50
        assert sum(v['category_id']=='a' for v in actual['videos'])==25
        assert repo.candidate_pool(other)==([],[])
        repo.replace(uid,['empty']);assert repo.candidate_pool(uid)[1]==[]
        # Atomic failure leaves previous preferences unchanged.
        try:repo.replace(uid,['invalid'])
        except ValueError:pass
        assert [r['id'] for r in repo.preferences(uid)]==['empty']
        out={'status':'passed','scope':'isolated localhost fixture only','candidate_sql_equivalence':True,
             'seeded_sampler_unchanged':True,'unique_candidates':50,'balanced_categories':[25,25],
             'empty_category_preserved':True,'user_isolation':True,'atomic_invalid_update':True,
             'preference_replace_local_median_ms':round(statistics.median(samples),3)}
        target=Path('backend/reports/feed_latency_20261020/integration.json')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(out,indent=2)+'\n')
        print(json.dumps(out))
    finally:
        with connect('postgres') as conn:
            conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


if __name__=='__main__':run()
