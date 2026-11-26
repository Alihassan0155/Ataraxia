from dataclasses import fields, replace
import unittest

import numpy as np

from research.recommendation.catalogue import build_catalogue
from research.recommendation.simulator import Observation, SimulatorConfig, StepResult, SyntheticSimulator
from research.recommendation.simulator.profiles import item_qualities
from research.recommendation.simulator.response import completion_probability, start_probability, watched_units
from research.recommendation.tests.test_catalogue import fixture


def catalogue():
    data = fixture()
    for video in data['videos']:
        video['duration_seconds'] = {'A': 12., 'B': 20.}[video['video_id']]
    source = build_catalogue(data)
    return replace(source, records=(source.records[0], replace(source.records[1], category="Other", category_id="other")))


class SimulatorTests(unittest.TestCase):
    def test_alignment_duration_and_invalid_duration(self):
        source = catalogue()
        game = SyntheticSimulator(source, SimulatorConfig(lapse=1))
        game.reset(42, 73)
        for key, duration in [('A', 12), ('B', 20)]:
            row = source.id_to_row[key]
            self.assertEqual(source.records[row].duration_seconds, duration)
            self.assertEqual(source.embeddings[row].argmax(), row)
            r = game.step(key)
            self.assertAlmostEqual(r.watch_duration, duration * r.watch_ratio)
            self.assertTrue(0 <= r.watch_duration <= duration)
            self.assertEqual(r.completed, r.watch_ratio == 1)
            self.assertEqual(r.incomplete_viewing, not r.completed)
            self.assertEqual(r.immediate_pass, r.watch_ratio == 0)
        invalid = replace(source, records=(replace(source.records[0], duration_seconds=float('nan')), source.records[1]))
        with self.assertRaisesRegex(ValueError, 'Invalid duration'):
            SyntheticSimulator(invalid)

    def test_seeded_profile_quality_and_public_boundary(self):
        game = SyntheticSimulator(catalogue())
        first = game.reset(42, 73)
        hidden = game._interest.copy()
        self.assertFalse(np.array_equal(hidden, first.onboarding_vector))
        self.assertEqual(first, game.reset(42, 73))
        np.testing.assert_array_equal(hidden, game._interest)
        self.assertEqual(game._quality, item_qualities(['B', 'A'], 73, None))
        self.assertEqual(item_qualities(['A', 'B'], 73, 0), {'A': 0, 'B': 0})
        r = game.step('A')
        self.assertEqual({f.name for f in fields(Observation)},
                         {'categories', 'onboarding_vector', 'category_exposure', 'affect_exposure'})
        self.assertEqual({f.name for f in fields(StepResult)},
                         {'video_id', 'watch_duration', 'watch_ratio', 'completed', 'immediate_pass',
                          'incomplete_viewing', 'episode_step', 'terminated', 'truncated', 'truncation_reason', 'observation'})
        game.reset(42, 73)
        with self.assertRaises(ValueError):
            game.step('Recovery-Oriented')
        self.assertEqual(r, game.step('A'))

    def test_seeded_trajectory_and_boundaries(self):
        game = SyntheticSimulator(catalogue(), SimulatorConfig(start_intercept=-1000))
        def run():
            game.reset(3, 8)
            return [game.step('A'), game.step('B')]
        first, last = run()
        self.assertEqual([first, last], run())
        self.assertTrue(first.immediate_pass)
        self.assertFalse(first.terminated or first.truncated)
        self.assertEqual(last.truncation_reason, 'catalogue_exhausted')
        self.assertFalse(last.terminated)
        with self.assertRaises(RuntimeError):
            game.step('B')
        short = SyntheticSimulator(catalogue(), SimulatorConfig(horizon=1))
        short.reset(3, 8)
        self.assertEqual(short.step('A').truncation_reason, 'horizon')

    def test_hidden_update_and_stationary_controls(self):
        for config, change in [(SimulatorConfig(start_intercept=-1000), False),
                               (SimulatorConfig(start_intercept=1000, interest_rate=0, transition_noise=0), False),
                               (SimulatorConfig(start_intercept=1000, quality_constant=1, transition_noise=0), True)]:
            game = SyntheticSimulator(catalogue(), config)
            game.reset(42, 73)
            before = game._interest.copy()
            game.step('A')
            self.assertEqual(change, not np.array_equal(before, game._interest))
            self.assertAlmostEqual(float(np.linalg.norm(game._interest)), 1)
            if change:
                embedding = game._catalogue.embeddings[game._catalogue.id_to_row['A']]
                self.assertGreater(game._interest @ embedding, before @ embedding)

    def test_repetition_growth_decay_and_null_effect(self):
        from research.recommendation.simulator.transition import update_exposure
        zero = np.zeros(2)
        category = np.array([1., 0.])
        first = update_exposure(zero, category, .5, .8)
        second = update_exposure(first, category, .5, .8)
        third = update_exposure(second, category[::-1], .5, .8)
        np.testing.assert_allclose([first[0], second[0], third[0]], [.1, .18, .144])
        cfg = SimulatorConfig(repetition_weight=0)
        self.assertEqual(start_probability(.5, 0, cfg), start_probability(.5, 1, cfg))
        self.assertEqual(completion_probability(.5, 0, 0, cfg), completion_probability(.5, 0, 1, cfg))
        sensitive = replace(cfg, repetition_weight=2)
        self.assertLess(start_probability(.5, 1, sensitive), start_probability(.5, 0, sensitive))
        game = SyntheticSimulator(catalogue(), replace(cfg, start_intercept=1000))
        game.reset(42, 73)
        self.assertGreater(sum(dict(game.step('A').observation.category_exposure).values()), 0)

    def test_outside_option_lapse_and_extreme_logits(self):
        cfg = SimulatorConfig(start_intercept=0)
        self.assertEqual(start_probability(0, 0, cfg), .5)
        self.assertAlmostEqual(start_probability(1, 0, cfg), np.exp(-2)/(1+np.exp(-2)))
        for intercept in (-1000, 1000):
            extreme = replace(cfg, start_intercept=intercept, watch_intercept=intercept)
            for params in [extreme, replace(extreme, lapse=1)]:
                for p in [start_probability(0, 0, params), completion_probability(0, 0, 0, params)]:
                    self.assertTrue(0 <= p <= 1)
                    if params.lapse == 1:
                        self.assertEqual(p, .5)

    def test_geometric_distribution_and_resolution(self):
        rng = np.random.default_rng(712)
        draws = rng.random(60000)
        chi = .37
        for units in (10, 20, 40):
            samples = np.array([watched_units(chi, units, u) for u in draws])
            p = chi ** (1/(units-1))
            self.assertTrue(np.all((1 <= samples) & (samples <= units)))
            self.assertAlmostEqual(np.mean(samples == units), chi, delta=.008)
            self.assertAlmostEqual(np.mean(samples == 1), 1-p, delta=.008)
            self.assertAlmostEqual(np.mean(samples >= units//2), p**(units//2-1), delta=.008)
        self.assertEqual(watched_units(0, 20, 0), 1)
        self.assertEqual(watched_units(1, 20, .99), 20)

    def test_recovery_annotations_change_exposure_only(self):
        source = catalogue()
        modified = replace(source, records=tuple(replace(r, recovery_suitability=1)
                                                   for r in source.records))
        config = SimulatorConfig(start_intercept=1000, watch_intercept=1000)
        original = SyntheticSimulator(source, config)
        changed = SyntheticSimulator(modified, config)
        self.assertEqual(original.reset(42, 73), changed.reset(42, 73))
        for video_id in ('A', 'B'):
            a, b = original.step(video_id), changed.step(video_id)
            self.assertEqual(a, replace(b, observation=a.observation))
            self.assertEqual(a.observation.category_exposure, b.observation.category_exposure)
            self.assertEqual(a.observation.affect_exposure[:-1], b.observation.affect_exposure[:-1])
            self.assertGreater(b.observation.affect_exposure[-1], a.observation.affect_exposure[-1])
            np.testing.assert_array_equal(original._interest, changed._interest)
            self.assertEqual(original._quality, changed._quality)

    def test_geometric_survival_cutoffs(self):
        # For chi=1/8 and J=4, the continuation probability is exactly 1/2.
        for draw, expected in [(.75, 1), (.375, 2), (.1875, 3), (.0625, 4)]:
            self.assertEqual(watched_units(.125, 4, draw), expected)

    def test_quality_sign_moves_affinity_in_opposite_directions(self):
        from research.recommendation.simulator.transition import update_interest

        interest = np.array([1., 0.])
        embedding = np.array([0., 1.])
        config = SimulatorConfig(transition_noise=0)
        rng = np.random.default_rng(42)
        for quality in (-1, 1):
            next_interest = update_interest(interest, embedding, quality, True, config, rng)
            self.assertGreater(quality * (next_interest @ embedding), 0)
            self.assertAlmostEqual(np.linalg.norm(next_interest), 1)
