import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from backend.video_data.s3_references import audit_rows,load_plan,main,sha

class ReferenceSafetyTests(unittest.TestCase):
    def test_verified_scope(self):
        rows=audit_rows()
        self.assertEqual(len(rows),1140)
        self.assertEqual(len({r['video_id'] for r in rows}),1140)

    def test_plan_checksum_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            p.joinpath('plan.json').write_text('{}')
            p.joinpath('checksums.json').write_text(json.dumps({'plan.json':'0'*64}))
            with self.assertRaisesRegex(ValueError,'checksum'):load_plan(p)

    def test_remapped_uri_rejected_even_with_new_checksum(self):
        plan=load_plan('backend/reports/s3_references_20261018')
        plan=copy.deepcopy(plan);plan['records'][0]['after']['media_uri']='s3://other/key'
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);p.joinpath('plan.json').write_text(json.dumps(plan))
            p.joinpath('checksums.json').write_text(json.dumps({'plan.json':sha(p/'plan.json')}))
            with self.assertRaisesRegex(ValueError,'mapping mismatch'):load_plan(p)

    def test_unapproved_apply_never_connects(self):
        with patch('sys.argv',['s3_references','apply','--package','unused']),patch('backend.video_data.s3_references.connect') as connect,patch('builtins.print'):
            with self.assertRaises(SystemExit):main()
            connect.assert_not_called()
