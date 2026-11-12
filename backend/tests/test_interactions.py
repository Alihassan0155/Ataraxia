
"""Pure interaction model and HTTP contract tests; no external calls."""

import unittest
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import Mock, patch

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from backend.interactions.api import create_router
from backend.interactions.repository import (
    EventConflictError,
    SessionNotFoundError,
    SessionOwnershipError,
    UnknownVideoError,
)


class InteractionApiTests(unittest.TestCase):

    def setUp(self):
        self.user_id = uuid4()
        self.session_id = uuid4()
        self.event_id = uuid4()

        def authenticated(
            authorization: str | None = Header(default=None)
        ):
            if authorization != "Bearer valid":
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token",
                )

            return {"id": str(self.user_id)}

        app = FastAPI()
        app.include_router(create_router(authenticated))

        self.service_patcher = patch(
            "backend.interactions.api.InteractionService"
        )
        self.service_class = self.service_patcher.start()
        self.service = self.service_class.return_value

        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer valid"}

    def tearDown(self):
        self.service_patcher.stop()

    def valid_event(self):
        return {
            "event_id": str(self.event_id),
            "session_id": str(self.session_id),
            "video_id": "FV000001",
            "event_type": "skip",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "watch_duration_ms": 1200,
            "metadata": {
                "video_duration_ms": 10000,
                "watch_percentage": 12.0,
                "skip_classification": "early",
            },
        }

    def test_auth_required_for_all_interaction_routes(self):
        paths = [
            ("post", "/interactions/sessions", {
                "session_id": str(self.session_id)
            }),
            ("post", f"/interactions/sessions/{self.session_id}/close", {}),
            ("post", "/interactions/batch", {
                "events": [self.valid_event()]
            }),
        ]

        for method, path, body in paths:
            response = getattr(self.client, method)(
                path,
                json=body,
            )
            self.assertEqual(response.status_code, 401)

        self.service.register_session.assert_not_called()
        self.service.close_session.assert_not_called()
        self.service.ingest_batch.assert_not_called()

    def test_register_session_uses_authenticated_user(self):
        self.service.register_session.return_value = self.session_id

        response = self.client.post(
            "/interactions/sessions",
            headers=self.headers,
            json={"session_id": str(self.session_id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "session_id": str(self.session_id),
                "registered": True,
            },
        )

        kwargs = self.service.register_session.call_args.kwargs
        self.assertEqual(kwargs["user_id"], self.user_id)
        self.assertEqual(kwargs["session_id"], self.session_id)

    def test_session_registration_rejects_user_id_injection(self):
        response = self.client.post(
            "/interactions/sessions",
            headers=self.headers,
            json={
                "session_id": str(self.session_id),
                "user_id": str(uuid4()),
            },
        )

        self.assertEqual(response.status_code, 422)
        self.service.register_session.assert_not_called()

    def test_close_session_uses_authenticated_user(self):
        ended_at = datetime.now(timezone.utc)

        self.service.close_session.return_value = {
            "session_id": self.session_id,
            "ended_at": ended_at,
        }

        response = self.client.post(
            f"/interactions/sessions/{self.session_id}/close",
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200)

        kwargs = self.service.close_session.call_args.kwargs
        self.assertEqual(kwargs["user_id"], self.user_id)
        self.assertEqual(kwargs["session_id"], self.session_id)

    def test_batch_uses_authenticated_user(self):
        event = self.valid_event()
        self.service.ingest_batch.return_value = [self.event_id]

        response = self.client.post(
            "/interactions/batch",
            headers=self.headers,
            json={"events": [event]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted_count"], 1)
        self.assertEqual(
            response.json()["accepted_event_ids"],
            [str(self.event_id)],
        )

        kwargs = self.service.ingest_batch.call_args.kwargs
        self.assertEqual(kwargs["user_id"], self.user_id)
        self.assertEqual(len(kwargs["events"]), 1)

    def test_batch_rejects_user_id_injection(self):
        event = self.valid_event()
        event["user_id"] = str(uuid4())

        response = self.client.post(
            "/interactions/batch",
            headers=self.headers,
            json={"events": [event]},
        )

        self.assertEqual(response.status_code, 422)
        self.service.ingest_batch.assert_not_called()

    def test_batch_rejects_more_than_50_events(self):
        events = []

        for index in range(51):
            event = self.valid_event()
            event["event_id"] = str(uuid4())
            events.append(event)

        response = self.client.post(
            "/interactions/batch",
            headers=self.headers,
            json={"events": events},
        )

        self.assertEqual(response.status_code, 422)
        self.service.ingest_batch.assert_not_called()

    def test_batch_rejects_duplicate_event_ids(self):
        event = self.valid_event()

        response = self.client.post(
            "/interactions/batch",
            headers=self.headers,
            json={"events": [event, event]},
        )

        self.assertEqual(response.status_code, 422)
        self.service.ingest_batch.assert_not_called()

    def test_batch_rejects_timestamp_without_timezone(self):
        event = self.valid_event()
        event["occurred_at"] = "2026-11-11T12:00:00"

        response = self.client.post(
            "/interactions/batch",
            headers=self.headers,
            json={"events": [event]},
        )

        self.assertEqual(response.status_code, 422)
        self.service.ingest_batch.assert_not_called()

    def test_batch_rejects_invalid_skip_metadata(self):
        event = self.valid_event()
        event["metadata"]["skip_classification"] = "very_early"

        response = self.client.post(
            "/interactions/batch",
            headers=self.headers,
            json={"events": [event]},
        )

        self.assertEqual(response.status_code, 422)
        self.service.ingest_batch.assert_not_called()

    def test_repository_errors_have_expected_status_codes(self):
        cases = [
            (SessionOwnershipError("Wrong owner"), 409),
            (SessionNotFoundError("Missing session"), 404),
            (UnknownVideoError("Unknown video"), 422),
            (EventConflictError("Event conflict"), 409),
        ]

        for error, expected_status in cases:
            self.service.ingest_batch.side_effect = error

            response = self.client.post(
                "/interactions/batch",
                headers=self.headers,
                json={"events": [self.valid_event()]},
            )

            self.assertEqual(response.status_code, expected_status)

    def test_unexpected_storage_error_is_sanitized(self):
        self.service.ingest_batch.side_effect = RuntimeError(
            "secret database connection string"
        )

        response = self.client.post(
            "/interactions/batch",
            headers=self.headers,
            json={"events": [self.valid_event()]},
        )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret database connection string", response.text)

    def test_batch_accepts_skip_with_unknown_duration(self):
        event = self.valid_event()
        event["metadata"]["video_duration_ms"] = None
        event["metadata"]["watch_percentage"] = None
        event["metadata"]["skip_classification"] = "unknown"

        self.service.ingest_batch.return_value = [self.event_id]

        response = self.client.post(
            "/interactions/batch",
            headers=self.headers,
            json={"events": [event]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accepted_count"], 1)
        self.service.ingest_batch.assert_called_once()

if __name__ == "__main__":
    unittest.main()
