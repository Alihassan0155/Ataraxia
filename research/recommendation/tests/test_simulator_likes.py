from dataclasses import asdict, replace
import math
import sys
import unittest
from unittest.mock import Mock, patch

import numpy as np

from research.recommendation.simulator import LikeConfig, LikeStepResult, SimulatorConfig, StepResult, SyntheticSimulator
from research.recommendation.simulator.response import like_probability
from research.recommendation.tests.test_simulator import catalogue


class SimulatorLikeTests(unittest.TestCase):
    def test_probability_terms_and_extreme_logits(self):
        config = LikeConfig()
        base = like_probability(0, .5, 0, config)
        self.assertAlmostEqual(base, 1 / (1 + math.exp(3.5)))
        self.assertGreater(like_probability(.5, .5, 0, config), base)
        self.assertGreater(like_probability(0, .8, 0, config), base)
        self.assertGreater(like_probability(0, .5, .5, config), base)
        self.assertEqual(like_probability(1.01, .5, 0, config),
                         like_probability(1, .5, 0, config))
        limit = sys.float_info.max / 64
        for intercept, expected in ((limit, 1.), (-limit, 0.)):
            self.assertEqual(like_probability(1, 1, 0, LikeConfig(intercept=intercept)), expected)

    def test_invalid_settings(self):
        for params in (dict(intercept=math.nan), dict(intercept=True),
                       dict(affinity_coefficient=-1), dict(watch_ratio_coefficient=math.inf),
                       dict(propensity_scale=-1), dict(propensity_scale=sys.float_info.max)):
            with self.subTest(params=params), self.assertRaises(ValueError):
                LikeConfig(**params)
        with self.assertRaises(ValueError):
            SimulatorConfig(like=True)

    def test_pass_never_likes_or_draws(self):
        game = SyntheticSimulator(catalogue(), SimulatorConfig(
            start_intercept=-1000, like=LikeConfig(intercept=1000)))
        game.reset(42, 73)
        with patch.object(game, '_channel', wraps=game._channel) as channel:
            result = game.step('A')
        self.assertTrue(result.immediate_pass)
        self.assertIs(result.liked, False)
        self.assertEqual(result.watch_ratio, 0)
        self.assertNotIn(4, [call.args[0] for call in channel.call_args_list])

    def test_fixed_ratio_can_yield_either_outcome_using_pretransition_affinity(self):
        source = catalogue()
        game = SyntheticSimulator(source, SimulatorConfig(start_intercept=1000, like=LikeConfig()))
        for units in (10, 20):
            for uniform, liked in ((0., True), (.99, False)):
                game.reset(42, 73)
                affinity = float(game._interest @ source.embeddings[source.id_to_row['A']])
                channel = game._channel

                def controlled(number, step):
                    return Mock(**{'random.return_value': uniform}) if number == 4 else channel(number, step)

                with (patch.object(game, '_channel', side_effect=controlled),
                      patch('research.recommendation.simulator.episode.watched_units', return_value=units),
                      patch('research.recommendation.simulator.episode.like_probability',
                            wraps=like_probability) as probability):
                    result = game.step('A')
                probability.assert_called_once_with(affinity, units / 20, 0., LikeConfig())
                self.assertEqual(result.watch_ratio, units / 20)
                self.assertIs(result.liked, liked)

    def test_exact_trajectory_equivalence_and_public_schema(self):
        source = catalogue()
        config = SimulatorConfig()
        baseline = SyntheticSimulator(source, config)
        enabled = SyntheticSimulator(source, replace(config, like=LikeConfig(propensity_scale=.75)))
        seen_pass = seen_engagement = False
        for profile in (42, 43, 44):
            for seed in (73, 74, 75):
                replay = []
                for run in range(2):
                    self.assertEqual(baseline.reset(profile, seed), enabled.reset(profile, seed))
                    np.testing.assert_array_equal(baseline._interest, enabled._interest)
                    self.assertEqual(baseline._quality, enabled._quality)
                    for index, video in enumerate(('A', 'B')):
                        old, new = baseline.step(video), enabled.step(video)
                        self.assertIs(type(old), StepResult)
                        self.assertIs(type(new), LikeStepResult)
                        public = asdict(new)
                        self.assertIs(type(public.pop('liked')), bool)
                        self.assertEqual(asdict(old), public)
                        np.testing.assert_array_equal(baseline._interest, enabled._interest)
                        np.testing.assert_array_equal(baseline._category_exposure, enabled._category_exposure)
                        np.testing.assert_array_equal(baseline._affect_exposure, enabled._affect_exposure)
                        seen_pass |= old.immediate_pass
                        seen_engagement |= not old.immediate_pass
                        if run == 0:
                            replay.append(new)
                        else:
                            self.assertEqual(replay[index], new)
        self.assertTrue(seen_pass and seen_engagement)

    def test_seed_namespace_and_policy_pairing(self):
        game = SyntheticSimulator(catalogue(), SimulatorConfig(like=LikeConfig(propensity_scale=.75)))
        profile = 42
        seed = 73
        game.reset(profile, seed)
        key = tuple(map(int, np.random.SeedSequence(profile).generate_state(4)))
        keys = [(), (0,), (5,), *((i, 1, *key) for i in (1, 2, 3, 4))]
        states = {tuple(np.random.SeedSequence(seed, spawn_key=k).generate_state(4)) for k in keys}
        self.assertEqual(len(keys), len(states))
        self.assertEqual(game._channel(4, 1).random(), np.random.default_rng(
            np.random.SeedSequence(seed, spawn_key=(4, 1, *key))).random())
        propensity = game._like_propensity
        self.assertEqual(propensity, .75 * np.random.default_rng(
            np.random.SeedSequence(profile, spawn_key=(5,))).standard_normal())
        game.reset(profile, seed + 1)
        self.assertEqual(game._like_propensity, propensity)
        game.reset(profile + 1, seed)
        self.assertNotEqual(game._like_propensity, propensity)

        def step_two_draws(first):
            game.reset(profile, seed)
            game._channel(4, 1).random(100)
            game.step(first)
            return tuple(game._channel(i, 2).random() for i in (1, 2, 3, 4))

        self.assertEqual(step_two_draws('A'), step_two_draws('B'))
