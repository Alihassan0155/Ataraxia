"""Opt-in localhost-only PostgreSQL onboarding rehearsal; no production settings."""
import hashlib,json,subprocess,uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import psycopg
from psycopg import sql
from fastapi import FastAPI,Header,HTTPException
from fastapi.testclient import TestClient
from backend.onboarding.repository import PreferenceRepository,InvalidInterests
from backend.onboarding.service import PreferenceService
from backend.onboarding.api import create_router,get_service
from backend.video_data.s3_references import load_plan,execute,sha

OUT=Path('backend/reports/onboarding_20261019')

def run():
    name='ataraxia_onboarding_'+uuid.uuid4().hex[:8];bucket='ataraxia-fyp-videos-068371986822-ap-south-1-an'
    def connection(db=name):return psycopg.connect(host='127.0.0.1',port=55439,user='postgres',dbname=db,autocommit=True,options='-c search_path=public,extensions')
    with connection('postgres') as c:
        assert str(c.execute('SELECT inet_server_addr()').fetchone()[0])=='127.0.0.1'
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    with connection() as c:
        c.execute('CREATE SCHEMA extensions');c.execute("CREATE EXTENSION vector WITH SCHEMA extensions VERSION '0.8.2'")
        c.execute('CREATE SCHEMA auth');c.execute('CREATE TABLE auth.users(id uuid PRIMARY KEY)')
        c.execute("CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$")
        c.execute('GRANT USAGE ON SCHEMA auth TO authenticated')
    backup=Path('backend/reports/s3_references_20261018/production_execution/fresh_backup/video_tables.dump')
    expected=json.loads((backup.parent/'manifest.json').read_text())['sha256'];assert sha(backup)==expected
    result=subprocess.run(['backend/reports/catalogue_final_20261018/tools/pgsql/bin/pg_restore.exe','-h','127.0.0.1','-p','55439','-U','postgres','-d',name,'--exit-on-error',str(backup)],capture_output=True)
    if result.returncode:raise RuntimeError('Local restore failed')
    with connection() as c:execute(c,load_plan('backend/reports/s3_references_20261018'))
    def fingerprints():
        with connection() as c:
            result={}
            for t in ['videos','video_context','affect_annotations','video_semantics','video_embeddings','processing_runs','processing_jobs','interest_categories']:
                key='video_id' if t=='videos' else 'id'
                result[t]=c.execute(sql.SQL("SELECT count(*),md5(string_agg(md5(row_to_json(t)::text),'' ORDER BY {} COLLATE \"C\")) FROM public.{} t").format(sql.Identifier(key),sql.Identifier(t))).fetchone()
            return result
    baseline=fingerprints()
    migration=Path('backend/migrations/003_user_interest_preferences.sql')
    with connection() as c:c.execute(migration.read_text(encoding='utf-8-sig'))
    a,b=uuid.uuid4(),uuid.uuid4()
    with connection() as c:c.execute('INSERT INTO auth.users(id) VALUES(%s),(%s)',(a,b))
    repo=PreferenceRepository(connection);service=PreferenceService(repo,bucket)
    categories=repo.interests();assert len(categories)==18 and all(r['name'].lower()!='unknown' for r in categories)
    ids=[r['id'] for r in categories[:3]]
    assert repo.preferences(a)==[]
    repo.replace(a,ids[:2]);repo.replace(b,ids[2:])
    assert {r['id'] for r in repo.preferences(a)}==set(ids[:2])
    with connection() as c:before=c.execute('SELECT * FROM user_interest_preferences WHERE user_id=%s ORDER BY category_id',(a,)).fetchall()
    repo.replace(a,list(reversed(ids[:2])))
    with connection() as c:assert before==c.execute('SELECT * FROM user_interest_preferences WHERE user_id=%s ORDER BY category_id',(a,)).fetchall()
    with connection() as c:unknown=c.execute("SELECT id FROM interest_categories WHERE name='unknown'").fetchone()[0]
    for invalid in [['invalid'],[unknown],[ids[0],ids[0]]]:
        try:repo.replace(a,invalid)
        except InvalidInterests:pass
        else:raise AssertionError('Invalid category accepted')
    assert {r['id'] for r in repo.preferences(a)}==set(ids[:2])
    repo.replace(a,[]);assert repo.preferences(a)==[] and len(repo.preferences(b))==1
    def replace(values):return repo.replace(a,values)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(replace,[ids[:2],ids[2:]]))
    assert {r['id'] for r in repo.preferences(a)} in (set(ids[:2]),set(ids[2:]))
    # Failure after replacement begins must not leave a partially replaced set.
    repo.replace(a,ids[:1])
    with connection() as c:
        c.execute(sql.SQL("""CREATE FUNCTION public.reject_test_preference() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN IF NEW.category_id={} THEN RAISE EXCEPTION 'simulated database failure'; END IF;
          RETURN NEW; END $$""").format(sql.Literal(ids[2])))
        c.execute('CREATE TRIGGER reject_test_preference BEFORE INSERT ON public.user_interest_preferences FOR EACH ROW EXECUTE FUNCTION public.reject_test_preference()')
    try:repo.replace(a,ids[1:])
    except psycopg.errors.RaiseException:pass
    else:raise AssertionError('Injected database failure did not fire')
    assert {r['id'] for r in repo.preferences(a)}==set(ids[:1])
    with connection() as c:
        c.execute('DROP TRIGGER reject_test_preference ON public.user_interest_preferences')
        c.execute('DROP FUNCTION public.reject_test_preference()')
    # Direct authenticated SQL can read only its own preferences and cannot write.
    with connection() as c:
        with c.transaction():
            c.execute('SET LOCAL ROLE authenticated');c.execute("SELECT set_config('request.jwt.claim.sub',%s,true)",(str(a),))
            assert not c.execute('SELECT * FROM public.user_interest_preferences WHERE user_id=%s',(b,)).fetchall()
            try:
                with c.transaction():
                    c.execute('INSERT INTO public.user_interest_preferences(user_id,category_id) VALUES(%s,%s)',(a,ids[0]))
            except psycopg.errors.InsufficientPrivilege:pass
            else:raise AssertionError('Direct client write permitted')
    # Metadata-only rows with no embeddings remain eligible.
    with connection() as c:
        video,category=c.execute("""SELECT v.video_id,c.id FROM videos v JOIN interest_categories c ON c.name=v.payload->>'category'
            WHERE NOT EXISTS(SELECT 1 FROM video_embeddings e WHERE e.video_id=v.video_id) LIMIT 1""").fetchone()
    repo.replace(a,[category]);selected,pool=repo.candidate_pool(a);assert video in {r['video_id'] for r in pool}
    # HTTP integration uses test-only identities; production routes use Supabase Auth.
    def authenticated(authorization:str|None=Header(default=None)):
        user={'Bearer A':a,'Bearer B':b}.get(authorization)
        if user is None:raise HTTPException(401,'Invalid token')
        return {'id':str(user)}
    app=FastAPI();app.include_router(create_router(authenticated));app.dependency_overrides[get_service]=lambda:service
    with TestClient(app) as client:
        assert client.get('/users/me/interests').status_code==401
        assert client.get('/users/me/interests',headers={'Authorization':'Bearer A'}).json()['interests'][0]['id']==category
        response=client.get('/recommendations/cold-start',headers={'Authorization':'Bearer A'})
        assert response.status_code==200;body=response.json();assert 0<len(body['videos'])<=50
        assert len({r['video_id'] for r in body['videos']})==body['count']
        assert all(r['category_id']==category for r in body['videos'])
        assert client.put('/users/me/interests',headers={'Authorization':'Bearer A'},json={'category_ids':[unknown]}).status_code==422
    # Exercise unavailable-media filtering against committed isolated data.
    with connection() as c:
        original=c.execute('SELECT availability,media_uri FROM videos WHERE video_id=%s',(video,)).fetchone()
        c.execute('UPDATE videos SET availability=%s WHERE video_id=%s',('missing',video))
    assert video not in {r['video_id'] for r in repo.candidate_pool(a)[1]}
    with connection() as c:
        c.execute('UPDATE videos SET availability=%s,media_uri=%s WHERE video_id=%s',(original[0],'s3://wrong-bucket/videos/finevideo/'+video+'.mp4',video))
    assert video not in {r['video_id'] for r in service.candidates(a)['videos']}
    with connection() as c:
        c.execute('UPDATE videos SET media_uri=%s WHERE video_id=%s',(original[1],video))
    assert fingerprints()==baseline
    report={'isolated_database':name,'production_writes':0,'migration_sha256':sha(migration),'taxonomy_selectable':18,'multiple_interests_persisted':True,'idempotent_created_at_preserved':True,'invalid_unknown_duplicate_rejected':True,'empty_selection_clears_only_own_data':True,'concurrent_replacement_atomic':True,'database_failure_rolls_back_entire_replacement':True,'rls_user_isolation':True,'direct_authenticated_writes_denied':True,'metadata_only_video_without_embeddings_eligible':video,'http_integration_passed':True,'all_original_eight_tables_unchanged':True}
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'integration_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))

if __name__=='__main__':run()
