"""Execute a separately approved, hash-verified catalogue plan. Default is offline checks only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from .catalogue import load_package,verify_stage,ORDER


def preflight(package):
    package=Path(package).resolve()
    before,_=load_package(package/'production_snapshot');after,stage=load_package(package/'current_stage')
    report=verify_stage(package/'current_stage')
    if stage['info']['report']['scope']!='imported' or len(before['videos'])!=1140:
        raise ValueError('Approved imported scope required')
    if {r['video_id'] for r in before['videos']}!={r['video_id'] for r in after['videos']}:
        raise ValueError('Video scope changed')
    backup=package/'native_backup'
    native=json.loads((backup/'manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256((backup/'video_tables.dump').read_bytes()).hexdigest()!=native['sha256']:
        raise ValueError('Native backup hash mismatch')
    rehearsal=json.loads((package/'rehearsal_report.json').read_text(encoding='utf-8'))
    recovery=json.loads((package/'post_commit_recovery_report.json').read_text(encoding='utf-8'))
    if not all(rehearsal.get(x) for x in ['native_restore_compared',
        'transactional_rollback_preserved_original','all_staged_columns_and_vectors_match',
        'duplicate_compatible_embedding_fails_closed','repeat_current_only_delta_empty']):
        raise ValueError('Rehearsal incomplete')
    if not recovery.get('all_original_columns_timestamps_and_vectors_match'):
        raise ValueError('Native recovery verification incomplete')
    path=package/'sql_final/replacement_rehearsal.sql'
    binding=json.loads((package/'sql_final/README.json').read_text(encoding='utf-8'))
    for name,folder in [('snapshot','production_snapshot'),('stage','current_stage')]:
        if hashlib.sha256((package/folder/'manifest.json').read_bytes()).hexdigest()!=binding[name+'_manifest_sha256']:
            raise ValueError('Prepared package binding changed')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=rehearsal['sql_sha256']:
        raise ValueError('Rehearsed production SQL changed')
    sql=path.read_text(encoding='utf-8')
    if not sql.endswith('ROLLBACK;\n') or '\nCOMMIT;' in sql:
        raise ValueError('Expected rollback-only reviewed source')
    return package,sql,report


def execute(package,approved=False,writers_ack=None,rollback=False):
    package,text,report=preflight(package)
    if not approved:return {'status':'offline-preflight-passed','production_writes':0,**report}
    if writers_ack is None:raise ValueError('Confirmed writer-pause acknowledgement required')
    ack=json.loads(Path(writers_ack).read_text(encoding='utf-8'))
    if ack.get('all_local_remote_writers_paused') is not True or not ack.get('confirmed_by') or not ack.get('confirmed_at_utc'):
        raise ValueError('Writer quiescence not confirmed')
    if ack.get('stage_manifest_sha256')!=hashlib.sha256((package/'current_stage/manifest.json').read_bytes()).hexdigest():
        raise ValueError('Writer acknowledgement is for a different stage')
    if rollback:
        source=package/'sql_final/rollback_after_commit_rehearsal.sql'
        proof=json.loads((package/'rollback_rehearsal_report.json').read_text(encoding='utf-8'))
        if not proof.get('post_commit_rollback_local_commit_restores_all_original_rows_and_timestamps'):
            raise ValueError('Post-commit rollback not rehearsed')
        if hashlib.sha256(source.read_bytes()).hexdigest()!=proof['rollback_source_sha256']:
            raise ValueError('Rollback SQL changed')
        text=source.read_text(encoding='utf-8')
        if not text.endswith('ROLLBACK;\n'):raise ValueError('Rollback source must be rollback-only')
    # Create a fresh execution directory so logs/SQL from prior attempts survive.
    execution=package/('approved_rollback' if rollback else 'approved_execution');execution.mkdir(exist_ok=False)
    commit=execution/'replacement_commit.sql'
    commit.write_text(text[:-len('ROLLBACK;\n')]+'COMMIT;\n',encoding='utf-8')
    from psycopg.conninfo import conninfo_to_dict
    from .config import DatabaseSettings
    info=conninfo_to_dict(DatabaseSettings.load().dsn)
    mapping={'host':'PGHOST','hostaddr':'PGHOSTADDR','port':'PGPORT','dbname':'PGDATABASE',
             'user':'PGUSER','password':'PGPASSWORD','sslrootcert':'PGSSLROOTCERT',
             'sslcert':'PGSSLCERT','sslkey':'PGSSLKEY'}
    env={k:v for k,v in os.environ.items() if k not in mapping.values()}
    for name,target in mapping.items():
        if name in info:env[target]=info[name]
    env['PGSSLMODE']='require';env['PGOPTIONS']='-c lock_timeout=5000 -c statement_timeout=120000'
    psql=package/'tools/pgsql/bin/psql.exe'
    result=subprocess.run([str(psql),'-X','--no-password','--set=ON_ERROR_STOP=1','--file='+str(commit)],
                          env=env,capture_output=True)
    (execution/'psql.log').write_bytes(result.stdout+result.stderr)
    outcome={'status':'committed' if result.returncode==0 else 'failed_or_commit_uncertain_verify_live_before_retry',
             'exit_code':result.returncode,'sql_sha256':hashlib.sha256(commit.read_bytes()).hexdigest()}
    (execution/'result.json').write_text(json.dumps(outcome,indent=2),encoding='utf-8')
    return outcome


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('package',type=Path)
    approval=parser.add_mutually_exclusive_group()
    approval.add_argument('--approved-production-commit',action='store_true')
    approval.add_argument('--approved-production-rollback',action='store_true')
    parser.add_argument('--writers-ack',type=Path)
    args=parser.parse_args(argv)
    try:
        report=execute(args.package,args.approved_production_commit or args.approved_production_rollback,
                       args.writers_ack,args.approved_production_rollback)
        print(json.dumps(report,indent=2));return 0 if report.get('exit_code',0)==0 else 1
    except Exception as exc:
        print('Execution withheld: '+type(exc).__name__+'; inspect local prerequisites.');return 1


if __name__=='__main__':raise SystemExit(main())
