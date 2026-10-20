import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.video_data.category_completion import ROOT,accept
from backend.video_data.review_category_completion import finalize


class ReviewTests(unittest.TestCase):
    def test_review_abstains_without_overwriting_raw_checkpoint(self):
        taxonomy=json.loads((ROOT/'annotation/semantic_pipeline/configs/taxonomy_category_ids_v1.json').read_text())
        request={'video_id':'V','input_hash':'hash','original_category':'',
                 'sources':{'transcript':'An unspecified kit is available.'}}
        raw={'category_id':taxonomy['category_ids']['Beauty & Style'],
             'evidence':[{'source':'transcript','quote':'An unspecified kit is available.'}]}
        record={**accept(request,raw,taxonomy,set()),'execution_status':'completed','raw_response':raw,'run_id':'run'}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'videos/V';folder.mkdir(parents=True)
            (root/'run.json').write_text(json.dumps({'run_id':'run'}),encoding='utf-8')
            checkpoint=folder/'result.json';original=json.dumps(record);checkpoint.write_text(original,encoding='utf-8')
            with patch('backend.video_data.review_category_completion.load_inputs',return_value=([request],taxonomy,{})):
                report=finalize('unused',root,{'V':'Kit type is not established by content.'})
            self.assertEqual(report['successfully_classified'],0)
            self.assertEqual(report['unknown_abstained'],1)
            self.assertEqual(report['unsupported_category_proposals_rejected'],1)
            self.assertEqual(checkpoint.read_text(encoding='utf-8'),original)
            reviewed=json.loads((root/'reviewed/V.json').read_text(encoding='utf-8'))
            self.assertEqual(reviewed['qwen_proposed_category'],'Beauty & Style')
            self.assertEqual(reviewed['effective_category'],'unknown')
            self.assertEqual(reviewed['evidence'],[])
            self.assertFalse(reviewed['database_sync_allowed'])


if __name__=='__main__':unittest.main()
