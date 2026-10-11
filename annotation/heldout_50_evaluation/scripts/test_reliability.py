"""Regression tests without real model generation, network calls or secrets."""
import sys
import json
import unittest
import time
from unittest.mock import patch
from types import SimpleNamespace
from support import ROOT
from schema_repair import emotion_repair_instruction, normalize_emotion_points
from common_annotation import validate_emotion_points
import annotate_gemini as existing
from run_gemini import bounded_video, rotating_video, GeminiWorkerError


def hanging_worker(messages,*args):time.sleep(30)


class ReliabilityTests(unittest.TestCase):
    def test_key_failover_retries_same_video(self):
        for failure in [TimeoutError('hung'), GeminiWorkerError('quota', 'AllGeminiKeysUnavailable')]:
            calls=[]
            def runner(keys,vid,slot,disabled,cfg,**kwargs):
                calls.append((vid,slot,kwargs['deadline_seconds']))
                if slot==0:raise failure
                return {'video_id':vid},slot
            with patch('run_gemini.append'):
                result,index=rotating_video(['fake-a','fake-b'],'test',0,set(),{},runner)
            self.assertEqual(index,1)
            self.assertEqual([c[:2] for c in calls],[('test',0),('test',1)])
            self.assertTrue(all(c[2]<=180 for c in calls))

    def test_disabled_key_skipped_and_validation_not_rotated(self):
        calls=[]
        def runner(keys,vid,slot,disabled,cfg,**kwargs):
            calls.append(slot)
            raise GeminiWorkerError('schema','ValueError')
        with patch('run_gemini.append'):
            with self.assertRaises(GeminiWorkerError):rotating_video(['a','b'],'test',0,{0},{},runner)
        self.assertEqual(calls,[1])

    def test_total_failover_budget_is_bounded(self):
        calls=[]
        def runner(*args,**kwargs):
            calls.append(1)
            raise TimeoutError('hung')
        with patch('run_gemini.append'),patch('run_gemini.time.monotonic',side_effect=[0,0,601]):
            with self.assertRaises(GeminiWorkerError):rotating_video(['a','b'],'test',0,set(),{},runner)
        self.assertEqual(len(calls),1)

    def test_normalization_preserves_raw_and_exact_total(self):
        keys=['joy','sadness','anger','fear_anxiety','surprise','disgust','calm_contentment','neutral']
        for total_case in [[1,1,3,1,2,1,1,1],[.1]*8,[10]*8]:
            raw={'emotions':dict(zip(keys,total_case)),'dominant_emotion':'neutral','valence':-.3}
            original=json.dumps(raw)
            corrected,audit=normalize_emotion_points(raw)
            validate_emotion_points(corrected)
            self.assertEqual(json.dumps(raw),original)
            self.assertEqual(corrected['valence'],-.3)
            self.assertTrue(audit['applied'])
            self.assertEqual(corrected['emotions'][corrected['dominant_emotion']],max(corrected['emotions'].values()))

    def test_normalization_rejects_bad_vectors(self):
        keys=['joy','sadness','anger','fear_anxiety','surprise','disgust','calm_contentment','neutral']
        for value in [0,-1,float('nan'),float('inf'),True,11]:
            with self.assertRaises(ValueError):normalize_emotion_points({'emotions':dict.fromkeys(keys,value)})
        with self.assertRaises(ValueError):normalize_emotion_points({'emotions':{'joy':1}})

    def test_repair_explains_actual_eleven_and_remainder(self):
        scores=dict(zip(['joy','sadness','anger','fear_anxiety','surprise','disgust','calm_contentment','neutral'],[1,1,3,1,2,1,1,1]))
        original=json.dumps({'emotions':scores})
        guidance=emotion_repair_instruction(original,'bad total')
        self.assertIn('total is 11',guidance)
        self.assertIn('neutral MUST be 0',guidance)
        self.assertEqual(json.loads(original)['emotions']['neutral'],1)
        with self.assertRaises(ValueError):validate_emotion_points({'emotions':scores})
        scores['neutral']=0
        probabilities,_=validate_emotion_points({'emotions':scores})
        self.assertAlmostEqual(sum(probabilities['emotions'].values()),1)

    def test_upload_processing_deadline(self):
        file=SimpleNamespace(name='mock',state=SimpleNamespace(name='PROCESSING'))
        client=SimpleNamespace(files=SimpleNamespace(get=lambda **kwargs:file))
        with patch.object(existing.time,'monotonic',side_effect=[0,181]):
            with self.assertRaises(TimeoutError):existing.wait_until_active(client,file,'test')

    def test_failed_upload_state_is_reported(self):
        file=SimpleNamespace(name='mock',state=SimpleNamespace(name='FAILED'))
        client=SimpleNamespace(files=SimpleNamespace(get=lambda **kwargs:file))
        with patch.object(existing,'PROGRESS_HOOK') as log:
            with self.assertRaises(RuntimeError):existing.wait_until_active(client,file,'test')
            log.assert_called_with('test','processing',state='FAILED')

    def test_hung_worker_is_bounded(self):
        started=time.monotonic()
        with self.assertRaises(TimeoutError):bounded_video([],'test',0,set(),{},deadline_seconds=.2,target=hanging_worker)
        self.assertLess(time.monotonic()-started,8)


if __name__=='__main__':unittest.main()
