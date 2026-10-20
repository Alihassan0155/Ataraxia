"""Durable completion queue and latest-only batch delivery. Writes require explicit CLI flags."""
from contextlib import contextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import time

from .artifacts import Reader,canonical,fingerprint
from .catalogue import load_package,timestamp


class DurableQueue:
    def __init__(self,path,approved_ids,clock=time.time):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.clock=clock;self.ids=frozenset(approved_ids)
        if not self.ids:raise ValueError('An explicit approved video scope is required')
        self.db=sqlite3.connect(str(self.path),timeout=30,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS items(
          semantic_id TEXT PRIMARY KEY, video_id TEXT NOT NULL,
          completed_at REAL NOT NULL, discovered_at REAL NOT NULL,
          record_path TEXT NOT NULL, bundle TEXT NOT NULL, bundle_hash TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('pending','inflight','synced','superseded')),
          attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
          lease_until REAL, last_error TEXT, acknowledged_at REAL);
        CREATE INDEX IF NOT EXISTS items_pending ON items(status,retry_at,video_id);
        CREATE TABLE IF NOT EXISTS discovery_errors(
          record_path TEXT PRIMARY KEY, error_type TEXT NOT NULL,
          first_seen REAL NOT NULL,last_seen REAL NOT NULL, occurrences INTEGER NOT NULL);
        ''')
        scope=canonical(sorted(self.ids))
        try:
            with self.transaction():
                saved=self.db.execute("SELECT value FROM metadata WHERE key='approved_ids'").fetchone()
                if saved and saved[0]!=scope:raise ValueError('Queue scope cannot change')
                self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('approved_ids',?)",(scope,))
                self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('schema_version','1')")
                if self.db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]!='1':
                    raise ValueError('Unsupported queue format')
        except BaseException:
            self.db.close();raise

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK');raise

    def close(self):self.db.close()

    def enqueue(self,bundle,path):
        """Persist a bundle already validated by Reader.semantic_bundle."""
        semantic=next(x for x in bundle if x['table']=='video_semantics')
        vid=semantic['columns']['video_id'];sid=semantic['key']
        if vid not in self.ids:raise ValueError('Video is outside approved scope')
        completed=timestamp(semantic['payload']['completed_at']).timestamp()
        body=canonical(bundle);digest=fingerprint(bundle)
        with self.transaction():
            existing=self.db.execute('SELECT bundle_hash FROM items WHERE semantic_id=?',(sid,)).fetchone()
            if existing:
                if existing[0]!=digest:raise ValueError('Immutable queue identity collision')
                return False
            newer=self.db.execute("SELECT 1 FROM items WHERE video_id=? AND completed_at>? AND status='synced' LIMIT 1",(vid,completed)).fetchone()
            self.db.execute('''INSERT INTO items
                (semantic_id,video_id,completed_at,discovered_at,record_path,bundle,bundle_hash,status)
                VALUES (?,?,?,?,?,?,?,?)''',
                (sid,vid,completed,self.clock(),str(path),body,digest,'superseded' if newer else 'pending'))
        return True  # FULL durability commit occurs before discovery returns.

    def reconcile_existing(self,latest):
        """Local acknowledgement only, using independently verified remote rows."""
        with self.transaction():
            for vid,semantic in latest.items():
                if vid not in self.ids:raise ValueError('Remote scope mismatch')
                stamp=timestamp(semantic['payload']['completed_at']).timestamp()
                self.db.execute("UPDATE items SET status='synced',acknowledged_at=?,lease_until=NULL WHERE semantic_id=?",
                                (self.clock(),semantic['id']))
                self.db.execute("UPDATE items SET status='superseded',acknowledged_at=?,lease_until=NULL WHERE video_id=? AND completed_at<? AND status='pending'",
                                (self.clock(),vid,stamp))

    def record_error(self,path,error):
        # Exception type only: driver messages can contain credentials or payloads.
        now=self.clock()
        with self.transaction():
            self.db.execute('''INSERT INTO discovery_errors VALUES (?,?,?,?,1)
                ON CONFLICT(record_path) DO UPDATE SET error_type=excluded.error_type,
                last_seen=excluded.last_seen,occurrences=occurrences+1''',(str(path),type(error).__name__,now,now))

    def recover_inflight(self):
        """Call only while holding the queue's exclusive OS worker lock."""
        with self.transaction():
            return self.db.execute("UPDATE items SET status='pending',lease_until=NULL WHERE status='inflight'").rowcount

    def _pending(self):
        return self.db.execute("SELECT * FROM items WHERE status IN ('pending','inflight') ORDER BY discovered_at,semantic_id").fetchall()

    def summary(self,batch_size=10,max_wait=1800):
        if batch_size<1 or max_wait<=0:raise ValueError('Positive batch size and waiting time required')
        pending=self._pending();oldest=min((r['discovered_at'] for r in pending),default=None)
        count=len({r['video_id'] for r in pending})
        age=max(0,self.clock()-oldest) if oldest is not None else 0
        versions={}
        for r in pending:versions.setdefault(r['video_id'],[]).append(r['completed_at'])
        ambiguous=[v for v,stamps in versions.items() if stamps.count(max(stamps))>1]
        return {'pending_versions':len(pending),'pending_distinct_videos':count,
                'oldest_discovered_at':oldest,'oldest_wait_seconds':age,
                'batch_due':bool(count and (count>=batch_size or age>=max_wait)),
                'statuses':dict(self.db.execute('SELECT status,count(*) FROM items GROUP BY status').fetchall()),
                'ambiguous_latest_videos':sorted(ambiguous),
                'discovery_error_paths':self.db.execute('SELECT count(*) FROM discovery_errors').fetchone()[0]}

    def claim(self,batch_size=10,max_wait=1800,lease_seconds=300):
        with self.transaction():
            if not self.summary(batch_size,max_wait)['batch_due']:return []
            rows=self._pending();grouped={}
            for r in rows:grouped.setdefault(r['video_id'],[]).append(r)
            eligible=[]
            for versions in grouped.values():
                if any(r['status']=='inflight' for r in versions):continue
                latest=max(r['completed_at'] for r in versions)
                newest=[r for r in versions if r['completed_at']==latest]
                # Equal timestamps are review cases, never arbitrary selections.
                if len(newest)!=1 or newest[0]['retry_at']>self.clock():continue
                eligible.append((min(r['discovered_at'] for r in versions),newest[0]))
            chosen=[dict(r) for _,r in sorted(eligible,key=lambda x:(x[0],x[1]['semantic_id']))[:batch_size]]
            for r in chosen:
                self.db.execute("UPDATE items SET status='inflight',attempts=attempts+1,lease_until=? WHERE semantic_id=?",
                                (self.clock()+lease_seconds,r['semantic_id']))
            return chosen

    def retry(self,rows,error,base_delay=30,max_delay=1800):
        with self.transaction():
            for r in rows:
                state=self.db.execute('SELECT status,attempts FROM items WHERE semantic_id=?',(r['semantic_id'],)).fetchone()
                if state['status']!='inflight':continue
                delay=min(max_delay,base_delay*2**min(state['attempts']-1,12))
                self.db.execute("UPDATE items SET status='pending',retry_at=?,lease_until=NULL,last_error=? WHERE semantic_id=?",
                                (self.clock()+delay,type(error).__name__,r['semantic_id']))

    def acknowledge(self,rows,outcomes):
        """Writer must confirm remote commit or exact existing version identity.

        A connection loss at commit is NOT success. Retrying the same semantic ID
        must be idempotent at the remote transactional writer boundary.
        """
        if set(outcomes)!={r['semantic_id'] for r in rows} or any(v not in ('synced','superseded') for v in outcomes.values()):
            raise ValueError('Every claimed version needs a confirmed outcome')
        with self.transaction():
            for r in rows:
                self.db.execute('UPDATE items SET status=?,acknowledged_at=?,lease_until=NULL,last_error=NULL WHERE semantic_id=?',
                                (outcomes[r['semantic_id']],self.clock(),r['semantic_id']))
                self.db.execute("UPDATE items SET status='superseded',acknowledged_at=? WHERE video_id=? AND completed_at<? AND status='pending'",
                                (self.clock(),r['video_id'],r['completed_at']))

    def deliver(self,writer,batch_size=10,max_wait=1800):
        rows=self.claim(batch_size,max_wait)
        if not rows:return 0
        try:
            for r in rows:
                if fingerprint(json.loads(r['bundle']))!=r['bundle_hash']:raise ValueError('Queue bundle corruption')
            outcomes=writer(rows)
            self.acknowledge(rows,outcomes)
        except Exception as error:
            self.retry(rows,error);return 0
        return len(rows)


def discover(queue,root):
    """Poll finalized record.json files, validate through the original Reader.

    Full rescan on every startup/interval recovers rename/notification races.
    Invalid and partial artifacts are retained on disk and retried next scan.
    """
    root=Path(root).resolve();reader=Reader(root);cache={};added=0
    for path in sorted((root/'semantic_pipeline/runs').glob('*/videos/*/*/record.json')):
        if path.parent.parent.name not in queue.ids:continue
        try:
            raw=path.read_bytes();record=json.loads(raw);run=path.parents[3]
            if run not in cache:cache[run]=(reader.api[1](run/'frozen.json'),reader.api[3](run))
            bundle=reader.semantic_bundle(run,path,*cache[run])
            if raw!=path.read_bytes() or next(x['payload'] for x in bundle if x['table']=='video_semantics')!=record:
                raise ValueError('Completion changed during validation')
            added+=queue.enqueue(bundle,path.relative_to(root).as_posix())
        except Exception as error:queue.record_error(path.relative_to(root).as_posix(),error)
    return added


def reconcile_read_only(queue):
    from .config import DatabaseSettings,connect
    from .catalogue import ORDER,validate,select_latest,compatible
    from psycopg import sql
    with connect(DatabaseSettings.load()) as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            data={}
            for table in ORDER:
                cur=conn.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier('public',table)))
                data[table]=[dict(zip([c.name for c in cur.description],row)) for row in cur.fetchall()]
            validate(data,clean=False)
    if {r['video_id'] for r in data['videos']}!=queue.ids:raise ValueError('Live scope changed')
    latest,ties=select_latest(data['video_semantics'])
    valid={v:s for v,s in latest.items() if v not in ties and
           sum(compatible(e,s) for e in data['video_embeddings'])==1}
    queue.reconcile_existing(valid)
    return len(valid)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue',type=Path,required=True)
    parser.add_argument('--approved-snapshot',type=Path,required=True)
    parser.add_argument('--annotation-root',type=Path,default=Path('annotation'))
    parser.add_argument('--batch-size',type=int,default=10)
    parser.add_argument('--max-wait-seconds',type=float,default=1800)
    parser.add_argument('--poll-seconds',type=float,default=60)
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--reconcile-live',action='store_true',help='READ ONLY remote validation; acknowledge already stored current versions locally')
    parser.add_argument('--apply',action='store_true',help='Enable the explicitly approved transactional batch writer')
    parser.add_argument('--allow-live-writes',action='store_true')
    args=parser.parse_args(argv)
    if args.batch_size<1 or args.max_wait_seconds<=0 or args.poll_seconds<1:parser.error('Invalid scheduling values')
    if args.apply!=args.allow_live_writes:parser.error('Writes require both --apply and --allow-live-writes')
    data,manifest=load_package(args.approved_snapshot)
    ids={r['video_id'] for r in data['videos']}
    if len(ids)!=1140 or manifest['info']['kind']!='read-only-production-snapshot':
        parser.error('Verified original 1,140-video snapshot required')
    import sys
    sys.path.insert(0,str(args.annotation_root.resolve()/'src'))
    from ataraxia.distributed.common import lock
    queue=None
    try:
        with lock(args.queue.with_suffix(args.queue.suffix+'.worker.lock')):
            queue=DurableQueue(args.queue,ids);queue.recover_inflight()
            writer=None
            if args.apply:
                from .batch_writer import BatchWriter
                writer=BatchWriter(args.annotation_root,ids)
            def drain():
                delivered=0
                if writer:
                    while True:
                        count=queue.deliver(writer,args.batch_size,args.max_wait_seconds)
                        if not count:break
                        delivered+=count
                        print(json.dumps({'event':'batch_committed','versions':count,
                                          'insertions':writer.last_insertions}),flush=True)
                return delivered
            # Expired persisted batches need not wait for a potentially long rescan.
            if args.apply or args.reconcile_live:
                try:reconcile_read_only(queue)
                except Exception as error:queue.record_error('remote-reconciliation',error)
            drain()
            while True:
                added=discover(queue,args.annotation_root)
                if args.reconcile_live:
                    try:reconcile_read_only(queue)
                    except Exception as error:queue.record_error('remote-reconciliation',error)
                delivered=drain()
                print(json.dumps({'new_versions':added,**queue.summary(args.batch_size,args.max_wait_seconds),
                                  'writer_enabled':args.apply,'delivered_after_scan':delivered}),flush=True)
                if not args.watch:break
                status=queue.summary(args.batch_size,args.max_wait_seconds)
                remaining=args.max_wait_seconds-status['oldest_wait_seconds']
                time.sleep(min(args.poll_seconds,max(1,remaining)) if status['pending_versions'] else args.poll_seconds)
                drain()
    except KeyboardInterrupt:print('Stopped; durable pending records retained.')
    except OSError as error:
        print(json.dumps({'status':'worker_lock_or_local_io_unavailable',
                          'error_type':type(error).__name__,'database_writes':0}))
        return 1
    finally:
        if queue is not None:queue.close()


if __name__=='__main__':raise SystemExit(main())
