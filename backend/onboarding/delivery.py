"""Bounded, user-bound feed snapshots and just-in-time private media signing."""
from collections import OrderedDict
from secrets import token_urlsafe
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from .api import get_service
from .repository import PreferenceRepository
from .sampling import valid_media


class FeedSnapshots:
    """One unchanged balanced sample per traversal. Restart/eviction returns 410."""
    def __init__(self, ttl=600, capacity=256, clock=monotonic):
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self.entries, self.lock = OrderedDict(), Lock()

    def start(self, user_id, result, page_size):
        with self.lock:
            now = self.clock()
            for key in list(self.entries):
                if self.entries[key][0] <= now:
                    del self.entries[key]
            key = token_urlsafe(24)
            self.entries[key] = (now + self.ttl, str(user_id), result)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
            return self._page(key, result, 0, page_size)

    def page(self, user_id, cursor, page_size):
        try:
            key, offset = cursor.split(':')
            offset = int(offset)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Invalid feed cursor.')
        with self.lock:
            entry = self.entries.get(key)
            if not entry or entry[0] <= self.clock() or entry[1] != str(user_id):
                raise HTTPException(410, 'Feed expired. Refresh your feed.')
            if offset < 0 or offset > len(entry[2]['videos']):
                raise HTTPException(400, 'Invalid feed cursor.')
            return self._page(key, entry[2], offset, page_size)

    def media(self, user_id, video_id):
        with self.lock:
            now = self.clock()
            for expiry, owner, result in reversed(self.entries.values()):
                # Cache verified references for no longer than one signed-URL TTL.
                if owner == str(user_id) and now < min(expiry, expiry - self.ttl + 300):
                    row = result.get('_media', {}).get(video_id)
                    if row:
                        return row
        return None

    @staticmethod
    def _page(key, result, offset, size):
        videos = result['videos'][offset:offset + size]
        end = offset + len(videos)
        return {'videos': videos, 'count': len(videos), 'total': len(result['videos']),
                'next_cursor': f'{key}:{end}' if end < len(result['videos']) else None,
                'strategy': result['strategy']}


def create_delivery_router(current_user, s3, bucket, snapshots=None, media_lookup=None):
    router = APIRouter(tags=['Progressive feed'])
    snapshots = snapshots or FeedSnapshots()
    media_lookup = media_lookup or PreferenceRepository().media

    def identity(user=Depends(current_user)):
        try:
            return UUID(str(user['id']))
        except (ValueError, KeyError, TypeError):
            raise HTTPException(401, 'Invalid authenticated user identity.')

    def sign(video_id, row):
        if (not row or not valid_media(row['media_uri'], row['availability'], bucket)
                or row['media_uri'].rsplit('/', 1)[-1] != video_id + '.mp4'
                or len(row.get('media_sha256') or '') != 64
                or any(c not in '0123456789abcdefABCDEF' for c in row['media_sha256'])):
            raise HTTPException(404, 'Video is unavailable.')
        url = s3.generate_presigned_url('get_object',
            Params={'Bucket': bucket, 'Key': urlsplit(row['media_uri']).path.lstrip('/')},
            ExpiresIn=300, HttpMethod='GET')
        return {'video_id': video_id, 'playback_url': url, 'expires_in': 300}

    @router.get('/recommendations/feed')
    def feed(response: Response, cursor: str | None = Query(default=None, max_length=128),
             page_size: int = Query(default=5, ge=1, le=45),
             user_id=Depends(identity), service=Depends(get_service)):

        response.headers['Cache-Control'] = 'no-store'
        try:
            if cursor:
                result = snapshots.page(user_id, cursor, page_size)
            else:
                # Sample all 50 once; never independently resample pages.
                result = snapshots.start(user_id, service.candidates(user_id, 50, include_media=True), min(page_size, 10))
                if result['videos']:
                    first_id = result['videos'][0]['video_id']
                    try:
                        result['initial_playback'] = sign(first_id, snapshots.media(user_id, first_id))
                    except Exception:
                        # Deliver metadata even if first-URL signing needs retry.
                        result['initial_playback'] = None

            return result
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, 'Recommendations are temporarily unavailable.')

    @router.get('/catalogue/videos/{video_id}/playback')
    def playback(video_id: str, response: Response, user_id=Depends(identity)):
        response.headers['Cache-Control'] = 'no-store'

        try:
            row = snapshots.media(user_id, video_id) or media_lookup(video_id)

            result = sign(video_id, row)

            return result
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, 'Playback is temporarily unavailable.')

    return router
