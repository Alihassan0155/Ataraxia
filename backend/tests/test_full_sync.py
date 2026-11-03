import base64
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

from backend.video_data.full_sync import Conflict, insert, insert_batch, log, same, target_key, verify_s3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reports/s3_dry_run_20261018/dependencies'))
from botocore.exceptions import ClientError


class FullSyncTests(unittest.TestCase):
    def test_completed_report_with_timestamp_can_be_logged(self):
        output = io.StringIO()
        with redirect_stdout(output):
            log('verified', at='2026-11-03T17:02:35+00:00', missing_entities={})
        self.assertEqual(json.loads(output.getvalue())['event'], 'verified')

    def test_platforms_keep_canonical_ids(self):
        for platform, vid, source in [('youtube', 'YT__abc', '_abc'),
                                      ('tiktok', 'TT_123', '123'),
                                      ('finevideo', 'FV000001', 'FV000001')]:
            self.assertEqual(target_key(dict(platform=platform, assigned_id=vid, source_id=source)),
                             f'videos/{platform}/{vid}.mp4')
        with self.assertRaises(Conflict):
            target_key(dict(platform='youtube', assigned_id='YT_wrong', source_id='original'))

    def test_existing_video_metadata_never_written(self):
        columns = dict(media_sha256='a' * 64, media_uri='s3://bucket/key', title='local title')
        item = dict(table='videos', key='YT_a', content_hash='local', payload={}, columns=columns)
        actual = dict(video_id='YT_a', **columns)
        actual['title'] = 'valid remote title'
        cur = Mock()
        cur.description = [Mock(name=None) for _ in actual]
        for desc, name in zip(cur.description, actual):
            desc.name = name
        cur.fetchone.return_value = tuple(actual.values())
        conn = Mock()
        conn.execute.return_value = cur
        self.assertFalse(insert(conn, item, 'extensions'))
        self.assertEqual(conn.execute.call_count, 1)
        actual['media_sha256'] = 'b' * 64
        cur.fetchone.return_value = tuple(actual.values())
        with self.assertRaises(Conflict):
            insert(conn, item, 'extensions')
        self.assertEqual(conn.execute.call_count, 2)

    def test_existing_vector_must_match_exactly(self):
        self.assertTrue(same({'embedding': [1., 0.]}, {'embedding': '[1,0]'}))
        self.assertFalse(same({'embedding': [1., 0.]}, {'embedding': '[0,1]'}))

    def media(self):
        return dict(video_id='YT_a', key='videos/youtube/YT_a.mp4', sha256='a' * 64,
                    size=10, existing=False, path='test.mp4')

    def test_matching_remote_checksum_never_uploads(self):
        c = Mock()
        c.head_object.return_value = dict(ContentLength=10, ETag='etag',
            ChecksumSHA256=base64.b64encode(bytes.fromhex('a' * 64)).decode())
        self.assertEqual(verify_s3(c, self.media(), True)['proof'], 's3_full_object_sha256')
        c.put_object.assert_not_called()
        c.get_object.assert_not_called()

    def test_size_conflict_stops_without_upload(self):
        c = Mock()
        c.head_object.return_value = dict(ContentLength=9)
        with self.assertRaises(Conflict):
            verify_s3(c, self.media(), True)
        c.put_object.assert_not_called()

    def test_missing_object_uses_conditional_put_and_checksum(self):
        c = Mock()
        digest = base64.b64encode(bytes.fromhex('a' * 64)).decode()
        c.head_object.side_effect = [ClientError({'Error': {'Code': '404'}}, 'HeadObject'),
            dict(ContentLength=10, ETag='etag', ChecksumSHA256=digest)]
        stream = Mock()
        with patch('backend.video_data.full_sync.sha', return_value=('a' * 64, 10, 0)), \
                patch('pathlib.Path.open') as opened:
            opened.return_value.__enter__.return_value = stream
            verify_s3(c, self.media(), True)
        self.assertEqual(c.put_object.call_args.kwargs['IfNoneMatch'], '*')
        self.assertEqual(c.put_object.call_args.kwargs['ChecksumSHA256'], digest)

    def test_missing_preexisting_object_not_recreated(self):
        c = Mock()
        c.head_object.side_effect = ClientError({'Error': {'Code': '404'}}, 'HeadObject')
        with self.assertRaises(Conflict):
            verify_s3(c, self.media(), False)
        c.put_object.assert_not_called()

    def test_batch_collision_aborts_before_any_insert(self):
        conn = Mock()
        conn.transaction.return_value.__enter__ = Mock()
        conn.transaction.return_value.__exit__ = Mock(return_value=False)
        cur = Mock()
        actual = dict(id='run-a', payload={'old': True}, content_hash='old', kind='affect', name='old')
        cur.description = []
        for name in actual:
            desc = Mock()
            desc.name = name
            cur.description.append(desc)
        cur.fetchall.return_value = [tuple(actual.values())]
        conn.execute.return_value = cur
        item = dict(table='processing_runs', key='run-a', payload={'new': True},
                    content_hash='new', columns=dict(kind='affect', name='new'))
        with self.assertRaises(Conflict):
            insert_batch(conn, [item], 'extensions')
        conn.cursor.assert_not_called()
        self.assertIs(conn.transaction.return_value.__exit__.call_args.args[0], Conflict)


if __name__ == '__main__':
    unittest.main()
