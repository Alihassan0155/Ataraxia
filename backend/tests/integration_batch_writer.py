"""Opt-in integration check on localhost only; never loads production settings."""
import json
from pathlib import Path
import sqlite3
import subprocess
import uuid
import psycopg
from psycopg import sql
from backend.video_data.batch_sync import DurableQueue
from backend.video_data.batch_writer import BatchWriter
from backend.video_data.catalogue import load_package,validate
from backend.video_data.config import DatabaseSettings
from backend.video_data.rehearse_catalogue import tables,compare


def run():
    package=Path('backend/reports/catalogue_final_20261018').resolve()
    target=Path('backend/reports/automatic_batch_sync_20261018').resolve()
    database='ataraxia_batch_test_'+uuid.uuid4().hex[:8]
    def conn(db=database):
        return psycopg.connect(host='127.0.0.1',port=55439,user='postgres',dbname=db,
                              autocommit=True,options='-c search_path=public,extensions')
    with conn('postgres') as c:
        assert str(c.execute('SELECT inet_server_addr()').fetchone()[0])=='127.0.0.1'
        c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    with conn() as c:
        c.execute('CREATE SCHEMA extensions');c.execute("CREATE EXTENSION vector WITH SCHEMA extensions VERSION '0.8.2'")
    result=subprocess.run([str(package/'tools/pgsql/bin/pg_restore.exe'),'-h','127.0.0.1','-p','55439',
        '-U','postgres','-d',database,'--exit-on-error',str(package/'native_backup/video_tables.dump')],capture_output=True)
    if result.returncode:raise ValueError('Local restore failed')
    queuepath=target/(database+'.sqlite')
    source=sqlite3.connect(target/'queue.sqlite');copy=sqlite3.connect(queuepath)
    source.backup(copy);copy.close();source.close()
    before,_=load_package(package/'production_snapshot');ids={v['video_id'] for v in before['videos']}
    q=DurableQueue(queuepath,ids);q.recover_inflight()
    rows=q.claim();assert len(rows)==10
    writer=BatchWriter(Path('annotation'),ids,DatabaseSettings('unused'),conn)
    outcomes=writer(rows);insertions=dict(writer.last_insertions)
    with conn() as c:
        first=tables(c);validation=validate(first,clean=False)
        assert validation['retrieval_ready']==828
        assert {v['video_id']:v['payload'] for v in first['videos']}=={v['video_id']:v['payload'] for v in before['videos']}
    assert writer(rows)==outcomes and writer.last_insertions=={}
    q.acknowledge(rows,outcomes)
    second=q.claim();assert len(second)==10
    insert=writer._insert
    def fail_after_insert(c,item,data):
        insert(c,item,data)
        if writer.last_insertions:raise RuntimeError('simulated connection interruption')
    writer._insert=fail_after_insert
    try:writer(second)
    except RuntimeError:pass
    else:raise AssertionError('Failure injection missing')
    expected={t:[{k:v.isoformat() if hasattr(v,'isoformat') else v for k,v in row.items()} for row in rs] for t,rs in first.items()}
    with conn() as c:compare(expected,tables(c))
    writer._insert=insert
    older=dict(q.db.execute("SELECT * FROM items WHERE status='superseded' LIMIT 1").fetchone())
    assert writer([older])=={older['semantic_id']:'superseded'} and not writer.last_insertions
    q.close()
    report={'isolated_database':database,'production_writes':0,'batch_size':10,
        'ready_before':818,'ready_after':828,'insertions':insertions,
        'repeat_delivery_inserts':0,'transaction_failure_preserves_all_rows':True,
        'older_version_replay_skipped':True,'original_metadata_unchanged':True}
    (target/'writer_integration_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':print(json.dumps(run(),indent=2))
