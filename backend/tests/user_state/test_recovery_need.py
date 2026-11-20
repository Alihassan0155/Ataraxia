import unittest

from backend.user_state.recovery_need import (calculate_recovery_need, calculate_recovery_bonus,)

class TestRecoveryNeed(unittest.TestCase):

    def test_zero_fatigue(self):
        self.assertEqual(calculate_recovery_need(0.0), 0.0,)

    def test_maximum_fatigue(self):
        self.assertEqual(calculate_recovery_need(1.0), 1.0,)

    def test_intermediate_fatigue(self):
        self.assertEqual(calculate_recovery_need(0.68), 0.68,)

    def test_rounding(self):
        self.assertEqual(calculate_recovery_need(0.123456789), 0.123457,)

    def test_negative_fatigue(self):
        with self.assertRaises(ValueError):
            calculate_recovery_need(-0.1)

    def test_fatigue_above_one(self):
        with self.assertRaises(ValueError):
            calculate_recovery_need(1.1)

    def test_non_numeric_fatigue(self):
        with self.assertRaises(TypeError):
            calculate_recovery_need("0.5")

    def test_boolean_fatigue(self):
        with self.assertRaises(TypeError):
            calculate_recovery_need(True)

    def test_non_finite_fatigue(self):
        with self.assertRaises(ValueError):
            calculate_recovery_need(float("nan"))

    def test_zero_recovery_bonus(self):
        self.assertEqual(calculate_recovery_bonus(0.0, 1.0), 0.0,)

    def test_maximum_recovery_bonus(self):
        self.assertEqual(calculate_recovery_bonus(1.0, 1.0), 1.0,)

    def test_intermediate_recovery_bonus(self):
        self.assertEqual(calculate_recovery_bonus(0.8, 0.75), 0.6,)

    def test_zero_suitability(self):
        self.assertEqual(calculate_recovery_bonus(1.0, 0.0), 0.0,)

    def test_invalid_recovery_suitability(self):
        with self.assertRaises(ValueError):
            calculate_recovery_bonus(0.8, 1.2)

    def test_invalid_recovery_need(self):
        with self.assertRaises(ValueError):
            calculate_recovery_bonus(-0.1, 0.5)

    def test_missing_suitability(self):
        with self.assertRaises(TypeError):
            calculate_recovery_bonus(0.8, None)


if __name__ == "__main__":
    unittest.main()
