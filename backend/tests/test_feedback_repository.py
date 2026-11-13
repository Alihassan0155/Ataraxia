"""Mocked repository tests for reading persistent video feedback."""

import unittest
from uuid import uuid4

from backend.feedback.repository import (
    FeedbackRepository,
    UnknownVideoError,
)


class FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []

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

    def execute(self, query, params):
        if "FROM public.videos" in query:
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
                        "is_liked": self.feedback[key],
                    })

            return FakeResult(rows)

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

        # Seed current-state rows directly. Writes are now performed
        # by the interaction repository, not this feedback repository.
        self.feedback = {
            (self.user_id, "FV000001"): False,
            (self.user_id, "FV000003"): True,
            (self.other_user_id, "FV000002"): True,
        }

        self.connection = FakeConnection(
            self.videos,
            self.feedback,
        )

        self.repository = FeedbackRepository(
            connection_factory=lambda: self.connection
        )

    def test_batch_states_distinguish_unliked_from_no_feedback(self):
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
        states = self.repository.get_states(
            self.user_id,
            ["FV000003", "FV000001", "FV000002"],
        )

        self.assertEqual(
            [state["video_id"] for state in states],
            ["FV000003", "FV000001", "FV000002"],
        )

    def test_feedback_is_isolated_between_users(self):
        states = self.repository.get_states(
            self.other_user_id,
            ["FV000001", "FV000002"],
        )

        self.assertEqual(
            states,
            [
                {
                    "video_id": "FV000001",
                    "is_liked": False,
                    "has_feedback": False,
                },
                {
                    "video_id": "FV000002",
                    "is_liked": True,
                    "has_feedback": True,
                },
            ],
        )

    def test_unknown_video_is_rejected_for_batch_read(self):
        with self.assertRaises(UnknownVideoError):
            self.repository.get_states(
                self.user_id,
                ["FV000001", "UNKNOWN_VIDEO"],
            )

    def test_empty_video_list_returns_empty_list(self):
        states = self.repository.get_states(
            self.user_id,
            [],
        )

        self.assertEqual(states, [])

    def test_user_id_is_converted_to_uuid(self):
        states = self.repository.get_states(
            str(self.user_id),
            ["FV000001"],
        )

        self.assertTrue(states[0]["has_feedback"])


if __name__ == "__main__":
    unittest.main()