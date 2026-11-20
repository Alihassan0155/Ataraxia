
import unittest
from datetime import datetime, timedelta, timezone

from backend.user_state.interaction_history import (
    aggregate_interaction_history,
)


class InteractionHistoryTests(unittest.TestCase):

    def setUp(self):
        self.now = datetime(
            2026, 11, 20, 15, 0, 0,
            tzinfo=timezone.utc,
        )

    def make_event(
        self,
        event_type,
        minutes_ago=0,
        video_id="video_1",
        duration=None,
        classification=None,
        interaction_id="event_1",
    ):
        event = {
            "interaction_id": interaction_id,
            "video_id": video_id,
            "event_type": event_type,
            "occurred_at": self.now - timedelta(
                minutes=minutes_ago
            ),
            "received_at": self.now - timedelta(
                minutes=minutes_ago
            ),
            "watch_duration_ms": duration,
            "metadata": {},
        }

        if classification is not None:
            event["metadata"]["skip_classification"] = classification

        return event

    def aggregate(self, events, session_watch_ms=0, **kwargs):
        return aggregate_interaction_history(
            events=events,
            session_watch_ms=session_watch_ms,
            now=self.now,
            **kwargs,
        )

    def test_empty_history_returns_zero_values(self):
        result = self.aggregate([])

        self.assertEqual(result["session_watch_ms"], 0)
        self.assertEqual(result["recent_watch_ms"], 0)
        self.assertEqual(result["recent_departures"], [])
        self.assertEqual(result["watch_exposures"], [])

    def test_session_watch_duration_is_preserved(self):
        result = self.aggregate(
            [],
            session_watch_ms=45000,
        )

        self.assertEqual(result["session_watch_ms"], 45000)

    def test_recent_watch_duration_sums_watch_events(self):
        events = [
            self.make_event(
                "watch",
                minutes_ago=1,
                duration=30000,
            ),
            self.make_event(
                "watch",
                minutes_ago=3,
                duration=45000,
                interaction_id="event_2",
            ),
        ]

        result = self.aggregate(events)

        self.assertEqual(result["recent_watch_ms"], 75000)

    def test_old_watch_events_are_excluded_from_recent_duration(self):
        events = [
            self.make_event(
                "watch",
                minutes_ago=6,
                duration=50000,
            ),
        ]

        result = self.aggregate(events)

        self.assertEqual(result["recent_watch_ms"], 0)

    def test_event_exactly_at_recent_window_boundary_is_included(self):
        events = [
            self.make_event(
                "watch",
                minutes_ago=5,
                duration=20000,
            ),
        ]

        result = self.aggregate(events)

        self.assertEqual(result["recent_watch_ms"], 20000)

    def test_skip_duration_is_not_added_to_watch_duration(self):
        events = [
            self.make_event(
                "skip",
                minutes_ago=1,
                duration=50000,
                classification="early",
            ),
        ]

        result = self.aggregate(events)

        self.assertEqual(result["recent_watch_ms"], 0)

    def test_marker_events_do_not_contribute_watch_duration(self):
        events = [
            self.make_event("impression", duration=10000),
            self.make_event("completion", duration=20000),
            self.make_event("rewatch", duration=30000),
            self.make_event("like", duration=40000),
            self.make_event("unlike", duration=50000),
        ]

        result = self.aggregate(events)

        self.assertEqual(result["recent_watch_ms"], 0)
        self.assertEqual(result["watch_exposures"], [])

    def test_recent_departures_include_skip_classifications(self):
        events = [
            self.make_event(
                "skip",
                minutes_ago=3,
                classification="early",
            ),
            self.make_event(
                "skip",
                minutes_ago=2,
                classification="late",
                interaction_id="event_2",
            ),
            self.make_event(
                "skip",
                minutes_ago=1,
                classification="mid",
                interaction_id="event_3",
            ),
        ]

        result = self.aggregate(events)

        self.assertEqual(
            result["recent_departures"],
            ["early", "late", "mid"],
        )

    def test_missing_skip_classification_becomes_unknown(self):
        events = [
            self.make_event(
                "skip",
                classification=None,
            ),
        ]

        result = self.aggregate(events)

        self.assertEqual(
            result["recent_departures"],
            ["unknown"],
        )

    def test_only_latest_ten_skip_classifications_are_retained(self):
        events = []

        for index in range(12):
            events.append(
                self.make_event(
                    "skip",
                    minutes_ago=12 - index,
                    classification="early" if index % 2 == 0 else "late",
                    interaction_id="event_" + str(index),
                )
            )

        result = self.aggregate(events)

        self.assertEqual(len(result["recent_departures"]), 10)
        self.assertEqual(
            result["recent_departures"],
            [
                "early", "late", "early", "late", "early",
                "late", "early", "late", "early", "late",
            ],
        )

    def test_skip_events_are_ordered_oldest_to_newest(self):
        events = [
            self.make_event(
                "skip",
                minutes_ago=1,
                classification="late",
                interaction_id="newer",
            ),
            self.make_event(
                "skip",
                minutes_ago=3,
                classification="early",
                interaction_id="older",
            ),
        ]

        result = self.aggregate(events)

        self.assertEqual(
            result["recent_departures"],
            ["early", "late"],
        )

    def test_watch_exposures_preserve_individual_events(self):
        events = [
            self.make_event(
                "watch",
                minutes_ago=10,
                video_id="video_1",
                duration=20000,
            ),
            self.make_event(
                "watch",
                minutes_ago=2,
                video_id="video_1",
                duration=15000,
                interaction_id="event_2",
            ),
        ]

        result = self.aggregate(events)
        exposures = result["watch_exposures"]

        self.assertEqual(len(exposures), 2)
        self.assertEqual(
            exposures[0]["watch_duration_ms"],
            20000,
        )
        self.assertEqual(
            exposures[1]["watch_duration_ms"],
            15000,
        )

    def test_watch_exposures_preserve_video_ids(self):
        events = [
            self.make_event(
                "watch",
                video_id="video_1",
                duration=10000,
            ),
            self.make_event(
                "watch",
                video_id="video_2",
                duration=20000,
                interaction_id="event_2",
            ),
        ]

        result = self.aggregate(events)

        self.assertEqual(
            [
                exposure["video_id"]
                for exposure in result["watch_exposures"]
            ],
            ["video_1", "video_2"],
        )

    def test_watch_exposure_contains_age_and_timestamp(self):
        events = [
            self.make_event(
                "watch",
                minutes_ago=4,
                duration=15000,
            ),
        ]

        result = self.aggregate(events)
        exposure = result["watch_exposures"][0]

        self.assertEqual(exposure["age_minutes"], 4.0)
        self.assertEqual(
            exposure["occurred_at"],
            self.now - timedelta(minutes=4),
        )

    def test_zero_duration_watch_is_not_an_exposure(self):
        events = [
            self.make_event(
                "watch",
                duration=0,
            ),
        ]

        result = self.aggregate(events)

        self.assertEqual(result["recent_watch_ms"], 0)
        self.assertEqual(result["watch_exposures"], [])

    def test_future_watch_events_are_excluded(self):
        future_event = self.make_event(
            "watch",
            duration=30000,
        )
        future_event["occurred_at"] = self.now + timedelta(minutes=1)

        result = self.aggregate([future_event])

        self.assertEqual(result["recent_watch_ms"], 0)
        self.assertEqual(result["watch_exposures"], [])

    def test_future_skip_events_are_excluded(self):
        future_event = self.make_event(
            "skip",
            classification="early",
        )
        future_event["occurred_at"] = self.now + timedelta(minutes=1)

        result = self.aggregate([future_event])

        self.assertEqual(result["recent_departures"], [])

    def test_invalid_skip_classification_is_rejected(self):
        events = [
            self.make_event(
                "skip",
                classification="invalid",
            ),
        ]

        with self.assertRaises(ValueError):
            self.aggregate(events)

    def test_negative_session_watch_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            self.aggregate([], session_watch_ms=-1)

    def test_boolean_session_watch_duration_is_rejected(self):
        with self.assertRaises(TypeError):
            self.aggregate([], session_watch_ms=True)

    def test_naive_current_datetime_is_rejected(self):
        naive_now = datetime(2026, 11, 20, 15, 0, 0)

        with self.assertRaises(ValueError):
            aggregate_interaction_history(
                events=[],
                session_watch_ms=0,
                now=naive_now,
            )

    def test_non_list_events_are_rejected(self):
        with self.assertRaises(TypeError):
            self.aggregate("invalid")

    def test_naive_event_timestamp_is_rejected(self):
        event = self.make_event("watch", duration=10000)
        event["occurred_at"] = datetime(2026, 11, 20, 14, 0, 0)

        with self.assertRaises(ValueError):
            self.aggregate([event])

    def test_non_positive_recent_window_is_rejected(self):
        with self.assertRaises(ValueError):
            self.aggregate(
                [],
                recent_window=timedelta(seconds=0),
            )

    def test_non_positive_departure_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            self.aggregate([], departure_limit=0)


if __name__ == "__main__":
    unittest.main()
