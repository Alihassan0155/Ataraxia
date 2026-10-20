import json
import unittest

from backend.video_data.category_completion import ROOT,accept,contract,missing

TAX=json.loads((ROOT/'annotation/semantic_pipeline/configs/taxonomy_category_ids_v1.json').read_text())


class CompletionTests(unittest.TestCase):
    def request(self):
        return {'video_id':'YT_test','original_category':'','input_hash':'a'*64,
                'sources':{'transcript':'The chef demonstrates a cooking recipe.'}}

    def test_exactly_18_choices_with_abstention_not_new_category(self):
        allowed,schema=contract(TAX)
        self.assertEqual(len(allowed),18)
        self.assertNotIn(TAX['category_ids']['unknown'],schema['properties']['category_id']['enum'])
        self.assertIn(None,schema['properties']['category_id']['enum'])

    def test_supported_choice_preserves_original_and_scope(self):
        result={'category_id':TAX['category_ids']['Food & Cooking'],
                'evidence':[{'source':'transcript','quote':'cooking recipe'}]}
        candidate=accept(self.request(),result,TAX,set())
        self.assertFalse(candidate['database_sync_allowed'])
        self.assertEqual(candidate['original_category'],'')
        self.assertEqual(candidate['effective_category'],'Food & Cooking')
        self.assertTrue(accept(self.request(),result,TAX,{'YT_test'})['database_sync_allowed'])

    def test_abstain_keeps_unknown_and_rejects_arbitrary_names(self):
        result=accept(self.request(),{'category_id':None,'evidence':[]},TAX,set())
        self.assertEqual(result['effective_category'],'unknown')
        for value in ['Comedy','invented',TAX['category_ids']['unknown'],['multiple']]:
            with self.assertRaises(Exception):accept(self.request(),{'category_id':value,'evidence':[]},TAX,set())

    def test_original_or_fabricated_evidence_cannot_be_overwritten(self):
        result={'category_id':TAX['category_ids']['Food & Cooking'],'evidence':[{'source':'transcript','quote':'fake'}]}
        with self.assertRaises(ValueError):accept(self.request(),result,TAX,{'YT_test'})
        result['evidence'][0]['quote']='cooking recipe'
        with self.assertRaises(ValueError):accept({**self.request(),'original_category':'Stand-up'},result,TAX,{'YT_test'})
        self.assertTrue(missing({'category_original':'unknown'}))
        self.assertFalse(missing({'category_original':'Stand-up'}))


if __name__=='__main__':unittest.main()
