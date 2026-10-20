"""Offline catalogue preparation. The only database operation is a READ ONLY snapshot.

No apply/restore/sync command is provided. Vectors are written to local archives,
never printed. Historical model artifacts are read using the original Reader.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from .artifacts import (Reader, canonical, fingerprint, metadata_rows, video,
                        context_entity, affect, entity, categories, under, validate_vector)
from .config import TABLES, DatabaseSettings, connect

ORDER = ('videos', 'processing_runs', 'video_context', 'affect_annotations',
         'video_semantics', 'video_embeddings', 'processing_jobs', 'interest_categories')
POLICY = 'catalogue-current-v1'


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('Missing timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return parsed.astimezone(timezone.utc)


def key(row, table):
    return row['video_id' if table == 'videos' else 'id']


def row_from_entity(item):
    return {('video_id' if item['table'] == 'videos' else 'id'): item['key'],
            'payload': item['payload'], 'content_hash': item['content_hash'], **item['columns']}


def vector_array(value):
    return np.array(json.loads(value) if isinstance(value, str) else value, dtype=np.float32)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def write_package(destination, tables, info, extras=None):
    """New directory only; hashes cover every file including complete vector values."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    files = {}
    for table in ORDER:
        rows = sorted(tables.get(table, []), key=lambda r: key(r, table))
        path = destination/(table+'.jsonl')
        path.write_text(''.join(canonical(r)+'\n' for r in rows), encoding='utf-8')
        files[path.name] = {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'rows':len(rows)}
    for name, value in (extras or {}).items():
        write_json(destination/name, value)
        files[name] = {'sha256':hashlib.sha256((destination/name).read_bytes()).hexdigest()}
    write_json(destination/'manifest.json', {'format':'ataraxia-catalogue-package-v1',
               'created_at':datetime.now(timezone.utc).isoformat(), 'info':info, 'files':files})
    return destination


