import unittest
from backend.video_data.category_discovery import discovery_contract,validate_candidate,group_reviewed
from backend.video_data.artifacts import fingerprint


class DiscoveryTests(unittest.TestCase):
    def candidate(self,vid='v',label='History & Archaeology'):
        request={'video_id':vid,'original_category':'','input_hash':'h',
                 'sources':{'transcript':'This stone toilet is 2700 years old.'}}
        return validate_candidate(request,{'category':label,'description':'Historical places and material culture.',
            'existing_fit':'The central theme is historical material culture, not technology.',
            'evidence':[{'source':'transcript','quote':'2700 years old'}]},
            {'category_ids':{'unknown':'u','Science & Technology':'s'}})

    def test_open_prompt_and_schema(self):
        c=discovery_contract()
        self.assertNotIn('enum',c['output_schema']['properties']['category'])
        self.assertIn('not allowed choices or preferred answers',c['prompt'])
        self.assertEqual(self.candidate()['status'],'requires_content_review')

    def test_no_review_means_no_accepted_category(self):
        report=group_reviewed([self.candidate()],{})
        self.assertEqual(report['accepted_local_new_categories'],[])
        self.assertEqual(len(report['unsupported_or_unreviewed']),1)

    def test_explicit_synonyms_merge_and_count_distinct_videos(self):
        a=self.candidate();b=self.candidate('v2','History and Archaeology')
        reviews={c['video_id']:{'candidate_hash':fingerprint(c),'decision':'supported',
            'reviewer':'test reviewer','reason':'Historical artifact evidence supports the theme.',
            'existing_categories_inadequate':True,'canonical_name':'History & Archaeology',
            'synonym_reason':'and and ampersand express the same category.',
            'description':'Historical places and material culture.'} for c in (a,b)}
        r=group_reviewed([a,b,a],reviews)
        self.assertEqual(len(r['accepted_local_new_categories']),1)
        self.assertEqual(r['accepted_local_new_categories'][0]['frequency'],2)

    def test_stale_review_cannot_accept(self):
        c=self.candidate()
        r=group_reviewed([c],{'v':{'candidate_hash':'wrong','decision':'supported'}})
        self.assertFalse(r['accepted_local_new_categories'])
