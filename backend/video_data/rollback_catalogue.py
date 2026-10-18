"""Prepare rollback SQL from immutable packages. No database connection."""
import hashlib
import json
from pathlib import Path
import re
from psycopg import sql
from .catalogue import ORDER,load_package,changes,key,canonical


def prepare_rollback(package):
    package=Path(package).resolve()
    before,_=load_package(package/'production_snapshot');after,_=load_package(package/'current_stage')
    delta=changes(after,before)
    original=(package/'sql_final/replacement_rehearsal.sql').read_text(encoding='utf-8')
    guard=re.search(r'DO \$schema_guard\$.*?END \$schema_guard\$;',original,re.S).group()
    literal=lambda value:sql.Literal(canonical(value) if isinstance(value,(dict,list)) else value).as_string()
    ident=lambda value:sql.Identifier(value).as_string()
    names=','.join(literal(t) for t in ORDER)
    # The original table grants must match; newly created catalogue views have
    # their own grants and are removed by this rollback, not silently ignored.
    guard=guard.replace("WHERE table_schema='public' ORDER BY", "WHERE table_schema='public' AND table_name IN ("+names+") ORDER BY")
    prod=lambda t:'"public".'+ident(t)
    tmp=lambda p,t:'pg_temp.'+ident(p+t)
    lines=['\\set ON_ERROR_STOP on','-- APPROVAL REQUIRED. Prepared post-commit rollback, ROLLBACK by default.',
           'BEGIN;',"SET LOCAL lock_timeout='5s';","SET LOCAL statement_timeout='120s';",
           'LOCK TABLE '+','.join(prod(t) for t in ORDER)+' IN EXCLUSIVE MODE;',guard]
    for prefix,tables in [('clean_',after),('original_',before)]:
        for t in ORDER:
            lines.append('CREATE TEMP TABLE '+ident(prefix+t)+' (LIKE '+prod(t)+' INCLUDING ALL) ON COMMIT DROP;')
            for row in tables[t]:
                columns=list(row)
                lines.append('INSERT INTO '+tmp(prefix,t)+' ('+','.join(ident(x) for x in columns)+') VALUES ('+
                             ','.join(literal(row[x]) for x in columns)+');')
    lines.append('DO $rollback_guard$ BEGIN')
    catalog=json.loads((package/'production_snapshot/catalog.json').read_text(encoding='utf-8'))
    for t in ORDER:
        cols=','.join(ident(c['column_name']) for c in catalog['columns'] if c['table_name']==t and c['column_name']!='created_at')
        lines.append('IF EXISTS ((SELECT '+cols+' FROM '+prod(t)+' EXCEPT SELECT '+cols+' FROM '+tmp('clean_',t)+
                     ') UNION ALL (SELECT '+cols+' FROM '+tmp('clean_',t)+' EXCEPT SELECT '+cols+' FROM '+prod(t)+
                     ")) THEN RAISE EXCEPTION 'Clean catalogue changed; rollback requires review: "+t+"'; END IF;")
    lines.append('END $rollback_guard$;')
    for name in ['video_catalogue_all','video_catalogue_retrieval_ready','video_catalogue_categories','video_catalogue_current']:
        lines.append('DROP VIEW '+prod(name)+';')  # RESTRICT; never CASCADE.
    for t in reversed(ORDER):
        if delta[t]['remove']:
            pk=ident('video_id' if t=='videos' else 'id')
            lines.append('DELETE FROM '+prod(t)+' WHERE '+pk+' IN ('+','.join(literal(x) for x in delta[t]['remove'])+');')
    for t in ORDER:
        if delta[t]['insert']:
            pk=ident('video_id' if t=='videos' else 'id')
            columns=','.join(ident(c['column_name']) for c in catalog['columns'] if c['table_name']==t)
            lines.append('INSERT INTO '+prod(t)+' ('+columns+') SELECT '+columns+' FROM '+tmp('original_',t)+
                         ' WHERE '+pk+' IN ('+','.join(literal(x) for x in delta[t]['insert'])+');')
    lines.append('DO $restore_result$ BEGIN')
    for t in ORDER:
        lines.append('IF EXISTS ((SELECT * FROM '+prod(t)+' EXCEPT SELECT * FROM '+tmp('original_',t)+
                     ') UNION ALL (SELECT * FROM '+tmp('original_',t)+' EXCEPT SELECT * FROM '+prod(t)+
                     ")) THEN RAISE EXCEPTION 'Original snapshot restore mismatch: "+t+"'; END IF;")
    lines.extend(['END $restore_result$;','SET CONSTRAINTS ALL IMMEDIATE;','ROLLBACK;'])
    path=package/'sql_final/rollback_after_commit_rehearsal.sql'
    if path.exists():raise FileExistsError('Never overwrite a prepared rollback')
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    report={'executed':False,'ends_in_rollback':True,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'delta':{t:{'insert':len(d['insert']),'remove':len(d['remove'])} for t,d in delta.items()}}
    (package/'sql_final/rollback_plan.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('package',type=Path)
    print(json.dumps(prepare_rollback(p.parse_args().package),indent=2))
