import unittest
from backend.video_data.propose_categories import accept_proposal


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.request={'video_id':'test','original_category':'unknown','input_hash':'test',
                      'sources':{'transcript':'We discuss philosophy and existentialism.'}}
        self.taxonomy={'category_ids':{'unknown':'u','Science & Technology':'s'}}

    def accept(self,label,quote=None):
        evidence=[] if quote is None else [{'source':'transcript','quote':quote}]
        return accept_proposal(self.request,{'category':label,'evidence':evidence},self.taxonomy,set())

    def test_new_label_is_local_proposal_only(self):
        r=self.accept('Philosophy','philosophy and existentialism')
        self.assertTrue(r['proposed_new_category'])
        self.assertIsNone(r['effective_category_id'])
        self.assertFalse(r['database_sync_allowed'])
        self.assertEqual(r['status'],'proposal_requires_review')

    def test_existing_category_reuses_id(self):
        self.assertEqual(self.accept('Science & Technology','philosophy')['effective_category_id'],'s')

    def test_abstention_and_invalid_evidence(self):
        self.assertEqual(self.accept(None)['effective_category'],'unknown')
        with self.assertRaises(ValueError):self.accept('Philosophy','invented quote')
        with self.assertRaises(ValueError):self.accept('Philosophy')

    def test_source_category_cannot_be_overwritten(self):
        self.request['original_category']='Music'
        with self.assertRaises(ValueError):self.accept('Philosophy','philosophy')
