"""Backend video-data audit/import CLI. Defaults to local dry-run only."""
import argparse
import collections
from contextlib import nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid

from .artifacts import Reader, canonical, fingerprint, metadata_rows, video, context_entity, affect, entity, categories, under


REPO = Path(__file__).resolve().parents[2]


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    tmp.replace(path)


def synchronize(root, runs, affect_files, manifest_path, repository=None, limit=0):
    reader = Reader(root)
    _, read, _, load_metadata, _, _, _, annotation_schema = reader.api
    current = metadata_rows(manifest_path)
    report = {'at':datetime.now(timezone.utc).isoformat(), 'mode':'apply' if repository else 'dry-run',
              'successful':0,'skipped':0,'incomplete':0,'failed':0,'valid_semantic_records':0,
              'valid_affect_records':0,'entities':{},'database_changes':{'inserted':0,'updated':0,'skipped':0},
              'issues':[], 'run_names':[], 'models_executed':0, 'storage_uploads':0}
    seen = set()
    semantic_ids, affect_ids = set(), set()
    attempted = 0

    def issue(kind, source, message):
        report[kind] += 1
        report['issues'].append({'kind':kind,'source':str(source),'message':message})

    def put(items):
        nonlocal attempted
        if limit and attempted>=limit:
            return
        attempted += 1
        # Dedup within this snapshot; database remains authoritative on resume.
        unique = []
        for item in items:
            if item['table']=='videos' and item['key'] in current:
                item = video(item['key'],current[item['key']])
            identity = (item['table'],item['key'],item['content_hash'])
            if identity not in seen:
                unique.append(item)
        if not unique:
            report['skipped'] += 1
            return
        if repository:
            try:
                changes = repository.put_bundle(unique)
            except Exception as exc:
                # DB exception strings may contain credentials/connection info.
                issue('failed', 'database transaction', 'Transaction failed; SQLSTATE='+str(getattr(exc,'sqlstate',None))+'; safe to resume')
                return
            for key,value in changes.items():
                report['database_changes'][key] += value
            report['skipped' if changes['inserted']==changes['updated']==0 else 'successful'] += 1
        else:
            report['successful'] += 1
        for item in unique:
            seen.add((item['table'],item['key'],item['content_hash']))
            report['entities'][item['table']] = report['entities'].get(item['table'],0)+1

    # Canonical onboarding taxonomy is reused, including unknown as non-onboarding.
    put(categories(root/'semantic_pipeline/configs/taxonomy.json'))
    for run in runs:
        if limit and attempted>=limit:
            break
        try:
            frozen = read(run/'frozen.json')
            rows = load_metadata(run)
        except (OSError,ValueError,KeyError) as exc:
            issue('incomplete',run,type(exc).__name__+': missing/invalid frozen metadata')
            continue
        report['run_names'].append(run.name)
        run_id = fingerprint(['semantic',run.relative_to(root).as_posix(),frozen['fingerprint']])
        run_entity = entity('processing_runs',run_id,
                            {'name':run.name,'path':run.relative_to(root).as_posix(),'frozen':frozen},
                            kind='semantic',name=run.name)
        # A fixed list of atomic completion files, not a growing log or model call.
        complete_paths = sorted((run/'videos').glob('*/*/record.json'))
        for path in complete_paths:
            if limit and attempted>=limit:
                break
            try:
                items = reader.semantic_bundle(run,path,frozen,rows)
                report['valid_semantic_records'] += 1
                semantic_ids.add(items[0]['key'])
                put(items)
            except FileNotFoundError:
                issue('incomplete',path,'Required source/context/embedding file missing')
            except Exception as exc:
                issue('failed',path,type(exc).__name__+': artifact validation failed')
        for state_path in sorted((run/'videos').glob('*/*/state.json')):
            if limit and attempted>=limit:
                break
            try:
                state = read(state_path)
                vid = state_path.parent.parent.name
                if vid not in rows:
                    raise ValueError('Job ID absent from frozen manifest')
                if state.get('status')!='complete':
                    report['incomplete'] += 1
                # State snapshots are immutable versions, preserving failures/retries.
                payload = {'video_id':vid,'source_fingerprint':state_path.parent.name,'state':state}
                job = entity('processing_jobs',fingerprint([run_id,payload]),payload,
                             video_id=vid,run_id=run_id,stage=state.get('stage','complete' if state.get('status')=='complete' else 'unknown'),
                             status=state.get('status','unknown'),attempts=int(state.get('attempts',0)))
                if job['columns']['attempts']<0:
                    raise ValueError('Negative attempts')
                put([video(vid,rows[vid]),run_entity,job])
            except Exception as exc:
                issue('failed',state_path,type(exc).__name__+': invalid state snapshot')
    for path in affect_files:
        if limit and attempted>=limit:
            break
        if not path.exists():
            issue('incomplete',path,'Prediction file missing')
            continue
        data = path.read_bytes()
        lines = data.splitlines()
        if data and not data.endswith(b'\n'):
            lines = lines[:-1]
            issue('incomplete',path,'Trailing non-newline record deferred until complete append')
        for number,line in enumerate(lines,1):
            if limit and attempted>=limit:
                break
            try:
                item = json.loads(line.decode('utf-8-sig'))
                annotation_schema.model_validate(item)
                vid = item['video_id']
                row = current[vid]
                if not item.get('model'):
                    raise ValueError('Missing model identifier')
                ctxpath = under(root,row['context_path']) if row.get('context_path') else None
                context = read(ctxpath) if ctxpath and ctxpath.exists() else {}
                if context and context.get('video_id')!=vid:
                    raise ValueError('Context ID mismatch')
                trpath = under(root,row['transcript_path']) if row.get('transcript_path') else None
                transcript = trpath.read_text(encoding='utf-8-sig') if trpath and trpath.exists() else context.get('transcript','')
                ctx = context_entity(vid,row,context,transcript)
                report['valid_affect_records'] += 1
                affect_ids.add(vid)
                origin = reader.affect_run(path)
                put([video(vid,row),origin,ctx,affect(vid,item,origin['key'])])
            except Exception as exc:
                issue('failed',str(path)+':'+str(number),type(exc).__name__+': invalid annotation or metadata reference')
    report['scope_note'] = ('Counts are processing bundles and entity rows, not unique videos. '
                            'Incomplete includes job states; valid earlier stages may still be imported.')
    report['unique_semantic_videos'] = len(semantic_ids)
    report['unique_explicit_affect_videos'] = len(affect_ids)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('inspect','sync'))
    parser.add_argument('--annotation-root',type=Path,default=REPO/'annotation')
    parser.add_argument('--run',action='append',help='Semantic run name; repeatable. Default: all initialized runs')
    parser.add_argument('--affect',action='append',type=Path,help='Prediction JSONL relative to annotation root; repeatable')
    parser.add_argument('--metadata',type=Path,default=Path('data/normalized/preprocessed_merged_v2/ready_metadata.csv'))
    parser.add_argument('--env-file',type=Path)
    parser.add_argument('--table-map',type=Path,help='JSON logical-to-existing table names after schema review')
    parser.add_argument('--report-dir',type=Path,default=REPO/'backend/reports/video_sync')
    parser.add_argument('--limit',type=int,default=0,help='Limit processing bundles, including taxonomy/jobs; zero=all')
    parser.add_argument('--apply',action='store_true',help='WRITE existing database only after explicit approval')
    parser.add_argument('--allow-live-writes',action='store_true',help='Second explicit confirmation for approved writes')
    parser.add_argument('--watch',action='store_true',help='Foreground incremental polling until Ctrl+C')
    parser.add_argument('--current-only',action='store_true',
                        help='READ ONLY: prepare a current catalogue delta for existing DB video IDs; no live apply')
    parser.add_argument('--poll-seconds',type=int,default=60)
    args = parser.parse_args(argv)
    if args.current_only:
        if args.command!='sync' or args.apply or args.allow_live_writes or args.watch or args.limit or args.run or args.affect or args.table_map or args.env_file:
            parser.error('--current-only is a read-only, single-pass catalogue planner; apply/watch/custom-source flags are not supported')
        from .catalogue import capture, prepare, export_sql
        # No default-directory overwrite: each planning snapshot must be immutable.
        target=args.report_dir
        if target.exists():
            parser.error('--current-only requires a new --report-dir to preserve earlier snapshots')
        target.mkdir(parents=True,exist_ok=False)
        capture(target/'production_snapshot')
        result=prepare(target/'production_snapshot',target/'current_stage',args.annotation_root,'imported')
        export_sql(target/'production_snapshot',target/'current_stage',target/'sql_review')
        print(json.dumps(result,indent=2,ensure_ascii=False))
        print('READ ONLY planning complete. SQL is rollback-only; no production writes executed.')
        return 0
    if args.limit<0 or args.poll_seconds<10:
        parser.error('Limit must be nonnegative; poll interval at least 10 seconds')
    if args.apply != args.allow_live_writes:
        parser.error('Approved writes require BOTH --apply and --allow-live-writes')
    mapping = json.loads(args.table_map.read_text()) if args.table_map else None
    from .config import DatabaseSettings, connect, TABLES
    if args.command=='inspect':
        if args.apply or args.watch:
            parser.error('inspect is read-only and single-pass')
        from .repository import inspect_schema, compatibility
        try:
            settings = DatabaseSettings.load(args.env_file)
            with connect(settings) as conn:
                inventory = inspect_schema(conn)
            names = {name:name for name in TABLES}
            names.update(mapping or {})
            inventory['compatibility'] = compatibility(inventory,settings.schema,names)
        except ImportError:
            print('Database driver unavailable; install backend/requirements-import.txt into the backend import environment.',file=sys.stderr)
            return 2
        except ValueError as exc:
            print(str(exc),file=sys.stderr)
            return 2
        except Exception as exc:
            print('Read-only database inspection failed; SQLSTATE='+str(getattr(exc,'sqlstate',None)),file=sys.stderr)
            return 2
        atomic_json(args.report_dir/'schema_report.json',inventory)
        print(json.dumps(inventory['compatibility'],indent=2))
        print('Full schema/bucket metadata report: '+str(args.report_dir/'schema_report.json'))
        return 0
    root = args.annotation_root.resolve()
    reader = Reader(root)  # Local imports/validators only, never loads models.
    settings = DatabaseSettings.load(args.env_file) if args.apply else None
    if args.run:
        import re
        if any(not re.fullmatch(r'[A-Za-z0-9_-]+',name) for name in args.run):
            parser.error('Invalid run name')
    try:
        while True:
            run_base = root/'semantic_pipeline/runs'
            runs = [run_base/name for name in args.run] if args.run else sorted(p.parent for p in run_base.glob('*/frozen.json'))
            paths = [under(root,p) for p in args.affect] if args.affect else [root/'runs/gemini_full_remaining_20261012/predictions/gemini/annotations.jsonl']
            connection = connect(settings) if settings else nullcontext(None)
            with connection as conn:
                if conn is not None:
                    from .repository import Repository
                    repository = Repository(conn,settings.schema,mapping)
                else:
                    repository = None
                report = synchronize(root,runs,paths,under(root,args.metadata),repository,args.limit)
            atomic_json(args.report_dir/'summary.json',report)
            print(json.dumps({k:v for k,v in report.items() if k!='issues'},indent=2),flush=True)
            if not args.watch:
                return 1 if report['failed'] else 0
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        print('Stopped. Committed bundles are preserved; repeat the command to resume.')
        return 0
    except Exception as exc:
        # Never echo connection strings or driver exceptions.
        print('Sync stopped: '+type(exc).__name__+'; use dry-run/schema inspection to diagnose. No models were run.',file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
