import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ataraxia.annotation.backends import gemini_execution as runner


class AllKeysTests(unittest.TestCase):
    def test_non_timeout_failure_tries_next_key_on_same_video(self):
        seen=[]
        def attempt(keys,vid,slot,disabled,cfg,deadline_seconds):
            seen.append((vid,slot,deadline_seconds))
            if slot==0:raise runner.GeminiWorkerError('bad result','ValueError')
            return {'video_id':vid},slot
        with tempfile.TemporaryDirectory() as d, patch.object(runner,'ROOT',Path(d)), \
             patch.dict(os.environ,{'ATARAXIA_GEMINI_ALL_KEYS_BEFORE_STOP':'1'}):
            result,slot=runner.rotating_video(['a','b'],'V1',0,set(),{},attempt)
        self.assertEqual(slot,1)
        self.assertEqual(seen,[('V1',0,180),('V1',1,180)])

    def test_every_available_key_tried_without_600_second_cutoff(self):
        seen=[]
        def attempt(keys,vid,slot,disabled,cfg,deadline_seconds):
            seen.append(slot)
            raise TimeoutError('timeout')
        with tempfile.TemporaryDirectory() as d, patch.object(runner,'ROOT',Path(d)), \
             patch.dict(os.environ,{'ATARAXIA_GEMINI_ALL_KEYS_BEFORE_STOP':'1'}), \
             patch.object(runner.time,'monotonic',side_effect=[0]+[10000]*30):
            with self.assertRaisesRegex(runner.GeminiWorkerError,'all available keys failed'):
                runner.rotating_video(list('abcdef'),'V1',0,{2},{},attempt)
        self.assertEqual(seen,[0,1,3,4,5])

    def test_main_stops_before_next_video_and_preserves_resume(self):
        from ataraxia.annotation.backends import gemini
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            metadata=folder/'metadata.csv'
            metadata.write_text('assigned_id\nV1\nV2\n',encoding='utf-8')
            with patch.object(runner,'OUTPUT_ROOT',folder),patch.object(runner,'ROOT',folder), \
                 patch.object(runner,'metadata_path',return_value=metadata), \
                 patch.object(runner,'load_processed_ids',return_value=set()), \
                 patch.object(gemini,'load_api_keys',return_value=['secret']), \
                 patch.object(runner,'rotating_video',side_effect=runner.GeminiWorkerError('exhausted','KeyFailoverExhausted')) as call, \
                 patch.dict(os.environ,{'ATARAXIA_GEMINI_ALL_KEYS_BEFORE_STOP':'1'}):
                with self.assertRaises(SystemExit):runner.main()
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args[1],'V1')
            status=json.loads((folder/'gemini/status.json').read_text())
            self.assertEqual(status['completed'],0)
            self.assertEqual(status['failed_video_ids'],['V1'])


if __name__=='__main__':unittest.main()
