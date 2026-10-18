import hashlib
from pathlib import Path
import tempfile
import unittest
from backend.video_data.s3_dry_run import destination,map_files


class S3DryRunTests(unittest.TestCase):
    def test_exact_approved_object_keys(self):
        self.assertEqual(destination('FV000002','HuggingFaceFV/finevideo','videos/'),
                         ('finevideo','videos/finevideo/FV000002.mp4'))
        self.assertEqual(destination('TT_123','Suthans/tiktok','videos/'),
                         ('tiktok','videos/tiktok/TT_123.mp4'))

    def test_other_sources_and_prefix_traversal_rejected(self):
        for vid,source,prefix in [('YT_1','youtube','videos/'),('FV1','tiktok','videos/'),('FV1','finevideo','../videos/')]:
            with self.assertRaises(ValueError):destination(vid,source,prefix)

    def test_file_hash_selects_correct_copy_and_retains_exact_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bad=root/'bad/FV000001.mp4';good=root/'good/FV000001.mp4'
            bad.parent.mkdir();good.parent.mkdir();bad.write_bytes(b'wrong');good.write_bytes(b'correct')
            row={'video_id':'FV000001','source_dataset':'finevideo','media_uri':str(bad),
                 'media_sha256':hashlib.sha256(b'correct').hexdigest()}
            results,_=map_files([row],'existing-bucket','videos/',[root])
            self.assertEqual(results[0]['source_path'],str(good.resolve()))
            self.assertEqual(results[0]['status'],'matched_sha256')
            self.assertTrue(results[0]['rejected_candidates'])

    def test_missing_file_and_duplicate_ids_are_not_upload_candidates(self):
        row={'video_id':'FV000001','source_dataset':'finevideo','media_sha256':'a'*64}
        results,_=map_files([row],'bucket','videos/',[])
        self.assertEqual(results[0]['status'],'missing_local_file')
        with self.assertRaises(ValueError):map_files([row,row],'bucket','videos/',[])
