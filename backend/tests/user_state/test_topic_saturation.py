
import unittest

from backend.user_state.topic_saturation import (
    calculate_topic_saturation,
)


class TestTopicSaturation(unittest.TestCase):

    def test_empty_exposures_return_zero(self):
        result = calculate_topic_saturation([])
        self.assertEqual(result, 0.0)

    def test_zero_watch_duration_returns_zero(self):
        exposures = [
            {
                "similarity": 0.9,
                "watch_duration_ms": 0,
                "age_minutes": 0,
            }
        ]

        result = calculate_topic_saturation(exposures)
        self.assertEqual(result, 0.0)

    def test_short_watch_contributes_proportionally(self):
        short_exposure = [
            {
                "similarity": 1.0,
                "watch_duration_ms": 5000,
                "age_minutes": 0,
            }
        ]

        long_exposure = [
            {
                "similarity": 1.0,
                "watch_duration_ms": 30000,
                "age_minutes": 0,
            }
        ]

        short_result = calculate_topic_saturation(short_exposure)
        long_result = calculate_topic_saturation(long_exposure)

        self.assertGreater(short_result, 0.0)
        self.assertLess(short_result, long_result)

    def test_watch_duration_is_capped_at_thirty_seconds(self):
        normal_exposure = [
            {
                "similarity": 1.0,
                "watch_duration_ms": 30000,
                "age_minutes": 0,
            }
        ]

        longer_exposure = [
            {
                "similarity": 1.0,
                "watch_duration_ms": 60000,
                "age_minutes": 0,
            }
        ]

        self.assertEqual(
            calculate_topic_saturation(normal_exposure),
            calculate_topic_saturation(longer_exposure),
        )

    def test_higher_similarity_increases_saturation(self):
        low_similarity = [
            {
                "similarity": 0.3,
                "watch_duration_ms": 30000,
                "age_minutes": 0,
            }
        ]

        high_similarity = [
            {
                "similarity": 0.9,
                "watch_duration_ms": 30000,
                "age_minutes": 0,
            }
        ]

        self.assertGreater(
            calculate_topic_saturation(high_similarity),
            calculate_topic_saturation(low_similarity),
        )

    def test_negative_similarity_does_not_increase_saturation(self):
        exposures = [
            {
                "similarity": -0.5,
                "watch_duration_ms": 30000,
                "age_minutes": 0,
            }
        ]

        self.assertEqual(calculate_topic_saturation(exposures), 0.0)

    def test_older_exposure_has_less_influence(self):
        recent_exposure = [
            {
                "similarity": 0.9,
                "watch_duration_ms": 30000,
                "age_minutes": 0,
            }
        ]

        older_exposure = [
            {
                "similarity": 0.9,
                "watch_duration_ms": 30000,
                "age_minutes": 30,
            }
        ]

        self.assertGreater(
            calculate_topic_saturation(recent_exposure),
            calculate_topic_saturation(older_exposure),
        )

    def test_multiple_exposures_increase_saturation(self):
        one_exposure = [
            {
                "similarity": 0.8,
                "watch_duration_ms": 30000,
                "age_minutes": 0,
            }
        ]

        multiple_exposures = [
            {
                "similarity": 0.8,
                "watch_duration_ms": 30000,
                "age_minutes": 0,
            },
            {
                "similarity": 0.8,
                "watch_duration_ms": 30000,
                "age_minutes": 0,
            },
        ]

        self.assertGreater(
            calculate_topic_saturation(multiple_exposures),
            calculate_topic_saturation(one_exposure),
        )

    def test_saturation_stays_between_zero_and_one(self):
        exposures = []

        for i in range(100):
            exposures.append({
                "similarity": 1.0,
                "watch_duration_ms": 30000,
                "age_minutes": 0,
            })

        result = calculate_topic_saturation(exposures)

        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 1.0)

    def test_negative_watch_duration_is_rejected(self):
        exposures = [
            {
                "similarity": 0.8,
                "watch_duration_ms": -1000,
                "age_minutes": 0,
            }
        ]

        with self.assertRaises(ValueError):
            calculate_topic_saturation(exposures)

    def test_negative_age_is_rejected(self):
        exposures = [
            {
                "similarity": 0.8,
                "watch_duration_ms": 10000,
                "age_minutes": -5,
            }
        ]

        with self.assertRaises(ValueError):
            calculate_topic_saturation(exposures)

    def test_invalid_similarity_is_rejected(self):
        exposures = [
            {
                "similarity": 1.5,
                "watch_duration_ms": 10000,
                "age_minutes": 0,
            }
        ]

        with self.assertRaises(ValueError):
            calculate_topic_saturation(exposures)

    def test_missing_field_is_rejected(self):
        exposures = [
            {
                "similarity": 0.8,
                "watch_duration_ms": 10000,
            }
        ]

        with self.assertRaises(ValueError):
            calculate_topic_saturation(exposures)


if __name__ == "__main__":
    unittest.main()
