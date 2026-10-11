import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from common_annotation import EmotionScores, validate_emotion_points
from prompts import ANNOTATION_PROMPT, ANNOTATION_PROMPT_POINTS10


class EmotionPointsTests(unittest.TestCase):
    def setUp(self):
        self.raw = {"emotions": {name: 0 for name in EmotionScores.model_fields}}
        self.raw["emotions"].update(joy=6, surprise=2, neutral=2)

    def test_exact_allocation_converts_units_without_mutation(self):
        original = copy.deepcopy(self.raw)
        converted, points = validate_emotion_points(self.raw)
        self.assertEqual(self.raw, original)
        self.assertEqual(sum(points.values()), 10)
        self.assertEqual(converted["emotions"]["joy"], 0.6)

    def test_decimal_allocation(self):
        self.raw["emotions"].update(joy=3.33, surprise=3.33, neutral=3.34)
        converted, _ = validate_emotion_points(self.raw)
        self.assertAlmostEqual(sum(converted["emotions"].values()), 1)

    def test_invalid_totals_and_bounds_are_rejected(self):
        for value in (5.99, 6.01, -1, 11, True, "6", float("nan"), float("inf"), 6.001):
            with self.subTest(value=value):
                raw = copy.deepcopy(self.raw)
                raw["emotions"]["joy"] = value
                with self.assertRaises(ValueError):
                    validate_emotion_points(raw)

    def test_probability_scale_not_accepted_as_points(self):
        raw = copy.deepcopy(self.raw)
        raw["emotions"] = {key: value / 10 for key, value in raw["emotions"].items()}
        with self.assertRaises(ValueError):
            validate_emotion_points(raw)

    def test_missing_and_extra_keys(self):
        for operation in ("missing", "extra"):
            raw = copy.deepcopy(self.raw)
            if operation == "missing":
                del raw["emotions"]["anger"]
            else:
                raw["emotions"]["other"] = 0
            with self.assertRaises(ValueError):
                validate_emotion_points(raw)

    def test_prompt_version_and_scale_are_separate(self):
        self.assertIn("version v1.0", ANNOTATION_PROMPT)
        self.assertIn("version v1.1-points10", ANNOTATION_PROMPT_POINTS10)
        self.assertNotIn("sum approximately to 1.00", ANNOTATION_PROMPT_POINTS10)
        self.assertIn("sum EXACTLY to 10.00", ANNOTATION_PROMPT_POINTS10)


if __name__ == "__main__":
    unittest.main()
