
"""Tests for read-only interaction history retrieval."""

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from backend.interactions.repository import (
    InteractionRepository,
    SessionNotFoundError,
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


class HistoryFakeConnection:
    """In-memory simulation of read-only history SQL queries."""

    def __init__(self, sessions, interactions):
        self.sessions = sessions
        self.interactions = interactions
        self.row_factory = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        if "SUM(i.watch_duration_ms)" in query:
            session_id, user_id = params

            if (
                session_id not in self.sessions
                or self.sessions[session_id] != user_id
            ):
                return FakeResult()

            total_watch_ms = 0

            for event in self.interactions:
                if (
                    event["session_id"] == session_id
                    and event["event_type"] == "watch"
                    and event["watch_duration_ms"] is not None
                ):
                    total_watch_ms += event["watch_duration_ms"]

            return FakeResult([
                {
                    "session_id": session_id,
                    "session_watch_ms": total_watch_ms,
                }
            ])

        if "FROM public.interactions AS i" in query:
            user_id, since, limit = params
            matching_events = []

            for event in self.interactions:
                session_user = self.sessions.get(event["session_id"])

                if (
                    session_user == user_id
                    and event["occurred_at"] >= since
                ):
                    matching_events.append(event.copy())

            # The SQL subquery selects the newest events first.
            matching_events.sort(
                key=lambda event: (
                    event["occurred_at"],
                    event["received_at"],
                    str(event["interaction_id"]),
                ),
                reverse=True,
            )

            matching_events = matching_events[:limit]

            # The outer SQL query returns the selected events
            # in chronological order.
            matching_events.sort(
                key=lambda event: (
                    event["occurred_at"],
                    event["received_at"],
                    str(event["interaction_id"]),
                )
            )

            return FakeResult(matching_events)

        raise AssertionError(f"Unexpected SQL operation: {query}")


class InteractionHistoryRepositoryTests(unittest.TestCase):

    def setUp(self):
        self.user_id = uuid4()
        self.other_user_id = uuid4()

        self.session_id = uuid4()
        self.other_session_id = uuid4()

        self.now = datetime.now(timezone.utc)

        self.sessions = {
            self.session_id: self.user_id,
            self.other_session_id: self.other_user_id,
        }

        self.interactions = []

        self.connection = HistoryFakeConnection(
            self.sessions,
            self.interactions,
        )

        self.repository = InteractionRepository(
            connection_factory=lambda: self.connection
        )

    def add_event(
        self,
        session_id,
        event_type,
        watch_duration_ms,
        occurred_at=None,
        received_at=None,
        video_id="FV000001",
    ):
        if occurred_at is None:
            occurred_at = self.now

        if received_at is None:
            received_at = self.now

        event = {
            "interaction_id": uuid4(),
            "session_id": session_id,
            "video_id": video_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "received_at": received_at,
            "watch_duration_ms": watch_duration_ms,
            "metadata": {},
        }

        self.interactions.append(event)
        return event

    # Session watch duration tests

    def test_session_watch_duration_sums_watch_events(self):
        self.add_event(
            self.session_id,
            "watch",
            5000,
        )
        self.add_event(
            self.session_id,
            "watch",
            3000,
        )

        result = self.repository.get_session_watch_ms(
            self.user_id,
            self.session_id,
        )

        self.assertEqual(result, 8000)

    def test_session_watch_duration_ignores_skip_duration(self):
        self.add_event(
            self.session_id,
            "watch",
            5000,
        )
        self.add_event(
            self.session_id,
            "skip",
            4500,
        )

        result = self.repository.get_session_watch_ms(
            self.user_id,
            self.session_id,
        )

        self.assertEqual(result, 5000)

    def test_session_watch_duration_ignores_marker_events(self):
        self.add_event(
            self.session_id,
            "completion",
            None,
        )
        self.add_event(
            self.session_id,
            "rewatch",
            None,
        )

        result = self.repository.get_session_watch_ms(
            self.user_id,
            self.session_id,
        )

        self.assertEqual(result, 0)

    def test_empty_session_returns_zero(self):
        result = self.repository.get_session_watch_ms(
            self.user_id,
            self.session_id,
        )

        self.assertEqual(result, 0)

    def test_session_watch_duration_rejects_another_users_session(self):
        with self.assertRaises(SessionNotFoundError):
            self.repository.get_session_watch_ms(
                self.user_id,
                self.other_session_id,
            )

    def test_session_watch_duration_rejects_missing_session(self):
        with self.assertRaises(SessionNotFoundError):
            self.repository.get_session_watch_ms(
                self.user_id,
                uuid4(),
            )

    # Recent event retrieval tests

    def test_recent_events_returns_only_the_users_events(self):
        own_event = self.add_event(
            self.session_id,
            "watch",
            2000,
        )

        self.add_event(
            self.other_session_id,
            "watch",
            3000,
        )

        result = self.repository.get_recent_events(
            self.user_id,
            self.now - timedelta(minutes=5),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["interaction_id"],
            own_event["interaction_id"],
        )

    def test_recent_events_filters_by_since(self):
        old_event = self.add_event(
            self.session_id,
            "watch",
            1000,
            occurred_at=self.now - timedelta(minutes=10),
        )

        recent_event = self.add_event(
            self.session_id,
            "watch",
            2000,
            occurred_at=self.now - timedelta(minutes=2),
        )

        result = self.repository.get_recent_events(
            self.user_id,
            self.now - timedelta(minutes=5),
        )

        returned_ids = [
            event["interaction_id"] for event in result
        ]

        self.assertNotIn(old_event["interaction_id"], returned_ids)
        self.assertIn(recent_event["interaction_id"], returned_ids)

    def test_recent_events_are_ordered_deterministically(self):
        later_event = self.add_event(
            self.session_id,
            "watch",
            1000,
            occurred_at=self.now + timedelta(seconds=2),
        )

        earlier_event = self.add_event(
            self.session_id,
            "watch",
            1000,
            occurred_at=self.now - timedelta(seconds=2),
        )

        result = self.repository.get_recent_events(
            self.user_id,
            self.now - timedelta(minutes=5),
        )

        returned_ids = [
            event["interaction_id"] for event in result
        ]

        self.assertEqual(
            returned_ids,
            [
                earlier_event["interaction_id"],
                later_event["interaction_id"],
            ],
        )

    def test_recent_events_respects_limit(self):
        for index in range(5):
            self.add_event(
                self.session_id,
                "watch",
                1000,
                occurred_at=self.now + timedelta(seconds=index),
            )

        result = self.repository.get_recent_events(
            self.user_id,
            self.now - timedelta(minutes=5),
            limit=3,
        )

        self.assertEqual(len(result), 3)

    def test_recent_events_limit_keeps_newest_events(self):
        events = []

        for index in range(5):
            events.append(
                self.add_event(
                    self.session_id,
                    "watch",
                    1000,
                    occurred_at=self.now + timedelta(seconds=index),
                )
            )

        result = self.repository.get_recent_events(
            self.user_id,
            self.now - timedelta(minutes=5),
            limit=2,
        )

        returned_ids = [
            event["interaction_id"] for event in result
        ]

        self.assertEqual(
            returned_ids,
            [
                events[3]["interaction_id"],
                events[4]["interaction_id"],
            ],
        )

    def test_recent_events_returns_required_fields(self):
        event = self.add_event(
            self.session_id,
            "watch",
            2000,
        )

        result = self.repository.get_recent_events(
            self.user_id,
            self.now - timedelta(minutes=5),
        )

        required_fields = {
            "interaction_id",
            "session_id",
            "video_id",
            "event_type",
            "occurred_at",
            "received_at",
            "watch_duration_ms",
            "metadata",
        }

        self.assertEqual(
            set(result[0].keys()),
            required_fields,
        )
        self.assertEqual(
            result[0]["interaction_id"],
            event["interaction_id"],
        )

    # Input validation tests

    def test_recent_events_rejects_non_datetime_since(self):
        with self.assertRaises(ValueError):
            self.repository.get_recent_events(
                self.user_id,
                "2026-11-20",
            )

    def test_recent_events_rejects_naive_datetime(self):
        naive_datetime = datetime(2026, 11, 20, 10, 0, 0)

        with self.assertRaises(ValueError):
            self.repository.get_recent_events(
                self.user_id,
                naive_datetime,
            )

    def test_recent_events_rejects_zero_limit(self):
        with self.assertRaises(ValueError):
            self.repository.get_recent_events(
                self.user_id,
                self.now,
                limit=0,
            )

    def test_recent_events_rejects_negative_limit(self):
        with self.assertRaises(ValueError):
            self.repository.get_recent_events(
                self.user_id,
                self.now,
                limit=-1,
            )

    def test_recent_events_rejects_boolean_limit(self):
        with self.assertRaises(ValueError):
            self.repository.get_recent_events(
                self.user_id,
                self.now,
                limit=True,
            )


if __name__ == "__main__":
    unittest.main()
