import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from backend.video_data.batch_sync import DurableQueue
from unittest.mock import patch


def bundle(video='v',version='s',completed='2026-10-18T00:00:00+00:00'):
    # Scheduler fixture; production discovery uses the full original Reader.
    return [{'table':'video_semantics','key':version,'columns':{'video_id':video},
             'payload':{'completed_at':completed}}]


class BatchQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'queue.sqlite'
        self.now=100.;self.ids={'v'+str(i) for i in range(12)}|{'v'}
        self.q=DurableQueue(self.path,self.ids,lambda:self.now)

    def tearDown(self):self.q.close();self.temp.cleanup()

    def add(self,video='v',version='s',completed='2026-10-18T00:00:00+00:00'):
        return self.q.enqueue(bundle(video,version,completed),'record.json')

    def test_partial_batch_survives_restart_and_uses_original_wait(self):
        for i in range(5):self.add('v'+str(i),'s'+str(i))
        self.q.close();self.now+=14400
        self.q=DurableQueue(self.path,self.ids,lambda:self.now)
        self.assertTrue(self.q.summary()['batch_due'])
        self.assertEqual(len(self.q.claim()),5)

    def test_threshold_ten_distinct_videos(self):
        for i in range(9):self.add('v'+str(i),'s'+str(i))
        self.assertFalse(self.q.summary()['batch_due'])
        self.add('v9','s9');self.assertEqual(len(self.q.claim()),10)

    def test_versions_do_not_count_as_distinct_videos(self):
        for i in range(12):self.add(version='s'+str(i),completed=f'2026-10-18T00:00:{i:02d}+00:00')
        self.assertEqual(self.q.summary()['pending_distinct_videos'],1)
        self.assertFalse(self.q.summary()['batch_due'])
        self.now+=1800;rows=self.q.claim()
        self.assertEqual([r['semantic_id'] for r in rows],['s11'])

    def test_discovery_deduplicates_without_resetting_timestamp(self):
        self.add();self.now+=1700;self.assertFalse(self.add())
        self.now+=100;self.assertTrue(self.q.summary()['batch_due'])

    def test_equal_latest_timestamps_are_not_arbitrarily_selected(self):
        self.add(version='a');self.add(version='b');self.now+=1800
        self.assertEqual(self.q.claim(),[])
        self.assertEqual(self.q.summary()['pending_versions'],2)

    def test_failed_delivery_remains_durable_and_backs_off(self):
        self.add();self.now+=1800
        def offline(rows):raise ConnectionError('private connection details')
        self.assertEqual(self.q.deliver(offline),0)
        row=self.q.db.execute('SELECT * FROM items').fetchone()
        self.assertEqual(row['status'],'pending');self.assertEqual(row['last_error'],'ConnectionError')
        self.assertEqual(self.q.claim(),[])
        self.now+=30;self.assertEqual(len(self.q.claim()),1)

    def test_crash_after_remote_commit_retries_same_identity(self):
        self.add();self.now+=1800;remote=set()
        first=self.q.claim();remote.add(first[0]['semantic_id'])
        self.q.close();self.q=DurableQueue(self.path,self.ids,lambda:self.now)
        self.assertEqual(self.q.recover_inflight(),1)
        def idempotent(rows):
            remote.update(r['semantic_id'] for r in rows)
            return {r['semantic_id']:'synced' for r in rows}
        self.assertEqual(self.q.deliver(idempotent),1)
        self.assertEqual(remote,{'s'});self.assertEqual(self.q.summary()['pending_versions'],0)

    def test_two_connections_do_not_claim_same_video(self):
        self.add();self.now+=1800
        second=DurableQueue(self.path,self.ids,lambda:self.now)
        try:
            self.assertEqual(len(self.q.claim()),1)
            self.assertEqual(second.claim(),[])
        finally:second.close()

    def test_partial_ack_rejected_without_losing_pending_records(self):
        self.add();self.now+=1800;rows=self.q.claim()
        with self.assertRaises(ValueError):self.q.acknowledge(rows,{})
        self.q.recover_inflight();self.assertEqual(self.q.summary()['pending_versions'],1)

    def test_scope_cannot_expand_and_out_of_scope_is_rejected(self):
        with self.assertRaises(ValueError):self.add('unapproved')
        with self.assertRaises(ValueError):DurableQueue(self.path,self.ids|{'new'})

    def test_older_version_found_after_sync_stays_superseded(self):
        self.add(version='new',completed='2026-10-18T01:00:00+00:00');self.now+=1800
        rows=self.q.claim();self.q.acknowledge(rows,{'new':'synced'})
        self.add(version='old')
        self.assertEqual(self.q.summary()['pending_versions'],0)

    def test_abrupt_process_exit_does_not_lose_committed_discovery(self):
        script="""import os,sys
from backend.video_data.batch_sync import DurableQueue
q=DurableQueue(sys.argv[1],{'v'})
q.enqueue([{'table':'video_semantics','key':'s','columns':{'video_id':'v'},'payload':{'completed_at':'2026-10-18T00:00:00+00:00'}}],'record.json')
os._exit(0)
"""
        path=Path(self.temp.name)/'crashed.sqlite'
        subprocess.run([sys.executable,'-B','-c',script,str(path)],check=True)
        recovered=DurableQueue(path,{'v'})
        try:self.assertEqual(recovered.summary()['pending_versions'],1)
        finally:recovered.close()

    def test_partial_artifact_is_not_queued_and_rescan_recovers_it(self):
        from backend.video_data.batch_sync import discover
        root=Path(self.temp.name)/'annotation'
        path=root/'semantic_pipeline/runs/run/videos/v/source/record.json'
        path.parent.mkdir(parents=True)
        entities=bundle();path.write_text(json.dumps(entities[0]['payload']))
        with patch('backend.video_data.batch_sync.Reader') as reader:
            reader.return_value.api=(None,lambda p:{},None,lambda p:{})
            reader.return_value.semantic_bundle.side_effect=FileNotFoundError('embedding not finalized')
            self.assertEqual(discover(self.q,root),0)
            self.assertEqual(self.q.summary()['pending_versions'],0)
            reader.return_value.semantic_bundle.side_effect=None
            reader.return_value.semantic_bundle.return_value=entities
            self.assertEqual(discover(self.q,root),1)
            self.assertEqual(discover(self.q,root),0)

    def test_corrupted_queue_body_is_never_delivered(self):
        self.add();self.now+=1800
        self.q.db.execute("UPDATE items SET bundle='[]'")
        with patch('builtins.print'):
            def writer(rows):raise AssertionError('Corrupt record must not reach writer')
            self.assertEqual(self.q.deliver(writer),0)
        self.assertEqual(self.q.summary()['pending_versions'],1)
