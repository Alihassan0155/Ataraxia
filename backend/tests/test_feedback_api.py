"""API tests for authenticated persistent video feedback."""

import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from backend.feedback.api import create_router
from backend.feedback.repository import UnknownVideoError


class FakeFeedbackService:
    def __init__(self):
        self.states = []
        self.updated = []

    def get_states(self, user_id, video_ids):
        self.states.append((user_id, video_ids))

        return [
            {
                "video_id": video_id,
                "is_liked": video_id == "FV000001",
                "has_feedback": video_id == "FV000001",
            }
            for video_id in video_ids
        ]

    def set_state(self, user_id, video_id, is_liked):
        self.updated.append((user_id, video_id, is_liked))

        return {
            "video_id": video_id,
            "is_liked": is_liked,
            "has_feedback": True,
        }


class FeedbackApiTests(unittest.TestCase):

    def setUp(self):
        self.user_id = uuid4()
        self.service = FakeFeedbackService()

        def current_user(authorization: str | None = Header(default=None)):
            if authorization != "Bearer valid-token":
                raise HTTPException(
                    status_code=401,
                    detail="Not authenticated.",
                )

            return {"id": str(self.user_id)}

        self.app = FastAPI()
        self.app.include_router(create_router(current_user))

        self.client = TestClient(self.app)

        self.service_patch = patch(
            "backend.feedback.api.FeedbackService",
            return_value=self.service,
        )
        self.service_patch.start()
        self.addCleanup(self.service_patch.stop)

        self.headers = {
            "Authorization": "Bearer valid-token",
        }

    def test_auth_required_for_batch_state(self):
        response = self.client.post(
            "/feedback/batch-state",
            json={"video_ids": ["FV000001"]},
        )

        self.assertEqual(response.status_code, 401)

    def test_auth_required_for_set_state(self):
        response = self.client.put(
            "/feedback/videos/FV000001",
            json={"is_liked": True},
        )

        self.assertEqual(response.status_code, 401)

    def test_batch_state_uses_authenticated_user(self):
        response = self.client.post(
            "/feedback/batch-state",
            headers=self.headers,
            json={
                "video_ids": ["FV000001", "FV000002"],
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.json(),
            {
                "states": [
                    {
                        "video_id": "FV000001",
                        "is_liked": True,
                        "has_feedback": True,
                    },
                    {
                        "video_id": "FV000002",
                        "is_liked": False,
                        "has_feedback": False,
                    },
                ],
            },
        )

        self.assertEqual(
            self.service.states,
            [(self.user_id, ["FV000001", "FV000002"])],
        )

    def test_set_like_uses_authenticated_user(self):
        response = self.client.put(
            "/feedback/videos/FV000001",
            headers=self.headers,
            json={"is_liked": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "video_id": "FV000001",
                "is_liked": True,
                "has_feedback": True,
            },
        )

        self.assertEqual(
            self.service.updated,
            [(self.user_id, "FV000001", True)],
        )

    def test_set_unlike_uses_authenticated_user(self):
        response = self.client.put(
            "/feedback/videos/FV000001",
            headers=self.headers,
            json={"is_liked": False},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_liked"])
        self.assertTrue(response.json()["has_feedback"])

        self.assertEqual(
            self.service.updated,
            [(self.user_id, "FV000001", False)],
        )

    def test_batch_rejects_user_id_injection(self):
        response = self.client.post(
            "/feedback/batch-state",
            headers=self.headers,
            json={
                "video_ids": ["FV000001"],
                "user_id": str(uuid4()),
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.service.states, [])

    def test_set_state_rejects_user_id_injection(self):
        response = self.client.put(
            "/feedback/videos/FV000001",
            headers=self.headers,
            json={
                "is_liked": True,
                "user_id": str(uuid4()),
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.service.updated, [])

    def test_batch_rejects_empty_video_list(self):
        response = self.client.post(
            "/feedback/batch-state",
            headers=self.headers,
            json={"video_ids": []},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.service.states, [])

    def test_batch_rejects_more_than_50_videos(self):
        response = self.client.post(
            "/feedback/batch-state",
            headers=self.headers,
            json={
                "video_ids": [
                    f"FV{index:06d}"
                    for index in range(51)
                ],
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.service.states, [])

    def test_batch_rejects_duplicate_video_ids(self):
        response = self.client.post(
            "/feedback/batch-state",
            headers=self.headers,
            json={
                "video_ids": ["FV000001", "FV000001"],
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.service.states, [])

    def test_batch_rejects_blank_video_id(self):
        response = self.client.post(
            "/feedback/batch-state",
            headers=self.headers,
            json={"video_ids": [""]},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.service.states, [])

    def test_unknown_video_returns_422(self):
        self.service.set_state = unittest.mock.Mock(
            side_effect=UnknownVideoError(
                "The requested video does not exist."
            )
        )

        response = self.client.put(
            "/feedback/videos/UNKNOWN_VIDEO",
            headers=self.headers,
            json={"is_liked": True},
        )

        self.assertEqual(response.status_code, 422)

    def test_storage_error_returns_sanitized_503(self):
        self.service.set_state = unittest.mock.Mock(
            side_effect=RuntimeError(
                "Internal database connection details."
            )
        )

        response = self.client.put(
            "/feedback/videos/FV000001",
            headers=self.headers,
            json={"is_liked": True},
        )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn(
            "Internal database connection details",
            response.text,
        )

    def test_invalid_authenticated_user_id_returns_401(self):
        def invalid_user():
            return {"id": "not-a-valid-uuid"}

        app = FastAPI()
        app.include_router(create_router(invalid_user))
        client = TestClient(app)

        response = client.post(
            "/feedback/batch-state",
            json={"video_ids": ["FV000001"]},
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
