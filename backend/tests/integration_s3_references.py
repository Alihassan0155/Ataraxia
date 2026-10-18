"""Localhost-only rehearsal on a fresh restored copy of the live eight tables."""
import json,subprocess,uuid,copy
from pathlib import Path
import psycopg
from psycopg import sql
from backend.video_data.s3_references import load_plan,execute,snapshot,dump,sha
from backend.video_data.repository import Repository
from backend.video_data.artifacts import video
from backend.video_data.catalogue import validate
from backend.video_data.rehearse_catalogue import tables

PACKAGE=Path('backend/reports/s3_references_20261018')

def run():
    database='ataraxia_s3_test_'+uuid.uuid4().hex[:8]
    def conn(db=database):
        return psycopg.connect(host='127.0.0.1',port=55439,user='postgres',dbname=db,autocommit=True,options='-c search_path=public,extensions')
    with conn('postgres') as c:
        assert str(c.execute('SELECT inet_server_addr()').fetchone()[0])=='127.0.0.1'
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    with conn() as c:
        c.execute('CREATE SCHEMA extensions');c.execute("CREATE EXTENSION vector WITH SCHEMA extensions VERSION '0.8.2'")
    result=subprocess.run([str(Path('backend/reports/catalogue_final_20261018/tools/pgsql/bin/pg_restore.exe')),'-h','127.0.0.1','-p','55439','-U','postgres','-d',database,'--exit-on-error',str(PACKAGE/'native_backup/video_tables.dump')],capture_output=True)
    if result.returncode:raise RuntimeError('Isolated native restore failed')
    plan=load_plan(PACKAGE);report={'database':database,'production_writes':0}
    with conn() as c:
        baseline=snapshot(c)
        assert baseline[1]==plan['invariants']
        report['native_restore_matches_live_plan']=True
        try:execute(c,plan,fail_after=5)
        except RuntimeError:pass
        else:raise AssertionError('Missing injected failure')
        assert snapshot(c)==baseline;report['injected_failure_atomic_rollback']=True
        report['apply']=execute(c,plan)
        assert report['apply']['changed']==1140
        report['repeat_apply']=execute(c,plan);assert report['repeat_apply']['changed']==0
        data=tables(c);validation=validate(data,clean=False)
        assert validation['retrieval_ready']==927
        report['retrieval_ready_after']=927;report['incomplete_preserved']=213
        repo=Repository(c)
        original=next(r for r in data['videos'] if r['video_id']=='FV000002')
        with c.transaction():
            metadata=copy.deepcopy(original['payload']);metadata['title']='Importer S3 regression test'
            item=video('FV000002',metadata)
            repo.put_bundle([item])
            current=c.execute("SELECT media_uri,availability,media_sha256,payload->>'title' FROM videos WHERE video_id='FV000002'").fetchone()
            assert current[:3]==(original['media_uri'],'s3_verified',original['media_sha256']) and current[3]==metadata['title']
            assert repo.put_bundle([item])['skipped']==1
            metadata['media_sha256']='0'*64
            try:
                with c.transaction():repo.put_bundle([video('FV000002',metadata)])
            except ValueError:pass
            else:raise AssertionError('Changed media hash accepted')
            raise psycopg.Rollback()
        report['importer_preserves_verified_storage_and_updates_metadata']=True
        report['importer_changed_media_hash_rejected']=True
        # Storage reference drift is rejected and partial earlier work rolled back.
        with c.transaction():
            c.execute("UPDATE videos SET media_uri='s3://conflict/key' WHERE video_id=%s",(plan['records'][-1]['video_id'],))
            conflict=snapshot(c)
            try:
                with c.transaction():execute(c,plan,rollback=True)
            except ValueError:pass
            else:raise AssertionError('Conflict was accepted')
            assert snapshot(c)==conflict
            raise psycopg.Rollback()
        report['storage_conflict_rejected_atomically']=True
        with c.transaction():
            c.execute("UPDATE videos SET title='concurrent metadata' WHERE video_id='FV000002'")
            try:
                with c.transaction():execute(c,plan,rollback=True)
            except ValueError:pass
            else:raise AssertionError('Metadata conflict accepted')
            raise psycopg.Rollback()
        report['unrelated_metadata_change_rejected']=True
        with c.transaction():
            c.execute("SELECT video_id FROM videos WHERE video_id='FV000002' FOR UPDATE")
            with conn() as second:
                second.execute("SET lock_timeout='100ms'")
                try:second.execute("UPDATE videos SET availability=availability WHERE video_id='FV000002'")
                except psycopg.errors.LockNotAvailable:pass
                else:raise AssertionError('Concurrent writer bypassed row lock')
        report['concurrent_row_lock_blocks_writer']=True
        report['rollback']=execute(c,plan,rollback=True)
        assert snapshot(c)==baseline
        assert execute(c,plan,rollback=True)['changed']==0
        report['rollback_restores_every_original_column']=True
        report['rollback_idempotent']=True
        # Ordinary unverified local references retain normal metadata-upsert behavior.
        with c.transaction():
            metadata=copy.deepcopy(original['payload']);metadata['title']='Local metadata import regression'
            repo.put_bundle([video('FV000002',metadata)])
            local=c.execute("SELECT media_uri,availability,payload->>'title' FROM videos WHERE video_id='FV000002'").fetchone()
            assert local==(metadata['file_path'],'local_reference_only',metadata['title'])
            raise psycopg.Rollback()
        assert snapshot(c)==baseline
        report['ordinary_metadata_import_preserved']=True
    report['bindings']={'plan_sha256':sha(PACKAGE/'plan.json'),
                        'utility_sha256':sha('backend/video_data/s3_references.py'),
                        'repository_sha256':sha('backend/video_data/repository.py'),
                        'backup_sha256':sha(PACKAGE/'native_backup/video_tables.dump')}
    (PACKAGE/'rehearsal.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':print(json.dumps(run(),indent=2))