def load_package(path):
    path = Path(path)
    manifest = json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    if manifest['format'] != 'ataraxia-catalogue-package-v1':
        raise ValueError('Unknown archive format')
    for name, spec in manifest['files'].items():
        if Path(name).name != name:
            raise ValueError('Invalid package filename')
        raw = (path/name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec['sha256']:
            raise ValueError('Archive file checksum mismatch: '+name)
        if 'rows' in spec and len(raw.splitlines()) != spec['rows']:
            raise ValueError('Archive row count mismatch: '+name)
    tables = {t:[json.loads(line) for line in (path/(t+'.jsonl')).read_text(encoding='utf-8').splitlines()]
              for t in ORDER}
    return tables, manifest


def capture(destination):
    """Consistent eight-table data archive plus schema/security catalog inventory."""
    from psycopg import sql
    settings = DatabaseSettings.load()
    with connect(settings) as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            if conn.execute('SHOW transaction_read_only').fetchone()[0] != 'on':
                raise ValueError('Read-only transaction required')
            schema = settings.schema
            tables = {}
            for table in ORDER:
                cur = conn.execute(sql.SQL('SELECT * FROM {} ORDER BY {}').format(
                    sql.Identifier(schema, table), sql.Identifier('video_id' if table=='videos' else 'id')))
                columns = [c.name for c in cur.description]
                rows = []
                for values in cur.fetchall():
                    row = dict(zip(columns, values))
                    for name, value in row.items():
                        if isinstance(value, datetime):
                            row[name] = value.isoformat()
                    rows.append(row)
                tables[table] = rows
            def catalog(query, params=(schema,)):
                cur = conn.execute(query, params)
                names = [c.name for c in cur.description]
                return [dict(zip(names, r)) for r in cur.fetchall()]
            inventory = {
                'columns':catalog("""SELECT c.relname AS table_name,a.attname AS column_name,
                    format_type(a.atttypid,a.atttypmod) AS type,a.attnotnull AS not_null,
                    pg_get_expr(d.adbin,d.adrelid) AS default_expression,a.attidentity,a.attgenerated
                    FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                    LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                    WHERE n.nspname=%s AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
                    ORDER BY c.relname,a.attnum"""),
                'constraints':catalog("""SELECT c.relname AS table_name,p.conname,p.contype,
                    p.convalidated,pg_get_constraintdef(p.oid) AS definition FROM pg_constraint p
                    JOIN pg_class c ON c.oid=p.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname=%s ORDER BY c.relname,p.conname"""),
                'indexes':catalog('SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname=%s ORDER BY tablename,indexname'),
                'security':catalog("""SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,
                    pg_get_userbyid(c.relowner) AS owner,c.relacl::text AS acl FROM pg_class c
                    JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relkind='r' ORDER BY c.relname"""),
                'policies':catalog('SELECT * FROM pg_policies WHERE schemaname=%s ORDER BY tablename,policyname'),
                'grants':catalog('SELECT table_name,grantor,grantee,privilege_type,is_grantable FROM information_schema.role_table_grants WHERE table_schema=%s ORDER BY table_name,grantee,privilege_type'),
                'triggers':catalog("""SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) AS definition
                    FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname=%s AND NOT t.tgisinternal ORDER BY c.relname,t.tgname"""),
                'inbound_fks':catalog("""SELECT n.nspname,c.relname,p.conname,pg_get_constraintdef(p.oid) AS definition
                    FROM pg_constraint p JOIN pg_class c ON c.oid=p.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                    JOIN pg_class target ON target.oid=p.confrelid JOIN pg_namespace tn ON tn.oid=target.relnamespace
                    WHERE p.contype='f' AND tn.nspname=%s AND target.relname=ANY(%s) ORDER BY n.nspname,c.relname,p.conname""", (schema,list(TABLES))),
                'extensions':catalog("SELECT e.extname,e.extversion,n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname", ()),
                'activity':catalog("""SELECT pid,state,wait_event_type,
                    query ~* '(insert|update|delete|truncate|copy)' AS possible_write
                    FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()
                    AND query ~* '(videos|video_context|affect_annotations|video_semantics|video_embeddings|processing_jobs|processing_runs|interest_categories)'
                    ORDER BY pid""", ()),
            }
            schema_signature = fingerprint({k:v for k,v in inventory.items() if k!='activity'})
            report = validate(tables, clean=False)
    write_package(destination, tables, {'kind':'read-only-production-snapshot', 'schema':schema,
                  'schema_signature':schema_signature, 'validation':report,
                  'restore_rehearsed':False, 'pg_dump_required_before_replacement':True}, {'catalog.json':inventory})
    # Reopen all files and revalidate; never claim restore rehearsal from this check.
    restored, _ = load_package(destination)
    if validate(restored, clean=False) != report:
        raise ValueError('Archive readback differs')
    return report


def dump_backup(destination, pg_dump='pg_dump', pg_restore='pg_restore'):
    """Optional native, read-only eight-table dump; never put credentials in argv.

    This does not restore anything. An isolated restore rehearsal remains required.
    Both PostgreSQL executables must already be installed by the operator.
    """
    import os
    import shutil
    import subprocess
    from psycopg.conninfo import conninfo_to_dict
    dump=shutil.which(str(pg_dump));restore=shutil.which(str(pg_restore))
    if not dump or not restore:raise FileNotFoundError('PostgreSQL backup tools unavailable')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    settings=DatabaseSettings.load();info=conninfo_to_dict(settings.dsn)
    env=os.environ.copy()
    params={'host':'PGHOST','hostaddr':'PGHOSTADDR','port':'PGPORT','dbname':'PGDATABASE',
            'user':'PGUSER','password':'PGPASSWORD','sslrootcert':'PGSSLROOTCERT',
            'sslcert':'PGSSLCERT','sslkey':'PGSSLKEY'}
    for name,target in params.items():
        if name in info:env[target]=info[name]
    env['PGSSLMODE']='require'
    env['PGOPTIONS']='-c default_transaction_read_only=on -c lock_timeout=5000'
    args=[dump,'--no-password','--format=custom','--strict-names','--file='+str(destination/'video_tables.dump')]
    args.extend('--table='+settings.schema+'.'+t for t in ORDER)
    result=subprocess.run(args,env=env,capture_output=True,check=False)
    if result.returncode:raise RuntimeError('Native backup failed; driver output withheld')
    listing=subprocess.run([restore,'--list',str(destination/'video_tables.dump')],capture_output=True,check=False)
    if listing.returncode:raise ValueError('Native backup cannot be listed')
    toc=listing.stdout.decode('utf-8')
    for t in ORDER:
        if ' TABLE DATA '+settings.schema+' '+t+' ' not in toc:
            raise ValueError('Native backup table data absent')
    (destination/'contents.txt').write_text(toc,encoding='utf-8')
    report={'kind':'native-eight-table-backup','tables':list(ORDER),
            'sha256':hashlib.sha256((destination/'video_tables.dump').read_bytes()).hexdigest(),
            'readable_table_of_contents':True,'restore_rehearsed':False,
            'requires_original_roles_and_pgvector_extension':True}
    write_json(destination/'manifest.json',report)
    return report


def compatible(embedding, semantic):
    p = semantic['payload']
    return (embedding['semantic_id']==semantic['id'] and
            embedding['video_id']==semantic['video_id'] and embedding['run_id']==semantic['run_id'] and
            embedding['model']==p['embedding']['checkpoint'] and embedding['revision']==p['embedding']['revision'] and
            embedding['template_version']==p['template_version'] and embedding['input_hash']==p['embedding_input_sha256'] and
            embedding['payload']==p['embedding'])


def changes(before, after):
    """Plan immutable-identity deltas; re-preparing an unchanged stage is a no-op."""
    result={}
    for t in ORDER:
        old={key(r,t):r for r in before[t]};new={key(r,t):r for r in after[t]}
        # Identity collisions must not quietly overwrite provenance or metadata.
        for identity in old.keys() & new.keys():
            a={k:v for k,v in old[identity].items() if k!='created_at'}
            b={k:v for k,v in new[identity].items() if k!='created_at'}
            if t=='video_embeddings':
                a['embedding']=vector_array(a['embedding']).tolist();b['embedding']=vector_array(b['embedding']).tolist()
            if a!=b:raise ValueError('Existing identity changed: '+t)
        result[t]={'remove':sorted(old.keys()-new.keys()),'insert':sorted(new.keys()-old.keys()),
                   'unchanged':len(old.keys() & new.keys())}
    return result


def validate(tables, clean=True):
    maps = {}
    for table in ORDER:
        rows = tables.get(table, [])
        maps[table] = {key(r, table):r for r in rows}
        if len(maps[table]) != len(rows):
            raise ValueError('Duplicate primary key: '+table)
        for r in rows:
            if fingerprint(r['payload']) != r['content_hash']:
                raise ValueError('Payload hash mismatch: '+table)
        if clean and table in ('video_context','affect_annotations','processing_jobs'):
            if len({r['video_id'] for r in rows})!=len(rows):
                raise ValueError('Multiple current video records: '+table)
    for table in ORDER:
        for r in tables.get(table, []):
            if table!='videos' and 'video_id' in r and r['video_id'] not in maps['videos']:
                raise ValueError('Missing video FK: '+table)
            if 'run_id' in r and r['run_id'] not in maps['processing_runs']:
                raise ValueError('Missing run FK: '+table)
    seen = set()
    for s in tables.get('video_semantics', []):
        p=s['payload'];run=maps['processing_runs'][s['run_id']]
        if p['status']!='complete' or p['video_id']!=s['video_id'] or run['kind']!='semantic':
            raise ValueError('Invalid completed semantic identity')
        if p['run_fingerprint']!=run['payload']['frozen']['fingerprint']:
            raise ValueError('Frozen run mismatch')
        frozen=run['payload']['frozen'];config=frozen['config']
        if (p['source_fingerprint']!=fingerprint(p['source_hashes']) or
                p['definitions']!=frozen['definition_hashes'] or p['extractor']!=config['extractor'] or
                p['schema_version']!=config['schema_version'] or
                p['extraction_prompt_version']!=config['extraction_prompt_version']):
            raise ValueError('Semantic source/configuration provenance mismatch')
        if timestamp(p['extracted_at']) > timestamp(p['completed_at']):
            raise ValueError('Completion precedes extraction')
        for name, table in [('context_id','video_context'),('affect_id','affect_annotations')]:
            if s[name] not in maps[table] or maps[table][s[name]]['video_id']!=s['video_id']:
                raise ValueError('Cross-video or missing semantic FK')
        if maps['affect_annotations'][s['affect_id']]['content_hash']!=p['source_hashes']['gemini']:
            raise ValueError('Semantic source annotation hash mismatch')
        for name in ['primary_category','semantic_summary','topics','tags']:
            if s[name]!=p['semantic'][name]:
                raise ValueError('Semantic projection mismatch')
        if clean and s['video_id'] in seen:
            raise ValueError('Multiple current semantics')
        seen.add(s['video_id'])
    embedded=set(); identities=set()
    for e in tables.get('video_embeddings', []):
        s=maps['video_semantics'].get(e['semantic_id'])
        if s is None or not compatible(e,s):
            raise ValueError('Incompatible embedding')
        validate_vector(vector_array(e['embedding']))
        if e['model']!='BAAI/bge-m3' or e['payload']['dimensions']!=1024:
            raise ValueError('Wrong embedding model/dimension')
        identity=tuple(e[f] for f in ['semantic_id','run_id','model','revision','template_version','input_hash'])
        if identity in identities or (clean and e['semantic_id'] in embedded):
            raise ValueError('Duplicate current embedding')
        identities.add(identity);embedded.add(e['semantic_id'])
    for a in tables.get('affect_annotations', []):
        if a['payload']['video_id']!=a['video_id']:
            raise ValueError('Affect identity mismatch')
        for f in ['model','valence','arousal','recovery_suitability','emotions','dominant_emotion','confidence']:
            if a[f]!=a['payload'][f]:raise ValueError('Affect projection mismatch')
    for ctx in tables.get('video_context', []):
        if ctx['transcript']!=ctx['payload']['transcript'] or ctx['acoustic_features']!=ctx['payload']['acoustic_features']:
            raise ValueError('Context projection mismatch')
    return {'counts':{t:len(tables.get(t,[])) for t in ORDER},
            'unique_videos':len(maps['videos']), 'semantic_videos':len(seen),
            'retrieval_ready':len({maps['video_semantics'][sid]['video_id'] for sid in embedded}),
            'semantics_without_embedding':len(maps['video_semantics'].keys()-embedded)}


def select_latest(semantics):
    by=defaultdict(list)
    for s in semantics:
        by[s['video_id']].append(s)
    selected={};ties=[]
    for vid, items in by.items():
        # All timestamps parsed to UTC. Run names/import time never determine recency.
        latest=max(timestamp(s['payload']['completed_at']) for s in items)
        contenders=[s for s in items if timestamp(s['payload']['completed_at'])==latest]
        if len(contenders)>1:
            ties.append(vid)
            # Do not silently make an arbitrary scientific version choice.
            continue
        selected[vid]=contenders[0]
    return selected,ties


def category_resolution(metadata, semantic, mapping, taxonomy, secondary_review=None, sources=None):
    original=metadata.get('category_original','')
    missing={'','unknown','unmapped / needs review','none','null','n/a','nan'}
    valid=isinstance(original,str) and original.strip().casefold() not in missing
    canonical_category=mapping.get(original, original if original in taxonomy['categories'] else None) if valid else None
    qwen=semantic['payload']['semantic'].get('primary_category') if semantic else None
    if qwen not in taxonomy['categories'] or qwen=='unknown':qwen=None
    primary=canonical_category or (qwen if not valid else None)
    resolution={'policy':POLICY,'original_label':original,'original_metadata_category':metadata.get('category'),
            'source_manifest':metadata.get('source_manifest'), 'primary_category':primary,
            'provenance':'source_metadata' if valid else 'existing_qwen' if qwen else 'missing',
            'taxonomy_version':taxonomy['version'], 'mapping_version':'existing-dataset-MAPPING-v1',
            'effective_categories':[primary] if primary else [],
            'qwen_candidate':qwen, 'qwen_semantic_id':semantic['id'] if semantic else None,
            # Existing provenance explicitly says taxonomy membership is NOT entailment.
            'secondary_categories':[],
            'secondary_status':'equivalent_deduplicated' if qwen and qwen==primary else
                               'withheld_unverified_evidence' if qwen else 'no_candidate',
            'source_conflict':str(metadata.get('category_conflict','')).lower()=='true'}
    if secondary_review is not None:
        from ataraxia.semantic.category_ids import supported_secondary
        if supported_secondary(primary,qwen,semantic['id'] if semantic else None,secondary_review,sources):
            resolution['secondary_categories']=[qwen]
            resolution['effective_categories']=[primary,qwen]
            resolution['secondary_status']='accepted_human_evidence_review'
            resolution['secondary_review']=secondary_review.copy()
    return resolution


def prepare(snapshot, destination, root, scope):
    """Stage a complete FK closure locally, with no inference and no live writes."""
    root=Path(root).resolve();db,archive=load_package(snapshot);validate(db,clean=False)
    rows=metadata_rows(root/'data/normalized/preprocessed_merged_v2/ready_metadata.csv')
    ids=set(r['video_id'] for r in db['videos']) if scope=='imported' else set(rows)
    if ids-set(rows):raise ValueError('Imported videos absent from local manifest; scope needs review')
    # Import metadata byte-for-byte when in imported scope: do not silently refresh it.
    current={r['video_id']:r for r in db['videos']}
    pool={t:{key(r,t):r for r in db[t]} for t in ORDER}
    reader=Reader(root);issues=[];local_history=[];job_states=[];run_cache={};input_files={}
    read=reader.api[1]
    record_paths=sorted((root/'semantic_pipeline/runs').glob('*/videos/*/*/record.json'))
    for path in record_paths:
        vid=path.parent.parent.name
        if vid not in ids:continue
        run=path.parents[3]
        try:
            if run not in run_cache:run_cache[run]=(read(run/'frozen.json'),reader.api[3](run))
            frozen,frozen_rows=run_cache[run]
            items=reader.semantic_bundle(run,path,frozen,frozen_rows)
            # Verify file remained stable during validation and archive exact bytes.
            raw=path.read_bytes();record=json.loads(raw)
            sem=next(item for item in items if item['table']=='video_semantics')
            if sem['payload']!=record:raise ValueError('Local completion changed during read')
            if timestamp(record['extracted_at'])>timestamp(record['completed_at']):raise ValueError('Invalid time order')
            for item in items:
                table=item['table'];r=row_from_entity(item)
                prior=pool[table].get(key(r,table))
                if prior and prior['content_hash']!=r['content_hash']:
                    # videos use the explicit scope policy; immutable records never overwrite.
                    if table!='videos':raise ValueError('Immutable identity collision')
                if table!='videos':pool[table].setdefault(key(r,table),r)
            local_history.append({'path':path.relative_to(root).as_posix(), 'sha256':hashlib.sha256(raw).hexdigest(),
                                  'semantic_id':sem['key'],'video_id':vid})
            input_files[str(path.relative_to(root))]=hashlib.sha256(raw).hexdigest()
        except Exception as exc:
            issues.append({'source':path.relative_to(root).as_posix(),'kind':type(exc).__name__,
                           'reason':'failed existing artifact validation'})
    # Existing DB records remain valid candidates even if historical files are unavailable;
    # they passed graph/projection/hash/vector validation and are preserved in the snapshot.
    for run in sorted((root/'semantic_pipeline/runs').glob('*')):
        if not (run/'frozen.json').exists():continue
        for p in sorted((run/'videos').glob('*/*/state.json')):
            vid=p.parent.parent.name
            if vid not in ids:continue
            try:
                state=read(p);payload={'video_id':vid,'source_fingerprint':p.parent.name,'state':state}
                frozen=read(run/'frozen.json');rid=fingerprint(['semantic',run.relative_to(root).as_posix(),frozen['fingerprint']])
                rp={'name':run.name,'path':run.relative_to(root).as_posix(),'frozen':frozen}
                rr=row_from_entity(entity('processing_runs',rid,rp,kind='semantic',name=run.name))
                pool['processing_runs'].setdefault(rid,rr)
                j=row_from_entity(entity('processing_jobs',fingerprint([rid,payload]),payload,video_id=vid,run_id=rid,
                     stage=state.get('stage','complete' if state.get('status')=='complete' else 'unknown'),
                     status=state.get('status','unknown'),attempts=int(state.get('attempts',0))))
                job_states.append(j)
            except Exception as exc:issues.append({'source':p.relative_to(root).as_posix(),'kind':type(exc).__name__,'reason':'invalid state'})
    candidates=[s for s in pool['video_semantics'].values() if s['video_id'] in ids]
    selected,ties=select_latest(candidates)
    if ties:raise ValueError('Ambiguous latest completion timestamps; review tied videos')
    # Explicit affect source only: pilot/heldout are not pulled into this catalogue.
    prediction=root/'runs/gemini_full_remaining_20261012/predictions/gemini/annotations.jsonl'
    raw=prediction.read_bytes();input_files[str(prediction.relative_to(root))]=hashlib.sha256(raw).hexdigest()
    complete_lines=raw.splitlines() if raw.endswith(b'\n') else raw.splitlines()[:-1]
    for number,line in enumerate(complete_lines,1):
        try:
            item=json.loads(line.decode('utf-8-sig'));vid=item['video_id']
            if vid not in ids:continue
            reader.api[-1].model_validate(item)
            ann=row_from_entity(affect(vid,item,reader.affect_run(prediction)['key']))
            origin=row_from_entity(reader.affect_run(prediction));pool['processing_runs'].setdefault(origin['id'],origin)
            pool['affect_annotations'].setdefault(ann['id'],ann)
        except Exception as exc:issues.append({'source':'remaining annotations line '+str(number),'kind':type(exc).__name__,'reason':'invalid annotation'})
    out={t:[] for t in ORDER};missing_embeddings=[];selection=[]
    kept_affects=set();kept_contexts=set();kept_runs=set();stages=Counter();category_report=[]
    from ataraxia.datasets.normalization import MAPPING
    taxonomy=read(root/'semantic_pipeline/configs/taxonomy.json')
    jobs=defaultdict(list)
    for j in list(pool['processing_jobs'].values())+job_states:jobs[j['video_id']].append(j)
    for vid in sorted(ids):
        v=current[vid] if scope=='imported' else row_from_entity(video(vid,rows[vid]))
        out['videos'].append(v);s=selected.get(vid)
        if s:
            out['video_semantics'].append(s);kept_affects.add(s['affect_id']);kept_contexts.add(s['context_id']);kept_runs.add(s['run_id'])
            matches=[e for e in pool['video_embeddings'].values() if compatible(e,s)]
            if len(matches)>1:raise ValueError('Multiple compatible embeddings for selected semantic')
            if matches:out['video_embeddings'].append(matches[0]);stages['fully_processed']+=1
            else:missing_embeddings.append(vid);stages['semantic_without_embedding']+=1
            selection.append({'video_id':vid,'semantic_id':s['id'],'run_id':s['run_id'],
                              'completed_at':s['payload']['completed_at'],'embedding_id':matches[0]['id'] if matches else None,
                              'excluded_semantic_ids':sorted(x['id'] for x in candidates if x['video_id']==vid and x['id']!=s['id'])})
        else:
            anns=[a for a in pool['affect_annotations'].values() if a['video_id']==vid]
            # Ties are resolved by identity only for identical annotation payloads;
            # conflicting undated annotation records require review.
            if anns:
                def affect_time(a):
                    value=a['payload'].get('run_metadata',{}).get('annotated_at_utc')
                    return timestamp(value) if value else datetime.min.replace(tzinfo=timezone.utc)
                latest=max(affect_time(a) for a in anns);contenders=[a for a in anns if affect_time(a)==latest]
                if len({a['content_hash'] for a in contenders})>1:raise ValueError('Ambiguous latest affect annotation')
                ann=min(contenders,key=lambda a:a['id']);kept_affects.add(ann['id']);stages['affect_without_semantics']+=1
            else:stages['context_or_metadata_only']+=1
            # Reuse current manifest context deterministically; no models executed.
            meta=rows[vid];cp=under(root,meta['context_path']) if meta.get('context_path') else None
            tp=under(root,meta['transcript_path']) if meta.get('transcript_path') else None
            ctx=read(cp) if cp and cp.exists() else {}
            transcript=tp.read_text(encoding='utf-8-sig') if tp and tp.exists() else ctx.get('transcript','')
            if ctx:
                ce=row_from_entity(context_entity(vid,meta,ctx,transcript))
                pool['video_context'].setdefault(ce['id'],ce);kept_contexts.add(ce['id'])
        category_report.append({'video_id':vid,**category_resolution(v['payload'],s,MAPPING,taxonomy)})
        # Jobs describe only the selected successful semantic completion. Failures/retries
        # and non-selected versions remain in archive; no fabricated completion jobs.
        if s:
            relevant={j['id']:j for j in jobs[vid] if j['run_id']==s['run_id'] and j['status']=='complete'
                      and j['payload']['source_fingerprint']==s['payload']['source_fingerprint']}
            if relevant:
                if len(relevant)>1:raise ValueError('Multiple complete state snapshots require review')
                out['processing_jobs'].append(next(iter(relevant.values())))
    out['affect_annotations']=[pool['affect_annotations'][x] for x in sorted(kept_affects)]
    out['video_context']=[pool['video_context'][x] for x in sorted(kept_contexts)]
    kept_runs.update(a['run_id'] for a in out['affect_annotations'])
    out['processing_runs']=[pool['processing_runs'][x] for x in sorted(kept_runs)]
    out['interest_categories']=db['interest_categories']
    report=validate(out)
    original_semantics={r['id'] for r in db['video_semantics']};selected_ids={r['id'] for r in out['video_semantics']}
    report.update({'scope':scope,'policy':POLICY,'snapshot_created_at':archive['created_at'],
          'manifest_videos':len(rows),'imported_videos':len(current),'valid_semantic_candidates':len(candidates),
          'historical_semantics_excluded':len(candidates)-len(selected),
          'production_historical_semantics_excluded':len(original_semantics-selected_ids),
          'new_local_semantics_selected':len(selected_ids-original_semantics),
          'stages':dict(stages),'missing_compatible_embeddings':missing_embeddings,
          'source_category_provenance':dict(Counter(x['provenance'] for x in category_report)),
          'primary_category_distribution':dict(Counter(x['primary_category'] or 'unresolved' for x in category_report)),
          'secondary_category_status':dict(Counter(x['secondary_status'] for x in category_report)),
          'source_category_conflicts':sum(x['source_conflict'] for x in category_report),
          'nonempty_transcript_retrieval_ready':sum(bool(pool['video_context'][s['context_id']]['transcript'].strip()) for s in selected.values() if s['video_id'] not in missing_embeddings),
          'artifact_validation_issues':issues,'local_record_files_validated':len(local_history),
          'db_writes':0,'models_executed':0,'ambiguous_latest_selections':ties})
    # Preserve every validated historical local candidate, not just production history.
    history={t:sorted(pool[t].values(),key=lambda r:key(r,t)) for t in ORDER}
    # Add metadata for local-only IDs to make history closure self-contained.
    for vid in ids:
        if vid not in pool['videos']:history['videos'].append(row_from_entity(video(vid,rows[vid])))
    write_package(destination,out,{'kind':'offline-stage','report':report,'source_snapshot':str(Path(snapshot).resolve())},
                  {'categories.json':category_report,'selection.json':selection,'input_hashes.json':input_files})
    archive_path=Path(destination).with_name(Path(destination).name+'-history')
    # Include all source job snapshots (including failures) in the historical archive.
    all_jobs={r['id']:r for r in history['processing_jobs']}
    for j in job_states:all_jobs[j['id']]=j
    history['processing_jobs']=list(all_jobs.values())
    # History may include local candidates outside the chosen scope only from original DB;
    # every referenced video/run remains present.
    validate(history,clean=False)
    write_package(archive_path,history,{'kind':'historical-candidate-archive','scope':scope},
                  {'local_records.json':local_history})
    loaded,_=load_package(destination);validate(loaded)
    old,_=load_package(archive_path);validate(old,clean=False)
    return report


def verify_stage(path):
    tables,manifest=load_package(path);report=validate(tables)
    if manifest['info']['kind']!='offline-stage':raise ValueError('Not a staged catalogue')
    path=Path(path);history,_=load_package(path.with_name(path.name+'-history'));validate(history,clean=False)
    latest,ties=select_latest(history['video_semantics'])
    chosen={s['video_id']:s for s in tables['video_semantics']}
    ids={v['video_id'] for v in tables['videos']}
    if ties or {v:s['id'] for v,s in latest.items() if v in ids}!={v:s['id'] for v,s in chosen.items()}:
        raise ValueError('Stage is not the unique latest historical selection')
    cat=json.loads((path/'categories.json').read_text(encoding='utf-8'))
    if len(cat)!=len(ids) or {r['video_id'] for r in cat}!=ids:
        raise ValueError('Missing or duplicate category resolutions')
    # Rebuild policies from preserved original data, never from model claims alone.
    import sys
    src=str(Path(__file__).resolve().parents[2]/'annotation/src')
    if src not in sys.path:sys.path.insert(0,src)
    from ataraxia.datasets.normalization import MAPPING
    taxonomy={'version':'ataraxia-semantic-taxonomy-v1',
              'categories':{r['name']:r['subcategories'] for r in tables['interest_categories']}}
    if not taxonomy['categories']:
        # Synthetic fixtures may omit category rows; production packages never do.
        taxonomy=json.loads((Path(__file__).resolve().parents[2]/'annotation/semantic_pipeline/configs/taxonomy.json').read_text())
    vmap={r['video_id']:r for r in tables['videos']}
    for resolution in cat:
        vid=resolution['video_id']
        expected={'video_id':vid,**category_resolution(vmap[vid]['payload'],chosen.get(vid),MAPPING,taxonomy)}
        if resolution!=expected:raise ValueError('Category provenance or original label changed')
    report['latest_selection_verified']=True;report['categories_verified']=True
    return report


def export_sql(snapshot, stage, destination):
    """Offline-only SQL rehearsal and restore-to-empty-tables script.

    Both end in ROLLBACK. No SQL is executed. Retain the immutable packages;
    the JSONL archives, not a terminal transcript, contain the full vectors.
    """
    from psycopg import sql
    before,bm=load_package(snapshot);after,sm=load_package(stage)
    validate(before,clean=False);validate(after)
    if sm['info']['report']['scope']!='imported':
        raise ValueError('SQL plan requires the explicitly selected imported-video scope')
    if {r['video_id'] for r in before['videos']}!={r['video_id'] for r in after['videos']}:
        raise ValueError('Replacement changes approved video-ID scope')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    schema=bm['info']['schema']
    delta=changes(before,after)
    catalog=json.loads((Path(snapshot)/'catalog.json').read_text(encoding='utf-8'))
    external=[r for r in catalog['inbound_fks'] if r['nspname']!=schema or r['relname'] not in ORDER]
    if external:raise ValueError('External inbound FKs require separate dependency review')
    if catalog['triggers']:raise ValueError('User triggers require separate replacement review')
    def ident(name):return sql.Identifier(name).as_string()
    def literal(value):
        if isinstance(value,(dict,list)):value=canonical(value)
        return sql.Literal(value).as_string()
    def inserts(tables,prefix):
        lines=[]
        for t in ORDER:
            for r in sorted(tables[t],key=lambda x:key(x,t)):
                cols=list(r)
                lines.append('INSERT INTO '+prefix(t)+' ('+','.join(ident(x) for x in cols)+') VALUES ('+
                             ','.join(literal(r[x]) for x in cols)+');')
        return lines
    production=lambda t:ident(schema)+'.'+ident(t)
    temp=lambda p,t:'pg_temp.'+ident(p+t)
    header=['\\set ON_ERROR_STOP on','-- PREPARED REHEARSAL ONLY. NOT APPLIED. Ends in ROLLBACK.',
            '-- Must pause ALL writers and rehearse full schema/data restore before approval.',
            'BEGIN;',"SET LOCAL lock_timeout='5s';","SET LOCAL statement_timeout='120s';",
            "SET LOCAL standard_conforming_strings=on;",'LOCK TABLE '+','.join(production(t) for t in ORDER)+' IN EXCLUSIVE MODE;']
    lines=list(header)
    # Recheck schema/security in the same locked transaction, not just the earlier audit.
    schema_checks={
        'indexes':"SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname="+literal(schema)+' ORDER BY tablename,indexname',
        'constraints':"""SELECT c.relname AS table_name,p.conname,p.contype,p.convalidated,
            pg_get_constraintdef(p.oid) AS definition FROM pg_constraint p JOIN pg_class c ON c.oid=p.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname="""+literal(schema)+' ORDER BY c.relname,p.conname',
        'security':"""SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) AS owner,
            c.relacl::text AS acl FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname="""+
            literal(schema)+" AND c.relkind='r' ORDER BY c.relname",
        'policies':'SELECT * FROM pg_policies WHERE schemaname='+literal(schema)+' ORDER BY tablename,policyname',
        'grants':'SELECT table_name,grantor,grantee,privilege_type,is_grantable FROM information_schema.role_table_grants WHERE table_schema='+literal(schema)+' ORDER BY table_name,grantee,privilege_type',
        'extensions':"SELECT e.extname,e.extversion,n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname",
        'triggers':"""SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) AS definition FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname="""+
            literal(schema)+" AND NOT t.tgisinternal ORDER BY c.relname,t.tgname",
        'columns':"""SELECT c.relname AS table_name,a.attname AS column_name,format_type(a.atttypid,a.atttypmod) AS type,
            a.attnotnull AS not_null,pg_get_expr(d.adbin,d.adrelid) AS default_expression,a.attidentity,a.attgenerated
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE n.nspname="""+
            literal(schema)+" AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum",
        'inbound_fks':"""SELECT n.nspname,c.relname,p.conname,pg_get_constraintdef(p.oid) AS definition
            FROM pg_constraint p JOIN pg_class c ON c.oid=p.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_class target ON target.oid=p.confrelid JOIN pg_namespace tn ON tn.oid=target.relnamespace
            WHERE p.contype='f' AND tn.nspname="""+literal(schema)+" AND target.relname IN ("+
            ','.join(literal(t) for t in ORDER)+') ORDER BY n.nspname,c.relname,p.conname',
    }
    lines.append('DO $schema_guard$ BEGIN')
    for name,query in schema_checks.items():
        lines.append("IF (SELECT coalesce(jsonb_agg(to_jsonb(q)),'[]'::jsonb) FROM ("+query+') q) IS DISTINCT FROM '+
                     literal(catalog[name])+"::jsonb THEN RAISE EXCEPTION 'Schema/security changed: "+name+"'; END IF;")
    lines.append('END $schema_guard$;')
    for prefix,tables in [('expected_',before),('next_',after)]:
        for t in ORDER:
            lines.append('CREATE TEMP TABLE '+ident(prefix+t)+' (LIKE '+production(t)+' INCLUDING ALL) ON COMMIT DROP;')
        lines.extend(inserts(tables,lambda t:temp(prefix,t)))
    lines.append('DO $catalogue_guard$ BEGIN')
    # Exact typed row comparison includes timestamps, full payloads and full vectors;
    # rejects even an insertion that occurred after the read-only snapshot.
    for t in ORDER:
        lines.append('IF EXISTS ((SELECT * FROM '+production(t)+' EXCEPT SELECT * FROM '+temp('expected_',t)+
                     ') UNION ALL (SELECT * FROM '+temp('expected_',t)+' EXCEPT SELECT * FROM '+production(t)+
                     ")) THEN RAISE EXCEPTION 'Production snapshot changed: "+t+"'; END IF;")
    lines.append('END $catalogue_guard$;')
    # Explicit staging FK validation; LIKE does not copy foreign keys.
    checks=[]
    for t in ORDER:
        if t not in ('videos','processing_runs','interest_categories'):
            checks.append((t,'video_id','videos','video_id'))
        if t in ('affect_annotations','video_semantics','video_embeddings','processing_jobs'):
            checks.append((t,'run_id','processing_runs','id'))
    checks.extend([('video_semantics','context_id','video_context','id'),
                   ('video_semantics','affect_id','affect_annotations','id'),
                   ('video_embeddings','semantic_id','video_semantics','id')])
    lines.append('DO $staging_guard$ BEGIN')
    for child,fk,parent,pk in checks:
        lines.append('IF EXISTS (SELECT 1 FROM '+temp('next_',child)+' c LEFT JOIN '+temp('next_',parent)+
                     ' p ON p.'+ident(pk)+'=c.'+ident(fk)+' WHERE p.'+ident(pk)+
                     " IS NULL) THEN RAISE EXCEPTION 'Staging FK failed: "+child+'.'+fk+"'; END IF;")
    lines.append('END $staging_guard$;')
    # Keep all production relation objects: constraints/indexes/RLS/ACL remain attached.
    for t in reversed(ORDER):
        if delta[t]['remove']:
            pk=ident('video_id' if t=='videos' else 'id')
            lines.append('DELETE FROM '+production(t)+' WHERE '+pk+' IN ('+
                         ','.join(literal(x) for x in delta[t]['remove'])+');')
    for t in ORDER:
        cols=[r['column_name'] for r in catalog['columns'] if r['table_name']==t]
        coltext=','.join(ident(x) for x in cols)
        # New rows receive their original completion data; DB created_at defaults
        # identify insertion time only and never affect semantic ordering.
        staged_columns=set().union(*(set(r) for r in after[t])) if after[t] else set(cols)
        columns=[x for x in cols if x in staged_columns]
        coltext=','.join(ident(x) for x in columns)
        if delta[t]['insert']:
            pk=ident('video_id' if t=='videos' else 'id')
            lines.append('INSERT INTO '+production(t)+' ('+coltext+') SELECT '+coltext+' FROM '+temp('next_',t)+
                         ' WHERE '+pk+' IN ('+','.join(literal(x) for x in delta[t]['insert'])+');')
    lines.append('DO $result_guard$ BEGIN')
    for t in ORDER:
        lines.append('IF (SELECT count(*) FROM '+production(t)+') <> '+str(len(after[t]))+
                     " THEN RAISE EXCEPTION 'Result count failed: "+t+"'; END IF;")
    lines.append('IF EXISTS (SELECT video_id FROM '+production('video_semantics')+
                 " GROUP BY video_id HAVING count(*)>1) THEN RAISE EXCEPTION 'Duplicate current semantic'; END IF;")
    # Compare every staged column (except insertion-time defaults for new entities)
    # against production, including the vector itself.
    for t in ORDER:
        cols=[x['column_name'] for x in catalog['columns'] if x['table_name']==t and x['column_name']!='created_at']
        ct=','.join(ident(x) for x in cols)
        lines.append('IF EXISTS ((SELECT '+ct+' FROM '+production(t)+' EXCEPT SELECT '+ct+' FROM '+temp('next_',t)+
                     ') UNION ALL (SELECT '+ct+' FROM '+temp('next_',t)+' EXCEPT SELECT '+ct+' FROM '+production(t)+
                     ")) THEN RAISE EXCEPTION 'Result differs from validated stage: "+t+"'; END IF;")
    lines.append('END $result_guard$;')
    views=category_views(schema)
    (destination/'catalogue_views.sql').write_text(views,encoding='utf-8')
    lines.append(views)
    lines.extend(['SET CONSTRAINTS ALL IMMEDIATE;',
                  '-- Verify the protected current-only synchronization path before COMMIT.',
                  '-- Do not replace ROLLBACK until restore rehearsal, writer quiescence, and separate approval.',
                  'ROLLBACK;'])
    (destination/'replacement_rehearsal.sql').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    # Data-only restoration into an EMPTY copy of the original schema.
    restore=list(header)
    restore.append('DO $restore_guard$ BEGIN')
    for t in ORDER:restore.append('IF EXISTS (SELECT 1 FROM '+production(t)+") THEN RAISE EXCEPTION 'Restore requires empty original tables'; END IF;")
    restore.append('END $restore_guard$;')
    restore.extend(inserts(before,production));restore.append('ROLLBACK;')
    (destination/'restore_data_rehearsal.sql').write_text('\n'.join(restore)+'\n',encoding='utf-8')
    write_json(destination/'README.json',{'status':'NOT EXECUTED; ROLLBACK ONLY',
        'snapshot_manifest_sha256':hashlib.sha256((Path(snapshot)/'manifest.json').read_bytes()).hexdigest(),
        'stage_manifest_sha256':hashlib.sha256((Path(stage)/'manifest.json').read_bytes()).hexdigest(),
        'blockers':['pg_dump schema archive and isolated restore rehearsal',
                    'pause and positively identify all local/remote writers',
                    'recheck schema/security signature inside replacement transaction',
                    'activate current-only incremental writer; legacy history importer must stay disabled',
                    'separate explicit production replacement approval'],
        'sql_sha256':{name:hashlib.sha256((destination/name).read_bytes()).hexdigest()
                      for name in ['replacement_rehearsal.sql','restore_data_rehearsal.sql','catalogue_views.sql']},
        'vectors_present_in_sql_files':True,'never_print_sql_files':True})
    write_json(destination/'delta.json',delta)
    return {'sql_files_prepared':2,'executed':False,'ends_in_rollback':True}


def category_views(schema):
    """Backend-only views; no rewrites of historical semantic payloads/hashes."""
    from psycopg import sql
    import sys
    src=str(Path(__file__).resolve().parents[2]/'annotation/src')
    if src not in sys.path:sys.path.insert(0,src)
    from ataraxia.datasets.normalization import MAPPING
    ident=lambda s:sql.Identifier(s).as_string()
    literal=lambda s:sql.Literal(s).as_string()
    prefix=ident(schema)+'.'
    pairs=','.join('('+literal(k)+','+literal(v)+')' for k,v in sorted(MAPPING.items()))
    current=prefix+'video_catalogue_current';categories_view=prefix+'video_catalogue_categories'
    text=f"""-- Prepared only. Apply inside approved replacement transaction.
CREATE OR REPLACE VIEW {current} WITH (security_invoker=true) AS
WITH eligible AS (
 SELECT s.id,s.video_id,
 CASE WHEN pg_input_is_valid(s.payload->>'completed_at','timestamp with time zone')
 THEN (s.payload->>'completed_at')::timestamptz END AS completed_at
 FROM {prefix}video_semantics s JOIN {prefix}processing_runs r ON r.id=s.run_id
 WHERE s.payload->>'status'='complete' AND r.kind='semantic'
 AND s.payload->>'completed_at' ~ '(Z|[+-][0-9][0-9]:[0-9][0-9])$'
 AND s.payload->>'video_id'=s.video_id
 AND s.payload->>'run_fingerprint'=r.payload->'frozen'->>'fingerprint'
), ranked AS (
 SELECT id,row_number() OVER (PARTITION BY video_id ORDER BY completed_at DESC) AS position,
 count(*) OVER (PARTITION BY video_id,completed_at) AS timestamp_ties
 FROM eligible WHERE completed_at IS NOT NULL
)
SELECT s.*,e.id AS embedding_id,e.embedding,(e.id IS NOT NULL) AS retrieval_ready
FROM {prefix}video_semantics s JOIN ranked x ON x.id=s.id AND x.position=1 AND x.timestamp_ties=1
JOIN {prefix}video_context c ON c.id=s.context_id AND c.video_id=s.video_id
JOIN {prefix}affect_annotations a ON a.id=s.affect_id AND a.video_id=s.video_id
LEFT JOIN LATERAL (
 SELECT matched.* FROM (
 SELECT candidate.*,count(*) OVER () AS compatible_count
 FROM {prefix}video_embeddings candidate
 WHERE candidate.semantic_id=s.id AND candidate.video_id=s.video_id
 AND candidate.run_id=s.run_id AND candidate.model=s.payload->'embedding'->>'checkpoint'
 AND candidate.revision=s.payload->'embedding'->>'revision'
 AND candidate.template_version=s.payload->>'template_version'
 AND candidate.input_hash=s.payload->>'embedding_input_sha256'
 AND candidate.payload=s.payload->'embedding'
 ) matched WHERE matched.compatible_count=1
) e ON true;
CREATE OR REPLACE VIEW {categories_view} WITH (security_invoker=true) AS
WITH mapping(original_label,canonical_category) AS (VALUES {pairs}), base AS (
 SELECT v.video_id,v.payload->>'category_original' AS original_label,
 v.payload->>'category' AS original_metadata_category,v.payload->>'source_manifest' AS source_manifest,
 coalesce(m.canonical_category,t.name) AS source_category,
 coalesce(lower(btrim(v.payload->>'category_original')) NOT IN ('','unknown','unmapped / needs review','none','null','n/a','nan'),false) AS has_original,
 s.id AS qwen_semantic_id,q.name AS qwen_candidate
 FROM {prefix}videos v LEFT JOIN mapping m ON m.original_label=v.payload->>'category_original'
 LEFT JOIN {prefix}interest_categories t ON t.name=v.payload->>'category_original'
  AND t.taxonomy_version='ataraxia-semantic-taxonomy-v1' AND t.name<>'unknown'
 LEFT JOIN {current} s ON s.video_id=v.video_id
 LEFT JOIN {prefix}interest_categories q ON q.name=s.primary_category
  AND q.taxonomy_version='ataraxia-semantic-taxonomy-v1' AND q.name<>'unknown'
), resolved AS (
 SELECT *,CASE WHEN has_original THEN source_category ELSE qwen_candidate END AS primary_category FROM base
)
SELECT video_id,original_label,original_metadata_category,primary_category,
 CASE WHEN has_original THEN 'source_metadata' WHEN qwen_candidate IS NOT NULL THEN 'existing_qwen' ELSE 'missing' END AS provenance,
 source_manifest,
 'ataraxia-semantic-taxonomy-v1'::text AS taxonomy_version,
 'existing-dataset-MAPPING-v1'::text AS mapping_version,
 CASE WHEN primary_category IS NULL THEN '[]'::jsonb
 ELSE jsonb_build_array(primary_category) END AS effective_categories,
 '[]'::jsonb AS secondary_categories,qwen_semantic_id,qwen_candidate,
 CASE WHEN qwen_candidate=primary_category THEN 'equivalent_deduplicated'
 WHEN qwen_candidate IS NULL THEN 'no_candidate'
 ELSE 'withheld_unverified_evidence' END AS secondary_status
FROM resolved;
CREATE OR REPLACE VIEW {prefix}video_catalogue_retrieval_ready WITH (security_invoker=true) AS
SELECT * FROM {current} WHERE retrieval_ready;
CREATE OR REPLACE VIEW {prefix}video_catalogue_all WITH (security_invoker=true) AS
SELECT v.video_id,v.title,v.language,v.source_dataset,v.duration_seconds,
 v.payload AS original_metadata,c.primary_category,c.effective_categories,
 s.id AS semantic_id,s.embedding_id,coalesce(s.retrieval_ready,false) AS retrieval_ready
FROM {prefix}videos v JOIN {categories_view} c ON c.video_id=v.video_id
LEFT JOIN {current} s ON s.video_id=v.video_id;
REVOKE ALL ON {current},{categories_view},{prefix}video_catalogue_retrieval_ready,
 {prefix}video_catalogue_all FROM PUBLIC,anon,authenticated;
GRANT SELECT ON {current},{categories_view},{prefix}video_catalogue_retrieval_ready,
 {prefix}video_catalogue_all TO service_role;
"""
    return text


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    snap=sub.add_parser('snapshot');snap.add_argument('--out',type=Path,required=True)
    dump=sub.add_parser('dump');dump.add_argument('--out',type=Path,required=True)
    dump.add_argument('--pg-dump',default='pg_dump');dump.add_argument('--pg-restore',default='pg_restore')
    stage=sub.add_parser('prepare');stage.add_argument('--snapshot',type=Path,required=True)
    stage.add_argument('--out',type=Path,required=True);stage.add_argument('--scope',choices=['imported','manifest'],required=True)
    stage.add_argument('--annotation-root',type=Path,default=Path('annotation'))
    check=sub.add_parser('verify');check.add_argument('package',type=Path)
    export=sub.add_parser('export-sql');export.add_argument('--snapshot',type=Path,required=True)
    export.add_argument('--stage',type=Path,required=True);export.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='snapshot':report=capture(args.out)
        elif args.command=='dump':report=dump_backup(args.out,args.pg_dump,args.pg_restore)
        elif args.command=='prepare':report=prepare(args.snapshot,args.out,args.annotation_root,args.scope)
        elif args.command=='export-sql':report=export_sql(args.snapshot,args.stage,args.out)
        else:
            tables,manifest=load_package(args.package)
            report=verify_stage(args.package) if manifest['info']['kind']=='offline-stage' else validate(tables,clean=False)
        # No payloads, credentials, full vectors, or raw driver exceptions on stdout.
        print(json.dumps(report,indent=2,ensure_ascii=False))
        return 0
    except Exception as exc:
        print('Catalogue preparation stopped: '+type(exc).__name__+'; SQLSTATE='+str(getattr(exc,'sqlstate',None)))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
