"""Offline safeguards for the manifest-only uploader."""
import hashlib
import io
import unittest
from unittest.mock import Mock
from backend.video_data.s3_upload import load_rows, verify

class UploadSafetyTests(unittest.TestCase):
    def test_frozen_scope_and_unique_mapping(self):
        rows=load_rows()
        self.assertEqual(len(rows),1140)
        self.assertEqual(len({r['s3_key'] for r in rows}),1140)
        self.assertEqual(sum(r['size_bytes'] for r in rows),4492269234)

    def test_full_download_checks_hash_not_etag(self):
        client=Mock()
        client.head_object.return_value={'ContentLength':3,'ETag':'multipart-etag-2'}
        client.get_object.return_value={'Body':io.BytesIO(b'abc')}
        row={'s3_key':'videos/finevideo/FV1.mp4','size_bytes':3,'sha256':hashlib.sha256(b'abc').hexdigest()}
        self.assertEqual(verify(client,row)['verified_sha256'],row['sha256'])
        self.assertEqual(client.get_object.call_args.kwargs['IfMatch'],'multipart-etag-2')

    def test_same_size_wrong_content_rejected(self):
        client=Mock()
        client.head_object.return_value={'ContentLength':3,'ETag':'etag'}
        client.get_object.return_value={'Body':io.BytesIO(b'bad')}
        row={'s3_key':'videos/finevideo/FV1.mp4','size_bytes':3,'sha256':hashlib.sha256(b'abc').hexdigest()}
        with self.assertRaisesRegex(ValueError,'content hash'):verify(client,row)

    def test_wrong_size_rejected_before_download(self):
        client=Mock()
        client.head_object.return_value={'ContentLength':2,'ETag':'etag'}
        with self.assertRaisesRegex(ValueError,'size'):verify(client,{'s3_key':'x','size_bytes':3})
        client.get_object.assert_not_called()
