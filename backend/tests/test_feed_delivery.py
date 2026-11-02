"""Local HTTP contracts: no production identity, database or S3 calls."""
import unittest
from unittest.mock import Mock
from uuid import uuid4
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from backend.onboarding.api import get_service
from backend.onboarding.delivery import FeedSnapshots, create_delivery_router
from backend.onboarding.service import PreferenceService
from backend.tests.test_onboarding import video, BUCKET, CATEGORY


class FeedDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.uid, self.other = str(uuid4()), str(uuid4())
        self.now = 0
        self.snapshots = FeedSnapshots(ttl=60, capacity=2, clock=lambda: self.now)
        self.repo, self.signer, self.lookup = Mock(), Mock(), Mock()
        self.repo.candidate_pool.return_value = ([CATEGORY], [{**video(n, CATEGORY['id']), 'media_sha256': 'a'*64} for n in range(80)])
        self.signer.generate_presigned_url.return_value = 'https://example.invalid/private'
        self.lookup.return_value = {**video(1), 'media_sha256': 'a' * 64}
        def identity(authorization: str | None = Header(None)):
            if authorization == 'Bearer first': return {'id': self.uid}
            if authorization == 'Bearer second': return {'id': self.other}
            raise HTTPException(401, 'Unauthorized')
        app = FastAPI()
        app.include_router(create_delivery_router(identity, self.signer, BUCKET, self.snapshots, self.lookup))
        app.dependency_overrides[get_service] = lambda: PreferenceService(self.repo, BUCKET)
        self.client = TestClient(app)
        self.headers = {'Authorization': 'Bearer first'}

    def test_first_five_then_same_fifty_without_resampling_and_only_first_signed(self):
        response = self.client.get('/recommendations/feed', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('server-timing', response.headers)
        self.assertEqual(response.headers['cache-control'], 'no-store')

        page = response.json(); videos = page['videos']
        self.assertEqual(len(videos), 5)
        self.assertEqual(page['total'], 50)
        while page['next_cursor']:
            page = self.client.get('/recommendations/feed', params={'cursor': page['next_cursor'], 'page_size': 10}, headers=self.headers).json()
            videos.extend(page['videos'])
        self.assertEqual(len(videos), 50)
        self.assertEqual(len({v['video_id'] for v in videos}), 50)
        self.repo.candidate_pool.assert_called_once()
        self.signer.generate_presigned_url.assert_called_once()
        self.assertIn('initial_playback', response.json())
        self.assertNotIn('_media', response.json())
        self.lookup.assert_not_called()

    def test_page_retry_is_idempotent_and_user_bound(self):
        cursor = self.client.get('/recommendations/feed', headers=self.headers).json()['next_cursor']
        path = '/recommendations/feed'
        one = self.client.get(path, params={'cursor': cursor}, headers=self.headers)
        two = self.client.get(path, params={'cursor': cursor}, headers=self.headers)
        self.assertEqual(one.json(), two.json())
        self.assertEqual(self.client.get(path, params={'cursor': cursor}, headers={'Authorization': 'Bearer second'}).status_code, 410)
        self.now = 61
        self.assertEqual(self.client.get(path, params={'cursor': cursor}, headers=self.headers).status_code, 410)

    def test_nearby_playback_reuses_user_bound_verified_snapshot(self):
        data = self.client.get('/recommendations/feed', headers=self.headers).json()
        vid = data['videos'][1]['video_id']
        response = self.client.get(f'/catalogue/videos/{vid}/playback', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.lookup.assert_not_called()
        self.assertIsNone(self.snapshots.media(self.other, vid))
        self.now = 301
        self.assertIsNone(self.snapshots.media(self.uid, vid))

    def test_cursor_validation_and_empty_preferences(self):
        for cursor in ['bad', 'bad:-1', 'bad:9999']:
            self.assertIn(self.client.get('/recommendations/feed', params={'cursor': cursor}, headers=self.headers).status_code, (400, 410))
        self.assertEqual(self.client.get('/recommendations/feed?page_size=50', headers=self.headers).status_code, 422)
        self.repo.candidate_pool.return_value = ([], [])
        data = self.client.get('/recommendations/feed', headers=self.headers).json()
        self.assertEqual(data['videos'], [])
        self.assertIsNone(data['next_cursor'])

    def test_playback_signs_exact_verified_reference_and_allows_range(self):
        response = self.client.get('/catalogue/videos/FV000001/playback', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['expires_in'], 300)

        self.signer.generate_presigned_url.assert_called_once_with('get_object',
            Params={'Bucket': BUCKET, 'Key': 'videos/finevideo/FV000001.mp4'},
            ExpiresIn=300, HttpMethod='GET')
        # Range is deliberately not signed: native players may request any byte range.
        self.assertNotIn('Range', self.signer.generate_presigned_url.call_args.kwargs['Params'])

    def test_playback_rejects_wrong_identity_bucket_status_hash(self):
        for change in [None, {'availability': 'local'}, {'media_uri': 's3://other/videos/finevideo/FV000001.mp4'},
                       {'media_uri': f's3://{BUCKET}/videos/finevideo/FV000002.mp4'}, {'media_sha256': 'z'*64}]:
            self.lookup.return_value = None if change is None else {**video(1), 'media_sha256': 'a'*64, **change}
            self.assertEqual(self.client.get('/catalogue/videos/FV000001/playback', headers=self.headers).status_code, 404)
        self.signer.generate_presigned_url.assert_not_called()

    def test_auth_and_failure_sanitization(self):
        for path in ['/recommendations/feed', '/catalogue/videos/FV000001/playback']:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.lookup.side_effect = RuntimeError('secret')
        response = self.client.get('/catalogue/videos/FV000001/playback', headers=self.headers)
        self.assertEqual(response.status_code, 503); self.assertNotIn('secret', response.text)
        self.repo.candidate_pool.side_effect = RuntimeError('secret')
        response = self.client.get('/recommendations/feed', headers=self.headers)
        self.assertEqual(response.status_code, 503); self.assertNotIn('secret', response.text)

    def test_snapshot_capacity_and_preserved_sampler_order(self):
        data = {'videos': [{'video_id': str(n)} for n in range(50)], 'strategy': 'test'}
        first = self.snapshots.start(self.uid, data, 5)
        self.snapshots.start(self.uid, data, 5)
        self.snapshots.start(self.uid, data, 5)
        with self.assertRaises(HTTPException): self.snapshots.page(self.uid, first['next_cursor'], 5)
        first = self.snapshots.start(self.uid, data, 5)
        second = self.snapshots.page(self.uid, first['next_cursor'], 10)
        self.assertEqual([v['video_id'] for v in second['videos']], [str(n) for n in range(5, 15)])

    def test_first_page_stays_small_and_one_background_page_finishes_sample(self):
        page = self.client.get('/recommendations/feed?page_size=45', headers=self.headers).json()
        self.assertEqual(len(page['videos']), 10)
        next_page = self.client.get('/recommendations/feed', params={'cursor':page['next_cursor'], 'page_size':45}, headers=self.headers).json()
        self.assertEqual(len(next_page['videos']), 40)
        self.assertIsNone(next_page['next_cursor'])
