
"""Mocked repository tests for interaction idempotency and atomicity."""

import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from backend.interactions.models import InteractionEventRequest
from backend.interactions.repository import (
    EventConflictError,
    InteractionRepository,
)


class FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchone(self):
        if not self.rows:
            return None
        return self.rows[0]

    def fetchall(self):
        return self.rows


class FakeConnection:
    """Minimal in-memory simulation of repository database operations."""

    def __init__(self, sessions, videos, interactions):
        self.sessions = sessions
        self.videos = videos
        self.interactions = interactions
        self.row_factory = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    @contextmanager
    def transaction(self):
        original_interactions = self.interactions.copy()

        try:
            yield
        except Exception:
            self.interactions.clear()
            self.interactions.update(original_interactions)
            raise

    def execute(self, query, params):
        if "SELECT session_id, user_id" in query:
            requested_ids = params[0]

            rows = []

            for session_id in requested_ids:
                if session_id in self.sessions:
                    rows.append({
                        "session_id": session_id,
                        "user_id": self.sessions[session_id],
                    })

            return FakeResult(rows)

        if "SELECT video_id" in query:
            requested_ids = params[0]

            rows = []

            for video_id in requested_ids:
                if video_id in self.videos:
                    rows.append({"video_id": video_id})

            return FakeResult(rows)

        if "INSERT INTO public.interactions" in query:
            (
                event_id,
                session_id,
                video_id,
                event_type,
                occurred_at,
                watch_duration_ms,
                metadata,
            ) = params

            if event_id in self.interactions:
                return FakeResult()

            self.interactions[event_id] = {
                "session_id": session_id,
                "video_id": video_id,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "watch_duration_ms": watch_duration_ms,
                "metadata": metadata.obj,
            }

            return FakeResult([{"interaction_id": event_id}])

        if "SELECT" in query and "FROM public.interactions" in query:
            event_id = params[0]

            if event_id not in self.interactions:
                return FakeResult()

            return FakeResult([self.interactions[event_id]])

        raise AssertionError(f"Unexpected SQL operation: {query}")


class InteractionRepositoryTests(unittest.TestCase):

    def setUp(self):
        self.user_id = uuid4()
        self.session_id = uuid4()

        self.sessions = {
            self.session_id: self.user_id,
        }

        self.videos = {
            "FV000001",
            "FV000002",
        }

        self.interactions = {}

        self.connection = FakeConnection(
            self.sessions,
            self.videos,
            self.interactions,
        )

        self.repository = InteractionRepository(
            connection_factory=lambda: self.connection
        )

    def make_event(
        self,
        event_id=None,
        video_id="FV000001",
        event_type="skip",
    ):
        return InteractionEventRequest(
            event_id=event_id or uuid4(),
            session_id=self.session_id,
            video_id=video_id,
            event_type=event_type,
            occurred_at=datetime.now(timezone.utc),
            watch_duration_ms=1200,
            metadata={
                "video_duration_ms": 10000,
                "watch_percentage": 12.0,
                "skip_classification": "early",
            },
        )

    def test_new_event_is_inserted(self):
        event = self.make_event()

        accepted_ids = self.repository.insert_batch(
            self.user_id,
            [event],
        )

        self.assertEqual(accepted_ids, [event.event_id])
        self.assertIn(event.event_id, self.interactions)
        self.assertEqual(len(self.interactions), 1)

    def test_identical_retry_is_idempotent(self):
        event = self.make_event()

        first_result = self.repository.insert_batch(
            self.user_id,
            [event],
        )

        second_result = self.repository.insert_batch(
            self.user_id,
            [event],
        )

        self.assertEqual(first_result, [event.event_id])
        self.assertEqual(second_result, [event.event_id])
        self.assertEqual(len(self.interactions), 1)

    def test_reused_event_id_with_different_data_is_rejected(self):
        event_id = uuid4()

        original_event = self.make_event(
            event_id=event_id,
            video_id="FV000001",
        )

        conflicting_event = self.make_event(
            event_id=event_id,
            video_id="FV000002",
        )

        self.repository.insert_batch(
            self.user_id,
            [original_event],
        )

        with self.assertRaises(EventConflictError):
            self.repository.insert_batch(
                self.user_id,
                [conflicting_event],
            )

        self.assertEqual(len(self.interactions), 1)
        self.assertEqual(
            self.interactions[event_id]["video_id"],
            "FV000001",
        )

    def test_conflict_rolls_back_earlier_batch_insertions(self):
        existing_event_id = uuid4()

        existing_event = self.make_event(
            event_id=existing_event_id,
            video_id="FV000001",
        )

        self.repository.insert_batch(
            self.user_id,
            [existing_event],
        )

        new_event = self.make_event(
            video_id="FV000002",
        )

        conflicting_event = self.make_event(
            event_id=existing_event_id,
            video_id="FV000002",
        )

        with self.assertRaises(EventConflictError):
            self.repository.insert_batch(
                self.user_id,
                [new_event, conflicting_event],
            )

        # The first insertion in the failed batch must also be rolled back.
        self.assertNotIn(new_event.event_id, self.interactions)

        # The original event must remain unchanged.
        self.assertEqual(len(self.interactions), 1)
        self.assertEqual(
            self.interactions[existing_event_id]["video_id"],
            "FV000001",
        )

    def test_unknown_video_rejects_batch_before_insertion(self):
        event = self.make_event(video_id="UNKNOWN_VIDEO")

        with self.assertRaises(Exception):
            self.repository.insert_batch(
                self.user_id,
                [event],
            )

        self.assertEqual(len(self.interactions), 0)


if __name__ == "__main__":
    unittest.main()
