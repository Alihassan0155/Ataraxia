"""Mocked repository tests for persistent video feedback."""

import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from backend.feedback.repository import (
    FeedbackRepository,
    UnknownVideoError,
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
    def __init__(self, videos, feedback):
        self.videos = videos
        self.feedback = feedback
        self.row_factory = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    @contextmanager
    def transaction(self):
        original = self.feedback.copy()

        try:
            yield
        except Exception:
            self.feedback.clear()
            self.feedback.update(original)
            raise

    def execute(self, query, params):
        if "WHERE video_id = ANY" in query:
            requested_ids = params[0]
            rows = []

            for video_id in requested_ids:
                if video_id in self.videos:
                    rows.append({"video_id": video_id})

            return FakeResult(rows)

        if "FROM public.user_video_feedback" in query:
            user_id, requested_ids = params
            rows = []

            for video_id in requested_ids:
                key = (user_id, video_id)

                if key in self.feedback:
                    rows.append({
                        "video_id": video_id,
                        "is_liked": self.feedback[key]["is_liked"],
                    })

            return FakeResult(rows)

        if "WHERE video_id = %s" in query:
            video_id = params[0]

            if video_id in self.videos:
                return FakeResult([{"video_id": video_id}])

            return FakeResult()

        if "INSERT INTO public.user_video_feedback" in query:
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
                    "video_id": video_id,
                    "is_liked": is_liked,
                    "created_at": now,
                    "updated_at": now,
                }
                self.feedback[key] = row

            return FakeResult([row.copy()])

        raise AssertionError(f"Unexpected SQL operation: {query}")


class FeedbackRepositoryTests(unittest.TestCase):

    def setUp(self):
        self.user_id = uuid4()
        self.other_user_id = uuid4()

        self.videos = {
            "FV000001",
            "FV000002",
            "FV000003",
        }

        self.feedback = {}

        self.connection = FakeConnection(
            self.videos,
            self.feedback,
        )

        self.repository = FeedbackRepository(
            connection_factory=lambda: self.connection
        )

    def test_new_like_is_inserted(self):
        result = self.repository.set_state(
            self.user_id,
            "FV000001",
            True,
        )

        self.assertEqual(result["video_id"], "FV000001")
        self.assertTrue(result["is_liked"])
        self.assertTrue(result["has_feedback"])
        self.assertEqual(len(self.feedback), 1)

    def test_unlike_is_persisted_as_explicit_feedback(self):
        result = self.repository.set_state(
            self.user_id,
            "FV000001",
            False,
        )

        self.assertFalse(result["is_liked"])
        self.assertTrue(result["has_feedback"])
        self.assertIn((self.user_id, "FV000001"), self.feedback)

    def test_repeated_like_is_idempotent(self):
        first = self.repository.set_state(
            self.user_id,
            "FV000001",
            True,
        )

        created_at = self.feedback[
            (self.user_id, "FV000001")
        ]["created_at"]

        updated_at = self.feedback[
            (self.user_id, "FV000001")
        ]["updated_at"]

        second = self.repository.set_state(
            self.user_id,
            "FV000001",
            True,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(self.feedback), 1)
        self.assertEqual(
            self.feedback[(self.user_id, "FV000001")]["created_at"],
            created_at,
        )
        self.assertEqual(
            self.feedback[(self.user_id, "FV000001")]["updated_at"],
            updated_at,
        )

    def test_unlike_after_like_updates_existing_state(self):
        self.repository.set_state(
            self.user_id,
            "FV000001",
            True,
        )

        result = self.repository.set_state(
            self.user_id,
            "FV000001",
            False,
        )

        self.assertFalse(result["is_liked"])
        self.assertTrue(result["has_feedback"])
        self.assertEqual(len(self.feedback), 1)

    def test_batch_states_distinguish_unliked_from_no_feedback(self):
        self.repository.set_state(
            self.user_id,
            "FV000001",
            False,
        )

        states = self.repository.get_states(
            self.user_id,
            ["FV000001", "FV000002"],
        )

        self.assertEqual(
            states,
            [
                {
                    "video_id": "FV000001",
                    "is_liked": False,
                    "has_feedback": True,
                },
                {
                    "video_id": "FV000002",
                    "is_liked": False,
                    "has_feedback": False,
                },
            ],
        )

    def test_batch_states_preserve_requested_order(self):
        self.repository.set_state(
            self.user_id,
            "FV000001",
            True,
        )
        self.repository.set_state(
            self.user_id,
            "FV000003",
            True,
        )

        states = self.repository.get_states(
            self.user_id,
            ["FV000003", "FV000001", "FV000002"],
        )

        self.assertEqual(
            [state["video_id"] for state in states],
            ["FV000003", "FV000001", "FV000002"],
        )

    def test_feedback_is_isolated_between_users(self):
        self.repository.set_state(
            self.user_id,
            "FV000001",
            True,
        )

        states = self.repository.get_states(
            self.other_user_id,
            ["FV000001"],
        )

        self.assertEqual(
            states,
            [{
                "video_id": "FV000001",
                "is_liked": False,
                "has_feedback": False,
            }],
        )

    def test_unknown_video_is_rejected_for_write(self):
        with self.assertRaises(UnknownVideoError):
            self.repository.set_state(
                self.user_id,
                "UNKNOWN_VIDEO",
                True,
            )

        self.assertEqual(len(self.feedback), 0)

    def test_unknown_video_is_rejected_for_batch_read(self):
        with self.assertRaises(UnknownVideoError):
            self.repository.get_states(
                self.user_id,
                ["FV000001", "UNKNOWN_VIDEO"],
            )


if __name__ == "__main__":
    unittest.main()
