import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.video_data.execute_catalogue import execute
from backend.video_data.rehearse_catalogue import compare
from backend.video_data.catalogue import ORDER
from datetime import datetime,timezone,timedelta


class ExecutionSafetyTests(unittest.TestCase):
    def test_default_does_not_launch_database_tools(self):
        with patch('backend.video_data.execute_catalogue.preflight',return_value=(Path('.'),'ROLLBACK;\n',{})),patch('subprocess.run',side_effect=AssertionError('No execution')):
            self.assertEqual(execute('.')['production_writes'],0)

    def test_approval_without_writer_ack_cannot_execute(self):
        with patch('backend.video_data.execute_catalogue.preflight',return_value=(Path('.'),'ROLLBACK;\n',{})),patch('subprocess.run',side_effect=AssertionError('No execution')):
            with self.assertRaisesRegex(ValueError,'writer-pause'):execute('.',True)

    def test_unconfirmed_writer_ack_cannot_execute(self):
        with tempfile.TemporaryDirectory() as temp:
            ack=Path(temp)/'ack.json';ack.write_text(json.dumps({'all_local_remote_writers_paused':False}))
            with patch('backend.video_data.execute_catalogue.preflight',return_value=(Path(temp),'ROLLBACK;\n',{})),patch('subprocess.run',side_effect=AssertionError('No execution')):
                with self.assertRaisesRegex(ValueError,'quiescence'):execute(temp,True,ack)

    def test_native_restore_compares_timestamp_instants_and_vector_values(self):
        a={t:[] for t in ORDER};b={t:[] for t in ORDER}
        a['videos']=[{'video_id':'v','created_at':'2026-10-17T00:00:00+00:00'}]
        b['videos']=[{'video_id':'v','created_at':datetime(2026,10,17,5,tzinfo=timezone(timedelta(hours=5)))}]
        compare(a,b)
        b['videos'][0]['created_at']+=timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError,'Timestamp'):compare(a,b)
