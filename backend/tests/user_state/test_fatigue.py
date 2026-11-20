
import unittest
from datetime import timedelta

from backend.user_state.fatigue import (
    calculate_current_fatigue,
    calculate_fatigue,
    calculate_carryover,
)


class TestCurrentFatigue(unittest.TestCase):

    def test_no_activity_has_zero_fatigue(self):
        result = calculate_current_fatigue(
            session_watch_ms=0,
            recent_watch_ms=0,
            recent_departures=[],
        )
        self.assertEqual(result, 0.0)

    def test_maximum_signals_reach_one(self):
        result = calculate_current_fatigue(
            session_watch_ms=30 * 60 * 1000,
            recent_watch_ms=4 * 60 * 1000,
            recent_departures=["early"] * 10,
        )
        self.assertAlmostEqual(result, 1.0)

    def test_insufficient_departures_do_not_add_skip_fatigue(self):
        result = calculate_current_fatigue(
            session_watch_ms=0,
            recent_watch_ms=0,
            recent_departures=["early", "early"],
        )
        self.assertEqual(result, 0.0)

    def test_late_skips_do_not_count_as_early_skips(self):
        result = calculate_current_fatigue(
            session_watch_ms=0,
            recent_watch_ms=0,
            recent_departures=["late"] * 10,
        )
        self.assertEqual(result, 0.0)
    def test_unknown_departures_are_excluded(self):
        result = calculate_current_fatigue(
            session_watch_ms=0,
            recent_watch_ms=0,
            recent_departures=[
                "early",
                "early",
                "late",
                "unknown",
            ],
        )
        self.assertAlmostEqual(result, 0.166667, places=5)

    def test_invalid_departure_classification_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_current_fatigue(
                session_watch_ms=0,
                recent_watch_ms=0,
                recent_departures=[
                    "early",
                    "invalid",
                    "late",
                ],
            )

    def test_result_is_bounded(self):
        result = calculate_current_fatigue(
            session_watch_ms=60 * 60 * 1000,
            recent_watch_ms=10 * 60 * 1000,
            recent_departures=["early"] * 10,
        )
        self.assertLessEqual(result, 1.0)
        self.assertGreaterEqual(result, 0.0)


class TestFatigueCarryover(unittest.TestCase):

    def test_carryover_at_session_end(self):
        result = calculate_carryover(
            previous_fatigue=1.0,
            elapsed_since_previous_session=timedelta(0),
        )
        self.assertAlmostEqual(result, 1.0)

    def test_carryover_halves_after_thirty_minutes(self):
        result = calculate_carryover(
            previous_fatigue=1.0,
            elapsed_since_previous_session=timedelta(minutes=30),
        )
        self.assertAlmostEqual(result, 0.5)

    def test_carryover_decays_to_near_zero(self):
        result = calculate_carryover(
            previous_fatigue=1.0,
            elapsed_since_previous_session=timedelta(hours=10),
        )
        self.assertLess(result, 0.001)

    def test_negative_elapsed_time_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_carryover(
                previous_fatigue=0.5,
                elapsed_since_previous_session=timedelta(minutes=-1),
            )


class TestCombinedFatigue(unittest.TestCase):

    def test_no_carryover_uses_current_fatigue(self):
        result = calculate_fatigue(
            current_fatigue=0.6,
            carryover_fatigue=0.0,
        )
        self.assertAlmostEqual(result, 0.48)

    def test_combined_result_is_bounded(self):
        result = calculate_fatigue(
            current_fatigue=1.0,
            carryover_fatigue=1.0,
        )
        self.assertAlmostEqual(result, 1.0)


if __name__ == "__main__":
    unittest.main()
