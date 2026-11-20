
import unittest

from backend.user_state.affective_saturation import (
    calculate_affective_saturation,
)


def make_affect(
    valence=0.5,
    arousal=0.5,
    joy=1.0,
    sadness=0.0,
    anger=0.0,
    fear_anxiety=0.0,
    surprise=0.0,
    disgust=0.0,
    calm_contentment=0.0,
    neutral=0.0,
):
    return {
        "valence": valence,
        "arousal": arousal,
        "emotions": {
            "joy": joy,
            "sadness": sadness,
            "anger": anger,
            "fear_anxiety": fear_anxiety,
            "surprise": surprise,
            "disgust": disgust,
            "calm_contentment": calm_contentment,
            "neutral": neutral,
        },
    }


def make_exposure(
    affect=None,
    watch_duration_ms=30000,
    age_minutes=0,
):
    if affect is None:
        affect = make_affect()

    return {
        "affect": affect,
        "watch_duration_ms": watch_duration_ms,
        "age_minutes": age_minutes,
    }


class TestAffectiveSaturation(unittest.TestCase):

    def test_empty_exposures_return_zero(self):
        candidate = make_affect()

        result = calculate_affective_saturation(candidate, [])

        self.assertEqual(result, 0.0)

    def test_identical_affect_produces_expected_saturation(self):
        candidate = make_affect()
        exposures = [make_exposure()]

        result = calculate_affective_saturation(candidate, exposures)

        self.assertEqual(result, 0.393469)

    def test_short_watch_contributes_proportionally(self):
        candidate = make_affect()

        short_exposure = [
            make_exposure(watch_duration_ms=5000)
        ]

        long_exposure = [
            make_exposure(watch_duration_ms=30000)
        ]

        short_result = calculate_affective_saturation(
            candidate,
            short_exposure
        )

        long_result = calculate_affective_saturation(
            candidate,
            long_exposure
        )

        self.assertGreater(short_result, 0.0)
        self.assertLess(short_result, long_result)

    def test_watch_duration_is_capped_at_thirty_seconds(self):
        candidate = make_affect()

        normal_exposure = [
            make_exposure(watch_duration_ms=30000)
        ]

        longer_exposure = [
            make_exposure(watch_duration_ms=60000)
        ]

        self.assertEqual(
            calculate_affective_saturation(candidate, normal_exposure),
            calculate_affective_saturation(candidate, longer_exposure),
        )

    def test_completely_different_affect_produces_zero(self):
        candidate = make_affect(valence=1.0, arousal=1.0, joy=1.0,)
        previous = make_affect(valence=-1.0, arousal=0.0, joy=0.0, sadness=1.0,)

        exposures = [make_exposure(affect=previous)]
        result = calculate_affective_saturation(candidate, exposures)
        self.assertEqual(result, 0.0)

    def test_different_emotions_with_same_valence_and_arousal(self):
        candidate = make_affect(valence=0.5, arousal=0.5, joy=1.0,)
        previous = make_affect(valence=0.5, arousal=0.5, joy=0.0, sadness=1.0,)

        exposures = [make_exposure(affect=previous)]

        result = calculate_affective_saturation(candidate, exposures)

        # Emotion similarity is zero, but valence and arousal match. Combined similarity is therefore 0.50.
        self.assertEqual(result, 0.221199)

    def test_older_exposure_has_less_influence(self):
        candidate = make_affect()

        recent_exposure = [make_exposure(age_minutes=0)]
        older_exposure = [make_exposure(age_minutes=30)]
        recent_result = calculate_affective_saturation(candidate, recent_exposure)
        older_result = calculate_affective_saturation(candidate, older_exposure)

        self.assertGreater(recent_result, older_result)
        self.assertEqual(older_result, 0.221199)

    def test_multiple_exposures_increase_saturation(self):
        candidate = make_affect()

        one_exposure = [make_exposure()]
        multiple_exposures = [make_exposure(), make_exposure(),]
        one_result = calculate_affective_saturation(candidate, one_exposure)
        multiple_result = calculate_affective_saturation(candidate, multiple_exposures)

        self.assertGreater(multiple_result, one_result)

    def test_permissible_rounding_drift_is_normalized(self):
        candidate = make_affect(joy=0.995)
        previous = make_affect(joy=1.0)
        exposures = [make_exposure(affect=previous)]

        result = calculate_affective_saturation(candidate, exposures)

        self.assertGreater(result, 0.0)
        self.assertLessEqual(result, 0.393469)

    def test_emotion_distribution_outside_allowed_total_is_rejected(self):
        candidate = make_affect(joy=0.98)

        with self.assertRaises(ValueError):
            calculate_affective_saturation(candidate, [])

    def test_missing_emotion_is_rejected(self):
        candidate = make_affect()
        del candidate["emotions"]["joy"]

        with self.assertRaises(ValueError):
            calculate_affective_saturation(candidate, [])

    def test_extra_emotion_key_is_rejected(self):
        candidate = make_affect()
        candidate["emotions"]["boredom"] = 0.0

        with self.assertRaises(ValueError):
            calculate_affective_saturation(candidate, [])

    def test_emotion_score_outside_range_is_rejected(self):
        candidate = make_affect(joy=1.2, sadness=0.0,)

        with self.assertRaises(ValueError):
            calculate_affective_saturation(candidate, [])

    def test_invalid_valence_is_rejected(self):
        candidate = make_affect(valence=1.5)

        with self.assertRaises(ValueError):
            calculate_affective_saturation(candidate, [])

    def test_invalid_arousal_is_rejected(self):
        candidate = make_affect(arousal=-0.1)

        with self.assertRaises(ValueError):
            calculate_affective_saturation(candidate, [])

    def test_negative_watch_duration_is_rejected(self):
        candidate = make_affect()
        exposures = [make_exposure(watch_duration_ms=-1000)]

        with self.assertRaises(ValueError):
            calculate_affective_saturation(candidate, exposures)

    def test_negative_age_is_rejected(self):
        candidate = make_affect()
        exposures = [make_exposure(age_minutes=-5)]

        with self.assertRaises(ValueError):
            calculate_affective_saturation(candidate, exposures)

    def test_boolean_watch_duration_is_rejected(self):
        candidate = make_affect()
        exposures = [ make_exposure(watch_duration_ms=True)]

        with self.assertRaises(TypeError):
            calculate_affective_saturation(candidate, exposures)

    def test_infinite_age_is_rejected(self):
        candidate = make_affect()
        exposures = [make_exposure(age_minutes=float("inf"))]

        with self.assertRaises(ValueError):
            calculate_affective_saturation(candidate, exposures)

    def test_missing_exposure_field_is_rejected(self):
        candidate = make_affect()

        exposures = [
            {
                "affect": make_affect(),
                "watch_duration_ms": 10000,
            }
        ]

        with self.assertRaises(ValueError):
            calculate_affective_saturation(candidate, exposures)

    def test_zero_watch_duration_returns_zero(self):
        candidate = make_affect()
        exposures = [make_exposure(watch_duration_ms=0)]

        result = calculate_affective_saturation(candidate, exposures)

        self.assertEqual(result, 0.0)

    def test_saturation_stays_between_zero_and_one(self):
        candidate = make_affect()
        exposures = []

        for i in range(100):
            exposures.append(make_exposure())

        result = calculate_affective_saturation(candidate, exposures)

        self.assertGreaterEqual(result, 0.0)
        self.assertLessEqual(result, 1.0)


if __name__ == "__main__":
    unittest.main()
