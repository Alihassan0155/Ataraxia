"""Mocked repository tests for interaction idempotency and feedback atomicity."""

import copy
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
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
    """In-memory simulation of the SQL used by InteractionRepository."""

    def __init__(self, sessions, videos, interactions, feedback):
        self.sessions = sessions
        self.videos = videos
        self.interactions = interactions
        self.feedback = feedback
        self.row_factory = None
        self.fail_feedback_write = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    @contextmanager
    def transaction(self):
        original_interactions = copy.deepcopy(self.interactions)
        original_feedback = copy.deepcopy(self.feedback)

        try:
            yield
        except Exception:
            self.interactions.clear()
            self.interactions.update(original_interactions)
            self.feedback.clear()
            self.feedback.update(original_feedback)
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
                "received_at": datetime.now(timezone.utc),
                "watch_duration_ms": watch_duration_ms,
                "metadata": metadata.obj,
            }

            return FakeResult([{"interaction_id": event_id}])

        if "pg_advisory_xact_lock" in query:
            return FakeResult()

        if "FROM public.interactions AS i" in query:
            user_id, video_id = params
            matching_events = []

            for event_id, event in self.interactions.items():
                session_user = self.sessions.get(event["session_id"])

                if (
                    session_user == user_id
                    and event["video_id"] == video_id
                    and event["event_type"] in {"like", "unlike"}
                ):
                    matching_events.append({
                        "event_type": event["event_type"],
                        "occurred_at": event["occurred_at"],
                        "received_at": event["received_at"],
                        "interaction_id": event_id,
                    })

            if not matching_events:
                return FakeResult()

            latest = max(
                matching_events,
                key=lambda item: (
                    item["occurred_at"],
                    item["received_at"],
                    str(item["interaction_id"]),
                ),
            )

            return FakeResult([latest])

        if "INSERT INTO public.user_video_feedback" in query:
            if self.fail_feedback_write:
                raise RuntimeError("Simulated feedback write failure.")

            user_id, video_id, is_liked = params
            key = (user_id, video_id)
            now = datetime.now(timezone.utc)

            if key in self.feedback:
                existing = self.feedback[key]

                if existing["is_liked"] != is_liked:
                    existing["is_liked"] = is_liked
                    existing["updated_at"] = now

                row = existing
            else:
                row = {
                    "user_id": user_id,
                    "video_id": video_id,
                    "is_liked": is_liked,
                    "created_at": now,
                    "updated_at": now,
                }
                self.feedback[key] = row

            return FakeResult([row.copy()])

        if (
            "SELECT" in query
            and "FROM public.interactions" in query
        ):
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
        self.feedback = {}

        self.connection = FakeConnection(
            self.sessions,
            self.videos,
            self.interactions,
            self.feedback,
        )

        self.repository = InteractionRepository(
            connection_factory=lambda: self.connection
        )

    def make_event(
        self,
        event_id=None,
        video_id="FV000001",
        event_type="skip",
        occurred_at=None,
    ):
        if event_type in {"like", "unlike"}:
            watch_duration_ms = None
            metadata = {}
        else:
            watch_duration_ms = 1200
            metadata = {
                "video_duration_ms": 10000,
                "watch_percentage": 12.0,
                "skip_classification": "early",
            }

        return InteractionEventRequest(
            event_id=event_id or uuid4(),
            session_id=self.session_id,
            video_id=video_id,
            event_type=event_type,
            occurred_at=occurred_at or datetime.now(timezone.utc),
            watch_duration_ms=watch_duration_ms,
            metadata=metadata,
        )

    def get_feedback(self, video_id="FV000001"):
        return self.feedback.get((self.user_id, video_id))

    def test_new_event_is_inserted(self):
        event = self.make_event()

        accepted_ids = self.repository.insert_batch(
            self.user_id,
            [event],
        )

        self.assertEqual(accepted_ids, [event.event_id])
        self.assertIn(event.event_id, self.interactions)
        self.assertEqual(len(self.interactions), 1)
        self.assertEqual(len(self.feedback), 0)

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

        new_event = self.make_event(video_id="FV000002")

        conflicting_event = self.make_event(
            event_id=existing_event_id,
            video_id="FV000002",
        )

        with self.assertRaises(EventConflictError):
            self.repository.insert_batch(
                self.user_id,
                [new_event, conflicting_event],
            )

        self.assertNotIn(new_event.event_id, self.interactions)
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

    def test_new_like_updates_history_and_current_state(self):
        event = self.make_event(event_type="like")

        accepted = self.repository.insert_batch(self.user_id, [event])

        self.assertEqual(accepted, [event.event_id])
        self.assertIn(event.event_id, self.interactions)
        self.assertTrue(self.get_feedback()["is_liked"])

    def test_new_unlike_updates_history_and_current_state(self):
        event = self.make_event(event_type="unlike")

        self.repository.insert_batch(self.user_id, [event])

        self.assertIn(event.event_id, self.interactions)
        self.assertFalse(self.get_feedback()["is_liked"])

    def test_like_then_unlike_leaves_current_state_unliked(self):
        now = datetime.now(timezone.utc)

        like_event = self.make_event(
            event_type="like",
            occurred_at=now,
        )
        unlike_event = self.make_event(
            event_type="unlike",
            occurred_at=now + timedelta(seconds=1),
        )

        self.repository.insert_batch(
            self.user_id,
            [like_event, unlike_event],
        )

        self.assertEqual(len(self.interactions), 2)
        self.assertFalse(self.get_feedback()["is_liked"])

    def test_older_like_uploaded_after_newer_unlike_does_not_overwrite(self):
        now = datetime.now(timezone.utc)

        newer_unlike = self.make_event(
            event_type="unlike",
            occurred_at=now + timedelta(minutes=1),
        )
        older_like = self.make_event(
            event_type="like",
            occurred_at=now,
        )

        self.repository.insert_batch(self.user_id, [newer_unlike])
        self.repository.insert_batch(self.user_id, [older_like])

        self.assertEqual(len(self.interactions), 2)
        self.assertFalse(self.get_feedback()["is_liked"])

    def test_duplicate_feedback_retry_does_not_reapply_state(self):
        event = self.make_event(event_type="like")

        self.repository.insert_batch(self.user_id, [event])

        feedback_before = copy.deepcopy(self.get_feedback())

        self.repository.insert_batch(self.user_id, [event])

        self.assertEqual(self.get_feedback(), feedback_before)
        self.assertEqual(len(self.interactions), 1)

    def test_playback_event_does_not_create_feedback_state(self):
        event = self.make_event(event_type="completion")

        self.repository.insert_batch(self.user_id, [event])

        self.assertEqual(len(self.interactions), 1)
        self.assertIsNone(self.get_feedback())

    def test_latest_event_in_batch_determines_current_state(self):
        now = datetime.now(timezone.utc)

        events = [
            self.make_event(
                event_type="like",
                occurred_at=now,
            ),
            self.make_event(
                event_type="unlike",
                occurred_at=now + timedelta(seconds=2),
            ),
            self.make_event(
                event_type="like",
                occurred_at=now + timedelta(seconds=1),
            ),
        ]

        self.repository.insert_batch(self.user_id, events)

        self.assertEqual(len(self.interactions), 3)
        self.assertFalse(self.get_feedback()["is_liked"])

    def test_feedback_write_failure_rolls_back_interaction_insert(self):
        event = self.make_event(event_type="like")
        self.connection.fail_feedback_write = True

        with self.assertRaises(RuntimeError):
            self.repository.insert_batch(self.user_id, [event])

        self.assertEqual(len(self.interactions), 0)
        self.assertEqual(len(self.feedback), 0)

    def test_feedback_state_is_isolated_between_users(self):
        other_user_id = uuid4()
        other_session_id = uuid4()

        self.sessions[other_session_id] = other_user_id

        other_event = InteractionEventRequest(
            event_id=uuid4(),
            session_id=other_session_id,
            video_id="FV000001",
            event_type="like",
            occurred_at=datetime.now(timezone.utc),
            watch_duration_ms=None,
            metadata={},
        )

        self.repository.insert_batch(other_user_id, [other_event])

        self.assertTrue(
            self.feedback[(other_user_id, "FV000001")]["is_liked"]
        )
        self.assertIsNone(self.get_feedback())

    def test_unlike_after_like_updates_existing_feedback_row(self):
        now = datetime.now(timezone.utc)

        like_event = self.make_event(
            event_type="like",
            occurred_at=now,
        )
        unlike_event = self.make_event(
            event_type="unlike",
            occurred_at=now + timedelta(seconds=1),
        )

        self.repository.insert_batch(self.user_id, [like_event])
        created_at = self.get_feedback()["created_at"]

        self.repository.insert_batch(self.user_id, [unlike_event])

        self.assertFalse(self.get_feedback()["is_liked"])
        self.assertEqual(self.get_feedback()["created_at"], created_at)
        self.assertEqual(len(self.feedback), 1)


if __name__ == "__main__":
    unittest.main()