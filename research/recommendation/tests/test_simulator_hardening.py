import sys
import unittest

import numpy as np

from research.recommendation.simulator import SimulatorConfig, SyntheticSimulator
from research.recommendation.simulator.profiles import unit
from research.recommendation.tests.test_simulator import catalogue


class SimulatorHardeningTests(unittest.TestCase):
    def test_scaled_normalization(self):
        for scale in (1, 1e200, sys.float_info.max):
            np.testing.assert_allclose(unit(np.array([scale, -scale])), [2**-.5, -2**-.5])
        for small in ([0., 0.], [1e-200, 0.]):
            with self.assertRaises(ValueError):
                unit(small)
            np.testing.assert_array_equal(unit(small, [0., 2.]), [0., 1.])
        for invalid in ([np.nan, 0], [np.inf, 0], [0, -np.inf]):
            with self.assertRaises(ValueError):
                unit(invalid, [0., 1.])
        with self.assertRaises(ValueError):
            unit([0., 0.], [0., 0.])

    def test_episode_initialization_and_transition_at_extreme_finite_noise(self):
        for noise in (.005, 1e200, sys.float_info.max):
            game = SyntheticSimulator(catalogue(), SimulatorConfig(
                initial_noise=noise, transition_noise=noise, start_intercept=1000))
            with np.errstate(over='raise', invalid='raise'):
                game.reset(42, 73)
                for video_id in ('A', 'B'):
                    self.assertTrue(np.isfinite(game._interest).all())
                    self.assertAlmostEqual(float(np.linalg.norm(game._interest)), 1)
                    self.assertFalse(game.step(video_id).immediate_pass)
                self.assertAlmostEqual(float(np.linalg.norm(game._interest)), 1)

    def test_invalid_config_and_seeds(self):
        for kwargs in (dict(initial_noise=np.nan), dict(transition_noise=np.inf),
                       dict(initial_noise=-1), dict(concentration=0),
                       dict(quality_constant=np.nan), dict(lapse=True),
                       dict(watch_weight='1'), dict(affinity_weight=sys.float_info.max)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SimulatorConfig(**kwargs)
        game = SyntheticSimulator(catalogue())
        for seeds in [(-1, 1, 2), (1, True, 2), (1, 2, .5)]:
            with self.assertRaises(ValueError):
                game.reset(*seeds[:2], quality_seed=seeds[2])

    def test_quality_and_response_seed_axes(self):
        game = SyntheticSimulator(catalogue())
        game.reset(42, 73, quality_seed=9)
        quality = game._quality.copy()
        draws = [game._channel(i, 1).random() for i in (1, 2, 3)]
        self.assertEqual(len(set(draws)), 3)
        game.reset(43, 73, quality_seed=9)
        self.assertEqual(quality, game._quality)
        for i, draw in enumerate(draws, 1):
            self.assertNotEqual(draw, game._channel(i, 1).random())
        game.reset(42, 74, quality_seed=9)
        self.assertEqual(quality, game._quality)
        self.assertNotEqual(draws[0], game._channel(1, 1).random())
        game.reset(42, 73, quality_seed=10)
        self.assertNotEqual(quality, game._quality)
        self.assertEqual(draws, [game._channel(i, 1).random() for i in (1, 2, 3)])
        game.reset(42, 73)
        default_quality = game._quality.copy()
        game.reset(42, 73, quality_seed=73)
        self.assertEqual(default_quality, game._quality)

    def test_matched_draws_despite_different_served_ids_and_channel_consumption(self):
        game = SyntheticSimulator(catalogue())

        def next_draws(first):
            game.reset(81, 55)
            game._channel(2, 1).random(80)
            game.step(first)
            return [game._channel(i, 2).random() for i in (1, 2, 3)]

        self.assertEqual(next_draws('A'), next_draws('B'))
        game.reset(81, 55)
        trajectory = (game.step('A'), game.step('B'))
        game.reset(81, 55)
        self.assertEqual(trajectory, (game.step('A'), game.step('B')))
