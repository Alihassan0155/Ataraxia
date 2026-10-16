import base64
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
import threading
import subprocess
import sys
from unittest.mock import patch

from ataraxia.distributed.common import lock, safe_id, under, write
from ataraxia.distributed.controller import database, export, reconcile, worker_command, initialize, schedule, csv_write, transport_options, launch, health_checks
from ataraxia.distributed.worker import execute

ROOT = Path(__file__).resolve().parents[1]


class DistributedTests(unittest.TestCase):
    def test_local_os_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'lock'
            with lock(p):
                with self.assertRaises(OSError):
                    with lock(p): pass
            with lock(p): pass

    def test_ids_and_paths_cannot_escape_run(self):
        with self.assertRaises(ValueError): safe_id('../secret')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): under(Path(d),'../secret')

    def test_ssh_quotes_unc_and_uses_host_key_validation(self):
        w = {'transport':'ssh','host':'worker@pc','root':r'\\main\share with space',
             'python':r'C:\Python path\python.exe','local_root':r'C:\worker', 'cache':r'C:\cache'}
        cmd = worker_command(w,'runs/distributed/run/attempts/abc')
        self.assertIn('StrictHostKeyChecking=yes',cmd)
        ps = base64.b64decode(cmd[-1]).decode('utf-16le')
        self.assertIn("'C:\\Python path\\python.exe'",ps)
        self.assertIn('\\\\main\\share with space',ps)
        self.assertNotIn('password',ps)

    def test_interactive_auth_preserves_key_option_and_task_transport(self):
        for transport in ('ssh', 'ssh-task'):
            w = {'transport':transport, 'host':'saad@10.104.112.18',
                 'root':r'\\main\share', 'python':r'D:\worker\python.exe',
                 'local_root':r'D:\worker\state', 'cache':r'D:\worker\cache'}
            self.assertIn('BatchMode=yes', worker_command(w, health=True))
            w['ssh_auth'] = 'interactive'
            for cmd in (worker_command(w, health=True), worker_command(w, 'attempt')):
                self.assertIn('BatchMode=no', cmd)
                self.assertNotIn('BatchMode=yes', cmd)
                self.assertIn('StrictHostKeyChecking=yes', cmd)
                self.assertIn(w['host'], cmd)
            self.assertEqual(transport_options({'transport':'local'}), {})

    def test_interactive_launch_keeps_prompt_streams_out_of_log(self):
        w = {'transport':'ssh', 'ssh_auth':'interactive', 'host':'lab@10.104.112.9',
             'root':r'\\main\share', 'python':r'D:\worker\python.exe',
             'local_root':r'D:\worker\state', 'cache':r'D:\worker\cache'}
        with tempfile.TemporaryDirectory() as d, patch('ataraxia.distributed.controller.subprocess.run') as run:
            run.return_value.returncode = 0
            with patch('ataraxia.distributed.controller.transport_options', return_value={'creationflags':16}):
                self.assertEqual(launch(w, 'attempt', Path(d)/'log', 10), 0)
            self.assertIsNone(run.call_args.kwargs['stderr'])
            self.assertEqual(run.call_args.kwargs['creationflags'], 16)
            self.assertNotIn('input', run.call_args.kwargs)
            self.assertEqual((Path(d)/'log').read_bytes(), b'')

    def test_interactive_health_captures_json_without_prompt_stderr(self):
        w = {'id':'gpu3', 'transport':'ssh', 'ssh_auth':'interactive', 'host':'lab@10.104.112.9',
             'root':r'\\main\share', 'python':r'D:\worker\python.exe',
             'local_root':r'D:\worker\state', 'cache':r'D:\worker\cache'}
        with patch('ataraxia.distributed.controller.subprocess.run') as run, \
             patch('ataraxia.distributed.controller.transport_options', return_value={'creationflags':16}):
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps({'utc_time':time.time(), 'machine':'LAB12-PC08'})
            run.return_value.stderr = None
            self.assertTrue(health_checks({'workers':[w]})['gpu3']['ok'])
            self.assertIsNone(run.call_args.kwargs['stderr'])
            run.return_value.returncode = 255
            run.return_value.stdout = ''
            failure = health_checks({'workers':[w]})['gpu3']
            self.assertFalse(failure['ok'])
            self.assertIn('SSH exited 255', failure['error'])

    def test_remote_wrapper_preserves_quoted_paths_and_reports_missing_entry(self):
        w = {'transport':'ssh', 'ssh_auth':'interactive', 'host':'lab@10.104.112.9',
             'root':r'\\main\share with spaces', 'python':r"D:\Ali's worker\python.exe",
             'local_root':r'D:\worker\state', 'cache':r'D:\worker\cache'}
        ps = base64.b64decode(worker_command(w, health=True)[-1]).decode('utf-16le')
        self.assertIn("'D:\\Ali''s worker\\python.exe'", ps)
        self.assertIn('Test-Path -LiteralPath', ps)
        self.assertIn('Project share inaccessible', ps)
        self.assertIn('Worker entry script missing', ps)
        self.assertIn('2>&1 | ForEach-Object', ps)
        self.assertIn('ATARAXIA_REMOTE_ERROR', ps)
        self.assertIn('exit $code', ps)

    def test_health_failure_saves_remote_diagnostics_locally(self):
        w = {'id':'gpu2','transport':'ssh','ssh_auth':'interactive',
             'host':'saad@10.104.112.18','root':r'\\main\share',
             'python':r'C:\worker\python.exe','local_root':r'C:\state','cache':r'C:\cache'}
        with tempfile.TemporaryDirectory() as d, \
             patch('ataraxia.distributed.controller.transport_options',return_value={}), \
             patch('ataraxia.distributed.controller.subprocess.run') as run:
            run.return_value.returncode=2
            run.return_value.stdout='python.exe: cannot open worker entry script\nATARAXIA_REMOTE_EXIT=2'
            run.return_value.stderr=None
            result=health_checks({'controller_root':d,'workers':[w]})['gpu2']
            self.assertFalse(result['ok'])
            self.assertIn('cannot open',result['error'])
            saved=json.loads(Path(result['diagnostic_log']).read_text())
            self.assertEqual(saved['returncode'],2)
            self.assertIn('cannot open',saved['stdout'])
            self.assertIsNone(saved['stderr'])

    def test_task_trigger_never_opens_unc_from_ssh_session(self):
        w = {'transport':'ssh-task','ssh_auth':'interactive','host':'saad@10.104.112.18',
             'root':r'\\main\share','python':r'D:\ALI\AtaraxiaWorker\venv\Scripts\python.exe',
             'local_root':r'D:\ALI\AtaraxiaWorker','cache':r'D:\ALI\AtaraxiaWorker\cache\hub',
             'task_name':'AtaraxiaGPUWorker'}
        for cmd in (worker_command(w, health=True),worker_command(w,'attempt')):
            ps=base64.b64decode(cmd[-1]).decode('utf-16le')
            self.assertIn('schtasks.exe /Run /TN',ps)
            self.assertIn('2>&1',ps)
            self.assertNotIn(w['root'],ps)
            self.assertNotIn('Test-Path',ps)
            self.assertIn('BatchMode=no',cmd)

    def test_task_bootstrap_records_share_failure_without_shared_imports(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            r=subprocess.run([sys.executable,str(ROOT/'commands/distributed_task_bootstrap.py'),
                              '--root',str(folder/'missing_share'),'--worker','gpu2',
                              '--local-root',str(folder/'state'),'--cache',str(folder/'cache'),
                              '--logs',str(folder/'logs')],capture_output=True,text=True)
            self.assertNotEqual(r.returncode,0)
            diagnostic=json.loads((folder/'logs/last_dispatch.json').read_text())
            self.assertIn('Project share inaccessible',diagnostic['error'])
            self.assertEqual(diagnostic['worker'],'gpu2')

    def test_local_task_bootstrap_delivers_health_report_from_inbox(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            package=folder/'src/ataraxia/distributed'
            package.mkdir(parents=True)
            (package/'__init__.py').write_text('')
            (package.parent/'__init__.py').write_text('')
            (package/'common.py').write_text((ROOT/'src/ataraxia/distributed/common.py').read_text())
            commands=folder/'commands'
            commands.mkdir()
            (commands/'distributed_worker.py').write_text('import json; print(json.dumps({"machine":"fixture","utc_time":1}))')
            write(folder/'runs/distributed_inbox/gpu2.json',{'health_result':'runs/probe.json'})
            (folder/'state').mkdir()
            r=subprocess.run([sys.executable,str(ROOT/'commands/distributed_task_bootstrap.py'),
                              '--root',str(folder),'--worker','gpu2',
                              '--local-root',str(folder/'state'),'--cache',str(folder/'cache'),
                              '--logs',str(folder/'logs')],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(json.loads((folder/'runs/probe.json').read_text())['machine'],'fixture')
            self.assertEqual(json.loads((folder/'logs/last_dispatch.json').read_text())['stage'],'health_passed')

    def fixture(self, d, deadline=None):
        run = Path(d)
        run.mkdir(parents=True,exist_ok=True)
        db = database(run)
        db.execute("INSERT INTO jobs(model,video_id,state,tries,attempt) VALUES ('qwen','V1','running',1,'a')")
        db.execute("INSERT INTO jobs(model,video_id,state,tries,attempt) VALUES ('qwen','V2','running',1,'a')")
        db.execute("INSERT INTO attempts(id,worker,model,started,deadline) VALUES ('a','gpu1','qwen',?,?)",
                   (time.time(),deadline if deadline is not None else time.time()+100))
        db.commit()
        folder = run/'attempts/a/output/pilot'; folder.mkdir(parents=True)
        source = ROOT/'pilot_50_reels_30h/results/pilot50_qwen_nf4_max32_limit15p8_v5/qwen/pilot/annotations.jsonl'
        item = json.loads(source.read_text().splitlines()[0])
        item['video_id']='V1'
        item['run_metadata'].update(revision='revision',media_sha256='media',peak_device_gib=12)
        frozen = {'models':{'qwen':{'revision':'revision'}},'inputs':{'V1':{'videos_sha256':'media'}}}
        return run,db,folder,item,frozen

    def test_partial_batch_accepts_valid_and_retries_only_missing(self):
        with tempfile.TemporaryDirectory() as d:
            run,db,folder,item,frozen = self.fixture(d)
            (folder/'annotations.jsonl').write_text(json.dumps(item)+'\n{truncated',encoding='utf-8')
            write(run/'attempts/a/receipt.json',{'machine':'testpc','exit_code':1})
            reconcile(db,run,frozen,3)
            states = {r['video_id']:r['state'] for r in db.execute('SELECT * FROM jobs')}
            self.assertEqual(states,{'V1':'done','V2':'pending'})
            reconcile(db,run,frozen,3)  # repeated reconciliation must not duplicate output
            export(db,run)
            self.assertEqual(len((run/'results/qwen/annotations.jsonl').read_text().splitlines()),1)
            db.close()

    def test_disconnect_waits_for_deadline_not_immediate_requeue(self):
        with tempfile.TemporaryDirectory() as d:
            run,db,folder,item,frozen = self.fixture(d)
            reconcile(db,run,frozen,3)
            self.assertEqual(db.execute("SELECT state FROM jobs LIMIT 1").fetchone()[0],'running')
            db.execute('UPDATE attempts SET deadline=0'); db.commit()
            reconcile(db,run,frozen,1)
            self.assertEqual(db.execute("SELECT state FROM jobs LIMIT 1").fetchone()[0],'failed')
            db.close()

    def test_bad_revision_and_memory_gate_are_not_published(self):
        for bad in ({'revision':'wrong'},{'peak_device_gib':16.1}):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as d:
                run,db,folder,item,frozen = self.fixture(d,0)
                item['run_metadata'].update(bad)
                (folder/'annotations.jsonl').write_text(json.dumps(item)+'\n')
                reconcile(db,run,frozen,1)
                self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE state='done'").fetchone()[0],0)
                db.close()

    def test_full_run_is_blocked_without_real_smoke_proof(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'smoke-run'):
                initialize(Path(d),Path(d)/'new',Path(d)/'not_read.csv',0,['qwen'])

    def test_duplicate_result_is_quarantined(self):
        with tempfile.TemporaryDirectory() as d:
            run,db,folder,item,frozen = self.fixture(d,0)
            (folder/'annotations.jsonl').write_text((json.dumps(item)+'\n')*2)
            reconcile(db,run,frozen,1)
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE state='done'").fetchone()[0],0)
            db.close()

    def test_scheduled_transport_only_triggers_registered_task(self):
        w = {'transport':'ssh-task','host':'worker@pc','root':r'\\main\share',
             'python':r'C:\python.exe','local_root':r'C:\worker','cache':r'C:\cache'}
        cmd=worker_command(w,'runs/distributed/test/attempts/a')
        ps=base64.b64decode(cmd[-1]).decode('utf-16le')
        self.assertIn('schtasks.exe /Run',ps)
        self.assertNotIn('password',ps)

    def test_three_concurrent_mock_workers_publish_unique_results(self):
        # Exercises the real controller/database/export; transport/inference are fake.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); run=root/'runs/distributed/test'; run.mkdir(parents=True)
            _, fixture_db, _, template, _ = self.fixture(root/'fixture')
            fixture_db.close()
            ids=['V'+str(i) for i in range(1,7)]
            frozen={'sources':{},'models':{'qwen':{'revision':'revision'}},
                    'inputs':{v:{'videos_sha256':'media'} for v in ids}}
            write(run/'frozen.json',frozen)
            csv_write(run/'metadata.csv',[{'assigned_id':v,'duration':'1'} for v in ids])
            db=database(run)
            db.executemany('INSERT INTO jobs(model,video_id) VALUES (?,?)',[('qwen',v) for v in ids])
            db.commit(); db.close()
            c={'workers':[{'id':'w'+str(i),'transport':'local'} for i in range(3)],'batch_size':2,'max_attempts':1}
            gate=threading.Lock(); active=0; maximum=0
            def fake_launch(w,relative,log,timeout):
                nonlocal active,maximum
                with gate: active+=1; maximum=max(maximum,active)
                time.sleep(.2)
                folder=root/relative
                request=json.loads((folder/'request.json').read_text())
                out=folder/'output/pilot'; out.mkdir(parents=True)
                results=[]
                for vid in request['ids']:
                    item=copy.deepcopy(template); item['video_id']=vid; results.append(json.dumps(item))
                (out/'annotations.jsonl').write_text('\n'.join(results)+'\n')
                write(folder/'receipt.json',{'machine':w['id'],'exit_code':0})
                with gate: active-=1
                return 0
            health={w['id']:{'ok':True,'machine':w['id']} for w in c['workers']}
            with patch('ataraxia.distributed.controller.health_checks',return_value=health), patch('ataraxia.distributed.controller.launch',side_effect=fake_launch):
                schedule(root,run,c)
            self.assertEqual(maximum,3)
            rows=[json.loads(s) for s in (run/'results/qwen/annotations.jsonl').read_text().splitlines()]
            self.assertEqual({r['video_id'] for r in rows},set(ids))
            self.assertEqual(len(rows),6)

    def worker_fixture(self, root, lease):
        run=root/'runs/test'; attempt=run/'attempts/a'; attempt.mkdir(parents=True)
        write(run/'frozen.json',{'sources':{},'models':{'qwen':{'packages':{},'arguments':[]}}})
        write(attempt/'request.json',{'run_relative':'runs/test','model':'qwen','ids':[],
              'worker_id':'test','attempt':'a','timeout_seconds':1,'lease_deadline':lease})
        return attempt

    def test_expired_lease_never_loads_backend(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); attempt=self.worker_fixture(root,0)
            with patch('ataraxia.distributed.worker.runpy.run_module') as backend:
                with self.assertRaisesRegex(RuntimeError,'lease expired'):
                    execute(root,attempt,root/'local',root/'cache')
                backend.assert_not_called()

    def test_local_deadline_terminates_even_when_shared_write_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); attempt=self.worker_fixture(root,time.time()+60)
            program = '''
import time
from pathlib import Path
from unittest.mock import patch
from ataraxia.distributed.worker import execute
import sys
r=Path(sys.argv[1])
with patch('ataraxia.distributed.worker.health',return_value={'packages':{},'gpu':'RTX A4000'}), patch('ataraxia.distributed.worker.write',side_effect=lambda *args: time.sleep(20)):
    execute(r,r/'runs/test/attempts/a',r/'local',r/'cache')
'''
            start=time.monotonic()
            result=subprocess.run([sys.executable,'-c',program,str(root)],timeout=8,capture_output=True)
            self.assertEqual(result.returncode,124,result.stderr.decode())
            self.assertLess(time.monotonic()-start,8)


if __name__ == '__main__': unittest.main()
