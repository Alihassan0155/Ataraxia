"""Transactional latest-only delivery; preserve metadata, taxonomy and history."""
import json
from pathlib import Path
import numpy as np
from psycopg import sql
from psycopg.types.json import Jsonb
from .artifacts import Reader,entity,fingerprint
from .catalogue import ORDER,validate,select_latest,timestamp,compatible,row_from_entity,vector_array
from .config import DatabaseSettings,connect


class BatchWriter:
    def __init__(self,root,approved_ids,settings=None,connection_factory=None):
        self.root=Path(root).resolve();self.ids=frozenset(approved_ids)
        if len(self.ids)!=1140:raise ValueError('Exact approved 1,140-video scope required')
        self.settings=settings or DatabaseSettings.load()
        self.connection_factory=connection_factory or (lambda:connect(self.settings))
        self.last_insertions={}

    def _bundles(self,rows):
        reader=Reader(self.root);result=[]
        for row in rows:
            if row['video_id'] not in self.ids:raise ValueError('Unapproved video')
            queued=json.loads(row['bundle'])
            if fingerprint(queued)!=row['bundle_hash']:raise ValueError('Queue hash mismatch')
            path=(self.root/row['record_path']).resolve()
            if not path.is_relative_to(self.root):raise ValueError('Artifact escapes annotation root')
            run=path.parents[3];frozen=reader.api[1](run/'frozen.json')
            bundle=reader.semantic_bundle(run,path,frozen,reader.api[3](run))
            if fingerprint(bundle)!=row['bundle_hash']:raise ValueError('Queued artifact changed')
            semantic=next(e for e in bundle if e['table']=='video_semantics')
            if semantic['key']!=row['semantic_id'] or semantic['columns']['video_id']!=row['video_id']:
                raise ValueError('Queue identity mismatch')
            statepath=path.parent/'state.json'
            if statepath.exists():
                state=reader.api[1](statepath)
                if state.get('status')=='complete':
                    rid=semantic['columns']['run_id']
                    payload={'video_id':row['video_id'],'source_fingerprint':path.parent.name,'state':state}
                    bundle.append(entity('processing_jobs',fingerprint([rid,payload]),payload,
                        video_id=row['video_id'],run_id=rid,stage=state.get('stage','complete'),
                        status='complete',attempts=int(state.get('attempts',0))))
            result.append((row,bundle,semantic))
        return result

    @staticmethod
    def _same(expected,actual):
        for name,value in expected.items():
            if name=='embedding':
                if not np.array_equal(vector_array(value),vector_array(actual[name])):return False
            elif actual.get(name)!=value:return False
        return True

    def _insert(self,conn,item,data):
        table=item['table']
        if table in ('videos','interest_categories'):return  # Source metadata always authoritative.
        if table not in ORDER:raise ValueError('Unknown table')
        row=row_from_entity(item);existing=next((r for r in data[table] if r['id']==item['key']),None)
        if existing:
            if not self._same(row,existing):raise ValueError('Immutable identity collision')
            return
        cols=list(row);values=[];holders=[]
        for name in cols:
            value=row[name]
            if name=='embedding':
                values.append('['+','.join(str(float(v)) for v in value)+']')
                # The existing typed column supplies the installed vector cast.
                holders.append(sql.SQL('%s::{}').format(sql.Identifier(self.vector_schema,'vector')))
            else:
                values.append(Jsonb(value) if isinstance(value,(dict,list)) else value)
                holders.append(sql.Placeholder())
        conn.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
            sql.Identifier(self.settings.schema,table),sql.SQL(',').join(map(sql.Identifier,cols)),sql.SQL(',').join(holders)),values)
        data[table].append(row)
        self.last_insertions[table]=self.last_insertions.get(table,0)+1

    def __call__(self,rows):
        if len({r['video_id'] for r in rows})!=len(rows):raise ValueError('One selected version per batch video required')
        bundles=self._bundles(rows);outcomes={};self.last_insertions={}
        with self.connection_factory() as conn:
            with conn.transaction():
                conn.execute("SET LOCAL lock_timeout='5s'")
                if not conn.execute('SELECT pg_try_advisory_xact_lock(193701,1140)').fetchone()[0]:
                    raise ValueError('Another batch writer is active')
                conn.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(
                    sql.SQL(',').join(sql.Identifier(self.settings.schema,t) for t in ORDER)))
                self.vector_schema=conn.execute('SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname=%s',('vector',)).fetchone()[0]
                data={}
                for table in ORDER:
                    cur=conn.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(self.settings.schema,table)))
                    data[table]=[dict(zip([c.name for c in cur.description],r)) for r in cur.fetchall()]
                if {v['video_id'] for v in data['videos']}!=self.ids:raise ValueError('Live scope changed')
                validate(data,clean=False)
                latest,ties=select_latest(data['video_semantics'])
                for queued,bundle,item in bundles:
                    vid=queued['video_id'];sid=item['key'];candidate=row_from_entity(item)
                    if vid in ties:raise ValueError('Ambiguous live latest timestamp')
                    current=latest.get(vid)
                    if current and current['id']!=sid:
                        live_time=timestamp(current['payload']['completed_at'])
                        candidate_time=timestamp(candidate['payload']['completed_at'])
                        if live_time==candidate_time:raise ValueError('Conflicting equal completion timestamps')
                        if live_time>candidate_time:
                            if sum(compatible(e,current) for e in data['video_embeddings'])!=1:
                                raise ValueError('Newer remote semantic lacks a unique compatible embedding')
                            outcomes[sid]='superseded';continue
                    if current and current['id']==sid and sum(compatible(e,current) for e in data['video_embeddings'])==1:
                        # Validate exact identity/projections/vector before lost-ack retry succeeds.
                        for e in bundle:
                            if e['table'] in ('videos','interest_categories','processing_jobs'):continue
                            self._insert(conn,e,data)
                        outcomes[sid]='synced';continue
                    for table in ORDER:
                        for e in bundle:
                            if e['table']==table:self._insert(conn,e,data)
                    latest[vid]=candidate;outcomes[sid]='synced'
                validate(data,clean=False)
        # Returned only after transaction commit; uncertain commits are retried.
        return outcomes
