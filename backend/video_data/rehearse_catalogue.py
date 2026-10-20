"""Rehearse prepared SQL on a disposable localhost database ONLY.

Never reads backend/.env. Never connects to Supabase. Requires the restored
eight-table baseline in database ataraxia_rehearsal on 127.0.0.1:55439.
"""
import json
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
import numpy as np
import psycopg
from psycopg import sql
from .catalogue import ORDER,load_package,validate,key,vector_array,changes


def local_connection():
    conn=psycopg.connect(host='127.0.0.1',port=55439,user='postgres',
        dbname='ataraxia_rehearsal',sslmode='disable',connect_timeout=5,autocommit=True)
    address,database=conn.execute('SELECT inet_server_addr(),current_database()').fetchone()
    if str(address)!='127.0.0.1' or database!='ataraxia_rehearsal':
        conn.close();raise ValueError('Disposable localhost database required')
    conn.execute('SET search_path TO public,extensions')
    return conn


def tables(conn):
    result={}
    for name in ORDER:
        cur=conn.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier('public',name)))
        result[name]=[dict(zip([x.name for x in cur.description],row)) for row in cur.fetchall()]
    return result


def compare(expected,actual):
    """Compare all expected columns, including original timestamps and vectors."""
    for table in ORDER:
        left={key(r,table):r for r in expected[table]};right={key(r,table):r for r in actual[table]}
        if left.keys()!=right.keys():raise ValueError('Identity mismatch: '+table)
        for ident,row in left.items():
            for col,value in row.items():
                observed=right[ident][col]
                if col=='embedding':
                    if not np.array_equal(vector_array(value),vector_array(observed)):
                        raise ValueError('Vector mismatch')
                else:
                    if isinstance(observed,datetime):
                        if observed!=datetime.fromisoformat(value.replace('Z','+00:00')):
                            raise ValueError('Timestamp mismatch: '+table+'.'+col)
                        continue
                    if observed!=value:raise ValueError('Column mismatch: '+table+'.'+col)


def rehearse(package):
    package=Path(package).resolve();before,_=load_package(package/'production_snapshot')
    after,_=load_package(package/'current_stage')
    prepared=package/'sql_final/replacement_rehearsal.sql'
    original=prepared.read_text(encoding='utf-8')
    assert original.endswith('ROLLBACK;\n')
    report={'production_writes':0,'host':'127.0.0.1','port':55439,
            'database':'ataraxia_rehearsal','native_restore_compared':False}
    executable=package/'tools/pgsql/bin/psql.exe'
    def execute(path,label,expected_failure=False):
        result=subprocess.run([str(executable),'-X','-h','127.0.0.1','-p','55439','-U','postgres',
            '-d','ataraxia_rehearsal','--set=ON_ERROR_STOP=1',
            '-c','SET search_path TO public,extensions','-f',str(path)],capture_output=True)
        (package/(label+'.log')).write_bytes(result.stdout+result.stderr)
        if (result.returncode!=0)!=expected_failure:
            raise ValueError(label+' unexpected exit; inspect local log')
        return result
    with local_connection() as conn:
        baseline=tables(conn);validate(baseline,clean=False);compare(before,baseline)
        report['native_restore_compared']=True
        # Supabase-only extension packages are not available in portable Windows.
        # Prove the untouched production guard rejects this environment first.
        failed=execute(prepared,'production_guard_expected_rejection',True)
        if b'Schema/security changed: extensions' not in failed.stderr:
            raise ValueError('Unexpected guard difference; cannot silently bypass')
        actual_extensions=conn.execute("SELECT e.extname,e.extversion,n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname").fetchall()
        names=['extname','extversion','nspname']
        actual_extensions=[dict(zip(names,x)) for x in actual_extensions]
        catalog=json.loads((package/'production_snapshot/catalog.json').read_text(encoding='utf-8'))
        literal=lambda v:sql.Literal(json.dumps(v,ensure_ascii=False,separators=(',',':'),sort_keys=True)).as_string()
        expected=literal(catalog['extensions'])+'::jsonb'
        replacement=literal(actual_extensions)+'::jsonb'
        if original.count(expected)!=1:raise ValueError('Extension fixture must replace exactly one guard value')
        isolated=original.replace(expected,replacement)
        report['isolated_environment_substitution']={'only':'extension inventory guard',
            'production':catalog['extensions'],'local':actual_extensions,
            'note':'Production SQL remains unchanged; all other schema/security/data guards run unchanged.'}
        rollback=package/'isolated_replacement_rollback.sql';rollback.write_text(isolated,encoding='utf-8')
        execute(rollback,'replacement_rollback')
        compare(before,tables(conn));report['transactional_rollback_preserved_original']=True
        commit=package/'isolated_replacement_commit.sql'
        commit.write_text(isolated[:-len('ROLLBACK;\n')]+'COMMIT;\n',encoding='utf-8')
        execute(commit,'replacement_local_commit')
        clean=tables(conn);report['clean_validation']=validate(clean);compare(after,clean)
        report['all_staged_columns_and_vectors_match']=True
        views={}
        for name in ['video_catalogue_current','video_catalogue_categories','video_catalogue_retrieval_ready','video_catalogue_all']:
            count,distinct=conn.execute(sql.SQL('SELECT count(*),count(DISTINCT video_id) FROM {}').format(sql.Identifier('public',name))).fetchone()
            views[name]={'rows':count,'unique_videos':distinct}
            if count!=distinct:raise ValueError('Duplicate catalogue video')
        if views['video_catalogue_all']['rows']!=1140 or views['video_catalogue_retrieval_ready']['rows']!=927:
            raise ValueError('Unexpected catalogue coverage')
        report['views']=views
        permissions={}
        for role in ['anon','authenticated','service_role']:
            allowed=[]
            for name in views:
                try:
                    with conn.transaction():
                        conn.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                        conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier('public',name))).fetchone()
                    allowed.append(name)
                except psycopg.errors.InsufficientPrivilege:pass
            permissions[role]=allowed
        if permissions['anon'] or permissions['authenticated'] or len(permissions['service_role'])!=4:
            raise ValueError('Unexpected view access')
        report['view_permissions']=permissions
        # A duplicate compatible embedding must not multiply the current row.
        with conn.transaction(force_rollback=True):
            conn.execute("INSERT INTO public.video_embeddings SELECT 'rehearsal_duplicate',video_id,run_id,semantic_id,content_hash,payload,model,revision,template_version,input_hash,embedding,created_at FROM public.video_embeddings LIMIT 1")
            count,distinct,ready=conn.execute('SELECT count(*),count(DISTINCT video_id),count(*) FILTER (WHERE retrieval_ready) FROM public.video_catalogue_current').fetchone()
            if (count,distinct,ready)!=(927,927,926):raise ValueError('Ambiguous embedding did not fail closed')
        report['duplicate_compatible_embedding_fails_closed']=True
        compare(after,tables(conn))
        delta=changes(clean,clean)
        if any(x['insert'] or x['remove'] for x in delta.values()):raise ValueError('Non-idempotent clean plan')
        report['repeat_current_only_delta_empty']=True
        report['legacy_writer']='Existing Repository guard blocks history importer when current catalogue view exists; tested by unit test.'
    report['sql_sha256']=hashlib.sha256(prepared.read_bytes()).hexdigest()
    (package/'rehearsal_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('package',type=Path)
    args=parser.parse_args()
    try:print(json.dumps(rehearse(args.package),indent=2))
    except Exception as exc:
        print('Local rehearsal stopped: '+type(exc).__name__+': '+str(exc)[:200]);raise SystemExit(1)
