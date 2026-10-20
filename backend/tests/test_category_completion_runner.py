import json
from pathlib import Path
import tempfile
import unittest

from backend.video_data.run_category_completion import filler_only,load_inputs,summarize


class RunnerTests(unittest.TestCase):
    def test_filler_does_not_establish_category(self):
        self.assertTrue(filler_only({'transcript':'Hello! Ha ha ha!'}))
        self.assertTrue(filler_only({'transcript':'No! Huh? Mmm! Hee hee! Here you go! Do it!'}))
        self.assertFalse(filler_only({'transcript':'Let us cook rice.'}))
        self.assertFalse(filler_only({'transcript':'This is iPhone Duo.'}))

    def test_prepared_scope_is_exactly_172_and_excludes_evidence_empty(self):
        requests,_,_=load_inputs('backend/reports/category_completion_20261017')
        self.assertEqual(len(requests),172)
        self.assertTrue(all(r['disposition']=='awaiting_qwen_approval' for r in requests))
        self.assertTrue(all(any(r['sources'].values()) for r in requests))
        self.assertTrue(all(not r['database_exists'] for r in requests))

    def test_checkpoint_summary_reports_invalid_failed_and_abstained_separately(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);requests=[]
            for i,(status,category) in enumerate([('completed','Comedy'),('completed','unknown'),('failed',None),('invalid',None)]):
                request={'video_id':'V'+str(i),'input_hash':'hash'+str(i)};requests.append(request)
                folder=out/'videos'/request['video_id'];folder.mkdir(parents=True)
                result={**request,'execution_status':status,'run_id':'run'}
                if category:result['effective_category']=category
                (folder/'result.json').write_text(json.dumps(result),encoding='utf-8')
            report=summarize(out,requests,'run')
            self.assertEqual(report['total_processed'],4)
            self.assertEqual(report['successfully_classified'],1)
            self.assertEqual(report['unknown_abstained'],1)
            self.assertEqual(report['failed'],1)
            self.assertEqual(report['invalid_classifications'],1)
            self.assertEqual(report['database_writes'],0)
            self.assertEqual(len((out/'results.jsonl').read_text().splitlines()),4)
            with self.assertRaises(ValueError):summarize(out,requests,'wrong-run')


if __name__=='__main__':unittest.main()
